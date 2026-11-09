import asyncio
import unittest
from unittest.mock import patch

from solidworks_mcp import server


class GuardedServerTests(unittest.TestCase):
    def test_guarded_mode_does_not_advertise_execute_python(self):
        with patch.object(server.config, "guarded_mode", True):
            tools = asyncio.run(server.list_tools())

        self.assertNotIn("execute_python", [tool.name for tool in tools])

    def test_guarded_mode_does_not_dispatch_execute_python(self):
        from solidworks_mcp.tools import connection

        with patch.object(server.config, "guarded_mode", True), patch.object(
            connection, "_execute_python", side_effect=AssertionError("must not execute")
        ) as execute:
            response = asyncio.run(server.call_tool("execute_python", {"code": "print('x')"}))

        execute.assert_not_called()
        self.assertIn("guarded", response[0].text.lower())


if __name__ == "__main__":
    unittest.main()
