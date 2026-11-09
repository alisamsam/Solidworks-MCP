import math
import types
import unittest

from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sketch_entities import (
    convert_entities, draw_arc_slot, draw_arc_slot_3point,
    draw_center_rectangle, draw_centerline, draw_circle_radius, draw_ellipse,
    draw_elliptical_arc, draw_equation_curve, draw_equation_curve_3d,
    draw_parallelogram, draw_parabola, draw_point,
    draw_rectangle_3point_center, draw_rectangle_3point_corner,
    draw_sketch_text, draw_tangent_arc,
)


EXPECTED_TOOLS = {
    "draw_centerline": [1, 1, 0.0, 2, 2, 0.0],
    "draw_point": [1, 2, 0.0],
    "draw_circle_radius": [1, 2, 0.0, 3],
    "draw_center_rectangle": [2.5, 3.5, 0.0, 4.5, 5.5, 0.0],  # centre, corner
    "draw_rectangle_3point_corner": [1, 2, 0.0, 3, 4, 0.0, 5, 6, 0.0],
    "draw_rectangle_3point_center": [1, 2, 0.0, 3, 4, 0.0, 5, 6, 0.0],
    "draw_parallelogram": [1, 2, 0.0, 3, 4, 0.0, 5, 6, 0.0],
}

# Millimetre arguments reused by the behaviour tests below.
ARGS = {
    "draw_centerline": dict(x1=1, y1=1, x2=2, y2=2),
    "draw_point": dict(x=1, y=2),
    "draw_circle_radius": dict(cx=1, cy=2, radius=3),
    "draw_center_rectangle": dict(cx=2.5, cy=3.5, width=4, height=4),
    "draw_rectangle_3point_corner": dict(x1=1, y1=2, x2=3, y2=4, x3=5, y3=6),
    "draw_rectangle_3point_center": dict(x1=1, y1=2, x2=3, y2=4, x3=5, y3=6),
    "draw_parallelogram": dict(x1=1, y1=2, x2=3, y2=4, x3=5, y3=6),
}

CALLABLES = {
    "draw_centerline": draw_centerline,
    "draw_point": draw_point,
    "draw_circle_radius": draw_circle_radius,
    "draw_center_rectangle": draw_center_rectangle,
    "draw_rectangle_3point_corner": draw_rectangle_3point_corner,
    "draw_rectangle_3point_center": draw_rectangle_3point_center,
    "draw_parallelogram": draw_parallelogram,
}


_DEFAULT_RESULT = object()


class SketchManager:
    def __init__(self, result=_DEFAULT_RESULT):
        self.result = object() if result is _DEFAULT_RESULT else result
        self.calls = []
        self.document = None

    def __getattr__(self, name):
        if not name.startswith("Create"):
            raise AttributeError(name)

        def record(_bound_self, *args):
            self.calls.append((name, args))
            if self.document is not None and name in (
                    "CreateEquationSpline", "CreateEquationSpline2"):
                self.document.segments.append(Segment(3))
            return self.result

        # Return a bound method, exactly like a real COM method wrapper:
        # comutil.com() only invokes the member when inspect.ismethod() is true.
        return types.MethodType(record, self)


class Segment:
    def __init__(self, kind):
        self.kind = kind

    def GetType(self):
        return self.kind


class SketchPoint:
    def __init__(self, x, y, z=0.0):
        self.X = x
        self.Y = y
        self.Z = z


class Spline:
    def __init__(self, length=0.0, points=()):
        self.length = length
        self.points = list(points)

    def GetLength(self):
        return self.length

    def GetPoints2(self):
        return list(self.points)


class Sketch:
    def __init__(self, document):
        self.document = document

    def GetSketchSegments(self):
        return list(self.document.segments)

    def GetSketchTextSegments(self):
        return list(self.document.text_segments)

    def Is3D(self):
        return self.document.is_3d


class SketchText:
    def __init__(self, text):
        self.text = text

    def Text(self):
        return self.text


class Extension:
    def __init__(self, document, select_ok=True):
        self.document = document
        self.select_ok = select_ok
        self.select_calls = []

    def SelectByID2(self, name, type_name, x, y, z, append, mark, callout,
                    options):
        self.select_calls.append((name, type_name, append, x, y, z))
        if not self.select_ok:
            return False
        self.document.selected.append((type_name, x, y, z))
        return True


class SelectionManager:
    def __init__(self, document):
        self.document = document

    def GetSelectedObjectCount2(self, mark):
        return self.document.selected_count


class Document:
    def __init__(self, sketch_result=_DEFAULT_RESULT, linear_unit=0):
        self.linear_unit = linear_unit
        self.segments = []
        self.SketchManager = SketchManager(sketch_result)
        self.SketchManager.document = self
        self.text_calls = []
        self.text_ok = True
        self.text_registers = True
        self.text_segments = []
        self.Extension = Extension(self)
        self.SelectionManager = SelectionManager(self)
        self.selected = []
        self.selected_count = 0
        self.active_sketch = True
        self.is_3d = False
        self.converted_segments = 0
        self.convert_ok = True
        self.convert_calls = []

    def SketchUseEdge2(self, chain):
        self.convert_calls.append(chain)
        if not self.convert_ok:
            return False
        for _ in range(self.converted_segments):
            self.segments.append(Segment(0))
        return True

    def ClearSelection2(self, clear_all):
        self.selected = []
        return True

    def InsertSketchText(self, x, y, z, text, alignment, flip, mirror,
                         width_factor, spacing):
        self.text_calls.append((x, y, z, text, alignment, flip, mirror,
                                width_factor, spacing))
        if not self.text_ok:
            return None
        if self.text_registers:
            self.text_segments.append(SketchText(text))
        return SketchText(text)

    def GetUnits(self):
        return (self.linear_unit, 0)

    def GetActiveSketch2(self):
        if not self.active_sketch:
            return None
        return Sketch(self)


class Units:
    FACTORS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "inch": 0.0254}

    def to_meters(self, value, unit):
        return value * self.FACTORS[unit]


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self._units = Units()
        self.active_doc_calls = 0

    def get_active_doc(self):
        self.active_doc_calls += 1
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "data": data or {},
        }


class SketchEntityRegistrationTests(unittest.TestCase):
    def test_all_entity_tools_are_registered_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        for name in EXPECTED_TOOLS:
            self.assertIn(name, tools)
            self.assertIs(OperationClass.MUTATE, operation_class_for(name))

    def test_the_equation_curve_tool_is_registered_as_a_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("draw_equation_curve", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("draw_equation_curve"))
        properties = tools["draw_equation_curve"].inputSchema["properties"]
        self.assertEqual(["mm", "cm", "m", "inch"], properties["unit"]["enum"])
        self.assertEqual(["expression", "range_start", "range_end"],
                         tools["draw_equation_curve"].inputSchema["required"])

    def test_unit_argument_accepts_the_documented_units(self):
        tools = {item.name: item for item in registered_tools()}

        for name in EXPECTED_TOOLS:
            unit = tools[name].inputSchema["properties"]["unit"]
            self.assertEqual(["mm", "cm", "m", "inch"], unit["enum"])
            self.assertEqual("mm", unit["default"])


class SketchEntityBehaviorTests(unittest.TestCase):
    def test_entities_convert_millimetres_to_metres(self):
        for name, expected in EXPECTED_TOOLS.items():
            with self.subTest(tool=name):
                automation = Automation()

                result = CALLABLES[name](automation, **ARGS[name])

                self.assertTrue(result["success"], result["message"])
                method, arguments = automation.document.SketchManager.calls[0]
                self.assertTrue(method.startswith("Create"))
                for actual, wanted in zip(arguments, expected):
                    self.assertAlmostEqual(wanted * 0.001, actual, places=12)
                self.assertEqual("mm", result["data"]["unit"])

    def test_center_rectangle_passes_the_centre_and_one_corner(self):
        """Live: two opposite corners doubled the rectangle (1600000 mm3 box)."""
        automation = Automation()

        result = draw_center_rectangle(automation, cx=2.5, cy=3.5, width=4, height=4)

        self.assertTrue(result["success"], result["message"])
        method, arguments = automation.document.SketchManager.calls[0]
        self.assertEqual("CreateCenterRectangle", method)
        self.assertAlmostEqual(0.0025, arguments[0], places=12)
        self.assertAlmostEqual(0.0035, arguments[1], places=12)
        self.assertAlmostEqual(0.0045, arguments[3], places=12)
        self.assertAlmostEqual(0.0055, arguments[4], places=12)

    def test_non_positive_radius_is_rejected_before_com(self):
        automation = Automation()

        result = draw_circle_radius(automation, radius=0)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])
        self.assertEqual(0, automation.active_doc_calls)
        self.assertEqual([], automation.document.SketchManager.calls)

    def test_non_positive_rectangle_side_is_rejected_before_com(self):
        automation = Automation()

        result = draw_center_rectangle(automation, width=-5, height=10)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])
        self.assertEqual([], automation.document.SketchManager.calls)

    def test_failed_create_reports_a_sketch_error(self):
        automation = Automation(Document(sketch_result=None))

        result = draw_point(automation, x=1, y=2)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swSketchError, result["error_code"])


class EllipseBehaviorTests(unittest.TestCase):
    def test_ellipse_axis_points_follow_the_rotation(self):
        automation = Automation()

        result = draw_ellipse(automation, cx=0, cy=0, major_radius=10,
                              minor_radius=5, rotation_deg=90)

        self.assertTrue(result["success"], result["message"])
        method, arguments = automation.document.SketchManager.calls[0]
        self.assertEqual("CreateEllipse", method)
        # Major axis at 90 degrees: (0, +0.010); minor axis at 180 degrees: (-0.005, 0).
        self.assertAlmostEqual(0.0, arguments[3], places=12)
        self.assertAlmostEqual(0.010, arguments[4], places=12)
        self.assertAlmostEqual(-0.005, arguments[6], places=12)
        self.assertAlmostEqual(0.0, arguments[7], places=12)

    def test_ellipse_rejects_non_positive_radii(self):
        automation = Automation()

        result = draw_ellipse(automation, major_radius=10, minor_radius=0)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])
        self.assertEqual([], automation.document.SketchManager.calls)

    def test_elliptical_arc_direction_follows_the_clockwise_flag(self):
        counter_clockwise = Automation()
        clockwise = Automation()

        draw_elliptical_arc(counter_clockwise, major_radius=10, minor_radius=5,
                            end_angle_deg=90)
        draw_elliptical_arc(clockwise, major_radius=10, minor_radius=5,
                            end_angle_deg=90, counter_clockwise=False)

        self.assertEqual(1, counter_clockwise.document.SketchManager.calls[0][1][-1])
        self.assertEqual(-1, clockwise.document.SketchManager.calls[0][1][-1])

    def test_elliptical_arc_end_point_lies_on_the_ellipse(self):
        automation = Automation()

        draw_elliptical_arc(automation, cx=1, cy=2, major_radius=10, minor_radius=5,
                            end_angle_deg=90)

        _method, arguments = automation.document.SketchManager.calls[0]
        end_x, end_y = arguments[12], arguments[13]
        # At 90 degrees the parametric point is the minor axis: center + (0, b).
        self.assertAlmostEqual(0.001, end_x, places=12)
        self.assertAlmostEqual(0.002 + 0.005, end_y, places=12)

    def test_elliptical_arc_rejects_out_of_range_end_angle(self):
        automation = Automation()

        result = draw_elliptical_arc(automation, major_radius=10, minor_radius=5,
                                     end_angle_deg=400)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])


class ParabolaBehaviorTests(unittest.TestCase):
    def test_parabola_passes_focus_apex_and_end_points(self):
        automation = Automation()

        result = draw_parabola(automation, focus_x=0, focus_y=5, apex_x=0, apex_y=0,
                               start_x=-10, start_y=5, end_x=10, end_y=5)

        self.assertTrue(result["success"], result["message"])
        method, arguments = automation.document.SketchManager.calls[0]
        self.assertEqual("CreateParabola", method)
        self.assertAlmostEqual(0.0, arguments[0], places=12)
        self.assertAlmostEqual(0.005, arguments[1], places=12)
        self.assertAlmostEqual(-0.010, arguments[6], places=12)

    def test_parabola_rejects_coincident_focus_and_apex(self):
        automation = Automation()

        result = draw_parabola(automation, focus_x=0, focus_y=0, apex_x=0, apex_y=0,
                               start_x=-10, start_y=5, end_x=10, end_y=5)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])
        self.assertEqual([], automation.document.SketchManager.calls)

    def test_parabola_rejects_coincident_end_points(self):
        automation = Automation()

        result = draw_parabola(automation, focus_x=0, focus_y=5, apex_x=0, apex_y=0,
                               start_x=1, start_y=1, end_x=1, end_y=1)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])


class TangentArcAndSlotBehaviorTests(unittest.TestCase):
    def test_tangent_arc_is_registered_as_a_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        for name in ("draw_tangent_arc", "draw_arc_slot", "draw_arc_slot_3point"):
            self.assertIn(name, tools)
            self.assertIs(OperationClass.MUTATE, operation_class_for(name))

    def test_tangent_arc_passes_zero_arc_type_after_the_coordinates(self):
        automation = Automation()

        result = draw_tangent_arc(automation, start_x=20, start_y=0, end_x=30, end_y=10)

        self.assertTrue(result["success"], result["message"])
        method, arguments = automation.document.SketchManager.calls[0]
        self.assertEqual("CreateTangentArc", method)
        self.assertEqual(7, len(arguments))
        self.assertAlmostEqual(0.020, arguments[0], places=12)
        self.assertAlmostEqual(0.030, arguments[3], places=12)
        self.assertEqual(0, arguments[6])

    def test_tangent_arc_rejects_coincident_points_before_com(self):
        automation = Automation()

        result = draw_tangent_arc(automation, start_x=5, start_y=5, end_x=5, end_y=5)

        self.assertFalse(result["success"])
        self.assertEqual(SwErrors.swInvalidInput, result["error_code"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_arc_slot_splits_non_coordinate_arguments_around_the_geometry(self):
        automation = Automation()

        result = draw_arc_slot(automation, center_x=0, center_y=0, start_x=10, start_y=0,
                              end_x=0, end_y=10, width=4)

        self.assertTrue(result["success"], result["message"])
        method, arguments = automation.document.SketchManager.calls[0]
        self.assertEqual("CreateSketchSlot", method)
        # (CreationType, LengthType, Width, center, start, end, direction, add-dim)
        self.assertEqual(2, arguments[0])
        self.assertEqual(0, arguments[1])
        self.assertAlmostEqual(0.004, arguments[2], places=12)
        self.assertAlmostEqual(0.0, arguments[3], places=12)
        self.assertAlmostEqual(0.010, arguments[6], places=12)
        self.assertAlmostEqual(0.0, arguments[9], places=12)
        self.assertAlmostEqual(0.010, arguments[10], places=12)
        self.assertEqual((1, False), arguments[12:14])

    def test_3point_arc_slot_uses_the_three_point_creation_type(self):
        automation = Automation()

        result = draw_arc_slot_3point(automation, x1=-10, y1=0, x2=0, y2=8, x3=10, y3=0,
                                     width=3)

        self.assertTrue(result["success"], result["message"])
        _method, arguments = automation.document.SketchManager.calls[0]
        self.assertEqual(3, arguments[0])
        self.assertAlmostEqual(0.003, arguments[2], places=12)

    def test_arc_slot_rejects_zero_width_and_coincident_points(self):
        zero_width = Automation()
        coincident = Automation()

        width_result = draw_arc_slot(zero_width, center_x=0, center_y=0, start_x=10,
                                     start_y=0, end_x=0, end_y=10, width=0)
        point_result = draw_arc_slot_3point(coincident, x1=1, y1=1, x2=1, y2=1,
                                            x3=1, y3=1, width=3)

        self.assertFalse(width_result["success"])
        self.assertFalse(point_result["success"])
        self.assertEqual([], zero_width.document.SketchManager.calls)
        self.assertEqual([], coincident.document.SketchManager.calls)


class EquationCurveTests(unittest.TestCase):
    """The live call takes the range in the document unit and the offsets in
    metres; the measured evidence is in docs/api-findings.md section 26."""

    @staticmethod
    def sine():
        return Spline(0.0076404, [SketchPoint(0.0, 0.0), SketchPoint(0.0062832, 0.0)])

    def test_range_uses_the_document_unit_while_the_offsets_use_metres(self):
        document = Document(self.sine(), linear_unit=3)  # an inch document
        automation = Automation(document)

        result = draw_equation_curve(automation, "sin(x)", 0, 25.4, x_offset=1,
                                     y_offset=2, unit="mm")

        self.assertTrue(result["success"], result["message"])
        method, arguments = document.SketchManager.calls[0]
        self.assertEqual("CreateEquationSpline", method)
        self.assertEqual("sin(x)", arguments[0])
        self.assertAlmostEqual(0.0, arguments[1], places=9)
        self.assertAlmostEqual(1.0, arguments[2], places=9)  # 25.4 mm = 1 inch
        self.assertIs(False, arguments[3])
        self.assertAlmostEqual(0.0, arguments[4], places=9)
        self.assertAlmostEqual(0.001, arguments[5], places=9)  # 1 mm in metres
        self.assertAlmostEqual(0.002, arguments[6], places=9)
        self.assertEqual("inch", result["data"]["document_unit"])
        self.assertEqual([0.0, 1.0], result["data"]["range_in_document_unit"])

    def test_rotation_is_radians_and_measurements_come_back_in_the_unit(self):
        document = Document(self.sine(), linear_unit=0)
        automation = Automation(document)

        result = draw_equation_curve(automation, "sin(x)", 0, 6.2831853,
                                     rotation_deg=90, unit="mm")

        _method, arguments = document.SketchManager.calls[0]
        self.assertAlmostEqual(math.pi / 2, arguments[4], places=12)
        self.assertAlmostEqual(7.6404, result["data"]["curve_length"], places=4)
        self.assertEqual([[0.0, 0.0, 0.0], [6.2832, 0.0, 0.0]],
                         result["data"]["endpoints"])
        self.assertEqual(1, result["data"]["spline_count"])

    def test_bad_input_is_rejected_before_any_com_call(self):
        cases = (
            {"expression": "   "},
            {"range_start": 1, "range_end": 1},
            {"range_start": "0"},
            {"rotation_deg": None},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                automation = Automation()
                call = {"expression": "sin(x)", "range_start": 0, "range_end": 1}
                call.update(overrides)

                result = draw_equation_curve(automation, **call)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)
                self.assertEqual([], automation.document.SketchManager.calls)

    def test_an_unsupported_document_unit_is_reported(self):
        automation = Automation(Document(linear_unit=5))  # feet and inches

        result = draw_equation_curve(automation, "sin(x)", 0, 10)

        self.assertFalse(result["success"])
        self.assertEqual("UNSUPPORTED_DOCUMENT_UNIT", result["data"]["code"])

    def test_a_curve_that_adds_no_spline_is_a_failure(self):
        automation = Automation()
        automation.document.segments.append(Segment(3))
        automation.document.SketchManager.document = None

        result = draw_equation_curve(automation, "sin(x)", 0, 10)

        self.assertFalse(result["success"])
        self.assertEqual("EQUATION_CURVE_FAILED", result["data"]["code"])


class EquationCurve3DTests(unittest.TestCase):
    """CreateEquationSpline2 returns None for any non-integer range on a
    decimal-comma Windows locale, so the tool always passes 0..1 and maps the
    parameter inside the expressions; see docs/api-findings.md section 30."""

    @staticmethod
    def document(linear_unit=0):
        document = Document(Spline(0.064076, [SketchPoint(0.01, 0.0),
                                              SketchPoint(0.01, 0.0, 0.012566)]),
                            linear_unit=linear_unit)
        document.is_3d = True
        return document

    def test_the_tool_is_registered_as_a_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("draw_equation_curve_3d", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("draw_equation_curve_3d"))
        self.assertEqual(
            ["x_expression", "y_expression", "z_expression", "range_start",
             "range_end"],
            tools["draw_equation_curve_3d"].inputSchema["required"])

    def test_the_range_is_always_zero_to_one_and_t_is_remapped(self):
        document = self.document()
        automation = Automation(document)

        result = draw_equation_curve_3d(
            automation, "10*cos(t)", "10*sin(t)", "2*t", 0.5, 6.7832,
            rotation_deg=90, x_offset=1, y_offset=2)

        self.assertTrue(result["success"], result["message"])
        method, arguments = document.SketchManager.calls[0]
        self.assertEqual("CreateEquationSpline2", method)
        mapped = "(0.5+6.2832*t)"
        self.assertEqual(f"10*cos({mapped})", arguments[0])
        self.assertEqual(f"10*sin({mapped})", arguments[1])
        self.assertEqual(f"2*{mapped}", arguments[2])
        self.assertEqual((0.0, 1.0, False), arguments[3:6])
        self.assertAlmostEqual(math.pi / 2, arguments[6], places=12)
        self.assertAlmostEqual(0.001, arguments[7], places=12)
        self.assertAlmostEqual(0.002, arguments[8], places=12)
        self.assertEqual((False, False), arguments[9:11])
        self.assertAlmostEqual(64.076, result["data"]["curve_length"], places=3)
        self.assertEqual([[10.0, 0.0, 0.0], [10.0, 0.0, 12.566]],
                         result["data"]["endpoints"])

    def test_names_containing_t_are_left_alone(self):
        automation = Automation(self.document())

        draw_equation_curve_3d(automation, "sqrt(t)", "tan(t)", "t", 0, 2)

        arguments = automation.document.SketchManager.calls[0][1]
        self.assertEqual("sqrt((0+2*t))", arguments[0])
        self.assertEqual("tan((0+2*t))", arguments[1])
        self.assertEqual("(0+2*t)", arguments[2])

    def test_expressions_are_scaled_from_the_unit_to_the_document_unit(self):
        automation = Automation(self.document(linear_unit=3))  # inch

        draw_equation_curve_3d(automation, "t", "0", "25.4", 0, 1, unit="mm")

        arguments = automation.document.SketchManager.calls[0][1]
        # Written in fixed notation: the expression parser is not trusted with 1e-05.
        self.assertEqual("((0+1*t))*0.03937007874", arguments[0])
        self.assertEqual("(25.4)*0.03937007874", arguments[2])

    def test_a_2d_sketch_is_rejected(self):
        document = self.document()
        document.is_3d = False
        automation = Automation(document)

        result = draw_equation_curve_3d(automation, "t", "0", "0", 0, 1)

        self.assertFalse(result["success"])
        self.assertEqual("NOT_A_3D_SKETCH", result["data"]["code"])
        self.assertEqual([], document.SketchManager.calls)

    def test_bad_input_is_rejected_before_any_com_call(self):
        cases = (
            {"x_expression": " "},
            {"z_expression": None},
            {"range_start": 1, "range_end": 1},
            {"range_end": float("nan")},
            {"rotation_deg": "0"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                automation = Automation(self.document())
                call = {"x_expression": "t", "y_expression": "0",
                        "z_expression": "0", "range_start": 0, "range_end": 1}
                call.update(overrides)

                result = draw_equation_curve_3d(automation, **call)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_a_curve_that_adds_no_spline_is_a_failure(self):
        automation = Automation(self.document())
        automation.document.SketchManager.document = None

        result = draw_equation_curve_3d(automation, "t", "0", "0", 0, 1)

        self.assertFalse(result["success"])
        self.assertEqual("EQUATION_CURVE_FAILED", result["data"]["code"])


class SketchTextTests(unittest.TestCase):
    def test_the_text_tool_is_registered_as_a_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("draw_sketch_text", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("draw_sketch_text"))
        properties = tools["draw_sketch_text"].inputSchema["properties"]
        self.assertEqual(["mm", "cm", "m", "inch"], properties["unit"]["enum"])
        self.assertEqual(["text"],
                         tools["draw_sketch_text"].inputSchema["required"])

    def test_the_point_is_converted_and_the_text_read_back(self):
        automation = Automation()

        result = draw_sketch_text(automation, "Hello", x=10, y=-5, unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual((0.01, -0.005, 0.0, "Hello", 2, 0, 0, 100, 100),
                         automation.document.text_calls[0])
        self.assertEqual("Hello", result["data"]["stored_text"])
        self.assertTrue(result["data"]["read_back_matches"])
        self.assertEqual(1, result["data"]["text_segment_count"])

    def test_text_that_solidworks_does_not_record_is_a_failure(self):
        automation = Automation()
        automation.document.text_registers = False

        result = draw_sketch_text(automation, "Hello")

        self.assertFalse(result["success"])
        self.assertEqual("TEXT_NOT_ADDED", result["data"]["code"])

    def test_defaults_are_millimetres_and_the_verified_alignment(self):
        automation = Automation()

        result = draw_sketch_text(automation, "x")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(2, automation.document.text_calls[0][4])
        self.assertEqual(0.0, automation.document.text_calls[0][0])

    def test_bad_input_is_rejected_before_any_com_call(self):
        cases = (
            {"text": ""},
            {"text": "   "},
            {"text": 5},
            {"text": "x", "alignment_code": 4},
            {"text": "x", "alignment_code": -1},
            {"text": "x", "alignment_code": True},
            {"text": "x", "x": "a"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                automation = Automation()

                result = draw_sketch_text(automation, **arguments)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)
                self.assertEqual([], automation.document.text_calls)

    def test_text_solidworks_refuses_is_a_failure(self):
        automation = Automation()
        automation.document.text_ok = False

        result = draw_sketch_text(automation, "Hello")

        self.assertFalse(result["success"])
        self.assertEqual(1, len(automation.document.text_calls))


class ConvertEntityTests(unittest.TestCase):
    def test_the_tool_is_registered_as_a_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("convert_entities", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("convert_entities"))

    def test_a_face_point_is_selected_and_the_growth_proves_it(self):
        automation = Automation()
        automation.document.converted_segments = 4

        result = convert_entities(automation, faces=[[1, 2, 3]], unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(4, result["data"]["added"])
        self.assertEqual(4, result["data"]["segments_after"])
        self.assertEqual(["FACE"], [call[1] for call
                                    in automation.document.Extension.select_calls])
        self.assertEqual((0.001, 0.002, 0.003),
                         automation.document.Extension.select_calls[0][3:6])

    def test_edges_are_selected_after_faces(self):
        automation = Automation()
        automation.document.converted_segments = 5

        result = convert_entities(automation, faces=[[1, 0, 0]],
                                  edges=[[0, 0, 0]], unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(["FACE", "EDGE"],
                         [call[1] for call
                          in automation.document.Extension.select_calls])
        self.assertEqual(5, result["data"]["segments_after"])

    def test_a_selection_solidworks_cannot_convert_is_a_failure(self):
        automation = Automation()  # the conversion adds nothing

        result = convert_entities(automation, faces=[[0, 0, 0]], unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual("CONVERT_FAILED", result["data"]["code"])

    def test_an_empty_selection_is_a_failure(self):
        automation = Automation()
        automation.document.Extension.select_ok = False

        result = convert_entities(automation, faces=[[0, 0, 0]], unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual("SELECTION_EMPTY", result["data"]["code"])

    def test_use_selection_needs_something_selected(self):
        automation = Automation()
        automation.document.selected_count = 0

        result = convert_entities(automation, use_selection=True)

        self.assertFalse(result["success"])
        self.assertEqual("SELECTION_EMPTY", result["data"]["code"])

    def test_use_selection_converts_the_current_selection(self):
        automation = Automation()
        automation.document.selected_count = 1
        automation.document.converted_segments = 4

        result = convert_entities(automation, use_selection=True)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([], automation.document.Extension.select_calls)
        self.assertEqual(1, result["data"]["selected"])

    def test_no_open_sketch_is_reported(self):
        automation = Automation()
        automation.document.active_sketch = False

        result = convert_entities(automation, use_selection=True)

        self.assertFalse(result["success"])
        self.assertEqual("NO_ACTIVE_SKETCH", result["data"]["code"])

    def test_validation_happens_before_com(self):
        cases = ({"use_selection": True, "faces": [[0, 0, 0]]},
                 {},
                 {"faces": [[0, 0]]},
                 {"faces": [[0, 0, "a"]]},
                 {"faces": "face"},
                 {"chain": "yes", "edges": [[0, 0, 0]]})
        for arguments in cases:
            with self.subTest(arguments=arguments):
                automation = Automation()

                result = convert_entities(automation, **arguments)

                self.assertFalse(result["success"])
                self.assertEqual([], automation.document.Extension.select_calls)


if __name__ == "__main__":
    unittest.main()
