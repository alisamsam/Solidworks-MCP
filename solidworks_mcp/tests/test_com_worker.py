import asyncio
import threading
import time
import unittest

from solidworks_mcp import server
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, tool


class Automation:
    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class ComWorkerTests(unittest.TestCase):
    NAME = "_test_slow_com"

    def setUp(self):
        self.original = server.sw_automation
        server.sw_automation = Automation()

        @tool(name=self.NAME, description="test", schema={"type": "object", "properties": {}},
              operation_class=OperationClass.READ)
        def handler(sw):
            time.sleep(0.3)
            return sw._result(True, "slow", 0, {"thread": threading.current_thread().name})

    def tearDown(self):
        server.sw_automation = self.original
        _TOOLS.pop(self.NAME, None)

    def test_event_loop_stays_responsive_during_a_long_call(self):
        async def scenario():
            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.02)
                    ticks += 1

            task = asyncio.create_task(ticker())
            response = await server.call_tool(self.NAME, {})
            task.cancel()
            return ticks, response[0].text

        ticks, text = asyncio.run(scenario())
        self.assertGreaterEqual(ticks, 5)
        self.assertIn("solidworks-com", text)

    def test_every_call_uses_the_same_thread(self):
        first = asyncio.run(server.call_tool(self.NAME, {}))[0].text
        second = asyncio.run(server.call_tool(self.NAME, {}))[0].text
        thread = lambda text: text.split('"thread": "', 1)[1].split('"', 1)[0]
        self.assertEqual(thread(first), thread(second))


if __name__ == "__main__":
    unittest.main()
