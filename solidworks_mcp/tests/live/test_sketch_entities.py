"""Live COM tests for the sketch entity tools (M1.1).

One scratch part is built in an explicit sequence: one step per entity tool,
each step owning its own zone of the sketch plane, each step screenshotted
before the part is closed.  An equation-driven curve follows, then a plate
profile that is extruded; the plate's measured volume proves that the whole
profile (outline *and* holes) was used, not just the first loop.
"""

import math
import unittest

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only, zone
from solidworks_mcp.tools.sketch_create import (
    create_3d_sketch, create_sketch_on_plane,
)
from solidworks_mcp.tools.sketch_entities import (
    convert_entities, draw_arc_slot, draw_arc_slot_3point,
    draw_center_rectangle, draw_centerline, draw_circle_radius, draw_ellipse,
    draw_elliptical_arc, draw_equation_curve, draw_equation_curve_3d,
    draw_parallelogram, draw_parabola,
    draw_point, draw_rectangle_3point_center, draw_rectangle_3point_corner,
    draw_sketch_text, draw_tangent_arc,
)


# The plate step sits two rows below the last entity step.
PLATE_ZONE = (0, -450)
PLATE = dict(width=120.0, height=70.0, depth=8.0, hole_radius=4.0,
             holes=((-45, -22), (45, -22), (-45, 22), (45, 22), (0, 0)))


@live_only
class LiveSketchEntityTests(ScratchPartTestCase):
    def test_every_entity_builds_a_complex_plate_without_saving(self):
        self.open_scratch_part()

        cases = self._entity_cases()
        self.assertEqual(21, len(cases), "every entity tool needs one step")
        for index, (purpose, plane, calls, expectations) in enumerate(cases, 1):
            with self.subTest(step=index, purpose=purpose):
                self._step(index, purpose, plane, calls, expectations)

        self._equation_curve_step(len(cases) + 1)
        self._text_step(len(cases) + 2)
        self._plate_step(len(cases) + 3)
        self._plane_step(len(cases) + 5)
        self._convert_step(len(cases) + 6)
        self._sketch_3d_step(len(cases) + 7)
        self._equation_3d_step(len(cases) + 8)
        self.assert_unsaved()

    def _step(self, index, purpose, plane, calls, expectations):
        try:
            sketch = self.new_sketch(plane)
            for call in calls:
                result = call()
                self.assertTrue(result["success"], result["message"])
        finally:
            self.close_sketch()
        for expectation in expectations:
            self._check(sketch, expectation)
        self.capture(index, purpose)

    # -- the ordered sequence ----------------------------------------------
    def _entity_cases(self):
        """(purpose, plane, calls, expectations) in build order."""
        automation = self.automation
        cases = []

        def add(purpose, plane, calls, expectations):
            cases.append((purpose, plane, calls, expectations))

        def at(position, x, y):
            ox, oy = zone(*position)
            return ox + x, oy + y

        add("open lines at three angles", "Front",
            [lambda: automation.draw_line(*at((0, 0), 0, 20), *at((0, 0), 10, -20), "mm"),
             lambda: automation.draw_line(*at((0, 0), 20, -20), *at((0, 0), 30, 10), "mm"),
             lambda: automation.draw_line(*at((0, 0), -25, -15), *at((0, 0), -5, 20), "mm")],
            [("counter", "GetLineCount", 3)])
        add("reference centerlines", "Front",
            [lambda: automation.draw_centerline(*at((1, 0), 0, -30), *at((1, 0), 0, 30), "mm"),
             lambda: automation.draw_centerline(*at((1, 0), -30, 0), *at((1, 0), 30, 0), "mm")],
            [("counter", "GetLineCount", 2)])
        add("circles by an edge point", "Front",
            [lambda: automation.draw_circle(*at((2, 0), -12, 0), 8, "mm"),
             lambda: automation.draw_circle(*at((2, 0), 12, 0), 12, "mm")],
            [("counter", "GetArcCount", 2)])
        add("circles by radius", "Front",
            [lambda: draw_circle_radius(automation, *at((3, 0), -14, 0), 10, "mm"),
             lambda: draw_circle_radius(automation, *at((3, 0), 14, 0), 6, "mm")],
            [("counter", "GetArcCount", 2)])
        add("rectangle from two corners", "Front",
            [lambda: automation.draw_rectangle(*at((0, 1), -30, -18), *at((0, 1), 10, 18), "mm")],
            [("counter", "GetLineCount", 4)])
        add("rectangle from its centre", "Front",
            [lambda: draw_center_rectangle(automation, *at((1, 1), 0, 0), 44, 30, "mm")],
            [("counter", "GetLineCount", 6), ("construction", 2),
             # Two diagonals, then the 44 x 30 sides: the size is not doubled.
             ("lengths", (53.254, 53.254, 44.0, 44.0, 30.0, 30.0))])
        add("rectangle from three corners", "Front",
            [lambda: draw_rectangle_3point_corner(
                automation, *at((2, 1), -25, -15), *at((2, 1), -25, 15),
                *at((2, 1), 15, 15), "mm")],
            [("counter", "GetLineCount", 4)])
        add("rectangle from three points, centred", "Front",
            [lambda: draw_rectangle_3point_center(
                automation, *at((3, 1), -20, 0), *at((3, 1), 20, 0),
                *at((3, 1), -20, 14), "mm")],
            [("counter", "GetLineCount", 6), ("construction", 2)])
        add("parallelogram", "Front",
            [lambda: draw_parallelogram(
                automation, *at((0, 2), -20, -15), *at((0, 2), 20, -15),
                *at((0, 2), 0, 15), "mm")],
            [("counter", "GetLineCount", 4)])
        add("arcs from a centre and two angles", "Front",
            [lambda: automation.draw_arc_center(*at((1, 2), 0, 0), 16, 0, 90, "mm"),
             lambda: automation.draw_arc_center(*at((1, 2), 0, 0), 24, 90, 200, "mm")],
            [("counter", "GetArcCount", 2)])
        add("arcs through three points", "Front",
            [lambda: automation.draw_arc_3point(
                *at((2, 2), -25, -5), *at((2, 2), 25, -5), *at((2, 2), 0, 15), "mm"),
             lambda: automation.draw_arc_3point(
                *at((2, 2), -25, 15), *at((2, 2), 25, 15), *at((2, 2), 0, -10), "mm")],
            [("counter", "GetArcCount", 2)])
        add("tangent arc chain", "Front",
            [lambda: automation.draw_line(*at((3, 2), -25, -10), *at((3, 2), 5, -10), "mm"),
             lambda: draw_tangent_arc(
                automation, *at((3, 2), 5, -10), *at((3, 2), 20, 0), "mm"),
             lambda: draw_tangent_arc(
                automation, *at((3, 2), 20, 0), *at((3, 2), 25, 15), "mm")],
            [("counter", "GetArcCount", 2), ("counter", "GetLineCount", 1)])
        add("spline through points", "Front",
            [lambda: automation.draw_spline(
                [list(at((0, 3), -25, -15)), list(at((0, 3), -10, 15)),
                 list(at((0, 3), 10, -15)), list(at((0, 3), 25, 10))], "mm")],
            [("segments", 1)])
        add("ellipse, one rotated", "Front",
            [lambda: draw_ellipse(automation, *at((1, 3), -14, 0), 12, 6, unit="mm"),
             lambda: draw_ellipse(automation, *at((1, 3), 14, 0), 8, 5,
                                  rotation_deg=45, unit="mm")],
            [("counter", "GetEllipseCount", 2)])
        add("partial elliptical arcs", "Front",
            [lambda: draw_elliptical_arc(
                automation, *at((2, 3), -14, 0), 12, 6, end_angle_deg=180, unit="mm"),
             lambda: draw_elliptical_arc(
                automation, *at((2, 3), 14, 0), 10, 5, end_angle_deg=270, unit="mm")],
            [("counter", "GetEllipseCount", 2)])
        add("parabola from focus and apex", "Front",
            [lambda: draw_parabola(
                automation, *at((3, 3), 0, 0), *at((3, 3), 0, -10),
                *at((3, 3), -20, 10), *at((3, 3), 20, 10), "mm")],
            [("counter", "GetParabolaCount", 1)])
        add("triangle and hexagon", "Front",
            [lambda: automation.draw_polygon(*at((0, 4), -14, 0), 14, 3, "mm"),
             lambda: automation.draw_polygon(*at((0, 4), 14, 0), 12, 6, "mm")],
            [("min_lines", 9)])
        add("sketch points", "Front",
            [lambda: draw_point(automation, *at((1, 4), -15, 0), "mm"),
             lambda: draw_point(automation, *at((1, 4), 0, 12), "mm"),
             lambda: draw_point(automation, *at((1, 4), 15, 0), "mm")],
            [("counter", "GetUserPointsCount", 3)])
        add("straight slots", "Front",
            [lambda: automation.draw_slot(*at((2, 4), -20, -12), *at((2, 4), 15, -12), 8, "mm"),
             lambda: automation.draw_slot(*at((2, 4), 10, 15), *at((2, 4), -20, 15), 6, "mm")],
            [("counter", "GetSketchSlotCount", 2)])
        add("arc slot", "Front",
            [lambda: draw_arc_slot(
                automation, *at((3, 4), 0, -15), *at((3, 4), 25, -15),
                *at((3, 4), 0, 10), 6, "mm")],
            [("counter", "GetSketchSlotCount", 1)])
        add("three point arc slot", "Front",
            [lambda: draw_arc_slot_3point(
                automation, *at((0, 5), -25, -10), *at((0, 5), 0, 10),
                *at((0, 5), 25, -10), 6, "mm")],
            [("counter", "GetSketchSlotCount", 1)])
        return cases

    # -- the piece itself --------------------------------------------------
    def _equation_curve_step(self, index):
        """y = 8*sin(x) over one period; the arc length pins the scale.

        SolidWorks evaluates both the range and the expression in the document
        unit, so the expected length is the arc length of y = 8*sin(x) with x in
        millimetres.  A metre interpretation would be off by a factor of 1000.
        """
        ox, oy = zone(1, 5)
        amplitude = 8.0
        sketch = self.new_sketch("Front")
        result = draw_equation_curve(
            self.automation, f"{amplitude}*sin(x)", ox, ox + 2 * math.pi,
            y_offset=oy, unit="mm")
        self.assertTrue(result["success"], result["message"])
        self.exit_sketch()

        steps = 20000
        span = 2 * math.pi
        expected = sum(
            math.sqrt(1 + (amplitude * math.cos(step * span / steps)) ** 2)
            * span / steps
            for step in range(steps)
        )

        data = result["data"]
        self.assertEqual(1, self.segment_count(sketch))
        self.assertEqual(1, data["spline_count"])
        self.assertEqual("mm", data["document_unit"])
        self.assertAlmostEqual(expected, data["curve_length"],
                               delta=expected * 0.005)
        # The range starts at x = ox, so the curve starts at sin(ox), not at 0.
        self.assertAlmostEqual(ox, data["endpoints"][0][0], places=4)
        self.assertAlmostEqual(oy + amplitude * math.sin(ox),
                               data["endpoints"][0][1], delta=1e-3)
        self.assertAlmostEqual(ox + span, data["endpoints"][1][0], places=3)
        self.assertAlmostEqual(oy + amplitude * math.sin(ox + span),
                               data["endpoints"][1][1], delta=1e-3)
        self.capture(index, "equation driven curve")

    def _text_step(self, index):
        """Sketch text: counted while open and again once the sketch is closed."""
        ox, oy = zone(2, 5)
        sketch = self.new_sketch("Front")

        first = draw_sketch_text(self.automation, "SW MCP", ox, oy, unit="mm")
        second = draw_sketch_text(self.automation, "M1.3", ox, oy - 20, unit="mm")

        self.assertTrue(first["success"], first["message"])
        self.assertTrue(second["success"], second["message"])
        self.assertEqual(1, first["data"]["text_segment_count"])
        self.assertEqual(2, second["data"]["text_segment_count"])
        self.assertTrue(second["data"]["read_back_matches"])
        self.assertEqual("M1.3", second["data"]["stored_text"])
        self.capture(index, "sketch text")

        self.exit_sketch()
        # The text is a durable part of the sketch, not just a returned object.
        segments = list(com(self.sketch(sketch), "GetSketchTextSegments") or [])
        self.assertEqual(2, len(segments))
        for segment in segments:
            self.assertEqual(4, int(com(segment, "GetType")))

    def _plane_step(self, index):
        """A sketch on the Right Plane, not on the Front plane the rest uses."""
        ox, oy = zone(0, 6)
        result = create_sketch_on_plane(self.automation, "Right Plane")
        self.assertTrue(result["success"], result["message"])
        sketch = result["data"]["sketch"]
        self.assertFalse(result["data"]["is_3d"])

        drawn = self.automation.draw_line(ox - 25, oy, ox + 25, oy, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        self.exit_sketch()

        self.assertEqual(1, self.segment_count(sketch))
        self.capture(index, "sketch on the right plane")

    def _convert_step(self, index):
        """Convert a model face, then a single model edge, into a sketch."""
        box = self.body_box_mm()[0]
        mid_x = (box[0] + box[3]) / 2.0
        mid_z = (box[2] + box[5]) / 2.0
        # Middle of the +Y face: a plain rectangle, clear of the holes.
        face_point = [mid_x, box[4], mid_z]
        edge_point = [box[3], box[4], mid_z]

        entered = self.automation.create_sketch_on_face(*face_point, unit="mm")
        self.assertTrue(entered["success"], entered["message"])
        converted = convert_entities(self.automation, faces=[face_point],
                                     unit="mm")
        self.assertTrue(converted["success"], converted["message"])
        self.assertEqual(4, converted["data"]["added"])
        self.capture(index, "converted a model face")
        self.exit_sketch()

        # A single edge, converted into a fresh empty sketch.
        entered = self.automation.create_sketch_on_face(*face_point, unit="mm")
        self.assertTrue(entered["success"], entered["message"])
        single = convert_entities(self.automation, edges=[edge_point],
                                  unit="mm")
        self.assertTrue(single["success"], single["message"])
        self.assertEqual(1, single["data"]["added"])
        self.exit_sketch()

    def _sketch_3d_step(self, index):
        """A 3D sketch accepts world coordinates and survives being closed."""
        result = create_3d_sketch(self.automation)
        self.assertTrue(result["success"], result["message"])
        self.assertTrue(result["data"]["is_3d"])
        sketch = result["data"]["sketch"]

        line = com(com(self.document(), "SketchManager"), "CreateLine",
                   0.0, 0.0, 0.0, 20.0 * 0.001, 30.0 * 0.001, 40.0 * 0.001)
        self.assertIsNotNone(line)
        self.assertEqual(1, self.segment_count(sketch))
        self.capture(index, "3d sketch with a spatial line")
        self.exit_sketch()

        closed = self.sketch(sketch)
        self.assertTrue(bool(com(closed, "Is3D")))
        self.assertEqual(1, self.segment_count(sketch))

    def _equation_3d_step(self, index):
        """One full helix turn over a non-integer range (0..2*pi).

        CreateEquationSpline2 itself rejects that range on a decimal-comma
        locale; the tool remaps t onto 0..1, and the arc length proves it.
        """
        result = create_3d_sketch(self.automation)
        self.assertTrue(result["success"], result["message"])
        sketch = result["data"]["sketch"]
        radius, pitch = 10.0, 12.0
        helix = draw_equation_curve_3d(
            self.automation, f"{radius}*cos(t)", f"{radius}*sin(t)",
            f"{pitch / (2 * math.pi)}*t", 0, 2 * math.pi, x_offset=-200)
        self.assertTrue(helix["success"], helix["message"])
        self.capture(index, "3d equation curve helix")
        self.exit_sketch()

        self.assertEqual(1, self.segment_count(sketch))
        expected = math.hypot(2 * math.pi * radius, pitch)
        self.assertAlmostEqual(expected, helix["data"]["curve_length"],
                               delta=expected * 0.001)
        self.assertEqual([-190.0, 0.0, 0.0], helix["data"]["endpoints"][0])
        self.assertAlmostEqual(pitch, helix["data"]["endpoints"][1][2],
                               places=3)

    def _plate_step(self, index):
        """One closed plate profile with five holes, then a boss extrusion."""
        ox, oy = PLATE_ZONE
        half_w = PLATE["width"] / 2
        half_h = PLATE["height"] / 2

        plate = self.new_sketch("Front")
        outline = self.automation.draw_rectangle(
            ox - half_w, oy - half_h, ox + half_w, oy + half_h, "mm")
        self.assertTrue(outline["success"], outline["message"])
        for dx, dy in PLATE["holes"]:
            hole = draw_circle_radius(self.automation, ox + dx, oy + dy,
                                      PLATE["hole_radius"], "mm")
            self.assertTrue(hole["success"], hole["message"])
        self.exit_sketch()
        self.assertEqual((4, 5), self.counts(plate))
        self.capture(index, "plate profile with five holes")

        extrusion = self.automation.extrude_sketch(PLATE["depth"], False, "mm")
        self.assertTrue(extrusion["success"], extrusion["message"])
        self.assertEqual(1, self.solid_body_count())
        self.assertEqual(1, self.feature_count("Extrusion"))

        # Volume proves every loop of the profile was used, not only the outline.
        expected = (PLATE["width"] * PLATE["height"] * PLATE["depth"]
                    - len(PLATE["holes"]) * math.pi
                    * PLATE["hole_radius"] ** 2 * PLATE["depth"])
        self.assertAlmostEqual(expected, self.total_volume_mm3(), delta=1.0)
        self.capture(index + 1, "extruded plate")


if __name__ == "__main__":
    unittest.main()
