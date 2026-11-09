# Parameter workspace V1 — first implementation stage

Implemented 2026-09-26. This is the shared local register and browser UI,
not the complete CAD-connected V1 from the design specification.

## Start

From the repository root with the project Python environment:

```powershell
./.venv/Scripts/python.exe scripts/parameter_workspace.py --open
```

The process prints a local authenticated URL and serves until interrupted.
Default port is 8765; `--port 0` chooses an available port. The URL changes
on restart. Do not reuse an old URL after restarting the process.
SQLite data remains at `output/parameter-workspace/workspace.sqlite3`.
All MCP processes from this checkout use the same database. A different
checkout has its own database; cross-checkout sharing is not implemented.
The local service listens only on 127.0.0.1 and needs no SolidWorks connection.

## Working browser features

Create an empty project or choose the stairs/railing starter structure.
The starter creates named owners, missing inputs and one derived stair rise;
it does not assume measurements or bind an arbitrary active CAD document.

Owners represent assemblies, parts, occurrences, weldment bodies, drawings
or requirements. Technical document/configuration/instance information is
stored separately and shown inside expandable details. Multiple occurrences
with the same document/configuration trigger a shared-part impact note.

Inputs support numbers (including decimal comma), integers, text, choices
and booleans. Use **Shrani osnutek** to persist a changed field. This updates
only the project register. Measurements and derived values are read-only.
Unsaved typing survives register refreshes, owner/filter changes and saves of
other fields within the open page. Closing/reloading the page still discards
unsaved typing (the browser is asked to warn). Persist a draft before leaving.
If another client changes the same parameter, the local input is retained and
marked as a conflict; review both values before discarding/re-entering a choice.
**Zavrzi vnos / osnutek** first clears local typing, or, if none exists, removes
the saved draft and restores the observed value. Saving an empty input explicitly
clears the effective value; it does not fall back to an earlier observation.
Formula creation selects existing numerical inputs and a supported binary
operation. Matching units are checked; automatic unit conversion and compound
units are not implemented in this stage. Formula links refer only to existing
parameters, so the current create-only graph cannot contain a cycle.

Search and filters distinguish missing inputs, drafts, derived values and
read-only fields.
An additional error/conflict filter separates invalid calculations from missing
inputs. Calculation errors include their reason, such as division by zero.
The owner selection filters that owner's own fields; choose all owners for the
complete project. Changes and request statuses are
recorded in history. The UI polls every 15 seconds when visible and not editing.
JSON export includes a schema version, owners, references, values and history.
Import and editing/deleting existing definitions are not implemented yet.

Requests carry the selected owner and are persisted as waiting for an agent.
Submitting a request does not wake arbitrary harnesses. Agents must read the
register and update request status themselves; there is no autonomous task runner.
This stage does not provide a leased multi-agent claim queue.

## MCP interface

Reconnect the MCP process after installing this code to load the new tools.

`read_parameter_workspace()` lists projects. Supplying `project_id` returns
owners, parameters, drafts, calculated values, missing data, requests, history,
register revision and explicit CAD capability state.

`write_parameter_workspace(action, payload, project_id?, expected_revision?)`
supports the actions below. It has the separate `project_write` operation class:
local metadata changes never bind or mutate the active CAD document.

| Action | Payload fields |
|---|---|
| create_project | `name`; optional `template: "stairs_railing"` |
| add_owner | `name`, `kind`; optional `parent_id`, `document_id`, `document_path`, `instance_path`, `configuration` |
| add_parameter | `owner_id`, `key`, `label`, `value_type`; optional `role`, `unit`, `group`, `description`, `observed_value`, `choices`, `formula`, `binding`, `source`, `reference`, `required`, `minimum`, `maximum` |
| set_draft | `parameter_id`, `value` |
| discard_draft | `parameter_id` |
| add_request | `text`; optional `owner_id` |
| update_request | `request_id`, `status` |

Read the fresh revision before editing an existing project and pass it as
`expected_revision`. A conflict returns `REVISION_CONFLICT` and leaves the
existing draft intact. Statuses are `waiting`, `in_progress`, `needs_info`,
`proposed`, `completed`, `rejected`, `cancelled`; completion describes request
handling, not proof of a CAD mutation.

Parameter types: `number`, `integer`, `text`, `boolean`, `enum`.
Roles: `input`, `derived`, `measurement`, `constraint`, `metadata`.
Formula example: `{"op":"divide","inputs":["total-height-id","rise-count-id"]}`.
Operations: add, subtract, multiply, divide. Derived/measurement/constraint
parameters cannot be overwritten by `set_draft`.
Snapshots distinguish `has_draft`, `draft_value`, `observed_value` and
`effective_value`. A draft with `null` is an intentional empty value; call
`discard_draft` to remove it. Derived failures provide `calculation_error`.
Integers must be exact and within the JavaScript safe integer range; neither
fractional input nor oversized integers are silently rounded.

Observed values and binding metadata supplied by an agent are recorded data;
they are not automatically verified against CAD. Record the source honestly.
HTTP writes use the same store and validation. The GUI token is a temporary
browser session, not an MCP credential, and is not included in exported data.

## Extension boundary

The response advertises `cad.connected=false`, `apply_available=false` and
no supported CAD operations. This is deliberate until read/write adapters
and the shared CAD execution guard are implemented and live-tested.

Later adapters should add discovery and verified operations without changing
parameter IDs, owner identity or the draft/observed distinction. Do not turn
an arbitrary binding dictionary into permission to execute code or mutate CAD.
The existing session and path guards remain the basis for actual CAD writes.

## Verification

```powershell
./.venv/Scripts/python.exe -m unittest solidworks_mcp.tests.test_parameter_workspace_v1 -q
node --test solidworks_mcp/tests/test_parameter_ui_state.cjs
```

Tests cover persistence across store instances, exact owner context, derived
values, read-only protection, stale revisions, invalid input, unit mismatch,
request status, starter structure, authorized local HTTP routes and the
MCP-to-register integration without CAD access. Browser testing separately
confirmed project creation, explicit draft saves, the 2800/16=175 calculation
and a persisted waiting request in the clearly named test project.
