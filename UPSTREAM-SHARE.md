# Author review package

This branch extends Samsaam Ali Baig's SolidWorks MCP project. It contains
the complete product tool implementation, shared modeling knowledge, unit
tests and opt-in live tests. Tests are kept in the same branch, outside the
runtime modules. No private mechanical-design skill is required to run it.

## Start here

- Runtime: `solidworks_mcp_server.py`, `solidworks_mcp/server.py`.
- Tool registration and filtering: `solidworks_mcp/registry.py`, `solidworks_mcp/catalog.py`.
- Implementations: `solidworks_mcp/tools/`.
- [Tests and verification commands](solidworks_mcp/tests/README.md).
- [Examples and live demonstration safety](examples/README.md).
- Human-facing tool examples: `scripts/user_tool_examples.txt`.
- Shared client instructions: `solidworks_mcp/knowledge/server-instructions.txt`.

## Complete tool coverage

At preparation time the registry contains 249 tools across these toolsets:

| Toolset | Registered tools |
|---|---:|
| core | 31 |
| sketch | 34 |
| sketch_edit | 16 |
| features | 35 |
| surfaces | 12 |
| assembly | 29 |
| drawing | 7 |
| sheetmetal | 11 |
| weldments | 10 |
| simulation | 8 |
| project | 33 |
| planners | 5 |
| routing | 18 |

Toolset selection changes discovery, not which implementations are shipped.
Routing is additionally permission-gated at dispatch. An unset toolset filter
exposes ordinary toolsets, but does not implicitly enable routing. To review
the full catalog in PowerShell:

```powershell
$env:SW_MCP_TOOLSETS = 'core,sketch,sketch_edit,features,surfaces,assembly,drawing,sheetmetal,weldments,simulation,project,planners,routing'
$env:SW_MCP_ROUTING_ENABLED = 'true'
.\.venv\Scripts\python.exe solidworks_mcp_server.py
```

This starts a stdio MCP server for a client, not an interactive command prompt.
Put the same environment variables in the MCP client's server configuration.
Use `get_capabilities` for the actual advertised tools. `guarded_mode` hides
`execute_python`, so a guarded full catalog contains 248 tools. Keeping routing
off or reducing the client's toolsets does not remove code or tests.

## Setup and operating limits

Use native Windows Python and the interactive Windows session that owns
SolidWorks. Install dependencies into a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest
```

`solidworks_mcp/config.json` uses generic installation discovery. Before CAD
work, review templates and configure `guarded_mode: true`, absolute writable
`output_roots` and any read-only `protected_roots` for the target machine.
The upstream-compatible default is not a sandbox. Never expose this stdio
process through an unauthenticated network bridge.

Run only one CAD client at a time. COM call serialization within one server
does not provide ownership across multiple server processes. Live tests,
demonstrations and an agent must not control the same session concurrently.
Available code does not imply that every operation works with every version,
license, add-in, template or Toolbox installation.

## Scope and review order

Review registry/catalog and document/path guards first, then COM execution,
feature toolsets, project workflows and optional routing. The parameter
workspace is a separate local HTTP UI, not an MCP HTTP transport. Review its
access boundaries before using it outside a local trusted workstation.

The package includes no personal CAD project, private skill, local agent
configuration or `.env` at the branch tip. A previous project-specific
assembly script is excluded because it closed open documents and depended
on a personal stair project. Its removal does not remove an MCP tool.

This is not a history rewrite. Older inherited commits may contain files
removed from the branch tip. Any credential previously committed must be
revoked or rotated independently of this packaging work.
