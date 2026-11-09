"""Native, bounded pipe/tube CPoints on circular solid-body edges."""

import math

from ..comutil import com
from ..constants import SwDocumentTypes, SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .routing import (_routing_allowed, _require_active_document_type,
                      _connection_point_data, _point_vector, _point_number)


def _circular_edges(doc):
    """Return circular edge proxies and geometry, retaining native body order."""
    bodies = list(com(doc, "GetBodies2", 0, True) or [])
    if len(bodies) > 100:
        raise ValueError("Inspection is limited to 100 solid bodies.")
    result = []
    visited = 0
    for body_index, body in enumerate(bodies):
        for edge in com(body, "GetEdges") or []:
            visited += 1
            if visited > 1000:
                raise ValueError("Inspection is limited to 1000 solid-body edges.")
            curve = com(edge, "GetCurve")
            if not com(curve, "IsCircle"):
                continue
            params = com(curve, "CircleParams")
            if not isinstance(params, (list, tuple)) or len(params) != 7:
                raise ValueError("Circular edge has invalid native circle parameters.")
            center = _point_vector(params[:3], 1000.0)
            axis = _point_vector(params[3:6], 1.0)
            radius = _point_number(_point_number(params[6]) * 1000.0)
            axis_length = math.hypot(*axis)
            if radius <= 0 or not math.isfinite(axis_length) or not math.isclose(axis_length, 1.0, abs_tol=1e-6):
                raise ValueError("Circular edge has invalid radius/axis.")
            result.append({"reference_index": len(result), "body_index": body_index,
                           "center_mm": center, "axis": axis, "radius_mm": radius,
                           "edge": edge})
    return result


def _gate_part(sw):
    if not _routing_allowed():
        return None, sw._result(False, "Routing is disabled.", SwErrors.swInvalidInput,
                                {"code": "ROUTING_DISABLED"})
    doc, _, error = _require_active_document_type(sw, SwDocumentTypes.swDocPART)
    return doc, error


@tool(
    name="list_routing_reference_edges",
    description="Read circular solid-body edges for native piping CPoint creation. Returns zero-based reference_index, part-local center/radius in mm and axis. Refresh after each geometry change. Limited to 100 bodies/1000 edges; no selection or editing.",
    schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    operation_class=OperationClass.READ,
)
def list_routing_reference_edges(sw):
    doc, error = _gate_part(sw)
    if error: return error
    try:
        edges = _circular_edges(doc)
        return sw._result(True, "Circular Routing reference edges read.", data={
            "edges": [{k: v for k, v in item.items() if k != "edge"} for item in edges],
            "count": len(edges), "coordinate_system": "active_part_local", "length_unit": "mm"})
    except Exception as exc:
        return sw._result(False, f"Could not inspect Routing references: {exc}", SwErrors.swUnknownError)


def _point_names(doc):
    names = set()
    f = com(doc, "FirstFeature")
    for _ in range(1000):
        if f is None: return names
        if com(f, "GetTypeName2") == "ConnectionPoint": names.add(com(f, "Name"))
        f = com(f, "GetNextFeature")
    raise ValueError("Feature traversal exceeded 1000 features.")


@tool(
    name="create_routing_connection_point",
    description="Create a native pipe or tube CPoint on a circular solid edge from list_routing_reference_edges. Explicit mm diameter/stub, native default subtype; tube minimum-straight/end-adjustment fixed zero. Verifies persistent feature and stored values. Changes selection; no add-in load or route manager. Refresh edge references after changes.",
    schema={"type": "object", "properties": {
        "reference_index": {"type": "integer", "minimum": 0},
        "diameter_mm": {"type": "number", "exclusiveMinimum": 0},
        "stub_length_mm": {"type": "number", "minimum": 0, "default": 0},
        "route_kind": {"type": "string", "enum": ["pipe", "tube"], "default": "pipe"},
        "reverse_direction": {"type": "boolean", "default": False}},
        "required": ["reference_index", "diameter_mm"], "additionalProperties": False},
    operation_class=OperationClass.MUTATE,
)
def create_routing_connection_point(sw, reference_index, diameter_mm, stub_length_mm=0.0,
                                    reverse_direction=False, route_kind="pipe"):
    doc, error = _gate_part(sw)
    if error: return error
    attempted = False
    try:
        diameter = _point_number(diameter_mm)
        stub = _point_number(stub_length_mm)
        if diameter <= 0 or stub < 0 or not isinstance(reverse_direction, bool):
            raise ValueError("Diameter must be positive, stub nonnegative and reverse_direction boolean.")
        if route_kind not in ("pipe", "tube"):
            raise ValueError("route_kind must be pipe or tube.")
        native_type = 2 if route_kind == "pipe" else 1
        if isinstance(reference_index, bool) or not isinstance(reference_index, int) or reference_index < 0:
            raise ValueError("reference_index must be a nonnegative integer.")
        if com(doc, "GetActiveSketch2") is not None:
            raise ValueError("Close the active sketch before creating a CPoint.")
        refs = _circular_edges(doc)
        if reference_index >= len(refs): raise ValueError("Circular edge reference_index out of range; refresh references.")
        before = _point_names(doc)
        selection = com(com(doc, "SelectionManager"), "CreateSelectData")
        selection.Mark = 1
        doc.ClearSelection2(True)
        if not refs[reference_index]["edge"].Select4(False, selection):
            raise ValueError("Could not select the circular edge.")
        attempted = True
        ok = com(doc, "FeatureManager").InsertConnectionPoint(
            native_type, 0, reverse_direction, diameter/1000.0, stub/1000.0,
            0.0, 0.0, 0.0, "", 0.0, 0.0, False, "", "")
        added = _point_names(doc) - before
        if not ok or len(added) != 1:
            raise RuntimeError(f"Native result {ok!r}, added CPoints {sorted(added)!r}.")
        name = next(iter(added))
        feature = doc.FeatureByName(name)
        point = _connection_point_data(feature, name)
        axis = refs[reference_index]["axis"]
        axis_norm = math.hypot(*axis)
        expected_direction = [v/axis_norm * (-1 if reverse_direction else 1) for v in axis]
        matches = (point["read_complete"] and point["route_type_raw"] == native_type
                   and math.isclose(point["nominal_diameter_mm"], diameter, rel_tol=1e-8, abs_tol=1e-6)
                   and math.isclose(point["stub_length_mm"], stub, rel_tol=1e-8, abs_tol=1e-6)
                   and all(math.isclose(a, b, abs_tol=1e-6) for a, b in
                           zip(point["position_mm"], refs[reference_index]["center_mm"]))
                   and all(math.isclose(a, b, abs_tol=1e-6) for a, b in
                           zip(point["direction"], expected_direction)))
        if not matches:
            return sw._result(False, "CPoint created but native values did not verify.", SwErrors.swFeatureError,
                              {"mutation_attempted": True, "connection_point": point})
        return sw._result(True, "Native Routing CPoint created and verified.", data={
            "connection_point": point, "mutation_attempted": True,
            "reference_index": reference_index, "verification": "persistent_feature_and_native_values"})
    except ValueError as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput, {"mutation_attempted": attempted})
    except Exception as exc:
        return sw._result(False, f"CPoint creation failed: {exc}", SwErrors.swFeatureError,
                          {"mutation_attempted": attempted, "rollback_performed": False})
