"""RT1 inspect_routing_context: bounded native read, gate first, no inference.

The tool reads only the active assembly's identity plus two zero-argument
members (``IsRouteAssembly`` and ``GetRouteManager``). These tests pin the
boundaries the brief requires: config gate before any document access, no
document/selection/add-in mutation, route manager observed as an object only
(no member called), null vs exception kept distinct from ``false``, and route
segments explicitly not inspected.
"""

import unittest
from unittest.mock import Mock, patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, _load
from solidworks_mcp.tools import routing

_SCHEMA = {"type": "object", "properties": {}, "required": [],
           "additionalProperties": False}

# The exact member sequence the handler is allowed to read on the assembly.
_ALLOWED_READS = ["GetType", "IsRouteAssembly", "GetRouteManager",
                  "GetTitle", "GetPathName"]


class _RouteManager:
    """Availability is the only permitted observation: members must not run."""

    def __getattr__(self, name):
        raise AssertionError(f"route manager member must not be read: {name}")


class _Assembly:
    """Document fake; any member outside the allowed set fails the test."""

    def __init__(self, document_type=2, native=True,
                 native_error=None, manager=None, manager_error=None,
                 title="routeassy1.sldasm", path="C:/samples/routeassy1.sldasm"):
        self.reads = []
        self.document_type = document_type
        self.native = native
        self.native_error = native_error
        self.manager = manager
        self.manager_error = manager_error
        self.title = title
        self.path = path
        self._oleobj_ = self

    def GetIDsOfNames(self, name):
        assert name == "GetRouteManager", name
        return 112

    def Invoke(self, dispid, lcid, flags, result):
        assert (dispid, lcid, flags, result) == (112, 0, 1, True)
        return self.GetRouteManager()

    def GetType(self):
        self.reads.append("GetType")
        return self.document_type

    def GetTitle(self):
        self.reads.append("GetTitle")
        return self.title

    def GetPathName(self):
        self.reads.append("GetPathName")
        return self.path

    def IsRouteAssembly(self):
        self.reads.append("IsRouteAssembly")
        if self.native_error:
            raise RuntimeError(self.native_error)
        return self.native

    def GetRouteManager(self):
        self.reads.append("GetRouteManager")
        if self.manager_error:
            raise RuntimeError(self.manager_error)
        return self.manager

    def __getattr__(self, name):
        raise AssertionError(f"inspect_routing_context must not touch assembly.{name}")


class _Sw:
    """Automation fake; direct app read and _result only, never auto-connect."""

    def __init__(self, doc=None, error=None):
        self.is_connected = True
        self.doc_reads = 0
        self._doc = doc
        self._error = error

    @property
    def app(self):
        return self

    @property
    def ActiveDoc(self):
        self.doc_reads += 1
        if isinstance(self._error, Exception):
            raise self._error
        return self._doc

    def _result(self, success, message, error_code=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": error_code.name, "data": data or {}}

    def __getattr__(self, name):
        raise AssertionError(f"inspect_routing_context must not touch sw.{name}")


def _no_active_document():
    return _Sw(None, {"success": False, "message": "No document open.",
                      "error_name": "swNoActiveDocument",
                      "error_code": int(SwErrors.swNoActiveDocument)})


class RoutingContextTests(unittest.TestCase):
    def _run(self, sw, enabled=True):
        with patch.object(catalog, "routing_enabled", return_value=enabled):
            return routing.inspect_routing_context(sw)

    # -- registration --------------------------------------------------------

    def test_registered_read_only_with_com_and_closed_schema(self):
        _load()
        entry = _TOOLS["inspect_routing_context"]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertTrue(entry["com"])
        self.assertIsNone(entry["postflight"])
        self.assertEqual(entry["tool"].inputSchema, _SCHEMA)
        self.assertEqual(entry["handler"].__module__, "solidworks_mcp.tools.routing")

    def test_registered_tool_belongs_to_the_routing_toolset(self):
        self.assertEqual("routing", catalog.toolset_of("inspect_routing_context"))

    # -- gate first ----------------------------------------------------------

    def test_disabled_gate_rejects_before_any_document_access(self):
        sw = _Sw(_Assembly())
        result = self._run(sw, enabled=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "ROUTING_DISABLED")
        self.assertEqual(result["error_name"], "swInvalidInput")
        self.assertEqual(sw.doc_reads, 0)

    def test_registry_rejects_before_handler_when_disabled(self):
        _load()
        handler = Mock()
        entry = dict(_TOOLS["inspect_routing_context"], handler=handler)
        sw = Mock()
        sw._result.side_effect = lambda success, message, error, data=None: {
            "success": success, "message": message, "error_code": int(error),
            "error_name": error.name, "data": data or {}}
        with patch.dict(_TOOLS, {"inspect_routing_context": entry}), \
                patch.object(catalog, "toolset_of", return_value="routing"), \
                patch.object(catalog, "routing_enabled", return_value=False):
            result = registry.execute("inspect_routing_context", sw, {}).result
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "ROUTING_DISABLED")
        handler.assert_not_called()
        sw.bind_active_document.assert_not_called()

    # -- document validation -------------------------------------------------

    def test_not_connected_does_not_auto_connect_or_read_document(self):
        sw = _Sw(_Assembly())
        sw.is_connected = False
        result = self._run(sw)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_name"], "swConnectionError")
        self.assertEqual(sw.doc_reads, 0)

    def test_connection_loss_during_document_read_never_reconnects(self):
        sw = _Sw(_Assembly(), error=RuntimeError("connection lost during ActiveDoc read"))
        result = self._run(sw)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_name"], "swConnectionError")
        self.assertEqual(sw.doc_reads, 1)

    def test_no_active_document_reports_error_without_com_reads(self):
        sw = _no_active_document()
        result = self._run(sw)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_name"], "swNoActiveDocument")
        self.assertEqual(sw.doc_reads, 1)

    def test_wrong_document_type_rejected_before_routing_reads(self):
        asm = _Assembly(document_type=1)
        result = self._run(_Sw(asm))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_name"], "swInvalidFileType")
        self.assertEqual(asm.reads, ["GetType"])

    def test_drawing_document_type_rejected(self):
        asm = _Assembly(document_type=3)
        result = self._run(_Sw(asm))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_name"], "swInvalidFileType")

    # -- native identity -----------------------------------------------------

    def test_native_route_assembly_true_and_false_are_preserved(self):
        for expected in (True, False):
            with self.subTest(native=expected):
                asm = _Assembly(native=expected)
                result = self._run(_Sw(asm))
                self.assertTrue(result["success"], result)
                self.assertIs(result["data"]["native_route_assembly"], expected)
                self.assertEqual(result["data"]["native_route_status"], "read")

    def test_document_context_is_reported_natively(self):
        result = self._run(_Sw(_Assembly(title="routeassy1.sldasm",
                                         path="C:/samples/routeassy1.sldasm")))
        document = result["data"]["document"]
        self.assertEqual(document["title"], "routeassy1.sldasm")
        self.assertEqual(document["path"], "C:/samples/routeassy1.sldasm")
        self.assertEqual(document["document_type"], 2)
        self.assertEqual(document["document_type_name"], "assembly")
        self.assertTrue(document["is_assembly"])

    # -- route manager: availability only ------------------------------------

    def test_null_route_manager_is_a_diagnostic_read_success(self):
        result = self._run(_Sw(_Assembly(manager=None)))
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertIs(data["route_manager_available"], False)
        self.assertEqual(data["route_manager_status"], "null")
        self.assertEqual(data["errors"], [])
        self.assertIn("not proof that the Routing add-in is disabled",
                      " ".join(data["notes"]))

    def test_manager_object_is_availability_only_no_members_invoked(self):
        result = self._run(_Sw(_Assembly(manager=_RouteManager())))
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertIs(data["route_manager_available"], True)
        self.assertEqual(data["route_manager_status"], "object")
        self.assertEqual(data["errors"], [])

    # -- null vs exception ---------------------------------------------------

    def test_native_read_exception_is_unavailable_not_false(self):
        asm = _Assembly(native_error="proxy refused")
        result = self._run(_Sw(asm))
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertIsNone(data["native_route_assembly"])
        self.assertEqual(data["native_route_status"], "unavailable")
        self.assertEqual(result["error_name"], "swUnknownError")
        self.assertTrue(any("IsRouteAssembly unavailable" in e for e in data["errors"]))

    def test_manager_read_exception_is_unavailable_not_false(self):
        asm = _Assembly(native=True, manager_error="no dispatch")
        result = self._run(_Sw(asm))
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertIsNone(data["route_manager_available"])
        self.assertEqual(data["route_manager_status"], "unavailable")
        self.assertIs(data["native_route_assembly"], True)  # still reported
        self.assertTrue(any("GetRouteManager unavailable" in e for e in data["errors"]))

    def test_non_boolean_native_value_is_unavailable_not_false(self):
        result = self._run(_Sw(_Assembly(native=None)))
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"]["native_route_assembly"])
        self.assertEqual(result["data"]["native_route_status"], "unavailable")

    # -- bounded reads: no mutation, no segments -----------------------------

    def test_reads_exactly_the_declared_members(self):
        asm = _Assembly(manager=_RouteManager())
        self._run(_Sw(asm))
        self.assertEqual(asm.reads, _ALLOWED_READS)

    def test_property_style_binding_is_normalised_too(self):
        """The COM helper must read attributes and methods alike (no CastTo)."""
        class _PropertyAssembly:
            GetType = 2
            GetTitle = "prop.sldasm"
            GetPathName = "C:/prop.sldasm"
            IsRouteAssembly = True
            GetRouteManager = None
            _oleobj_ = _Assembly(manager=None)

        result = self._run(_Sw(_PropertyAssembly()))
        self.assertTrue(result["success"], result)
        self.assertIs(result["data"]["native_route_assembly"], True)
        self.assertIs(result["data"]["route_manager_available"], False)
        self.assertEqual(result["data"]["document"]["title"], "prop.sldasm")

    def test_segments_and_selection_are_never_inspected(self):
        asm = _Assembly(manager=_RouteManager())
        result = self._run(_Sw(asm))
        data = result["data"]
        self.assertIs(data["segments_inspected"], False)
        self.assertNotIn("segment_count", data)
        self.assertNotIn("segment_ids", data)
        self.assertNotIn("GetAllRouteSegmentCount", asm.reads)
        self.assertNotIn("GetAllRouteSegmentIDs", asm.reads)
        self.assertNotIn("ClearSelection2", asm.reads)
        self.assertNotIn("SelectionManager", asm.reads)

    def test_rt0_module_stays_com_free_after_rt1_runs(self):
        self._run(_Sw(_Assembly()))
        self.assertFalse(hasattr(routing, "com"))
        self.assertNotIn("comutil", routing.__dict__)


if __name__ == "__main__":
    unittest.main()
