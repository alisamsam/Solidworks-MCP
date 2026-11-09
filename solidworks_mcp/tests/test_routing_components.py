"""get_component_connection_points: bounded, read-only component CPoint read.

The tool resolves exactly one direct top-level component by its exact Name2,
reads its already-loaded referenced part's top-level ConnectionPoint features
through ``routing._connection_point_data`` and derives the assembly placement
with the repository's verified transform formula. These tests pin the
boundaries: routing gate before any automation access, no auto-connect, part
document type validation, no resolve/edit/selection mutation, explicit errors
instead of an empty count, bounded top-level/feature traversal, honest
per-point partial coverage, and no fabricated assembly geometry.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools import routing_components as rc

IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0.0, 0.0, 0.0, 1, 0, 0, 0]
TRANSLATED_X = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0.1, 0.0, 0.0, 1, 0, 0, 0]
# Rz(+90 deg) in the repo's row-vector convention (assembly._euler_to_matrix).
ROTATED_Z90 = [0, 1, 0, -1, 0, 0, 0, 0, 1, 0.1, 0.0, 0.0, 1, 0, 0, 0]


class Definition:
    def __init__(self, **overrides):
        self.Location = (0.0, 0.0, -0.00635)
        self.Direction = (0.0, 0.0, -1.0)
        self.RouteDiameter = 0.0508
        self.StubLength = 0.0
        self.RouteType = 2
        self.RouteSubType = 20
        self.PortID = ""
        for key, value in overrides.items():
            setattr(self, key, value)

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


class Configuration:
    def __init__(self, name):
        self.Name = name

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected configuration access: {name}")


class ConfigurationManager:
    def __init__(self, active):
        self.ActiveConfiguration = Configuration(active)

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected configuration manager access: {name}")


class BrokenManager:
    def __getattr__(self, name):
        raise RuntimeError("configuration manager unavailable")


class NullActiveManager:
    ActiveConfiguration = None


_UNSET = object()


class Part:
    def __init__(self, features=(), kind=1, title="fitting.sldprt",
                 path="C:/fixture/fitting.sldprt", configuration="Default",
                 configuration_manager=_UNSET):
        self.features = list(features)
        self.kind = kind
        self.title = title
        self.path = path
        self.first_feature_calls = 0
        self.ConfigurationManager = (
            ConfigurationManager(configuration)
            if configuration_manager is _UNSET else configuration_manager
        )
        for left, right in zip(self.features, self.features[1:]):
            left.next = right

    def GetType(self): return self.kind
    def GetTitle(self): return self.title
    def GetPathName(self): return self.path

    def FirstFeature(self):
        self.first_feature_calls += 1
        return self.features[0] if self.features else None

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected document access: {name}")


class SpyPart(Part):
    """Records any configuration activation attempt (must stay empty)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.activation_calls = []

    def ShowConfiguration2(self, name):
        self.activation_calls.append(name)
        raise AssertionError("configuration must not be activated by a read-only tool")


class Transform:
    def __init__(self, data=IDENTITY):
        self._data = list(data)

    @property
    def ArrayData(self): return self._data


class BrokenTransform:
    @property
    def ArrayData(self):
        raise RuntimeError("transform unreadable")


class Component:
    def __init__(self, name, document=None, transform=None,
                 path="C:/fixture/fitting.sldprt", configuration="Default",
                 configuration_read_error=None):
        self.Name2 = name
        self._document = document
        self.Transform2 = transform if transform is not None else Transform(IDENTITY)
        self._path = path
        self._configuration = configuration
        self._configuration_read_error = configuration_read_error

    def GetModelDoc2(self): return self._document
    def GetPathName(self): return self._path

    def __getattr__(self, name):
        if name == "ReferencedConfiguration":
            if self.__dict__.get("_configuration_read_error"):
                raise RuntimeError(self.__dict__["_configuration_read_error"])
            return self.__dict__.get("_configuration")
        raise AssertionError(f"Unexpected component access: {name}")


class Assembly:
    def __init__(self, components=(), kind=2):
        self._components = list(components)
        self._kind = kind
        self.top_only_calls = []

    def GetType(self): return self._kind

    def GetComponents(self, top_only):
        self.top_only_calls.append(top_only)
        return list(self._components)

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected assembly access: {name}")


class SW:
    def __init__(self, document):
        self.is_connected = True
        self.app = SimpleNamespace(ActiveDoc=document)

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data or {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


def sample_part():
    """Part with two native connection points, as in the RT2 read."""
    second = Definition(Location=(0.05, 0.0, 0.0), Direction=(1.0, 0.0, 0.0),
                        RouteDiameter=0.0254, StubLength=0.01, RouteType=1,
                        RouteSubType=10, PortID="P2")
    return Part([Feature(name="CPoint1", definition=Definition()),
                 Feature(name="CPoint2", definition=second)])


class RoutingComponentTests(unittest.TestCase):
    def run_tool(self, assembly, name="Flange1-1", enabled=True, sw=None):
        with patch.object(catalog, "routing_enabled", return_value=enabled):
            return rc.get_component_connection_points(sw or SW(assembly), name)

    def assertVector(self, expected, actual, places=6):
        self.assertIsNotNone(actual, f"expected {expected}, got None")
        self.assertEqual(len(expected), len(actual))
        for left, right in zip(expected, actual):
            self.assertAlmostEqual(left, right, places=places)

    # -- registration --------------------------------------------------------

    def test_registered_read_only_with_com_and_closed_schema(self):
        entry = registry._TOOLS["get_component_connection_points"]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertTrue(entry["com"])
        self.assertIsNone(entry["postflight"])
        self.assertFalse(entry["tool"].inputSchema["additionalProperties"])
        self.assertEqual(entry["handler"].__module__,
                         "solidworks_mcp.tools.routing_components")

    # -- gate first ----------------------------------------------------------

    def test_disabled_gate_rejects_before_any_automation_access(self):
        class Disabled(SW):
            @property
            def is_connected(self):
                raise AssertionError("gate must be first")

        result = self.run_tool(Assembly(), enabled=False,
                               sw=Disabled.__new__(Disabled))
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "ROUTING_DISABLED")

    def test_invalid_name_rejected_before_component_resolution(self):
        assembly = Assembly([Component("A-1", sample_part())])
        result = self.run_tool(assembly, name="Sub-1/A-1")
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "INVALID_COMPONENT_NAME")
        self.assertEqual(assembly.top_only_calls, [])

    # -- document validation -------------------------------------------------

    def test_not_connected_never_auto_connects(self):
        sw = SW(Assembly())
        sw.is_connected = False
        result = self.run_tool(Assembly(), sw=sw)
        self.assertEqual(result["error_name"], "swConnectionError")

    def test_no_active_document(self):
        result = self.run_tool(None)
        self.assertEqual(result["error_name"], "swNoActiveDocument")

    def test_wrong_document_type(self):
        result = self.run_tool(Part())
        self.assertEqual(result["error_name"], "swInvalidFileType")

    # -- exact top-level resolution ------------------------------------------

    def test_component_not_found_is_explicit(self):
        assembly = Assembly([Component("B-1", sample_part())])
        result = self.run_tool(assembly, name="A-1")
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "COMPONENT_NOT_FOUND")

    def test_nested_path_style_name_is_never_matched_as_suffix(self):
        assembly = Assembly([Component("Sub-1/A-1", sample_part())])
        result = self.run_tool(assembly, name="A-1")
        self.assertEqual(result["data"]["code"], "COMPONENT_NOT_FOUND")

    def test_resolution_reads_only_top_level_components(self):
        assembly = Assembly([Component("A-1", sample_part())])
        self.run_tool(assembly, name="A-1")
        self.assertEqual(assembly.top_only_calls, [True])

    def test_component_search_bound_is_explicit(self):
        components = [Component(f"C{x}", sample_part()) for x in range(1001)]
        result = self.run_tool(Assembly(components), name="missing")
        self.assertEqual(result["data"]["code"], "COMPONENT_NOT_FOUND")
        self.assertEqual(result["data"]["examined_components"], 1000)
        self.assertTrue(result["data"]["components_truncated"])

    # -- native fields + assembly placement ----------------------------------

    def test_two_instances_keep_native_fields_and_differ_in_position(self):
        part = sample_part()
        first = Component("A-1", part, transform=Transform(IDENTITY))
        second = Component("B-1", part, transform=Transform(TRANSLATED_X))
        assembly = Assembly([first, second])

        first_result = self.run_tool(assembly, name="A-1")
        second_result = self.run_tool(assembly, name="B-1")
        self.assertTrue(first_result["success"], first_result)
        self.assertTrue(second_result["success"], second_result)

        first_points = first_result["data"]["connection_points"]
        second_points = second_result["data"]["connection_points"]
        self.assertEqual(2, first_result["data"]["count"])
        self.assertEqual(["CPoint1", "CPoint2"],
                         [point["feature_name"] for point in first_points])

        # Native part-local fields are passed through unchanged, both instances.
        self.assertVector([0.0, 0.0, -6.35], first_points[0]["position_mm"])
        self.assertVector([0.0, 0.0, -6.35], second_points[0]["position_mm"])
        self.assertEqual([0.0, 0.0, -1.0], first_points[0]["direction"])
        self.assertAlmostEqual(50.8, first_points[0]["nominal_diameter_mm"])
        self.assertEqual(0.0, first_points[0]["stub_length_mm"])
        self.assertEqual(2, first_points[0]["route_type_raw"])
        self.assertEqual(20, first_points[0]["route_subtype_raw"])
        self.assertEqual("", first_points[0]["port_id"])
        self.assertEqual(25.4, first_points[1]["nominal_diameter_mm"])
        self.assertEqual("P2", first_points[1]["port_id"])

        # Assembly placement differs by the translation only.
        self.assertVector([0.0, 0.0, -6.35], first_points[0]["assembly_position_mm"])
        self.assertVector([100.0, 0.0, -6.35], second_points[0]["assembly_position_mm"])
        self.assertVector([50.0, 0.0, 0.0], first_points[1]["assembly_position_mm"])
        self.assertVector([150.0, 0.0, 0.0], second_points[1]["assembly_position_mm"])
        self.assertEqual([0.0, 0.0, -1.0], first_points[0]["assembly_direction"])
        self.assertEqual([1.0, 0.0, 0.0], second_points[1]["assembly_direction"])

        self.assertEqual("active_assembly", first_result["data"]["coordinate_system"])
        self.assertEqual("mm", first_result["data"]["length_unit"])
        self.assertEqual(
            {"referenced": "Default", "active": "Default", "matched": True},
            first_result["data"]["configuration"])
        self.assertTrue(first_result["data"]["transform"]["valid"])
        self.assertVector([0.0, 0.0, 0.0],
                          first_result["data"]["transform"]["translation_mm"])
        self.assertVector([100.0, 0.0, 0.0],
                          second_result["data"]["transform"]["translation_mm"])
        self.assertEqual(1.0, first_result["data"]["transform"]["scale"])
        self.assertTrue(first_result["data"]["coverage"]["complete"])
        self.assertFalse(first_result["data"]["coverage"]["partial"])

    def test_rotated_instance_transforms_position_and_direction(self):
        component = Component("C-1", sample_part(), transform=Transform(ROTATED_Z90))
        result = self.run_tool(Assembly([component]), name="C-1")
        self.assertTrue(result["success"], result)
        points = result["data"]["connection_points"]
        self.assertVector([100.0, 0.0, -6.35], points[0]["assembly_position_mm"],
                          places=6)
        self.assertVector([0.0, 0.0, -1.0], points[0]["assembly_direction"])
        # local +X maps to assembly +Y under Rz(90) in the row-vector convention
        self.assertVector([100.0, 50.0, 0.0], points[1]["assembly_position_mm"],
                          places=6)
        self.assertVector([0.0, 1.0, 0.0], points[1]["assembly_direction"])
        self.assertVector([50.0, 0.0, 0.0], points[1]["position_mm"])

    def test_empty_part_is_a_complete_read_not_an_error(self):
        component = Component("A-1", Part())
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertTrue(result["success"], result)
        self.assertEqual(0, result["data"]["count"])
        self.assertEqual([], result["data"]["connection_points"])
        self.assertTrue(result["data"]["coverage"]["complete"])

    # -- transform failures: explicit, partial, never fabricated --------------

    def test_missing_transform_reports_partial_not_fabricated(self):
        component = Component("A-1", sample_part(), transform=BrokenTransform())
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertFalse(data["transform"]["valid"])
        self.assertIsNone(data["transform"]["array_data"])
        self.assertIsNone(data["transform"]["translation_mm"])
        self.assertIsNone(data["transform"]["scale"])
        self.assertTrue(data["coverage"]["partial"])
        self.assertFalse(data["coverage"]["complete"])
        self.assertTrue(data["coverage"]["unresolved"])
        self.assertEqual(2, data["count"])
        for point in data["connection_points"]:
            self.assertIsNone(point["assembly_position_mm"])
            self.assertIsNone(point["assembly_direction"])
            self.assertFalse(point["assembly_placement_complete"])
            # part-local native fields stay readable and unchanged
            self.assertIsNotNone(point["position_mm"])
        self.assertAlmostEqual(50.8, data["connection_points"][0]["nominal_diameter_mm"])

    def test_unsupported_transform_values_are_rejected(self):
        cases = {
            "short": list(range(15)),
            "non_finite": [float("nan")] + IDENTITY[1:],
            "zero_scale": IDENTITY[:12] + [0] + IDENTITY[13:],
            "negative_scale": IDENTITY[:12] + [-1] + IDENTITY[13:],
            "non_unit_scale": IDENTITY[:12] + [2.0] + IDENTITY[13:],
            "fractional_scale": IDENTITY[:12] + [0.5] + IDENTITY[13:],
        }
        for label, values in cases.items():
            with self.subTest(label=label):
                component = Component("A-1", sample_part(), transform=Transform(values))
                result = self.run_tool(Assembly([component]), name="A-1")
                self.assertFalse(result["success"])
                self.assertFalse(result["data"]["transform"]["valid"])
                self.assertIsNone(
                    result["data"]["connection_points"][0]["assembly_position_mm"])
                self.assertTrue(result["data"]["errors"])

    def test_non_rigid_rotation_is_rejected(self):
        cases = {
            # reflection: determinant -1
            "mirror": [-1, 0, 0, 0, 1, 0, 0, 0, 1],
            # shear: row length sqrt(1.25), not unit
            "shear": [1, 0, 0, 0.5, 1, 0, 0, 0, 1],
            # degenerate: zero row
            "degenerate": [0, 0, 0, 0, 1, 0, 0, 0, 1],
            # non-orthogonal rows
            "skew": [1, 0, 0, 1, 0, 0, 0, 0, 1],
        }
        for label, rotation in cases.items():
            with self.subTest(label=label):
                values = list(rotation) + IDENTITY[9:]
                component = Component("A-1", sample_part(), transform=Transform(values))
                result = self.run_tool(Assembly([component]), name="A-1")
                self.assertFalse(result["success"])
                self.assertFalse(result["data"]["transform"]["valid"])
                self.assertIsNone(result["data"]["transform"]["array_data"])
                for point in result["data"]["connection_points"]:
                    self.assertIsNone(point["assembly_position_mm"])
                    self.assertIsNone(point["assembly_direction"])
                    self.assertFalse(point["assembly_placement_complete"])
                self.assertTrue(result["data"]["errors"])

    # -- configuration match: never read CPoints from the wrong configuration --

    def test_configuration_match_is_reported_and_cp_read_happens(self):
        part = SpyPart(sample_part().features)
        component = Component("A-1", part)
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertTrue(result["success"], result)
        self.assertEqual(
            {"referenced": "Default", "active": "Default", "matched": True},
            result["data"]["configuration"])
        self.assertEqual(1, part.first_feature_calls)
        self.assertEqual([], part.activation_calls)

    def test_configuration_mismatch_blocks_cp_read_with_evidence(self):
        part = SpyPart(sample_part().features)
        component = Component("A-1", part, configuration="Other")
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("CONFIGURATION_MISMATCH", data["code"])
        self.assertIsNone(data["count"])
        self.assertEqual([], data["connection_points"])
        self.assertEqual("Other", data["configuration"]["referenced"])
        self.assertEqual("Default", data["configuration"]["active"])
        self.assertFalse(data["configuration"]["matched"])
        self.assertTrue(data["configuration"]["evidence"])
        self.assertFalse(data["coverage"]["complete"])
        self.assertTrue(data["coverage"]["partial"])
        self.assertEqual(0, part.first_feature_calls)   # no CPoint read
        self.assertEqual([], part.activation_calls)     # no activation
        self.assertTrue(any("no configuration was activated" in error
                            for error in data["errors"]))
        self.assertEqual("swInvalidInput", result["error_name"])

    def test_configuration_unavailable_when_manager_null(self):
        part = Part(sample_part().features, configuration_manager=None)
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertEqual("CONFIGURATION_UNAVAILABLE", data["code"])
        self.assertIsNone(data["count"])
        self.assertEqual([], data["connection_points"])
        self.assertIsNone(data["configuration"]["active"])
        self.assertEqual(0, part.first_feature_calls)
        self.assertIn("swUnknownError", result["error_name"])

    def test_configuration_unavailable_when_manager_unreadable(self):
        part = Part(sample_part().features, configuration_manager=BrokenManager())
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertEqual("CONFIGURATION_UNAVAILABLE", result["data"]["code"])
        self.assertIsNone(result["data"]["count"])
        self.assertIsNone(result["data"]["configuration"]["active"])

    def test_configuration_unavailable_when_active_configuration_null(self):
        part = Part(sample_part().features, configuration_manager=NullActiveManager())
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertEqual("CONFIGURATION_UNAVAILABLE", result["data"]["code"])
        self.assertIsNone(result["data"]["configuration"]["active"])

    def test_configuration_unavailable_when_reference_unreadable(self):
        component = Component("A-1", sample_part(),
                              configuration_read_error="proxy lost")
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertEqual("CONFIGURATION_UNAVAILABLE", result["data"]["code"])
        self.assertIsNone(result["data"]["count"])
        self.assertIsNone(result["data"]["configuration"]["referenced"])

    def test_null_reference_configuration_is_unavailable_without_traversal(self):
        part = SpyPart(sample_part().features)
        result = self.run_tool(Assembly([Component("A-1", part, configuration=None)]), name="A-1")
        self.assertEqual("CONFIGURATION_UNAVAILABLE", result["data"]["code"])
        self.assertIsNone(result["data"]["count"])
        self.assertEqual(0, part.first_feature_calls)

    def test_examined_count_is_actual_early_match_count(self):
        result = self.run_tool(Assembly([Component("A-1", sample_part()), Component("B-1", sample_part())]), name="A-1")
        self.assertTrue(result["success"], result)
        self.assertEqual(1, result["data"]["coverage"]["examined_components"])

    # -- part document unavailable: explicit error, not an empty count --------

    def test_unloaded_part_document_is_an_explicit_error(self):
        component = Component("A-1", None)
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertFalse(result["success"])
        data = result["data"]
        self.assertIsNone(data["part"])
        self.assertIsNone(data["count"])
        self.assertEqual([], data["connection_points"])
        self.assertFalse(data["coverage"]["complete"])
        self.assertTrue(data["coverage"]["partial"])
        self.assertTrue(any("not loaded" in error for error in data["errors"]))

    def test_part_document_read_error_is_an_explicit_error(self):
        class Lightweight(Component):
            def GetModelDoc2(self):
                raise RuntimeError("lightweight component")

        result = self.run_tool(Assembly([Lightweight("A-1")]), name="A-1")
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"]["count"])
        self.assertTrue(any("could not be read" in error
                            for error in result["data"]["errors"]))

    def test_subassembly_component_is_rejected_as_not_a_part(self):
        component = Component("A-1", Part(kind=2))
        result = self.run_tool(Assembly([component]), name="A-1")
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"]["count"])
        self.assertEqual([], result["data"]["connection_points"])
        self.assertTrue(any("not a part" in error for error in result["data"]["errors"]))

    # -- native data problems are null, never invented ------------------------

    def test_bad_native_fields_are_null_not_fabricated(self):
        definition = Definition(Location=(0.0, float("nan"), 0.0), RouteType="2",
                                StubLength=None)
        part = Part([Feature(definition=definition)])
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertFalse(result["success"])
        point = result["data"]["connection_points"][0]
        self.assertIsNone(point["position_mm"])
        self.assertIsNone(point["assembly_position_mm"])
        self.assertIsNone(point["route_type_raw"])
        self.assertIsNone(point["stub_length_mm"])
        self.assertFalse(point["read_complete"])
        self.assertFalse(point["assembly_placement_complete"])
        self.assertAlmostEqual(50.8, point["nominal_diameter_mm"])
        # direction is still native and valid, so its assembly image is real
        self.assertEqual([0.0, 0.0, -1.0], point["assembly_direction"])

    def test_zero_direction_is_rejected_for_assembly_but_kept_part_local(self):
        definition = Definition(Direction=(0.0, 0.0, 0.0))
        part = Part([Feature(definition=definition)])
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertFalse(result["success"])
        point = result["data"]["connection_points"][0]
        self.assertEqual([0.0, 0.0, 0.0], point["direction"])
        self.assertIsNone(point["assembly_direction"])
        self.assertVector([0.0, 0.0, -6.35], point["assembly_position_mm"])
        self.assertTrue(any("direction" in error for error in result["data"]["errors"]))

    # -- bounded feature traversal -------------------------------------------

    def test_feature_traversal_bound_is_explicit(self):
        part = Part([Feature(kind="RefPlane") for _ in range(1001)])
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertFalse(result["success"])
        coverage = result["data"]["coverage"]
        self.assertEqual(1000, coverage["visited_features"])
        self.assertTrue(coverage["features_truncated"])
        self.assertFalse(coverage["complete"])
        self.assertEqual(0, result["data"]["count"])

    def test_feature_traversal_error_is_not_complete(self):
        class Broken(Feature):
            def GetNextFeature(self):
                raise RuntimeError("proxy lost")

        part = Part([Broken(definition=Definition())])
        result = self.run_tool(Assembly([Component("A-1", part)]), name="A-1")
        self.assertFalse(result["success"])
        self.assertFalse(result["data"]["coverage"]["complete"])
        self.assertEqual(1, result["data"]["count"])

    # -- read-only surface ----------------------------------------------------

    def test_no_selection_edit_or_resolve_members_are_used(self):
        assembly = Assembly([Component("A-1", sample_part())])
        result = self.run_tool(assembly, name="A-1")
        self.assertTrue(result["success"], result)
        self.assertEqual(assembly.top_only_calls, [True])
        self.assertTrue(all("saved" not in point for point in
                            result["data"]["connection_points"]))


if __name__ == "__main__":
    unittest.main()
