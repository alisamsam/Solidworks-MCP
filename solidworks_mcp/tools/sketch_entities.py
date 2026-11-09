"""
Sketch entity tools for the active 2D sketch.

Covers the primitive entities that the legacy server tools do not expose:
centerline, sketch point, radius circle, rectangle variants, parallelogram,
ellipse, elliptical arc, parabola and the equation-driven curve. Every call is
a mutation on the active sketch, so each tool declares OperationClass.MUTATE.

The SolidWorks signatures were read from sldworks.tlb (ISketchManager), not
guessed; see docs/api-findings.md section 0.
"""

import math
import re

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


UNIT_SCHEMA = {
    "type": "string",
    "enum": ["mm", "cm", "m", "inch"],
    "default": "mm",
}


def _is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _invalid(sw, message, code="VALIDATION_FAILED"):
    return sw._result(
        False, message, SwErrors.swInvalidInput, {"code": code}
    )


def _convert_coordinates(sw, unit, values):
    """Convert flat user-unit coordinates to meters; return (meters, error)."""
    if any(not _is_number(value) for value in values):
        return None, _invalid(sw, "All coordinates and dimensions must be finite numbers.")
    try:
        return [sw._units.to_meters(value, unit) for value in values], None
    except (KeyError, TypeError, ValueError) as conversion_error:
        return None, _invalid(sw, f"Invalid unit or coordinate: {conversion_error}")


def _create_entity(sw, method, coordinates, unit, message, data, leading=(), trailing=()):
    """Call one SketchManager create method with metre coordinates.

    ``leading`` and ``trailing`` carry non-coordinate arguments (an arc
    direction flag, a slot creation type) that must not be unit-converted.
    """
    document, error = sw.get_active_doc()
    if error:
        return error
    meters, conversion_error = _convert_coordinates(sw, unit, coordinates)
    if conversion_error:
        return conversion_error
    arguments = list(leading) + list(meters) + list(trailing)
    try:
        entity = com(com(document, "SketchManager"), method, *arguments)
    except Exception as create_error:
        return sw._result(
            False, f"{message} failed: {create_error}", SwErrors.swSketchError
        )
    if entity is None:
        return sw._result(
            False,
            f"{message} failed. Ensure a sketch is active and the geometry is valid.",
            SwErrors.swSketchError,
        )
    result_data = dict(data)
    result_data["unit"] = unit
    result_data["sketch_method"] = method
    return sw._result(True, message, SwErrors.swSuccess, result_data)


@tool(
    name="draw_line_3d",
    description="Draw a straight line with explicit XYZ endpoints in the active 3D sketch. Coordinates are in the part model frame.",
    schema={"type": "object", "properties": {
        **{key: {"type": "number"} for key in ("x1", "y1", "z1", "x2", "y2", "z2")},
        "unit": UNIT_SCHEMA,
    }, "required": ["x1", "y1", "z1", "x2", "y2", "z2"]},
    operation_class=OperationClass.MUTATE,
)
def draw_line_3d(sw, x1, y1, z1, x2, y2, z2, unit="mm"):
    values = (x1, y1, z1, x2, y2, z2)
    meters, error = _convert_coordinates(sw, unit, values)
    if error:
        return error
    if math.dist(meters[:3], meters[3:]) < 1e-10:
        return _invalid(sw, "The two 3D line endpoints must differ.")
    document, error = sw.get_active_doc()
    if error:
        return error
    try:
        sketch = com(document, "GetActiveSketch2")
        if sketch is None or not bool(com(sketch, "Is3D")):
            return _invalid(sw, "Start a 3D sketch before drawing a 3D line.", "NOT_A_3D_SKETCH")
    except Exception as exc:
        return _invalid(sw, f"Could not verify the active 3D sketch: {exc}")
    return _create_entity(sw, "CreateLine", values, unit, "Created 3D line.",
                          {"start": list(values[:3]), "end": list(values[3:])})


@tool(
    name="draw_centerline",
    description=(
        "Draw a centerline in the active sketch. Centerlines are construction "
        "geometry and are the usual revolve axis."
    ),
    schema={"type": "object", "properties": {
        "x1": {"type": "number", "default": 0},
        "y1": {"type": "number", "default": -50},
        "x2": {"type": "number", "default": 0},
        "y2": {"type": "number", "default": 50},
        "unit": UNIT_SCHEMA,
    }, "required": []},
    operation_class=OperationClass.MUTATE,
)
def draw_centerline(sw, x1: float = 0, y1: float = -50, x2: float = 0, y2: float = 50,
                    unit: str = "mm") -> dict:
    if x1 == x2 and y1 == y2:
        return _invalid(sw, "Centerline start and end points must differ.")
    return _create_entity(
        sw, "CreateCenterLine", [x1, y1, 0.0, x2, y2, 0.0], unit,
        "Centerline created.",
        {"start": [x1, y1], "end": [x2, y2]},
    )


@tool(
    name="draw_point",
    description="Draw a sketch point in the active sketch.",
    schema={"type": "object", "properties": {
        "x": {"type": "number", "default": 0},
        "y": {"type": "number", "default": 0},
        "unit": UNIT_SCHEMA,
    }, "required": []},
    operation_class=OperationClass.MUTATE,
)
def draw_point(sw, x: float = 0, y: float = 0, unit: str = "mm") -> dict:
    return _create_entity(
        sw, "CreatePoint", [x, y, 0.0], unit,
        "Sketch point created.",
        {"position": [x, y]},
    )


@tool(
    name="draw_circle_radius",
    description=(
        "Draw a circle from its center and an exact radius. Use this instead of "
        "draw_circle when the radius is known and no edge point is needed."
    ),
    schema={"type": "object", "properties": {
        "cx": {"type": "number", "default": 0},
        "cy": {"type": "number", "default": 0},
        "radius": {"type": "number", "exclusiveMinimum": 0, "default": 25},
        "unit": UNIT_SCHEMA,
    }, "required": ["radius"]},
    operation_class=OperationClass.MUTATE,
)
def draw_circle_radius(sw, cx: float = 0, cy: float = 0, radius: float = 25,
                       unit: str = "mm") -> dict:
    if not _is_number(radius) or radius <= 0:
        return _invalid(sw, "Circle radius must be a positive finite number.")
    return _create_entity(
        sw, "CreateCircleByRadius", [cx, cy, 0.0, radius], unit,
        f"Circle created with radius {radius}{unit}.",
        {"center": [cx, cy], "radius": radius},
    )


@tool(
    name="draw_center_rectangle",
    description="Draw a center-to-corner rectangle from its center, width and height.",
    schema={"type": "object", "properties": {
        "cx": {"type": "number", "default": 0},
        "cy": {"type": "number", "default": 0},
        "width": {"type": "number", "exclusiveMinimum": 0, "default": 50},
        "height": {"type": "number", "exclusiveMinimum": 0, "default": 25},
        "unit": UNIT_SCHEMA,
    }, "required": ["width", "height"]},
    operation_class=OperationClass.MUTATE,
)
def draw_center_rectangle(sw, cx: float = 0, cy: float = 0, width: float = 50,
                          height: float = 25, unit: str = "mm") -> dict:
    if not _is_number(width) or not _is_number(height) or width <= 0 or height <= 0:
        return _invalid(sw, "Rectangle width and height must be positive finite numbers.")
    half_width = width / 2.0
    half_height = height / 2.0
    return _create_entity(
        sw, "CreateCenterRectangle",
        # CreateCenterRectangle takes the centre and one corner (sldworks.tlb).
        [cx, cy, 0.0, cx + half_width, cy + half_height, 0.0],
        unit,
        f"Center rectangle created: {width}x{height}{unit}.",
        {"center": [cx, cy], "width": width, "height": height},
    )


def _three_point_rectangle(sw, method, label, points, unit):
    coordinates = []
    for x, y in points:
        coordinates.extend([x, y, 0.0])
    return _create_entity(
        sw, method, coordinates, unit,
        f"{label} created.",
        {"points": [list(point) for point in points]},
    )


@tool(
    name="draw_rectangle_3point_corner",
    description=(
        "Draw a 3-point corner rectangle. The first two points define one edge; "
        "the third sets the opposite corner."
    ),
    schema={"type": "object", "properties": {
        "x1": {"type": "number"}, "y1": {"type": "number"},
        "x2": {"type": "number"}, "y2": {"type": "number"},
        "x3": {"type": "number"}, "y3": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["x1", "y1", "x2", "y2", "x3", "y3"]},
    operation_class=OperationClass.MUTATE,
)
def draw_rectangle_3point_corner(sw, x1: float, y1: float, x2: float, y2: float,
                                 x3: float, y3: float, unit: str = "mm") -> dict:
    return _three_point_rectangle(
        sw, "Create3PointCornerRectangle", "3-point corner rectangle",
        [(x1, y1), (x2, y2), (x3, y3)], unit,
    )


@tool(
    name="draw_rectangle_3point_center",
    description=(
        "Draw a 3-point center rectangle. The first two points define the center "
        "and one corner; the third sets the width direction."
    ),
    schema={"type": "object", "properties": {
        "x1": {"type": "number"}, "y1": {"type": "number"},
        "x2": {"type": "number"}, "y2": {"type": "number"},
        "x3": {"type": "number"}, "y3": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["x1", "y1", "x2", "y2", "x3", "y3"]},
    operation_class=OperationClass.MUTATE,
)
def draw_rectangle_3point_center(sw, x1: float, y1: float, x2: float, y2: float,
                                 x3: float, y3: float, unit: str = "mm") -> dict:
    return _three_point_rectangle(
        sw, "Create3PointCenterRectangle", "3-point center rectangle",
        [(x1, y1), (x2, y2), (x3, y3)], unit,
    )


@tool(
    name="draw_parallelogram",
    description="Draw a parallelogram through three ordered corner points.",
    schema={"type": "object", "properties": {
        "x1": {"type": "number"}, "y1": {"type": "number"},
        "x2": {"type": "number"}, "y2": {"type": "number"},
        "x3": {"type": "number"}, "y3": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["x1", "y1", "x2", "y2", "x3", "y3"]},
    operation_class=OperationClass.MUTATE,
)
def draw_parallelogram(sw, x1: float, y1: float, x2: float, y2: float,
                       x3: float, y3: float, unit: str = "mm") -> dict:
    return _three_point_rectangle(
        sw, "CreateParallelogram", "Parallelogram",
        [(x1, y1), (x2, y2), (x3, y3)], unit,
    )


@tool(
    name="draw_ellipse",
    description=(
        "Draw a full ellipse from center, major radius, minor radius and an "
        "optional in-plane rotation."
    ),
    schema={"type": "object", "properties": {
        "cx": {"type": "number", "default": 0},
        "cy": {"type": "number", "default": 0},
        "major_radius": {"type": "number", "exclusiveMinimum": 0},
        "minor_radius": {"type": "number", "exclusiveMinimum": 0},
        "rotation_deg": {"type": "number", "default": 0},
        "unit": UNIT_SCHEMA,
    }, "required": ["major_radius", "minor_radius"]},
    operation_class=OperationClass.MUTATE,
)
def draw_ellipse(sw, cx: float = 0, cy: float = 0, major_radius: float = 25,
                 minor_radius: float = 12.5, rotation_deg: float = 0,
                 unit: str = "mm") -> dict:
    if (
        not _is_number(major_radius)
        or not _is_number(minor_radius)
        or major_radius <= 0
        or minor_radius <= 0
    ):
        return _invalid(sw, "Ellipse radii must be positive finite numbers.")
    rotation = math.radians(rotation_deg)
    major_x = cx + major_radius * math.cos(rotation)
    major_y = cy + major_radius * math.sin(rotation)
    minor_x = cx - minor_radius * math.sin(rotation)
    minor_y = cy + minor_radius * math.cos(rotation)
    return _create_entity(
        sw, "CreateEllipse",
        [cx, cy, 0.0, major_x, major_y, 0.0, minor_x, minor_y, 0.0],
        unit,
        f"Ellipse created: {major_radius}x{minor_radius}{unit}.",
        {
            "center": [cx, cy],
            "major_radius": major_radius,
            "minor_radius": minor_radius,
            "rotation_deg": rotation_deg,
        },
    )


@tool(
    name="draw_elliptical_arc",
    description=(
        "Draw a partial elliptical arc between two parametric angles of an "
        "ellipse defined by center, radii and in-plane rotation."
    ),
    schema={"type": "object", "properties": {
        "cx": {"type": "number", "default": 0},
        "cy": {"type": "number", "default": 0},
        "major_radius": {"type": "number", "exclusiveMinimum": 0},
        "minor_radius": {"type": "number", "exclusiveMinimum": 0},
        "rotation_deg": {"type": "number", "default": 0},
        "start_angle_deg": {"type": "number", "default": 0},
        "end_angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
        "counter_clockwise": {"type": "boolean", "default": True},
        "unit": UNIT_SCHEMA,
    }, "required": ["major_radius", "minor_radius", "end_angle_deg"]},
    operation_class=OperationClass.MUTATE,
)
def draw_elliptical_arc(sw, cx: float = 0, cy: float = 0, major_radius: float = 25,
                        minor_radius: float = 12.5, rotation_deg: float = 0,
                        start_angle_deg: float = 0, end_angle_deg: float = 180,
                        counter_clockwise: bool = True, unit: str = "mm") -> dict:
    if (
        not _is_number(major_radius)
        or not _is_number(minor_radius)
        or major_radius <= 0
        or minor_radius <= 0
    ):
        return _invalid(sw, "Elliptical arc radii must be positive finite numbers.")
    if not _is_number(end_angle_deg) or not 0 < end_angle_deg <= 360:
        return _invalid(sw, "end_angle_deg must be in (0, 360].")

    rotation = math.radians(rotation_deg)

    def point_at(angle_deg):
        angle = math.radians(angle_deg)
        return (
            cx + major_radius * math.cos(angle) * math.cos(rotation)
            - minor_radius * math.sin(angle) * math.sin(rotation),
            cy + major_radius * math.cos(angle) * math.sin(rotation)
            + minor_radius * math.sin(angle) * math.cos(rotation),
        )

    major_x = cx + major_radius * math.cos(rotation)
    major_y = cy + major_radius * math.sin(rotation)
    minor_x = cx - minor_radius * math.sin(rotation)
    minor_y = cy + minor_radius * math.cos(rotation)
    start_x, start_y = point_at(start_angle_deg)
    end_x, end_y = point_at(end_angle_deg)
    direction = 1 if counter_clockwise else -1
    return _create_entity(
        sw, "CreateEllipticalArc",
        [
            cx, cy, 0.0,
            major_x, major_y, 0.0,
            minor_x, minor_y, 0.0,
            start_x, start_y, 0.0,
            end_x, end_y, 0.0,
        ],
        unit,
        f"Elliptical arc created from {start_angle_deg} to {end_angle_deg} degrees.",
        {
            "center": [cx, cy],
            "major_radius": major_radius,
            "minor_radius": minor_radius,
            "rotation_deg": rotation_deg,
            "start_angle_deg": start_angle_deg,
            "end_angle_deg": end_angle_deg,
            "counter_clockwise": counter_clockwise,
        },
        trailing=[direction],
    )


@tool(
    name="draw_tangent_arc",
    description=(
        "Draw a tangent arc from an existing segment endpoint to a second point. "
        "The first point must be an endpoint of an existing sketch segment."
    ),
    schema={"type": "object", "properties": {
        "start_x": {"type": "number"},
        "start_y": {"type": "number"},
        "end_x": {"type": "number"},
        "end_y": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["start_x", "start_y", "end_x", "end_y"]},
    operation_class=OperationClass.MUTATE,
)
def draw_tangent_arc(sw, start_x: float, start_y: float, end_x: float, end_y: float,
                     unit: str = "mm") -> dict:
    if (start_x, start_y) == (end_x, end_y):
        return _invalid(sw, "Tangent arc start and end points must differ.")
    # ArcType was probed live in SW 2025: values 0-3 all produce an identical
    # arc for a 2D tangent arc, so the flag is fixed at 0 rather than exposed.
    return _create_entity(
        sw, "CreateTangentArc",
        [start_x, start_y, 0.0, end_x, end_y, 0.0],
        unit,
        "Tangent arc created.",
        {"start": [start_x, start_y], "end": [end_x, end_y]},
        trailing=[0],
    )


# swSketchSlotCreationType_e: line=0, center_line=1, arc=2, 3pointarc=3
SW_SLOT_ARC = 2
SW_SLOT_3POINT_ARC = 3

# swSketchSlotLengthType_e: CenterCenter=0, FullLength=1
SW_SLOT_CENTER_CENTER = 0


# CreateSketchSlot order is
# (SlotCreationType, SlotLengthType, Width, X1..Z1, X2..Z2, X3..Z3,
#  CenterArcDirection, AddDimension): two non-coordinate arguments lead, two
# trail, and only the width plus the nine coordinates are unit-converted.
def _slot_call(sw, creation_type, width, points, unit, message, data):
    coordinates = [width]
    for x, y in points:
        coordinates.extend([x, y, 0.0])
    return _create_entity(
        sw, "CreateSketchSlot",
        coordinates,
        unit,
        message,
        data,
        leading=[creation_type, SW_SLOT_CENTER_CENTER],
        trailing=[1, False],
    )


@tool(
    name="draw_arc_slot",
    description=(
        "Draw an arc slot from an arc center, an arc start point and an arc end "
        "point, plus the slot width."
    ),
    schema={"type": "object", "properties": {
        "center_x": {"type": "number"},
        "center_y": {"type": "number"},
        "start_x": {"type": "number"},
        "start_y": {"type": "number"},
        "end_x": {"type": "number"},
        "end_y": {"type": "number"},
        "width": {"type": "number", "exclusiveMinimum": 0},
        "unit": UNIT_SCHEMA,
    }, "required": ["center_x", "center_y", "start_x", "start_y",
                   "end_x", "end_y", "width"]},
    operation_class=OperationClass.MUTATE,
)
def draw_arc_slot(sw, center_x: float, center_y: float, start_x: float, start_y: float,
                  end_x: float, end_y: float, width: float, unit: str = "mm") -> dict:
    points = [(center_x, center_y), (start_x, start_y), (end_x, end_y)]
    if len(set(points)) < 3:
        return _invalid(sw, "Arc slot center, start and end points must be distinct.")
    if not _is_number(width) or width <= 0:
        return _invalid(sw, "Slot width must be a positive finite number.")
    return _slot_call(
        sw, SW_SLOT_ARC, width, points, unit,
        f"Arc slot created with width {width}{unit}.",
        {"center": [center_x, center_y], "start": [start_x, start_y],
         "end": [end_x, end_y], "width": width},
    )


@tool(
    name="draw_arc_slot_3point",
    description=(
        "Draw a 3-point arc slot through three points on the slot centerline, "
        "plus the slot width."
    ),
    schema={"type": "object", "properties": {
        "x1": {"type": "number"}, "y1": {"type": "number"},
        "x2": {"type": "number"}, "y2": {"type": "number"},
        "x3": {"type": "number"}, "y3": {"type": "number"},
        "width": {"type": "number", "exclusiveMinimum": 0},
        "unit": UNIT_SCHEMA,
    }, "required": ["x1", "y1", "x2", "y2", "x3", "y3", "width"]},
    operation_class=OperationClass.MUTATE,
)
def draw_arc_slot_3point(sw, x1: float, y1: float, x2: float, y2: float,
                         x3: float, y3: float, width: float,
                         unit: str = "mm") -> dict:
    points = [(x1, y1), (x2, y2), (x3, y3)]
    if len(set(points)) < 3:
        return _invalid(sw, "Arc slot points must be distinct.")
    if not _is_number(width) or width <= 0:
        return _invalid(sw, "Slot width must be a positive finite number.")
    return _slot_call(
        sw, SW_SLOT_3POINT_ARC, width, points, unit,
        f"3-point arc slot created with width {width}{unit}.",
        {"points": [list(point) for point in points], "width": width},
    )


@tool(
    name="draw_parabola",
    description=(
        "Draw a parabolic segment from a focus, an apex and the two end points "
        "on the curve."
    ),
    schema={"type": "object", "properties": {
        "focus_x": {"type": "number"}, "focus_y": {"type": "number"},
        "apex_x": {"type": "number"}, "apex_y": {"type": "number"},
        "start_x": {"type": "number"}, "start_y": {"type": "number"},
        "end_x": {"type": "number"}, "end_y": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["focus_x", "focus_y", "apex_x", "apex_y",
                   "start_x", "start_y", "end_x", "end_y"]},
    operation_class=OperationClass.MUTATE,
)
def draw_parabola(sw, focus_x: float, focus_y: float, apex_x: float, apex_y: float,
                  start_x: float, start_y: float, end_x: float, end_y: float,
                  unit: str = "mm") -> dict:
    if (focus_x, focus_y) == (apex_x, apex_y):
        return _invalid(sw, "Parabola focus and apex must differ.")
    if (start_x, start_y) == (end_x, end_y):
        return _invalid(sw, "Parabola start and end points must differ.")
    return _create_entity(
        sw, "CreateParabola",
        [
            focus_x, focus_y, 0.0,
            apex_x, apex_y, 0.0,
            start_x, start_y, 0.0,
            end_x, end_y, 0.0,
        ],
        unit,
        "Parabolic segment created.",
        {
            "focus": [focus_x, focus_y],
            "apex": [apex_x, apex_y],
            "start": [start_x, start_y],
            "end": [end_x, end_y],
        },
    )


# swLengthUnit_e from swconst.tlb, mapped to metres per unit.
_LINEAR_UNIT_FACTORS = {
    0: (0.001, "mm"),
    1: (0.01, "cm"),
    2: (1.0, "m"),
    3: (0.0254, "inch"),
    4: (0.3048, "foot"),
    6: (1.0e-10, "angstrom"),
    7: (1.0e-9, "nanometre"),
    8: (1.0e-6, "micron"),
    9: (2.54e-5, "mil"),
    10: (2.54e-8, "microinch"),
}


def _document_linear_unit(document):
    """(metres per unit, unit name) for the document's linear unit."""
    try:
        units = com(document, "GetUnits")
    except Exception:  # noqa: BLE001
        return None, None
    if not units:
        return None, None
    return _LINEAR_UNIT_FACTORS.get(int(units[0]), (None, None))


def _spline_count(document):
    sketch = com(document, "GetActiveSketch2")
    if sketch is None:
        return None
    return sum(
        1
        for segment in list(com(sketch, "GetSketchSegments") or [])
        if int(com(segment, "GetType")) == 3
    )


def _curve_points(spline, unit_factor):
    """The two stored curve endpoints, converted to metres then to the unit."""
    points = []
    for point in list(com(spline, "GetPoints2") or []):
        points.append([
            round(float(com(point, member)) / unit_factor, 6)
            for member in ("X", "Y", "Z")
        ])
    return points


@tool(
    name="draw_equation_curve",
    description=(
        "Draw an equation-driven curve y = f(x) in the active sketch. The "
        "expression uses x and is evaluated in the document's linear unit; "
        "SolidWorks keeps it as a closed-form spline. range_start and "
        "range_end are given in the requested unit and converted to the "
        "document unit, while the offsets are applied in the sketch plane. A "
        "positive rotation turns the curve counter-clockwise about the "
        "sketch origin."
    ),
    schema={"type": "object", "properties": {
        "expression": {"type": "string"},
        "range_start": {"type": "number"},
        "range_end": {"type": "number"},
        "rotation_deg": {"type": "number", "default": 0},
        "x_offset": {"type": "number", "default": 0},
        "y_offset": {"type": "number", "default": 0},
        "lock_start": {"type": "boolean", "default": False},
        "lock_end": {"type": "boolean", "default": False},
        "unit": UNIT_SCHEMA,
    }, "required": ["expression", "range_start", "range_end"]},
    operation_class=OperationClass.MUTATE,
)
def draw_equation_curve(sw, expression: str, range_start: float,
                        range_end: float, rotation_deg: float = 0,
                        x_offset: float = 0, y_offset: float = 0,
                        lock_start: bool = False, lock_end: bool = False,
                        unit: str = "mm") -> dict:
    if not isinstance(expression, str) or not expression.strip():
        return _invalid(sw, "expression must be a non-empty equation in x.")
    if any(not _is_number(value)
           for value in (range_start, range_end, rotation_deg, x_offset,
                         y_offset)):
        return _invalid(sw, "The range, rotation and offsets must be finite "
                            "numbers.")
    if range_start == range_end:
        return _invalid(sw, "range_start and range_end must differ.")

    document, error = sw.get_active_doc()
    if error:
        return error
    document_factor, document_unit = _document_linear_unit(document)
    if document_factor is None:
        return sw._result(
            False,
            "The document uses a linear unit this tool cannot convert; set "
            "the document to mm, cm, m or inch first.",
            SwErrors.swSketchError,
            {"code": "UNSUPPORTED_DOCUMENT_UNIT"},
        )
    try:
        start_meters = sw._units.to_meters(range_start, unit)
        end_meters = sw._units.to_meters(range_end, unit)
        x_offset_meters = sw._units.to_meters(x_offset, unit)
        y_offset_meters = sw._units.to_meters(y_offset, unit)
    except (KeyError, TypeError, ValueError) as conversion_error:
        return _invalid(sw, f"Invalid unit or value: {conversion_error}")

    splines_before = _spline_count(document)
    try:
        spline = com(
            com(document, "SketchManager"), "CreateEquationSpline",
            expression,
            start_meters / document_factor,
            end_meters / document_factor,
            False,
            math.radians(rotation_deg),
            x_offset_meters,
            y_offset_meters,
            bool(lock_start),
            bool(lock_end),
        )
    except Exception as create_error:
        return sw._result(
            False, f"Equation curve failed: {create_error}",
            SwErrors.swSketchError,
        )
    if spline is None:
        return sw._result(
            False,
            "Equation curve failed. Ensure a sketch is active and the "
            "expression is valid.",
            SwErrors.swSketchError,
        )

    splines_after = _spline_count(document)
    if splines_before is not None and splines_after is not None \
            and splines_after <= splines_before:
        return sw._result(
            False,
            "Equation curve failed: no new spline appeared in the sketch.",
            SwErrors.swSketchError,
            {"code": "EQUATION_CURVE_FAILED"},
        )

    factor = sw._units.to_meters(1.0, unit)
    return sw._result(
        True,
        f"Equation curve '{expression}' created from {range_start} to "
        f"{range_end}{unit}.",
        SwErrors.swSuccess,
        {
            "expression": expression,
            "range": [range_start, range_end],
            "range_in_document_unit": [
                round(start_meters / document_factor, 6),
                round(end_meters / document_factor, 6),
            ],
            "document_unit": document_unit,
            "rotation_deg": rotation_deg,
            "offsets": [x_offset, y_offset],
            "unit": unit,
            "curve_length": round(float(com(spline, "GetLength")) / factor, 6),
            "endpoints": _curve_points(spline, factor),
            "spline_count": splines_after,
            "sketch_method": "CreateEquationSpline",
        },
    )


def _plain_number(value):
    """Fixed notation; the expression parser is not trusted with 1e-05."""
    text = f"{value:.12f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _remap_parameter(expression, start, end):
    """Replace the parameter t with start + (end - start) * t over 0..1."""
    mapped = f"({_plain_number(start)}+{_plain_number(end - start)}*t)"
    return re.sub(r"\bt\b", mapped, expression)


@tool(
    name="draw_equation_curve_3d",
    description=(
        "Draw a parametric equation-driven curve x(t), y(t), z(t) in the "
        "active 3D sketch (start one with create_3d_sketch). The expressions "
        "use t, which runs from range_start to range_end, and give "
        "coordinates in the requested unit. The offsets move the curve in X "
        "and Y and a positive rotation turns it counter-clockwise about Z."
    ),
    schema={"type": "object", "properties": {
        "x_expression": {"type": "string"},
        "y_expression": {"type": "string"},
        "z_expression": {"type": "string"},
        "range_start": {"type": "number"},
        "range_end": {"type": "number"},
        "rotation_deg": {"type": "number", "default": 0},
        "x_offset": {"type": "number", "default": 0},
        "y_offset": {"type": "number", "default": 0},
        "lock_start": {"type": "boolean", "default": False},
        "lock_end": {"type": "boolean", "default": False},
        "unit": UNIT_SCHEMA,
    }, "required": ["x_expression", "y_expression", "z_expression",
                    "range_start", "range_end"]},
    operation_class=OperationClass.MUTATE,
)
def draw_equation_curve_3d(sw, x_expression: str, y_expression: str,
                           z_expression: str, range_start: float,
                           range_end: float, rotation_deg: float = 0,
                           x_offset: float = 0, y_offset: float = 0,
                           lock_start: bool = False, lock_end: bool = False,
                           unit: str = "mm") -> dict:
    expressions = (x_expression, y_expression, z_expression)
    if any(not isinstance(text, str) or not text.strip()
           for text in expressions):
        return _invalid(sw, "x_expression, y_expression and z_expression "
                            "must be non-empty equations in t.")
    if any(not _is_number(value)
           for value in (range_start, range_end, rotation_deg, x_offset,
                         y_offset)):
        return _invalid(sw, "The range, rotation and offsets must be finite "
                            "numbers.")
    if range_start == range_end:
        return _invalid(sw, "range_start and range_end must differ.")

    document, error = sw.get_active_doc()
    if error:
        return error
    sketch = com(document, "GetActiveSketch2")
    if sketch is None or not bool(com(sketch, "Is3D")):
        return sw._result(
            False,
            "No 3D sketch is active; start one with create_3d_sketch first.",
            SwErrors.swSketchError,
            {"code": "NOT_A_3D_SKETCH"},
        )
    document_factor, document_unit = _document_linear_unit(document)
    if document_factor is None:
        return sw._result(
            False,
            "The document uses a linear unit this tool cannot convert; set "
            "the document to mm, cm, m or inch first.",
            SwErrors.swSketchError,
            {"code": "UNSUPPORTED_DOCUMENT_UNIT"},
        )
    try:
        factor = sw._units.to_meters(1.0, unit)
        x_offset_meters = sw._units.to_meters(x_offset, unit)
        y_offset_meters = sw._units.to_meters(y_offset, unit)
    except (KeyError, TypeError, ValueError) as conversion_error:
        return _invalid(sw, f"Invalid unit or value: {conversion_error}")

    # CreateEquationSpline2 returns None for any non-integer range on a
    # decimal-comma locale, so the range is always 0..1 (api-findings §30).
    scale = factor / document_factor
    sent = []
    for text in expressions:
        mapped = _remap_parameter(text, range_start, range_end)
        if not math.isclose(scale, 1.0):
            mapped = f"({mapped})*{_plain_number(scale)}"
        sent.append(mapped)

    splines_before = _spline_count(document)
    try:
        spline = com(
            com(document, "SketchManager"), "CreateEquationSpline2",
            *sent, 0.0, 1.0, False, math.radians(rotation_deg),
            x_offset_meters, y_offset_meters,
            bool(lock_start), bool(lock_end),
        )
    except Exception as create_error:
        return sw._result(
            False, f"Equation curve failed: {create_error}",
            SwErrors.swSketchError,
        )
    splines_after = _spline_count(document)
    if spline is None or (splines_before is not None
                          and splines_after is not None
                          and splines_after <= splines_before):
        return sw._result(
            False,
            "Equation curve failed: no new spline appeared in the 3D sketch. "
            "Check the expressions.",
            SwErrors.swSketchError,
            {"code": "EQUATION_CURVE_FAILED"},
        )

    return sw._result(
        True,
        f"3D equation curve created for t from {range_start} to {range_end}.",
        SwErrors.swSuccess,
        {
            "expressions": list(expressions),
            "sent_expressions": sent,
            "range": [range_start, range_end],
            "document_unit": document_unit,
            "rotation_deg": rotation_deg,
            "offsets": [x_offset, y_offset],
            "unit": unit,
            "curve_length": round(float(com(spline, "GetLength")) / factor, 6),
            "endpoints": _curve_points(spline, factor),
            "spline_count": splines_after,
            "sketch_method": "CreateEquationSpline2",
        },
    )


def _sketch_text_count(document):
    """How many text segments the active sketch holds, or None if unreadable.

    ``ISketch.GetSketchTextSegments`` is the durable record of inserted text:
    live it returns one type-4 segment per text, while open or closed.  Note
    that ``GetActiveSketch2`` returns ``None`` right after an ``EditRebuild3``.
    """
    try:
        sketch = com(document, "GetActiveSketch2")
        if sketch is None:
            return None
        return len(list(com(sketch, "GetSketchTextSegments") or []))
    except Exception:  # noqa: BLE001
        return None


@tool(
    name="draw_sketch_text",
    description=(
        "Insert sketch text at a point in the active sketch. The text is stored "
        "as an ISketchText object, read back, and the sketch's text segment "
        "count must grow, so the result is proven rather than assumed. The "
        "point is given in the requested unit. alignment_code is passed "
        "straight through to SolidWorks (the live test uses 2) and the width "
        "factor and character spacing are the verified 100/100 percentages."
    ),
    schema={"type": "object", "properties": {
        "text": {"type": "string"},
        "x": {"type": "number", "default": 0},
        "y": {"type": "number", "default": 0},
        "alignment_code": {"type": "integer", "minimum": 0, "maximum": 3,
                           "default": 2},
        "unit": UNIT_SCHEMA,
    }, "required": ["text"]},
    operation_class=OperationClass.MUTATE,
)
def draw_sketch_text(sw, text, x=0, y=0, alignment_code=2, unit="mm"):
    if not isinstance(text, str) or not text.strip():
        return _invalid(sw, "text must be a non-empty string.")

    if (not isinstance(alignment_code, int) or isinstance(alignment_code, bool)
            or not 0 <= alignment_code <= 3):
        return _invalid(sw, "alignment_code must be an integer from 0 to 3.")

    meters, conversion_error = _convert_coordinates(sw, unit, [x, y])
    if conversion_error:
        return conversion_error

    document, error = sw.get_active_doc()
    if error:
        return error

    before = _sketch_text_count(document)

    try:
        sketch_text = com(
            document, "InsertSketchText", meters[0], meters[1], 0.0, text,
            alignment_code, 0, 0, 100, 100,
        )
    except Exception as create_error:  # noqa: BLE001
        return sw._result(False, f"Sketch text failed: {create_error}",
                          SwErrors.swSketchError)

    if sketch_text is None:
        return sw._result(
            False,
            "Sketch text failed. Ensure a sketch is active.",
            SwErrors.swSketchError,
        )

    try:
        stored = com(sketch_text, "Text")
    except Exception:  # noqa: BLE001
        stored = None

    after = _sketch_text_count(document)
    if before is not None and after is not None and after <= before:
        return sw._result(
            False,
            f"SolidWorks did not record the sketch text {text!r}; the sketch "
            f"still holds {after} text segment(s).",
            SwErrors.swSketchError,
            {"code": "TEXT_NOT_ADDED", "text_segment_count": after},
        )

    return sw._result(
        True,
        f"Inserted the sketch text {text!r} at ({x}, {y}) {unit}.",
        SwErrors.swSuccess,
        {
            "text": text,
            "stored_text": stored,
            "read_back_matches": stored == text,
            "x": x,
            "y": y,
            "alignment_code": alignment_code,
            "unit": unit,
            "text_segment_count": after,
            "sketch_method": "InsertSketchText",
        },
    )


def _active_sketch_segment_count(document):
    """How many segments the active sketch holds, or None when none is open."""
    sketch = com(document, "GetActiveSketch2")
    if sketch is None:
        return None
    return len(list(com(sketch, "GetSketchSegments") or []))


def _point_list(sw, value, label):
    """Validate a list of [x, y, z] points; return (points, error)."""
    if value is None:
        return [], None
    if not isinstance(value, list):
        return None, _invalid(sw, f"{label} must be a list of [x, y, z] points.")
    points = []
    for index, point in enumerate(value):
        if (not isinstance(point, (list, tuple)) or len(point) != 3
                or any(not _is_number(item) for item in point)):
            return None, _invalid(
                sw, f"{label}[{index}] must be three finite numbers.")
        points.append(list(point))
    return points, None


@tool(
    name="convert_entities",
    description=(
        "Convert model geometry into the active sketch (Convert Entities). Give "
        "the points that lie on the faces or edges to convert, or use the "
        "current selection; the active sketch must be open for editing. "
        "SolidWorks silently rejects a selection it cannot convert and clears "
        "it, so success is proven by the sketch gaining segments. One face or a "
        "few coherent edges convert reliably; converting every edge of a body "
        "at once does not."
    ),
    schema={"type": "object", "properties": {
        "faces": {"type": "array", "items": {
            "type": "array", "items": {"type": "number"},
            "minItems": 3, "maxItems": 3}},
        "edges": {"type": "array", "items": {
            "type": "array", "items": {"type": "number"},
            "minItems": 3, "maxItems": 3}},
        "chain": {"type": "boolean", "default": False},
        "use_selection": {"type": "boolean", "default": False},
        "unit": UNIT_SCHEMA,
    }, "required": []},
    operation_class=OperationClass.MUTATE,
)
def convert_entities(sw, faces=None, edges=None, chain=False,
                     use_selection=False, unit="mm"):
    if not isinstance(chain, bool) or not isinstance(use_selection, bool):
        return _invalid(sw, "chain and use_selection must be true or false.")

    face_points, error = _point_list(sw, faces, "faces")
    if error:
        return error
    edge_points, error = _point_list(sw, edges, "edges")
    if error:
        return error

    if use_selection and (face_points or edge_points):
        return _invalid(sw, "Give either points or use_selection, not both.")
    if not use_selection and not face_points and not edge_points:
        return _invalid(
            sw,
            "Give at least one face or edge point, or set use_selection true.",
        )

    document, error = sw.get_active_doc()
    if error:
        return error

    before = _active_sketch_segment_count(document)
    if before is None:
        return _invalid(
            sw,
            "No sketch is open. Open the sketch that should receive the "
            "converted geometry.",
            "NO_ACTIVE_SKETCH",
        )

    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    if use_selection:
        selected = int(com(document.SelectionManager,
                           "GetSelectedObjectCount2", -1))
    else:
        com(document, "ClearSelection2", True)
        selected = 0
        for kind, points in (("FACE", face_points), ("EDGE", edge_points)):
            for point in points:
                meters, conversion_error = _convert_coordinates(sw, unit, point)
                if conversion_error:
                    return conversion_error
                picked = com(document.Extension, "SelectByID2", "", kind,
                             meters[0], meters[1], meters[2], selected > 0, 0,
                             callout, 0)
                if picked:
                    selected += 1

    if not selected:
        return sw._result(
            False,
            "Nothing was selected: no face or edge was found at the given "
            "points.",
            SwErrors.swSelectionError,
            {"code": "SELECTION_EMPTY"},
        )

    try:
        com(document, "SketchUseEdge2", chain)
    except Exception as convert_error:  # noqa: BLE001
        return sw._result(
            False,
            f"Convert entities failed: {convert_error}",
            SwErrors.swSketchError,
            {"code": "CONVERT_FAILED"},
        )

    after = _active_sketch_segment_count(document)
    after = before if after is None else after
    added = after - before
    if added <= 0:
        return sw._result(
            False,
            "SolidWorks did not convert the selection; it clears a selection "
            "it cannot convert. Try one face or a few coherent edges instead "
            "of many edges at once.",
            SwErrors.swSketchError,
            {"code": "CONVERT_FAILED", "selected": selected,
             "segments_before": before, "segments_after": after},
        )

    return sw._result(
        True,
        f"Converted {added} segment(s) from {selected} selected "
        f"{'entity' if selected == 1 else 'entities'} into the active sketch.",
        SwErrors.swSuccess,
        {
            "selected": selected,
            "segments_before": before,
            "segments_after": after,
            "added": added,
            "chain": chain,
            "unit": unit,
            "sketch_method": "SketchUseEdge2",
        },
    )
