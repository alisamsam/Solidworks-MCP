"""Bounded read of one top-level assembly component's native connection points.

This tool resolves exactly one *direct* child of the active assembly by its
exact ``Name2`` -- mirroring the exact-name pattern of
``assembly._find_component`` but restricted to the bounded top-level
``GetComponents(True)`` list, so a nested instance path can never be matched
and no component is resolved or unsuppressed. The referenced part document is
read only when it is already loaded (``IComponent2.GetModelDoc2``) and is
rejected unless it is a part; an unavailable document or an unreadable
transform is reported as an explicit error, never as an empty count.

The connection points themselves come from ``routing._connection_point_data``
(``ConnectionPoint`` -> ``GetDefinition`` properties), so the part-local
fields are byte-for-byte the RT2 read.

Before any connection point is read, the component's ``ReferencedConfiguration``
must equal the loaded part's ``ConfigurationManager.ActiveConfiguration.Name``.
``GetModelDoc2`` can return a document whose active configuration differs from
the configuration this instance references, which would silently attach the
wrong CPoint set; a missing or unreadable configuration is
``CONFIGURATION_UNAVAILABLE`` and a readable mismatch is
``CONFIGURATION_MISMATCH``, both returning ``count: null`` with the expected
and active names as evidence. No configuration is ever activated
(``ShowConfiguration2`` is never used).

On top of the part-local data this tool derives the assembly placement with the
repository's verified manual matrix multiply (``assembly._local_to_global``
over ``IComponent2.Transform2.ArrayData``, 16 floats: rotation 0..8,
translation 9..11 in metres, scale at 12). Only rigid placements are
advertised: the scale must be 1 and the 3x3 block must be a proper rotation
(orthonormal, determinant +1); a scaled, mirrored or non-orthonormal matrix is
rejected instead of being applied. The part-local ``position_mm`` is converted
to metres for that native transform and the result is converted back to mm; the
assembly direction is the translation-free, normalised rotation image of the
part direction. The native ``nominal_diameter_mm`` is passed through unchanged.

Read-only and bounded: at most 1000 examined top-level components and at most
1000 visited part features, both stated in ``coverage``. The tool never
selects, edits, resolves, loads an add-in, rebuilds or saves, and it performs
no nested branch recursion.
"""

import math
from typing import Any, Dict, List, Optional

from ..comutil import com
from ..constants import SwDocumentTypes, SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from . import assembly, routing

# Explicit bounds; both are reported in ``coverage``.
_MAX_COMPONENTS = 1000
_MAX_FEATURES = 1000
_TRANSFORM_LENGTH = 16
_DIRECTION_EPSILON = 1e-12
# Only rigid placements (unit scale, proper rotation) are advertised.
_SCALE_TOLERANCE = 1e-9
_ROTATION_TOLERANCE = 1e-6

_PART_DOCUMENT_TYPE = int(SwDocumentTypes.swDocPART)

_NOTES = [
    "Part-local position_mm, direction and nominal_diameter_mm are the native "
    "ConnectionPoint values and are unchanged; the assembly_* fields are derived.",
    "Connection points are read only when the component's ReferencedConfiguration "
    "equals the loaded part's active configuration; no configuration is activated.",
    "Assembly placement uses the component's Transform2.ArrayData with the verified "
    "row-vector matrix multiply (assembly._local_to_global): part-local mm is converted "
    "to metres for the native transform and the result converted back to mm.",
    "Only rigid placements are supported: unit scale and an orthonormal rotation with "
    "determinant +1; scaled, mirrored or non-orthonormal transforms are rejected.",
    "Assembly direction is the rotation-only image of the part direction with "
    "translation excluded, normalised; the part direction is rejected if it does not "
    "define an orientation.",
    "Nominal diameter is the native nominal route diameter, not a measured fitting OD.",
    "Read-only: no selection, edit mode, resolve/unsuppress, configuration activation, "
    "add-in load, rebuild or save.",
]


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _find_top_level_component(asm, component_name: str):
    """Resolve one exact ``Name2`` among the bounded direct children.

    Returns ``(component, examined, truncated)``. ``examined`` is the number of
    direct components inspected and ``truncated`` is True when the assembly
    exposes more direct components than the bound allows. No nested path,
    suffix or recursive match is attempted.
    """
    components = list(com(asm, "GetComponents", True) or [])
    truncated = len(components) > _MAX_COMPONENTS
    examined = components[:_MAX_COMPONENTS]
    for index, component in enumerate(examined, 1):
        if com(component, "Name2") == component_name:
            return component, index, truncated
    return None, len(examined), truncated


def _validate_rotation(transform) -> None:
    """Reject a non-orthonormal or mirrored 3x3 rotation block.

    In the repo's row-vector convention rows 0..2 / 3..5 / 6..8 are the images
    of the local X / Y / Z axes, so a rigid placement has orthonormal rows and
    determinant +1. A reflection, shear or non-unit row would silently produce
    an invalid assembly point, so it is rejected instead.
    """
    r = transform[:9]
    rows = (r[0:3], r[3:6], r[6:9])
    for index, row in enumerate(rows):
        norm = math.sqrt(sum(value * value for value in row))
        if abs(norm - 1.0) > _ROTATION_TOLERANCE:
            raise ValueError(
                f"Rotation row {index} has length {norm!r}; the matrix is not a rigid rotation."
            )
    for first, second in ((0, 1), (0, 2), (1, 2)):
        dot = sum(a * b for a, b in zip(rows[first], rows[second]))
        if abs(dot) > _ROTATION_TOLERANCE:
            raise ValueError(
                "Rotation rows are not orthogonal; the matrix is not a rigid rotation."
            )
    determinant = (
        r[0] * (r[4] * r[8] - r[5] * r[7])
        - r[1] * (r[3] * r[8] - r[5] * r[6])
        + r[2] * (r[3] * r[7] - r[4] * r[6])
    )
    if abs(determinant - 1.0) > _ROTATION_TOLERANCE:
        raise ValueError(
            f"Rotation determinant is {determinant!r}, not +1; a reflection or "
            f"degenerate placement is unsupported."
        )


def _component_transform(component) -> List[float]:
    """Validated rigid 16-value ``Transform2.ArrayData`` of the component.

    Only unit-scale rigid placements are advertised: a scale other than 1 is
    rejected because the dimensional semantics of a scaled instance transform
    have not been verified in this repository.
    """
    values = list(com(com(component, "Transform2"), "ArrayData") or [])
    if len(values) != _TRANSFORM_LENGTH:
        raise ValueError(
            f"Transform2.ArrayData returned {len(values)} of {_TRANSFORM_LENGTH} values."
        )
    if not all(_finite(value) for value in values):
        raise ValueError("Transform2.ArrayData contains a non-finite value.")
    numbers = [float(value) for value in values]
    if abs(numbers[12] - 1.0) > _SCALE_TOLERANCE:
        raise ValueError(
            f"Component scale {numbers[12]!r} is not unit; only rigid placements "
            f"(scale 1) are supported."
        )
    _validate_rotation(numbers)
    return numbers


def _assembly_direction(direction, transform) -> List[float]:
    """Rotation-only, translation-free assembly image of a part direction."""
    rotation = list(transform)
    rotation[9:13] = [0.0, 0.0, 0.0, 1.0]
    x, y, z = assembly._local_to_global(direction, rotation)
    length = math.sqrt(x * x + y * y + z * z)
    if not math.isfinite(length) or length <= _DIRECTION_EPSILON:
        raise ValueError("Connection point direction has no usable orientation.")
    return [x / length, y / length, z / length]


def _assembly_placement(position_mm, direction, transform):
    """Return (assembly_position_mm, assembly_direction, problems)."""
    position: Optional[List[float]] = None
    rotated: Optional[List[float]] = None
    problems: List[str] = []

    if position_mm is None:
        problems.append("Part-local position unavailable.")
    else:
        try:
            local_m = [value / 1000.0 for value in position_mm]
            x, y, z = assembly._local_to_global(local_m, transform)
            candidate = [x * 1000.0, y * 1000.0, z * 1000.0]
            if not all(_finite(value) for value in candidate):
                raise ValueError("non-finite result")
            position = candidate
        except Exception as exc:
            problems.append(f"Assembly position: {exc}")

    if direction is None:
        problems.append("Part-local direction unavailable.")
    else:
        try:
            rotated = _assembly_direction(direction, transform)
        except Exception as exc:
            problems.append(f"Assembly direction: {exc}")

    return position, rotated, problems


def _part_connection_points(part_doc):
    """Bounded walk of the part's top-level ``ConnectionPoint`` features.

    Returns ``(points, traversal_errors, visited, truncated)``. The traversal
    is linear (``FirstFeature``/``GetNextFeature``), never recursive, and stops
    after ``_MAX_FEATURES`` features with ``truncated`` set.
    """
    points: List[Dict[str, Any]] = []
    errors: List[str] = []
    visited = 0
    truncated = False
    retained: List[Any] = []  # keep proxies alive during the native traversal
    try:
        feature = com(part_doc, "FirstFeature")
        while feature is not None and visited < _MAX_FEATURES:
            retained.append(feature)
            visited += 1
            if com(feature, "GetTypeName2") == "ConnectionPoint":
                points.append(
                    routing._connection_point_data(feature, com(feature, "Name"))
                )
            feature = com(feature, "GetNextFeature")
        truncated = feature is not None
    except Exception as exc:
        errors.append(f"Feature traversal: {exc}")
    return points, errors, visited, truncated


def _part_document(component):
    """Already-loaded referenced part, or None with an explicit reason.

    ``GetModelDoc2`` returns the referenced document only when it is loaded.
    A lightweight or suppressed component exposes None; it is reported, never
    resolved in place.
    """
    document = com(component, "GetModelDoc2")
    if document is None:
        return None, (
            "The component's referenced part is not loaded "
            "(lightweight or suppressed) and was not resolved."
        )
    document_type = com(document, "GetType")
    if document_type != _PART_DOCUMENT_TYPE:
        return None, (
            f"The component's referenced document is not a part "
            f"(type {document_type}); assembly connection points require a part."
        )
    return document, None


def _configuration_state(component, part):
    """Compare the instance configuration with the loaded part's active one.

    ``GetModelDoc2`` returns the part document itself, not the instance's
    configuration view: if the part's active configuration is not the one the
    component references, reading its connection points would describe the
    wrong configuration. Returns ``(state, code, message)`` where ``code`` is
    None on a match. Read-only: no configuration is ever activated.
    """
    problems: List[str] = []

    referenced = None
    try:
        referenced = com(component, "ReferencedConfiguration")
    except Exception as exc:
        problems.append(f"ReferencedConfiguration unreadable: {exc}")
    if not isinstance(referenced, str) or not referenced:
        problems.append("ReferencedConfiguration is not a non-empty string.")

    active = None
    try:
        manager = com(part, "ConfigurationManager")
    except Exception as exc:
        manager = None
        problems.append(f"ConfigurationManager unreadable: {exc}")
    if manager is None:
        if not any("ConfigurationManager" in message for message in problems):
            problems.append("ConfigurationManager is null.")
    else:
        try:
            active_configuration = com(manager, "ActiveConfiguration")
        except Exception as exc:
            active_configuration = None
            problems.append(f"ActiveConfiguration unreadable: {exc}")
        if active_configuration is None:
            if not any("ActiveConfiguration" in message for message in problems):
                problems.append("ActiveConfiguration is null.")
        else:
            try:
                active = com(active_configuration, "Name")
            except Exception as exc:
                problems.append(f"ActiveConfiguration.Name unreadable: {exc}")
            else:
                if not isinstance(active, str) or not active:
                    problems.append("ActiveConfiguration.Name is not a non-empty string.")

    state = {
        "referenced": referenced if isinstance(referenced, str) and referenced else None,
        "active": active if isinstance(active, str) and active else None,
        "matched": False,
    }
    if problems:
        state["evidence"] = problems
        return state, "CONFIGURATION_UNAVAILABLE", "; ".join(problems)
    if state["referenced"] != state["active"]:
        state["evidence"] = [
            f"ReferencedConfiguration={state['referenced']!r}",
            f"ActiveConfiguration={state['active']!r}",
        ]
        return state, "CONFIGURATION_MISMATCH", (
            f"Component references configuration {state['referenced']!r} but the loaded "
            f"part's active configuration is {state['active']!r}; no configuration was activated."
        )
    state["matched"] = True
    return state, None, None


def _document_identity(document):
    title = path = None
    try:
        title = com(document, "GetTitle")
    except Exception:
        title = None
    try:
        path = com(document, "GetPathName")
    except Exception:
        path = None
    return {"title": title or None, "path": path or None}


@tool(
    name="get_component_connection_points",
    description=(
        "Read one exact top-level assembly component's native ConnectionPoint features "
        "in part-local mm and, using the component's verified rigid transform, their "
        "assembly position (mm) and direction. Requires an existing MCP connection, a "
        "loaded referenced part and a matching ReferencedConfiguration. No selection, "
        "resolve, edit, configuration activation, add-in load or save; read-only and bounded."
    ),
    schema={
        "type": "object",
        "properties": {
            "component_name": {
                "type": "string",
                "minLength": 1,
                "description": "Exact top-level component Name2, e.g. \"Flange1-1\".",
            }
        },
        "required": ["component_name"],
        "additionalProperties": False,
    },
    operation_class=OperationClass.READ,
    com=True,
)
def get_component_connection_points(sw, component_name) -> Dict:
    """Read assembly placement of one top-level component's connection points."""
    if not routing._routing_allowed():
        return sw._result(
            False,
            "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
            "and restart the MCP server.",
            SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        )

    if not isinstance(component_name, str) or not component_name or "/" in component_name:
        return sw._result(
            False,
            "An exact top-level component Name2 (no '/' path separator) is required.",
            SwErrors.swInvalidInput,
            {"code": "INVALID_COMPONENT_NAME"},
        )

    asm, _, error = routing._require_active_assembly(sw)
    if error:
        return error

    errors: List[str] = []

    try:
        component, examined, components_truncated = _find_top_level_component(
            asm, component_name
        )
    except Exception as exc:
        return sw._result(
            False,
            f"Could not read the top-level components: {exc}",
            SwErrors.swUnknownError,
            {"code": "COMPONENTS_UNREADABLE"},
        )

    if component is None:
        data = {
            "component_name": component_name,
            "examined_components": examined,
            "component_limit": _MAX_COMPONENTS,
            "components_truncated": components_truncated,
            "code": "COMPONENT_NOT_FOUND",
        }
        note = (
            " The top-level search was truncated at the component limit, so the "
            "exact name was not searched exhaustively."
            if components_truncated
            else ""
        )
        return sw._result(
            False,
            f"Exact top-level component not found: {component_name}.{note}",
            SwErrors.swInvalidInput,
            data,
        )

    # Component transform next: it is read from the resolved instance only.
    transform: Optional[List[float]] = None
    try:
        transform = _component_transform(component)
    except Exception as exc:
        errors.append(f"Component transform unavailable: {exc}")

    component_identity = {"name": com(component, "Name2"), "path": None}
    try:
        component_identity["path"] = com(component, "GetPathName") or None
    except Exception:
        component_identity["path"] = None

    try:
        part, part_error = _part_document(component)
    except Exception as exc:
        part, part_error = None, f"Referenced part could not be read: {exc}"

    transform_block = {
        "array_data": transform,
        "translation_mm": [value * 1000.0 for value in transform[9:12]] if transform else None,
        "scale": transform[12] if transform else None,
        "valid": transform is not None,
    }
    coverage_base = {
        "scope": "referenced_part_top_level_features",
        "visited_features": 0,
        "feature_limit": _MAX_FEATURES,
        "features_truncated": False,
        "examined_components": examined,
        "component_limit": _MAX_COMPONENTS,
        "components_truncated": components_truncated,
    }

    if part is None:
        errors.append(f"Referenced part unavailable: {part_error}")
        data = {
            "component_name": component_name,
            "component": component_identity,
            "part": None,
            "configuration": None,
            "code": "PART_UNAVAILABLE",
            "coordinate_system": "active_assembly",
            "length_unit": "mm",
            "transform": transform_block,
            "connection_points": [],
            "count": None,
            "coverage": {
                **coverage_base,
                "connection_point_count": None,
                "complete": False,
                "partial": True,
                "unresolved": list(errors),
            },
            "errors": errors,
            "notes": _NOTES,
        }
        return sw._result(
            False,
            f"Connection points for {component_name} could not be read: "
            f"{part_error}",
            SwErrors.swUnknownError,
            data,
        )

    # The loaded part's active configuration must be the one the instance
    # references, otherwise the CPoint set belongs to a different configuration.
    config_state, config_code, config_error = _configuration_state(component, part)
    if config_code is not None:
        errors.append(config_error)
        data = {
            "component_name": component_name,
            "component": component_identity,
            "part": _document_identity(part),
            "configuration": config_state,
            "code": config_code,
            "coordinate_system": "active_assembly",
            "length_unit": "mm",
            "transform": transform_block,
            "connection_points": [],
            "count": None,
            "coverage": {
                **coverage_base,
                "connection_point_count": None,
                "complete": False,
                "partial": True,
                "unresolved": list(errors),
            },
            "errors": errors,
            "notes": _NOTES,
        }
        return sw._result(
            False,
            f"Connection points for {component_name} were not read: {config_error}",
            SwErrors.swInvalidInput
            if config_code == "CONFIGURATION_MISMATCH"
            else SwErrors.swUnknownError,
            data,
        )

    raw_points, traversal_errors, visited, truncated = _part_connection_points(part)
    errors.extend(traversal_errors)

    points: List[Dict[str, Any]] = []
    point_errors: List[str] = []
    for raw in raw_points:
        entry = dict(raw)
        entry["errors"] = list(raw["errors"])
        position, direction, problems = (None, None, ["Component transform unavailable."])
        if transform is not None:
            position, direction, problems = _assembly_placement(
                raw["position_mm"], raw["direction"], transform
            )
        elif raw["position_mm"] is not None or raw["direction"] is not None:
            problems = ["Component transform unavailable."]
        entry["assembly_position_mm"] = position
        entry["assembly_direction"] = direction
        entry["assembly_placement_complete"] = not problems
        entry["assembly_errors"] = problems
        point_errors.extend(
            f"{entry['feature_name']}: {message}" for message in problems
        )
        for message in entry["errors"]:
            point_errors.append(f"{entry['feature_name']}: {message}")
        points.append(entry)

    errors.extend(point_errors)

    complete = (
        not errors
        and not truncated
        and all(point["read_complete"] for point in points)
        and all(point["assembly_placement_complete"] for point in points)
    )

    data = {
        "component_name": component_name,
        "component": component_identity,
        "part": _document_identity(part),
        "configuration": config_state,
        "coordinate_system": "active_assembly",
        "length_unit": "mm",
        "transform": transform_block,
        "connection_points": points,
        "count": len(points),
        "coverage": {
            **coverage_base,
            "visited_features": visited,
            "features_truncated": truncated,
            "connection_point_count": len(points),
            "complete": complete,
            "partial": not complete,
            "unresolved": list(errors),
        },
        "errors": errors,
        "notes": _NOTES,
    }

    if complete:
        message = (
            f"Read {len(points)} connection point(s) on {component_name} in the "
            f"assembly frame."
        )
    else:
        message = (
            f"Connection point placement for {component_name} is incomplete or "
            f"unresolved; see coverage and errors."
        )
    return sw._result(
        complete,
        message,
        SwErrors.swSuccess if complete else SwErrors.swUnknownError,
        data,
    )
