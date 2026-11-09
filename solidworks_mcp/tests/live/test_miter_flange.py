"""S3: replay the user's four-segment Right-Plane miter on a fresh plate.

No existing user document is changed. A call returning a feature is not enough:
the sheet must grow from 5000 to about 6990.6 mm3 and 6 to 38 faces.
"""

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.inspection import list_body_edges
from solidworks_mcp.tools.sheetmetal import (create_miter_flange,
                                              create_sheet_metal_base_flange)


@live_only
class LiveMiterFlangeTests(ScratchPartTestCase):
    def test_four_segment_path_creates_four_bends_and_adds_material(self):
        self.open_scratch_part()
        self.assertEqual(0, self.solid_body_count())
        doc = self.document()
        self.new_sketch("Front")
        rectangle = self.automation.draw_rectangle(0, 0, 100, 50, "mm")
        self.assertTrue(rectangle["success"], rectangle)
        self.exit_sketch()
        base = create_sheet_metal_base_flange(self.automation, 1.0,
                                               bend_radius_mm=1.0)
        self.assertTrue(base["success"], base)
        com(doc, "ForceRebuild3", False)

        # Target the back edge (X=-1, Z=50), running the full Y width.
        listing = list_body_edges(self.automation)
        self.assertTrue(listing["success"], listing)
        matches = [edge for edge in listing["data"]["edges"]
                   if abs(edge["length_mm"] - 100.0) < 0.01
                   and all(abs(p[0] + 1.0) < 0.01
                           and abs(p[2] - 50.0) < 0.01
                           for p in (edge["start_mm"], edge["end_mm"]))]
        self.assertEqual(1, len(matches), matches)
        edge_index = matches[0]["index"]

        profile = self.new_sketch("Right")
        # Right Plane has sketch X=-model X and sketch Y=model Z on this part.
        # These are real sketch coordinates in meters, NOT model coordinates.
        points = [(0.001, 0.050), (0.010390, 0.050),
                  (0.012226, 0.051886), (0.012226, 0.057039),
                  (0.010390, 0.058397)]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            self.assertIsNotNone(com(doc, "CreateLine2", ax, ay, 0.0,
                                     bx, by, 0.0), "profile line not created")
        self.exit_sketch()
        self.assertEqual(4, self.segment_count(profile))
        before_volume = self.total_volume_mm3()
        before_faces = self.total_solid_faces()
        self.assertAlmostEqual(5000.0, before_volume, delta=0.01)
        self.assertEqual(6, before_faces)

        result = create_miter_flange(self.automation, edge_index, profile)

        self.assertTrue(result["success"], result)
        self.assertEqual("SMMiteredFlange", result["data"]["feature_type"])
        self.assertIsNotNone(self.feature_named(result["data"]["feature"]))
        self.assertAlmostEqual(6990.607, self.total_volume_mm3(), delta=1.0)
        self.assertAlmostEqual(1990.607, result["data"]["gained_mm3"], delta=1.0)
        self.assertEqual(38, self.total_solid_faces())
        self.assertEqual(1, self.solid_body_count())
        feature = self.feature_named(result["data"]["feature"])
        bends = []
        child = com(feature, "GetFirstSubFeature")
        while child is not None:
            if str(com(child, "GetTypeName2")) == "SketchBend":
                bends.append(child)
            child = com(child, "GetNextSubFeature")
        self.assertEqual(4, len(bends))
        self.capture(1, "miter flange four bends")


if __name__ == "__main__":
    import unittest
    unittest.main()
