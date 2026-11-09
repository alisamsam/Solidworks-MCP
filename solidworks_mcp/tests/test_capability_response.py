import asyncio
import unittest

from solidworks_mcp import server


class CapabilityResponseTests(unittest.TestCase):
    def test_capability_response_reports_guarded_mode_and_known_blockers(self):
        response = asyncio.run(server.call_tool("get_capabilities", {}))

        text = response[0].text
        self.assertIn("guarded_mode", text)
        self.assertIn("execute_python", text)
        self.assertIn("pack_and_go", text)


if __name__ == "__main__":
    unittest.main()
