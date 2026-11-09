import asyncio
import threading
import unittest
from unittest import mock

from solidworks_mcp import server
from solidworks_mcp.core.contracts import DocumentRef, OperationStatus
from solidworks_mcp.core.evidence import OperationJournal
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, tool

DOCUMENT = DocumentRef("doc-1", None, "part", "Default", "mcp:0")


class Automation:
    def has_bound_document(self):
        return False

    def bind_active_document(self):
        return DOCUMENT

    def mark_active_document_mutated(self, before):
        return before

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class ServerOperationTests(unittest.TestCase):
    NAME = "_test_server_operation"

    def setUp(self):
        self.calls = []
        self.release = threading.Event()
        self.started = threading.Event()
        patches = [
            mock.patch.object(server, "sw_automation", Automation()),
            mock.patch.object(server, "operation_journal", OperationJournal()),
            mock.patch.object(server.logger, "info"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(_TOOLS.pop, self.NAME, None)
        self.payloads = {}
        patch = mock.patch.object(server, "_operation_payloads", self.payloads)
        patch.start()
        self.addCleanup(patch.stop)

    def register(self, handler, schema=None):
        tool(name=self.NAME, description="test",
             schema=schema or {"type": "object", "properties": {"size": {"type": "integer"}}},
             operation_class=OperationClass.MUTATE)(handler)

    def test_cancelled_call_still_records_and_replays_without_rerunning(self):
        def handler(sw, size=0):
            self.calls.append(size)
            self.started.set()
            self.release.wait(5)
            return sw._result(True, "built", data={"size": size})
        self.register(handler)

        async def scenario():
            pending = asyncio.ensure_future(server.call_tool(self.NAME, {"operation_id": "op-1", "size": 3}))
            while not self.started.is_set():
                await asyncio.sleep(0.01)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.release.set()
            for _ in range(200):
                if server.operation_journal.get("op-1") is not None:
                    break
                await asyncio.sleep(0.01)
            return await server.call_tool(self.NAME, {"operation_id": "op-1", "size": 3})

        replay = asyncio.run(scenario())
        self.assertEqual([3], self.calls)
        self.assertEqual(OperationStatus.COMPLETED, server.operation_journal.get("op-1").status)
        self.assertTrue(replay[0].text.startswith("[SUCCESS] built"))

    def test_validation_failure_is_not_journaled_so_the_id_can_be_reused(self):
        def handler(sw, size=0):
            self.calls.append(size)
            return sw._result(True, "built")
        self.register(handler)

        async def scenario():
            rejected = await server.call_tool(self.NAME, {"operation_id": "op-2", "size": "x"})
            accepted = await server.call_tool(self.NAME, {"operation_id": "op-2", "size": 4})
            return rejected, accepted

        rejected, accepted = asyncio.run(scenario())
        self.assertTrue(rejected[0].text.startswith("[ERROR]"))
        self.assertTrue(accepted[0].text.startswith("[SUCCESS] built"))
        self.assertEqual([4], self.calls)

    def test_validation_failure_leaves_no_record(self):
        self.register(lambda sw, size=0: sw._result(True, "built"))
        asyncio.run(server.call_tool(self.NAME, {"operation_id": "op-3", "size": "x"}))
        self.assertIsNone(server.operation_journal.get("op-3"))
        self.assertIsNone(server.operation_journal.get_state("op-3"))
        self.assertNotIn("op-3", self.payloads)

    def test_handler_exception_keeps_the_document_it_started_from(self):
        def handler(sw, size=0):
            raise RuntimeError("com exploded")
        self.register(handler)
        asyncio.run(server.call_tool(self.NAME, {"operation_id": "op-4"}))
        recorded = server.operation_journal.get("op-4")
        self.assertEqual(OperationStatus.FAILED, recorded.status)
        self.assertEqual(DOCUMENT, recorded.target_before)


    def test_tool_without_com_runs_while_the_com_thread_is_busy(self):
        def slow(sw, size=0):
            self.started.set()
            self.release.wait(5)
            return sw._result(True, "slow")
        self.register(slow)
        tool(name=self.NAME + "_guide", description="test", schema={"type": "object", "properties": {}},
             operation_class=OperationClass.READ, com=False)(lambda sw: sw._result(True, "guide"))
        self.addCleanup(_TOOLS.pop, self.NAME + "_guide", None)

        async def scenario():
            busy = asyncio.ensure_future(server.call_tool(self.NAME, {}))
            while not self.started.is_set():
                await asyncio.sleep(0.01)
            try:
                return await asyncio.wait_for(server.call_tool(self.NAME + "_guide", {}), 2)
            finally:
                self.release.set()
                await busy

        self.assertTrue(asyncio.run(scenario())[0].text.startswith("[SUCCESS] guide"))

if __name__ == "__main__":
    unittest.main()
