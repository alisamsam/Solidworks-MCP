"""Native scratch proof for circular-edge pipe/tube CPoints and editing."""
import os
from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.routing_create import (list_routing_reference_edges,
                                                 create_routing_connection_point)
from solidworks_mcp.tools.routing_edit import update_routing_connection_point


@live_only
class LiveRoutingCreationTests(ScratchPartTestCase):
    def test_pipe_tube_and_reverse_persist_native_values_without_changing_solid(self):
        self.assertEqual("true", os.environ.get("SW_MCP_ROUTING_ENABLED"))
        self.open_scratch_part()
        doc = self.document()
        self.automation.bind_active_document()
        f = com(doc, "FirstFeature")
        while f is not None and com(f, "GetTypeName2") != "RefPlane":
            f = com(f, "GetNextFeature")
        self.assertIsNotNone(f)
        self.assertTrue(f.Select2(False, 0))
        sk = self._keep(com(doc, "SketchManager"))
        sk.InsertSketch(True)
        self._keep(sk.CreateCircleByRadius(0., 0., 0., .025))
        sk.InsertSketch(True)
        boss = com(doc, "FeatureManager").FeatureExtrusion2(
            True,False,False,0,0,.01,.01,False,False,False,False,0.,0.,
            False,False,False,False,True,True,True,0,0.,False)
        self.assertIsNotNone(self._keep(boss))
        before_volume = com(com(com(doc, "Extension"), "CreateMassProperty"), "Volume")
        refs = list_routing_reference_edges(self.automation)
        self.assertTrue(refs["success"], refs)
        self.assertEqual(2, refs["data"]["count"])
        directions = []
        for kind, reverse, diameter, stub in [("pipe", False, 25., 5.),
                                             ("pipe", True, 32., 7.),
                                             ("tube", False, 18., 4.)]:
            refs = list_routing_reference_edges(self.automation)
            self.assertTrue(refs["success"])
            result = create_routing_connection_point(self.automation, 0, diameter,
                                                     stub, reverse, kind)
            self.assertTrue(result["success"], result)
            point = result["data"]["connection_point"]
            self.assertEqual(2 if kind == "pipe" else 1, point["route_type_raw"])
            self.assertAlmostEqual(diameter, point["nominal_diameter_mm"])
            self.assertAlmostEqual(stub, point["stub_length_mm"])
            for actual, expected in zip(point["position_mm"], refs["data"]["edges"][0]["center_mm"]):
                self.assertAlmostEqual(expected, actual, places=6)
            directions.append(point["direction"])
        for a, b in zip(directions[0], directions[1]): self.assertAlmostEqual(a, -b)
        # All public update combinations on the native tube CPoint created above.
        name = point["feature_name"]
        for updates in ({"diameter_mm": 22., "stub_length_mm": 9.},
                         {"diameter_mm": 24.}, {"stub_length_mm": 6.}):
            edited = update_routing_connection_point(self.automation, name, **updates)
            self.assertTrue(edited["success"], edited)
            self.assertTrue(edited["data"]["rebuild"])
            self.assertTrue(edited["data"]["invariants_unchanged"])
        for updates in ({"port_id": "SPIGOT"}, {"port_id": "PRIKLJUČEK_Ž"}, {"port_id": ""},
                        {"port_id": "SOCKET", "diameter_mm": 26., "stub_length_mm": 8.}):
            edited = update_routing_connection_point(self.automation, name, **updates)
            self.assertTrue(edited["success"], edited)
            self.assertEqual(updates["port_id"], edited["data"]["after"]["port_id"])
            self.assertTrue(edited["data"]["invariants_unchanged"])
        self.assertEqual(before_volume, com(com(com(doc, "Extension"), "CreateMassProperty"), "Volume"))
        self.assert_unsaved()
