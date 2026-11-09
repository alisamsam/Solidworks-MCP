import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from solidworks_mcp import server

SNAPSHOT = Path(__file__).parent / "data" / "tool_catalog_snapshot.json"


def full_catalog():
    """Every tool, as a client would see it with all toolsets and raw execution enabled."""
    with mock.patch.dict(os.environ, {}, clear=False), \
            mock.patch.object(server.config, "guarded_mode", False), \
            mock.patch.object(server.config, "enabled_toolsets", None):
        os.environ.pop("SW_MCP_TOOLSETS", None)
        return {t.name: t for t in asyncio.run(server.list_tools())}


class CatalogSnapshotTests(unittest.TestCase):
    def test_catalog_matches_snapshot(self):
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        tools = full_catalog()
        self.assertEqual(sorted(expected), sorted(tools))
        for name, entry in expected.items():
            with self.subTest(tool=name):
                self.assertEqual(entry, {"description": tools[name].description,
                                         "inputSchema": tools[name].inputSchema})


    def test_connection_tools_are_listed_first(self):
        with mock.patch.object(server.config, "guarded_mode", False):
            names = [t.name for t in asyncio.run(server.list_tools())]
        self.assertEqual(
            ["get_modeling_guide", "connect_solidworks", "get_solidworks_info", "get_capabilities"],
            names[:4])

if __name__ == "__main__":
    unittest.main()
