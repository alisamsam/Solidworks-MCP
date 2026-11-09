# Shared SolidWorks expert knowledge — phase 1

The maintained skill is `../solidworks-2025-expert/SKILL.md`. It is served
by MCP resources and `get_modeling_guide` and loaded directly by the project's
OpenCode configuration. The old user-local synchronized entrypoint redirects
to this source; it is not another maintained copy. A synchronization service
may replace that entrypoint, so verify it if that service updates the skill.

## MCP interface

- Initialization instructions: `../server-instructions.txt`, deliberately short.
- `get_modeling_guide(topic="index")`: list exact IDs before reading a topic.
- `get_modeling_guide(topic="workflow/part")`: ordered guidance, available and
  unavailable recommended tools, plus compact recorded evidence when installed.
- `solidworks://guides/index` and `solidworks://guides/<topic>`: identical
  source content over MCP resources. Relative file links are rewritten to
  resource URIs where a topic exists. The guide tool is the fallback for
  clients that do not expose resources to the model.

Topic IDs are an allowlist. The interface accepts no arbitrary file paths,
does not connect to SolidWorks and executes no CAD commands. Module notes
are instructional material and require current documentation checks for
specific version/licensing claims. Tool evidence is historical, drawn from
`scripts/capability_requirements.json` when available; a missing evidence
file is explicitly reported. No workflow is labeled fully live-verified.

Use the active schemas to supply arguments. Adding guidance does not reduce
the number of advertised CAD tools or replace validation/path/session guards.
Existing server processes need a restart/reconnect to load the new Python
code and initialization instructions. Do that between CAD operations.

## Maintenance

Edit the canonical skill and its references/workflows here. Do not edit the
review candidate under `output/` or duplicate the same guidance in the local
MCP skill. Its generated tool catalog derives new groups from registered
handler modules, so new tools no longer fall into an undifferentiated list.

New workflow files need a relevant `TOPIC_TOOLS` entry in `library.py` if
they recommend specific tools. The mapping is compared with the current
advertised names at read time; unsupported names are reported separately.
Adding a file is not sufficient evidence to mark its workflow tested.

## Verification

Run with the project Python environment:

```
python -m unittest solidworks_mcp.tests.test_modeling_guidance -q
python scripts/verify_modeling_guidance.py
```

The second check starts a fresh MCP subprocess, tests initialization,
tools, resource discovery and equality of resource/tool content. It does
not launch or connect to CAD. Actual modeling quality requires a separate
scratch-project evaluation with measured geometry and parameter revisions.

## Next phase: learn from demonstrated work

Start with structured worked examples. Record intent, input dimensions,
dependencies, selections, operations, verification, failures and corrections.
A video supplies observations and timestamps; reproduce the sequence before
promoting it to a verified recipe. Preserve what was not visible in the video
as uncertainty. Use examples as retrieved context first, then measure whether
additional training improves held-out tasks. The workflow `learning` gives
the record fields and criteria. This change does not train any model.

MecAgent describes text-to-macro-to-CAD with native, editable parametric
results. That is a useful outcome to evaluate, not proof of its internal
training method or a guarantee of equivalent results here. Our existing
MCP already calls the native SolidWorks API. Source reviewed 2026-09-25:
https://mecagent.com/blog/text-to-macro-to-cad-the-future-of-design
