"""Read-only Routing file-location settings and save/naming toggles (RS1).

``get_routing_file_locations`` reads the *configured* Routing file locations and
four Routing save/naming toggles from the active SolidWorks installation through
``ISldWorks.GetRoutingSettings`` -> ``IRoutingSettings``:

* ``GetRoutingUserPreferenceStringValue(int UserPreference, bool UseDefaultVal)``
  for the four members of ``swUserPreferenceRoutingFileLocations_e`` (installed
  ``SWRoutingLib`` type library):

  =====  ====================================================
  id     enum member
  =====  ====================================================
  1      ``swRoutingLibraryPath``
  2      ``swFileLocationsRoutingAssemblyTemplate``
  3      ``swFileLocationsRoutingStandardTubes``
  4      ``swFileLocationsRoutingPipeTubeCoveringLibrary``
  =====  ====================================================

* ``GetRoutingUserPreferenceToggle(int UserPreference)`` for four Routing
  save/naming toggles: id 2 ``swSaveRouteAssemblyExternally``, id 3
  ``swSaveRoutePartsExternally``, id 4 ``swUseAutomaticNamingForRouteParts`` and
  id 13 ``swAlwaysUseDefaultDocumentTemplate``.

The Routing configuration gate is checked first, before any application or COM
access. An existing MCP connection is required, but no active document is: this
tool reads application-level Routing settings, so a part, assembly, drawing or no
document at all are all acceptable and ``ActiveDoc`` is never read.

Both ``GetRoutingSettings`` and the parameter-taking getters are invoked
explicitly with ``GetIDsOfNames`` + ``DISPATCH_METHOD`` on the raw ``_oleobj_``.
The raw ``GetRoutingSettings`` return is a ``pythoncom.PyIDispatch`` without an
``_oleobj_``, so it is wrapped with ``win32com.client.Dispatch`` (the same pattern
``routing._routing_component_manager`` uses) before any getter is invoked.

``use_default`` is an explicit request selector, not a fallback: ``False`` reads
the configured values and ``True`` reads the native defaults, and the chosen value
is passed straight to the native ``UseDefaultVal`` parameter. A missing configured
value is returned as an empty string, never silently replaced by the default.

Boundaries:

* only ``swUserPreferenceRoutingFileLocations_e`` ids 1-4 and the four routing
  toggle ids are read; Electrical ids 5+ and the core
  ``ISldWorks.GetUserPreferenceStringValue`` (37, "electrical xml") are never used,
* no filesystem access, existence check, directory scan, CAD selection, add-in
  load, configuration/global set, document Load or Save,
* a null or unreadable settings object, and any per-field failure (raised or an
  invalid native return), fail closed: the field stays ``None``, the error is
  recorded and ``complete`` becomes ``False``; the remaining fields are still read
  and reported, and no path is ever invented,
* the returned object is a settings view only. It proves nothing about license,
  add-in loaded state or library readiness, and it does not control where route
  assemblies or parts are saved.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .routing import _routing_allowed


_ROUTING_DISABLED_MESSAGE = (
    "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
    "and restart the MCP server."
)

# Explicit Dispatch member names. The getters take parameters, so they are invoked
# with GetIDsOfNames + DISPATCH_METHOD and never through a property-get fallback.
_GET_ROUTING_SETTINGS = "GetRoutingSettings"
_STRING_GETTER = "GetRoutingUserPreferenceStringValue"
_TOGGLE_GETTER = "GetRoutingUserPreferenceToggle"

# swUserPreferenceRoutingFileLocations_e, confirmed against the installed
# SWRoutingLib type library. Ids 1-4 are the Routing file locations; Electrical
# and later members (id 5+) are deliberately excluded.
_STRING_ENUM = "swUserPreferenceRoutingFileLocations_e"
_STRING_FIELDS: Tuple[Tuple[int, str], ...] = (
    (1, "swRoutingLibraryPath"),
    (2, "swFileLocationsRoutingAssemblyTemplate"),
    (3, "swFileLocationsRoutingStandardTubes"),
    (4, "swFileLocationsRoutingPipeTubeCoveringLibrary"),
)

# Routing save/naming toggles read through GetRoutingUserPreferenceToggle.
_TOGGLE_FIELDS: Tuple[Tuple[int, str], ...] = (
    (2, "swSaveRouteAssemblyExternally"),
    (3, "swSaveRoutePartsExternally"),
    (4, "swUseAutomaticNamingForRouteParts"),
    (13, "swAlwaysUseDefaultDocumentTemplate"),
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "use_default": {
            "type": "boolean",
            "description": (
                "False reads the configured file-location strings; True reads the "
                "native defaults. Explicit request selector, never a fallback."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}

_NOTES = [
    "Read-only native Routing file-location strings and save/naming toggles; no "
    "file or folder is opened, created, scanned or checked for existence.",
    "Only swUserPreferenceRoutingFileLocations_e ids 1-4 and the Routing toggle "
    "ids are read; Electrical ids 5+ and the core GetUserPreferenceStringValue "
    "are never used.",
    "An empty string is reported as the raw configured-or-default value; it is "
    "never replaced by an invented path or by the other use_default variant.",
    "The Routing settings view is not a licence or add-in readiness check and does "
    "not control where route assemblies or parts are saved.",
]


def _raw_invoke(obj, name, *args):
    """Invoke a member with explicit ``DISPATCH_METHOD`` on the raw dispatch.

    The installed type library declares ``GetRoutingSettings`` and both parameter
    getters with ``INVOKE_FUNC``; the raw call keeps method (not property)
    semantics and passes the declared parameters explicitly.
    """
    import pythoncom

    ole = obj._oleobj_
    return ole.Invoke(ole.GetIDsOfNames(name), 0, pythoncom.DISPATCH_METHOD, True, *args)


def _wrap_settings(raw):
    """Wrap the raw ``PyIDispatch`` return so it exposes ``_oleobj_`` for getters."""
    import win32com.client

    return win32com.client.Dispatch(raw)


def _routing_settings_object(app):
    """Return the wrapped ``IRoutingSettings`` object, or ``None`` when native null."""
    raw = _raw_invoke(app, _GET_ROUTING_SETTINGS)
    return None if raw is None else _wrap_settings(raw)


def _native_str(value) -> str:
    """A native string, including an empty one; anything else is a failed read."""
    if not isinstance(value, str):
        raise ValueError("Expected a native string value.")
    return value


def _native_toggle(value) -> bool:
    """A native boolean; an int 0/1 is coerced, any other return is a failed read."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError("Expected a native boolean value.")


def _string_entry(field_id, name, use_default, value) -> Dict[str, Any]:
    return {"id": field_id, "name": name, "use_default": use_default, "value": value}


def _toggle_entry(field_id, name, value) -> Dict[str, Any]:
    return {"id": field_id, "name": name, "value": value}


def _data(settings_status, use_default, file_locations, toggles, complete,
          errors) -> Dict[str, Any]:
    return {
        "configuration": {"routing_enabled": True},
        "settings_status": settings_status,
        "use_default": use_default,
        "string_enum": _STRING_ENUM,
        "file_locations": file_locations,
        "toggles": toggles,
        "complete": complete,
        "errors": list(errors),
        "notes": list(_NOTES),
    }


@tool(
    name="get_routing_file_locations",
    description=(
        "Read the Routing file locations (swUserPreferenceRoutingFileLocations_e "
        "ids 1-4: library path, routing assembly template, standard tubes, pipe/tube "
        "covering library) and four Routing save/naming toggles from the active "
        "SolidWorks install via IRoutingSettings. use_default selects configured "
        "(False) or native default (True) strings explicitly. Read-only: no "
        "filesystem, selection, add-in load, configuration change or save; requires "
        "an existing connection but no open document."
    ),
    schema=_SCHEMA,
    operation_class=OperationClass.READ,
    com=True,
)
def get_routing_file_locations(sw, use_default=False) -> Dict:
    """Read Routing file locations and toggles; fail closed per field."""
    # Gate first: no application, connection or COM access while Routing is off.
    if not _routing_allowed():
        return sw._result(
            False, _ROUTING_DISABLED_MESSAGE, SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        )

    # Bound the direct handler argument before any COM access: an int 0/1 or a
    # string must not be silently treated as a request selector.
    if not isinstance(use_default, bool):
        return sw._result(
            False, "use_default must be a boolean (False = configured, True = defaults).",
            SwErrors.swInvalidInput,
            {"code": "ROUTING_INPUT_INVALID", "use_default": use_default},
        )

    # An existing connection is required, but no document: this tool never reads
    # ActiveDoc, so any open document or none at all is acceptable.
    if not sw.is_connected:
        return sw._result(
            False,
            "Connect to the running SolidWorks session before reading Routing settings.",
            SwErrors.swConnectionError,
        )
    try:
        app = sw.app
        if app is None:
            raise RuntimeError("The existing SolidWorks connection was lost.")
    except Exception as exc:
        return sw._result(
            False,
            f"Could not read the connected SolidWorks application: {exc}",
            SwErrors.swConnectionError,
        )

    errors: List[str] = []
    settings = None
    accessor_failed = False
    try:
        settings = _routing_settings_object(app)
    except Exception as exc:
        accessor_failed = True
        errors.append(f"{_GET_ROUTING_SETTINGS}: {exc}")

    if settings is None:
        settings_status = "unavailable" if accessor_failed else "null"
        if not accessor_failed:
            errors.append(f"{_GET_ROUTING_SETTINGS} returned null.")
        data = {"code": "ROUTING_SETTINGS_UNAVAILABLE", **_data(
            settings_status, use_default,
            [_string_entry(field_id, name, use_default, None)
             for field_id, name in _STRING_FIELDS],
            [_toggle_entry(field_id, name, None)
             for field_id, name in _TOGGLE_FIELDS],
            False, errors,
        )}
        return sw._result(
            False,
            "Native Routing settings object unavailable; no file location was read.",
            SwErrors.swUnknownError if accessor_failed else SwErrors.swFeatureError,
            data,
        )

    file_locations: List[Dict[str, Any]] = []
    for field_id, name in _STRING_FIELDS:
        entry = _string_entry(field_id, name, use_default, None)
        try:
            entry["value"] = _native_str(
                _raw_invoke(settings, _STRING_GETTER, field_id, use_default))
        except Exception as exc:
            errors.append(f"{_STRING_GETTER}({field_id}, {use_default}): {exc}")
        file_locations.append(entry)

    toggles: List[Dict[str, Any]] = []
    for field_id, name in _TOGGLE_FIELDS:
        entry = _toggle_entry(field_id, name, None)
        try:
            entry["value"] = _native_toggle(
                _raw_invoke(settings, _TOGGLE_GETTER, field_id))
        except Exception as exc:
            errors.append(f"{_TOGGLE_GETTER}({field_id}): {exc}")
        toggles.append(entry)

    complete = not errors
    data = _data("object", use_default, file_locations, toggles, complete, errors)

    if not complete:
        return sw._result(
            False,
            "Routing file locations read is incomplete; see errors. Unread fields "
            "stay null and no path is invented.",
            SwErrors.swUnknownError,
            {"code": "ROUTING_SETTINGS_INCOMPLETE", **data},
        )

    return sw._result(
        True,
        f"Routing file locations read (use_default={use_default}); "
        f"{len(file_locations)} string(s) and {len(toggles)} toggle(s).",
        SwErrors.swSuccess,
        {"code": "ROUTING_FILE_LOCATIONS_READ", **data},
    )
