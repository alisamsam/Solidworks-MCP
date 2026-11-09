"""Read-only native geometry proof on the owned routeassy1 reference copy."""
import hashlib
import math
from pathlib import Path
import unittest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import live_only
from solidworks_mcp.tools.routing_path import list_routing_path_segments


@live_only
class LiveRoutingPathReadTests(unittest.TestCase):
    def test_owned_route_lines_arcs_and_construction_without_mutation(self):
        sw = SolidWorksAutomation()
        self.assertTrue(sw.connect()["success"])
        doc = sw.app.ActiveDoc
        path = Path(com(doc, "GetPathName"))
        if "routing-native-skid-20261016-R01" not in path.parts or not path.name.startswith("routeassy1-"):
            self.skipTest("Activate the owned native routeassy1 reference copy first.")
        self.assertIs(com(doc, "IsRouteAssembly"), True)
        self.assertIs(com(doc, "GetSaveFlag"), False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        selection = com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1)
        result = list_routing_path_segments(sw, "3DSketch1")
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual(24, data["count"])
        self.assertTrue(data["coverage"]["complete"])
        self.assertEqual({"line", "arc"}, {s["type"] for s in data["segments"]})
        self.assertGreater(data["coverage"]["construction_segments"], 0)
        expected_total = 0.
        for segment in data["segments"]:
            chord = math.dist(segment["start_mm"], segment["end_mm"])
            if segment["type"] == "line":
                self.assertAlmostEqual(chord, segment["length_mm"], places=6)
            else:
                self.assertGreater(segment["radius_mm"], 0.)
                self.assertLessEqual(chord, 2 * segment["radius_mm"] + 1e-6)
                self.assertLessEqual(segment["length_mm"], 2 * math.pi * segment["radius_mm"] + 1e-6)
            if not segment["construction"]:
                expected_total += segment["length_mm"]
        self.assertAlmostEqual(expected_total, data["total_nonconstruction_length_mm"], places=6)
        self.assertFalse(data["managed_route_membership_verified"])
        self.assertFalse(data["route_manager_ids_read"])
        self.assertEqual(selection, com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1))
        self.assertIs(com(doc, "GetSaveFlag"), False)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(path, Path(com(sw.app.ActiveDoc, "GetPathName")))
