"""Bounded native edit of one existing Routing connection point (CPoint).

``update_routing_connection_point`` edits only the nominal route diameter, the
stub length and/or the native port ID of one exact existing *top-level*
``ConnectionPoint`` feature in the active part's current configuration. It
follows the documented native path
(``Get_and_Set_Connection_Point_Feature_Data_Example``): get the feature
definition with ``IFeature::GetDefinition``, assign the supplied properties
directly on that feature data object, then ``IModelDoc2::ForceRebuild3(false)``.
``AccessSelections``, ``ModifyDefinition`` and ``ReleaseSelectionAccess`` are not
used at all: the native live run showed ``ModifyDefinition`` returning ``False``
while the direct assignment still persisted, so the direct-set plus rebuild path
is the documented one.

Safety boundaries:

* the Routing configuration gate is checked first, before any document, feature
  or definition access,
* a *saved* part additionally requires an approved write policy before any
  feature or definition access; a missing or unapproved policy fails closed,
* the active document must be a part and the named feature must resolve through
  ``IModelDoc2.FeatureByName`` to a ``ConnectionPoint``,
* the original ``IConnectionPointFeatureData`` values are read first as evidence,
* only the supplied ``RouteDiameter``, ``StubLength`` and/or ``PortID`` are set;
  every other CPoint property (location, direction, route type/subtype and the
  unsupplied editable fields) must read back unchanged,
* ``PortID`` is a native BSTR assigned exactly as supplied: at most 128
  characters, no control characters, no leading/trailing whitespace and an empty
  string legitimately clears it -- values are rejected, never silently trimmed or
  normalised,
* a fresh ``GetDefinition`` readback asserts the requested value persisted and
  that those invariant fields did not change.

A failed ``ForceRebuild3`` or a readback/invariant mismatch fails with
partial-mutation evidence and **no automatic rollback**; the document is never
rebuilt twice, saved or reverted. Route type/subtype, direction, location,
feature name and any selection/component option are deliberately not editable
here, and the Routing add-in or a route manager is never loaded or queried.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict

from ..comutil import com, set_com
from ..constants import SwDocumentTypes, SwErrors
from ..core.policy import OperationClass
from ..registry import tool


_ROUTING_DISABLED_MESSAGE = (
    "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
    "and restart the MCP server."
)

# The only editable CPoint properties: two native dimensions in millimetres and
# the native BSTR port identifier. Anything else (route type/subtype, direction,
# location, selection/component) would change routing semantics beyond this
# bounded scope.
_DIAMETER_MM = "diameter_mm"
_STUB_LENGTH_MM = "stub_length_mm"
_PORT_ID = "port_id"
_FIELDS = (_DIAMETER_MM, _STUB_LENGTH_MM, _PORT_ID)

# PortID is a native BSTR (IConnectionPointFeatureData.PortID). It is bounded
# here rather than silently trimmed or normalised.
_MAX_PORT_ID_CHARS = 128

# request key -> IConnectionPointFeatureData member written (diameter/stub in
# native metres; PortID is the exact supplied string, not a length).
_WRITERS = {
    _DIAMETER_MM: "RouteDiameter",
    _STUB_LENGTH_MM: "StubLength",
    _PORT_ID: "PortID",
}

# request key -> key in routing._connection_point_data (dimensions in native
# millimetres; port ID as the native string).
_READBACK = {
    _DIAMETER_MM: "nominal_diameter_mm",
    _STUB_LENGTH_MM: "stub_length_mm",
    _PORT_ID: "port_id",
}

# Unrelated CPoint evidence that must survive an edit unchanged. port_id is
# intentionally absent: it is handled through _FIELDS, so it is checked as an
# invariant only while it is not one of the supplied editable fields.
_INVARIANTS = ("position_mm", "direction", "route_type_raw", "route_subtype_raw")

_MM_PER_METRE = 1000.0

_SCHEMA = {
    "type": "object",
    "properties": {
        "feature_name": {
            "type": "string",
            "description": "Exact name of an existing top-level ConnectionPoint feature.",
        },
        "diameter_mm": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Nominal route diameter in mm (> 0).",
        },
        "stub_length_mm": {
            "type": "number",
            "minimum": 0,
            "description": "Stub length in mm (>= 0).",
        },
        _PORT_ID: {
            "type": "string",
            "maxLength": _MAX_PORT_ID_CHARS,
            "description": (
                "Native PortID string, at most 128 characters. An empty string clears "
                "it. Control characters and leading/trailing whitespace are rejected "
                "rather than trimmed or normalised; Unicode is accepted."
            ),
        },
    },
    "required": ["feature_name"],
    "additionalProperties": False,
    "anyOf": [{"required": [_DIAMETER_MM]}, {"required": [_STUB_LENGTH_MM]},
              {"required": [_PORT_ID]}],
}


def _routing():
    """routing helpers, imported lazily so this module stays independent."""
    from . import routing

    return routing


def _finite(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number.")
    return float(value)


def _port_id_value(port_id: object) -> str:
    """Bound the native PortID string; never silently trim or normalise."""
    if not isinstance(port_id, str):
        raise ValueError(f"{_PORT_ID} must be a string.")
    if len(port_id) > _MAX_PORT_ID_CHARS:
        raise ValueError(f"{_PORT_ID} must be at most {_MAX_PORT_ID_CHARS} characters.")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in port_id):
        raise ValueError(f"{_PORT_ID} must not contain control characters.")
    if port_id != port_id.strip():
        raise ValueError(
            f"{_PORT_ID} must not have leading or trailing whitespace; it is stored "
            "exactly as supplied."
        )
    return port_id


def _requested_updates(diameter_mm, stub_length_mm, port_id=None) -> Dict[str, object]:
    """Validate direct handler arguments; at least one bounded value is required."""
    updates: Dict[str, object] = {}
    if diameter_mm is not None:
        diameter = _finite(diameter_mm, _DIAMETER_MM)
        if diameter <= 0.0:
            raise ValueError(f"{_DIAMETER_MM} must be greater than 0.")
        updates[_DIAMETER_MM] = diameter
    if stub_length_mm is not None:
        stub = _finite(stub_length_mm, _STUB_LENGTH_MM)
        if stub < 0.0:
            raise ValueError(f"{_STUB_LENGTH_MM} must be at least 0.")
        updates[_STUB_LENGTH_MM] = stub
    if port_id is not None:
        updates[_PORT_ID] = _port_id_value(port_id)
    if not updates:
        raise ValueError("Supply diameter_mm, stub_length_mm, port_id or a combination.")
    return updates


def _requested(updates: Dict[str, object]) -> Dict[str, object]:
    return {key: updates[key] for key in _FIELDS if key in updates}


def _native_value(key: str, value: object) -> object:
    """Native value to assign: mm dimensions become metres; PortID stays a string."""
    if key == _PORT_ID:
        return value
    return float(value) / _MM_PER_METRE


def _same_value(left, right) -> bool:
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    return left == right


def _confirmed(key: str, value, actual) -> bool:
    """Whether a fresh readback confirmed one requested field."""
    if key == _PORT_ID:
        # Exact match: the native BSTR is compared verbatim, never normalised.
        return isinstance(actual, str) and actual == value
    return (not isinstance(actual, bool) and isinstance(actual, (int, float))
            and math.isfinite(actual)
            and math.isclose(float(actual), value, rel_tol=1e-9, abs_tol=1e-9))


def _mismatches(updates, after) -> list:
    """Requested values that a fresh GetDefinition readback did not confirm."""
    if not isinstance(after, dict):
        return [{"field": key, "requested": value, "readback": None}
                for key, value in _requested(updates).items()]
    found = []
    for key, value in _requested(updates).items():
        actual = after.get(_READBACK[key])
        if not _confirmed(key, value, actual):
            found.append({"field": key, "requested": value, "readback": actual})
    return found


def _invariant_changes(before, after, updates) -> list:
    """Unrelated CPoint fields (and the unsupplied editable fields) that moved."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    changed = []
    for field in _INVARIANTS:
        old, new = before.get(field), after.get(field)
        if not _same_value(old, new):
            changed.append({"field": field, "before": old, "after": new})
    for key in _FIELDS:
        if key in updates:
            continue
        field = _READBACK[key]
        old, new = before.get(field), after.get(field)
        if not _same_value(old, new):
            changed.append({"field": field, "before": old, "after": new})
    return changed


def _evidence(code, feature_name, updates, *, before=None, after=None, rebuild=None,
              mismatches=(), invariant_changes=(), written=(), document_may_be_modified=False) -> Dict:
    return {
        "code": code,
        "feature_name": feature_name,
        "requested": _requested(updates),
        "properties_written": list(written),
        "before": before,
        "after": after,
        "rebuild": rebuild,
        "mismatches": list(mismatches),
        "invariant_changes": list(invariant_changes),
        "document_may_be_modified": bool(document_may_be_modified),
        "automatic_rollback": False,
        "saved": False,
        "notes": [
            "Only the supplied diameter_mm/stub_length_mm/port_id are set on the "
            "existing ConnectionPoint feature definition; other CPoint properties "
            "are preserved.",
            "No AccessSelections/ModifyDefinition, no second rebuild, no save and no "
            "automatic rollback are performed.",
        ],
    }


def _checked_invariants(updates) -> list:
    fields = list(_INVARIANTS)
    fields.extend(_READBACK[key] for key in _FIELDS if key not in updates)
    return fields


@tool(
    name="update_routing_connection_point",
    description=(
        "Edit the nominal route diameter, stub length and/or native port ID of one "
        "exact existing ConnectionPoint feature in the active part's current "
        "configuration. Sets the supplied properties directly on its feature "
        "definition, ForceRebuild3(false) and asserts a fresh GetDefinition readback: "
        "the requested value persisted and every other CPoint property is unchanged. "
        "An empty port_id clears it; port_id is bounded to 128 characters and rejects "
        "control characters and surrounding whitespace rather than normalising. Saved "
        "parts require an approved write policy. A failed rebuild or mismatch fails "
        "with partial-mutation evidence and no automatic rollback. Does not use "
        "AccessSelections/ModifyDefinition, create features, load Routing or save."
    ),
    schema=_SCHEMA,
    operation_class=OperationClass.MUTATE,
)
def update_routing_connection_point(sw, feature_name=None, diameter_mm=None,
                                    stub_length_mm=None, port_id=None) -> Dict:
    """Direct-set one existing CPoint's RouteDiameter/StubLength/PortID; rebuild and read back."""
    # Gate first: no COM, no document and no feature access while Routing is off.
    if not _routing()._routing_allowed():
        return sw._result(False, _ROUTING_DISABLED_MESSAGE, SwErrors.swInvalidInput,
                          {"code": "ROUTING_DISABLED"})

    # Bound the direct handler arguments before any COM access, so a direct call
    # cannot reach the definition with non-finite, out-of-range or unbounded values.
    try:
        if not isinstance(feature_name, str) or not feature_name.strip():
            raise ValueError("An exact existing ConnectionPoint feature_name is required.")
        updates = _requested_updates(diameter_mm, stub_length_mm, port_id)
    except ValueError as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          {"code": "ROUTING_INPUT_INVALID", "feature_name": feature_name})

    routing = _routing()
    doc, _, error = routing._require_active_document_type(sw, SwDocumentTypes.swDocPART)
    if error:
        return error

    changed = False
    written = []
    result = None
    before = None

    try:
        title = com(doc, "GetTitle")
        path = com(doc, "GetPathName")

        # Saved parts require an approved write policy before any feature or
        # definition access; a missing or unapproved policy fails closed, exactly
        # as configure_routing_component does for library metadata.
        if path:
            policy = getattr(sw, "_path_policy", None)
            if policy is None:
                return sw._result(
                    False,
                    "Saved parts require an explicit approved write policy before the "
                    "connection point can be edited.",
                    SwErrors.swInvalidInput,
                    {"code": "ROUTING_WRITE_DENIED", "feature_name": feature_name,
                     "document_may_be_modified": False})
            try:
                policy.require_write(Path(path), OperationClass.MUTATE)
            except Exception as exc:
                return sw._result(
                    False,
                    f"Connection point write denied before feature access: {exc}",
                    SwErrors.swInvalidInput,
                    {"code": "ROUTING_WRITE_DENIED", "feature_name": feature_name,
                     "document_may_be_modified": False})

        feature = com(doc, "FeatureByName", feature_name)
        if feature is None:
            return sw._result(
                False, f"Feature not found: {feature_name}", SwErrors.swFeatureError,
                _evidence("ROUTING_CONNECTION_POINT_NOT_FOUND", feature_name, updates))
        kind = str(com(feature, "GetTypeName2"))
        if kind != "ConnectionPoint":
            return sw._result(
                False, f"Feature '{feature_name}' is a {kind}, not a ConnectionPoint.",
                SwErrors.swFeatureError,
                _evidence("ROUTING_CONNECTION_POINT_TYPE_MISMATCH", feature_name, updates,
                          before={"feature_type": kind}))

        before = routing._connection_point_data(feature, feature_name)
        if not before.get("read_complete"):
            return sw._result(
                False, f"ConnectionPoint '{feature_name}' definition could not be fully read.",
                SwErrors.swFeatureError,
                _evidence("ROUTING_CONNECTION_POINT_UNREADABLE", feature_name, updates, before=before))

        definition = com(feature, "GetDefinition")
        if definition is None:
            raise ValueError("ConnectionPoint GetDefinition returned null.")

        # Documented native path: assign the properties directly on the feature
        # data object. ModifyDefinition is unrelated and returns False even though
        # the assignment persists, so it is never used.
        changed = True
        for key in _FIELDS:
            if key in updates:
                set_com(definition, _WRITERS[key], _native_value(key, updates[key]))
                written.append(key)

        rebuild = bool(com(doc, "ForceRebuild3", False))
        after = routing._connection_point_data(feature, feature_name)
        mismatches = _mismatches(updates, after)
        invariant_changes = _invariant_changes(before, after, updates)

        if not rebuild:
            result = sw._result(
                False, "Connection point was set but ForceRebuild3(false) failed; no rollback.",
                SwErrors.swFeatureError,
                _evidence("ROUTING_REBUILD_FAILED", feature_name, updates, before=before, after=after,
                          rebuild=rebuild, mismatches=mismatches, invariant_changes=invariant_changes,
                          written=written, document_may_be_modified=True))
        elif mismatches or invariant_changes or not after.get("read_complete"):
            result = sw._result(
                False,
                "Connection point was set but readback did not confirm the request; no automatic rollback.",
                SwErrors.swFeatureError,
                _evidence("ROUTING_VERIFICATION_FAILED", feature_name, updates, before=before, after=after,
                          rebuild=rebuild, mismatches=mismatches, invariant_changes=invariant_changes,
                          written=written, document_may_be_modified=True))
        else:
            result = sw._result(
                True, f"ConnectionPoint '{feature_name}' updated, rebuilt and read back; not saved.",
                SwErrors.swSuccess,
                {
                    "document": {"title": title, "path": path or None},
                    "coordinate_system": "active_part_local",
                    "length_unit": "mm",
                    "scope": "active_configuration",
                    "feature_name": feature_name,
                    "feature_type": "ConnectionPoint",
                    "requested": _requested(updates),
                    "properties_written": written,
                    "before": before,
                    "after": after,
                    "rebuild": rebuild,
                    "invariants_checked": _checked_invariants(updates),
                    "invariants_unchanged": True,
                    "document_may_be_modified": True,
                    "automatic_rollback": False,
                    "saved": False,
                    "notes": [
                        "Only the supplied diameter_mm/stub_length_mm/port_id were set "
                        "on the existing feature definition; every other CPoint "
                        "property was verified unchanged.",
                        "Readback used a fresh GetDefinition after ForceRebuild3(false); no "
                        "AccessSelections/ModifyDefinition, save or rollback was performed.",
                        "port_id was assigned as the exact supplied BSTR and is verified "
                        "by an exact readback match.",
                        "The Routing add-in and route manager were not loaded or queried.",
                    ],
                })
    except Exception as exc:
        result = sw._result(
            False, f"Connection point update failed: {exc}", SwErrors.swUnknownError,
            _evidence("ROUTING_UPDATE_FAILED", feature_name, updates, before=before,
                      written=written, document_may_be_modified=changed))
    return result
