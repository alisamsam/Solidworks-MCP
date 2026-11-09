"""Bounded read-only read of one exact named native 3D sketch (RT3 path).

``list_routing_path_segments`` inspects exactly one named native 3D sketch
feature in the active assembly and reports its sketch segments. It never edits
the route, never selects or resolves anything, never rebuilds, never activates a
configuration, never loads the Routing add-in and never starts or edits a route.

Read path, in order, all on the already-active document:

* the Routing configuration gate, then an existing MCP connection and the active
  assembly through ``routing._require_active_assembly`` (no auto-connect),
* ``IAssemblyDoc.IsRouteAssembly`` must read as the native boolean ``True``; a
  ``False``, unreadable or non-boolean value fails closed with ``NOT_ROUTE_ASSEMBLY``
  rather than inspecting a sketch that is not a native Routing path,
* ``IModelDoc2.FeatureByName(feature_name)`` must resolve, ``GetTypeName2`` must be
  ``3DProfileFeature`` (a native 3D sketch) and ``IFeature.IsSuppressed`` must not
  read as ``True``,
* ``IFeature.GetSpecificFeature2`` -> ``ISketch.GetSketchSegments`` must read as a
  sequence. A null or malformed return fails; a legitimate empty 3D sketch is a
  complete zero-segment read.

Per segment (native enumeration order, at most ``_MAX_SEGMENTS``):

* ``ISketchSegment.GetType`` as a raw int (0 line, 1 arc),
* ``ISketchSegment.ConstructionGeometry`` as a native boolean,
* ``ISketchSegment.GetLength`` in metres, reported in mm and required finite >= 0,
* for line/arc only, ``GetStartPoint2``/``GetEndPoint2`` XYZ in metres, reported
  in mm and required finite,
* for arc only, ``ISketchArc.GetRadius`` in metres, reported in mm and required
  finite > 0.

Only line and arc are advertised. Any other segment type keeps its raw native
type and an error, and makes the whole read incomplete: no endpoint is fabricated
and no partial aggregate is produced. ``total_nonconstruction_length_mm`` is the
sum of the non-construction segment lengths and is reported **only** when every
segment read completely; otherwise it is ``null``. Construction segments are kept
in the rows but excluded from the aggregate.

The coordinates are returned in the 3D sketch's own local coordinate system
(``route_3d_sketch_local``). No assembly transform is applied and no component
placement is derived. Native ``IRouteManager`` identifiers are not read and are
never inferred from a segment index; segment ``index`` values are the native
enumeration order of this one read and are not persistent identifiers. Nothing
about connectivity, pipe/fitting counts or wall quantities is reported or
inferred.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .routing import (_coerce_native_bool, _point_integer, _point_number,
                      _require_active_assembly, _routing_allowed)

_ROUTING_DISABLED_MESSAGE = (
    "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
    "and restart the MCP server."
)

# A single bounded read; the limit is checked before any segment is inspected.
_MAX_SEGMENTS = 1000
_MM_PER_METRE = 1000.0

# Native 3D sketch feature type name and the only advertised segment types.
_SKETCH_TYPE_3D = "3DProfileFeature"
_SEGMENT_LINE = 0
_SEGMENT_ARC = 1
_SEGMENT_TYPE_NAMES = {_SEGMENT_LINE: "line", _SEGMENT_ARC: "arc"}

_COORDINATE_SYSTEM = "route_3d_sketch_local"

_SCHEMA = {
    "type": "object",
    "properties": {
        "feature_name": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Exact name of one native 3D sketch feature "
                "(3DProfileFeature) in the active route assembly."
            ),
        },
    },
    "required": ["feature_name"],
    "additionalProperties": False,
}

_NOTES = [
    "Read-only: one exact named 3D sketch's native segments; no selection, "
    "edit mode, rebuild, route edit, configuration activation, add-in load or save.",
    "Coordinates are in the 3D sketch's own local coordinate system "
    "(route_3d_sketch_local); no assembly transform is applied and no component "
    "placement is derived.",
    "Only native line (0) and arc (1) segments are advertised; any other segment "
    "type keeps its raw type and an error and makes the read incomplete.",
    "total_nonconstruction_length_mm sums the non-construction segment lengths and "
    "is reported only when every segment read completely; otherwise it is null. "
    "Construction segments stay in the rows but are excluded from the aggregate.",
    "Segment index is the native enumeration order of this one read only; it is not "
    "a persistent identifier.",
    "Native route manager identifiers are not read and are never inferred from a "
    "segment index.",
    "No connectivity, pipe/fitting count or wall quantity is reported or inferred.",
    "IsRouteAssembly is a document classification, not proof that every segment "
    "in the selected 3D sketch is managed by Routing; managed-route membership "
    "and generated-pipe behaviour are not verified by this reader.",
]


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _scaled_mm(value) -> float:
    """Native metres -> mm; a non-finite or non-numeric value raises."""
    return _point_number(_point_number(value) * _MM_PER_METRE)


def _point_mm(point) -> List[float]:
    """Native sketch point (X/Y/Z in metres) as mm, all three finite."""
    values = []
    for axis in ("X", "Y", "Z"):
        values.append(_scaled_mm(com(point, axis)))
    return values


def _segment_data(segment, index: int) -> Dict[str, Any]:
    """One native sketch segment, fail closed per field.

    ``read_complete`` is True only when the raw type, the construction flag and
    the length were read, the type is an advertised line/arc and its endpoints
    (and, for an arc, its radius) were read. A failed read keeps the field null
    and records an error; nothing is fabricated.
    """
    entry: Dict[str, Any] = {
        "index": index,
        "type_raw": None,
        "type": None,
        "construction": None,
        "length_mm": None,
        "start_mm": None,
        "end_mm": None,
        "radius_mm": None,
        "read_complete": False,
        "errors": [],
    }

    try:
        raw_type = _point_integer(com(segment, "GetType"))
    except Exception as exc:
        entry["errors"].append(f"GetType: {exc}")
        return entry
    entry["type_raw"] = raw_type
    entry["type"] = _SEGMENT_TYPE_NAMES.get(raw_type, "unsupported")

    # ConstructionGeometry and GetLength are ISketchSegment base members, so they
    # are read for every segment regardless of the concrete type.
    try:
        construction = _coerce_native_bool(com(segment, "ConstructionGeometry"))
        if construction is None:
            raise ValueError("ConstructionGeometry returned no boolean value.")
        entry["construction"] = construction
    except Exception as exc:
        entry["errors"].append(f"ConstructionGeometry: {exc}")

    try:
        length = _scaled_mm(com(segment, "GetLength"))
        if length < 0.0:
            raise ValueError("GetLength returned a negative length.")
        entry["length_mm"] = length
    except Exception as exc:
        entry["errors"].append(f"GetLength: {exc}")

    if raw_type in (_SEGMENT_LINE, _SEGMENT_ARC):
        for member, key in (("GetStartPoint2", "start_mm"), ("GetEndPoint2", "end_mm")):
            try:
                entry[key] = _point_mm(com(segment, member))
            except Exception as exc:
                entry[key] = None
                entry["errors"].append(f"{member}: {exc}")
        if raw_type == _SEGMENT_ARC:
            try:
                radius = _scaled_mm(com(segment, "GetRadius"))
                if radius <= 0.0:
                    raise ValueError("GetRadius returned a non-positive radius.")
                entry["radius_mm"] = radius
            except Exception as exc:
                entry["errors"].append(f"GetRadius: {exc}")
    else:
        entry["errors"].append(
            f"Unsupported native sketch segment type {raw_type}; only line (0) "
            f"and arc (1) are advertised."
        )

    entry["read_complete"] = not entry["errors"]
    return entry


def _active_configuration_name(doc) -> Optional[str]:
    """Best-effort active configuration name; never activated, None on failure."""
    manager = com(doc, "ConfigurationManager")
    if manager is None:
        return None
    active = com(manager, "ActiveConfiguration")
    if active is None:
        return None
    name = com(active, "Name")
    return str(name) if name else None


def _document_identity(doc) -> Dict[str, Any]:
    """Best-effort document identity; an unreadable field stays null."""

    def read(name):
        try:
            return com(doc, name) or None
        except Exception:
            return None

    try:
        configuration = _active_configuration_name(doc)
    except Exception:
        configuration = None
    return {
        "title": read("GetTitle"),
        "path": read("GetPathName"),
        "configuration": configuration,
    }


def _failure(sw, message, error, code, **data):
    payload = {"code": code, **data}
    return sw._result(False, message, error, payload)


@tool(
    name="list_routing_path_segments",
    description=(
        "Read one exact named native 3D sketch (3DProfileFeature) in the active "
        "route assembly: per segment raw type, construction flag, native length in mm "
        "and, for line/arc only, endpoint coordinates in the sketch-local frame. "
        "Requires an existing MCP connection and IAssemblyDoc.IsRouteAssembly true; "
        "the non-construction length total is reported only when every segment read "
        "completely. No selection, edit, rebuild, route edit, configuration activation, "
        "add-in load or save; bounded to 1000 segments."
    ),
    schema=_SCHEMA,
    operation_class=OperationClass.READ,
    com=True,
)
def list_routing_path_segments(sw, feature_name) -> Dict:
    """Read one named 3D sketch in a route assembly, including absorbed route sketches."""
    # Gate first: no connection, document or COM access while Routing is off.
    if not _routing_allowed():
        return sw._result(False, _ROUTING_DISABLED_MESSAGE, SwErrors.swInvalidInput,
                          {"code": "ROUTING_DISABLED"})

    # Bound the direct handler argument before any COM access.
    if not isinstance(feature_name, str) or not feature_name.strip():
        return _failure(
            sw,
            "An exact non-empty 3D sketch feature_name is required.",
            SwErrors.swInvalidInput,
            "ROUTING_INPUT_INVALID",
            feature_name=feature_name,
        )

    # Existing connection + active assembly; never auto-connects.
    asm, _, error = _require_active_assembly(sw)
    if error:
        return error

    # The active assembly must itself be a native route assembly.
    try:
        native_route = _coerce_native_bool(com(asm, "IsRouteAssembly"))
    except Exception as exc:
        return _failure(
            sw,
            f"Could not read IAssemblyDoc.IsRouteAssembly: {exc}",
            SwErrors.swUnknownError,
            "ROUTE_ASSEMBLY_UNREADABLE",
            feature_name=feature_name,
        )
    if native_route is None:
        return _failure(
            sw,
            "IAssemblyDoc.IsRouteAssembly returned no boolean value.",
            SwErrors.swUnknownError,
            "ROUTE_ASSEMBLY_UNREADABLE",
            feature_name=feature_name,
        )
    if native_route is not True:
        return _failure(
            sw,
            "The active assembly is not a native route assembly (IsRouteAssembly is "
            "not true); its 3D sketches are not Routing paths.",
            SwErrors.swInvalidInput,
            "NOT_ROUTE_ASSEMBLY",
            feature_name=feature_name,
            native_route_assembly=native_route,
        )

    document = _document_identity(asm)

    # Named sketches may be absorbed by FabricatedRoute, as in the native sample.
    # Do not claim top-level ownership from FeatureByName.
    try:
        feature = com(asm, "FeatureByName", feature_name)
    except Exception as exc:
        return _failure(
            sw,
            f"Could not read feature {feature_name!r}: {exc}",
            SwErrors.swUnknownError,
            "FEATURE_UNREADABLE",
            feature_name=feature_name,
        )
    if feature is None:
        return _failure(
            sw,
            f"Named feature not found: {feature_name}.",
            SwErrors.swFeatureError,
            "FEATURE_NOT_FOUND",
            feature_name=feature_name,
            document=document,
        )

    try:
        kind = str(com(feature, "GetTypeName2"))
    except Exception as exc:
        return _failure(
            sw,
            f"Could not read the feature type of {feature_name!r}: {exc}",
            SwErrors.swUnknownError,
            "FEATURE_TYPE_UNREADABLE",
            feature_name=feature_name,
        )
    if kind != _SKETCH_TYPE_3D:
        return _failure(
            sw,
            f"Feature {feature_name!r} is a {kind}, not a native 3D sketch "
            f"({_SKETCH_TYPE_3D}).",
            SwErrors.swInvalidInput,
            "FEATURE_TYPE_MISMATCH",
            feature_name=feature_name,
            feature_type=kind,
        )

    errors: List[str] = []

    # A suppressed feature is rejected when its state reads; an unreadable state
    # is recorded and fails the read closed rather than being guessed.
    suppressed: Optional[bool] = None
    try:
        suppressed = _coerce_native_bool(com(feature, "IsSuppressed"))
        if suppressed is None:
            errors.append("IsSuppressed returned no boolean value.")
    except Exception as exc:
        errors.append(f"IsSuppressed: {exc}")
    if suppressed is True:
        return _failure(
            sw,
            f"Feature {feature_name!r} is suppressed; its sketch segments were not read.",
            SwErrors.swFeatureError,
            "FEATURE_SUPPRESSED",
            feature_name=feature_name,
            document=document,
        )

    try:
        sketch = com(feature, "GetSpecificFeature2")
    except Exception as exc:
        return _failure(
            sw,
            f"Could not read GetSpecificFeature2 of {feature_name!r}: {exc}",
            SwErrors.swUnknownError,
            "SKETCH_UNREADABLE",
            feature_name=feature_name,
        )
    if sketch is None:
        return _failure(
            sw,
            f"Feature {feature_name!r} exposed no sketch object.",
            SwErrors.swFeatureError,
            "SKETCH_NULL",
            feature_name=feature_name,
        )

    try:
        raw_segments = com(sketch, "GetSketchSegments")
    except Exception as exc:
        return _failure(
            sw,
            f"Could not read GetSketchSegments of {feature_name!r}: {exc}",
            SwErrors.swUnknownError,
            "SEGMENTS_UNREADABLE",
            feature_name=feature_name,
        )
    if raw_segments is None:
        return _failure(
            sw,
            f"GetSketchSegments of {feature_name!r} returned null; no segment was read.",
            SwErrors.swFeatureError,
            "SEGMENTS_NULL",
            feature_name=feature_name,
        )
    if not isinstance(raw_segments, (list, tuple)):
        return _failure(
            sw,
            f"GetSketchSegments of {feature_name!r} did not return a segment sequence.",
            SwErrors.swFeatureError,
            "SEGMENTS_MALFORMED",
            feature_name=feature_name,
        )
    segments = list(raw_segments)

    # The bound is checked before any segment member is read: an over-limit sketch
    # yields no partial rows and no aggregate.
    if len(segments) > _MAX_SEGMENTS:
        return _failure(
            sw,
            f"The 3D sketch has {len(segments)} segments, above the {_MAX_SEGMENTS} "
            f"limit; no segment was read.",
            SwErrors.swInvalidInput,
            "SEGMENT_LIMIT_EXCEEDED",
            feature_name=feature_name,
            segment_count=len(segments),
            limit=_MAX_SEGMENTS,
            document=document,
        )

    rows = [_segment_data(segment, index) for index, segment in enumerate(segments)]
    for row in rows:
        errors.extend(f"segment {row['index']}: {message}" for message in row["errors"])

    complete = not errors and all(row["read_complete"] for row in rows)

    total: Optional[float] = None
    if complete:
        total = 0.0
        for row in rows:
            if row["construction"]:
                continue
            total += row["length_mm"]
        if not _finite(total):
            total = None
            errors.append("The non-construction length total overflowed finite range.")
            complete = False

    construction_count = sum(1 for row in rows if row["construction"] is True)
    unsupported_count = sum(1 for row in rows if row["type"] == "unsupported")

    data = {
        "document": document,
        "coordinate_system": _COORDINATE_SYSTEM,
        "length_unit": "mm",
        "feature": {
            "name": feature_name,
            "type": kind,
            "suppressed": suppressed,
        },
        "segments": rows,
        "count": len(rows),
        "total_nonconstruction_length_mm": total,
        "coverage": {
            "scope": "single_named_3d_sketch",
            "complete": complete,
            "partial": not complete,
            "segment_limit": _MAX_SEGMENTS,
            "truncated": False,
            "construction_segments": construction_count,
            "unsupported_segments": unsupported_count,
            "unresolved": list(errors),
        },
        "route_manager_ids_read": False,
        "managed_route_membership_verified": False,
        "errors": errors,
        "notes": list(_NOTES),
    }

    if complete:
        message = (
            f"Read {len(rows)} segment(s) of {feature_name!r}; "
            f"total_nonconstruction_length_mm={total}."
        )
    else:
        message = (
            f"The segment read of {feature_name!r} is incomplete; see coverage and "
            f"errors. No endpoint or aggregate is fabricated."
        )
    return sw._result(
        complete,
        message,
        SwErrors.swSuccess if complete else SwErrors.swUnknownError,
        data,
    )
