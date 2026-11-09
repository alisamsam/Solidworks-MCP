"""list_routing_path_segments: bounded read-only 3D-sketch segment read (RT3).

The tool reads exactly one named native 3D sketch (``3DProfileFeature``) in
the active native route assembly and reports its segments. These tests pin the
boundaries the brief requires: the Routing gate before any automation access, an
existing connection and the active assembly, ``IsRouteAssembly`` true, an exact
feature name of the right native type, no suppression, a null/malformed segment
read failing instead of reading as empty, the 1000-segment bound checked before
any segment is touched, only line/arc advertised, fail-closed per-field reads
(negative length, non-finite coordinates, non-integer type, non-positive arc
radius), construction rows kept but excluded from the aggregate, the aggregate
reported only when every segment read completely, sketch-local coordinates, no
route-manager identifiers, and no CAD mutators.
"""

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools import routing
from solidworks_mcp.tools import routing_path as rp


# ---------------------------------------------------------------------------
# Native stand-ins
# ---------------------------------------------------------------------------

class Point:
    def __init__(self, x, y, z=0.0):
        self.X = x
        self.Y = y
        self.Z = z


class Segment:
    def __init__(self, kind=0, construction=False, length=0.01):
        self.kind = kind
        self.construction = construction
        self.length = length

    def GetType(self):
        return self.kind

    @property
    def ConstructionGeometry(self):
        return self.construction

    def GetLength(self):
        return self.length


class Line(Segment):
    def __init__(self, start=(0.0, 0.0, 0.0), end=(0.01, 0.0, 0.0), **kwargs):
        super().__init__(kind=0, **kwargs)
        self.start = start
        self.end = end

    def GetStartPoint2(self):
        return Point(*self.start)

    def GetEndPoint2(self):
        return Point(*self.end)

    def GetRadius(self):
        raise AssertionError("GetRadius must not be read for a line segment")


class Arc(Segment):
    def __init__(self, start=(0.002, 0.0, 0.0), end=(0.0, 0.002, 0.0),
                 radius=0.002, **kwargs):
        super().__init__(kind=1, **kwargs)
        self.start = start
        self.end = end
        self.radius = radius

    def GetStartPoint2(self):
        return Point(*self.start)

    def GetEndPoint2(self):
        return Point(*self.end)

    def GetRadius(self):
        return self.radius


class Unsupported(Segment):
    def __init__(self, kind=3, **kwargs):
        super().__init__(kind=kind, **kwargs)

    def GetStartPoint2(self):
        raise AssertionError("endpoints must not be read for an unsupported segment")

    def GetEndPoint2(self):
        raise AssertionError("endpoints must not be read for an unsupported segment")


class NeverTouched:
    """A segment that must not be read at all (over-limit guard)."""

    calls = 0

    def GetType(self):
        NeverTouched.calls += 1
        return 0


class Sketch:
    def __init__(self, segments=()):
        self._segments = list(segments)

    def GetSketchSegments(self):
        return list(self._segments)


class NullSketch:
    def GetSketchSegments(self):
        return None


class BrokenSketch:
    def GetSketchSegments(self):
        raise RuntimeError("segments unavailable")


class MalformedSketch:
    def GetSketchSegments(self):
        return 5


class Feature:
    def __init__(self, name="Sketch3D1", kind="3DProfileFeature", sketch=None,
                 suppressed=False, type_error=None, specific_error=None,
                 suppressed_error=None):
        self.name = name
        self.kind = kind
        self.sketch = sketch if sketch is not None else Sketch()
        self.suppressed = suppressed
        self.type_error = type_error
        self.specific_error = specific_error
        self.suppressed_error = suppressed_error

    def GetTypeName2(self):
        if self.type_error:
            raise RuntimeError(self.type_error)
        return self.kind

    def GetSpecificFeature2(self):
        if self.specific_error:
            raise RuntimeError(self.specific_error)
        return self.sketch

    def IsSuppressed(self):
        if self.suppressed_error:
            raise RuntimeError(self.suppressed_error)
        return self.suppressed


class Configuration:
    def __init__(self, name):
        self.Name = name


class ConfigurationManager:
    def __init__(self, name):
        self.ActiveConfiguration = Configuration(name)


class Assembly:
    def __init__(self, features=(), kind=2, route_value=True, route_error=None):
        self._features = {feature.name: feature for feature in features}
        self._kind = kind
        self._route_value = route_value
        self._route_error = route_error

    def GetType(self):
        return self._kind

    def IsRouteAssembly(self):
        if self._route_error:
            raise RuntimeError(self._route_error)
        return self._route_value

    def FeatureByName(self, name):
        return self._features.get(name)

    def GetTitle(self):
        return "Route1.SLDASM"

    def GetPathName(self):
        return "C:/fixture/Route1.SLDASM"

    @property
    def ConfigurationManager(self):
        return ConfigurationManager("Default")


class SW:
    def __init__(self, document):
        self.is_connected = True
        self.app = SimpleNamespace(ActiveDoc=document)

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data or {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


def _route_feature(feature):
    """An assembly whose only feature is the given one, marked a route assembly."""
    return Assembly([feature])


class RoutingPathTests(unittest.TestCase):
    def run_tool(self, assembly, feature_name="Sketch3D1", enabled=True):
        with patch.object(catalog, "routing_enabled", return_value=enabled):
            return rp.list_routing_path_segments(SW(assembly), feature_name)

    # -- registration and schema ---------------------------------------------

    def test_registered_read_only_with_com(self):
        registry.registered_tools()
        entry = registry._TOOLS["list_routing_path_segments"]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertTrue(entry["com"])
        self.assertIsNone(entry["postflight"])
        self.assertEqual(entry["handler"].__module__,
                         "solidworks_mcp.tools.routing_path")

    def test_schema_requires_a_non_empty_feature_name(self):
        schema = registry._TOOLS["list_routing_path_segments"]["tool"].inputSchema
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(["feature_name"], schema["required"])
        self.assertEqual("string", schema["properties"]["feature_name"]["type"])
        self.assertEqual(1, schema["properties"]["feature_name"]["minLength"])

    def test_reuses_the_shared_routing_gate(self):
        self.assertIs(rp._routing_allowed, routing._routing_allowed)

    # -- gate first -----------------------------------------------------------

    def test_disabled_gate_rejects_before_any_automation_access(self):
        class Disabled(SW):
            @property
            def is_connected(self):
                raise AssertionError("gate must be first")

        with patch.object(catalog, "routing_enabled", return_value=False):
            result = rp.list_routing_path_segments(Disabled.__new__(Disabled), "Sketch3D1")
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_registry_rejects_before_handler_when_disabled(self):
        from unittest.mock import Mock

        sw = Mock()
        sw._result.side_effect = lambda success, message, error, data=None: {
            "success": success, "message": message, "data": data or {}}
        handler = Mock()
        entry = dict(registry._TOOLS["list_routing_path_segments"], handler=handler)
        with patch.dict(registry._TOOLS, {"list_routing_path_segments": entry}), \
                patch.object(catalog, "toolset_of", return_value="routing"), \
                patch.object(catalog, "routing_enabled", return_value=False):
            result = registry.execute("list_routing_path_segments", sw,
                                      {"feature_name": "Sketch3D1"}).result
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])
        handler.assert_not_called()

    # -- bounded argument, connection and document ----------------------------

    def test_invalid_feature_name_is_rejected_before_com(self):
        class Boom(Assembly):
            def IsRouteAssembly(self):
                raise AssertionError("must not reach COM for a bad argument")

        for bad in (None, "", "   ", 5, True):
            with self.subTest(feature_name=bad):
                result = self.run_tool(Boom(), feature_name=bad)
                self.assertFalse(result["success"])
                self.assertEqual("ROUTING_INPUT_INVALID", result["data"]["code"])

    def test_disconnected_never_auto_connects(self):
        sw = SW(_route_feature(Feature()))
        sw.is_connected = False
        with patch.object(catalog, "routing_enabled", return_value=True):
            result = rp.list_routing_path_segments(sw, "Sketch3D1")
        self.assertEqual("swConnectionError", result["error_name"])

    def test_no_active_document(self):
        result = self.run_tool(None)
        self.assertEqual("swNoActiveDocument", result["error_name"])

    def test_non_assembly_document(self):
        result = self.run_tool(Assembly([Feature()], kind=1))
        self.assertEqual("swInvalidFileType", result["error_name"])

    # -- native route assembly required ---------------------------------------

    def test_not_a_route_assembly_fails_closed(self):
        result = self.run_tool(Assembly([Feature()], route_value=False))
        self.assertFalse(result["success"])
        self.assertEqual("NOT_ROUTE_ASSEMBLY", result["data"]["code"])
        self.assertIs(False, result["data"]["native_route_assembly"])

    def test_non_boolean_route_flag_fails_closed(self):
        result = self.run_tool(Assembly([Feature()], route_value="yes"))
        self.assertFalse(result["success"])
        self.assertEqual("ROUTE_ASSEMBLY_UNREADABLE", result["data"]["code"])

    def test_unreadable_route_flag_fails_closed(self):
        result = self.run_tool(Assembly([Feature()], route_error="proxy lost"))
        self.assertFalse(result["success"])
        self.assertEqual("ROUTE_ASSEMBLY_UNREADABLE", result["data"]["code"])

    # -- exact feature and type -----------------------------------------------

    def test_feature_not_found(self):
        result = self.run_tool(_route_feature(Feature(name="Other")), "Sketch3D1")
        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_NOT_FOUND", result["data"]["code"])

    def test_wrong_feature_type_is_rejected(self):
        feature = Feature(kind="ProfileFeature", sketch=Sketch([Line()]))
        result = self.run_tool(_route_feature(feature))
        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_TYPE_MISMATCH", result["data"]["code"])
        self.assertEqual("ProfileFeature", result["data"]["feature_type"])

    def test_unreadable_feature_type(self):
        feature = Feature(type_error="no type")
        result = self.run_tool(_route_feature(feature))
        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_TYPE_UNREADABLE", result["data"]["code"])

    def test_suppressed_feature_is_rejected(self):
        feature = Feature(sketch=Sketch([Line()]), suppressed=True)
        result = self.run_tool(_route_feature(feature))
        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_SUPPRESSED", result["data"]["code"])

    def test_unreadable_suppression_state_fails_closed(self):
        feature = Feature(sketch=Sketch([Line()]), suppressed_error="no state")
        result = self.run_tool(_route_feature(feature))
        self.assertFalse(result["success"])
        self.assertFalse(result["data"]["coverage"]["complete"])
        self.assertTrue(any("IsSuppressed" in error for error in result["data"]["errors"]))

    # -- sketch and segment sequence ------------------------------------------

    def test_null_sketch_object(self):
        feature = Feature(specific_error=None)
        feature.sketch = None
        result = self.run_tool(_route_feature(feature))
        self.assertFalse(result["success"])
        self.assertEqual("SKETCH_NULL", result["data"]["code"])

    def test_unreadable_specific_feature(self):
        result = self.run_tool(_route_feature(Feature(specific_error="no sketch")))
        self.assertFalse(result["success"])
        self.assertEqual("SKETCH_UNREADABLE", result["data"]["code"])

    def test_null_segments_fails_not_empty(self):
        result = self.run_tool(_route_feature(Feature(sketch=NullSketch())))
        self.assertFalse(result["success"])
        self.assertEqual("SEGMENTS_NULL", result["data"]["code"])

    def test_malformed_segments_fails_not_empty(self):
        result = self.run_tool(_route_feature(Feature(sketch=MalformedSketch())))
        self.assertFalse(result["success"])
        self.assertEqual("SEGMENTS_MALFORMED", result["data"]["code"])

    def test_malformed_empty_iterables_are_not_successful_empty_sketches(self):
        class ContainerSketch:
            def __init__(self, value):
                self.value = value
            def GetSketchSegments(self):
                return self.value
        for value in ("", b"", {}, set(), iter(())):
            sketch = ContainerSketch(value)
            result = self.run_tool(_route_feature(Feature(sketch=sketch)))
            self.assertFalse(result["success"], value)
            self.assertEqual("SEGMENTS_MALFORMED", result["data"]["code"])

    def test_named_absorbed_sketch_does_not_claim_top_level_or_managed_membership(self):
        feature = Feature(sketch=Sketch([Line()]))
        feature.GetOwnerFeature = lambda: SimpleNamespace(Name="Route1", GetTypeName2=lambda: "FabricatedRoute")
        result = self.run_tool(_route_feature(feature))
        self.assertTrue(result["success"], result)
        self.assertEqual("single_named_3d_sketch", result["data"]["coverage"]["scope"])
        self.assertFalse(result["data"]["managed_route_membership_verified"])

    def test_unreadable_segments(self):
        result = self.run_tool(_route_feature(Feature(sketch=BrokenSketch())))
        self.assertFalse(result["success"])
        self.assertEqual("SEGMENTS_UNREADABLE", result["data"]["code"])

    def test_empty_sketch_is_a_complete_zero_segment_read(self):
        result = self.run_tool(_route_feature(Feature(sketch=Sketch([]))))
        self.assertTrue(result["success"], result)
        self.assertEqual(0, result["data"]["count"])
        self.assertEqual(0.0, result["data"]["total_nonconstruction_length_mm"])
        self.assertTrue(result["data"]["coverage"]["complete"])

    # -- line / arc reads -----------------------------------------------------

    def test_line_and_arc_are_converted_and_read(self):
        sketch = Sketch([
            Line(start=(0.0, 0.0, 0.0), end=(0.01, 0.0, 0.0), length=0.01),
            Arc(start=(0.002, 0.0, 0.0), end=(0.0, 0.002, 0.0), radius=0.002,
                length=0.00314159265),
        ])
        result = self.run_tool(_route_feature(Feature(sketch=sketch)))
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual("route_3d_sketch_local", data["coordinate_system"])
        self.assertEqual("mm", data["length_unit"])
        self.assertNotIn("transform", data)
        self.assertFalse(data["route_manager_ids_read"])
        self.assertFalse(data["managed_route_membership_verified"])

        line, arc = data["segments"]
        self.assertEqual(0, line["index"])
        self.assertEqual(0, line["type_raw"])
        self.assertEqual("line", line["type"])
        self.assertFalse(line["construction"])
        self.assertAlmostEqual(10.0, line["length_mm"])
        self.assertEqual([0.0, 0.0, 0.0], line["start_mm"])
        self.assertEqual([10.0, 0.0, 0.0], line["end_mm"])
        self.assertIsNone(line["radius_mm"])
        self.assertTrue(line["read_complete"])

        self.assertEqual(1, arc["index"])
        self.assertEqual(1, arc["type_raw"])
        self.assertEqual("arc", arc["type"])
        self.assertEqual([2.0, 0.0, 0.0], arc["start_mm"])
        self.assertEqual([0.0, 2.0, 0.0], arc["end_mm"])
        self.assertAlmostEqual(2.0, arc["radius_mm"])
        self.assertTrue(arc["read_complete"])

        self.assertAlmostEqual(10.0 + 3.14159265, data["total_nonconstruction_length_mm"])

    def test_construction_rows_kept_but_excluded_from_aggregate(self):
        sketch = Sketch([
            Line(length=0.01),
            Line(length=0.02, construction=True),
            Arc(length=0.005),
        ])
        result = self.run_tool(_route_feature(Feature(sketch=sketch)))
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual(3, data["count"])
        self.assertEqual(3, len(data["segments"]))
        self.assertTrue(data["segments"][1]["construction"])
        self.assertEqual(1, data["coverage"]["construction_segments"])
        self.assertAlmostEqual(0.015 * 1000.0, data["total_nonconstruction_length_mm"])

    def test_unsupported_type_keeps_raw_type_and_fails(self):
        sketch = Sketch([Line(), Unsupported(kind=3)])
        result = self.run_tool(_route_feature(Feature(sketch=sketch)))
        self.assertFalse(result["success"])
        data = result["data"]
        row = data["segments"][1]
        self.assertEqual(3, row["type_raw"])
        self.assertEqual("unsupported", row["type"])
        self.assertIsNone(row["start_mm"])
        self.assertIsNone(row["end_mm"])
        self.assertIsNone(row["radius_mm"])
        self.assertFalse(row["read_complete"])
        self.assertFalse(data["coverage"]["complete"])
        self.assertIsNone(data["total_nonconstruction_length_mm"])
        self.assertEqual(1, data["coverage"]["unsupported_segments"])

    def test_non_integer_type_is_a_field_error(self):
        for bad in (True, "0", None, 1.0):
            with self.subTest(bad=bad):
                segment = Line()
                segment.kind = bad
                result = self.run_tool(_route_feature(Feature(sketch=Sketch([segment]))))
                self.assertFalse(result["success"])
                row = result["data"]["segments"][0]
                self.assertIsNone(row["type_raw"])
                self.assertFalse(row["read_complete"])

    def test_negative_length_is_a_field_error_and_no_aggregate(self):
        result = self.run_tool(
            _route_feature(Feature(sketch=Sketch([Line(length=-0.01)]))))
        self.assertFalse(result["success"])
        row = result["data"]["segments"][0]
        self.assertIsNone(row["length_mm"])
        self.assertFalse(row["read_complete"])
        self.assertIsNone(result["data"]["total_nonconstruction_length_mm"])

    def test_non_finite_coordinates_are_field_errors(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                segment = Line(start=(bad, 0.0, 0.0))
                result = self.run_tool(_route_feature(Feature(sketch=Sketch([segment]))))
                self.assertFalse(result["success"])
                row = result["data"]["segments"][0]
                self.assertIsNone(row["start_mm"])
                self.assertFalse(row["read_complete"])
                self.assertIsNone(result["data"]["total_nonconstruction_length_mm"])

    def test_non_positive_arc_radius_is_a_field_error(self):
        for bad in (0.0, -0.002):
            with self.subTest(bad=bad):
                result = self.run_tool(
                    _route_feature(Feature(sketch=Sketch([Arc(radius=bad)]))))
                self.assertFalse(result["success"])
                row = result["data"]["segments"][0]
                self.assertIsNone(row["radius_mm"])
                self.assertFalse(row["read_complete"])

    def test_non_boolean_construction_flag_is_a_field_error(self):
        segment = Line()
        segment.construction = "yes"
        result = self.run_tool(_route_feature(Feature(sketch=Sketch([segment]))))
        self.assertFalse(result["success"])
        row = result["data"]["segments"][0]
        self.assertIsNone(row["construction"])
        self.assertFalse(row["read_complete"])

    def test_partial_failure_makes_the_aggregate_null(self):
        sketch = Sketch([Line(length=0.01), Unsupported(kind=4)])
        result = self.run_tool(_route_feature(Feature(sketch=sketch)))
        data = result["data"]
        self.assertTrue(data["coverage"]["partial"])
        self.assertIsNone(data["total_nonconstruction_length_mm"])
        self.assertTrue(any("segment 1" in error for error in data["errors"]))

    # -- limit ----------------------------------------------------------------

    def test_segment_limit_is_checked_before_any_segment_read(self):
        NeverTouched.calls = 0
        try:
            sketch = Sketch([NeverTouched() for _ in range(1001)])
            result = self.run_tool(_route_feature(Feature(sketch=sketch)))
            self.assertFalse(result["success"])
            data = result["data"]
            self.assertEqual("SEGMENT_LIMIT_EXCEEDED", data["code"])
            self.assertEqual(1001, data["segment_count"])
            self.assertEqual(1000, data["limit"])
            self.assertNotIn("segments", data)
            self.assertEqual(0, NeverTouched.calls)
        finally:
            NeverTouched.calls = 0

    def test_at_limit_is_read(self):
        sketch = Sketch([Line(length=0.001) for _ in range(1000)])
        result = self.run_tool(_route_feature(Feature(sketch=sketch)))
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1000, result["data"]["count"])

    # -- identity, notes, no mutators -----------------------------------------

    def test_document_identity_and_feature_evidence(self):
        result = self.run_tool(_route_feature(Feature(sketch=Sketch([Line()]))))
        data = result["data"]
        self.assertEqual("Route1.SLDASM", data["document"]["title"])
        self.assertEqual("C:/fixture/Route1.SLDASM", data["document"]["path"])
        self.assertEqual("Default", data["document"]["configuration"])
        self.assertEqual({"name": "Sketch3D1", "type": "3DProfileFeature",
                          "suppressed": False}, data["feature"])

    def test_notes_state_the_read_only_boundaries(self):
        result = self.run_tool(_route_feature(Feature(sketch=Sketch([Line()]))))
        notes = " ".join(result["data"]["notes"])
        self.assertIn("route_3d_sketch_local", notes)
        self.assertIn("not a persistent identifier", notes)
        self.assertIn("route manager identifiers are not read", notes)
        self.assertIn("connectivity", notes)

    def test_module_has_no_cad_mutators_or_filesystem_handles(self):
        source = inspect.getsource(rp)
        for forbidden in ("ClearSelection", "ForceRebuild", "Rebuild3", "EditRoute",
                          "StartRoute", "InsertRoute", "AutoConnect",
                          "ShowConfiguration", "GetRouteManager", "AccessSelections",
                          "ModifyDefinition", "SetUserPreference", "LoadFile", "SaveAs"):
            self.assertNotIn(forbidden, source, forbidden)
        for attribute in ("os", "Path", "open", "stat", "exists", "listdir"):
            self.assertFalse(hasattr(rp, attribute), attribute)


if __name__ == "__main__":
    unittest.main()
