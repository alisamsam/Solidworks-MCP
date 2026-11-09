"""Live check over MCP stdio: CAD tools run on the COM thread while pings stay fast.

Requires a running SolidWorks. Creates one unsaved part and closes it without saving.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STEPS = [
    ("connect_solidworks", {}),
    ("create_new_part", {}),
    ("create_sketch", {"plane": "Front"}),
    ("draw_rectangle", {"x1": -20, "y1": -10, "x2": 20, "y2": 10, "unit": "mm"}),
    ("extrude_sketch", {"depth": 10, "unit": "mm"}),
    ("list_features", {}),
]


async def _ping_while(session, call):
    task = asyncio.create_task(call)
    delays = []
    while not task.done():
        started = time.monotonic()
        await session.send_ping()
        delays.append(time.monotonic() - started)
        await asyncio.sleep(0.05)
    return await task, delays


async def verify():
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(command=sys.executable,
                                       args=[str(root / 'solidworks_mcp_server.py')],
                                       cwd=str(root))
    report = {"steps": [], "max_ping_s": 0.0}
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                for name, arguments in STEPS:
                    response, delays = await _ping_while(session, session.call_tool(name, arguments))
                    text = response.content[0].text
                    report["steps"].append({"tool": name, "ok": text.startswith("[SUCCESS]")})
                    report["max_ping_s"] = max([report["max_ping_s"], *delays])
                    assert text.startswith("[SUCCESS]"), f"{name}: {text[:300]}"
                assert "Boss-Extrude1" in text or "Extrusion" in text, text[:300]
            finally:
                closed = await session.call_tool("close_document", {"save": False})
                report["closed"] = closed.content[0].text.startswith("[SUCCESS]")
    assert report["max_ping_s"] < 1.0, report
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    asyncio.run(verify())
