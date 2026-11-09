"""Read-only geometric gap between two native connection points (RT2 measure).

This tool composes the bounded RT2 component read
(``routing_components.get_component_connection_points``) instead of touching
COM itself. Each of the two named connections is read exactly like one RT2
call, and both reads must succeed with *complete* coverage: that guarantees an
exact top-level loaded part, a matching ``ReferencedConfiguration`` and a
verified rigid (unit-scale, proper-rotation) placement, so the reported
``assembly_position_mm`` and ``assembly_direction`` are native-derived.

On top of the two reads it computes a purely geometric measurement in the
active assembly frame:

* ``delta_mm`` -- second minus first assembly position,
* ``distance_mm`` -- ``math.hypot`` of that delta,
* ``diameter_difference_mm`` -- second minus first native nominal diameter,
* ``direction_dot`` -- dot product of the two normalised assembly directions,
* ``opposition_angle_deg`` -- ``degrees(acos(clamp(-direction_dot)))``, so 0
  degrees means the directions face opposite and 180 degrees means they point
  the same way.

Both directions must be finite and non-zero; a degenerate or unreadable vector
is reported as an error, never replaced by a fabricated value. ``route_type_equal``
compares the two raw CPoint ``RouteType`` integers and is reported strictly as
that integer comparison -- never as connectivity, a mate, a native route or
proof of physical compatibility. There is no tolerance parameter and no
pass/fail status: the result is a native read measurement only.

Read-only: the tool never selects, resolves, activates a configuration, loads
an add-in, rebuilds or saves, and it never binds or edits a route. The Routing
gate is evaluated before any SolidWorks access.
"""

import math
from typing import Any, Dict, List, Optional

from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from . import routing_components
from .routing import _routing_allowed

_DIRECTION_EPSILON = 1e-12

_NOTES = [
    "Read-only native measurement: no selection, resolve/unsuppress, edit mode, "
    "configuration activation, add-in load, rebuild or save.",
    "Both connection points are read through get_component_connection_points and "
    "each read must succeed with complete coverage and an exact point feature_name "
    "match; partial or missing data is never fabricated.",
    "Positions and distances use the active assembly frame in mm. Delta and diameter "
    "difference are second minus first; distance is the unsigned Euclidean magnitude.",
    "direction_dot is the dot product of the two normalised assembly directions; "
    "opposition_angle_deg = degrees(acos(clamp(-direction_dot))), so 0 deg means the "
    "directions face opposite and 180 deg means they point the same way.",
    "nominal_diameter_mm is the native nominal route diameter, not a measured fitting OD.",
    "route_type_equal compares the two raw CPoint RouteType integers and is not "
    "connectivity, a mate, a native route or proof of physical compatibility.",
    "No tolerance or pass/fail parameter is accepted; no connectivity, mate or "
    "compatibility result is reported.",
]


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _finite_vector(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_finite(component) for component in value)
    )


def _unit_direction(value) -> Optional[List[float]]:
    """Normalised assembly direction, or None when it is unusable."""
    if not _finite_vector(value):
        return None
    length = math.sqrt(sum(component * component for component in value))
    if not math.isfinite(length) or length <= _DIRECTION_EPSILON:
        return None
    return [component / length for component in value]


def _raw_route_type(value) -> Optional[int]:
    """Native CPoint RouteType as a raw int, or None when it was not read."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _find_point(points, feature_name) -> Optional[Dict[str, Any]]:
    """Exact ``feature_name`` match among the read connection points."""
    for point in points or []:
        if point.get("feature_name") == feature_name:
            return point
    return None


def _error_enum(name):
    """Map a preserved upstream error name back to SwErrors, safely."""
    if isinstance(name, str):
        try:
            return SwErrors[name]
        except KeyError:
            pass
    return SwErrors.swUnknownError


def _measurement(first: Dict[str, Any], second: Dict[str, Any]):
    """Return (measurement, errors) from two read connection points."""
    errors: List[str] = []

    first_position = first.get("assembly_position_mm")
    second_position = second.get("assembly_position_mm")
    if not _finite_vector(first_position):
        errors.append("first assembly_position_mm is unavailable or not three finite numbers.")
    if not _finite_vector(second_position):
        errors.append("second assembly_position_mm is unavailable or not three finite numbers.")

    first_direction = _unit_direction(first.get("assembly_direction"))
    second_direction = _unit_direction(second.get("assembly_direction"))
    if first_direction is None:
        errors.append(
            "first assembly_direction is unavailable, not three finite numbers, or has zero length."
        )
    if second_direction is None:
        errors.append(
            "second assembly_direction is unavailable, not three finite numbers, or has zero length."
        )

    first_diameter = first.get("nominal_diameter_mm")
    second_diameter = second.get("nominal_diameter_mm")
    if not _finite(first_diameter):
        errors.append("first nominal_diameter_mm is unavailable.")
    if not _finite(second_diameter):
        errors.append("second nominal_diameter_mm is unavailable.")

    first_type = _raw_route_type(first.get("route_type_raw"))
    second_type = _raw_route_type(second.get("route_type_raw"))
    route_type_equal: Optional[bool] = None
    if first_type is None or second_type is None:
        errors.append("raw CPoint route_type is unavailable for both points.")
    else:
        route_type_equal = first_type == second_type

    delta = distance = None
    if _finite_vector(first_position) and _finite_vector(second_position):
        delta = [second_position[i] - first_position[i] for i in range(3)]
        distance = math.hypot(delta[0], delta[1], delta[2])
        if not _finite_vector(delta) or not _finite(distance):
            delta = distance = None
            errors.append("Position difference overflowed finite measurement range.")

    diameter_difference = None
    if _finite(first_diameter) and _finite(second_diameter):
        diameter_difference = second_diameter - first_diameter
        if not _finite(diameter_difference):
            diameter_difference = None
            errors.append("Diameter difference overflowed finite measurement range.")

    direction_dot = opposition_angle_deg = None
    if first_direction is not None and second_direction is not None:
        direction_dot = sum(a * b for a, b in zip(first_direction, second_direction))
        clamped = max(-1.0, min(1.0, direction_dot))
        opposition_angle_deg = math.degrees(math.acos(-clamped))

    measurement = {
        "first": {
            "assembly_position_mm": first_position if _finite_vector(first_position) else None,
            "assembly_direction": first_direction,
            "nominal_diameter_mm": first_diameter if _finite(first_diameter) else None,
            "route_type_raw": first_type,
            "route_subtype_raw": _raw_route_type(first.get("route_subtype_raw")),
        },
        "second": {
            "assembly_position_mm": second_position if _finite_vector(second_position) else None,
            "assembly_direction": second_direction,
            "nominal_diameter_mm": second_diameter if _finite(second_diameter) else None,
            "route_type_raw": second_type,
            "route_subtype_raw": _raw_route_type(second.get("route_subtype_raw")),
        },
        "delta_mm": delta,
        "distance_mm": distance,
        "diameter_difference_mm": diameter_difference,
        "direction_dot": direction_dot,
        "opposition_angle_deg": opposition_angle_deg,
        "route_type_equal": route_type_equal,
    }
    return measurement, errors


def _component_evidence(data: Dict[str, Any], component_name, point_name):
    """Reference and configuration evidence carried over from one RT2 read."""
    coverage = data.get("coverage") or {}
    return {
        "component_name": component_name,
        "point_name": point_name,
        "component": data.get("component"),
        "part": data.get("part"),
        "configuration": data.get("configuration"),
        "connection_point_count": data.get("count"),
        "coverage_complete": bool(coverage.get("complete")),
    }


def _read_ready(result) -> bool:
    """True only when an RT2 read succeeded with complete coverage."""
    if not result.get("success"):
        return False
    coverage = (result.get("data") or {}).get("coverage") or {}
    return coverage.get("complete") is True


def _upstream_failure(sw, result, role, component_name):
    """Failure result when one RT2 read did not succeed with complete coverage.

    The upstream reason is preserved verbatim in the message and in the
    ``upstream`` evidence block; nothing is inferred from a partial read.
    """
    data = result.get("data") or {}
    coverage = data.get("coverage") or {}
    complete = coverage.get("complete") is True
    reason = result.get("message") or "the component read did not report success."
    upstream_code = data.get("code")
    upstream_name = result.get("error_name")

    if result.get("success") and not complete:
        code = "INCOMPLETE_COVERAGE"
        error = SwErrors.swUnknownError
        message = (
            f"{component_name} connection points were read without complete coverage; "
            f"the measurement was not computed."
        )
    else:
        code = "COMPONENT_READ_FAILED"
        error = _error_enum(upstream_name)
        message = f"{component_name} connection points could not be read: {reason}"

    return sw._result(
        False,
        message,
        error,
        {
            "code": code,
            "source": role,
            "component_name": component_name,
            "upstream": {
                "success": bool(result.get("success")),
                "message": reason,
                "error_name": upstream_name,
                "error_code": result.get("error_code"),
                "code": upstream_code,
                "coverage_complete": complete,
            },
            "notes": _NOTES,
        },
    )


def _point_not_found(sw, role, component_name, point_name, points):
    available = [point.get("feature_name") for point in points or []]
    return sw._result(
        False,
        f"Connection point {point_name!r} was not found on {component_name} "
        f"(available: {available}); an exact feature_name match is required.",
        SwErrors.swInvalidInput,
        {
            "code": "POINT_NOT_FOUND",
            "source": role,
            "component_name": component_name,
            "point_name": point_name,
            "available_points": available,
            "notes": _NOTES,
        },
    )


@tool(
    name="measure_routing_connection_gap",
    description=(
        "Measure the read-only native gap between two exact top-level fitting connection "
        "points: assembly delta in mm, Euclidean distance, nominal-diameter difference, "
        "normalised direction dot and opposition angle (0 deg facing opposite, 180 deg same "
        "direction), plus raw CPoint route-type equality. Reads both points through "
        "get_component_connection_points and requires loaded, same-configuration, rigidly "
        "placed parts; it never claims connectivity, a mate, a native route or physical "
        "compatibility. Requires an existing MCP connection."
    ),
    schema={
        "type": "object",
        "properties": {
            "component1": {
                "type": "string",
                "minLength": 1,
                "description": "Exact top-level component Name2 of the first connection.",
            },
            "point1": {
                "type": "string",
                "minLength": 1,
                "description": "Exact ConnectionPoint feature name on the first component.",
            },
            "component2": {
                "type": "string",
                "minLength": 1,
                "description": "Exact top-level component Name2 of the second connection.",
            },
            "point2": {
                "type": "string",
                "minLength": 1,
                "description": "Exact ConnectionPoint feature name on the second component.",
            },
        },
        "required": ["component1", "point1", "component2", "point2"],
        "additionalProperties": False,
    },
    operation_class=OperationClass.READ,
    com=True,
)
def measure_routing_connection_gap(sw, component1, point1, component2, point2) -> Dict:
    """Measure the assembly-frame gap between two native connection points."""
    if not _routing_allowed():
        return sw._result(
            False,
            "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
            "and restart the MCP server.",
            SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        )

    arguments = (
        ("component1", component1),
        ("point1", point1),
        ("component2", component2),
        ("point2", point2),
    )
    for label, value in arguments:
        if not isinstance(value, str) or not value:
            return sw._result(
                False,
                f"{label} must be a non-empty string.",
                SwErrors.swInvalidInput,
                {"code": "INVALID_ARGUMENTS", "argument": label},
            )

    if component1 == component2 and point1 == point2:
        return sw._result(
            False,
            f"component1/point1 and component2/point2 are the same connection point "
            f"({component1} / {point1}); a gap requires two distinct connection points.",
            SwErrors.swInvalidInput,
            {
                "code": "SAME_CONNECTION_POINT",
                "component_name": component1,
                "point_name": point1,
                "notes": _NOTES,
            },
        )

    first = routing_components.get_component_connection_points(sw, component1)
    if not _read_ready(first):
        return _upstream_failure(sw, first, "first", component1)

    second = routing_components.get_component_connection_points(sw, component2)
    if not _read_ready(second):
        return _upstream_failure(sw, second, "second", component2)

    first_points = (first.get("data") or {}).get("connection_points") or []
    second_points = (second.get("data") or {}).get("connection_points") or []

    first_point = _find_point(first_points, point1)
    if first_point is None:
        return _point_not_found(sw, "first", component1, point1, first_points)

    second_point = _find_point(second_points, point2)
    if second_point is None:
        return _point_not_found(sw, "second", component2, point2, second_points)

    measurement, errors = _measurement(first_point, second_point)

    data = {
        "coordinate_system": "active_assembly",
        "length_unit": "mm",
        "components": {
            "first": _component_evidence(first.get("data") or {}, component1, point1),
            "second": _component_evidence(second.get("data") or {}, component2, point2),
        },
        "measurement": measurement,
        "errors": errors,
        "notes": _NOTES,
    }

    if errors:
        return sw._result(
            False,
            f"The gap between {component1}/{point1} and {component2}/{point2} could not be "
            f"fully measured; see errors. Missing or degenerate native data is never "
            f"fabricated.",
            SwErrors.swUnknownError,
            data,
        )

    return sw._result(
        True,
        f"Measured {measurement['distance_mm']:.3f} mm between {component1}/{point1} and "
        f"{component2}/{point2}; opposition_angle_deg="
        f"{measurement['opposition_angle_deg']:.3f}, route_type_equal="
        f"{measurement['route_type_equal']}.",
        SwErrors.swSuccess,
        data,
    )
