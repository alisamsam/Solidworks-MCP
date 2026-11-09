"""Live proof for the Tab and Slot tool (S22).

Fixture: two sheet-metal bodies of 1 mm sheet that meet at a corner, so a tab
grown from one body's edge passes through the other body's large face.

  Body A: base flange from a Top-plane rectangle  -> Z -1..0, X -50..0, Y 0..100
  Body B: base flange from a Right-plane rectangle -> Y -1..0, X -50..50, Z -50..50

A's edge at Y=0, Z=0 lies in the middle of B's face at Y=0, so the tab grows
through B and B loses the slot material.  The proof is per body: the tab body
must gain the tab volume and the slot body must lose the slot volume, and the
body count and the tab/slot face topology must change accordingly.  A feature
name alone is never treated as proof.
"""

import unittest
from pathlib import Path
from uuid import uuid4

import pythoncom
import win32com.client

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.inspection import list_body_edges
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.sheetmetal import create_tab_and_slot


@live_only
class LiveTabAndSlotTests(ScratchPartTestCase):
    def _base_flange(self, thickness_mm=1.0, width_mm=50.0, radius_mm=1.0):
        """Second and further sheet-metal bodies, which the MCP tool refuses.

        The call is the same live-verified 16-argument
        InsertSheetMetalBaseFlange used by create_sheet_metal_base_flange; a
        scratch part only ever needs it once through that tool.
        """
        document = self.document()
        selected, _sketch, message = self.automation._close_and_select_sketch(document)
        self.assertTrue(selected, message)
        half = width_mm / 2000.0
        feature = com(
            com(document, "FeatureManager"), "InsertSheetMetalBaseFlange",
            thickness_mm / 1000.0, False, radius_mm / 1000.0,
            half, half, False, 0, 0, 0,
            win32com.client.VARIANT(pythoncom.VT_DISPATCH, None),
            False, 0, 0.0, 0.0, 0.0, False,
        )
        self.assertIsNotNone(feature, "base flange was not created")
        return com(feature, "Name")

    def _corner_fixture(self):
        """Two perpendicular 1 mm sheet bodies meeting at a corner."""
        self.open_scratch_part()
        self.new_sketch("Top")
        self.assertTrue(self.automation.draw_rectangle(0, 0, 100, 50, "mm")["success"])
        self.exit_sketch()
        self._base_flange()
        self.new_sketch("Right")
        self.assertTrue(self.automation.draw_rectangle(-50, -50, 50, 50, "mm")["success"])
        self.exit_sketch()
        self._base_flange()
        com(self.document(), "ForceRebuild3", False)
        self.assertEqual(2, self.solid_body_count())
        return self.document()

    def _slot_face_and_tab_edge(self):
        """Indices of the slot face and of the tab edge inside its plane."""
        faces = list_planar_faces(self.automation)
        self.assertTrue(faces["success"], faces["message"])
        candidates = [face for face in faces["data"]["faces"]
                      if face["normal"][1] > 0.99 and face["area_mm2"] > 5000]
        self.assertEqual(1, len(candidates), f"slot face: {candidates}")
        slot = candidates[0]

        listed = list_body_edges(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        point, normal = slot["point_mm"], slot["normal"]

        def in_plane(coordinates):
            return abs(sum((coordinates[axis] - point[axis]) * normal[axis]
                           for axis in range(3))) < 0.01

        edges = [edge for edge in listed["data"]["edges"]
                 if edge["is_line"] and edge["body"] != slot["body"]
                 and in_plane(edge["start_mm"]) and in_plane(edge["end_mm"])]
        self.assertTrue(edges, "no tab edge found in the slot face plane")
        tab_edge = max(edges, key=lambda edge: edge["length_mm"])
        return slot["index"], tab_edge["index"]

    def _volumes(self):
        return [round(volume, 3) for volume in self._body_volumes()]

    def _sorted_volumes(self):
        """Body volumes sorted ascending.

        GetBodies2 does not promise a stable order across documents, so the
        live proof compares the two bodies by rank: the smaller body gains the
        tab, the larger one loses the slot.
        """
        return sorted(self._volumes())

    def _sorted_face_counts(self):
        return sorted(self._face_counts())

    def _body_volumes(self):
        volumes = []
        for body in com(self.document(), "GetBodies2", 0, True) or []:
            self._keep(body)
            volumes.append(com(body, "GetMassProperties", 0.0)[3] * 1e9)
        return volumes

    def _face_counts(self):
        counts = []
        for body in com(self.document(), "GetBodies2", 0, True) or []:
            self._keep(body)
            counts.append(len(com(body, "GetFaces") or []))
        return counts

    def test_tab_is_grown_and_slot_is_cut(self):
        self._corner_fixture()
        slot_index, tab_index = self._slot_face_and_tab_edge()
        before = self._sorted_volumes()
        faces_before = self._sorted_face_counts()
        self.assertEqual([5000.0, 10000.0], before)

        result = create_tab_and_slot(self.automation, tab_index, slot_index,
                                     tab_length_mm=10.0, tab_height_mm=6.0,
                                     slot_clearance_mm=0.2)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("TabAndSlotFeature", result["data"]["feature_type"])
        # Tab: 10 mm long x 1 mm sheet x 6 mm high; slot: 10.4 x 1.2 x 1 mm.
        self.assertAlmostEqual(60.0, result["data"]["gained_mm3"], delta=0.1)
        self.assertAlmostEqual(12.48, result["data"]["removed_mm3"], delta=0.1)

        after = self._sorted_volumes()
        self.assertEqual(len(before), len(after))
        # The smaller body gained the tab, the larger one lost the slot.
        self.assertAlmostEqual(60.0, after[0] - before[0], delta=0.1)
        self.assertAlmostEqual(12.48, before[1] - after[1], delta=0.1)

        faces_after = self._sorted_face_counts()
        # The tab adds two faces to its body, the slot walls four to the other.
        self.assertEqual([faces_before[0] + 2, faces_before[1] + 4], faces_after)

        # The definition must read back as one group with the requested height
        # type; the exact length, height and clearance are proven by the volume
        # deltas above, which the readback of a Blind height does not reflect.
        readback = result["data"]["definition_readback"]
        self.assertEqual(1, readback.get("groups"), readback)
        self.assertEqual(0, int(readback["TabHeightType"]), readback)

        com(self.document(), "ForceRebuild3", False)
        feature = self.feature_named(result["data"]["feature"])
        self.assertIsNotNone(feature)
        self.assertEqual("TabAndSlotFeature", str(com(feature, "GetTypeName2")))
        self.capture(1, "tab and slot corner")
        self.assert_unsaved()

        root = Path(self.automation._path_policy.output_roots[0])
        target = root / "saved" / f"mcp_live_tab_and_slot_{uuid4().hex}.SLDPRT"
        saved = save_document(self.automation, path=str(target), overwrite=False)
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(target.stat().st_size, 0)
        self.created_titles[-1] = str(com(self.document(), "GetTitle"))

    def test_evenly_spaced_instances_and_fillet_treatment(self):
        self._corner_fixture()
        slot_index, tab_index = self._slot_face_and_tab_edge()
        before = self._sorted_volumes()

        result = create_tab_and_slot(self.automation, tab_index, slot_index,
                                     tab_length_mm=10.0, tab_height_mm=6.0,
                                     slot_clearance_mm=0.2, spacing="equal",
                                     instances=3)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(180.0, result["data"]["gained_mm3"], delta=0.3)
        self.assertAlmostEqual(37.44, result["data"]["removed_mm3"], delta=0.3)
        after = self._sorted_volumes()
        self.assertAlmostEqual(180.0, after[0] - before[0], delta=0.3)
        self.assertAlmostEqual(37.44, before[1] - after[1], delta=0.3)

        # A second group on the same edge with a filleted tab edge.
        self._corner_fixture()
        slot_index, tab_index = self._slot_face_and_tab_edge()
        before = self._sorted_volumes()
        result = create_tab_and_slot(self.automation, tab_index, slot_index,
                                     tab_length_mm=10.0, tab_height_mm=6.0,
                                     edge_treatment="fillet",
                                     edge_treatment_mm=2.0)
        self.assertTrue(result["success"], result["message"])
        # The fillet removes the two sharp tab corners, so slightly less than 60.
        self.assertGreater(result["data"]["gained_mm3"], 55.0)
        self.assertLess(result["data"]["gained_mm3"], 60.0)
        after = self._sorted_volumes()
        self.assertGreater(after[0], before[0])
        self.assertLess(after[1], before[1])

    def test_an_edge_outside_the_slot_plane_creates_nothing(self):
        self._corner_fixture()
        slot_index, tab_index = self._slot_face_and_tab_edge()
        listed = list_body_edges(self.automation)
        outside = [edge for edge in listed["data"]["edges"]
                   if edge["is_line"] and edge["length_mm"]
                   and edge["start_mm"][1] > 99.0 and edge["end_mm"][1] > 99.0]
        self.assertTrue(outside, "expected the far edge of body A")
        before = self._sorted_volumes()

        result = create_tab_and_slot(self.automation, outside[0]["index"], slot_index)
        self.assertFalse(result["success"])
        self.assertEqual(before, self._sorted_volumes())

    def test_tool_rejects_a_single_body_part(self):
        self.open_scratch_part()
        self.new_sketch("Top")
        self.assertTrue(self.automation.draw_rectangle(0, 0, 100, 50, "mm")["success"])
        self.exit_sketch()
        self._base_flange()
        result = create_tab_and_slot(self.automation, 0, 0)
        self.assertFalse(result["success"])
        self.assertIn("two solid bodies", result["message"])


if __name__ == "__main__":
    unittest.main()
