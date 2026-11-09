# Examples separate from runtime code

The complete implementation remains in `solidworks_mcp/tools/`. This page
indexes examples already shipped in the same branch, without making them
automatic startup actions.

## No CAD connection

- `scripts/user_tool_examples.txt`: human-facing request examples by tool.
- `solidworks_mcp/knowledge/solidworks-2025-expert/workflows/tools.md`: domain index, with separate `tools-*.md` pages.
- `scripts/verify_modeling_guidance.py`: real stdio discovery and knowledge check. See the [test commands](../solidworks_mcp/tests/README.md).
- `solidworks_mcp/tests/test_toolsets.py`: catalog-selection examples.
- `solidworks_mcp/tests/test_routing_opt_in.py`: explicit routing permission examples.

Before modeling, a client should read `get_modeling_guide(topic="index")`,
`workflow/operating` and the relevant domain workflow. Inspect the open
documents and explicitly bind the intended CAD document before mutations.

## Live demonstrations

- `solidworks_mcp/tests/live/test_sketch_entities.py`: scratch sketch entities and a plate with measured-volume checks.
- `scripts/example_fastener_assembly.py`: plate, holes and standard fasteners. Requires matching Toolbox assets; saves the plate and leaves the assembly open for review.
- `scripts/verify_standard_parts_assembly_live.py`: installation-dependent standard-parts verification.
- `scripts/verify_standard_recipes_live.py`: standard-size recipe verification.

These are examples to inspect, not a batch of safe commands to run on an
existing project. Run only after explicit approval in a disposable CAD session,
with configured output roots and no other MCP client connected. Templates,
Toolbox paths and available standards can differ on the recipient's machine.
No live example was executed as part of preparing this branch.
