"""configure_routing_component: bounded native Routing library metadata write.

The tool writes only the active part's requested Routing component metadata
(description and/or CPoint inclusion policy) through
``IRoutingComponentManager`` and proves the result with a *fresh* manager read
back. These tests pin the boundaries the brief requires: Routing gate before any
automation access, no auto-connect, active-part-only, direct-handler argument
validation before COM, strict policy strings and empty-description handling,
explicit ``GetIDsOfNames`` + ``DISPATCH_METHOD`` setter invocation, requested
values persisted and untouched description/policy plus component/route type
unchanged, and fail-closed null/exception handling with partial-mutation evidence
and no rollback.

The raw dispatch fake models the real manager: a shared ``FakeOle`` (the raw
``_oleobj_``) plus one ``FakeManager`` view per ``_routing_component_manager``
call, so "fresh manager after set" is observable as a new object.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema import Draft7Validator

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools import routing
from solidworks_mcp.tools import routing_library as rl

_GETTER_KEYS = {
    "GetComponentType": "component_type_raw",
    "GetComponentRouteType": "component_route_type_raw",
    "GetCPointConfiguration": "cpoint_configuration_raw",
    "GetRoutingComponentDescription": "description",
}
_SETTER_KEYS = {
    "SetRoutingComponentDescription": "description",
    "SetCPointConfiguration": "cpoint_configuration_raw",
}
_MEMBER_DISPIDS = {
    name: index + 1
    for index, name in enumerate(list(_GETTER_KEYS) + list(_SETTER_KEYS))
}
_DISPID_MEMBERS = {value: key for key, value in _MEMBER_DISPIDS.items()}

_DISPATCH_METHOD = 1


class FakeOle:
    """Raw dispatch object shared by every manager view of one native manager."""

    def __init__(self, **values):
        self.values = {
            "component_type_raw": 3,
            "component_route_type_raw": 1,
            "cpoint_configuration_raw": 1,
            "description": "",
        }
        self.values.update(values)
        self.getid_calls = []
        self.invoke_calls = []
        self.errors = {}          # member -> exception raised on Invoke
        self.error_after_set = {}  # merged into errors once a setter runs
        self.stall = set()        # setter members that record but do not persist
        self.force_on_set = {}    # values forced once a setter runs (side effects)

    def GetIDsOfNames(self, name):
        self.getid_calls.append(name)
        if name not in _MEMBER_DISPIDS:
            raise RuntimeError(f"unknown member {name}")
        return _MEMBER_DISPIDS[name]

    def Invoke(self, dispid, lcid, flags, want, *args):
        name = _DISPID_MEMBERS[dispid]
        self.invoke_calls.append((name, lcid, flags, want, args))
        if name in self.errors:
            raise self.errors[name]
        if name in _SETTER_KEYS:
            self.errors.update(self.error_after_set)
            for key, value in self.force_on_set.items():
                self.values[key] = value
            key = _SETTER_KEYS[name]
            if name not in self.stall:
                self.values[key] = args[0]
            return None
        return self.values[_GETTER_KEYS[name]]


class FakeManager:
    def __init__(self, ole):
        self._oleobj_ = ole


class Part:
    def __init__(self, kind=1, title="flange.sldprt", path="C:/library/flange.sldprt"):
        self.kind = kind
        self.title = title
        self.path = path

    def GetType(self): return self.kind
    def GetTitle(self): return self.title
    def GetPathName(self): return self.path

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected document access: {name}")


class SW:
    def __init__(self, document):
        self.is_connected = True
        self.app = SimpleNamespace(ActiveDoc=document)
        self._path_policy = SimpleNamespace(require_write=lambda path, operation: path)

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data or {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


class RoutingLibraryTests(unittest.TestCase):
    def test_native_ascii_lowercase_is_explicitly_supported_not_arbitrary_changes(self):
        before = {"component_type_raw":0,"component_route_type_raw":1,
                  "description":"", "cpoint_configuration_raw":1}
        after = dict(before, description="pipelife kg sn4")
        self.assertEqual(([], []), rl._verification({"description":"Pipelife KG SN4"}, before, after))
        changed = dict(after, description="different text")
        mismatches, _ = rl._verification({"description":"Pipelife KG SN4"}, before, changed)
        self.assertTrue(mismatches)

    def test_saved_part_without_write_policy_is_denied_before_manager(self):
        sw = SW(Part())
        sw._path_policy = None
        with patch.object(catalog, "routing_enabled", return_value=True), \
                patch.object(routing, "_routing_component_manager", side_effect=AssertionError("must not read manager")):
            result = rl.configure_routing_component(sw, description="new")
        self.assertEqual("ROUTING_LIBRARY_WRITE_DENIED", result["data"]["code"])
        self.assertFalse(result["data"]["document_may_be_modified"])

    def setUp(self):
        self.ole = FakeOle()
        self.doc = Part()
        self.views = []
        gate = patch.object(catalog, "routing_enabled", return_value=True)
        gate.start()
        self.addCleanup(gate.stop)

    def accessor(self, returns=None):
        """Patch routing._routing_component_manager with fresh views.

        Default: a new FakeManager(view) wrapping the shared ole on every call.
        ``returns``: an explicit list popped per call (e.g. [view, None]).
        """
        self.views = []

        def factory(document):
            if returns is None:
                view = FakeManager(self.ole)
            else:
                view = returns.pop(0)
            self.views.append(view)
            return view

        handle = patch.object(routing, "_routing_component_manager",
                              side_effect=factory)
        started = handle.start()
        self.addCleanup(handle.stop)
        return started

    def run_tool(self, **kwargs):
        return rl.configure_routing_component(SW(self.doc), **kwargs)

    # -- registration and schema ---------------------------------------------

    def test_registered_mutate_with_closed_at_least_one_schema(self):
        registry.registered_tools()
        entry = registry._TOOLS["configure_routing_component"]
        self.assertIs(entry["operation_class"], OperationClass.MUTATE)
        self.assertTrue(entry["com"])
        self.assertIsNone(entry["postflight"])
        schema = entry["tool"].inputSchema
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual([], schema["required"])
        self.assertEqual(
            [{"required": ["description"]}, {"required": ["cpoint_policy"]}],
            schema["anyOf"])
        self.assertEqual(["add_all", "do_not_add", "select"],
                         schema["properties"]["cpoint_policy"]["enum"])
        self.assertEqual(entry["handler"].__module__,
                         "solidworks_mcp.tools.routing_library")

    def test_schema_requires_one_field_and_rejects_unknown_policy(self):
        schema = registry._TOOLS["configure_routing_component"]["tool"].inputSchema
        validator = Draft7Validator(schema)
        for good in ({"description": ""}, {"description": "x"},
                     {"cpoint_policy": "add_all"},
                     {"description": "x", "cpoint_policy": "select"}):
            self.assertEqual([], list(validator.iter_errors(good)), good)
        for bad in ({}, {"cpoint_policy": "bogus"}, {"description": 5},
                    {"description": None}, {"cpoint_policy": 1},
                    {"extra": 1}, {"cpoint_policy": "Add_All"}):
            self.assertTrue(list(validator.iter_errors(bad)), bad)

    # -- gate first -----------------------------------------------------------

    def test_disabled_gate_rejects_before_any_automation_access(self):
        class Disabled(SW):
            @property
            def is_connected(self):
                raise AssertionError("gate must be first")

        with patch.object(catalog, "routing_enabled", return_value=False):
            result = rl.configure_routing_component(
                Disabled.__new__(Disabled), description="x")
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    # -- direct handler validation before COM --------------------------------

    def test_direct_handler_input_validation_before_com(self):
        handle = self.accessor()
        for kwargs in ({}, {"description": 5}, {"description": True},
                       {"cpoint_policy": "bogus"}, {"cpoint_policy": 1},
                       {"cpoint_policy": None, "description": None}):
            with self.subTest(kwargs=kwargs):
                result = self.run_tool(**kwargs)
                self.assertFalse(result["success"])
                self.assertEqual("ROUTING_INPUT_INVALID", result["data"]["code"])
        self.assertEqual(0, handle.call_count)
        self.assertEqual([], self.ole.invoke_calls)

    # -- active part required, no auto-connect --------------------------------

    def test_active_part_required_and_no_connect(self):
        handle = self.accessor()
        self.assertEqual("swInvalidFileType",
                         rl.configure_routing_component(SW(Part(kind=2)),
                                                        description="x")["error_name"])
        self.assertEqual("swNoActiveDocument",
                         rl.configure_routing_component(SW(None),
                                                        description="x")["error_name"])
        disconnected = SW(self.doc)
        disconnected.is_connected = False
        self.assertEqual("swConnectionError",
                         rl.configure_routing_component(disconnected,
                                                        description="x")["error_name"])
        self.assertEqual(0, handle.call_count)
        self.assertEqual([], self.views)

    # -- requested persistence + untouched invariants --------------------------

    def test_description_only_persists_and_keeps_policy_and_types(self):
        handle = self.accessor()
        result = self.run_tool(description="NPS2 flange")
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual("ROUTING_CONFIGURED", data["code"])
        self.assertEqual(["description"], data["properties_written"])
        self.assertEqual("NPS2 flange", data["after"]["description"])
        self.assertEqual(1, data["before"]["cpoint_configuration_raw"])
        self.assertEqual(1, data["after"]["cpoint_configuration_raw"])
        self.assertEqual(3, data["after"]["component_type_raw"])
        self.assertEqual(1, data["after"]["component_route_type_raw"])
        self.assertEqual([], data["mismatches"])
        self.assertEqual([], data["invariant_changes"])
        self.assertTrue(data["document_may_be_modified"])
        self.assertFalse(data["automatic_rollback"])
        self.assertFalse(data["saved"])
        self.assertTrue(data["fresh_manager"])
        # fresh manager: two distinct views over the raw manager object
        self.assertEqual(2, handle.call_count)
        self.assertIsNot(self.views[0], self.views[1])
        # explicit DISPATCH_METHOD with the string argument; policy untouched
        self.assertIn(("SetRoutingComponentDescription", 0, _DISPATCH_METHOD, True,
                       ("NPS2 flange",)), self.ole.invoke_calls)
        self.assertNotIn("SetCPointConfiguration",
                         [call[0] for call in self.ole.invoke_calls])

    def test_policy_only_persists_and_keeps_description_and_types(self):
        self.ole.values["description"] = "existing"
        self.accessor()
        result = self.run_tool(cpoint_policy="select")
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual(["cpoint_policy"], data["properties_written"])
        self.assertEqual("select", data["requested"]["cpoint_policy"])
        self.assertEqual(3, data["cpoint_policy_native"])
        self.assertEqual(3, data["after"]["cpoint_configuration_raw"])
        self.assertEqual("existing", data["after"]["description"])
        self.assertEqual([], data["mismatches"])
        self.assertEqual([], data["invariant_changes"])
        self.assertIn(("SetCPointConfiguration", 0, _DISPATCH_METHOD, True, (3,)),
                      self.ole.invoke_calls)
        self.assertNotIn("SetRoutingComponentDescription",
                         [call[0] for call in self.ole.invoke_calls])

    def test_both_fields_persisted_in_one_write(self):
        self.ole.values["description"] = "old"
        self.accessor()
        result = self.run_tool(description="new", cpoint_policy="add_all")
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual(["description", "cpoint_policy"], data["properties_written"])
        self.assertEqual("new", data["after"]["description"])
        self.assertEqual(1, data["after"]["cpoint_configuration_raw"])
        self.assertEqual(
            ["component_type_raw", "component_route_type_raw"],
            [field for field in data["invariances_checked"]
             if field in ("component_type_raw", "component_route_type_raw")])

    def test_all_policies_map_to_native_one_two_three(self):
        for policy, native in (("add_all", 1), ("do_not_add", 2), ("select", 3)):
            with self.subTest(policy=policy):
                self.ole = FakeOle()
                self.accessor()
                result = self.run_tool(cpoint_policy=policy)
                self.assertTrue(result["success"], result)
                self.assertEqual(native, result["data"]["cpoint_policy_native"])
                self.assertEqual(native, result["data"]["after"]["cpoint_configuration_raw"])
                self.assertIn(("SetCPointConfiguration", 0, _DISPATCH_METHOD, True,
                               (native,)), self.ole.invoke_calls)

    def test_empty_description_is_allowed_and_clears(self):
        self.ole.values["description"] = "old description"
        self.accessor()
        result = self.run_tool(description="")
        self.assertTrue(result["success"], result)
        self.assertEqual("", result["data"]["after"]["description"])
        self.assertIn(("SetRoutingComponentDescription", 0, _DISPATCH_METHOD, True,
                       ("",)), self.ole.invoke_calls)

    # -- verification failures: partial evidence, no rollback ------------------

    def test_setter_that_does_not_persist_fails_verification(self):
        self.ole.stall.add("SetCPointConfiguration")
        self.accessor()
        result = self.run_tool(cpoint_policy="do_not_add")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_VERIFICATION_FAILED", data["code"])
        self.assertEqual("cpoint_policy", data["mismatches"][0]["field"])
        self.assertEqual("do_not_add", data["mismatches"][0]["requested"])
        self.assertEqual(2, data["mismatches"][0]["requested_native"])
        self.assertEqual(1, data["mismatches"][0]["readback"])
        self.assertEqual(["cpoint_policy"], data["properties_written"])
        self.assertTrue(data["document_may_be_modified"])
        self.assertFalse(data["automatic_rollback"])
        self.assertFalse(data["saved"])

    def test_untouched_policy_change_is_an_invariant_violation(self):
        self.ole.force_on_set = {"cpoint_configuration_raw": 3}
        self.accessor()
        result = self.run_tool(description="x")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_VERIFICATION_FAILED", data["code"])
        self.assertEqual([], data["mismatches"])
        self.assertTrue(any(change["field"] == "cpoint_configuration_raw"
                            for change in data["invariant_changes"]))
        self.assertTrue(data["document_may_be_modified"])

    def test_component_type_change_is_an_invariant_violation(self):
        self.ole.force_on_set = {"component_type_raw": 9}
        self.accessor()
        result = self.run_tool(description="x")
        self.assertFalse(result["success"])
        self.assertTrue(any(change["field"] == "component_type_raw"
                            for change in result["data"]["invariant_changes"]))

    # -- fail-closed manager / read / setter handling --------------------------

    def test_null_manager_before_fails_closed_without_write(self):
        handle = self.accessor(returns=[None])
        result = self.run_tool(description="x")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_COMPONENT_MANAGER_UNAVAILABLE", data["code"])
        self.assertEqual("null", data["manager_status"])
        self.assertFalse(data["document_may_be_modified"])
        self.assertEqual([], data["properties_written"])
        self.assertEqual([], self.ole.invoke_calls)
        self.assertEqual(1, handle.call_count)

    def test_manager_accessor_error_before_fails_closed(self):
        handle = patch.object(routing, "_routing_component_manager",
                              side_effect=RuntimeError("no accessor"))
        handle.start()
        self.addCleanup(handle.stop)
        result = self.run_tool(description="x")
        self.assertEqual("ROUTING_COMPONENT_MANAGER_UNAVAILABLE", result["data"]["code"])
        self.assertEqual("unavailable", result["data"]["manager_status"])
        self.assertFalse(result["data"]["document_may_be_modified"])

    def test_before_read_error_fails_closed_without_write(self):
        self.ole.errors["GetComponentRouteType"] = RuntimeError("read failed")
        self.accessor()
        result = self.run_tool(description="x")
        data = result["data"]
        self.assertEqual("ROUTING_METADATA_UNREADABLE", data["code"])
        self.assertFalse(data["document_may_be_modified"])
        self.assertEqual([], data["properties_written"])
        self.assertNotIn("SetRoutingComponentDescription",
                         [call[0] for call in self.ole.invoke_calls])
        self.assertTrue(any("GetComponentRouteType" in error for error in data["errors"]))

    def test_setter_exception_reports_partial_mutation_without_rollback(self):
        self.ole.errors["SetCPointConfiguration"] = RuntimeError("com failure")
        handle = self.accessor()
        result = self.run_tool(cpoint_policy="select")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("ROUTING_CONFIGURATION_FAILED", data["code"])
        self.assertEqual([], data["properties_written"])
        self.assertTrue(data["document_may_be_modified"])
        self.assertFalse(data["automatic_rollback"])
        self.assertFalse(data["saved"])
        self.assertTrue(data["errors"])
        self.assertEqual(1, handle.call_count)

    def test_null_fresh_manager_fails_verification(self):
        handle = self.accessor(returns=[FakeManager(self.ole), None])
        result = self.run_tool(description="x")
        data = result["data"]
        self.assertEqual("ROUTING_VERIFICATION_FAILED", data["code"])
        self.assertFalse(data["fresh_manager"])
        self.assertEqual(["description"], data["properties_written"])
        self.assertTrue(data["document_may_be_modified"])
        self.assertEqual(2, handle.call_count)
        self.assertEqual("", data["before"]["description"])  # pre-write snapshot retained
        self.assertIsNone(data["after"])

    def test_after_read_error_fails_verification(self):
        self.ole.error_after_set = {"GetComponentType": RuntimeError("gone")}
        self.accessor()
        result = self.run_tool(description="x")
        data = result["data"]
        self.assertEqual("ROUTING_VERIFICATION_FAILED", data["code"])
        self.assertTrue(data["fresh_manager"])
        self.assertTrue(data["errors"])
        self.assertTrue(data["document_may_be_modified"])

    # -- no nested read handler, reuses the existing accessor ------------------

    def test_does_not_nest_the_public_read_handler(self):
        self.accessor()
        with patch.object(routing, "get_routing_component_metadata",
                          side_effect=AssertionError("must not nest the read handler")):
            result = self.run_tool(description="x")
        self.assertTrue(result["success"], result)

    def test_reuses_existing_manager_accessor_for_the_active_document(self):
        handle = self.accessor()
        result = self.run_tool(description="x")
        self.assertTrue(result["success"], result)
        self.assertEqual(2, handle.call_count)
        for call in handle.call_args_list:
            self.assertIs(call.args[0], self.doc)

    def test_setter_method_uses_explicit_dispatch_flags(self):
        class Ole:
            def GetIDsOfNames(self, name):
                self.name = name
                return 21

            def Invoke(self, *args):
                self.args = args
                return None

        ole = Ole()
        value = rl._setter_method(SimpleNamespace(_oleobj_=ole),
                                  "SetCPointConfiguration", 2)
        self.assertIsNone(value)
        self.assertEqual("SetCPointConfiguration", ole.name)
        self.assertEqual((21, 0, _DISPATCH_METHOD, True, 2), ole.args)


if __name__ == "__main__":
    unittest.main()
