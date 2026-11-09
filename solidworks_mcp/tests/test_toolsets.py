import asyncio
import os
import unittest
from unittest import mock

from solidworks_mcp import catalog, server
from solidworks_mcp.registry import registered_tools
from solidworks_mcp.tests.test_catalog_budget import catalog_bytes


def _names(env):
    with mock.patch.dict(os.environ, env, clear=False):
        return {item.name for item in asyncio.run(server.list_tools())}


class ToolsetTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SW_MCP_TOOLSETS", None)

    def test_every_tool_belongs_to_a_toolset(self):
        for item in asyncio.run(server.list_tools()):
            with self.subTest(tool=item.name):
                self.assertIn(catalog.toolset_of(item.name), catalog.TOOLSETS)

    def test_default_advertises_every_tool(self):
        self.assertEqual(len(asyncio.run(server.list_tools())), len(_names({})))
        self.assertIn("run_analysis", _names({}))

    def test_selected_toolsets_limit_the_catalog_and_keep_core(self):
        names = _names({"SW_MCP_TOOLSETS": "sketch,features"})
        self.assertIn("connect_solidworks", names)      # core, always on
        self.assertIn("restart_solidworks", names)      # core
        self.assertIn("draw_line", names)               # sketch
        self.assertIn("fillet_edges", names)            # features
        self.assertNotIn("create_structural_member", names)
        self.assertNotIn("run_analysis", names)

    def test_unknown_toolset_is_ignored_with_a_warning(self):
        with self.assertLogs("SolidWorksMCP", level="WARNING") as logs:
            names = _names({"SW_MCP_TOOLSETS": "sketch,weldment"})
        self.assertIn("draw_line", names)
        self.assertIn("weldment", "\n".join(logs.output))

    def test_config_selects_toolsets_when_env_is_absent(self):
        with mock.patch.object(server.config, "enabled_toolsets", ["assembly"]):
            names = _names({})
        self.assertIn("insert_component", names)
        self.assertNotIn("draw_line", names)

    def test_core_sketch_features_fit_the_small_budget(self):
        with mock.patch.dict(os.environ, {"SW_MCP_TOOLSETS": "core,sketch,features"}):
            tools = asyncio.run(server.list_tools())
        self.assertLessEqual(catalog_bytes(tools), 48_000)

    def test_guarded_mode_still_hides_execute_python(self):
        with mock.patch.object(server.config, "guarded_mode", True):
            self.assertNotIn("execute_python", _names({}))

    def test_capabilities_report_enabled_toolsets(self):
        with mock.patch.dict(os.environ, {"SW_MCP_TOOLSETS": "sketch"}):
            text = asyncio.run(server.call_tool("get_capabilities", {}))[0].text
        self.assertIn('"enabled": ["core", "sketch"]', text)

    def test_registry_listing_stays_unfiltered(self):
        with mock.patch.dict(os.environ, {"SW_MCP_TOOLSETS": "sketch"}):
            self.assertIn("run_analysis", {t.name for t in registered_tools()})


if __name__ == "__main__":
    unittest.main()
