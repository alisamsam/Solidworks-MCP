import asyncio
import unittest
from types import SimpleNamespace

from mcp.server.lowlevel.server import request_ctx

from solidworks_mcp import server
from solidworks_mcp.core import progress
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, tool


class Clock:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


class ReportProgressTests(unittest.TestCase):
    def test_without_scope_nothing_happens(self):
        progress.report_progress(1, 2, "ignored")

    def test_updates_are_throttled_but_the_final_one_is_sent(self):
        sent = []
        clock = Clock(0.0, 0.1, 0.7, 0.8)
        with progress.progress_scope(lambda *args: sent.append(args)):
            progress.report_progress(1, 10, "a", clock=clock)   # sent
            progress.report_progress(2, 10, "b", clock=clock)   # 0.1 s later: dropped
            progress.report_progress(3, 10, "c", clock=clock)   # 0.7 s: sent
            progress.report_progress(10, 10, "d", clock=clock)  # final: sent
        self.assertEqual([(1, 10, "a"), (3, 10, "c"), (10, 10, "d")], sent)

    def test_reporter_errors_never_reach_the_tool(self):
        def broken(*args):
            raise RuntimeError("client gone")

        with progress.progress_scope(broken):
            progress.report_progress(1, 1, "done")

    def test_scope_restores_the_previous_reporter(self):
        outer, inner = [], []
        with progress.progress_scope(lambda *a: outer.append(a)):
            with progress.progress_scope(lambda *a: inner.append(a)):
                progress.report_progress(1, 1)
            progress.report_progress(1, 1)
        self.assertEqual(1, len(inner))
        self.assertEqual(1, len(outer))


class Session:
    def __init__(self):
        self.sent = []

    async def send_progress_notification(self, token, progress_value, total=None, message=None,
                                         related_request_id=None):
        self.sent.append((token, progress_value, total, message, related_request_id))


class Automation:
    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class ServerProgressTests(unittest.TestCase):
    NAME = "_test_progress"

    def setUp(self):
        self.original = server.sw_automation
        server.sw_automation = Automation()

        @tool(name=self.NAME, description="test", schema={"type": "object", "properties": {}},
              operation_class=OperationClass.READ)
        def handler(sw):
            progress.report_progress(1, 2, "half")
            progress.report_progress(2, 2, "done")
            return sw._result(True, "ok")

    def tearDown(self):
        server.sw_automation = self.original
        _TOOLS.pop(self.NAME, None)

    def _call(self, meta):
        session = Session()

        async def scenario():
            context = SimpleNamespace(request_id=7, meta=meta, session=session, lifespan_context=None)
            token = request_ctx.set(context)
            try:
                response = await server.call_tool(self.NAME, {})
            finally:
                request_ctx.reset(token)
            await asyncio.sleep(0.05)
            return response

        response = asyncio.run(scenario())
        return session.sent, response[0].text

    def test_progress_token_produces_notifications(self):
        sent, text = self._call(SimpleNamespace(progressToken="tok"))
        self.assertTrue(text.startswith("[SUCCESS]"))
        self.assertEqual([("tok", 1, 2, "half", 7), ("tok", 2, 2, "done", 7)], sent)

    def test_no_progress_token_sends_nothing(self):
        sent, text = self._call(None)
        self.assertTrue(text.startswith("[SUCCESS]"))
        self.assertEqual([], sent)


if __name__ == "__main__":
    unittest.main()
