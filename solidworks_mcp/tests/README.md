# Tests for author review

Run commands from the repository root. Install `requirements.txt` and `pytest`
in a Windows virtual environment first. The tests use pywin32 imports, but the
offline suite does not require a running SolidWorks instance.

## Offline suite

```powershell
.\.venv\Scripts\python.exe -m pytest solidworks_mcp/tests --ignore=solidworks_mcp/tests/live -q
```

The explicit ignore keeps live COM tests out even if `SW_MCP_LIVE_TESTS` is
already set in the calling environment. This covers schemas, dispatch, mocks,
document/session guards, path policy, toolsets, geometry helpers and project
contracts. Passing mocks do not establish native CAD correctness.

The browser parameter-state test is separate from Python discovery. If Node.js
is installed, run it with:

```powershell
node --test solidworks_mcp/tests/test_parameter_ui_state.cjs
```

Smaller review examples:

```powershell
.\.venv\Scripts\python.exe -m pytest solidworks_mcp/tests/test_toolsets.py solidworks_mcp/tests/test_routing_opt_in.py -q
.\.venv\Scripts\python.exe -m pytest solidworks_mcp/tests/test_document_save_safety.py solidworks_mcp/tests/test_policy.py -q
```

The real stdio knowledge handshake can also be checked without connecting to CAD:

```powershell
Remove-Item Env:SW_MCP_TOOLSETS -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe scripts/verify_modeling_guidance.py
```

This uses the real server and may create normal server logs or local workspace
state. It checks discovery, instructions, resources and shared guide content.

## Live COM tests, explicit opt-in only

Use a disposable SolidWorks session with no user work open. Review the selected
test and `live/_scratch.py` before execution. Tests create documents, change
selection and may save files to configured output roots. Some depend on
templates, add-ins, standard profiles, sample models or license capabilities.
Set `guarded_mode: true` and valid absolute `output_roots` in
`solidworks_mcp/config.json` first. Routing tests also need the separate
`SW_MCP_ROUTING_ENABLED=true` permission and the relevant SolidWorks add-in.
Do not run the entire live directory blindly on a working CAD session.

One focused scratch example:

```powershell
$env:SW_MCP_LIVE_TESTS = '1'
$env:SW_MCP_KEEP_REVIEW = '1'
try {
    .\.venv\Scripts\python.exe -m unittest solidworks_mcp.tests.live.test_sketch_entities -v
} finally {
    Remove-Item Env:SW_MCP_LIVE_TESTS -ErrorAction SilentlyContinue
    Remove-Item Env:SW_MCP_KEEP_REVIEW -ErrorAction SilentlyContinue
}
```

Record the SolidWorks revision, add-ins, exact test command, output roots and
result alongside any screenshots. A skipped test is not a passed live check.
Never use parallel test workers against the same SolidWorks instance.

## Verification at package preparation

On 2026-11-09 the public worktree's offline suite returned:

```text
1607 passed, 1 skipped, 1743 subtests passed
```

The full opt-in registry was also enumerated without CAD: 249 tools. No live
COM tests were run for this packaging change. Historical live evidence in
fixtures and scripts is not a fresh verification on the recipient's machine.
