"""Verify knowledge over the real MCP stdio transport without connecting to CAD."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(command=sys.executable,
                                       args=[str(root / 'solidworks_mcp_server.py')],
                                       cwd=str(root))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.instructions and 'get_modeling_guide' in init.instructions
            tools = await session.list_tools()
            assert 'get_modeling_guide' in {tool.name for tool in tools.tools}
            assert {'read_parameter_workspace', 'write_parameter_workspace'} <= {tool.name for tool in tools.tools}
            workspace = await session.call_tool('read_parameter_workspace', {})
            assert '[SUCCESS]' in workspace.content[0].text
            resources = await session.list_resources()
            index = await session.call_tool('get_modeling_guide', {'topic': 'index'})
            assert '[SUCCESS]' in index.content[0].text
            guide = await session.call_tool('get_modeling_guide', {'topic': 'workflow/weldment'})
            assert '[SUCCESS]' in guide.content[0].text
            resource = await session.read_resource('solidworks://guides/workflow/weldment')
            data = json.loads(resource.contents[0].text)
            assert data['content_sha256'] in guide.content[0].text
            assert 'create_structural_member' in data['available_tools']
            print(json.dumps({'tools': len(tools.tools), 'resources': len(resources.resources),
                              'instructions': True, 'shared_content': True,
                              'cad_connected_by_test': False}, indent=2))


if __name__ == '__main__':
    asyncio.run(verify())
