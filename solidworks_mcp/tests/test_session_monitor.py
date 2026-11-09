import unittest

from solidworks_mcp.session_monitor import SessionMonitor


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class App:
    def __init__(self):
        self.count = 1

    def GetDocumentCount(self):
        return self.count


class PidApp(App):
    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    def GetProcessID(self):
        return self.pid


class Automation:
    def __init__(self):
        self.app = App()
        self.is_connected = True


class Gpu:
    def __init__(self, value=100.0):
        self.value = value
        self.reads = 0

    def __call__(self, sw):
        self.reads += 1
        return self.value


def monitor(gpu=None):
    clock = Clock()
    return SessionMonitor(clock=clock, gpu_reader=gpu or Gpu()), clock


class CountingTests(unittest.TestCase):
    def test_document_count_changes_are_counted(self):
        watcher, _ = monitor()
        sw = Automation()
        watcher.observe(sw, "connect_solidworks", True)   # baseline 1
        sw.app.count = 3
        watcher.observe(sw, "open_document", True)
        sw.app.count = 2
        watcher.observe(sw, "close_document", True)
        snapshot = watcher.snapshot()
        self.assertEqual(2, snapshot["documents_opened"])
        self.assertEqual(1, snapshot["documents_closed"])

    def test_disconnected_session_is_not_observed(self):
        watcher, _ = monitor()
        sw = Automation()
        sw.is_connected = False
        self.assertEqual((), watcher.observe(sw, "open_document", True))
        self.assertEqual(0, watcher.snapshot()["documents_opened"])

    def test_successful_restart_resets_counters(self):
        watcher, _ = monitor()
        sw = Automation()
        watcher.observe(sw, "connect_solidworks", True)
        sw.app.count = 0
        watcher.observe(sw, "close_document", True)
        watcher.observe(sw, "restart_solidworks", True)
        self.assertEqual(0, watcher.snapshot()["documents_closed"])

    def test_changed_process_id_resets_counters(self):
        watcher, _ = monitor()
        sw = Automation()
        sw.app = PidApp(100)
        sw.app.count = 5
        watcher.observe(sw, "connect_solidworks", True)
        sw.app.count = 0
        watcher.observe(sw, "close_document", True)
        self.assertEqual(5, watcher.snapshot()["documents_closed"])
        sw.app = PidApp(200)                  # SolidWorks crashed or was restarted by hand
        sw.app.count = 1
        watcher.observe(sw, "open_document", True)
        snapshot = watcher.snapshot()
        self.assertEqual(0, snapshot["documents_closed"])
        self.assertEqual(0, snapshot["documents_opened"])

    def test_failed_restart_keeps_counters(self):
        watcher, _ = monitor()
        sw = Automation()
        watcher.observe(sw, "connect_solidworks", True)
        sw.app.count = 0
        watcher.observe(sw, "close_document", True)
        watcher.observe(sw, "restart_solidworks", False)
        self.assertEqual(1, watcher.snapshot()["documents_closed"])


class GpuSamplingTests(unittest.TestCase):
    def test_gpu_is_sampled_on_lifecycle_tools_and_every_minute(self):
        gpu = Gpu()
        watcher, clock = monitor(gpu)
        sw = Automation()
        watcher.observe(sw, "draw_line", True)          # first observation samples
        clock.now = 10
        watcher.observe(sw, "draw_line", True)          # too soon
        clock.now = 20
        watcher.observe(sw, "open_document", True)      # lifecycle
        clock.now = 81
        watcher.observe(sw, "draw_line", True)          # 61 s after the last sample
        self.assertEqual(3, gpu.reads)
        self.assertEqual(100.0, watcher.snapshot()["gpu_dedicated_mb"])


class WarningTests(unittest.TestCase):
    def test_high_gpu_memory_warns_once_per_interval(self):
        watcher, clock = monitor(Gpu(5000.0))
        sw = Automation()
        first = watcher.observe(sw, "open_document", True)
        clock.now = 100
        second = watcher.observe(sw, "open_document", True)
        clock.now = 1000
        third = watcher.observe(sw, "open_document", True)
        self.assertEqual(1, len(first))
        self.assertIn("GPU memory 5000 MB", first[0])
        self.assertIn("ask the user before calling restart_solidworks", first[0])
        self.assertEqual((), second)
        self.assertEqual(1, len(third))

    def test_many_closed_documents_warn(self):
        watcher, _ = monitor()
        sw = Automation()
        sw.app.count = 200
        watcher.observe(sw, "connect_solidworks", True)
        sw.app.count = 0
        warnings = watcher.observe(sw, "close_document", True)
        self.assertIn("200 documents closed", warnings[0])

    def test_unknown_gpu_memory_does_not_warn(self):
        watcher, _ = monitor(Gpu(None))
        self.assertEqual((), watcher.observe(Automation(), "open_document", True))


import asyncio
from unittest import mock

from solidworks_mcp import server
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, tool


class ResultAutomation:
    is_connected = False

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class ServerWiringTests(unittest.TestCase):
    NAME = "_test_monitored"
    BESIDE = "_test_monitored_beside"

    def setUp(self):
        self.original = server.sw_automation
        server.sw_automation = ResultAutomation()

        @tool(name=self.NAME, description="test", schema={"type": "object", "properties": {}},
              operation_class=OperationClass.READ)
        def handler(sw):
            return sw._result(True, "read")

        @tool(name=self.BESIDE, description="test", schema={"type": "object", "properties": {}},
              operation_class=OperationClass.READ, com=False)
        def beside(sw):
            return sw._result(True, "read")

    def tearDown(self):
        server.sw_automation = self.original
        _TOOLS.pop(self.NAME, None)
        _TOOLS.pop(self.BESIDE, None)

    def test_monitor_warning_reaches_the_response(self):
        with mock.patch.object(server.session_monitor, "observe",
                               return_value=("Long SolidWorks session: test.",)) as observe:
            response = asyncio.run(server.call_tool(self.NAME, {}))
        observe.assert_called_once_with(server.sw_automation, self.NAME, True)
        self.assertTrue(response[0].text.startswith("[SUCCESS] read"))
        self.assertIn("Long SolidWorks session: test.", response[0].text)

    def test_monitor_failure_never_breaks_the_result(self):
        with mock.patch.object(server.session_monitor, "observe",
                               side_effect=RuntimeError("COM gone")):
            response = asyncio.run(server.call_tool(self.NAME, {}))
        self.assertTrue(response[0].text.startswith("[SUCCESS] read"))
        self.assertNotIn("COM gone", response[0].text)

    def test_replay_returns_the_same_text_including_the_warning(self):
        with mock.patch.object(server.session_monitor, "observe",
                               return_value=("Long SolidWorks session: test.",)) as observe:
            first = asyncio.run(server.call_tool(self.NAME, {"operation_id": "replay-1"}))
            second = asyncio.run(server.call_tool(self.NAME, {"operation_id": "replay-1"}))
        observe.assert_called_once()
        self.assertIn("Long SolidWorks session: test.", first[0].text)
        self.assertEqual(first[0].text, second[0].text)

    def test_rejected_call_does_not_consume_the_warning(self):
        @tool(name=self.NAME + "_strict", description="test",
              schema={"type": "object", "properties": {"x": {"type": "number"}},
                      "required": ["x"], "additionalProperties": False},
              operation_class=OperationClass.READ)
        def strict(sw, x):
            return sw._result(True, "read")

        try:
            with mock.patch.object(server.session_monitor, "observe") as observe:
                response = asyncio.run(server.call_tool(self.NAME + "_strict", {}))
            self.assertIn("VALIDATION_FAILED", response[0].text)
            observe.assert_not_called()
        finally:
            _TOOLS.pop(self.NAME + "_strict", None)

    def test_tool_that_never_touches_com_skips_the_monitor(self):
        with mock.patch.object(server.session_monitor, "observe") as observe:
            response = asyncio.run(server.call_tool(self.BESIDE, {}))
        observe.assert_not_called()
        self.assertTrue(response[0].text.startswith("[SUCCESS] read"))


if __name__ == "__main__":
    unittest.main()
