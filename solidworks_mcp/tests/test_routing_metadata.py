import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.tools import routing
from solidworks_mcp.tests.test_routing_points import SW, Part


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.doc = Part()
        self.doc.ConfigurationManager = SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name="Default"))
        self.values = {"GetComponentType": 3, "GetComponentRouteType": 1,
                       "GetCPointConfiguration": 1, "GetRoutingComponentDescription": ""}
        self.gate = patch.object(catalog, "routing_enabled", return_value=True)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def run_tool(self):
        def member(manager, name):
            value = self.values[name]
            if isinstance(value, Exception): raise value
            return value
        with patch.object(routing, "_routing_component_manager", return_value=object()), \
                patch.object(routing, "_metadata_method", side_effect=member):
            return routing.get_routing_component_metadata(SW(self.doc))

    def test_native_metadata_values_and_independent_enum_namespace(self):
        result = self.run_tool()
        self.assertTrue(result["success"], result)
        self.assertEqual(3, result["data"]["component_type_raw"])
        self.assertEqual(1, result["data"]["component_route_type_raw"])
        self.assertEqual(1, result["data"]["cpoint_configuration_raw"])
        self.assertEqual("", result["data"]["description"])

    def test_field_exception_preserves_other_values(self):
        self.values["GetComponentType"] = RuntimeError("read failed")
        result = self.run_tool()
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"]["component_type_raw"])
        self.assertEqual(1, result["data"]["component_route_type_raw"])

    def test_wrong_native_type_not_cast(self):
        for value in (True, "1", None):
            self.values["GetComponentRouteType"] = value
            result = self.run_tool()
            self.assertFalse(result["success"])
            self.assertIsNone(result["data"]["component_route_type_raw"])

    def test_null_manager_not_fake_metadata(self):
        with patch.object(routing, "_routing_component_manager", return_value=None):
            result = routing.get_routing_component_metadata(SW(self.doc))
        self.assertFalse(result["success"])
        self.assertEqual("null", result["data"]["manager_status"])
        self.assertIsNone(result["data"]["component_type_raw"])

    def test_manager_exception_has_unavailable_status(self):
        with patch.object(routing, "_routing_component_manager", side_effect=RuntimeError("no accessor")):
            result = routing.get_routing_component_metadata(SW(self.doc))
        self.assertFalse(result["success"])
        self.assertEqual("unavailable", result["data"]["manager_status"])

    def test_gate_first_and_dispatch_rejects_before_validation(self):
        with patch.object(catalog, "routing_enabled", return_value=False):
            sw = SW(None)
            del sw.is_connected
            self.assertEqual("ROUTING_DISABLED", routing.get_routing_component_metadata(sw)["data"]["code"])
            result = registry.execute("get_routing_component_metadata", sw, {"bad": 1}).result
            self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_part_only_and_no_connect(self):
        self.assertEqual("swInvalidFileType", routing.get_routing_component_metadata(SW(Part(kind=2)))["error_name"])
        sw = SW(self.doc)
        sw.is_connected = False
        self.assertEqual("swConnectionError", routing.get_routing_component_metadata(sw)["error_name"])

    def test_explicit_method_invocation_flags(self):
        class Ole:
            def GetIDsOfNames(self, name): return 6
            def Invoke(self, *args):
                self.args = args
                return 3
        ole = Ole()
        value = routing._metadata_method(SimpleNamespace(_oleobj_=ole), "GetComponentType")
        self.assertEqual(3, value)
        self.assertEqual((6, 0, 1, True), ole.args)

    def test_accessor_uses_document_extension_and_method_flags(self):
        class Ole:
            def GetIDsOfNames(self, name):
                self.name = name
                return 217
            def Invoke(self, *args):
                self.args = args
                return "native-dispatch"
        ole = Ole()
        self.doc.Extension = SimpleNamespace(_oleobj_=ole)
        with patch("win32com.client.Dispatch", return_value="wrapped") as wrap:
            self.assertEqual("wrapped", routing._routing_component_manager(self.doc))
        self.assertEqual("GetRoutingComponentManager", ole.name)
        self.assertEqual((217, 0, 1, True), ole.args)
        wrap.assert_called_once_with("native-dispatch")


if __name__ == "__main__": unittest.main()
