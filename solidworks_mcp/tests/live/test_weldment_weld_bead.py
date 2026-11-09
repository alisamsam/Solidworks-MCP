"""Live proof for the cosmetic weld bead tool (W5).

Fixture is the wide-through-member T-joint the user suggested: a wider through
member (Custom 50x50) with a narrower butting member (Custom 30x30) standing on
its top face, so the butting member's base loop sits fully inside the through
member's face and a cosmetic bead can run all the way around it.

Cosmetic beads add no material, so the proof is the persistent CosmeticWeldBead
feature in the weld folder plus its recorded total weld length, and the live
test asserts that the solid volume is unchanged.
"""

import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.inspection import list_body_edges
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.weldments import (
    create_cosmetic_weld_bead, create_structural_member,
    list_weldment_profiles,
)


@live_only
class LiveCosmeticWeldBeadTests(ScratchPartTestCase):
    def _profile(self, name):
        profiles = list_weldment_profiles(self.automation)
        self.assertTrue(profiles["success"], profiles["message"])
        matches = [item["path"] for item in profiles["data"]["profiles"]
                   if item["name"].casefold() == name.casefold()]
        self.assertEqual(1, len(matches), f"Profile not installed: {name}")
        return matches[0]

    def _member(self, lines, profile_path):
        sketch = self.new_sketch()
        for x0, y0, x1, y1 in lines:
            result = self.automation.draw_line(x0, y0, x1, y1, "mm")
            self.assertTrue(result["success"], result["message"])
        self.exit_sketch()
        member = create_structural_member(self.automation, sketch, profile_path)
        self.assertTrue(member["success"], member["message"])

    def _wide_through_t_joint(self):
        """Returns (through_box, butting_box) in millimetres."""
        self.open_scratch_part()
        wide = self._profile("50x50.SLDLFP")     # Z +-25, so top face at Z=25
        narrow = self._profile("30X30.SLDLFP")   # sits on that top face
        self._member([(0, 0, 150, 0)], wide)
        self._member([(75, 25, 75, 150)], narrow)
        boxes = self.body_box_mm()
        self.assertEqual(2, len(boxes), boxes)
        through = max(boxes, key=lambda box: box[3] - box[0])
        butting = next(box for box in boxes if box is not through)
        return through, butting

    def _base_loop(self, through, butting):
        """Indices of the butting member's base loop, plus its straight length.

        The loop includes the rounded-corner arcs when the profile has them, so
        the bead can run all the way around; only the straight part has a length
        we can measure here.
        """
        top_z = through[5]
        half = (butting[3] - butting[0]) / 2
        centre_y = (butting[1] + butting[4]) / 2
        listed = list_body_edges(self.automation)
        self.assertTrue(listed["success"], listed["message"])

        def at_base(point):
            if abs(point[2] - top_z) > 0.05:
                return False
            if abs(point[0]) > half + 0.01 or abs(point[1] - centre_y) > half + 0.01:
                return False
            return max(abs(point[0]), abs(point[1] - centre_y)) >= half - 0.01

        edges = [edge for edge in listed["data"]["edges"]
                 if at_base(edge["start_mm"]) and at_base(edge["end_mm"])]
        self.assertGreaterEqual(len(edges), 4, f"Too few base edges: {edges}")
        straight = sum(edge["length_mm"] or 0.0 for edge in edges)
        longest = max(edge["length_mm"] or 0.0 for edge in edges)
        return [edge["index"] for edge in edges], straight, longest

    def _find_deep(self, name):
        """Find a feature anywhere in the tree, weld-folder children included."""
        def walk(feature, next_name):
            while feature is not None:
                self._keep(feature)
                if com(feature, "Name") == name:
                    return feature
                child = com(feature, "GetFirstSubFeature")
                if child is not None:
                    found = walk(child, "GetNextSubFeature")
                    if found is not None:
                        return found
                feature = com(feature, next_name)
            return None

        return walk(com(self.document(), "FirstFeature"), "GetNextFeature")

    def _weld_folder_names(self):
        return [(com(feature, "Name"), com(feature, "GetTypeName2"))
                for feature in self.features()
                if "weld" in str(com(feature, "GetTypeName2")).casefold()]

    def test_bead_runs_around_the_butting_member_base(self):
        through, butting = self._wide_through_t_joint()
        indices, straight_length, longest_edge = self._base_loop(through, butting)
        before = self.total_volume_mm3()

        result = create_cosmetic_weld_bead(self.automation, indices, size_mm=4.0)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("CosmeticWeldBead", result["data"]["feature_type"])
        self.assertEqual(1, len(result["data"]["features"]))
        self.assertEqual(4.0, result["data"]["bead_size_mm"])
        total = result["data"]["total_weld_length_mm"]
        # The bead covers the whole base loop: at least the straight part, but
        # clearly more than a single edge (which would prove it did not wrap).
        self.assertGreaterEqual(total, straight_length - 0.5)
        self.assertLessEqual(total, straight_length * 1.2 + 1.0)
        self.assertGreater(total, longest_edge * 2.0)
        # Cosmetic beads are annotations: no material is added.
        self.assertAlmostEqual(0.0, result["data"]["added_mm3"], delta=0.001)
        self.assertAlmostEqual(before, self.total_volume_mm3(), delta=0.001)

        com(self.document(), "ForceRebuild3", False)
        feature = self._find_deep(result["data"]["features"][0])
        self.assertIsNotNone(feature, "Weld bead vanished from the feature tree")
        self.assertEqual("CosmeticWeldBead", str(com(feature, "GetTypeName2")))
        self.assertTrue(any("weld" in name.casefold() or "weld" in type_name.casefold()
                            for name, type_name in self._weld_folder_names()),
                        self._weld_folder_names())
        self.assert_unsaved()

        root = Path(self.automation._path_policy.output_roots[0])
        target = root / "saved" / f"mcp_live_weld_bead_{uuid4().hex}.SLDPRT"
        saved = save_document(self.automation, path=str(target), overwrite=False)
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(target.stat().st_size, 0)
        self.created_titles[-1] = str(com(self.document(), "GetTitle"))

    def test_single_edge_bead_records_that_edge_length(self):
        through, butting = self._wide_through_t_joint()
        del through, butting
        listed = list_body_edges(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        longest = max((edge for edge in listed["data"]["edges"]
                       if edge["length_mm"]), key=lambda edge: edge["length_mm"])

        result = create_cosmetic_weld_bead(self.automation, [longest["index"]],
                                           size_mm=3.0)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(3.0, result["data"]["bead_size_mm"])
        self.assertAlmostEqual(longest["length_mm"],
                               result["data"]["total_weld_length_mm"], delta=0.5)
        self.assertAlmostEqual(0.0, result["data"]["added_mm3"], delta=0.001)

    def test_weld_folder_is_not_a_solid_and_edges_are_listed_consistently(self):
        self._wide_through_t_joint()
        listed = list_body_edges(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        self.assertEqual(listed["data"]["count"], len(listed["data"]["edges"]))
        self.assertEqual(list(range(len(listed["data"]["edges"]))),
                         [edge["index"] for edge in listed["data"]["edges"]])
        for edge in listed["data"]["edges"]:
            if edge["is_line"]:
                self.assertGreater(edge["length_mm"], 0)


if __name__ == "__main__":
    unittest.main()
