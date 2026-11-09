# Engineering workflow package

Use current tool schemas, not assumed API availability. Tools may expose a
bounded subset (e.g. supported feature types, native-file references, one
active configuration). Unsupported actions must be reported, never simulated.

## Adapt existing work

1. Inspect references; copy to a new approved directory. Keep originals intact.
2. Inspect dependencies, existing drivers and model health. Determine which
   parts/configurations/occurrences are affected. Exact dimensions do not convey
   engineering intent: confirm whether height is profile length, rise, or total.
3. For several dimensions use apply_parameter_changes with explicit old values,
   units, configurations, and optional copied root_document. All requested
   dimensions preflight before any write; later rebuilds may still fail. This
   batch is not atomic and never promises rollback.
4. For one occurrence use make_component_independent; inspect resulting mates.
   For feature/pattern edits use supported typed actions. Never request generic
   COM property injection. Configuration switches must be explicit.
5. Compare health before/after; check_interferences detects volume overlaps,
   not load capacity. Distinguish allowed contacts from unintended overlap.
6. Saved checkpoint copies are independent backups, not snapshots of unsaved
   memory. Save only working copies when authorized.
7. present_result selects the exact copied file and view. Visible=True or
   activation in the COM session does not prove the user's desktop displays it.
   Give the final absolute file path; showing only the final result is allowed.

## Parameter workspace via MCP

import_parameter_workspace creates a fresh project from dimensions of a verified
active copy and its native references. Imported labels are technical; confirm
engineering meanings instead of pretending every dimension is understood.
The original demo/project register must not be overwritten.

GUI drafts are not CAD writes. The GUI queues an immutable job including exact
bindings and old/new values. Read read_parameter_workspace to find cad_jobs.
Execute process_parameter_workspace_job(project_id, job_id) on the MCP thread.
No background HTTP worker creates a second COM session. Completed jobs update
observed values; newer user drafts are retained. Failed jobs retain drafts and
report partial CAD outcomes. A job left running after process interruption needs
inspection and reconciliation; never retry it blindly.

The workspace connected flag does not imply a persistent COM connection. Queue
availability and confirmed job results are separate from host connection status.

## Engineering and manufacturing

plan_stair, plan_railing and plan_segments produce calculations, proposed
parameters and missing-input questions. They do not construct verified CAD or
certify compliance. Plans must name measuring references, landing/flight
conventions and user-defined limits. review_galvanizing is a rule-based review
using provider instructions and explicit immersion orientation, not automatic
approval of holes or closed cavities.

build_manufacturing_package exports a manifest of actual generated artifacts;
partial failure is not a manufacturing-ready package. update_drawing_package
rebuild evidence does not verify every dimension, annotation, sheet or fit.
compare_project_versions states whether comparison covers saved bytes or
semantic driver evidence; relinked file bytes alone do not prove shape change.

Current evidence and limitations: docs/upgrade/PROJECT-LIFECYCLE.md,
CAD-WORKFLOWS.md and MANUFACTURING-PLANNERS.md. Live evidence is separate from
unit tests and advertised schemas. End-to-end MCP tests must use actual transport;
calling Python handlers directly proves only the handler/COM implementation.
