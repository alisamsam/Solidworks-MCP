"""Bounded native edit of the active part's Routing library component metadata.

``configure_routing_component`` sets the description and/or the CPoint inclusion
policy of the *active part* through the same
``IModelDocExtension.GetRoutingComponentManager`` accessor the read tool RT9
uses (``routing._routing_component_manager``). The two editable members are the
argument-taking methods on ``IRoutingComponentManager``:

* ``SetRoutingComponentDescription(StringID)`` -- a BSTR; an empty string is a
  legitimate native value that clears the description,
* ``SetCPointConfiguration(type)`` -- an I4 enumeration of ``swCPointConfig_e``.

Both are invoked explicitly with ``GetIDsOfNames`` + ``DISPATCH_METHOD`` on the
raw ``_oleobj_`` (the installed type library declares both with ``INVOKE_FUNC``);
no pywin32 property fallback or new accessor path is used. The zero-argument
getters (``GetComponentType``, ``GetComponentRouteType``,
``GetCPointConfiguration``, ``GetRoutingComponentDescription``) are read through
the existing ``routing._metadata_method``.

Boundaries:

* the Routing configuration gate is checked first, before any document, manager
  or COM access,
* handler arguments are validated before COM, so a direct call cannot reach a
  setter with a non-string description or an unknown policy,
* only the requested members are written; the other policy/description member
  and the native component type/route type must read back unchanged,
* a *fresh* manager object is obtained after the set and every field is re-read
  through it; the requested value must persist and the untouched fields must not
  move.

The setter return is void, so persistence is proven only by the fresh readback.
A null or unreadable manager, a failed read, or a raising setter fails closed
with partial-mutation evidence and **no automatic rollback**. The document is
never rebuilt, saved, reverted, or reconfigured; no add-in is loaded, no route
manager is queried, no selection is touched and no folder is changed. Native
persistence of the setters is confirmed by the caller on its own library
component before this tool is advertised.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from ..comutil import com
from ..constants import SwDocumentTypes, SwErrors
from ..core.policy import OperationClass
from ..registry import tool


_ROUTING_DISABLED_MESSAGE = (
    "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
    "and restart the MCP server."
)

# swCPointConfig_e, verified against the installed SWRoutingLib.tlb:
#   swCPointConfig_AddAllCPoint    = 1
#   swCPointConfig_DoNotAddCPoint  = 2
#   swCPointConfig_SelectCPoints   = 3
_POLICY_TO_NATIVE = {"add_all": 1, "do_not_add": 2, "select": 3}

# Argument-taking setters invoked explicitly with DISPATCH_METHOD.
_SET_DESCRIPTION = "SetRoutingComponentDescription"
_SET_CPOINT = "SetCPointConfiguration"

# Zero-argument getters read through routing._metadata_method for the
# before/after invariant snapshot.
_GETTERS: Tuple[Tuple[str, str, str], ...] = (
    ("GetComponentType", "component_type_raw", "int"),
    ("GetComponentRouteType", "component_route_type_raw", "int"),
    ("GetCPointConfiguration", "cpoint_configuration_raw", "int"),
    ("GetRoutingComponentDescription", "description", "str"),
)

_DESCRIPTION = "description"
_CPOINT_POLICY = "cpoint_policy"
_FIELDS = (_DESCRIPTION, _CPOINT_POLICY)

_SCHEMA = {
    "type": "object",
    "properties": {
        _DESCRIPTION: {
            "type": "string",
            "description": (
                "Routing component description; an empty string clears it."
            ),
        },
        _CPOINT_POLICY: {
            "type": "string",
            "enum": ["add_all", "do_not_add", "select"],
            "description": (
                "CPoint inclusion policy: add_all, do_not_add or select."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
    "anyOf": [{"required": [_DESCRIPTION]}, {"required": [_CPOINT_POLICY]}],
}


def _routing():
    """routing helpers, imported lazily so this module stays independent."""
    from . import routing

    return routing


def _setter_method(manager, name, *args):
    """Invoke an argument-taking manager method with explicit DISPATCH_METHOD.

    The installed type library declares ``SetRoutingComponentDescription`` and
    ``SetCPointConfiguration`` as ``INVOKE_FUNC``; the raw dispatch call keeps the
    method (not property) semantics and passes the single argument explicitly.
    """
    import pythoncom

    ole = manager._oleobj_
    return ole.Invoke(ole.GetIDsOfNames(name), 0, pythoncom.DISPATCH_METHOD, True, *args)


def _requested_updates(description, cpoint_policy) -> Dict[str, Any]:
    """Validate direct handler arguments; at least one bounded field is required."""
    requested: Dict[str, Any] = {}
    if description is not None:
        if not isinstance(description, str):
            raise ValueError(
                "description must be a string; an empty string clears it."
            )
        requested[_DESCRIPTION] = description
    if cpoint_policy is not None:
        if not isinstance(cpoint_policy, str) or cpoint_policy not in _POLICY_TO_NATIVE:
            raise ValueError(
                "cpoint_policy must be one of add_all, do_not_add or select."
            )
        requested[_CPOINT_POLICY] = cpoint_policy
    if not requested:
        raise ValueError("Supply description, cpoint_policy or both.")
    return requested


def _requested(requested: Dict[str, Any]) -> Dict[str, Any]:
    return {key: requested[key] for key in _FIELDS if key in requested}


def _native_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer native enum value.")
    return value


def _native_str(value):
    if not isinstance(value, str):
        raise ValueError("Expected a native string.")
    return value


_CONVERTERS = {"int": _native_int, "str": _native_str}


def _read_snapshot(manager) -> Tuple[Dict[str, Any], List[str]]:
    """Read the four native metadata fields; per-field failures are collected."""
    routing = _routing()
    snapshot: Dict[str, Any] = {key: None for _, key, _ in _GETTERS}
    errors: List[str] = []
    for member, key, kind in _GETTERS:
        try:
            snapshot[key] = _CONVERTERS[kind](routing._metadata_method(manager, member))
        except Exception as exc:
            errors.append(f"{member}: {exc}")
    return snapshot, errors


def _native_policy(requested: Dict[str, Any]) -> Optional[int]:
    if _CPOINT_POLICY in requested:
        return _POLICY_TO_NATIVE[requested[_CPOINT_POLICY]]
    return None


def _verification(requested, before, after):
    """Requested fields that did not persist and untouched fields that moved."""
    mismatches: List[Dict[str, Any]] = []
    invariant_changes: List[Dict[str, Any]] = []

    if _DESCRIPTION in requested:
        wanted = requested[_DESCRIPTION]
        observed = after["description"]
        # SW2025 native getter normalises ASCII descriptions to lower case.
        # Preserve both values in the response, and do not generalise to Unicode.
        matches = observed == wanted or (wanted.isascii() and observed == wanted.lower())
        if not matches:
            mismatches.append({
                "field": _DESCRIPTION,
                "requested": requested[_DESCRIPTION],
                "readback": after["description"],
            })
    else:
        if before["description"] != after["description"]:
            invariant_changes.append({
                "field": "description",
                "before": before["description"],
                "after": after["description"],
            })

    if _CPOINT_POLICY in requested:
        want = _POLICY_TO_NATIVE[requested[_CPOINT_POLICY]]
        if after["cpoint_configuration_raw"] != want:
            mismatches.append({
                "field": _CPOINT_POLICY,
                "requested": requested[_CPOINT_POLICY],
                "requested_native": want,
                "readback": after["cpoint_configuration_raw"],
            })
    else:
        if before["cpoint_configuration_raw"] != after["cpoint_configuration_raw"]:
            invariant_changes.append({
                "field": "cpoint_configuration_raw",
                "before": before["cpoint_configuration_raw"],
                "after": after["cpoint_configuration_raw"],
            })

    for key in ("component_type_raw", "component_route_type_raw"):
        if before[key] != after[key]:
            invariant_changes.append({
                "field": key,
                "before": before[key],
                "after": after[key],
            })

    return mismatches, invariant_changes


def _evidence(code, requested, *, document=None, manager_status=None,
              fresh_manager=None, before=None, after=None, written=(),
              mismatches=(), invariant_changes=(), document_may_be_modified=False,
              errors=()) -> Dict[str, Any]:
    return {
        "code": code,
        "document": document,
        "requested": _requested(requested),
        "cpoint_policy_native": _native_policy(requested),
        "properties_written": list(written),
        "manager_status": manager_status,
        "fresh_manager": fresh_manager,
        "before": before,
        "after": after,
        "description_normalization": ("native_ascii_lowercase" if after and _DESCRIPTION in requested
            and after.get("description") != requested[_DESCRIPTION]
            and requested[_DESCRIPTION].isascii()
            and after.get("description") == requested[_DESCRIPTION].lower() else None),
        "mismatches": list(mismatches),
        "invariant_changes": list(invariant_changes),
        "document_may_be_modified": bool(document_may_be_modified),
        "automatic_rollback": False,
        "saved": False,
        "errors": list(errors),
        "notes": [
            "Only the supplied description/cpoint_policy are written through "
            "IRoutingComponentManager; the component type, route type and the "
            "untouched member are read back and must be unchanged.",
            "Setters are invoked with explicit GetIDsOfNames + DISPATCH_METHOD and "
            "verified by a fresh manager readback; no rebuild, save, add-in load, "
            "route manager, selection or folder change, and no automatic rollback.",
        ],
    }


@tool(
    name="configure_routing_component",
    description=(
        "Set the active part's native Routing library metadata: the component "
        "description and/or the CPoint inclusion policy (add_all, do_not_add, "
        "select). Writes only the requested members through "
        "IRoutingComponentManager (explicit DISPATCH_METHOD), then re-reads a fresh "
        "manager to confirm the requested value persisted and the component type, "
        "route type and untouched member are unchanged. Fails closed with partial "
        "mutation evidence and no rollback. Does not rebuild, save, load Routing, "
         "query a route manager or change configuration/folders. Saved parts require an approved write policy."
    ),
    schema=_SCHEMA,
    operation_class=OperationClass.MUTATE,
)
def configure_routing_component(sw, description=None, cpoint_policy=None) -> Dict:
    """Write requested Routing library metadata and verify by fresh readback."""
    # Gate first: no COM, no document and no manager access while Routing is off.
    if not _routing()._routing_allowed():
        return sw._result(
            False, _ROUTING_DISABLED_MESSAGE, SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        )

    # Bound the direct handler arguments before any COM access.
    try:
        requested = _requested_updates(description, cpoint_policy)
    except ValueError as exc:
        return sw._result(
            False, str(exc), SwErrors.swInvalidInput,
            {"code": "ROUTING_INPUT_INVALID",
             "description": description, "cpoint_policy": cpoint_policy},
        )

    routing = _routing()
    doc, _, error = routing._require_active_document_type(sw, SwDocumentTypes.swDocPART)
    if error:
        return error

    try:
        document = {"title": com(doc, "GetTitle"), "path": com(doc, "GetPathName") or None}
        if document["path"]:
            policy = getattr(sw, "_path_policy", None)
            if policy is None:
                raise PermissionError("Saved library parts require an explicit approved write policy.")
            policy.require_write(Path(document["path"]), OperationClass.MUTATE)
    except Exception as exc:
        return sw._result(False, f"Library write denied before metadata access: {exc}",
                          SwErrors.swInvalidInput, {"code": "ROUTING_LIBRARY_WRITE_DENIED",
                                                    "document_may_be_modified": False})

    # Before snapshot from the current manager; fail closed if it is missing.
    try:
        manager = routing._routing_component_manager(doc)
    except Exception as exc:
        return sw._result(
            False,
            f"The Routing component manager accessor failed: {exc}",
            SwErrors.swUnknownError,
            _evidence("ROUTING_COMPONENT_MANAGER_UNAVAILABLE", requested,
                      document=document, manager_status="unavailable"),
        )
    if manager is None:
        return sw._result(
            False,
            "Native Routing component manager returned null; nothing was written.",
            SwErrors.swFeatureError,
            _evidence("ROUTING_COMPONENT_MANAGER_UNAVAILABLE", requested,
                      document=document, manager_status="null"),
        )

    before, read_errors = _read_snapshot(manager)
    if read_errors:
        return sw._result(
            False,
            "Native Routing metadata could not be fully read; nothing was written.",
            SwErrors.swUnknownError,
            _evidence("ROUTING_METADATA_UNREADABLE", requested, document=document,
                      manager_status="object", before=before, errors=read_errors),
        )

    written: List[str] = []
    try:
        if _DESCRIPTION in requested:
            _setter_method(manager, _SET_DESCRIPTION, requested[_DESCRIPTION])
            written.append(_DESCRIPTION)
        if _CPOINT_POLICY in requested:
            _setter_method(manager, _SET_CPOINT, _POLICY_TO_NATIVE[requested[_CPOINT_POLICY]])
            written.append(_CPOINT_POLICY)
    except Exception as exc:
        return sw._result(
            False,
            f"Routing component metadata write failed: {exc}; no automatic rollback.",
            SwErrors.swFeatureError,
            _evidence("ROUTING_CONFIGURATION_FAILED", requested, document=document,
                      manager_status="object", before=before, written=written,
                      document_may_be_modified=True, errors=[str(exc)]),
        )

    # Fresh manager for the readback; a new object must expose the persisted values.
    fresh = None
    try:
        fresh = routing._routing_component_manager(doc)
    except Exception as exc:
        return sw._result(
            False,
            f"Fresh Routing component manager could not be obtained: {exc}; no rollback.",
            SwErrors.swUnknownError,
            _evidence("ROUTING_VERIFICATION_FAILED", requested, document=document,
                      manager_status="object", fresh_manager=False, before=before,
                      written=written, document_may_be_modified=True, errors=[str(exc)]),
        )
    if fresh is None:
        return sw._result(
            False,
            "Fresh Routing component manager returned null; verification impossible.",
            SwErrors.swFeatureError,
            _evidence("ROUTING_VERIFICATION_FAILED", requested, document=document,
                      manager_status="object", fresh_manager=False, before=before,
                      written=written, document_may_be_modified=True),
        )

    after, after_errors = _read_snapshot(fresh)
    if after_errors:
        return sw._result(
            False,
            "Routing component metadata could not be re-read after the write; no rollback.",
            SwErrors.swUnknownError,
            _evidence("ROUTING_VERIFICATION_FAILED", requested, document=document,
                      manager_status="object", fresh_manager=True, before=before,
                      after=after, written=written, document_may_be_modified=True,
                      errors=after_errors),
        )

    mismatches, invariant_changes = _verification(requested, before, after)
    if mismatches or invariant_changes:
        return sw._result(
            False,
            "Routing component metadata write did not verify; no automatic rollback.",
            SwErrors.swFeatureError,
            _evidence("ROUTING_VERIFICATION_FAILED", requested, document=document,
                      manager_status="object", fresh_manager=True, before=before,
                      after=after, written=written, mismatches=mismatches,
                      invariant_changes=invariant_changes, document_may_be_modified=True),
        )

    return sw._result(
        True,
        "Routing component metadata configured, verified by a fresh manager and not saved.",
        SwErrors.swSuccess,
        {
            "code": "ROUTING_CONFIGURED",
            "document": document,
            "requested": _requested(requested),
            "cpoint_policy_native": _native_policy(requested),
            "properties_written": written,
            "manager_status": "object",
            "fresh_manager": True,
            "before": before,
            "after": after,
            "description_normalization": ("native_ascii_lowercase" if _DESCRIPTION in requested
                and after["description"] != requested[_DESCRIPTION] else None),
            "mismatches": [],
            "invariant_changes": [],
            "invariances_checked": (
                ["component_type_raw", "component_route_type_raw"]
                + ([_DESCRIPTION] if _DESCRIPTION not in requested else [])
                + (["cpoint_configuration_raw"] if _CPOINT_POLICY not in requested else [])
            ),
            "document_may_be_modified": True,
            "automatic_rollback": False,
            "saved": False,
            "notes": [
                "Only the requested members were written through "
                "IRoutingComponentManager; the fresh readback confirmed the requested "
                "value persisted and every untouched field was unchanged.",
                "Raw enums belong to swCPointConfig_e (add_all=1, do_not_add=2, "
                "select=3) and are distinct from CPoint RouteType.",
                "SW2025 may lower-case ASCII descriptions; requested and stored values are reported separately.",
                "No rebuild, save, add-in load, route manager, selection, "
                "configuration or folder change was performed.",
            ],
        },
    )
