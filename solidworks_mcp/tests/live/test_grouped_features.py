"""Sequential live checks sharing a single solid body and saved part.

The numbered tests intentionally share model state. Run the whole class, not
individual methods: each operation has its own reported test and checkpoint.
"""

import math
import os
import unittest
from pathlib import Path
from uuid import uuid4

import pythoncom
import win32com.client

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.advanced_features import draft_faces, hole_wizard
from solidworks_mcp.tools.appearance import set_appearance
from solidworks_mcp.tools.body_features import delete_body, move_copy_body, scale_body
from solidworks_mcp.tools.configurations import create_configuration
from solidworks_mcp.tools.equations import add_equation
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.material import apply_material
from solidworks_mcp.tools.properties import set_custom_property
from solidworks_mcp.tools.reference_geometry import (
    create_coordinate_system,
    create_reference_axis,
    create_reference_plane,
)
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.surface_features import cut_with_surface, planar_surface


# Independent 3x3 matrix helpers so the coordinate-system checks below do not
# reuse the production rotation code they are meant to verify.
def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def _matmul3(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))


def _matvec3(a, v):
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))


def _transpose3(a):
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveGroupedSingleBodyTests(unittest.TestCase):
    """One part, initially a 100 x 100 x 40 mm body, then controlled copies."""

    @classmethod
    def setUpClass(cls):
        cls.automation = SolidWorksAutomation()
        cls.title = None
        cls.stage = 0
        cls.path = None
        result = cls.automation.connect()
        if not result["success"]:
            raise unittest.SkipTest(result["message"])
        try:
            result = cls.automation.create_new_part()
            if not result["success"]:
                raise AssertionError(result["message"])
            cls.title = result["data"]["name"]
            for result in (cls.automation.create_sketch("Front", exact_geometry=True),
                           cls.automation.draw_rectangle(-50, -50, 50, 50, "mm"),
                           cls.automation.extrude_sketch(40, False, "mm")):
                if not result["success"]:
                    raise AssertionError(result["message"])
            root = Path(cls.automation._path_policy.output_roots[0]) / "saved"
            cls.path = root / f"mcp_live_grouped_edges_hole_{uuid4().hex}.SLDPRT"
        except BaseException:
            cls._close_and_disconnect()
            raise

    @classmethod
    def _close_and_disconnect(cls):
        try:
            if cls.title is not None:
                cls.automation.app.CloseDoc(cls.title)
        finally:
            cls.automation.disconnect()

    @classmethod
    def tearDownClass(cls):
        try:
            # Preserve the diagnostic model even when an earlier stage fails.
            if cls.title is not None and cls.path is not None:
                saved = save_document(cls.automation, path=str(cls.path))
                if not saved["success"]:
                    raise AssertionError(saved["message"])
                # SaveAs renames the document; track the new title so the
                # finally-block closes it instead of leaking the window.
                cls.title = cls.path.stem
                if cls.path.stat().st_size == 0:
                    raise AssertionError("Shared part was saved empty.")
        finally:
            cls._close_and_disconnect()

    def _volume(self):
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        bodies = com(part, "GetBodies2", 0, True) or []
        self.assertEqual(1, len(bodies))
        return com(bodies[0], "GetMassProperties", 0.0)[3] * 1e9

    def _bodies(self):
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return com(part, "GetBodies2", 0, True) or []

    def _total_volume(self):
        return sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                   for body in self._bodies())

    def _require_stage(self, stage):
        if type(self).stage != stage:
            self.skipTest(f"Earlier operation did not reach checkpoint {stage}.")

    def test_00_fillet_rejects_point_off_edge(self):
        before = self._volume()
        result = self.automation.fillet_edges(5, "mm", edge_points=[[20, 0, 0]])
        self.assertFalse(result["success"])
        self.assertEqual("SELECTION_EMPTY", result["data"]["code"])
        self.assertAlmostEqual(before, self._volume(), delta=.01)

    def test_01_fillet_removes_expected_volume(self):
        before = self._volume()
        self.assertAlmostEqual(400000, before, delta=0.1)
        result = self.automation.fillet_edges(5, "mm", edge_points=[[20, 50, 50]])
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(before - self._volume(),
                               (25 - math.pi * 25 / 4) * 40, delta=0.05)
        type(self).stage = 1

    def test_02_chamfer_removes_expected_volume(self):
        self._require_stage(1)
        before = self._volume()
        result = self.automation.chamfer_edges(5, 45, "mm",
                                               edge_points=[[20, 50, -50]])
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(before - self._volume(), 5 * 5 / 2 * 40, delta=0.05)
        type(self).stage = 2

    def test_03_hole_wizard_removes_volume(self):
        self._require_stage(2)
        before = self._volume()
        faces = list_planar_faces(self.automation)
        self.assertTrue(faces["success"], faces["message"])
        cap = next((face for face in faces["data"]["faces"]
                    if face["normal"][0] > 0.9
                    and abs(face["point_mm"][0] - 40) < 0.1
                    and face["area_mm2"] > 9000), None)
        self.assertIsNotNone(cap, "Extrusion cap not found after edge treatments.")
        result = hole_wizard(self.automation, cap["index"], [40, 0, 0], 6, 8)
        self.assertTrue(result["success"], result["message"])
        after = self._volume()
        self.assertLess(after, before - 10)
        type(self).hole_removed = before - after
        type(self).stage = 3

    def test_04_reference_axis_does_not_change_volume(self):
        self._require_stage(3)
        before = self._volume()
        result = create_reference_axis(self.automation, "Front Plane", "Top Plane")
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(before, self._volume(), delta=0.01)
        type(self).stage = 4

    def test_05_custom_properties_in_both_scopes(self):
        self._require_stage(4)
        before = self._volume()
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        config = str(com(com(part, "ConfigurationManager"), "ActiveConfiguration").Name)
        first = set_custom_property(self.automation, "MCP_Document", "DOCUMENT_42")
        self.assertTrue(first["success"], first["message"])
        second = set_custom_property(self.automation, "MCP_Config", "CONFIG_19",
                                     configuration=config)
        self.assertTrue(second["success"], second["message"])
        self.assertEqual("DOCUMENT_42", first["data"]["read_back"])
        self.assertEqual("CONFIG_19", second["data"]["read_back"])
        self.assertAlmostEqual(before, self._volume(), delta=0.01)
        type(self).stage = 5

    def test_06_configuration_keeps_body_geometry(self):
        self._require_stage(5)
        before = self._volume()
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        first_config = str(com(com(part, "ConfigurationManager"), "ActiveConfiguration").Name)
        result = create_configuration(self.automation, "MCP_TEST_VARIANT",
                                      comment="MCP live", description="test configuration",
                                      activate=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("MCP_TEST_VARIANT", result["data"]["read_back"]["name"])
        self.assertTrue(result["data"]["active"])
        self.assertAlmostEqual(before, self._volume(), delta=0.01)
        duplicate = create_configuration(self.automation, "MCP_TEST_VARIANT")
        self.assertFalse(duplicate["success"])
        self.assertEqual("CONFIGURATION_EXISTS", duplicate["data"]["code"])
        self.assertIsNotNone(com(part, "GetConfigurationByName", first_config))
        type(self).stage = 6

    def test_07_equation_round_trips_without_volume_change(self):
        self._require_stage(6)
        before = self._volume()
        result = add_equation(self.automation, "MCP_Width", 20)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("verified", result["data"]["status"])
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        manager = com(part, "GetEquationMgr")
        self.assertTrue(com(manager, "GlobalVariable", result["data"]["index"]))
        self.assertIn('"MCP_Width"', com(manager, "Equation", result["data"]["index"]))
        self.assertAlmostEqual(before, self._volume(), delta=0.01)
        type(self).stage = 7

    def test_08_appearance_preserves_geometry(self):
        self._require_stage(7)
        before = self._volume()
        result = set_appearance(self.automation, 0.2, 0.5, 0.8)
        self.assertTrue(result["success"], result["message"])
        self.assertTrue(all(abs(actual - value) < 1 / 255 + 1e-6
                            for actual, value in zip(result["data"]["rgb"], (0.2, 0.5, 0.8))))
        self.assertAlmostEqual(before, self._volume(), delta=0.01)
        type(self).stage = 8

    def test_09_move_body_preserves_volume(self):
        self._require_stage(8)
        before = self._volume()
        result = move_copy_body(self.automation, 0, 0, 150, 0)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(result["data"]["box_after_m"][1] -
                               result["data"]["box_before_m"][1], .15, delta=1e-4)
        self.assertAlmostEqual(before, self._volume(), delta=1)
        type(self).stage = 9

    def test_10_copy_body_adds_one_body(self):
        self._require_stage(9)
        before = self._volume()
        result = move_copy_body(self.automation, 0, 0, 150, 0, copy=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(2, len(self._bodies()))
        self.assertAlmostEqual(before * 2, self._total_volume(), delta=1)
        self.assertAlmostEqual(result["data"]["box_after_m"][1] -
                               result["data"]["box_before_m"][1], .15, delta=1e-4)
        type(self).stage = 10

    def test_11_scale_one_body_octuples_its_volume(self):
        self._require_stage(10)
        bodies = self._bodies()
        before = [com(body, "GetMassProperties", 0.0)[3] * 1e9 for body in bodies]
        # Choose the body at y=150 mm, not the copied one at y=300 mm.
        index = min(range(len(bodies)), key=lambda i: com(bodies[i], "GetBodyBox")[1])
        box = com(bodies[index], "GetBodyBox")
        result = scale_body(self.automation, index, 2, origin="centroid")
        self.assertTrue(result["success"], result["message"])
        after = [com(body, "GetMassProperties", 0.0)[3] * 1e9 for body in self._bodies()]
        self.assertEqual(2, len(after))
        self.assertAlmostEqual(sum(after), sum(before) + before[index] * 7, delta=1)
        scaled = next(body for body in self._bodies()
                      if abs(com(body, "GetMassProperties", 0.0)[3] * 1e9 - before[index] * 8) < 1)
        scaled_box = com(scaled, "GetBodyBox")
        for axis in range(3):
            self.assertAlmostEqual(scaled_box[axis + 3] - scaled_box[axis],
                                   2 * (box[axis + 3] - box[axis]), delta=1e-4)
        type(self).stage = 11

    def test_12_delete_only_selected_body(self):
        self._require_stage(11)
        bodies = self._bodies()
        before = self._total_volume()
        index = max(range(len(bodies)), key=lambda i: com(bodies[i], "GetMassProperties", 0.0)[3])
        removed = com(bodies[index], "GetMassProperties", 0.0)[3] * 1e9
        result = delete_body(self.automation, index)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(self._volume(), before - removed, delta=1)
        type(self).stage = 12

    def test_13_keep_only_selected_body(self):
        self._require_stage(12)
        result = move_copy_body(self.automation, 0, 0, 150, 0, copy=True)
        self.assertTrue(result["success"], result["message"])
        bodies = self._bodies()
        self.assertEqual(2, len(bodies))
        before = self._total_volume()
        index = max(range(len(bodies)), key=lambda i: com(bodies[i], "GetBodyBox")[1])
        kept = com(bodies[index], "GetMassProperties", 0.0)[3] * 1e9
        result = delete_body(self.automation, index, keep_only=True)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(self._volume(), kept, delta=1)
        self.assertAlmostEqual(before, kept * 2, delta=1)
        type(self).stage = 13

    def test_14_scale_body_about_origin_octuples_volume(self):
        self._require_stage(13)
        body = self._bodies()[0]
        before_box = com(body, "GetBodyBox")
        before = self._volume()
        result = scale_body(self.automation, 0, 2, origin="origin")
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(self._volume(), before * 8, delta=1)
        after_box = com(self._bodies()[0], "GetBodyBox")
        for axis in range(3):
            self.assertAlmostEqual(after_box[axis + 3] - after_box[axis],
                                   2 * (before_box[axis + 3] - before_box[axis]), delta=1e-4)
        type(self).stage = 14

    def test_15_cut_with_surface_halves_remaining_body(self):
        self._require_stage(14)
        before = self._volume()
        box = com(self._bodies()[0], "GetBodyBox")
        middle_x = (box[0] + box[3]) * 500  # meters to millimeters / 2
        plane = create_reference_plane(self.automation, "Front Plane", middle_x, "mm")
        self.assertTrue(plane["success"], plane["message"])
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        com(part, "ClearSelection2", True)
        selected = com(com(part, "Extension"), "SelectByID2", "Plane1", "PLANE",
                       0., 0., 0., False, 0, empty, 0)
        self.assertTrue(selected)
        com(part, "InsertSketch2", True)
        rectangle = self.automation.draw_rectangle(box[1] * 1000 - 10,
                                                   box[2] * 1000 - 10,
                                                   box[4] * 1000 + 10,
                                                   box[5] * 1000 + 10, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        com(part, "InsertSketch2", True)
        last = None
        feature = com(part, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "ProfileFeature":
                last = str(com(feature, "Name"))
            feature = com(feature, "GetNextFeature")
        self.assertIsNotNone(last)
        surface = planar_surface(self.automation, last)
        self.assertTrue(surface["success"], surface["message"])
        cut = cut_with_surface(self.automation, surface["data"]["feature_name"])
        self.assertTrue(cut["success"], cut["message"])
        # The blind hole is on the far cap: two half-blocks differ by the
        # hole's volume (scaled 2x in each of the three dimensions).
        self.assertAlmostEqual(abs(self._volume() - before / 2),
                               4 * type(self).hole_removed, delta=1)
        type(self).stage = 15

    def _draft_remote_box(self, center, flip):
        initial_count = len(self._bodies())
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(center - 50, -50,
                                                   center + 50, 50, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extruded = self.automation.extrude_sketch(40, False, "mm")
        self.assertTrue(extruded["success"], extruded["message"])
        bodies = self._bodies()
        self.assertEqual(initial_count + 1, len(bodies))
        index = next(i for i, body in enumerate(bodies)
                     if abs(com(body, "GetBodyBox")[1] - (center - 50) / 1000) < .001)
        faces = list_planar_faces(self.automation)
        self.assertTrue(faces["success"], faces["message"])
        selected = [face for face in faces["data"]["faces"] if face["body_index"] == index]
        caps = [face["index"] for face in selected if round(face["area_mm2"]) == 10000]
        sides = [face["index"] for face in selected if round(face["area_mm2"]) == 4000]
        self.assertEqual((2, 4), (len(caps), len(sides)))
        before = self._total_volume()
        result = draft_faces(self.automation, 5, caps[0], sides, flip=flip)
        self.assertTrue(result["success"], result["message"])
        slope = 2 * math.tan(math.radians(5))
        expected = (40 * 100 ** 2 + (-1 if flip else 1) * 40 ** 2 * 100 * slope
                    + slope ** 2 * 40 ** 3 / 3)
        self.assertAlmostEqual(expected - 400000,
                               self._total_volume() - before, delta=1)

    def test_16_draft_remote_box_outward(self):
        self._require_stage(15)
        self._draft_remote_box(1200, flip=False)
        type(self).stage = 16

    def test_17_draft_remote_box_inward(self):
        self._require_stage(16)
        self._draft_remote_box(1500, flip=True)
        type(self).stage = 17

    def test_18_material_sets_density_and_mass(self):
        self._require_stage(17)
        database = Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english"
                        r"\sldmaterials\solidworks materials.sldmat")
        self.assertTrue(database.is_file(), f"Required material database missing: {database}")
        before_volume = self._total_volume()
        result = apply_material(self.automation, "Plain Carbon Steel", str(database))
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("Plain Carbon Steel", result["data"]["name"])
        self.assertAlmostEqual(7800, result["data"]["density_kg_m3"], delta=1)
        self.assertAlmostEqual(result["data"]["mass_after_kg"],
                               result["data"]["volume_m3"] * 7800, delta=1e-5)
        self.assertAlmostEqual(before_volume, self._total_volume(), delta=1)
        # Applying a library material replaces the document-level appearance.
        # Restore the tested RGB so the saved document verifies both properties.
        appearance = set_appearance(self.automation, 0.2, 0.5, 0.8)
        self.assertTrue(appearance["success"], appearance["message"])
        self.assertAlmostEqual(before_volume, self._total_volume(), delta=1)
        type(self).stage = 18

    def test_18b_coordinate_system_origin_and_orientation(self):
        self._require_stage(18)
        before = self._total_volume()
        result = create_coordinate_system(
            self.automation, x_offset=10, y_offset=-5, z_offset=2, unit="mm",
            rotate_z=30, name="MCP_Frame")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("MCP_Frame", result["data"]["feature_name"])
        self.assertAlmostEqual(10.0, result["data"]["origin"][0], places=4)
        self.assertAlmostEqual(-5.0, result["data"]["origin"][1], places=4)
        self.assertAlmostEqual(2.0, result["data"]["origin"][2], places=4)
        angle = math.radians(30)
        axes = result["data"]["axes"]
        self.assertAlmostEqual(math.cos(angle), axes[0][0], places=6)
        self.assertAlmostEqual(-math.sin(angle), axes[0][1], places=6)
        self.assertAlmostEqual(math.sin(angle), axes[1][0], places=6)
        self.assertAlmostEqual(math.cos(angle), axes[1][1], places=6)
        self.assertAlmostEqual(1.0, axes[2][2], places=6)
        determinant = (
            axes[0][0] * (axes[1][1] * axes[2][2] - axes[1][2] * axes[2][1])
            - axes[0][1] * (axes[1][0] * axes[2][2] - axes[1][2] * axes[2][0])
            + axes[0][2] * (axes[1][0] * axes[2][1] - axes[1][1] * axes[2][0])
        )
        self.assertAlmostEqual(1.0, determinant, places=6)
        rotated = create_coordinate_system(self.automation, rotate_z=90,
                                           name="MCP_Frame_Rot")
        self.assertTrue(rotated["success"], rotated["message"])
        for value in rotated["data"]["origin"]:
            self.assertAlmostEqual(0.0, value, places=4)
        self.assertAlmostEqual(before, self._total_volume(), delta=0.01)
        type(self).stage = 19

    def test_18c_coordinate_system_combined_rotation_and_offset(self):
        self._require_stage(19)
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        before = self._total_volume()
        offsets = (7.0, -3.0, 11.0)
        angles_deg = (20.0, -35.0, 50.0)
        angles = tuple(math.radians(value) for value in angles_deg)

        # Independent expectation: SolidWorks applies Rx @ Ry @ Rz to the part
        # axes. Assembled here, not via the production helper.
        expected = _matmul3(_matmul3(_rx(angles[0]), _ry(angles[1])), _rz(angles[2]))

        result = create_coordinate_system(
            self.automation, x_offset=offsets[0], y_offset=offsets[1],
            z_offset=offsets[2], unit="mm",
            rotate_x=angles_deg[0], rotate_y=angles_deg[1], rotate_z=angles_deg[2],
            name="MCP_Frame_Combined")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("MCP_Frame_Combined", result["data"]["feature_name"])

        # Read the transform straight from COM instead of trusting the helper.
        transform = com(part, "GetCoordinateSystemXformByName", "MCP_Frame_Combined")
        self.assertIsNotNone(transform)
        values = [float(value) for value in transform]
        axes = [values[0:3], values[3:6], values[6:9]]
        translation = values[9:12]
        for row, expected_row in zip(axes, expected):
            for value, expected_value in zip(row, expected_row):
                self.assertAlmostEqual(expected_value, value, places=6)

        # Origin from the raw transform: O = -M^T @ t, independent of the helper.
        origin_m = [-value for value in _matvec3(_transpose3(axes), translation)]
        for value, offset in zip(origin_m, offsets):
            self.assertAlmostEqual(offset / 1000.0, value, places=9)
        # The helper's reported origin/axes must match the same expectation.
        for value, offset in zip(result["data"]["origin"], offsets):
            self.assertAlmostEqual(offset, value, places=6)
        for row, expected_row in zip(result["data"]["axes"], expected):
            for value, expected_value in zip(row, expected_row):
                self.assertAlmostEqual(expected_value, value, places=6)

        self.assertAlmostEqual(before, self._total_volume(), delta=0.01)
        type(self).stage = 20

    def test_19_save_and_close_shared_part(self):
        self._require_stage(20)
        saved = save_document(self.automation, path=str(self.path))
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(self.path.stat().st_size, 0)
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        self.assertAlmostEqual(com(part, "GetMassProperties", 0.0)[5] /
                               com(part, "GetMassProperties", 0.0)[3], 7800, delta=1)
        self.assertTrue(all(abs(com(part, "MaterialPropertyValues")[i] - value) < 1 / 255 + 1e-6
                            for i, value in enumerate((0.2, 0.5, 0.8))))
        title = str(com(part, "GetTitle"))
        self.automation.app.CloseDoc(title)
        type(self).title = None
        documents = self.automation.list_open_documents()
        self.assertTrue(documents["success"], documents["message"])
        self.assertNotIn(title, [d["title"] for d in documents["data"]["documents"]])
