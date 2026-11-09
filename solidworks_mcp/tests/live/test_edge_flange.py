"""Live proof for the edge flange tool (S2).

One scratch document per test method, each holding a single sheet-metal body.

Why not one document with several bodies: the document-wide edge scan is
pathological as soon as a document has more than one body.  Measured on this
fixture, per scan of the same geometry:

    1 body  (12 edges) -> part_edges 0.14 s
    2 bodies (24 edges) -> part_edges 5.77 s
    3 bodies (36 edges) -> part_edges 8.54 s

so 12 extra edges cost 5.6 s, and sharing one document across variants made the
module slower (125 s) than one body per document (about 9 s each).  IBody2::
GetEdges is only ~1.8x faster (4.72 s for three bodies) and does not change the
shape of the cost, so the fixture stays single-body.

Fixture: a 100 x 50 x 1 mm plate on the Front plane made with
create_sheet_metal_base_flange (parent bend radius 1 mm); the flange grows from
its 100 mm perimeter edge.  A flange must add material and raise the face count;
the feature name alone is never treated as proof.

Measured gain for a 20 mm flange on the 100 mm edge (bend-outside position,
default relief, parent bend radius 1 mm):

  90 deg, default radius -> 2135.6 mm3, 6 -> 14 faces
  45 deg, default radius -> 2076.4 mm3
  90 deg, radius 5 mm    -> 2363.9 mm3
"""

import unittest

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.inspection import list_body_edges
from solidworks_mcp.tools.sheetmetal import (create_edge_flange,
                                             create_sheet_metal_base_flange)

LENGTH_MM = 20.0
BASE_GAIN_MM3 = 2135.6
ANGLE_GAIN_MM3 = 2076.4
RADIUS_GAIN_MM3 = 2363.9


@live_only
class LiveEdgeFlangeTests(ScratchPartTestCase):
    def _open_part(self):
        """One document per test method, verified empty before it is used."""
        self.open_scratch_part()
        self.assertEqual(0, self.solid_body_count(),
                         "the freshly created part is not empty, so a document "
                         "from an earlier test is still active")
        return self.document()

    def _add_plate(self):
        """Add the only body: a 100 x 50 x 1 mm sheet-metal plate."""
        document = self.document()
        self.new_sketch("Front")
        self.assertTrue(
            self.automation.draw_rectangle(0, 0, 100, 50, "mm")["success"])
        self.exit_sketch()
        result = create_sheet_metal_base_flange(self.automation, 1.0,
                                                bend_radius_mm=1.0)
        self.assertTrue(result["success"], result["message"])
        com(document, "ForceRebuild3", False)
        self.assertEqual(1, self.solid_body_count())
        return document

    def _longest_edge_index(self):
        """The one listing this test needs; the scan is priced per document."""
        listed = list_body_edges(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        edges = [edge for edge in listed["data"]["edges"]
                 if edge["length_mm"] is not None]
        self.assertTrue(edges, "no straight edges on the sheet")
        return max(edges, key=lambda edge: edge["length_mm"])["index"]

    def test_flange_grows_the_sheet_and_adds_faces(self):
        self._open_part()
        self._add_plate()
        edge_index = self._longest_edge_index()
        volume_before = self.total_volume_mm3()
        faces_before = self.total_solid_faces()

        result = create_edge_flange(self.automation, edge_index, LENGTH_MM)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual("EdgeFlange", result["data"]["feature_type"])
        self.assertTrue(result["data"]["feature"].startswith("Edge-Flange"),
                        result["data"]["feature"])
        self.assertTrue(
            self.feature_named(result["data"]["feature"]) is not None,
            "the flange did not persist in the feature tree")

        volume_after = self.total_volume_mm3()
        faces_after = self.total_solid_faces()
        gained = volume_after - volume_before
        self.assertAlmostEqual(BASE_GAIN_MM3, gained, delta=1.0)
        self.assertAlmostEqual(BASE_GAIN_MM3, result["data"]["gained_mm3"],
                               delta=1.0)
        self.assertGreater(faces_after, faces_before)
        self.assertEqual(14, faces_after)
        # A flange bends the existing sheet; it never adds a body.
        self.assertEqual(1, self.solid_body_count())
        self.assertEqual(1, result["data"]["bodies_before"])
        self.assertEqual(1, result["data"]["bodies_after"])
        self.assertTrue(result["data"]["uses_default_bend_radius"])
        self.capture(1, "edge flange 20 mm at 90 degrees")

    def test_shallower_angle_adds_less_material(self):
        self._open_part()
        self._add_plate()
        volume_before = self.total_volume_mm3()
        result = create_edge_flange(self.automation, self._longest_edge_index(),
                                    LENGTH_MM, angle_deg=45.0)
        self.assertTrue(result["success"], result["message"])
        gained = self.total_volume_mm3() - volume_before
        self.assertAlmostEqual(ANGLE_GAIN_MM3, gained, delta=1.0)
        self.assertLess(gained, BASE_GAIN_MM3)
        self.assertEqual(14, self.total_solid_faces())

    def test_explicit_radius_replaces_the_sheet_default(self):
        self._open_part()
        self._add_plate()
        volume_before = self.total_volume_mm3()
        result = create_edge_flange(self.automation, self._longest_edge_index(),
                                    LENGTH_MM, bend_radius_mm=5.0)
        self.assertTrue(result["success"], result["message"])
        gained = self.total_volume_mm3() - volume_before
        self.assertAlmostEqual(RADIUS_GAIN_MM3, gained, delta=1.0)
        self.assertGreater(gained, BASE_GAIN_MM3)
        self.assertFalse(result["data"]["uses_default_bend_radius"])
        self.assertAlmostEqual(5.0, result["data"]["bend_radius_mm"], places=3)

    def test_requests_that_cannot_build_are_rejected(self):
        # Before any sheet metal exists there is nothing to bend.
        self.open_scratch_part()
        empty = create_edge_flange(self.automation, 0, LENGTH_MM)
        self.assertFalse(empty["success"])
        self.assertEqual("NO_SHEET_METAL", empty["data"]["code"])

        # An index with no edge behind it changes nothing on a real sheet.
        self._add_plate()
        volume_before = self.total_volume_mm3()
        out_of_range = create_edge_flange(self.automation, 4096, LENGTH_MM)
        self.assertFalse(out_of_range["success"])
        self.assertAlmostEqual(volume_before, self.total_volume_mm3(),
                               delta=1e-6)
        self.assertEqual(0, self.feature_count("EdgeFlange"))


if __name__ == "__main__":
    unittest.main()
