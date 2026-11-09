"""RT2 read proof on the already-open, unmodified official flange sample."""

import hashlib
import os
from pathlib import Path
import unittest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import live_only
from solidworks_mcp.tools.routing import list_routing_connection_points, get_routing_component_metadata


@live_only
class LiveRoutingPointTests(unittest.TestCase):
    def test_flange_cpoint_native_values_and_read_only_state(self):
        self.assertEqual("true", os.environ.get("SW_MCP_ROUTING_ENABLED"))
        sw = SolidWorksAutomation()
        self.assertTrue(sw.connect()["success"])
        doc = sw.app.ActiveDoc
        self.assertEqual(1, com(doc, "GetType"))
        self.assertEqual("slip on weld flange", com(doc, "GetTitle"))
        source = Path(com(doc, "GetPathName"))
        self.assertIn("routing-pipes", source.parts)
        before = (com(doc, "GetTitle"), str(source), com(doc, "GetSaveFlag"),
                  com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1),
                  com(com(com(doc, "Extension"), "CreateMassProperty"), "Volume"))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()

        result = list_routing_connection_points(sw)

        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertTrue(data["coverage"]["complete"])
        self.assertEqual(1, data["count"])
        point = data["connection_points"][0]
        self.assertEqual("CPoint1", point["feature_name"])
        for actual, expected in zip(point["position_mm"], [0.0, 0.0, -6.35]):
            self.assertAlmostEqual(expected, actual, places=6)
        self.assertEqual([0.0, 0.0, -1.0], point["direction"])
        self.assertAlmostEqual(50.8, point["nominal_diameter_mm"], places=6)
        self.assertEqual(0.0, point["stub_length_mm"])
        self.assertEqual(2, point["route_type_raw"])
        self.assertEqual(20, point["route_subtype_raw"])
        self.assertEqual("", point["port_id"])
        metadata = get_routing_component_metadata(sw)
        self.assertTrue(metadata["success"], metadata)
        self.assertEqual(3, metadata["data"]["component_type_raw"])
        self.assertEqual(1, metadata["data"]["component_route_type_raw"])
        self.assertEqual(1, metadata["data"]["cpoint_configuration_raw"])
        self.assertEqual("", metadata["data"]["description"])
        after_doc = sw.app.ActiveDoc
        after = (com(after_doc, "GetTitle"), com(after_doc, "GetPathName"),
                 com(after_doc, "GetSaveFlag"),
                 com(com(after_doc, "SelectionManager"), "GetSelectedObjectCount2", -1),
                 com(com(com(after_doc, "Extension"), "CreateMassProperty"), "Volume"))
        self.assertEqual(before, after)
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
