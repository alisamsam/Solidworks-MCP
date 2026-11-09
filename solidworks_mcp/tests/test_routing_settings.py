"""get_routing_file_locations: read-only Routing file locations and toggles.

The tool reads the four ``swUserPreferenceRoutingFileLocations_e`` strings and four
Routing save/naming toggles through ``ISldWorks.GetRoutingSettings`` ->
``IRoutingSettings``. These tests pin the boundaries the brief requires: the
Routing gate before any automation access, an existing connection with *no* active
document requirement, explicit ``GetIDsOfNames`` + ``DISPATCH_METHOD`` for
``GetRoutingSettings`` and both parameter getters, the raw-``PyIDispatch`` wrapper,
the exact enum ids/names, ``use_default`` as an explicit request selector rather
than a fallback (configured vs defaults, empty configured strings preserved), the
absence of Electrical ids 5+, the core ``GetUserPreferenceStringValue`` and any
filesystem/CAD/add-in access, and fail-closed per-field handling (null object,
raised read, invalid native return) that reports ``complete=False`` without
inventing paths.
"""

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jsonschema import Draft7Validator

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools import routing
from solidworks_mcp.tools import routing_settings as rs

_DISPATCH_METHOD = 1
_STRING_DISPID = 11
_TOGGLE_DISPID = 12

_CONFIGURED = {
    1: r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\design library\routing",
    2: r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates\routeAssembly.asmdot",
    3: "",  # configured Standard Tubes may legitimately be empty
    4: r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\design library\routing\coverings.xml",
}
_DEFAULTS = {
    1: r"<built-in routing library>",
    2: r"<built-in route assembly template>",
    3: r"<built-in standard tubes>",
    4: r"<built-in covering library>",
}
_TOGGLE_VALUES = {2: True, 3: False, 4: False, 13: False}


class FakeSettingsOle:
    """Raw dispatch for ``IRoutingSettings`` with explicit member resolution."""

    def __init__(self):
        self.string_values = {False: dict(_CONFIGURED), True: dict(_DEFAULTS)}
        self.toggle_values = dict(_TOGGLE_VALUES)
        self.getid_calls = []
        self.invoke_calls = []
        self.errors = {}       # member name -> exception raised on Invoke
        self.bad_value = {}    # member name -> returned invalid native value

    def GetIDsOfNames(self, name):
        self.getid_calls.append(name)
        if name == rs._STRING_GETTER:
            return _STRING_DISPID
        if name == rs._TOGGLE_GETTER:
            return _TOGGLE_DISPID
        raise RuntimeError(f"unexpected Routing member: {name}")

    def Invoke(self, dispid, lcid, flags, want, *args):
        name = {_STRING_DISPID: rs._STRING_GETTER,
                _TOGGLE_DISPID: rs._TOGGLE_GETTER}[dispid]
        self.invoke_calls.append((name, lcid, flags, want, args))
        if name in self.errors:
            raise self.errors[name]
        if name in self.bad_value:
            return self.bad_value[name]
        if name == rs._STRING_GETTER:
            field_id, use_default = args
            return self.string_values[bool(use_default)][field_id]
        return self.toggle_values[args[0]]


class FakeSettings:
    """The wrapped settings view: one shared raw ole, no other members."""

    def __init__(self, ole):
        self._oleobj_ = ole

    def __getattr__(self, name):
        raise AssertionError(f"unexpected settings member: {name}")


class App:
    def __getattr__(self, name):
        raise AssertionError(f"get_routing_file_locations must not read app.{name}")


class SW:
    def __init__(self, app=App(), connected=True):
        self.is_connected = connected
        self.app = app

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data or {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


def _by_id(entries):
    return {entry["id"]: entry for entry in entries}


class RoutingSettingsTests(unittest.TestCase):
    def setUp(self):
        self.ole = FakeSettingsOle()
        self.settings = FakeSettings(self.ole)
        gate = patch.object(catalog, "routing_enabled", return_value=True)
        gate.start()
        self.addCleanup(gate.stop)

    def accessor(self, returns=None, raises=None):
        """Patch rs._routing_settings_object; default returns the shared settings."""
        if raises is not None:
            handle = patch.object(rs, "_routing_settings_object", side_effect=raises)
        else:
            def factory(app):
                return self.settings if returns is None else returns.pop(0)
            handle = patch.object(rs, "_routing_settings_object", side_effect=factory)
        started = handle.start()
        self.addCleanup(handle.stop)
        return started

    def run_tool(self, sw=None, **kwargs):
        return rs.get_routing_file_locations(sw if sw is not None else SW(), **kwargs)

    # -- registration and schema ---------------------------------------------

    def test_registered_read_only_with_com_and_no_postflight(self):
        registry.registered_tools()  # ensure the registry is loaded
        entry = registry._TOOLS["get_routing_file_locations"]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertTrue(entry["com"])
        self.assertIsNone(entry["postflight"])
        self.assertEqual(entry["handler"].__module__,
                         "solidworks_mcp.tools.routing_settings")

    def test_schema_is_closed_boolean_use_default(self):
        schema = registry._TOOLS["get_routing_file_locations"]["tool"].inputSchema
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual([], schema["required"])
        self.assertEqual("boolean", schema["properties"]["use_default"]["type"])
        validator = Draft7Validator(schema)
        for good in ({}, {"use_default": True}, {"use_default": False}):
            self.assertEqual([], list(validator.iter_errors(good)), good)
        for bad in ({"use_default": 1}, {"use_default": "true"}, {"use_default": None},
                    {"use_default": []}, {"extra": 1}):
            self.assertTrue(list(validator.iter_errors(bad)), bad)

    def test_reuses_the_shared_routing_gate(self):
        self.assertIs(rs._routing_allowed, routing._routing_allowed)

    # -- gate first -----------------------------------------------------------

    def test_disabled_gate_rejects_before_any_automation_access(self):
        class Disabled(SW):
            @property
            def is_connected(self):
                raise AssertionError("gate must be first")

        with patch.object(catalog, "routing_enabled", return_value=False):
            result = rs.get_routing_file_locations(Disabled.__new__(Disabled))
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_registry_rejects_before_handler_when_disabled(self):
        sw = SW()
        handler = Mock()
        entry = dict(registry._TOOLS["get_routing_file_locations"], handler=handler)
        with patch.dict(registry._TOOLS, {"get_routing_file_locations": entry}), \
                patch.object(catalog, "toolset_of", return_value="routing"), \
                patch.object(catalog, "routing_enabled", return_value=False):
            result = registry.execute("get_routing_file_locations", sw, {}).result
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])
        handler.assert_not_called()

    # -- bounded direct argument + connection, no active document --------------

    def test_invalid_use_default_is_rejected_before_com(self):
        handle = self.accessor(raises=AssertionError("must not read settings"))
        for bad in (None, 1, 0, "true", [], {}):
            with self.subTest(use_default=bad):
                result = self.run_tool(use_default=bad)
                self.assertFalse(result["success"])
                self.assertEqual("ROUTING_INPUT_INVALID", result["data"]["code"])
        self.assertEqual(0, handle.call_count)
        self.assertEqual([], self.ole.invoke_calls)

    def test_disconnected_and_null_app_report_connection_error(self):
        handle = self.accessor(raises=AssertionError("must not read settings"))
        disconnected = self.run_tool(sw=SW(connected=False))
        self.assertEqual("swConnectionError", disconnected["error_name"])
        null_app = self.run_tool(sw=SW(app=None))
        self.assertEqual("swConnectionError", null_app["error_name"])
        self.assertEqual(0, handle.call_count)

    def test_no_active_document_is_required(self):
        # App.__getattr__ raises for any member the handler might touch; only
        # sw.app is read, so no ActiveDoc access and no document is needed.
        self.accessor()
        result = self.run_tool()
        self.assertTrue(result["success"], result)

    # -- accessor: explicit dispatch and raw wrapper ---------------------------

    def test_settings_accessor_invokes_dispatch_method_and_wraps_pyidispatch(self):
        raw = object()
        ole_holder = SimpleNamespace(raw=raw, invoke_calls=[], getid_calls=[])

        class AppOle:
            def GetIDsOfNames(self, name):
                ole_holder.getid_calls.append(name)
                return 7

            def Invoke(self, dispid, lcid, flags, want, *args):
                ole_holder.invoke_calls.append((dispid, lcid, flags, want, args))
                return ole_holder.raw

        sentinel = object()
        app = SimpleNamespace(_oleobj_=AppOle())
        with patch("win32com.client.Dispatch", return_value=sentinel) as dispatch:
            settings = rs._routing_settings_object(app)
        self.assertIs(sentinel, settings)
        dispatch.assert_called_once_with(raw)
        self.assertEqual(["GetRoutingSettings"], ole_holder.getid_calls)
        self.assertEqual([(7, 0, _DISPATCH_METHOD, True, ())], ole_holder.invoke_calls)

    def test_settings_accessor_null_returns_none_without_wrapping(self):
        class AppOle:
            def GetIDsOfNames(self, name):
                return 1

            def Invoke(self, *args):
                return None

        with patch("win32com.client.Dispatch",
                   side_effect=AssertionError("must not wrap null")) as dispatch:
            settings = rs._routing_settings_object(SimpleNamespace(_oleobj_=AppOle()))
        self.assertIsNone(settings)
        dispatch.assert_not_called()

    def test_raw_invoke_uses_explicit_dispatch_flags(self):
        class Ole:
            def GetIDsOfNames(self, name):
                self.name = name
                return 5

            def Invoke(self, *args):
                self.args = args
                return "path"

        ole = Ole()
        value = rs._raw_invoke(SimpleNamespace(_oleobj_=ole), rs._STRING_GETTER, 3, True)
        self.assertEqual("path", value)
        self.assertEqual(rs._STRING_GETTER, ole.name)
        self.assertEqual((5, 0, _DISPATCH_METHOD, True, 3, True), ole.args)

    # -- null / unreadable settings object ------------------------------------

    def test_null_settings_object_fails_closed_and_keeps_ids(self):
        self.accessor(returns=[None])
        result = self.run_tool()
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_SETTINGS_UNAVAILABLE", data["code"])
        self.assertEqual("null", data["settings_status"])
        self.assertFalse(data["complete"])
        self.assertEqual([1, 2, 3, 4], [entry["id"] for entry in data["file_locations"]])
        self.assertTrue(all(entry["value"] is None for entry in data["file_locations"]))
        self.assertEqual([2, 3, 4, 13], [entry["id"] for entry in data["toggles"]])
        self.assertTrue(all(entry["value"] is None for entry in data["toggles"]))
        self.assertEqual([], self.ole.invoke_calls)

    def test_settings_accessor_error_fails_closed(self):
        self.accessor(raises=RuntimeError("no settings"))
        result = self.run_tool()
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_SETTINGS_UNAVAILABLE", data["code"])
        self.assertEqual("unavailable", data["settings_status"])
        self.assertFalse(data["complete"])
        self.assertTrue(any("GetRoutingSettings" in error for error in data["errors"]))

    # -- exact ids, args and raw values ---------------------------------------

    def test_all_ids_args_and_raw_paths_are_read(self):
        self.accessor()
        result = self.run_tool(use_default=False)
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual("ROUTING_FILE_LOCATIONS_READ", data["code"])
        self.assertTrue(data["complete"])
        self.assertEqual([], data["errors"])
        self.assertFalse(data["use_default"])
        self.assertEqual("swUserPreferenceRoutingFileLocations_e", data["string_enum"])

        locations = _by_id(data["file_locations"])
        self.assertEqual([1, 2, 3, 4], sorted(locations))
        self.assertEqual({"id": 1, "name": "swRoutingLibraryPath",
                          "use_default": False, "value": _CONFIGURED[1]}, locations[1])
        self.assertEqual("swFileLocationsRoutingAssemblyTemplate", locations[2]["name"])
        self.assertEqual("", locations[3]["value"])  # empty configured path preserved
        self.assertEqual("swFileLocationsRoutingPipeTubeCoveringLibrary",
                         locations[4]["name"])
        self.assertEqual(_CONFIGURED[4], locations[4]["value"])

        toggles = _by_id(data["toggles"])
        self.assertEqual([2, 3, 4, 13], sorted(toggles))
        self.assertEqual({"id": 2, "name": "swSaveRouteAssemblyExternally",
                          "value": True}, toggles[2])
        self.assertEqual("swSaveRoutePartsExternally", toggles[3]["name"])
        self.assertEqual("swUseAutomaticNamingForRouteParts", toggles[4]["name"])
        self.assertEqual("swAlwaysUseDefaultDocumentTemplate", toggles[13]["name"])
        self.assertEqual(False, toggles[13]["value"])

        # Every string getter took (id, False); every toggle getter took (id,).
        self.assertEqual(
            [(rs._STRING_GETTER, 0, _DISPATCH_METHOD, True, (field_id, False))
             for field_id in (1, 2, 3, 4)]
            + [(rs._TOGGLE_GETTER, 0, _DISPATCH_METHOD, True, (field_id,))
               for field_id in (2, 3, 4, 13)],
            self.ole.invoke_calls)

    def test_use_default_true_is_passed_and_reported(self):
        self.accessor()
        result = self.run_tool(use_default=True)
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertTrue(data["use_default"])
        locations = _by_id(data["file_locations"])
        self.assertEqual(_DEFAULTS[1], locations[1]["value"])
        self.assertTrue(all(entry["use_default"] is True
                            for entry in data["file_locations"]))
        self.assertIn((rs._STRING_GETTER, 0, _DISPATCH_METHOD, True, (1, True)),
                      self.ole.invoke_calls)

    def test_configured_and_defaults_are_distinct_not_a_fallback(self):
        self.accessor()
        configured = _by_id(self.run_tool(use_default=False)["data"]["file_locations"])
        self.ole.invoke_calls.clear()
        defaults = _by_id(self.run_tool(use_default=True)["data"]["file_locations"])
        for field_id in (1, 2, 3, 4):
            self.assertNotEqual(configured[field_id]["value"], defaults[field_id]["value"])
        # An empty configured string is reported as empty, never as the default.
        self.assertEqual("", configured[3]["value"])
        self.assertEqual(_DEFAULTS[3], defaults[3]["value"])

    # -- fail-closed per field -------------------------------------------------

    def test_raising_field_reports_error_and_reads_the_rest(self):
        self.ole.errors[rs._STRING_GETTER] = RuntimeError("read failed")
        self.accessor()
        result = self.run_tool()
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_SETTINGS_INCOMPLETE", data["code"])
        self.assertFalse(data["complete"])
        self.assertTrue(all(entry["value"] is None for entry in data["file_locations"]))
        self.assertTrue(any("GetRoutingUserPreferenceStringValue(1, False)" in error
                            for error in data["errors"]))
        # The toggles were still read even though the string getter raised.
        self.assertEqual(_TOGGLE_VALUES[2], _by_id(data["toggles"])[2]["value"])

    def test_invalid_string_return_is_a_per_field_error(self):
        for bad in (None, 5, True, b"bytes"):
            with self.subTest(bad=bad):
                self.ole.bad_value[rs._STRING_GETTER] = bad
                self.accessor()
                result = self.run_tool()
                self.assertFalse(result["success"])
                data = result["data"]
                self.assertEqual("ROUTING_SETTINGS_INCOMPLETE", data["code"])
                self.assertFalse(data["complete"])
                self.assertTrue(all(entry["value"] is None
                                    for entry in data["file_locations"]))

    def test_invalid_toggle_return_is_a_per_field_error(self):
        for bad in (None, "yes", 2, 1.0):
            with self.subTest(bad=bad):
                self.ole.bad_value[rs._TOGGLE_GETTER] = bad
                self.accessor()
                result = self.run_tool()
                self.assertFalse(result["success"])
                data = result["data"]
                self.assertEqual("ROUTING_SETTINGS_INCOMPLETE", data["code"])
                self.assertTrue(all(entry["value"] is None for entry in data["toggles"]))

    # -- no Electrical ids, no core API, no filesystem -------------------------

    def test_only_ids_one_to_four_and_the_four_toggles_are_read(self):
        self.assertEqual([1, 2, 3, 4], [field_id for field_id, _ in rs._STRING_FIELDS])
        self.assertEqual([2, 3, 4, 13], [field_id for field_id, _ in rs._TOGGLE_FIELDS])
        # No Electrical member (id 5+) and never the core electrical xml id 37.
        self.assertTrue(all(field_id < 5 for field_id, _ in rs._STRING_FIELDS))
        self.assertNotIn(37, [field_id for field_id, _ in rs._STRING_FIELDS]
                         + [field_id for field_id, _ in rs._TOGGLE_FIELDS])
        self.assertEqual(["swRoutingLibraryPath",
                          "swFileLocationsRoutingAssemblyTemplate",
                          "swFileLocationsRoutingStandardTubes",
                          "swFileLocationsRoutingPipeTubeCoveringLibrary"],
                         [name for _, name in rs._STRING_FIELDS])
        self.assertEqual(["swSaveRouteAssemblyExternally", "swSaveRoutePartsExternally",
                          "swUseAutomaticNamingForRouteParts",
                          "swAlwaysUseDefaultDocumentTemplate"],
                         [name for _, name in rs._TOGGLE_FIELDS])

    def test_only_the_routing_getters_are_invoked(self):
        self.accessor()
        self.run_tool()
        self.assertEqual({rs._STRING_GETTER, rs._TOGGLE_GETTER},
                         set(self.ole.getid_calls))
        # The core preference API and Electrical members are never resolved because
        # FakeSettingsOle.GetIDsOfNames raises for anything else.
        self.assertNotIn("GetUserPreferenceStringValue", self.ole.getid_calls)
        self.assertNotIn("GetUserPreferenceToggle", self.ole.getid_calls)

    def test_module_has_no_filesystem_handles(self):
        for attribute in ("Path", "os", "open", "stat", "exists", "listdir"):
            self.assertFalse(hasattr(rs, attribute), attribute)

    def test_notes_separate_settings_from_licence_and_save_destination(self):
        self.accessor()
        result = self.run_tool()
        notes = " ".join(result["data"]["notes"])
        self.assertIn("not a licence or add-in readiness check", notes)
        self.assertIn("does not control where route assemblies or parts are saved", notes)
        source = inspect.getsource(rs)
        self.assertIn("no filesystem", source)


if __name__ == "__main__":
    unittest.main()
