import asyncio
import unittest
from collections import OrderedDict
from unittest import mock

from solidworks_mcp import server
from solidworks_mcp.core.contracts import OperationResult, OperationStatus
from solidworks_mcp.core.evidence import OperationJournal
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, tool


def _completed(operation_id):
    return OperationResult(operation_id=operation_id, status=OperationStatus.COMPLETED,
                           target_before=None, target_after=None, data={})


class Automation:
    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class JournalBoundTests(unittest.TestCase):
    def test_oldest_entries_are_dropped(self):
        journal = OperationJournal(max_entries=3)
        for index in range(5):
            journal.reserve(f"op-{index}")
            journal.mark_running(f"op-{index}")
            journal.record(_completed(f"op-{index}"))
        self.assertIsNone(journal.get("op-0"))
        self.assertIsNone(journal.get_state("op-1"))
        self.assertIsNotNone(journal.get("op-4"))
        self.assertEqual(3, len(journal._states))

    def test_default_limit_is_one_thousand(self):
        self.assertEqual(1000, OperationJournal()._max_entries)


class ServerBoundTests(unittest.TestCase):
    NAME = "_test_bounded_read"

    def setUp(self):
        self.original = server.sw_automation
        server.sw_automation = Automation()

        @tool(name=self.NAME, description="test", schema={"type": "object", "properties": {}},
              operation_class=OperationClass.READ)
        def handler(sw):
            return sw._result(True, "read")

    def tearDown(self):
        server.sw_automation = self.original
        _TOOLS.pop(self.NAME, None)

    def test_many_calls_stay_bounded_and_latest_replays(self):
        async def scenario():
            for index in range(1005):
                await server.call_tool(self.NAME, {"operation_id": f"bound-{index}"})
            first = await server.call_tool(self.NAME, {"operation_id": "bound-1004"})
            return first

        replay = asyncio.run(scenario())
        self.assertLessEqual(len(server._operation_payloads), 1000)
        self.assertLessEqual(len(server.operation_journal._states), 1000)
        self.assertTrue(replay[0].text.startswith("[SUCCESS] read"))

    def test_dropped_id_runs_again_and_both_records_drop_the_same_entries(self):
        calls = []
        _TOOLS[self.NAME]["handler"] = lambda sw: calls.append(1) or sw._result(True, "read")

        async def scenario():
            for index in range(1001):
                await server.call_tool(self.NAME, {"operation_id": f"drop-{index}"})
            executed = len(calls)
            await server.call_tool(self.NAME, {"operation_id": "drop-0"})
            return executed

        with mock.patch.object(server, "operation_journal", OperationJournal()),                 mock.patch.object(server, "_operation_payloads", OrderedDict()):
            executed = asyncio.run(scenario())
            self.assertEqual(executed + 1, len(calls))
            self.assertEqual(set(server.operation_journal._results), set(server._operation_payloads))
            self.assertNotIn("drop-1", server._operation_payloads)
            self.assertIn("drop-0", server._operation_payloads)


if __name__ == "__main__":
    unittest.main()
