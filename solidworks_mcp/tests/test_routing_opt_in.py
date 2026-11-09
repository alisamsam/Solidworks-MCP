"""Routing visibility and execution permission are separate, fail-closed gates."""

import os
import unittest
from unittest.mock import Mock, patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.config import SolidWorksConfig
from solidworks_mcp.core.policy import OperationClass


class RoutingOptInTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.config = SolidWorksConfig()
        self.cfg = patch.object(catalog, "get_config", return_value=self.config)
        self.cfg.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.cfg.stop)

    def test_default_excludes_routing_only(self):
        self.assertFalse(catalog.routing_enabled())
        self.assertEqual(set(catalog.enabled_toolsets()), set(catalog.TOOLSETS) - {"routing"})

    def test_catalog_request_alone_is_not_permission(self):
        os.environ["SW_MCP_TOOLSETS"] = "core,routing,assembly"
        self.assertEqual(catalog.enabled_toolsets(), ["assembly", "core"])

    def test_permission_does_not_implicitly_advertise(self):
        self.config.routing_enabled = True
        self.assertTrue(catalog.routing_enabled())
        self.assertNotIn("routing", catalog.enabled_toolsets())

    def test_config_opt_in_and_explicit_selection(self):
        self.config.routing_enabled = True
        self.config.enabled_toolsets = ["routing", "assembly"]
        self.assertEqual(catalog.enabled_toolsets(), ["assembly", "core", "routing"])

    def test_environment_permission_is_strict_and_overrides_config(self):
        self.config.routing_enabled = True
        for value, expected in [("true", True), (" TRUE ", True), ("false", False),
                                ("1", False), ("", False), ("invalid", False)]:
            with self.subTest(value=value):
                os.environ["SW_MCP_ROUTING_ENABLED"] = value
                self.assertEqual(catalog.routing_enabled(), expected)

    def test_nonboolean_config_does_not_enable(self):
        self.config.routing_enabled = "false"
        self.assertFalse(catalog.routing_enabled())

    def test_dispatch_rejects_before_handler_or_document_binding(self):
        registry.registered_tools()
        handler = Mock()
        entry = dict(registry._TOOLS["get_routing_status"], handler=handler,
                     operation_class=OperationClass.MUTATE)
        sw = Mock()
        sw._result.side_effect = lambda success, message, error, data=None: {
            "success": success, "message": message, "data": data or {}}
        with patch.dict(registry._TOOLS, {"get_routing_status": entry}), \
                patch.object(catalog, "toolset_of", return_value="routing"):
            result = registry.execute("get_routing_status", sw, {}).result
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "ROUTING_DISABLED")
        handler.assert_not_called()
        sw.bind_active_document.assert_not_called()
        sw.require_bound_active_document.assert_not_called()

    def test_ordinary_hidden_tool_still_executes(self):
        os.environ["SW_MCP_TOOLSETS"] = "core"
        registry.registered_tools()
        sw = Mock()
        handler = Mock(return_value={"success": True})
        entry = dict(registry._TOOLS["create_new_part"], handler=handler,
                     operation_class=OperationClass.READ, postflight=None)
        with patch.dict(registry._TOOLS, {"create_new_part": entry}):
            self.assertTrue(registry.execute("create_new_part", sw, {}).result["success"])
        handler.assert_called_once()

    def test_tool_advertised_only_with_both_opt_ins(self):
        self.assertNotIn("get_routing_status", catalog.advertised_tool_names())
        os.environ["SW_MCP_TOOLSETS"] = "core,routing"
        self.assertNotIn("get_routing_status", catalog.advertised_tool_names())
        os.environ["SW_MCP_ROUTING_ENABLED"] = "true"
        self.assertIn("get_routing_status", catalog.advertised_tool_names())

    def test_disabled_call_is_rejected_without_session_observation(self):
        from solidworks_mcp import server
        sw = Mock()
        sw._result.side_effect = lambda success, message, error, data=None: {
            "success": success, "message": message, "data": data or {}}
        with patch.object(server.session_monitor, "observe") as observe:
            execution, warnings = server._run_tool(None, "get_routing_status", sw, {})
        self.assertTrue(server._is_rejected(execution))
        observe.assert_not_called()
        self.assertEqual(warnings, ())

    def test_call_tool_rejection_releases_operation_id(self):
        import asyncio
        from uuid import uuid4
        from solidworks_mcp import server
        operation_id = str(uuid4())
        sw = Mock()
        sw._result.side_effect = lambda success, message, error, data=None: {
            "success": success, "message": message, "error_code": int(error),
            "error_name": error.name, "data": data or {}}

        async def immediate(function, *args):
            return function(*args)

        with patch.object(server, "sw_automation", sw), \
                patch.object(server, "run_beside_com", side_effect=immediate), \
                patch.object(server.session_monitor, "observe") as observe:
            content = asyncio.run(server.call_tool(
                "get_routing_status", {"operation_id": operation_id}))
        self.assertIn("ROUTING_DISABLED", content[0].text)
        self.assertNotIn(operation_id, server._operation_payloads)
        observe.assert_not_called()
        # Reusing this ID is a new reservation, not replay of the rejected call.
        self.assertIsNone(server.operation_journal.reserve(operation_id))
        server.operation_journal.discard(operation_id)


if __name__ == "__main__":
    unittest.main()
