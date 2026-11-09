import math
import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

import pythoncom
import win32com.client

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.constants import SwDocumentTypes
from solidworks_mcp.core.session import TargetMismatchError
from solidworks_mcp.tools.assembly import (
    insert_component, list_component_faces, list_components, list_mates,
    mate_coincident, mate_concentric, mate_distance,
)
from solidworks_mcp.tools.inspection import inspect_document
from solidworks_mcp.tools.advanced_features import (
    boundary_boss, boundary_cut, loft_cut, loft_sketches, revolve_cut, rib, shell_feature, sweep_cut, sweep_sketch,
)
from solidworks_mcp.tools.drawing_annotations import auto_balloon, insert_marked_dimensions
from solidworks_mcp.tools.drawings import add_standard_3_view, insert_cut_list_table, list_drawing_views
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tests.live._scratch import (close_new_documents,
                                                open_document_titles)
from solidworks_mcp.tools.sheetmetal import (
    create_sheet_metal_base_flange, export_flat_pattern,
    flatten_sheet_metal, get_flat_pattern_info, get_sheet_metal_info,
)
from solidworks_mcp.tools.weldments import create_structural_member, list_weldment_profiles
from solidworks_mcp.tools.export import (
    export_face_to_dxf, export_step, export_stl, list_planar_faces,
)
from solidworks_mcp.tools.history import redo, undo
from solidworks_mcp.tools.inspection import list_planes
from solidworks_mcp.tools.patterns import mirror_feature
from solidworks_mcp.tools.reference_geometry import create_reference_plane
from solidworks_mcp.tools.sketch_entities import draw_centerline, draw_circle_radius
from solidworks_mcp.tools.views import capture_view


@unittest.skipUnless(
    os.environ.get("SW_MCP_LIVE_TESTS") == "1",
    "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.",
)
class LiveDocumentTargetTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.created_titles = []
        self.created_artifacts = []
        self.baseline_titles = open_document_titles(self.automation)

    def tearDown(self):
        for title in reversed(self.created_titles):
            try:
                self.automation.app.CloseDoc(title)
            except Exception:
                pass
        close_new_documents(self.automation, self.baseline_titles)
        for path in self.created_artifacts:
            Path(path).unlink(missing_ok=True)
        self.automation.disconnect()

    def _new_part(self):
        result = self.automation.create_new_part()
        self.assertTrue(result["success"], result["message"])
        title = result["data"]["name"]
        self.created_titles.append(title)
        return title

    def _top_level_feature_types(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        types = []
        feature = com(document, "FirstFeature")
        retained = []
        while feature is not None:
            retained.append(feature)
            types.append(com(feature, "GetTypeName2"))
            feature = com(feature, "GetNextFeature")
        return types

    def test_focus_change_rejects_old_target_until_explicit_rebind(self):
        first_title = self._new_part()
        first = self.automation.bind_active_document()
        second_title = self._new_part()

        with self.assertRaises(TargetMismatchError) as raised:
            self.automation.require_bound_active_document()

        self.assertEqual("WRONG_DOCUMENT", raised.exception.operation_error.code)
        second = self.automation.bind_active_document()
        current = self.automation.require_bound_active_document()
        self.assertEqual(second.document_id, current.document_id)
        self.assertNotEqual(first.document_id, second.document_id)
        self.assertNotEqual(first_title, second_title)
        self.assertIsNone(first.path)
        self.assertIsNone(second.path)

    def test_two_connections_remain_on_the_same_com_owner_thread(self):
        owner = self.automation._com_owner_thread_id

        result = self.automation.connect()

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(owner, self.automation._com_owner_thread_id)

    def test_inspect_unsaved_part_returns_versioned_summary_without_saving(self):
        self._new_part()

        result = inspect_document(self.automation, sections=["summary"])

        self.assertTrue(result["success"], result["message"])
        snapshot = result["data"]["snapshot"]
        self.assertEqual("part", snapshot["documents"][0]["document_type"])
        self.assertIsNone(snapshot["documents"][0]["path"])
        self.assertEqual("known", snapshot["observations"][0]["state"])

    def test_inspect_scratch_extrusion_preserves_live_feature_tree(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -10, 20, 10, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(8, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])

        result = inspect_document(
            self.automation, sections=["features", "parameters"], depth=6
        )

        self.assertTrue(result["success"], result["message"])
        observations = result["data"]["snapshot"]["observations"]
        feature_types = [item["type"] for item in observations[0]["value"]]
        self.assertIn("Extrusion", feature_types)

    def test_inspect_unsaved_part_dependencies_uses_compatibility_fallback(self):
        self._new_part()

        result = inspect_document(self.automation, sections=["dependencies"])

        self.assertTrue(result["success"], result["message"])
        snapshot = result["data"]["snapshot"]
        self.assertEqual([], snapshot["dependency_edges"])
        self.assertEqual(
            "IModelDoc2.GetDependencies2",
            snapshot["observations"][0]["source"],
            snapshot["observations"][0],
        )
        self.assertIn(
            "fallback",
            snapshot["observations"][0]["value"]["evidence"][0].lower(),
        )

    def test_capture_scratch_part_returns_real_png_without_saving_model(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -10, 20, 10, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(8, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])

        document, document_error = self.automation.get_active_doc()
        self.assertIsNone(document_error)
        feature = com(document, "FirstFeature")
        sketch_segment_count = None
        retained = []
        while feature is not None:
            retained.append(feature)
            if com(feature, "GetTypeName2") == "ProfileFeature":
                sketch = com(feature, "GetSpecificFeature2")
                sketch_segment_count = len(com(sketch, "GetSketchSegments") or [])
            feature = com(feature, "GetNextFeature")
        self.assertEqual(4, sketch_segment_count)
        com(document, "ClearSelection2", True)

        result = capture_view(
            self.automation, orientation="isometric", width=640, height=480
        )

        self.assertTrue(result["success"], result["message"])
        artifact = result["data"]["artifact"]
        if os.environ.get("SW_MCP_KEEP_CAPTURE") == "1":
            print(f"CAPTURE_PATH={artifact['path']}")
        else:
            self.created_artifacts.append(artifact["path"])
        self.assertEqual(b"\x89PNG\r\n\x1a\n", Path(artifact["path"]).read_bytes()[:8])
        self.assertEqual([640, 480], artifact["pixel_size"])
        self.assertEqual([], result["data"]["restore_warnings"])
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_export_scratch_part_to_step_and_stl_without_saving_native_model(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -10, 20, 10, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(8, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        output_root = self.automation._path_policy.output_roots[0] / "exports"
        stem = f"scratch-{uuid4().hex}"
        step_path = output_root / f"{stem}.step"
        stl_path = output_root / f"{stem}.stl"
        self.created_artifacts.extend((str(step_path), str(stl_path)))

        step_result = export_step(self.automation, str(step_path))
        stl_result = export_stl(self.automation, str(stl_path))

        self.assertTrue(step_result["success"], step_result["message"])
        self.assertTrue(stl_result["success"], stl_result["message"])
        self.assertGreater(step_path.stat().st_size, 0)
        self.assertGreater(stl_path.stat().st_size, 0)
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_undo_and_redo_restore_a_scratch_extrusion_without_saving(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -10, 20, 10, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(8, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        self.assertIn("Extrusion", self._top_level_feature_types())

        undo_result = undo(self.automation)
        self.assertTrue(undo_result["success"], undo_result["message"])
        self.assertNotIn("Extrusion", self._top_level_feature_types())

        redo_result = redo(self.automation)
        self.assertTrue(redo_result["success"], redo_result["message"])
        self.assertIn("Extrusion", self._top_level_feature_types())
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_create_offset_reference_plane_on_scratch_part_without_saving(self):
        self._new_part()
        before = list_planes(self.automation)
        self.assertTrue(before["success"], before["message"])

        result = create_reference_plane(
            self.automation, "Front Plane", 25, "mm"
        )

        self.assertTrue(result["success"], result["message"])
        after = list_planes(self.automation)
        self.assertTrue(after["success"], after["message"])
        self.assertEqual(
            len(before["data"]["planes"]) + 1,
            len(after["data"]["planes"]),
        )
        self.assertEqual("reference", after["data"]["planes"][-1]["kind"])
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def _feature_name_by_type(self, fragment):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        feature = com(document, "FirstFeature")
        retained = []
        while feature is not None:
            retained.append(feature)
            if fragment.casefold() in com(feature, "GetTypeName2").casefold():
                return com(feature, "Name")
            feature = com(feature, "GetNextFeature")
        return None

    def _solid_body_count(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return len(com(document, "GetBodies2", 0, True) or [])

    def _solid_body_count(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return len(com(document, "GetBodies2", 0, True) or [])

    def _sketch_names(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        names = []
        retained = []
        feature = com(document, "FirstFeature")
        while feature is not None:
            retained.append(feature)
            if com(feature, "GetTypeName2") == "ProfileFeature":
                names.append(com(feature, "Name"))
            feature = com(feature, "GetNextFeature")
        return names

    def _close_sketch(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        com(document, "InsertSketch2", True)

    def _sketch_on_plane(self, plane_name):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        com(document, "ClearSelection2", True)
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        selected = com(document.Extension, "SelectByID2", plane_name, "PLANE",
                       0.0, 0.0, 0.0, False, 0, empty, 0)
        self.assertTrue(selected, f"Could not select plane {plane_name}")
        com(document, "InsertSketch2", True)

    def _total_volume_mm3(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        total = 0.0
        retained = []
        for body in com(document, "GetBodies2", 0, True) or []:
            retained.append(body)
            total += com(body, "GetMassProperties", 0.0)[3] * 1e9
        return total

    def _find_feature_type(self, document, type_name):
        feature = com(document, "FirstFeature")
        retained = []
        while feature is not None:
            retained.append(feature)
            if com(feature, "GetTypeName2") == type_name:
                return com(feature, "Name")
            feature = com(feature, "GetNextFeature")
        return None

    def _last_sketch_name(self, document):
        name = None
        retained = []
        feature = com(document, "FirstFeature")
        while feature is not None:
            retained.append(feature)
            if com(feature, "GetTypeName2") == "ProfileFeature":
                name = com(feature, "Name")
            feature = com(feature, "GetNextFeature")
        return name

    def _segment_lengths(self, sketch_name):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        retained = []
        feature = com(document, "FirstFeature")
        while feature is not None:
            retained.append(feature)
            if com(feature, "Name") == sketch_name:
                sketch = com(feature, "GetSpecificFeature2")
                lengths = []
                for segment in com(sketch, "GetSketchSegments") or []:
                    retained.append(segment)
                    lengths.append(round(com(segment, "GetLength") * 1000, 3))
                return lengths
            feature = com(feature, "GetNextFeature")
        return None

    def _new_saved_cylinder(self, radius_mm, height_mm, filename):
        root = Path(self.automation._path_policy.output_roots[0])
        path = root / "saved" / filename
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        circle = self.automation.draw_circle(0, 0, radius_mm, "mm")
        self.assertTrue(circle["success"], circle["message"])
        self._close_sketch()
        extrusion = self.automation.extrude_sketch(height_mm, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        saved = save_document(self.automation, path=str(path))
        self.assertTrue(saved["success"], saved["message"])
        self.created_titles.append(str(com(document, "GetTitle")))
        return str(path)

    def _mate_count(self):
        result = list_mates(self.automation)
        self.assertTrue(result["success"], result["message"])
        return len(result["data"]["mates"])

    def _component_face_index(self, component_name, kind):
        result = list_component_faces(self.automation, component_name)
        self.assertTrue(result["success"], result["message"])
        for face in result["data"]["faces"]:
            if face["kind"] == kind:
                return face["index"]
        return None

    def _new_drawing(self, paper_size="A4"):
        result = self.automation.create_new_drawing(paper_size)
        self.assertTrue(result["success"], result["message"])
        title = result["data"]["name"]
        self.created_titles.append(title)
        return title

    def _model_view_name(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        retained = []
        view = com(document, "GetFirstView")
        while view is not None:
            retained.append(view)
            view = com(view, "GetNextView")
        for view in retained:
            if com(view, "ReferencedDocument") is not None:
                return com(view, "GetName2")
        return None

    def _new_part_with_extrusion(self):
        part_title = self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-5, -5, 5, 5, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        self._close_sketch()
        extrusion = self.automation.extrude_sketch(10, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        return part_title

    def _new_saved_part_with_extrusion(self, stem):
        """A rectangle + extrusion saved to the approved output root.

        A drawing view needs a referenced document that exists on disk;
        SolidWorks reports success from Create3rdAngleViews2 but creates no
        view for an unsaved part, so the part must be saved first.
        """
        self._new_part_with_extrusion()
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        path = (Path(self.automation._path_policy.output_roots[0]) / "saved" /
                f"{stem}_{uuid4().hex}.SLDPRT")
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = save_document(self.automation, path=str(path))
        self.assertTrue(saved["success"], saved["message"])
        title = str(com(part, "GetTitle"))
        return title

    def _close_saved_part_test(self, drawing_title, part_title):
        # The saved part is kept as an output artifact, like the other live
        # tests; only the open windows are closed here. Close the drawing first
        # because it references the part.
        self.automation.app.CloseDoc(drawing_title)
        self.created_titles = [item for item in self.created_titles
                               if item not in (drawing_title, part_title)]
        self.automation.app.CloseDoc(part_title)

    def test_assembly_insert_components_and_mate_without_saving(self):
        path_a = self._new_saved_cylinder(10.0, 20.0, "mcp_live_asm_a.SLDPRT")
        path_b = self._new_saved_cylinder(6.0, 20.0, "mcp_live_asm_b.SLDPRT")
        path_c = self._new_saved_cylinder(8.0, 20.0, "mcp_live_asm_c.SLDPRT")

        created = self.automation.create_new_assembly()
        self.assertTrue(created["success"], created["message"])
        self.created_titles.append(created["data"]["name"])

        names = []
        for index, path in enumerate((path_a, path_b, path_c)):
            inserted = insert_component(self.automation, path, 0.04 * index, 0.0, 0.0)
            self.assertTrue(inserted["success"], inserted["message"])
            names.append(inserted["data"]["name"])
        name_a, name_b, name_c = names

        components = list_components(self.automation)
        self.assertTrue(components["success"], components["message"])
        self.assertEqual(3, len(components["data"]["components"]))

        # A cylinder gives both a planar cap and a cylindrical wall, so the
        # same pair of components can carry a coincident and a concentric mate.
        coincident = mate_coincident(
            self.automation, name_a, self._component_face_index(name_a, "planar"),
            name_b, self._component_face_index(name_b, "planar"))
        self.assertTrue(coincident["success"], coincident["message"])

        # Indexes are only valid for the current model state, so re-read them.
        concentric = mate_concentric(
            self.automation, name_a, self._component_face_index(name_a, "cylindrical"),
            name_b, self._component_face_index(name_b, "cylindrical"))
        self.assertTrue(concentric["success"], concentric["message"])
        self.assertEqual(2, self._mate_count())

        distance = mate_distance(
            self.automation, name_a, self._component_face_index(name_a, "planar"),
            name_c, self._component_face_index(name_c, "planar"), 25.0)
        self.assertTrue(distance["success"], distance["message"])
        self.assertEqual(3, self._mate_count())

        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_sheet_metal_flat_pattern_flatten_and_export(self):
        root = Path(self.automation._path_policy.output_roots[0])
        part_path = root / "saved" / "mcp_live_sheetmetal_bend.SLDPRT"
        dxf_path = root / "saved" / "mcp_live_bend_flat_pattern.dxf"

        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_line(0, 0, 100, 0, "mm")["success"])
        flange = create_sheet_metal_base_flange(self.automation, 2.0,
                                               bend_radius_mm=1.0, width_mm=100.0)
        self.assertTrue(flange["success"], flange["message"])

        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)

        # Sheet metal always gets a Flat-Pattern feature, even with no bends.
        self.assertIsNotNone(self._find_feature_type(document, "FlatPattern"),
                             "No Flat-Pattern feature was created.")

        # Stateful flat-pattern reads are refused while the part is unsaved.
        refused = get_flat_pattern_info(self.automation)
        self.assertFalse(refused["success"])

        saved = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved["success"], saved["message"])
        self.created_titles.append(str(com(document, "GetTitle")))

        info = get_flat_pattern_info(self.automation)
        self.assertTrue(info["success"], info["message"])
        self.assertAlmostEqual(100.0, info["data"]["length_mm"], places=2)
        self.assertAlmostEqual(100.0, info["data"]["width_mm"], places=2)
        self.assertAlmostEqual(2.0, info["data"]["height_mm"], places=2)

        self.assertTrue(flatten_sheet_metal(self.automation, True)["success"])
        self.assertTrue(flatten_sheet_metal(self.automation, False)["success"])

        exported = export_flat_pattern(self.automation, str(dxf_path))
        self.assertTrue(exported["success"], exported["message"])
        self.assertGreater(dxf_path.stat().st_size, 0)

    def test_create_sheet_metal_base_flange_and_export_flat_pattern(self):
        root = Path(self.automation._path_policy.output_roots[0])
        part_path = root / "saved" / "mcp_live_sheetmetal_part.SLDPRT"
        dxf_path = root / "saved" / "mcp_live_flat_pattern.dxf"

        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_line(0, 0, 100, 0, "mm")["success"])

        result = create_sheet_metal_base_flange(self.automation, 2.0,
                                               bend_radius_mm=1.0, width_mm=100.0)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("Sheet-Metal1", result["data"]["sheet_metal_feature"])

        info = get_sheet_metal_info(self.automation)
        self.assertTrue(info["success"], info["message"])
        self.assertAlmostEqual(2.0, info["data"]["thickness_mm"], places=3)
        self.assertAlmostEqual(1.0, info["data"]["bend_radius_mm"], places=3)

        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        self.assertAlmostEqual(20000.0, self._total_volume_mm3(), delta=1.0)

        unsaved = export_flat_pattern(self.automation, str(dxf_path))
        self.assertFalse(unsaved["success"],
                         "An unsaved part must not silently fail the export.")
        self.assertEqual("UNSAVED_DOCUMENT", unsaved["data"]["code"])

        saved = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved["success"], saved["message"])
        self.created_titles.append(str(com(document, "GetTitle")))

        exported = export_flat_pattern(self.automation, str(dxf_path))
        self.assertTrue(exported["success"], exported["message"])
        self.assertTrue(dxf_path.is_file())
        self.assertGreater(dxf_path.stat().st_size, 0)

    def test_create_structural_member_on_scratch_part_without_saving(self):
        part_title = self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_line(0, 0, 100, 0, "mm")["success"])
        self.assertTrue(self.automation.draw_line(100, 0, 100, 60, "mm")["success"])
        self._close_sketch()

        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        sketch_name = self._last_sketch_name(document)
        self.assertIsNotNone(sketch_name, "No sketch feature was created.")

        packages = list_weldment_profiles(self.automation, filter="square tube")
        self.assertTrue(packages["success"], packages["message"])
        profiles = packages["data"]["profiles"]
        self.assertTrue(profiles, "No square tube weldment profile is available.")
        chosen = next(
            (item for item in profiles if item["folder"].casefold().startswith("iso")),
            profiles[0],
        )

        result = create_structural_member(self.automation, sketch_name, chosen["path"])

        self.assertTrue(result["success"], result["message"])
        types = []
        feature = com(document, "FirstFeature")
        retained = []
        while feature is not None:
            retained.append(feature)
            types.append(com(feature, "GetTypeName2"))
            feature = com(feature, "GetNextFeature")
        self.assertIn("WeldmentFeature", types, "Weldment folder feature was not created.")
        self.assertIn("WeldMemberFeat", types, "No structural member feature was created.")

        volumes = sorted(
            (com(body, "GetMassProperties", 0.0)[3] * 1e9
             for body in com(document, "GetBodies2", 0, True) or []),
            reverse=True,
        )
        self.assertEqual(2, len(volumes), "Expected one body per sketch segment.")
        self.assertGreater(volumes[0], 0)
        self.assertGreater(volumes[1], 0)
        self.assertAlmostEqual(100 / 60, volumes[0] / volumes[1], delta=0.05)

        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_save_part_and_drawing_with_views_into_output_root(self):
        root = Path(self.automation._path_policy.output_roots[0])
        part_path = root / "saved" / "mcp_live_pipeline_part.SLDPRT"
        drawing_path = root / "saved" / "mcp_live_pipeline_drawing.SLDDRW"

        part_title = self._new_part_with_extrusion()
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)

        saved_part = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved_part["success"], saved_part["message"])
        self.assertTrue(part_path.is_file())
        self.assertGreater(part_path.stat().st_size, 0)
        self.created_titles.append(str(com(part, "GetTitle")))

        self._new_drawing("A4")
        drawing, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        model_name = str(com(part, "GetTitle"))
        self.assertTrue(com(drawing, "Create3rdAngleViews2", model_name),
                        "Could not create the standard views for the saved part.")

        saved_drawing = save_document(self.automation, path=str(drawing_path))
        self.assertTrue(saved_drawing["success"], saved_drawing["message"])
        self.assertTrue(drawing_path.is_file())
        self.assertGreater(drawing_path.stat().st_size, 0)
        self.assertEqual("drawing", saved_drawing["data"]["document_type"])
        self.created_titles.append(str(com(drawing, "GetTitle")))

    def test_standard_views_and_cut_list_table_on_scratch_weldment(self):
        root = Path(self.automation._path_policy.output_roots[0]) / "saved"
        part_path = root / f"mcp_live_cutlist_{uuid4().hex}.SLDPRT"
        drawing_path = part_path.with_suffix(".SLDDRW")
        self._new_part()
        self.assertTrue(self.automation.create_sketch("Front", exact_geometry=True)["success"])
        self.assertTrue(self.automation.draw_line(0, 0, 100, 0, "mm")["success"])
        self._close_sketch()
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        profiles = list_weldment_profiles(self.automation, filter="square tube")
        self.assertTrue(profiles["success"], profiles["message"])
        self.assertTrue(profiles["data"]["profiles"])
        profile = profiles["data"]["profiles"][0]
        member = create_structural_member(
            self.automation, self._last_sketch_name(part), profile["path"]
        )
        self.assertTrue(member["success"], member["message"])
        saved = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved["success"], saved["message"])
        self.created_titles.append(str(com(part, "GetTitle")))

        self._new_drawing("A4")
        views = add_standard_3_view(self.automation, str(com(part, "GetTitle")))
        self.assertTrue(views["success"], views["message"])
        drawing, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        model_views = list_drawing_views(self.automation)
        self.assertTrue(model_views["success"], model_views["message"])
        self.assertGreaterEqual(len(model_views["data"]["views"]), 4)
        view_name = self._model_view_name()
        self.assertIsNotNone(view_name)
        result = insert_cut_list_table(self.automation, view_name)
        self.assertTrue(result["success"], result["message"])
        self.assertGreater(result["data"]["rows"], 1)
        self.assertGreater(result["data"]["columns"], 0)
        saved_drawing = save_document(self.automation, path=str(drawing_path))
        self.assertTrue(saved_drawing["success"], saved_drawing["message"])
        self.assertGreater(drawing_path.stat().st_size, 0)
        drawing_title = str(com(drawing, "GetTitle"))
        part_title = str(com(part, "GetTitle"))
        self.created_titles.append(drawing_title)
        self.automation.app.CloseDoc(drawing_title)
        self.automation.app.CloseDoc(part_title)
        open_documents = self.automation.list_open_documents()
        self.assertTrue(open_documents["success"])
        self.assertFalse({drawing_title, part_title} & {
            item["title"] for item in open_documents["data"]["documents"]
        })

    def test_rib_adds_solid_volume_and_saved_part_closes(self):
        root = Path(self.automation._path_policy.output_roots[0]) / "saved"
        part_path = root / f"mcp_live_rib_{uuid4().hex}.SLDPRT"
        sample = Path(r"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2025"
                      r"\samples\tutorial\api\block20.sldprt")
        if not sample.is_file():
            self.skipTest("SOLIDWORKS 2025 block20 sample not installed")
        root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample, part_path)
        opened = self.automation.open_document(str(part_path))
        self.assertTrue(opened["success"], opened["message"])
        self.created_titles.append(opened["data"]["name"])
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        extension = com(part, "Extension")
        selection_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        self.assertTrue(com(extension, "SelectByID2", "", "FACE",
                            -0.00878816842651986, 0.0396239999998897,
                            -0.0292468281514857, False, 1, selection_data, 0))
        com(part, "InsertFeatureShell", 0.00254, False)
        self.assertTrue(com(extension, "SelectByID2", "", "FACE",
                            0.00264031138414111, 0.028407059059532,
                            -0.0613970439424634, True, 0, selection_data, 0))
        self.assertTrue(com(extension, "SelectByID2", "", "FACE",
                            -0.059937899786064, 0.0277866864457792,
                            -0.00877977980189826, True, 1, selection_data, 0))
        plane = com(com(part, "FeatureManager"), "InsertRefPlane", 128, 0, 128, 0, 0, 0)
        self.assertIsNotNone(plane)
        com(part, "ClearSelection2", True)
        self.assertTrue(com(extension, "SelectByID2", "Plane1", "PLANE", 0, 0, 0,
                            False, 0, selection_data, 0))
        sketch_manager = com(part, "SketchManager")
        com(sketch_manager, "InsertSketch", True)
        for start, end in (
            ((-0.085797, 0.021082), (-0.03423, 0.035134)),
            ((-0.03423, 0.035134), (0.007726, 0.025357)),
            ((0.007726, 0.025357), (0.111514, 0.039624)),
        ):
            self.assertIsNotNone(com(sketch_manager, "CreateLine", *start, 0.0, *end, 0.0))
        com(part, "ClearSelection2", True)
        com(sketch_manager, "InsertSketch", True)
        com(part, "ClearSelection2", True)
        before = self._total_volume_mm3()
        sketch_name = self._last_sketch_name(part)
        result = rib(self.automation, sketch_name, thickness=2.54, unit="mm")
        self.assertTrue(result["success"], f'{result["message"]}; data={result.get("data")}; features={self._top_level_feature_types()}')
        self.assertGreater(self._total_volume_mm3(), before + 1)
        self.assertIn("Rib", self._top_level_feature_types())
        saved = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(part_path.stat().st_size, 0)
        self.automation.app.CloseDoc(opened["data"]["name"])
        open_documents = self.automation.list_open_documents()
        self.assertTrue(open_documents["success"])
        self.assertNotIn(
            opened["data"]["name"],
            [item["title"] for item in open_documents["data"]["documents"]],
        )

    def test_auto_balloon_scratch_drawing_view_without_saving(self):
        part_title = self._new_saved_part_with_extrusion("mcp_live_balloon_part")
        drawing_title = self._new_drawing("A4")
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        created = com(document, "Create3rdAngleViews2", part_title)
        self.assertTrue(created, "Could not create the standard views.")
        view_name = self._model_view_name()
        self.assertIsNotNone(view_name, "No model view was created.")

        result = auto_balloon(self.automation, view_name)

        self.assertTrue(result["success"], result["message"])
        self.assertGreaterEqual(result["data"]["balloons_added"] or 0, 1)
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)
        self._close_saved_part_test(drawing_title, part_title)

    def test_insert_marked_dimensions_imports_nothing_when_none_marked_without_saving(self):
        part_title = self._new_saved_part_with_extrusion("mcp_live_marked_part")
        drawing_title = self._new_drawing("A4")
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        created = com(document, "Create3rdAngleViews2", part_title)
        self.assertTrue(created, "Could not create the standard views.")
        view_name = self._model_view_name()
        self.assertIsNotNone(view_name, "No model view was created.")

        result = insert_marked_dimensions(self.automation, view_name)

        self.assertFalse(result["success"])
        self.assertEqual("NO_MARKED_DIMENSIONS", result["data"]["code"])
        self.assertEqual(0, result["data"]["dimensions_after"])
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)
        self._close_saved_part_test(drawing_title, part_title)

    def test_sweep_scratch_profile_along_path_without_saving(self):
        self._new_part()
        profile = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(profile["success"], profile["message"])
        circle = self.automation.draw_circle(0, 0, 2, "mm")
        self.assertTrue(circle["success"], circle["message"])
        self._close_sketch()
        path = self.automation.create_sketch("Top", exact_geometry=True)
        self.assertTrue(path["success"], path["message"])
        line = self.automation.draw_line(0, 0, 0, 50, "mm")
        self.assertTrue(line["success"], line["message"])
        self._close_sketch()
        profile_name, path_name = self._sketch_names()

        result = sweep_sketch(self.automation, profile_name, path_name)

        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(628.319, self._total_volume_mm3(), delta=1.0)
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_loft_scratch_profiles_without_saving(self):
        self._new_part()
        first = self.automation.create_sketch("Top", exact_geometry=True)
        self.assertTrue(first["success"], first["message"])
        circle = self.automation.draw_circle(0, 0, 5, "mm")
        self.assertTrue(circle["success"], circle["message"])
        self._close_sketch()
        reference_plane = create_reference_plane(self.automation, "Top Plane", 20, "mm")
        self.assertTrue(reference_plane["success"], reference_plane["message"])
        self._sketch_on_plane("Plane1")
        second_circle = self.automation.draw_circle(0, 0, 3, "mm")
        self.assertTrue(second_circle["success"], second_circle["message"])
        self._close_sketch()
        first_name, second_name = self._sketch_names()

        result = loft_sketches(self.automation, [first_name, second_name])

        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(1026.039, self._total_volume_mm3(), delta=1.0)
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def _box_100x100x40(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-50, -50, 50, 50, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(40, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        return self._total_volume_mm3()

    def test_revolve_cut_removes_a_half_ring_without_saving(self):
        before = self._box_100x100x40()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_rectangle(10, -10, 20, 10, "mm")["success"])
        self.assertTrue(draw_centerline(self.automation, 0, -30, 0, 30)["success"])
        self._close_sketch()
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)

        result = revolve_cut(self.automation, self._last_sketch_name(document))

        self.assertTrue(result["success"], result["message"])
        # Only the half of the ring in front of the Front plane is in the box.
        expected = 0.5 * math.pi * (20 ** 2 - 10 ** 2) * 20
        self.assertAlmostEqual(expected, before - self._total_volume_mm3(), delta=1.0)

    def test_sweep_cut_removes_a_half_cylinder_without_saving(self):
        before = self._box_100x100x40()
        path = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(path["success"], path["message"])
        self.assertTrue(self.automation.draw_line(0, 0, 60, 0, "mm")["success"])
        self._close_sketch()
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        path_name = self._last_sketch_name(document)
        self._sketch_on_plane("Right Plane")
        self.assertTrue(draw_circle_radius(self.automation, 0, 0, 5)["success"])
        self._close_sketch()

        result = sweep_cut(self.automation, self._last_sketch_name(document), path_name)

        self.assertTrue(result["success"], result["message"])
        expected = 0.5 * math.pi * 5 ** 2 * 50
        self.assertAlmostEqual(expected, before - self._total_volume_mm3(), delta=1.0)

    def test_loft_cut_removes_a_frustum_without_saving(self):
        before = self._box_100x100x40()
        plane = create_reference_plane(self.automation, "Front Plane", 40, "mm")
        self.assertTrue(plane["success"], plane["message"])
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_rectangle(-10, -10, 10, 10, "mm")["success"])
        self._close_sketch()
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        first = self._last_sketch_name(document)
        self._sketch_on_plane("Plane1")
        self.assertTrue(self.automation.draw_rectangle(-5, -5, 5, 5, "mm")["success"])
        self._close_sketch()

        result = loft_cut(self.automation, [first, self._last_sketch_name(document)])

        self.assertTrue(result["success"], result["message"])
        expected = 40 / 3 * (400 + 100 + math.sqrt(400 * 100))
        self.assertAlmostEqual(expected, before - self._total_volume_mm3(), delta=1.0)

    def _two_square_profiles(self):
        plane = create_reference_plane(self.automation, "Front Plane", 40, "mm")
        self.assertTrue(plane["success"], plane["message"])
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_rectangle(-10, -10, 10, 10, "mm")["success"])
        self._close_sketch()
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        first = self._last_sketch_name(document)
        self._sketch_on_plane("Plane1")
        self.assertTrue(self.automation.draw_rectangle(-5, -5, 5, 5, "mm")["success"])
        self._close_sketch()
        return [first, self._last_sketch_name(document)]

    def test_boundary_boss_builds_a_frustum_without_saving(self):
        self._new_part()

        result = boundary_boss(self.automation, self._two_square_profiles())

        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(9333.333, self._total_volume_mm3(), delta=1.0)

    def test_boundary_cut_removes_a_frustum_without_saving(self):
        before = self._box_100x100x40()

        result = boundary_cut(self.automation, self._two_square_profiles())

        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(9333.333, before - self._total_volume_mm3(), delta=1.0)

    def test_polygon_radius_is_the_circumscribed_vertex_radius_without_saving(self):
        self._new_part()
        self.assertTrue(self.automation.create_sketch("Top", exact_geometry=True)["success"])
        polygon = self.automation.draw_polygon(0, 0, 25, 6, "mm")
        self.assertTrue(polygon["success"], polygon["message"])
        extrusion = self.automation.extrude_sketch(10, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])

        hexagon_area = 3 * math.sqrt(3) / 2 * 25 ** 2
        self.assertAlmostEqual(hexagon_area * 10, self._total_volume_mm3(), places=2)

    def test_arc_runs_counter_clockwise_from_start_to_end_angle(self):
        self._new_part()
        self.assertTrue(self.automation.create_sketch("Front", exact_geometry=True)["success"])
        arc = self.automation.draw_arc_center(0, 0, 20, 90, 0, "mm")
        self.assertTrue(arc["success"], arc["message"])
        self.assertEqual(270, arc["data"]["arc_angle"])

        document, _ = self.automation.get_active_doc()
        sketch = com(com(document, "SketchManager"), "ActiveSketch")
        (segment,) = com(sketch, "GetSketchSegments")
        self.assertAlmostEqual(1.5 * math.pi * 20, com(segment, "GetLength") * 1000, places=3)

    def test_create_sketch_refuses_a_reference_plane_name(self):
        self._new_part()
        reference_plane = create_reference_plane(self.automation, "Top Plane", 30, "mm")
        self.assertTrue(reference_plane["success"], reference_plane["message"])

        result = self.automation.create_sketch("Plane1")

        self.assertFalse(result["success"])
        self.assertIn("create_sketch_on_plane", result["message"])

    @staticmethod
    def _dxf_line_points(path):
        """Normalised end points of the LINE entities in an ASCII DXF."""
        pairs = Path(path).read_text(errors="replace").splitlines()
        codes = [(pairs[i].strip(), pairs[i + 1].strip())
                 for i in range(0, len(pairs) - 1, 2)]
        points, entity, values = [], None, {}
        for code, value in codes + [("0", "EOF")]:
            if code == "0":
                if entity == "LINE":
                    points += [(values["10"], values["20"]), (values["11"], values["21"])]
                entity, values = value, {}
            elif code in ("10", "20", "11", "21"):
                values[code] = float(value)
        min_x = min(x for x, _ in points)
        min_y = min(y for _, y in points)
        return {(round(x - min_x, 2), round(y - min_y, 2)) for x, y in points}

    def test_planar_faces_report_outward_normals_and_dxf_is_not_mirrored(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        outline = [(0, 0), (60, 0), (60, 10), (10, 10), (10, 40), (0, 40), (0, 0)]
        for start, end in zip(outline, outline[1:]):
            self.assertTrue(self.automation.draw_line(*start, *end, "mm")["success"])
        extrusion = self.automation.extrude_sketch(5, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        faces = list_planar_faces(self.automation)["data"]["faces"]
        caps = [face for face in faces if round(face["area_mm2"]) == 900]
        self.assertEqual(2, len(caps))

        # B25: the two end caps face opposite ways.
        dot = sum(a * b for a, b in zip(caps[0]["normal"], caps[1]["normal"]))
        self.assertAlmostEqual(-1.0, dot, places=6)

        # Face export needs a saved model path.
        refused = export_face_to_dxf(self.automation, caps[0]["index"], "unused.dxf")
        self.assertFalse(refused["success"])
        root = Path(self.automation._path_policy.output_roots[0])
        part_path = root / "saved" / "mcp_live_l_plate.SLDPRT"
        saved = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved["success"], saved["message"])
        self.created_titles.append(str(com(self.automation.get_active_doc()[0], "GetTitle")))

        output_root = root / "exports"
        shapes = []
        for cap in caps:
            path = output_root / f"scratch-{uuid4().hex}.dxf"
            self.created_artifacts.append(str(path))
            result = export_face_to_dxf(self.automation, cap["index"], str(path))
            self.assertTrue(result["success"], result["message"])
            shapes.append(self._dxf_line_points(path))

        # Seen from outside, the two caps are mirror images of each other:
        # no in-plane rotation maps one onto the other, but a mirror does.
        def rotations(points):
            result = []
            for _ in range(4):
                points = {(-y, x) for x, y in points}
                min_x = min(x for x, _ in points)
                min_y = min(y for _, y in points)
                result.append({(round(x - min_x, 2), round(y - min_y, 2))
                               for x, y in points})
            return result

        mirrored = {(-x, y) for x, y in shapes[1]}
        self.assertNotIn(shapes[0], rotations(shapes[1]))
        self.assertIn(shapes[0], rotations(mirrored))

    def test_mirror_scratch_extrusion_about_front_plane_without_saving(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(5, -3, 15, 3, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(5, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        seed_name = self._feature_name_by_type("Extrusion")
        self.assertIsNotNone(seed_name)
        volume_before = self._total_volume_mm3()
        self.assertAlmostEqual(300.0, volume_before, delta=1.0)

        result = mirror_feature(self.automation, seed_name, "Front Plane")

        self.assertTrue(result["success"], result["message"])
        self.assertIsNotNone(self._feature_name_by_type("Mirror"))
        self.assertAlmostEqual(2 * volume_before, self._total_volume_mm3(), delta=1.0)
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def test_shell_scratch_extrusion_removes_one_planar_face_without_saving(self):
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -10, 20, 10, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extrusion = self.automation.extrude_sketch(20, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        faces = list_planar_faces(self.automation)
        self.assertTrue(faces["success"], faces["message"])
        self.assertTrue(faces["data"]["faces"])
        removable_face = faces["data"]["faces"][0]["index"]

        result = shell_feature(
            self.automation, 2, "mm", remove_face_indices=[removable_face]
        )

        self.assertTrue(result["success"], result["message"])
        self.assertIn("Shell", self._top_level_feature_types())
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)


@unittest.skipUnless(
    os.environ.get("SW_MCP_LIVE_TESTS") == "1",
    "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.",
)
class LiveAssemblyInspectionTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])

    def tearDown(self):
        self.automation.disconnect()

    def test_active_user_assembly_mates_are_read_without_saving(self):
        document, error = self.automation.get_active_doc()
        if error or com(document, "GetType") != SwDocumentTypes.swDocASSEMBLY:
            self.skipTest("No active assembly is available for read-only mate inspection.")

        result = list_mates(self.automation)

        self.assertTrue(result["success"], result["message"])
        for mate in result["data"]["mates"]:
            self.assertIn("entities", mate)
            self.assertIn("solver_status", mate)
            self.assertIn("feature_id", mate)


if __name__ == "__main__":
    unittest.main()
