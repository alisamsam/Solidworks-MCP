"""Read-only Routing detection: offline status (RT0) and native context (RT1).

RT0 ``get_routing_status`` reports two independent offline facts:

* whether Routing is permitted by server configuration, and
* which Routing installation files verify on local disk.

It never connects to, launches or loads SolidWorks and never touches an active
document or the selection, so it cannot report whether Routing is licensed,
loaded as an add-in or otherwise usable. Verified file presence is reported as
strictly as that; license, add-in loaded state and library readiness are always
reported as ``"unknown"`` because nothing here probes them.

RT1 ``inspect_routing_context`` is a bounded, read-only read of the *active*
assembly: its identity plus ``IAssemblyDoc.IsRouteAssembly`` and
``IAssemblyDoc.GetRouteManager`` (both zero-argument). It never calls a member
on the returned route manager, never inspects route segments and never touches
the selection, add-in loading, edit mode or the saved file. A null route
manager is reported as a diagnostic read result, never as proof that the
Routing add-in is disabled or that the assembly has no segments.

RT0's offline guard test asserts that importing this module does not pull the
COM helper in, so the COM import stays local to the RT1 handler.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..constants import SwDocumentTypes, SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from ..utils import get_solidworks_info


# (filename, role, required). The interop assembly is informational only: RT0
# never loads it, so its absence is not treated as a failure.
_ROUTING_MARKERS: Tuple[Tuple[str, str, bool], ...] = (
    ("sldrtadd.dll", "routing_addin_dll", True),
    ("SWRoutingLib.tlb", "routing_type_library", True),
    ("SolidWorks.Interop.SWRoutingLib.dll", "routing_interop_assembly", False),
)

# Bounded candidate directories below the install root. No recursive walk.
_SEARCH_SUBDIRS: Tuple[str, ...] = ("", "api", "api/redist")

_UNAVAILABLE = "unknown"


def _verified_routing_files(install_dir: Optional[str]) -> Tuple[List[Dict], List[Dict]]:
    """Return (verified, missing) file reports found directly under bounded dirs."""
    verified: List[Dict] = []
    missing: List[Dict] = []
    for filename, role, required in _ROUTING_MARKERS:
        found: Optional[Path] = None
        if install_dir:
            for subdir in _SEARCH_SUBDIRS:
                candidate = Path(install_dir, subdir, filename) if subdir \
                    else Path(install_dir, filename)
                try:
                    if candidate.is_file():
                        found = candidate
                        break
                except OSError:
                    continue
        if found is None:
            missing.append({"name": filename, "role": role, "required": required})
            continue
        entry = {
            "name": filename,
            "role": role,
            "required": required,
            "path": str(found),
            "size_bytes": None,
        }
        try:
            entry["size_bytes"] = found.stat().st_size
        except OSError:
            pass
        verified.append(entry)
    return verified, missing


def _routing_allowed() -> bool:
    """Configuration permission; imported lazily to avoid an import cycle."""
    from .. import catalog

    return catalog.routing_enabled()


@tool(
    name="get_routing_status",
    description=(
        "Report read-only Routing availability: the configuration gate and which "
        "Routing installation files verify on disk. Does not connect to, launch or "
        "load SolidWorks; license, add-in loaded state and library readiness are "
        "reported as unknown."
    ),
    schema={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    operation_class=OperationClass.READ,
    com=False,
)
def get_routing_status(sw) -> Dict:
    """Report Routing configuration permission and verified installation files."""
    if not _routing_allowed():
        return sw._result(
            False,
            "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
            "and restart the MCP server.",
            SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        )

    info = get_solidworks_info()
    install_dir = info.get("install_dir")
    found = bool(info.get("found"))
    verified, missing = _verified_routing_files(install_dir)

    data = {
        "configuration": {
            "routing_enabled": True,
        },
        "installation": {
            "found": found,
            "install_dir": install_dir,
            "version": info.get("version"),
        },
        "routing_files": {
            "verified": verified,
            "missing": missing,
            "verified_count": len(verified),
            "missing_count": len(missing),
        },
        "readiness": {
            "installed_files_verified": bool(verified),
            "license": _UNAVAILABLE,
            "addin_loaded": _UNAVAILABLE,
            "library_ready": _UNAVAILABLE,
        },
        "notes": [
            "Read-only local detection; no SolidWorks connection, launch or add-in load.",
            "License availability, add-in loaded state and library readiness are not "
            "probed and remain unknown.",
            "Verified file presence does not imply Routing is licensed or usable.",
        ],
    }

    if not found:
        return sw._result(
            False,
            "SolidWorks installation not found; Routing files were not scanned.",
            SwErrors.swSolidWorksNotFound,
            data,
        )

    return sw._result(
        True,
        f"Routing permitted; {len(verified)} installation file(s) verified "
        f"(license and add-in state unknown).",
        SwErrors.swSuccess,
        data,
    )


# ---------------------------------------------------------------------------
# RT1: native Routing context of the active assembly (read-only, com=True)
# ---------------------------------------------------------------------------

_DOCUMENT_TYPE_NAMES = {
    int(SwDocumentTypes.swDocPART): "part",
    int(SwDocumentTypes.swDocASSEMBLY): "assembly",
    int(SwDocumentTypes.swDocDRAWING): "drawing",
}

# Status vocabulary for one member read. "unavailable" stays distinct from a
# legitimate value: a COM failure must never read as ``native_route false``.
_READ_UNAVAILABLE = "unavailable"


def _com_member(obj, name):
    """Read one COM member, property or method, as ``comutil.com`` does.

    The import is deliberately local: RT0's offline guard test asserts that
    importing this module does not pull the COM helper in, so only the RT1
    handler (declared ``com=True``) may reach it.
    """
    from ..comutil import com

    return com(obj, name)


def _require_active_document_type(sw, required_type):
    """Return (document, document_type, error_result) for the required model type.

    Read the existing app proxy without auto-connect, activation or retry.
    Missing documents and non-assembly documents are distinct failures.
    """
    # Do not use get_active_doc: its second connectivity check can auto-launch SW.
    if not sw.is_connected:
        return None, None, sw._result(
            False, "Connect to the running SolidWorks session before inspecting Routing.",
            SwErrors.swConnectionError)
    try:
        app = sw.app
        if app is None:
            raise RuntimeError("The existing SolidWorks connection was lost.")
        doc = _com_member(app, "ActiveDoc")
    except Exception as exc:
        return None, None, sw._result(
            False, f"Could not read the connected SolidWorks document: {exc}",
            SwErrors.swConnectionError)
    required_name = _DOCUMENT_TYPE_NAMES[int(required_type)]
    if doc is None:
        return None, None, sw._result(
            False, f"No document open. Open a {required_name} before inspecting Routing.",
            SwErrors.swNoActiveDocument)
    try:
        document_type = _com_member(doc, "GetType")
    except Exception as exc:  # a broken read is reported, not treated as a type
        return None, None, sw._result(
            False, f"Could not read the active document type: {exc}",
            SwErrors.swUnknownError)
    if document_type != required_type:
        return None, None, sw._result(
            False, f"Active document is not a {required_name}.", SwErrors.swInvalidFileType)
    return doc, document_type, None


def _require_active_assembly(sw):
    return _require_active_document_type(sw, SwDocumentTypes.swDocASSEMBLY)


def _read_route_manager(assembly):
    """Invoke the documented method, not pywin32's PROPERTYGET fallback."""
    import pythoncom

    ole = assembly._oleobj_
    dispid = ole.GetIDsOfNames("GetRouteManager")
    return ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True)


def _coerce_native_bool(value) -> Optional[bool]:
    """True/False for a native boolean, None when the member gave no boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None


@tool(
    name="inspect_routing_context",
    description=(
        "Read the active assembly's native Routing context: document identity, "
        "IAssemblyDoc.IsRouteAssembly and whether IAssemblyDoc.GetRouteManager "
        "returns a manager object. Requires an existing MCP connection; route segments, the selection and "
        "add-in/license state are not inspected or inferred."
    ),
    schema={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    operation_class=OperationClass.READ,
    com=True,
)
def inspect_routing_context(sw) -> Dict:
    """Report native route-assembly identity and route-manager availability."""
    if not _routing_allowed():
        return sw._result(
            False,
            "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
            "and restart the MCP server.",
            SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        )

    asm, document_type, error = _require_active_assembly(sw)
    if error:
        return error

    errors: List[str] = []

    def read_optional(name) -> Tuple[bool, Any]:
        try:
            value = _read_route_manager(asm) if name == "GetRouteManager" else _com_member(asm, name)
        except Exception as exc:  # member failure is reported, never inferred
            errors.append(f"{name} unavailable: {exc}")
            return False, None
        return True, value

    # IAssemblyDoc.IsRouteAssembly: zero-argument bool. A failed or non-boolean
    # read is "unavailable", never "false".
    native_route_assembly: Optional[bool] = None
    native_route_status = _READ_UNAVAILABLE
    ok, value = read_optional("IsRouteAssembly")
    if ok:
        native_route_assembly = _coerce_native_bool(value)
        if native_route_assembly is None:
            errors.append("IsRouteAssembly returned no boolean value.")
        else:
            native_route_status = "read"

    # IAssemblyDoc.GetRouteManager: zero-argument IDispatch. Only object
    # availability is observed; no member is called on a returned manager.
    route_manager_available: Optional[bool] = None
    route_manager_status = _READ_UNAVAILABLE
    ok, manager = read_optional("GetRouteManager")
    if ok:
        if manager is None:
            route_manager_available = False
            route_manager_status = "null"
        else:
            route_manager_available = True
            route_manager_status = "object"

    title_ok, title = read_optional("GetTitle")
    path_ok, path = read_optional("GetPathName")

    data = {
        "configuration": {"routing_enabled": True},
        "document": {
            "title": str(title) if title_ok and title else None,
            "path": str(path) if path_ok and path else None,
            "document_type": int(document_type),
            "document_type_name": _DOCUMENT_TYPE_NAMES.get(int(document_type), "unknown"),
            "is_assembly": True,
        },
        "native_route_assembly": native_route_assembly,
        "native_route_status": native_route_status,
        "route_manager_available": route_manager_available,
        "route_manager_status": route_manager_status,
        "segments_inspected": False,
        "errors": errors,
        "notes": [
            "Read-only native context: only IsRouteAssembly and GetRouteManager were "
            "read; no member was called on the route manager object.",
            "Route segments were not inspected; the result reports no segment count "
            "and must not be read as zero segments.",
            "A null route manager (route_manager_available=false) is a diagnostic read "
            "result, not proof that the Routing add-in is disabled or unlicensed.",
            "License and add-in loaded state are not probed and are not inferred.",
        ],
    }

    if errors:
        return sw._result(
            False,
            "Routing context could not be fully read; see errors. "
            "Unread members are reported as unavailable, not as false.",
            SwErrors.swUnknownError,
            data,
        )

    return sw._result(
        True,
        f"Native routing context read (native_route_assembly="
        f"{native_route_assembly}, route_manager_available={route_manager_available}); "
        f"segments not inspected.",
        SwErrors.swSuccess,
        data,
    )


def _point_number(value):
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric native value.")
    return float(value)


def _point_vector(value, scale):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("Expected a native XYZ vector of three numbers.")
    return [_point_number(_point_number(component) * scale) for component in value]


def _connection_point_data(feature, name):
    """Read native feature data without AccessSelections or ModifyDefinition."""
    point = {"feature_name": name, "feature_type": "ConnectionPoint", "errors": []}
    point.update({key: None for key in (
        "position_mm", "direction", "nominal_diameter_mm", "stub_length_mm",
        "route_type_raw", "route_subtype_raw", "port_id",
    )})
    try:
        definition = _com_member(feature, "GetDefinition")
        if definition is None:
            raise ValueError("GetDefinition returned null.")
    except Exception as exc:
        point.update(read_complete=False)
        point["errors"].append(f"GetDefinition: {exc}")
        return point

    fields = (
        ("Location", "position_mm", lambda v: _point_vector(v, 1000.0)),
        ("Direction", "direction", lambda v: _point_vector(v, 1.0)),
        ("RouteDiameter", "nominal_diameter_mm", lambda v: _point_number(_point_number(v) * 1000.0)),
        ("StubLength", "stub_length_mm", lambda v: _point_number(_point_number(v) * 1000.0)),
        ("RouteType", "route_type_raw", _point_integer),
        ("RouteSubType", "route_subtype_raw", _point_integer),
        ("PortID", "port_id", _point_string),
    )
    for member, key, convert in fields:
        try:
            point[key] = convert(_com_member(definition, member))
        except Exception as exc:
            point[key] = None
            point["errors"].append(f"{member}: {exc}")
    point["read_complete"] = not point["errors"]
    return point


def _point_integer(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer native enum value.")
    return value


def _point_string(value):
    if not isinstance(value, str):
        raise ValueError("Expected a native string.")
    return value


@tool(
    name="list_routing_connection_points",
    description=(
        "Read top-level native CPoint features in the active part: part-local XYZ in mm, "
        "direction, nominal diameter, stub length, raw route type/subtype and port ID. "
        "Requires an existing MCP connection. No selection, editing or add-in loading. "
        "Bounded to 1000 top-level features; does not inspect RPoints or assembly instances."
    ),
    schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    operation_class=OperationClass.READ,
    com=True,
)
def list_routing_connection_points(sw) -> Dict:
    if not _routing_allowed():
        return sw._result(False, "Routing is disabled.", SwErrors.swInvalidInput,
                          {"code": "ROUTING_DISABLED"})
    doc, _, error = _require_active_document_type(sw, SwDocumentTypes.swDocPART)
    if error:
        return error
    points = []
    errors = []
    visited = 0
    truncated = False
    retained = []  # Keep proxies alive during native traversal; never mutate them.
    title = path = None
    try:
        title = _com_member(doc, "GetTitle")
        path = _com_member(doc, "GetPathName")
        feature = _com_member(doc, "FirstFeature")
        while feature is not None and visited < 1000:
            retained.append(feature)
            visited += 1
            if _com_member(feature, "GetTypeName2") == "ConnectionPoint":
                points.append(_connection_point_data(feature, _com_member(feature, "Name")))
            feature = _com_member(feature, "GetNextFeature")
        truncated = feature is not None
    except Exception as exc:
        errors.append(f"Feature traversal: {exc}")
    complete = not errors and not truncated and all(p["read_complete"] for p in points)
    data = {
        "document": {"title": title, "path": path or None},
        "coordinate_system": "active_part_local",
        "length_unit": "mm",
        "connection_points": points,
        "count": len(points),
        "coverage": {"scope": "top_level_features", "complete": complete,
                     "visited_features": visited, "truncated": truncated, "limit": 1000},
        "errors": errors,
        "notes": ["Diameter is the native nominal route diameter, not measured fitting OD.",
                  "Route enums are raw CPoint values, not IRouteManager RouteType values.",
                  "No RPoint geometry, selection access, manager, license or connectivity inspection."],
    }
    return sw._result(not errors and all(p["read_complete"] for p in points),
                      "Connection points read." if complete else "Connection point inspection is incomplete; see coverage/errors.",
                      SwErrors.swSuccess if not errors and all(p["read_complete"] for p in points) else SwErrors.swUnknownError,
                      data)


def _routing_component_manager(doc):
    import pythoncom
    import win32com.client

    ext = _com_member(doc, "Extension")
    ole = ext._oleobj_
    raw = ole.Invoke(ole.GetIDsOfNames("GetRoutingComponentManager"), 0,
                     pythoncom.DISPATCH_METHOD, True)
    return None if raw is None else win32com.client.Dispatch(raw)


def _metadata_method(manager, name):
    import pythoncom

    ole = manager._oleobj_
    return ole.Invoke(ole.GetIDsOfNames(name), 0, pythoncom.DISPATCH_METHOD, True)


@tool(
    name="get_routing_component_metadata",
    description="Read native Routing library metadata of the active part through IModelDocExtension.GetRoutingComponentManager: raw component type, raw component route type, CPoint inclusion rule and description. No selection, configuration activation, add-in load, rebuild or save. Requires an existing MCP connection.",
    schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    operation_class=OperationClass.READ,
    com=True,
)
def get_routing_component_metadata(sw):
    if not _routing_allowed():
        return sw._result(False, "Routing is disabled.", SwErrors.swInvalidInput,
                          {"code": "ROUTING_DISABLED"})
    doc, _, error = _require_active_document_type(sw, SwDocumentTypes.swDocPART)
    if error: return error
    data = {"manager_status": "unavailable", "component_type_raw": None,
            "component_route_type_raw": None, "cpoint_configuration_raw": None,
            "description": None, "errors": [],
            "notes": ["Raw enums belong to swRouteComponentTypeID_e, swComponentRouteType_e and swCPointConfig_e, not CPoint RouteType.",
                      "Library metadata does not prove route connectivity, licence or geometric compatibility."]}
    try:
        data["document"] = {"title": _com_member(doc, "GetTitle"),
                            "path": _com_member(doc, "GetPathName") or None,
                            "configuration": _com_member(_com_member(_com_member(doc, "ConfigurationManager"), "ActiveConfiguration"), "Name")}
        manager = _routing_component_manager(doc)
        if manager is None:
            data["manager_status"] = "null"
            return sw._result(False, "Native Routing component manager returned null.", SwErrors.swFeatureError, data)
        data["manager_status"] = "object"
        for member, key, convert in (
            ("GetComponentType", "component_type_raw", _point_integer),
            ("GetComponentRouteType", "component_route_type_raw", _point_integer),
            ("GetCPointConfiguration", "cpoint_configuration_raw", _point_integer),
            ("GetRoutingComponentDescription", "description", _point_string),
        ):
            try:
                data[key] = convert(_metadata_method(manager, member))
            except Exception as exc:
                data["errors"].append(f"{member}: {exc}")
    except Exception as exc:
        data["errors"].append(str(exc))
    ok = not data["errors"]
    return sw._result(ok, "Native Routing library metadata read." if ok else "Routing metadata read is incomplete.",
                      SwErrors.swSuccess if ok else SwErrors.swUnknownError, data)
