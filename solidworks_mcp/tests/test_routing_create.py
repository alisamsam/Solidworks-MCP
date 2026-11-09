"""Piping CPoint circular-reference creation contract."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.tools import routing_create as rc
from solidworks_mcp.tests.test_routing_points import SW, Part, Feature, Definition


class Curve:
    IsCircle = True
    CircleParams = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.025)


class Edge:
    GetCurve = Curve()
    def Select4(self, append, selection):
        assert not append and selection.Mark == 1
        return True


class Fixture(Part):
    GetActiveSketch2 = None
    def __init__(self, ok=True, persist=True):
        super().__init__()
        self.ok, self.persist = ok, persist
        self.calls = []
        self.edge = Edge()
        self.FeatureManager = self
        self.SelectionManager = SimpleNamespace(CreateSelectData=SimpleNamespace(Mark=0))

    def GetBodies2(self, kind, visible):
        return [SimpleNamespace(GetEdges=[self.edge])]

    def ClearSelection2(self, all): self.calls.append("clear")

    def InsertConnectionPoint(self, *args):
        self.calls.append(args)
        if self.persist:
            d = Definition()
            d.Location = (0.0, 0.0, 0.0)
            d.Direction = (0.0, 0.0, -1.0 if args[2] else 1.0)
            d.RouteDiameter, d.StubLength = args[3:5]
            self.features.append(Feature(definition=d))
        return self.ok

    def FeatureByName(self, name): return self.features[0]


class RoutingCreateTests(unittest.TestCase):
    def setUp(self):
        self.gate = patch.object(catalog, "routing_enabled", return_value=True)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def test_circle_geometry_in_mm(self):
        result = rc.list_routing_reference_edges(SW(Fixture()))
        self.assertTrue(result["success"])
        edge = result["data"]["edges"][0]
        self.assertEqual(0, edge["reference_index"])
        self.assertEqual(25.0, edge["radius_mm"])
        self.assertNotIn("edge", edge)

    def test_creation_values_and_native_feature_proof(self):
        doc = Fixture()
        result = rc.create_routing_connection_point(SW(doc), 0, 25, 5)
        self.assertTrue(result["success"], result)
        args = doc.calls[-1]
        self.assertEqual((2, 0, False, .025, .005), args[:5])
        self.assertEqual(14, len(args))
        self.assertEqual(25, result["data"]["connection_point"]["nominal_diameter_mm"])

    def test_reverse_direction_forwarded(self):
        doc = Fixture()
        self.assertTrue(rc.create_routing_connection_point(SW(doc), 0, 30, reverse_direction=True)["success"])
        self.assertTrue(doc.calls[-1][2])

    def test_tube_mode_native_type(self):
        doc = Fixture()
        original = doc.InsertConnectionPoint
        def insert(*args):
            ok = original(*args)
            doc.features[0].definition.RouteType = args[0]
            return ok
        doc.InsertConnectionPoint = insert
        result = rc.create_routing_connection_point(SW(doc), 0, 18, 4, route_kind="tube")
        self.assertTrue(result["success"], result)
        self.assertEqual(1, doc.calls[-1][0])
        self.assertEqual((0., 0.), doc.calls[-1][5:7])

    def test_gate_before_automation(self):
        with patch.object(catalog, "routing_enabled", return_value=False):
            sw = SW(None)
            del sw.is_connected
            for handler, args in [(rc.list_routing_reference_edges, ()),
                                  (rc.create_routing_connection_point, (0, 25))]:
                self.assertEqual("ROUTING_DISABLED", handler(sw, *args)["data"]["code"])

    def test_dispatcher_gate_precedes_invalid_args_and_binding(self):
        registry.registered_tools()
        with patch.object(catalog, "routing_enabled", return_value=False):
            result = registry.execute("create_routing_connection_point", SW(None), {"bad": 1}).result
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_validation_before_selection(self):
        for kwargs in ({"diameter_mm": 0}, {"diameter_mm": float("inf")},
                       {"stub_length_mm": -1}, {"reference_index": True},
                       {"reverse_direction": 1}, {"reference_index": 99}):
            with self.subTest(kwargs=kwargs):
                doc = Fixture()
                args = dict(reference_index=0, diameter_mm=25)
                args.update(kwargs)
                result = rc.create_routing_connection_point(SW(doc), **args)
                self.assertFalse(result["success"])
                self.assertEqual([], doc.calls)

    def test_active_sketch_rejected(self):
        doc = Fixture()
        doc.GetActiveSketch2 = object()
        self.assertFalse(rc.create_routing_connection_point(SW(doc), 0, 25)["success"])
        self.assertEqual([], doc.calls)

    def test_false_result_with_persistent_feature_reports_partial_mutation(self):
        result = rc.create_routing_connection_point(SW(Fixture(ok=False)), 0, 25)
        self.assertFalse(result["success"])
        self.assertTrue(result["data"]["mutation_attempted"])
        self.assertFalse(result["data"]["rollback_performed"])

    def test_true_return_without_feature_not_success(self):
        result = rc.create_routing_connection_point(SW(Fixture(persist=False)), 0, 25)
        self.assertFalse(result["success"])

    def test_wrong_readback_diameter_fails(self):
        doc = Fixture()
        def wrong(*args):
            Fixture.InsertConnectionPoint(doc, *args)
            doc.features[0].definition.RouteDiameter = .1
            return True
        doc.InsertConnectionPoint = wrong
        self.assertFalse(rc.create_routing_connection_point(SW(doc), 0, 25)["success"])

    def test_wrong_position_fails(self):
        doc = Fixture()
        def wrong(*args):
            Fixture.InsertConnectionPoint(doc, *args)
            doc.features[0].definition.Location = (.1, 0, 0)
            return True
        doc.InsertConnectionPoint = wrong
        self.assertFalse(rc.create_routing_connection_point(SW(doc), 0, 25)["success"])

    def test_invalid_or_wrong_reversal_direction_is_not_verified(self):
        for direction in ((0., 0., 0.), (1., 0., 0.), (0., 0., -1.)):
            with self.subTest(direction=direction):
                doc = Fixture()
                original = doc.InsertConnectionPoint
                def wrong(*args):
                    original(*args)
                    doc.features[0].definition.Direction = direction
                    return True
                doc.InsertConnectionPoint = wrong
                self.assertFalse(rc.create_routing_connection_point(SW(doc), 0, 25)["success"])

    def test_edge_limit_fails_closed(self):
        doc = Fixture()
        doc.GetBodies2 = lambda *args: [SimpleNamespace(GetEdges=[Edge()] * 1001)]
        self.assertFalse(rc.list_routing_reference_edges(SW(doc))["success"])
        self.assertFalse(rc.create_routing_connection_point(SW(doc), 0, 25)["success"])
        self.assertEqual([], doc.calls)

    def test_non_circle_skipped(self):
        doc = Fixture()
        doc.edge = SimpleNamespace(GetCurve=SimpleNamespace(IsCircle=False))
        result = rc.list_routing_reference_edges(SW(doc))
        self.assertTrue(result["success"])
        self.assertEqual(0, result["data"]["count"])

    def test_invalid_circle_axis_fails_before_selection(self):
        for axis in ((0., 0., 0.), (1e308, 1e308, 1e308)):
            doc = Fixture()
            doc.edge = SimpleNamespace(GetCurve=SimpleNamespace(IsCircle=True,
                CircleParams=(0., 0., 0., *axis, .025)))
            self.assertFalse(rc.create_routing_connection_point(SW(doc), 0, 25)["success"])
            self.assertEqual([], doc.calls)

    def test_wrong_type_and_not_connected(self):
        self.assertEqual("swInvalidFileType", rc.list_routing_reference_edges(SW(Part(kind=2)))["error_name"])
        sw = SW(Fixture())
        sw.is_connected = False
        self.assertEqual("swConnectionError", rc.create_routing_connection_point(sw, 0, 25)["error_name"])


if __name__ == "__main__": unittest.main()
