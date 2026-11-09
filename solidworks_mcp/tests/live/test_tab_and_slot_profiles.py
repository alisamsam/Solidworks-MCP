"""Live proof for Tab and Slot on real weldment profiles.

Fixture (the same T-joint as the weld-bead work):
  Through member: Custom 50x50 tube along world Y, Y 0..150, 2 mm walls, so its
                  top wall spans Z 23..25.
  Butting member: Custom 30X30 tube standing on that top face, Z 25..150.

The butting tube's base rim edges lie in the through tube's top face plane, so a
tab grown from such an edge can run down through the through tube's top wall.
The tab height is set to that wall's thickness, which makes the tab stop flush
at the wall's inner face - the "up to the other face" the user asked for.

Both the wall thickness and the joint plane are read from the geometry (the
outer and the cavity top faces of the through member), not hard-coded.
"""

import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.inspection import list_body_edges
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.sheetmetal import create_tab_and_slot
from solidworks_mcp.tools.weldments import create_structural_member, list_weldment_profiles


@live_only
class LiveTabAndSlotProfileTests(ScratchPartTestCase):
    def _profile(self, name):
        profiles = list_weldment_profiles(self.automation)
        self.assertTrue(profiles["success"], profiles["message"])
        matches = [item["path"] for item in profiles["data"]["profiles"]
                   if item["name"].casefold() == name.casefold()]
        self.assertEqual(1, len(matches), f"Profile not installed: {name}")
        return matches[0]

    def _member(self, lines, profile_path):
        sketch = self.new_sketch("Front")
        for x0, y0, x1, y1 in lines:
            result = self.automation.draw_line(x0, y0, x1, y1, "mm")
            self.assertTrue(result["success"], result["message"])
        self.exit_sketch()
        member = create_structural_member(self.automation, sketch, profile_path)
        self.assertTrue(member["success"], member["message"])

    def _t_joint(self):
        """Returns (slot_face_index, tab_edge_index, joint_z, wall_mm)."""
        self.open_scratch_part()
        self._member([(0, 0, 150, 0)], self._profile("50x50.SLDLFP"))
        self._member([(75, 25, 75, 150)], self._profile("30X30.SLDLFP"))
        com(self.document(), "ForceRebuild3", False)
        self.assertEqual(2, self.solid_body_count())

        boxes = self.named_body_boxes()
        through = max(boxes, key=lambda item: item["volume_mm3"])
        butting = min(boxes, key=lambda item: item["volume_mm3"])

        faces = list_planar_faces(self.automation)
        self.assertTrue(faces["success"], faces["message"])
        tops = [face for face in faces["data"]["faces"]
                if face["body"] == through["name"] and face["normal"][2] > 0.99]
        self.assertGreaterEqual(len(tops), 1, tops)
        tops.sort(key=lambda face: -face["point_mm"][2])
        slot = tops[0]                       # outer top wall face, the slot face
        # The wall thickness is the gap from the slot face down to the nearest
        # parallel face of the same body. The cavity ceiling is not usable on its
        # own because its normal points down into the cavity, so the nearest
        # parallel plane below the slot face is the cavity floor.
        axis = max(range(3), key=lambda index: abs(slot["normal"][index]))
        planes = sorted({round(face["point_mm"][axis], 4)
                         for face in faces["data"]["faces"]
                         if face["body"] == through["name"]
                         and abs(face["normal"][axis]) > 0.999})
        below = [value for value in planes if value < slot["point_mm"][axis] - 0.001]
        self.assertTrue(below, f"no parallel face below the slot face: {planes}")
        wall_mm = slot["point_mm"][axis] - max(below)
        self.assertGreater(wall_mm, 0.1)

        listed = list_body_edges(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        point, normal = slot["point_mm"], slot["normal"]

        def in_plane(coordinates):
            return abs(sum((coordinates[axis] - point[axis]) * normal[axis]
                           for axis in range(3))) < 0.01

        edges = [edge for edge in listed["data"]["edges"]
                 if edge["is_line"] and edge["body"] == butting["name"]
                 and in_plane(edge["start_mm"]) and in_plane(edge["end_mm"])]
        self.assertTrue(edges, "no base rim edge found in the joint plane")
        edges.sort(key=lambda edge: (edge["start_mm"][1], edge["end_mm"][1],
                                     edge["start_mm"][0], edge["end_mm"][0]))
        return slot["index"], edges[0]["index"], slot["point_mm"][2], wall_mm

    def named_body_boxes(self):
        boxes = []
        for body in com(self.document(), "GetBodies2", 0, True) or []:
            self._keep(body)
            boxes.append({
                "name": str(com(body, "Name")),
                "volume_mm3": com(body, "GetMassProperties", 0.0)[3] * 1e9,
                "box_mm": [round(float(value) * 1000, 3)
                           for value in com(body, "GetBodyBox")],
            })
        return boxes

    def _tab_body_box(self):
        """The butting body is the one whose bounding box reaches highest."""
        return max(self.named_body_boxes(), key=lambda item: item["box_mm"][2])

    def test_tab_stops_flush_at_the_walls_inner_face(self):
        slot_index, tab_index, joint_z, wall_mm = self._t_joint()
        tab_before = self._tab_body_box()
        self.assertAlmostEqual(joint_z, tab_before["box_mm"][2], delta=0.01)

        result = create_tab_and_slot(
            self.automation, tab_index, slot_index,
            tab_length_mm=10.0, tab_height_mm=wall_mm,
            tab_thickness_mm=wall_mm, slot_clearance_mm=0.2)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("TabAndSlotFeature", result["data"]["feature_type"])
        expected_tab = 10.0 * wall_mm * wall_mm
        expected_slot = 10.4 * (wall_mm + 0.2) * wall_mm
        self.assertAlmostEqual(expected_tab, result["data"]["gained_mm3"],
                               delta=0.5)
        self.assertAlmostEqual(expected_slot, result["data"]["removed_mm3"],
                               delta=0.5)

        tab_after = self._tab_body_box()
        # The tab goes through the wall and ends flush at its inner face.
        self.assertAlmostEqual(joint_z - wall_mm, tab_after["box_mm"][2],
                               delta=0.01)
        self.assertGreater(result["data"]["slot_body"]["faces_after"],
                           result["data"]["slot_body"]["faces_before"])

        com(self.document(), "ForceRebuild3", False)
        feature = self.feature_named(result["data"]["feature"])
        self.assertIsNotNone(feature)
        self.capture(1, "tab and slot through a tube wall")
        self.assert_unsaved()

        root = Path(self.automation._path_policy.output_roots[0])
        target = root / "saved" / f"mcp_live_tab_slot_profile_{uuid4().hex}.SLDPRT"
        saved = save_document(self.automation, path=str(target), overwrite=False)
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(target.stat().st_size, 0)
        self.created_titles[-1] = str(com(self.document(), "GetTitle"))

    def test_shorter_tab_leaves_a_blind_slot(self):
        slot_index, tab_index, joint_z, wall_mm = self._t_joint()
        height = round(wall_mm / 2.0, 3)

        result = create_tab_and_slot(self.automation, tab_index, slot_index,
                                     tab_length_mm=10.0, tab_height_mm=height,
                                     tab_thickness_mm=wall_mm,
                                     slot_clearance_mm=0.2)
        self.assertTrue(result["success"], result["message"])
        tab_after = self._tab_body_box()
        # A partial tab stops inside the wall and does not reach the inner face.
        self.assertAlmostEqual(joint_z - height, tab_after["box_mm"][2], delta=0.01)
        self.assertGreater(result["data"]["gained_mm3"], 0)

    def test_longer_tab_reaches_into_the_hollow_section(self):
        slot_index, tab_index, joint_z, wall_mm = self._t_joint()
        height = round(wall_mm + 3.0, 3)

        result = create_tab_and_slot(self.automation, tab_index, slot_index,
                                     tab_length_mm=10.0, tab_height_mm=height,
                                     tab_thickness_mm=wall_mm,
                                     slot_clearance_mm=0.2)
        self.assertTrue(result["success"], result["message"])
        tab_after = self._tab_body_box()
        self.assertAlmostEqual(joint_z - height, tab_after["box_mm"][2], delta=0.01)
        self.assertAlmostEqual(10.0 * height * wall_mm,
                               result["data"]["gained_mm3"], delta=0.5)


if __name__ == "__main__":
    unittest.main()
