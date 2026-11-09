"""Opt-in RT1 proof on an already-open assembly; never edits or saves it."""

import hashlib
import os
from pathlib import Path
import unittest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import live_only


@live_only
class LiveRoutingContextTests(unittest.TestCase):
    def test_active_assembly_native_identity_and_state_are_preserved(self):
        from solidworks_mcp.tools.routing import inspect_routing_context

        self.assertEqual("true", os.environ.get("SW_MCP_ROUTING_ENABLED"))
        expected = os.environ.get("SW_MCP_ROUTING_EXPECT_NATIVE")
        self.assertIn(expected, {"0", "1"}, "Set expected native identity to 0 or 1.")
        sw = SolidWorksAutomation()
        connected = sw.connect()
        self.assertTrue(connected["success"], connected)
        doc = sw.app.ActiveDoc
        self.assertIsNotNone(doc)
        self.assertEqual(2, com(doc, "GetType"))
        title = com(doc, "GetTitle")
        path = com(doc, "GetPathName")
        before = (title, path, com(doc, "GetSaveFlag"),
                  com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1))
        source = Path(path) if path else None
        digest = hashlib.sha256(source.read_bytes()).hexdigest() if source else None

        result = inspect_routing_context(sw)

        self.assertTrue(result["success"], result)
        self.assertEqual(expected == "1", result["data"]["native_route_assembly"])
        after_doc = sw.app.ActiveDoc
        after = (com(after_doc, "GetTitle"), com(after_doc, "GetPathName"),
                 com(after_doc, "GetSaveFlag"),
                 com(com(after_doc, "SelectionManager"), "GetSelectedObjectCount2", -1))
        self.assertEqual(before, after)
        if source:
            self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
