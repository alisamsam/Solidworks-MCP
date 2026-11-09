"""measure_routing_connection_gap: read-only geometric gap between two CPoints.

The tool composes the RT2 component read
(``routing_components.get_component_connection_points``) twice, requires both
reads to succeed with complete coverage and an exact ``feature_name`` match,
and then computes the assembly-frame measurement. These tests pin the
boundaries: the routing gate before any SolidWorks access, closed non-empty
string arguments, the same-connection-point rejection, strict reuse of the RT2
read, pure ``math`` geometry (delta, hypot distance, diameter difference,
normalised direction dot, opposition angle), raw route-type equality only, no
connectivity/mate/compatibility claim, no tolerance or pass/fail parameter, and
honest partial/missing handling that never fabricates a value.
"""

import math
import json
import os
import unittest
from unittest.mock import patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tests.test_routing_components import (
    Assembly,
    BrokenTransform,
    Component,
    Definition,
    Feature,
    IDENTITY,
    Part,
    ROTATED_Z90,
    SW,
    TRANSLATED_X,
    Transform,
)
from solidworks_mcp.tools import routing_components
from solidworks_mcp.tools import routing_measure as rm

TOOL = "measure_routing_connection_gap"
EXPECTED_MEASUREMENT_KEYS = {
    "first", "second", "delta_mm", "distance_mm", "diameter_difference_mm",
    "direction_dot", "opposition_angle_deg", "route_type_equal",
}


def one_point_part(direction=(0.0, 0.0, -1.0), route_type=2, diameter=0.0508):
    """A fitting part with one native connection point, as in the RT2 read."""
    return Part([Feature(name="CPoint1", definition=Definition(
        Direction=tuple(direction), RouteType=route_type, RouteDiameter=diameter))])


def upstream_point(**overrides):
    point = {
        "feature_name": "CPoint1",
        "assembly_position_mm": [0.0, 0.0, -6.35],
        "assembly_direction": [0.0, 0.0, -1.0],
        "nominal_diameter_mm": 50.8,
        "route_type_raw": 2,
        "route_subtype_raw": 20,
    }
    point.update(overrides)
    return point


def upstream_result(points, complete=True, success=None):
    """A canned RT2 read result for the patched upstream boundary."""
    if success is None:
        success = complete
    return {
        "success": success,
        "message": "Upstream read.",
        "error_name": (SwErrors.swSuccess if success else SwErrors.swUnknownError).name,
        "error_code": int(SwErrors.swSuccess if success else SwErrors.swUnknownError),
        "data": {
            "component_name": "canned",
            "component": {"name": "canned", "path": None},
            "part": {"title": "fitting.sldprt", "path": "C:/fixture/fitting.sldprt"},
            "configuration": {"referenced": "Default", "active": "Default", "matched": True},
            "connection_points": list(points),
            "count": len(points),
            "coverage": {"complete": complete, "partial": not complete},
        },
    }


class RoutingMeasureTests(unittest.TestCase):
    def test_overflow_is_reported_as_null_not_infinity(self):
        first = upstream_point(assembly_position_mm=[-1e308, 0, 0], nominal_diameter_mm=-1e308)
        second = upstream_point(assembly_position_mm=[1e308, 0, 0], nominal_diameter_mm=1e308)
        measured, errors = rm._measurement(first, second)
        self.assertIsNone(measured["distance_mm"])
        self.assertIsNone(measured["delta_mm"])
        self.assertIsNone(measured["diameter_difference_mm"])
        self.assertEqual(2, len(errors))
        json.dumps({"success": False, "data": measured, "errors": errors}, allow_nan=False)

    def test_finite_delta_with_overflowing_hypot_is_null(self):
        measured, errors = rm._measurement(
            upstream_point(assembly_position_mm=[0., 0., 0.]),
            upstream_point(assembly_position_mm=[1.7e308, 1.7e308, 1.7e308]))
        self.assertIsNone(measured["distance_mm"])
        self.assertIsNone(measured["delta_mm"])
        self.assertTrue(errors)
        json.dumps({"success": False, "data": measured, "errors": errors}, allow_nan=False)

    def run_tool(self, assembly=None, c1="A-1", p1="CPoint1", c2="B-1", p2="CPoint1",
                 enabled=True, sw=None):
        with patch.object(catalog, "routing_enabled", return_value=enabled):
            return rm.measure_routing_connection_gap(
                sw or SW(assembly), c1, p1, c2, p2)

    def assertVector(self, expected, actual, places=6):
        self.assertIsNotNone(actual, f"expected {expected}, got None")
        self.assertEqual(len(expected), len(actual))
        for left, right in zip(expected, actual):
            self.assertAlmostEqual(left, right, places=places)

    def pair(self, first, second):
        """Assembly with A-1 (first) and B-1 (second) as separate instances."""
        return Assembly([
            Component("A-1", first[0], transform=Transform(first[1])),
            Component("B-1", second[0], transform=Transform(second[1])),
        ])

    # -- registration --------------------------------------------------------

    def test_registered_read_only_com_closed_schema_and_routing_toolset(self):
        entry = registry._TOOLS[TOOL]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertTrue(entry["com"])
        self.assertIsNone(entry["postflight"])
        self.assertEqual(entry["handler"].__module__,
                         "solidworks_mcp.tools.routing_measure")
        schema = entry["tool"].inputSchema
        self.assertEqual(["component1", "point1", "component2", "point2"],
                         schema["required"])
        self.assertFalse(schema["additionalProperties"])
        for name in schema["required"]:
            self.assertEqual("string", schema["properties"][name]["type"])
            self.assertEqual(1, schema["properties"][name]["minLength"])
        self.assertEqual("routing", catalog.toolset_of(TOOL))

    def test_catalog_advertises_the_tool_only_with_routing_permission(self):
        with patch.dict(os.environ, {"SW_MCP_TOOLSETS": "core,routing"}):
            with patch.object(catalog, "routing_enabled", return_value=False):
                self.assertNotIn(TOOL, catalog.advertised_tool_names())
            with patch.object(catalog, "routing_enabled", return_value=True):
                self.assertIn(TOOL, catalog.advertised_tool_names())

    # -- gate first ----------------------------------------------------------

    def test_disabled_gate_rejects_before_any_automation_access(self):
        class Forbidden(SW):
            def __init__(self):
                pass

            @property
            def is_connected(self):
                raise AssertionError("the routing gate must run first")

            @property
            def app(self):
                raise AssertionError("the routing gate must run first")

        result = self.run_tool(enabled=False, sw=Forbidden())
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_invalid_arguments_rejected_before_component_read(self):
        cases = {
            "component1_empty": {"c1": ""},
            "point1_empty": {"p1": ""},
            "component2_empty": {"c2": ""},
            "point2_empty": {"p2": ""},
            "component1_not_string": {"c1": None},
            "point2_not_string": {"p2": 5},
        }
        for label, overrides in cases.items():
            with self.subTest(label=label):
                assembly = Assembly([Component("A-1", one_point_part())])
                result = self.run_tool(assembly, **overrides)
                self.assertFalse(result["success"])
                self.assertEqual("INVALID_ARGUMENTS", result["data"]["code"])
                self.assertEqual([], assembly.top_only_calls)

    def test_same_component_and_point_is_rejected_without_a_read(self):
        assembly = Assembly([Component("A-1", one_point_part())])
        result = self.run_tool(assembly, c1="A-1", p1="CPoint1",
                               c2="A-1", p2="CPoint1")
        self.assertFalse(result["success"])
        self.assertEqual("SAME_CONNECTION_POINT", result["data"]["code"])
        self.assertEqual([], assembly.top_only_calls)

    def test_two_points_on_the_same_component_are_allowed(self):
        part = Part([Feature(name="CPoint1", definition=Definition()),
                     Feature(name="CPoint2", definition=Definition(
                         Location=(0.05, 0.0, 0.0), Direction=(1.0, 0.0, 0.0)))])
        assembly = Assembly([Component("A-1", part)])
        result = self.run_tool(assembly, c1="A-1", p1="CPoint1",
                               c2="A-1", p2="CPoint2")
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(math.hypot(50.0, 0.0, -6.35),
                               result["data"]["measurement"]["distance_mm"])

    # -- exact geometry ------------------------------------------------------

    def test_exact_gap_100mm_delta_and_references(self):
        part = one_point_part()
        assembly = self.pair((part, IDENTITY), (part, TRANSLATED_X))
        result = self.run_tool(assembly, c1="A-1", p1="CPoint1",
                               c2="B-1", p2="CPoint1")
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual("active_assembly", data["coordinate_system"])
        self.assertEqual("mm", data["length_unit"])

        measurement = data["measurement"]
        self.assertEqual(EXPECTED_MEASUREMENT_KEYS, set(measurement))
        self.assertVector([100.0, 0.0, 0.0], measurement["delta_mm"])
        self.assertAlmostEqual(100.0, measurement["distance_mm"], places=6)
        self.assertAlmostEqual(0.0, measurement["diameter_difference_mm"], places=6)
        self.assertAlmostEqual(1.0, measurement["direction_dot"], places=9)
        self.assertAlmostEqual(180.0, measurement["opposition_angle_deg"], places=6)
        self.assertTrue(measurement["route_type_equal"])
        self.assertVector([0.0, 0.0, -6.35], measurement["first"]["assembly_position_mm"])
        self.assertVector([100.0, 0.0, -6.35], measurement["second"]["assembly_position_mm"])
        self.assertEqual(2, measurement["first"]["route_type_raw"])
        self.assertEqual(2, measurement["second"]["route_type_raw"])
        self.assertEqual(20, measurement["first"]["route_subtype_raw"])
        self.assertAlmostEqual(50.8, measurement["first"]["nominal_diameter_mm"])

        # references and configuration evidence are carried over from the RT2 read
        first = data["components"]["first"]
        self.assertEqual("A-1", first["component_name"])
        self.assertEqual("CPoint1", first["point_name"])
        self.assertEqual("C:/fixture/fitting.sldprt", first["part"]["path"])
        self.assertEqual("fitting.sldprt", first["part"]["title"])
        self.assertEqual({"referenced": "Default", "active": "Default", "matched": True},
                         first["configuration"])
        self.assertTrue(first["coverage_complete"])
        self.assertEqual("B-1", data["components"]["second"]["component_name"])
        self.assertEqual([], data["errors"])

    def test_opposite_directions_give_zero_degrees(self):
        assembly = self.pair((one_point_part(direction=(0.0, 0.0, -1.0)), IDENTITY),
                             (one_point_part(direction=(0.0, 0.0, 1.0)), TRANSLATED_X))
        result = self.run_tool(assembly)
        self.assertTrue(result["success"], result)
        measurement = result["data"]["measurement"]
        self.assertAlmostEqual(-1.0, measurement["direction_dot"], places=9)
        self.assertAlmostEqual(0.0, measurement["opposition_angle_deg"], places=6)

    def test_same_directions_give_180_degrees(self):
        assembly = self.pair((one_point_part(direction=(0.0, 0.0, -1.0)), IDENTITY),
                             (one_point_part(direction=(0.0, 0.0, -1.0)), TRANSLATED_X))
        result = self.run_tool(assembly)
        self.assertTrue(result["success"], result)
        measurement = result["data"]["measurement"]
        self.assertAlmostEqual(1.0, measurement["direction_dot"], places=9)
        self.assertAlmostEqual(180.0, measurement["opposition_angle_deg"], places=6)

    def test_rotated_instance_uses_assembly_directions_and_positions(self):
        # local +X of the rotated instance maps to assembly +Y (Rz(90), row-vector)
        assembly = self.pair((one_point_part(direction=(1.0, 0.0, 0.0)), IDENTITY),
                             (one_point_part(direction=(1.0, 0.0, 0.0)), ROTATED_Z90))
        result = self.run_tool(assembly)
        self.assertTrue(result["success"], result)
        measurement = result["data"]["measurement"]
        self.assertVector([1.0, 0.0, 0.0], measurement["first"]["assembly_direction"])
        self.assertVector([0.0, 1.0, 0.0], measurement["second"]["assembly_direction"])
        self.assertAlmostEqual(0.0, measurement["direction_dot"], places=9)
        self.assertAlmostEqual(90.0, measurement["opposition_angle_deg"], places=6)
        self.assertAlmostEqual(100.0, measurement["distance_mm"], places=6)

    def test_diameter_difference_is_second_minus_first(self):
        assembly = self.pair((one_point_part(diameter=0.0508), IDENTITY),
                             (one_point_part(diameter=0.0254), TRANSLATED_X))
        result = self.run_tool(assembly)
        self.assertTrue(result["success"], result)
        measurement = result["data"]["measurement"]
        self.assertAlmostEqual(50.8, measurement["first"]["nominal_diameter_mm"])
        self.assertAlmostEqual(25.4, measurement["second"]["nominal_diameter_mm"])
        self.assertAlmostEqual(-25.4, measurement["diameter_difference_mm"], places=6)

    def test_route_type_equality_is_a_raw_int_comparison(self):
        assembly = self.pair((one_point_part(route_type=2), IDENTITY),
                             (one_point_part(route_type=1), TRANSLATED_X))
        result = self.run_tool(assembly)
        self.assertTrue(result["success"], result)
        measurement = result["data"]["measurement"]
        self.assertFalse(measurement["route_type_equal"])
        self.assertEqual(2, measurement["first"]["route_type_raw"])
        self.assertEqual(1, measurement["second"]["route_type_raw"])

    # -- no connectivity / pass-fail claim -----------------------------------

    def test_result_reports_no_connectivity_or_pass_fail_status(self):
        assembly = self.pair((one_point_part(), IDENTITY), (one_point_part(), TRANSLATED_X))
        result = self.run_tool(assembly)
        self.assertTrue(result["success"], result)
        self.assertNotIn("connected", result["data"])
        measurement = result["data"]["measurement"]
        for forbidden in ("connected", "compatible", "pass", "tolerance",
                          "mate", "native_route"):
            self.assertNotIn(forbidden, measurement)

    # -- strict reuse of the RT2 read ----------------------------------------

    def test_unknown_component_preserves_upstream_reason(self):
        assembly = Assembly([Component("A-1", one_point_part())])
        result = self.run_tool(assembly, c2="MISSING-1")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("COMPONENT_READ_FAILED", data["code"])
        self.assertEqual("second", data["source"])
        self.assertEqual("COMPONENT_NOT_FOUND", data["upstream"]["code"])
        self.assertEqual("swInvalidInput", data["upstream"]["error_name"])
        self.assertIn("MISSING-1", result["message"])
        self.assertIn("MISSING-1", data["upstream"]["message"])
        # the upstream error class is preserved on the measure result as well
        self.assertEqual("swInvalidInput", result["error_name"])
        # the first component read enumerates the assembly, then the second does too
        self.assertEqual([True, True], assembly.top_only_calls)

    def test_unloaded_part_read_failure_preserves_upstream_reason(self):
        assembly = Assembly([Component("A-1", None)])
        result = self.run_tool(assembly)
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("COMPONENT_READ_FAILED", data["code"])
        self.assertEqual("first", data["source"])
        self.assertEqual("PART_UNAVAILABLE", data["upstream"]["code"])
        self.assertIn("not loaded", data["upstream"]["message"])
        self.assertNotIn("measurement", data)
        # the second connection is never read once the first read fails
        self.assertEqual([True], assembly.top_only_calls)

    def test_partial_upstream_read_is_rejected_not_fabricated(self):
        component = Component("A-1", one_point_part(), transform=BrokenTransform())
        assembly = Assembly([component, Component("B-1", one_point_part())])
        result = self.run_tool(assembly)
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("COMPONENT_READ_FAILED", data["code"])
        self.assertFalse(data["upstream"]["coverage_complete"])
        self.assertNotIn("measurement", data)

    def test_incomplete_coverage_on_a_successful_read_is_rejected(self):
        with patch.object(catalog, "routing_enabled", return_value=True), \
                patch.object(routing_components, "get_component_connection_points",
                             return_value=upstream_result([], complete=False, success=True)):
            result = rm.measure_routing_connection_gap(
                SW(Assembly()), "A-1", "CPoint1", "B-1", "CPoint1")
        self.assertFalse(result["success"])
        self.assertEqual("INCOMPLETE_COVERAGE", result["data"]["code"])
        self.assertNotIn("measurement", result["data"])

    def test_missing_point_name_is_not_found(self):
        assembly = Assembly([Component("A-1", one_point_part()),
                             Component("B-1", one_point_part())])
        result = self.run_tool(assembly, p1="CPoint9")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("POINT_NOT_FOUND", data["code"])
        self.assertEqual("first", data["source"])
        self.assertEqual(["CPoint1"], data["available_points"])
        self.assertNotIn("measurement", data)

    def test_point_name_match_is_exact_and_case_sensitive(self):
        assembly = Assembly([Component("A-1", one_point_part()),
                             Component("B-1", one_point_part())])
        result = self.run_tool(assembly, p1="cpoint1")
        self.assertEqual("POINT_NOT_FOUND", result["data"]["code"])

    # -- degenerate native data is never fabricated --------------------------

    def test_zero_direction_is_rejected_by_the_upstream_read(self):
        assembly = self.pair((one_point_part(direction=(0.0, 0.0, 0.0)), IDENTITY),
                             (one_point_part(), TRANSLATED_X))
        result = self.run_tool(assembly)
        self.assertFalse(result["success"])
        self.assertEqual("COMPONENT_READ_FAILED", result["data"]["code"])
        self.assertFalse(result["data"]["upstream"]["coverage_complete"])
        self.assertNotIn("measurement", result["data"])

    def test_zero_length_direction_stops_at_the_measurement_guard(self):
        zero = upstream_point(assembly_direction=[0.0, 0.0, 0.0])
        valid = upstream_point()
        with patch.object(catalog, "routing_enabled", return_value=True), \
                patch.object(routing_components, "get_component_connection_points",
                             side_effect=[upstream_result([zero]),
                                          upstream_result([valid])]):
            result = rm.measure_routing_connection_gap(
                SW(Assembly()), "A-1", "CPoint1", "B-1", "CPoint1")
        self.assertFalse(result["success"])
        self.assertTrue(result["data"]["errors"])
        self.assertTrue(any("direction" in error for error in result["data"]["errors"]))
        # the incomplete measurement is reported honestly, never fabricated
        self.assertIsNone(result["data"]["measurement"]["direction_dot"])
        self.assertIsNone(result["data"]["measurement"]["opposition_angle_deg"])


if __name__ == "__main__":
    unittest.main()
