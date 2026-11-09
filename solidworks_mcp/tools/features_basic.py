"""Basic solid features: extrude, cut, revolve, fillet, chamfer, feature list."""

import logging
import traceback

from ..comutil import com
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")


@tool(
    name="extrude_sketch",
    description="Extrude the active sketch (Boss-Extrude).",
    schema={
        "type": "object",
        "properties": {
            "depth": {"type": "number", "default": 10, "description": "Extrusion depth"},
            "both_directions": {"type": "boolean", "default": False, "description": "Extrude in both directions"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def extrude_sketch(sw, depth=10, both_directions=False, unit=None):
    return sw.extrude_sketch(depth, both_directions, unit)


@tool(
    name="cut_extrude",
    description="Cut extrude to remove material.",
    schema={
        "type": "object",
        "properties": {
            "depth": {"type": "number", "default": 10, "description": "Cut depth"},
            "through_all": {"type": "boolean", "default": False, "description": "Cut through all"},
            "both_directions": {"type": "boolean", "default": False, "description": "Cut both directions"},
            "flip_direction": {"type": "boolean", "description": "Explicit cut direction; omit to retry the opposite direction automatically"},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default (set_units)"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def cut_extrude(sw, depth=10, through_all=False, both_directions=False, unit=None,
                flip_direction=None):
    return sw.cut_extrude(depth, through_all, both_directions, unit, flip_direction)


@tool(
    name="revolve_sketch",
    description="Revolve the latest closed sketch around its construction centerline.",
    schema={
        "type": "object",
        "properties": {
            "angle": {"type": "number", "exclusiveMinimum": 0,
                      "maximum": 360, "default": 360,
                      "description": "Revolution angle in degrees"},
            "axis": {"type": "string", "enum": ["centerline"],
                     "default": "centerline",
                     "description": "Supported axis mode"}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def revolve_sketch(sw, angle=360, axis="centerline"):
    return sw.revolve_sketch(angle, axis)


@tool(
    name="fillet_edges",
    description="Edge fillet; native geometry verified; no save.",
    schema={
        "type": "object",
        "properties": {
            "radius": {"type": "number", "exclusiveMinimum": 0, "default": 2, "description": "Fillet radius"},
            "tangent_propagation": {"type":"boolean", "default":True},
            "edge_indices": {"type":"array","minItems":1,"maxItems":256,"uniqueItems":True,"items":{"type":"integer","minimum":0},"description":"Fresh list_body_edges indexes; exclusive with edge_points."},
            "edge_points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "description": "[x,y,z] in unit; omit edge inputs for selection."},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"]}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def fillet_edges(sw, radius=2, unit=None, edge_points=None, tangent_propagation=True,edge_indices=None):
    return sw.fillet_edges(radius, unit, edge_points, tangent_propagation=tangent_propagation,edge_indices=edge_indices)


@tool(
    name="chamfer_edges",
    description="Angle/distance or two-distance chamfer; native geometry verified; no save.",
    schema={
        "type": "object",
        "properties": {
            "distance": {"type": "number", "exclusiveMinimum":0, "default": 2, "description": "First distance"},
            "angle": {"type": "number", "exclusiveMinimum":0, "exclusiveMaximum":90, "default": 45, "description": "Degrees; angle_distance only"},
            "chamfer_type": {"type":"string", "enum":["angle_distance","distance_distance"], "default":"angle_distance"},
            "distance2": {"type":"number", "exclusiveMinimum":0, "description":"Required only for distance_distance"},
            "tangent_propagation": {"type":"boolean", "default":True},
            "flip_direction": {"type":"boolean", "default":False, "description":"Swap distance sides"},
            "edge_indices": {"type":"array","minItems":1,"maxItems":256,"uniqueItems":True,"items":{"type":"integer","minimum":0},"description":"Fresh list_body_edges indexes; exclusive with edge_points."},
            "edge_points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "description": "[x,y,z] in unit; omit edge inputs for selection."},
            "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"]}
        },
        "required": []
    },
    operation_class=OperationClass.MUTATE,
)
def chamfer_edges(sw, distance=2, angle=45, unit=None, edge_points=None,
                  chamfer_type='angle_distance', distance2=None,
                  tangent_propagation=True, flip_direction=False,edge_indices=None):
    return sw.chamfer_edges(distance, angle, unit, edge_points,
        chamfer_type=chamfer_type, distance2=distance2,
        tangent_propagation=tangent_propagation, flip_direction=flip_direction,edge_indices=edge_indices)


@tool(
    name="list_features",
    description="List all features in the model.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def list_features(sw):
    """
    List all features in the active document.
    FIXED v4.1: Property access for SW 2025 (FirstFeature, GetNextFeature, GetTypeName2).
    """
    try:
        doc, err = sw.get_active_doc()
        if err:
            return err

        features = []

        # FIXED (B17): CDispatch.__call__ always reports callable()==True even for
        # properties, so `if callable(x): x()` invokes properties as if they were
        # methods and raises "Member not found", which the bare except then
        # misread as "end of feature tree" -- stopping after the first feature.
        # com() resolves this correctly via inspect.ismethod().
        feat = com(doc, "FirstFeature")

        while feat is not None:
            try:
                name = com(feat, "Name")
            except:
                name = "<unknown>"

            try:
                feat_type = com(feat, "GetTypeName2")
            except:
                try:
                    feat_type = com(feat, "GetTypeName")
                except:
                    feat_type = "<unknown>"

            try:
                suppressed = com(feat, "IsSuppressed")
            except:
                suppressed = False

            features.append({
                "name": name,
                "type": feat_type,
                "suppressed": bool(suppressed)
            })

            feat = com(feat, "GetNextFeature")

        return {
            "success": True,
            "message": f"{len(features)} features found",
            "error_code": 0,
            "error_name": "swSuccess",
            "data": {"features": features, "count": len(features)}
        }

    except Exception as e:
        logger.error(f"List features error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {}
        }
