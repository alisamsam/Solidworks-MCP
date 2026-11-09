"""RT0 Routing status: config gate, verified files only, unknown readiness."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from solidworks_mcp import catalog, registry
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, _load
from solidworks_mcp.tools import routing


class _SwStub:
    """Stub that fails loudly if the tool touches anything but _result()."""

    def _result(self, success, message, error_code=SwErrors.swSuccess, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "error_name": error_code.name,
            "data": data or {},
        }

    def __getattr__(self, name):
        raise AssertionError(f"get_routing_status must not touch sw.{name}")


def _install_info(root, found=True, version="2025"):
    return {"found": found, "install_dir": str(root) if root else None,
            "version": version, "exe_path": None, "templates": {}}


class RoutingStatusTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def _run(self, info, enabled=True):
        with patch.object(catalog, "routing_enabled", return_value=enabled), \
                patch.object(routing, "get_solidworks_info", return_value=info):
            return routing.get_routing_status(_SwStub())

    def test_registered_read_only_without_com(self):
        _load()
        entry = _TOOLS["get_routing_status"]
        self.assertIs(entry["operation_class"], OperationClass.READ)
        self.assertFalse(entry["com"])
        self.assertIsNone(entry["postflight"])
        self.assertEqual(entry["handler"].__module__, "solidworks_mcp.tools.routing")

    def test_disabled_gate_rejects_before_scanning(self):
        scan = Mock()
        with patch.object(catalog, "routing_enabled", return_value=False), \
                patch.object(routing, "get_solidworks_info", scan):
            result = routing.get_routing_status(_SwStub())
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "ROUTING_DISABLED")
        scan.assert_not_called()

    def test_registry_rejects_before_handler_when_disabled(self):
        _load()
        sw = Mock()
        sw._result.side_effect = lambda success, message, error, data=None: {
            "success": success, "message": message, "data": data or {}}
        handler = Mock()
        entry = dict(_TOOLS["get_routing_status"], handler=handler)
        with patch.dict(_TOOLS, {"get_routing_status": entry}), \
                patch.object(catalog, "toolset_of", return_value="routing"), \
                patch.object(catalog, "routing_enabled", return_value=False):
            result = registry.execute("get_routing_status", sw, {}).result
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["code"], "ROUTING_DISABLED")
        handler.assert_not_called()

    def test_verified_files_reported_and_readiness_unknown(self):
        (self.root / "sldrtadd.dll").write_bytes(b"addin")
        (self.root / "SWRoutingLib.tlb").write_bytes(b"typelib")
        result = self._run(_install_info(self.root))

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["configuration"]["routing_enabled"])
        verified = {item["name"] for item in data["routing_files"]["verified"]}
        self.assertEqual(verified, {"sldrtadd.dll", "SWRoutingLib.tlb"})
        missing = {item["name"] for item in data["routing_files"]["missing"]}
        self.assertEqual(missing, {"SolidWorks.Interop.SWRoutingLib.dll"})
        readiness = data["readiness"]
        self.assertTrue(readiness["installed_files_verified"])
        self.assertEqual(readiness["license"], "unknown")
        self.assertEqual(readiness["addin_loaded"], "unknown")
        self.assertEqual(readiness["library_ready"], "unknown")

    def test_interop_found_in_bounded_subdir(self):
        redist = self.root / "api" / "redist"
        redist.mkdir(parents=True)
        (redist / "SolidWorks.Interop.SWRoutingLib.dll").write_bytes(b"interop")
        result = self._run(_install_info(self.root))
        verified = {item["name"]: item for item in result["data"]["routing_files"]["verified"]}
        self.assertIn("SolidWorks.Interop.SWRoutingLib.dll", verified)
        self.assertIn("api", verified["SolidWorks.Interop.SWRoutingLib.dll"]["path"])

    def test_partial_install_does_not_infer_library_readiness(self):
        (self.root / "sldrtadd.dll").write_bytes(b"addin")
        result = self._run(_install_info(self.root))
        data = result["data"]
        self.assertTrue(data["readiness"]["installed_files_verified"])
        self.assertEqual(data["readiness"]["library_ready"], "unknown")
        missing = {item["name"] for item in data["routing_files"]["missing"]}
        self.assertIn("SWRoutingLib.tlb", missing)

    def test_missing_files_carry_no_size_or_path(self):
        result = self._run(_install_info(self.root))
        for item in result["data"]["routing_files"]["missing"]:
            self.assertNotIn("path", item)
            self.assertNotIn("size_bytes", item)

    def test_installation_not_found_reports_unknown_readiness(self):
        result = self._run(_install_info(None, found=False, version=None))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_name"], "swSolidWorksNotFound")
        data = result["data"]
        self.assertTrue(data["configuration"]["routing_enabled"])
        self.assertFalse(data["installation"]["found"])
        self.assertEqual(data["routing_files"]["verified"], [])
        self.assertEqual(data["routing_files"]["missing_count"], 3)
        self.assertFalse(data["readiness"]["installed_files_verified"])
        self.assertEqual(data["readiness"]["license"], "unknown")

    def test_never_imports_com_layer(self):
        self.assertFalse(hasattr(routing, "com"))
        self.assertNotIn("comutil", routing.__dict__)


if __name__ == "__main__":
    unittest.main()
