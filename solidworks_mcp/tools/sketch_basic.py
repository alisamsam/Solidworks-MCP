"""Basic sketch tools: open/close sketches and draw simple entities."""

import logging
import traceback

from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")


@tool(
    name="create_sketch",
    description="Create a new sketch on a plane.",
    schema={
        "type": "object",
        "properties": {
            "plane": {
                "type": "string",
                "enum": ["Front", "Top", "Right"],
                "default": "Front",
                "description": "Plane to sketch on"
            },
            "exact_geometry": {"type": "boolean", "default": False, "description": "Disable automatic sketch relations and snapping for exact programmatic geometry"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def create_sketch(sw, plane="Front", exact_geometry=False):
    return sw.create_sketch(plane, exact_geometry)


@tool(
    name="create_sketch_on_face",
    description="Create a new sketch on an existing body face (by 3D coordinates). Use for cut-extrude on faces instead of reference planes.",
    schema={
        "type": "object",
        "properties": {
            "x": {"type": "number", "default": 0, "description": "X coordinate on the face"},
            "y": {"type": "number", "default": 0, "description": "Y coordinate on the face"},
            "z": {"type": "number", "default": 0, "description": "Z coordinate on the face"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"},
            "exact_geometry": {"type": "boolean", "default": False, "description": "Disable automatic sketch relations and snapping for exact programmatic geometry"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def create_sketch_on_face(sw, x=0, y=0, z=0, unit=None, exact_geometry=False):
    return sw.create_sketch_on_face(x, y, z, unit, exact_geometry)


@tool(
    name="draw_line",
    description="Draw a line in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x1": {"type": "number", "default": 0, "description": "Start X"},
            "y1": {"type": "number", "default": 0, "description": "Start Y"},
            "x2": {"type": "number", "default": 100, "description": "End X"},
            "y2": {"type": "number", "default": 0, "description": "End Y"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def draw_line(sw, x1=0, y1=0, x2=100, y2=0, unit=None):
    return sw.draw_line(x1, y1, x2, y2, unit)


@tool(
    name="draw_circle",
    description="Draw a circle in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x": {"type": "number", "default": 0, "description": "Center X"},
            "y": {"type": "number", "default": 0, "description": "Center Y"},
            "radius": {"type": "number", "default": 25, "description": "Radius"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def draw_circle(sw, x=0, y=0, radius=25, unit=None):
    return sw.draw_circle(x, y, radius, unit)


@tool(
    name="draw_rectangle",
    description="Draw a rectangle in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x1": {"type": "number", "default": -50, "description": "First corner X"},
            "y1": {"type": "number", "default": -25, "description": "First corner Y"},
            "x2": {"type": "number", "default": 50, "description": "Second corner X"},
            "y2": {"type": "number", "default": 25, "description": "Second corner Y"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def draw_rectangle(sw, x1=-50, y1=-25, x2=50, y2=25, unit=None):
    return sw.draw_rectangle(x1, y1, x2, y2, unit)


@tool(
    name="draw_arc",
    description="Draw an arc by center and angles, counter-clockwise from start_angle to end_angle.",
    schema={
        "type": "object",
        "properties": {
            "cx": {"type": "number", "default": 0, "description": "Center X"},
            "cy": {"type": "number", "default": 0, "description": "Center Y"},
            "radius": {"type": "number", "default": 25, "description": "Radius"},
            "start_angle": {"type": "number", "default": 0, "description": "Start angle (degrees)"},
            "end_angle": {"type": "number", "default": 90, "description": "End angle (degrees)"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def draw_arc(sw, cx=0, cy=0, radius=25, start_angle=0, end_angle=90, unit=None):
    return sw.draw_arc_center(cx, cy, radius, start_angle, end_angle, unit)


@tool(
    name="draw_polygon",
    description="Draw a regular polygon.",
    schema={
        "type": "object",
        "properties": {
            "cx": {"type": "number", "default": 0, "description": "Center X"},
            "cy": {"type": "number", "default": 0, "description": "Center Y"},
            "radius": {"type": "number", "default": 25, "description": "Radius"},
            "sides": {"type": "integer", "default": 6, "description": "Number of sides (3-100)"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def draw_polygon(sw, cx=0, cy=0, radius=25, sides=6, unit=None):
    return sw.draw_polygon(cx, cy, radius, sides, unit)


@tool(
    name="draw_spline",
    description="Draw a spline through ordered 2D points in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array", "minItems": 2,
                "items": {"type": "array", "minItems": 2, "maxItems": 2,
                          "items": {"type": "number"}}
            },
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": ["points"]
    },
    operation_class=OperationClass.MUTATE,
)
def draw_spline(sw, points=None, unit=None):
    return sw.draw_spline(points if points is not None else [], unit)


@tool(
    name="draw_arc_3point",
    description="Draw an arc from a start point to an end point through a third point.",
    schema={
        "type": "object",
        "properties": {
            "start_x": {"type": "number"}, "start_y": {"type": "number"},
            "end_x": {"type": "number"}, "end_y": {"type": "number"},
            "point_x": {"type": "number"}, "point_y": {"type": "number"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": ["start_x", "start_y", "end_x", "end_y", "point_x", "point_y"]
    },
    operation_class=OperationClass.MUTATE,
)
def draw_arc_3point(sw, start_x=None, start_y=None, end_x=None, end_y=None,
                    point_x=None, point_y=None, unit=None):
    return sw.draw_arc_3point(start_x, start_y, end_x, end_y, point_x, point_y, unit)


@tool(
    name="draw_slot",
    description="Draw a straight center-to-center slot in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x1": {"type": "number", "description": "First arc center X"},
            "y1": {"type": "number", "description": "First arc center Y"},
            "x2": {"type": "number", "description": "Second arc center X"},
            "y2": {"type": "number", "description": "Second arc center Y"},
            "width": {"type": "number", "exclusiveMinimum": 0,
                      "description": "Slot width"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": ["x1", "y1", "x2", "y2", "width"]
    },
    operation_class=OperationClass.MUTATE,
)
def draw_slot(sw, x1=None, y1=None, x2=None, y2=None, width=None, unit=None):
    return sw.draw_slot(x1, y1, x2, y2, width, unit)


@tool(
    name="close_sketch",
    description="Close/exit the active sketch. Call this before extrude if sketch is still open.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.MUTATE,
)
def close_sketch(sw):
    """
    Close the active sketch if one is open.
    Returns sketch status info.
    """
    try:
        doc, err = sw.get_active_doc()
        if err:
            return err

        # Check if sketch is active
        had_active = False
        try:
            active_sketch = doc.SketchManager.ActiveSketch
            had_active = active_sketch is not None
        except:
            pass

        if had_active:
            try:
                doc.SketchManager.InsertSketch(True)
            except:
                try:
                    doc.InsertSketch2(True)
                except:
                    pass

            return {
                "success": True,
                "message": "Sketch closed successfully",
                "error_code": 0,
                "error_name": "swSuccess",
                "data": {"had_active_sketch": True, "action": "closed"}
            }
        else:
            return {
                "success": True,
                "message": "No active sketch to close",
                "error_code": 0,
                "error_name": "swSuccess",
                "data": {"had_active_sketch": False, "action": "none"}
            }

    except Exception as e:
        logger.error(f"Close sketch error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {"traceback": traceback.format_exc()}
        }


@tool(
    name="get_sketch_status",
    description="Get diagnostic info: active sketch state, sketch count, sketch names in feature tree.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def get_sketch_status(sw):
    """
    Get diagnostic info about the current sketch state.
    Useful for debugging sketch/extrude issues.
    """
    try:
        doc, err = sw.get_active_doc()
        if err:
            return err

        info = {
            "has_active_sketch": False,
            "active_sketch_name": None,
            "sketch_count": 0,
            "sketch_names": [],
            "feature_count": 0,
            "extrusion_count": 0,
        }

        # Check active sketch
        try:
            active_sketch = doc.SketchManager.ActiveSketch
            if active_sketch is not None:
                info["has_active_sketch"] = True
                try:
                    info["active_sketch_name"] = active_sketch.Name
                except:
                    info["active_sketch_name"] = "<unknown>"
        except:
            pass

        # Walk feature tree (using PROPERTIES not methods)
        try:
            feat = doc.FirstFeature
            while feat is not None:
                try:
                    feat_type = feat.GetTypeName2
                    info["feature_count"] += 1

                    if feat_type == "ProfileFeature":
                        info["sketch_count"] += 1
                        info["sketch_names"].append(feat.Name)
                    elif feat_type == "Extrusion":
                        info["extrusion_count"] += 1
                except:
                    pass
                try:
                    feat = feat.GetNextFeature
                except:
                    break
        except:
            pass

        # Build readable message
        status = "OPEN" if info["has_active_sketch"] else "CLOSED"
        msg = (f"Sketch status: {status}. "
               f"Sketches: {info['sketch_count']} {info['sketch_names']}. "
               f"Extrusions: {info['extrusion_count']}. "
               f"Total features: {info['feature_count']}")

        return {
            "success": True,
            "message": msg,
            "error_code": 0,
            "error_name": "swSuccess",
            "data": info
        }

    except Exception as e:
        logger.error(f"Sketch status error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {"traceback": traceback.format_exc()}
        }
