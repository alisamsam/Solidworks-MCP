"""RT2 gap proof on two task-inserted native library flanges."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import live_only
from solidworks_mcp.tools.routing_measure import measure_routing_connection_gap


@live_only
class LiveRoutingGapTests(unittest.TestCase):
    def test_opposite_flange_cpoints_geometric_gap_and_unchanged_state(self):
        self.assertEqual("true", os.environ.get("SW_MCP_ROUTING_ENABLED"))
        sw = SolidWorksAutomation()
        self.assertTrue(sw.connect()["success"])
        doc = sw.app.ActiveDoc
        self.assertEqual(2, com(doc, "GetType"))
        self.assertFalse(com(doc, "GetPathName"), "Use the task scratch assembly only.")
        components = list(com(doc, "GetComponents", True) or [])
        self.assertEqual(2, len(components))
        self.assertEqual({"slip on weld flange-1", "slip on weld flange-2"},
                         {com(c, "Name2") for c in components})
        def state():
            return (com(sw.app.ActiveDoc, "GetTitle"), com(doc, "GetSaveFlag"),
                    com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1),
                    [(com(c, "Name2"), com(c, "ReferencedConfiguration"),
                      tuple(com(com(c, "Transform2"), "ArrayData")),
                      com(com(c, "GetModelDoc2"), "GetSaveFlag")) for c in components])
        before = state()
        sources = {Path(com(c, "GetPathName")) for c in components}
        digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        result = measure_routing_connection_gap(sw, "slip on weld flange-1", "CPoint1",
                                               "slip on weld flange-2", "CPoint1")
        self.assertTrue(result["success"], result)
        measurement = result["data"]["measurement"]
        self.assertAlmostEqual(112.7, measurement["distance_mm"], places=6)
        self.assertAlmostEqual(0., measurement["opposition_angle_deg"], places=6)
        self.assertAlmostEqual(-1., measurement["direction_dot"], places=6)
        self.assertAlmostEqual(0., measurement["diameter_difference_mm"], places=6)
        self.assertTrue(measurement["route_type_equal"])
        self.assertNotIn("connected", measurement)
        json.dumps(result, allow_nan=False)
        self.assertEqual(before, state())
        for path, digest in digests.items():
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
