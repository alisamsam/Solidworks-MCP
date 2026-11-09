import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools import routing


class Definition:
    Location = (0.0, 0.0, -0.00635)
    Direction = (0.0, 0.0, -1.0)
    RouteDiameter = 0.0508
    StubLength = 0.0
    RouteType = 2
    RouteSubType = 20
    PortID = ""

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected definition access: {name}")


class Feature:
    def __init__(self, name="CPoint1", kind="ConnectionPoint", definition=None):
        self.Name = name
        self.kind = kind
        self.definition = definition
        self.next = None

    def GetTypeName2(self): return self.kind
    def GetDefinition(self): return self.definition
    def GetNextFeature(self): return self.next

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected feature access: {name}")


class Part:
    def __init__(self, features=(), kind=1):
        self.features = list(features)
        self.kind = kind
        for left, right in zip(self.features, self.features[1:]): left.next = right

    def GetType(self): return self.kind
    def GetTitle(self): return "fitting"
    def GetPathName(self): return "C:/fixture/fitting.sldprt"
    def FirstFeature(self): return self.features[0] if self.features else None

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected document access: {name}")


class SW:
    def __init__(self, document):
        self.is_connected = True
        self.app = SimpleNamespace(ActiveDoc=document)

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data or {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


class RoutingPointTests(unittest.TestCase):
    def run_tool(self, part, enabled=True):
        with patch.object(catalog, "routing_enabled", return_value=enabled):
            return routing.list_routing_connection_points(SW(part))

    def point(self, definition=None):
        return Feature(definition=definition or Definition())

    def test_registration_and_schema(self):
        registry.registered_tools()
        entry = registry._TOOLS["list_routing_connection_points"]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertTrue(entry["com"])
        self.assertFalse(entry["tool"].inputSchema["additionalProperties"])
        self.assertEqual("routing", catalog.toolset_of("list_routing_connection_points"))

    def test_gate_before_any_automation_access(self):
        class Disabled(SW):
            @property
            def is_connected(self): raise AssertionError("gate must be first")
        with patch.object(catalog, "routing_enabled", return_value=False):
            result = routing.list_routing_connection_points(Disabled.__new__(Disabled))
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_conversion_and_raw_enums(self):
        result = self.run_tool(Part([self.point()]))
        self.assertTrue(result["success"], result)
        point = result["data"]["connection_points"][0]
        self.assertAlmostEqual(-6.35, point["position_mm"][2])
        self.assertEqual([0.0, 0.0, -1.0], point["direction"])
        self.assertAlmostEqual(50.8, point["nominal_diameter_mm"])
        self.assertEqual(0.0, point["stub_length_mm"])
        self.assertEqual(2, point["route_type_raw"])
        self.assertEqual(20, point["route_subtype_raw"])
        self.assertEqual("", point["port_id"])
        self.assertTrue(result["data"]["coverage"]["complete"])

    def test_empty_part_complete_not_routing_readiness(self):
        result = self.run_tool(Part())
        self.assertTrue(result["success"])
        self.assertEqual([], result["data"]["connection_points"])
        self.assertTrue(result["data"]["coverage"]["complete"])

    def test_skips_rpoints_and_regular_features(self):
        result = self.run_tool(Part([Feature(kind="RoutePoint"), Feature(kind="RefPlane"), self.point()]))
        self.assertEqual(1, result["data"]["count"])
        self.assertEqual(3, result["data"]["coverage"]["visited_features"])

    def test_multiple_points_keep_their_distinct_identity_and_data(self):
        second = Definition()
        second.Location = (0.1, 0.0, 0.0)
        second.Direction = (1.0, 0.0, 0.0)
        result = self.run_tool(Part([self.point(), Feature(name="CPoint2", definition=second)]))
        self.assertTrue(result["success"])
        points = result["data"]["connection_points"]
        self.assertEqual(["CPoint1", "CPoint2"], [p["feature_name"] for p in points])
        self.assertEqual([100.0, 0.0, 0.0], points[1]["position_mm"])
        self.assertEqual([1.0, 0.0, 0.0], points[1]["direction"])

    def test_null_definition_reports_incomplete_not_empty(self):
        result = self.run_tool(Part([Feature()]))
        self.assertFalse(result["success"])
        self.assertEqual(1, result["data"]["count"])
        self.assertFalse(result["data"]["connection_points"][0]["read_complete"])
        point = result["data"]["connection_points"][0]
        for key in ("position_mm", "direction", "nominal_diameter_mm", "stub_length_mm",
                    "route_type_raw", "route_subtype_raw", "port_id"):
            self.assertIn(key, point)
            self.assertIsNone(point[key])

    def test_raising_definition_has_same_null_field_shape(self):
        class Broken(Feature):
            def GetDefinition(self): raise RuntimeError("definition unavailable")
        result = self.run_tool(Part([Broken()]))
        self.assertFalse(result["success"])
        point = result["data"]["connection_points"][0]
        for key in ("position_mm", "direction", "nominal_diameter_mm", "stub_length_mm",
                    "route_type_raw", "route_subtype_raw", "port_id"):
            self.assertIn(key, point)
            self.assertIsNone(point[key])

    def test_unit_conversion_overflow_returns_null_not_infinity(self):
        definition = Definition()
        definition.RouteDiameter = 1e308
        definition.Location = (1e308, 0, 0)
        result = self.run_tool(Part([self.point(definition)]))
        self.assertFalse(result["success"])
        point = result["data"]["connection_points"][0]
        self.assertIsNone(point["nominal_diameter_mm"])
        self.assertIsNone(point["position_mm"])

    def test_bad_fields_are_null_not_fabricated_values(self):
        definition = Definition()
        definition.Location = (0.0, float("nan"), 0.0)
        definition.RouteType = "2"
        definition.StubLength = None
        result = self.run_tool(Part([self.point(definition)]))
        self.assertFalse(result["success"])
        point = result["data"]["connection_points"][0]
        for key in ("position_mm", "route_type_raw", "stub_length_mm"):
            self.assertIsNone(point[key])
        self.assertAlmostEqual(50.8, point["nominal_diameter_mm"])

    def test_invalid_vectors(self):
        for value in (None, [1, 2], [True, 0, 1], [0, float("inf"), 1]):
            with self.subTest(value=value):
                definition = Definition()
                definition.Direction = value
                result = self.run_tool(Part([self.point(definition)]))
                self.assertFalse(result["success"])
                self.assertIsNone(result["data"]["connection_points"][0]["direction"])

    def test_traversal_limit_is_explicit(self):
        result = self.run_tool(Part([Feature(kind="RefPlane") for _ in range(1001)]))
        coverage = result["data"]["coverage"]
        self.assertEqual(1000, coverage["visited_features"])
        self.assertTrue(coverage["truncated"])
        self.assertFalse(coverage["complete"])

    def test_traversal_error_is_not_complete(self):
        class Broken(Feature):
            def GetNextFeature(self): raise RuntimeError("proxy lost")
        result = self.run_tool(Part([Broken(definition=Definition())]))
        self.assertFalse(result["success"])
        self.assertFalse(result["data"]["coverage"]["complete"])
        self.assertEqual(1, result["data"]["count"])

    def test_wrong_document_type(self):
        result = self.run_tool(Part(kind=2))
        self.assertEqual("swInvalidFileType", result["error_name"])

    def test_no_document(self):
        result = self.run_tool(None)
        self.assertEqual("swNoActiveDocument", result["error_name"])

    def test_disconnected_never_auto_connects(self):
        sw = SW(Part())
        sw.is_connected = False
        with patch.object(catalog, "routing_enabled", return_value=True):
            result = routing.list_routing_connection_points(sw)
        self.assertEqual("swConnectionError", result["error_name"])


if __name__ == "__main__":
    unittest.main()
