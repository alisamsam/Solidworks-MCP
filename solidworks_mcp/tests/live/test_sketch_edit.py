"""Live COM tests for the sketch editing tools (M1.2 slice 1).

One scratch part carries the whole sequence: every step owns its own zone of
the sketch plane, exercises exactly one editing tool, and is screenshotted
before the part is closed.  Trim and extend, which used to live in
``test_documents``, are part of the same sequence here.
"""

import math
import unittest

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only, zone
from solidworks_mcp.tools.sketch_edit import (
    add_sketch_dimension, add_sketch_relation, delete_sketch_relations,
    extend_entities, get_sketch_relations, offset_entities, rotate_entities,
    scale_entities, sketch_chamfer, sketch_fillet, sketch_mirror,
    sketch_pattern_circular, sketch_pattern_linear, split_entities,
    toggle_construction, trim_entities,
)


@live_only
class LiveSketchEditTests(ScratchPartTestCase):
    def test_sketch_edit_sequence_on_one_scratch_part(self):
        self.open_scratch_part()

        cases = self._cases()
        for index, (purpose, body) in enumerate(cases, 1):
            with self.subTest(step=index, purpose=purpose):
                try:
                    body()
                finally:
                    self.close_sketch()
                self.capture(index, purpose)

        self.assert_unsaved()

    # -- helpers -----------------------------------------------------------
    def _result(self, result):
        self.assertTrue(result["success"], result["message"])
        return result

    def _rectangle(self, position, half_width=25, half_height=15):
        ox, oy = zone(*position)
        sketch = self.new_sketch()
        drawn = self.automation.draw_rectangle(
            ox - half_width, oy - half_height, ox + half_width, oy + half_height,
            "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()
        return sketch

    def _circle(self, position, dx=20, dy=0, radius=4, plane="Front"):
        ox, oy = zone(*position)
        sketch = self.new_sketch(plane)
        drawn = self.automation.draw_circle(ox + dx, oy + dy, radius, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()
        return sketch

    # -- the ordered sequence ----------------------------------------------
    def _cases(self):
        return [
            ("fillet one rectangle corner", self._fillet),
            ("chamfer by angle", self._chamfer_angle),
            ("chamfer by two distances", self._chamfer_distance_distance),
            ("chamfer with equal distances", self._chamfer_equal),
            ("fillet without constrained corners", self._fillet_free),
            ("offset one way", self._offset),
            ("offset both ways", self._offset_both),
            ("offset as construction geometry", self._offset_construction),
            ("mirror a circle about a centerline", self._mirror),
            ("split a line at a point", self._split),
            ("trim two lines to a corner", self._trim),
            ("extend a line to the next entity", self._extend),
            ("linear pattern grid", self._linear_grid),
            ("linear pattern folded onto one line", self._linear_collinear),
            ("circular pattern full turn", self._circular_full),
            ("circular pattern partial, counter clockwise", self._circular_partial),
            ("circular pattern on the top plane", self._circular_top_plane),
            ("split a closed circle at two points", self._split_closed),
            ("scale the selected entities", self._scale),
            ("mark construction geometry", self._construction_on),
            ("return one entity to normal geometry", self._construction_off),
            ("rotate the selected entities", self._rotate),
            ("rotate a profile and extrude it", self._rotate_and_extrude),
            ("add, re-add and delete sketch relations", self._relations),
            ("relation added and status reported", self._relation_status),
            ("driving dimension resizes a line and defines it", self._dimension),
        ]

    # -- fillet and chamfer ------------------------------------------------
    def _fillet(self):
        sketch = self._rectangle((0, 0))
        self.assertEqual((4, 0), self.counts(sketch))
        self._result(sketch_fillet(self.automation, sketch, ["Line1", "Line2"],
                                   radius=8, unit="mm"))
        self.assertEqual((4, 1), self.counts(sketch))

    def _fillet_free(self):
        sketch = self._rectangle((0, 1))
        self._result(sketch_fillet(self.automation, sketch, ["Line1", "Line2"],
                                   radius=5, constrained_corners=False,
                                   unit="mm"))
        self.assertEqual((4, 1), self.counts(sketch))

    def _chamfer_angle(self):
        sketch = self._rectangle((1, 0))
        self._result(sketch_chamfer(self.automation, sketch, ["Line1", "Line2"],
                                    distance=6, mode="distance_angle",
                                    angle_deg=45, unit="mm"))
        self.assertEqual((5, 0), self.counts(sketch))

    def _chamfer_distance_distance(self):
        sketch = self._rectangle((2, 0))
        self._result(sketch_chamfer(self.automation, sketch, ["Line1", "Line2"],
                                    distance=6, distance2=9,
                                    mode="distance_distance", unit="mm"))
        self.assertEqual((5, 0), self.counts(sketch))

    def _chamfer_equal(self):
        sketch = self._rectangle((3, 0))
        self._result(sketch_chamfer(self.automation, sketch, ["Line1", "Line2"],
                                    distance=6, mode="distance_equal", unit="mm"))
        self.assertEqual((5, 0), self.counts(sketch))

    # -- offset ------------------------------------------------------------
    def _offset(self):
        sketch = self._rectangle((1, 1))
        self._result(offset_entities(
            self.automation, sketch, ["Line1", "Line2", "Line3", "Line4"],
            offset=5, unit="mm"))
        self.assertEqual((8, 0), self.counts(sketch))

    def _offset_both(self):
        sketch = self._rectangle((2, 1))
        self._result(offset_entities(
            self.automation, sketch, ["Line1", "Line2", "Line3", "Line4"],
            offset=5, both_directions=True, unit="mm"))
        self.assertEqual((12, 0), self.counts(sketch))

    def _offset_construction(self):
        sketch = self._rectangle((3, 1))
        self._result(offset_entities(
            self.automation, sketch, ["Line1", "Line2", "Line3", "Line4"],
            offset=5, make_construction=True, unit="mm"))
        self.assertEqual((8, 0), self.counts(sketch))
        self.assertEqual(4, self.construction_count(sketch))

    # -- mirror, split, trim, extend ---------------------------------------
    def _mirror(self):
        ox, oy = zone(0, 2)
        sketch = self.new_sketch()
        axis = self.automation.draw_centerline(ox, oy - 30, ox, oy + 30, "mm")
        self.assertTrue(axis["success"], axis["message"])
        circle = self.automation.draw_circle(ox + 20, oy, 8, "mm")
        self.assertTrue(circle["success"], circle["message"])
        self.exit_sketch()

        self._result(sketch_mirror(self.automation, sketch, ["Arc1"],
                                   mirror_entity="Line1"))
        self.assertEqual((1, 2), self.counts(sketch))
        self.assertEqual(sorted([(ox + 20.0, oy), (ox - 20.0, oy)]),
                         sorted(self.centres_mm(sketch)))

    def _split(self):
        ox, oy = zone(1, 2)
        sketch = self.new_sketch()
        drawn = self.automation.draw_line(ox - 30, oy, ox + 30, oy, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()

        self._result(split_entities(self.automation, sketch, ["Line1"],
                                    x=ox, y=oy, unit="mm"))
        self.assertEqual((2, 0), self.counts(sketch))

    def _trim(self):
        ox, oy = zone(2, 2)
        sketch = self.new_sketch()
        first = self.automation.draw_line(ox - 25, oy, ox + 25, oy, "mm")
        self.assertTrue(first["success"], first["message"])
        second = self.automation.draw_line(ox, oy - 20, ox, oy + 20, "mm")
        self.assertTrue(second["success"], second["message"])
        self.exit_sketch()
        self.assertEqual([50.0, 40.0], self.segment_lengths_mm(sketch))

        self._result(trim_entities(self.automation, sketch, ["Line1", "Line2"],
                                   "corner"))
        self.assertEqual([25.0, 20.0], self.segment_lengths_mm(sketch))

    def _extend(self):
        ox, oy = zone(3, 2)
        sketch = self.new_sketch()
        first = self.automation.draw_line(ox - 30, oy, ox - 10, oy, "mm")
        self.assertTrue(first["success"], first["message"])
        second = self.automation.draw_line(ox + 10, oy - 10, ox + 10, oy + 10, "mm")
        self.assertTrue(second["success"], second["message"])
        self.exit_sketch()
        self.assertEqual([20.0, 20.0], self.segment_lengths_mm(sketch))

        self._result(extend_entities(self.automation, sketch, ["Line1"],
                                     pick=[ox - 10, oy, 0]))
        self.assertEqual([40.0, 20.0], self.segment_lengths_mm(sketch))

    # -- patterns ----------------------------------------------------------
    def _linear_grid(self):
        ox, oy = zone(0, 3)
        sketch = self._circle((0, 3), dx=0, dy=0, radius=5)
        self._result(sketch_pattern_linear(
            self.automation, sketch, ["Arc1"], spacing_x=20, spacing_y=15,
            count_x=2, count_y=3, unit="mm"))
        self.assertEqual((0, 6), self.counts(sketch))
        self.assertEqual(
            sorted([(ox, oy), (ox + 20, oy), (ox, oy + 15),
                    (ox + 20, oy + 15), (ox, oy + 30), (ox + 20, oy + 30)]),
            sorted(self.centres_mm(sketch)))

    def _linear_collinear(self):
        """A zero second angle folds the second row onto the same line."""
        ox, oy = zone(1, 3)
        sketch = self._circle((1, 3), dx=0, dy=0, radius=5)
        self._result(sketch_pattern_linear(
            self.automation, sketch, ["Arc1"], spacing_x=20, spacing_y=15,
            count_x=2, count_y=2, angle_y_deg=0, unit="mm"))
        centres = self.centres_mm(sketch)
        self.assertEqual(4, len(centres))
        self.assertTrue(all(abs(y - oy) < 1e-6 for _x, y in centres), centres)
        self.assertEqual([ox, ox + 15, ox + 20, ox + 35],
                         sorted(x for x, _y in centres))

    def _circular_full(self):
        ox, oy = zone(2, 3)
        sketch = self._circle((2, 3), dx=20, dy=0, radius=4)
        result = self._result(sketch_pattern_circular(
            self.automation, sketch, ["Arc1"], count=4, center_x=ox,
            center_y=oy, unit="mm"))
        self.assertEqual((0, 4), self.counts(sketch))
        self.assertAlmostEqual(20.0, result["data"]["arc_radius"], places=6)
        self.assertAlmostEqual(180.0, result["data"]["arc_angle_deg"], places=6)
        self.assertEqual(
            sorted([(ox + 20, oy), (ox, oy + 20), (ox - 20, oy),
                    (ox, oy - 20)]),
            sorted(self.centres_mm(sketch)))

    def _circular_partial(self):
        ox, oy = zone(3, 3)
        sketch = self._circle((3, 3), dx=20, dy=0, radius=4)
        self._result(sketch_pattern_circular(
            self.automation, sketch, ["Arc1"], count=3, total_angle_deg=90,
            center_x=ox, center_y=oy, unit="mm"))
        expected = [(ox + 20, oy)]
        for index in range(1, 3):
            angle = math.radians(30.0 * index)
            expected.append((round(ox + 20.0 * math.cos(angle), 3),
                             round(oy + 20.0 * math.sin(angle), 3)))
        self.assertEqual(sorted(expected), sorted(self.centres_mm(sketch)))

    # -- closed split, scale and construction ------------------------------
    def _split_closed(self):
        ox, oy = zone(0, 4)
        sketch = self.new_sketch()
        drawn = self.automation.draw_circle(ox, oy, 10, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()
        self.assertEqual((0, 1), self.counts(sketch))

        self._result(split_entities(self.automation, sketch, ["Arc1"],
                                    x=ox + 10, y=oy, x2=ox, y2=oy + 10,
                                    unit="mm"))
        self.assertEqual((0, 2), self.counts(sketch))

    def _scale(self):
        ox, oy = zone(1, 4)
        sketch = self.new_sketch()
        drawn = self.automation.draw_line(ox - 20, oy, ox + 20, oy, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()
        self.assertEqual([40.0], self.segment_lengths_mm(sketch))

        self._result(scale_entities(self.automation, sketch, ["Line1"], 2.0))
        self.assertEqual([80.0], self.segment_lengths_mm(sketch))

    def _construction_on(self):
        ox, oy = zone(2, 4)
        sketch = self.new_sketch()
        first = self.automation.draw_line(ox - 20, oy - 10, ox + 20, oy - 10, "mm")
        self.assertTrue(first["success"], first["message"])
        second = self.automation.draw_line(ox, oy - 20, ox, oy + 20, "mm")
        self.assertTrue(second["success"], second["message"])
        self.exit_sketch()
        self.assertEqual(0, self.construction_count(sketch))

        self._result(toggle_construction(self.automation, sketch,
                                         ["Line1", "Line2"], construction=True))
        self.assertEqual(2, self.construction_count(sketch))

    def _construction_off(self):
        ox, oy = zone(3, 4)
        sketch = self.new_sketch()
        drawn = self.automation.draw_line(ox - 20, oy, ox + 20, oy, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()

        self._result(toggle_construction(self.automation, sketch, ["Line1"]))
        self.assertEqual(1, self.construction_count(sketch))
        self._result(toggle_construction(self.automation, sketch, ["Line1"]))
        self.assertEqual(0, self.construction_count(sketch))

    # -- rotation ----------------------------------------------------------
    def _rotate(self):
        """The frame changes; the segment lengths deliberately do not."""
        ox, oy = zone(0, 5)
        sketch = self.new_sketch()
        drawn = self.automation.draw_line(ox, oy, ox + 30, oy, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        circle = self.automation.draw_circle(ox + 30, oy, 10, "mm")
        self.assertTrue(circle["success"], circle["message"])
        self.exit_sketch()
        before_frame = self.sketch_transform(sketch)
        before_lengths = self.segment_lengths_mm(sketch)

        self._result(rotate_entities(self.automation, sketch, ["Line1", "Arc1"],
                                     angle_deg=90, center_x=ox, center_y=oy,
                                     unit="mm"))

        self.assertNotEqual(before_frame, self.sketch_transform(sketch))
        self.assertEqual(before_lengths, self.segment_lengths_mm(sketch))

    def _rotate_and_extrude(self):
        """A measurable proof: the 40x20 profile swaps its axes in the body box."""
        ox, oy = zone(1, 5)
        sketch = self.new_sketch()
        drawn = self.automation.draw_rectangle(
            ox + 10, oy - 30, ox + 50, oy - 10, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()

        self._result(rotate_entities(
            self.automation, sketch,
            ["Line1", "Line2", "Line3", "Line4"],
            angle_deg=90, center_x=ox, center_y=oy, unit="mm"))

        extrusion = self.automation.extrude_sketch(5, False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        box = self.body_box_mm()[0]
        # The 40 mm edge now runs along the axis the 20 mm edge used to hold.
        self.assertAlmostEqual(20.0, box[4] - box[1], places=3)
        self.assertAlmostEqual(40.0, box[5] - box[2], places=3)

    # -- relation steps ----------------------------------------------------
    def _relations(self):
        """Two non-parallel lines: add one, re-add (ignored), delete all."""
        ox, oy = zone(2, 5)
        sketch = self.new_sketch()
        first = self.automation.draw_line(ox - 30, oy - 20, ox - 10, oy + 10, "mm")
        second = self.automation.draw_line(ox + 10, oy - 20, ox + 30, oy - 5, "mm")
        self.assertTrue(first["success"], first["message"])
        self.assertTrue(second["success"], second["message"])
        self.exit_sketch()

        before = self._result(get_sketch_relations(self.automation, sketch))
        self.assertNotIn("parallel", before["data"]["relation_counts"])

        self._result(add_sketch_relation(self.automation, sketch,
                                         ["Line1", "Line2"], "parallel"))

        after = self._result(get_sketch_relations(self.automation, sketch))
        self.assertEqual(1, after["data"]["relation_counts"].get("parallel"))
        self.assertEqual(before["data"]["relation_count"] + 1,
                         after["data"]["relation_count"])

        # SolidWorks ignores a relation the geometry already satisfies, and the
        # tool reports that instead of pretending it worked.
        redundant = add_sketch_relation(self.automation, sketch,
                                        ["Line1", "Line2"], "parallel")
        self.assertFalse(redundant["success"], redundant["message"])
        self.assertEqual("RELATION_NOT_ADDED", redundant["data"]["code"])

        self._result(delete_sketch_relations(self.automation, sketch, all=True))
        cleared = self._result(get_sketch_relations(self.automation, sketch))
        self.assertEqual(0, cleared["data"]["relation_count"])

    def _relation_status(self):
        """A fixed line still reports under-constrained in SW 2025 SP1.1.

        Measured: adding sgFIXED changes the relation list (type 17 appears) but
        GetConstrainedStatus stays 2 (under).  A driving dimension is what makes
        this sketch fully defined; see the dimension step.
        """
        ox, oy = zone(3, 5)
        sketch = self.new_sketch()
        line = self.automation.draw_line(ox - 25, oy, ox + 25, oy, "mm")
        self.assertTrue(line["success"], line["message"])
        self.exit_sketch()

        before = self._result(get_sketch_relations(self.automation, sketch))
        self.assertFalse(before["data"]["fully_defined"])
        self._result(add_sketch_relation(self.automation, sketch, ["Line1"],
                                         "fixed"))
        after = self._result(get_sketch_relations(self.automation, sketch))

        self.assertIn("fixed", after["data"]["relation_counts"])
        self.assertEqual("under_constrained", after["data"]["constrained_status"])
        self.assertFalse(after["data"]["fully_defined"])

    def _dimension(self):
        """A driving dimension resizes the line and makes the sketch defined.

        The line starts at the sketch origin and is drawn with inference on
        (exact_geometry=False), so it picks up the coincident and horizontal
        relations; those plus the length dimension leave no degree of freedom,
        which is what takes the status to fully constrained.
        """
        sketch = self.new_sketch(exact_geometry=False)
        line = self.automation.draw_line(0, 0, 50, 0, "mm")
        self.assertTrue(line["success"], line["message"])
        self.exit_sketch()

        before = self._result(get_sketch_relations(self.automation, sketch))
        self.assertFalse(before["data"]["fully_defined"])

        result = self._result(add_sketch_dimension(
            self.automation, sketch, ["Line1"], 25, -15, value=30, unit="mm"))

        self.assertTrue(result["data"]["geometry_changed"])
        self.assertEqual(30.0, result["data"]["dimension_value"])
        self.assertEqual([30.0], self.segment_lengths_mm(sketch))

        after = self._result(get_sketch_relations(self.automation, sketch))
        self.assertTrue(after["data"]["fully_defined"],
                        after["data"]["constrained_status"])

        # Nothing may be left waiting for the user to confirm.
        command = com(self.automation.app, "GetRunningCommandInfo")
        self.assertNotEqual("Dimension", str(command[1]).strip(),
                            "SolidWorks is waiting for a dimension value")

    def _circular_top_plane(self):
        """A top-plane sketch is deliberately placed clear of the front grid."""
        centre = (270.0, 0.0)
        sketch = self.new_sketch("Top")
        drawn = self.automation.draw_circle(centre[0] + 20, centre[1] + 10, 4, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()

        result = self._result(sketch_pattern_circular(
            self.automation, sketch, ["Arc1"], count=4, center_x=centre[0],
            center_y=centre[1], unit="mm"))
        self.assertEqual((0, 4), self.counts(sketch))
        radius = math.hypot(20.0, 10.0)
        phase = math.atan2(10.0, 20.0)
        expected = []
        for index in range(4):
            angle = phase + index * math.radians(90.0)
            expected.append((round(centre[0] + radius * math.cos(angle), 2),
                             round(centre[1] + radius * math.sin(angle), 2)))
        observed = [(round(u, 2), round(v, 2))
                    for u, v in self.centres_mm(sketch)]
        self.assertEqual(sorted(expected), sorted(observed))
        self.assertAlmostEqual(radius, result["data"]["arc_radius"], places=4)


if __name__ == "__main__":
    unittest.main()
