# Mechanical-design skill concept

This note describes PksOck's approach to using a mechanical-design skill
alongside SolidWorks MCP. It shares the concept, not the private skill or a
ready-to-install replacement. The MCP server works without that private skill.

Anyone adopting this approach must build and validate their own complete skill
for their agent platform, engineering domain and working practices.

## Why add a skill above the tools?

MCP tools let an agent inspect and change CAD. They do not, by themselves,
establish whether a design meets the user's functional, manufacturing or
installation requirements. A mechanical-design skill can guide the agent to
understand the problem, ask useful questions, calculate dependencies and check
the result instead of turning each request directly into a sequence of clicks.

Keep the responsibilities separate:

| Layer | Responsibility |
|---|---|
| Mechanical-design skill | Design intent, requirements, assumptions, calculations, materials, joints, manufacturing and acceptance criteria |
| MCP modeling guides | Current tool workflows, selection rules, prerequisites, known limitations and recovery procedures |
| MCP tools | Inspect and execute operations against the intended CAD document |
| Verification | Compare native geometry and saved deliverables with the agreed requirements |

The skill should discover the server's actual capabilities and read its guides,
not maintain a second, gradually outdated copy of every tool instruction.
Prompt instructions are not a substitute for server-side access controls.

## Suggested design process

1. Identify the purpose, interfaces and project phase. Separate measurements,
   user requirements, calculated values and assumptions.
2. Ask about missing information that changes the design. Do not silently
   invent dimensions, loads, site conditions or finish thicknesses.
3. Compare workable concepts and record why one was selected. Define parameters,
   units, references and dependent dimensions before detailed CAD work.
4. Plan feature order and manufacturing steps. Consider assembly, access,
   tolerances, joints and finishing rather than only the visible shape.
5. Read the relevant MCP workflow, inspect the session and explicitly bind the
   intended document. Preserve source projects and unrelated user work.
6. Model in bounded steps and verify native geometry after meaningful changes.
   A successful tool response or attractive screenshot is not enough.
7. Check saved deliverables and report what was proposed, executed, verified
   and left unresolved. Keep geometry, structural adequacy and regulatory
   compliance as separate verification claims.

For example, a request for a steel support should first establish its loads,
interfaces, available space, environment and manufacturing method. A plausible
CAD solid alone cannot establish its load capacity or anchor suitability.

## What adopters need to build themselves

- Agent instructions and activation rules for their own client.
- Domain references with checked sources and applicability, including any
  locally required standards. This concept provides no certified design rules.
- Project records for requirements, parameter revisions, decisions and evidence.
- A controlled way to record confirmed corrections and reusable lessons.
  Stored notes are not model training and must not rewrite permissions.
- Acceptance tests for incomplete requirements, conflicting dimensions, stale
  CAD references, failed operations and unsafe save or close requests.
- Any orchestration, session ownership and recovery mechanisms required by
  their chosen agent platform.

The private skill's instructions, reference collection, learned preferences,
project history, evaluation suite and client configuration are not supplied
here. This file is deliberately not a `SKILL.md` and installs nothing.

## Optional multi-agent direction

A possible extension is to separate coordination, research, calculations,
CAD execution and review. Independent research and calculations can run in
parallel, with each task receiving the same confirmed parameter revision.

Only one executor should own a live SolidWorks session at a time. Other agents
should review exported evidence rather than make simultaneous COM calls,
including read-only calls during a mutation. Session handover must identify
the document, saved state, parameter revision and unresolved problems.

This is an architectural direction, not a shipped multi-agent implementation.
The server does not gain a cross-process ownership lock merely because a skill
describes one. Adopters must implement and test their own coordination.

## Starting points in this repository

- [Author review package](UPSTREAM-SHARE.md)
- [Modeling workflow and tool index](solidworks_mcp/knowledge/solidworks-2025-expert/workflows/tools.md)
- [Operating workflow](solidworks_mcp/knowledge/solidworks-2025-expert/workflows/operating.md)
- [Tests and verification](solidworks_mcp/tests/README.md)

The intended benefit is more deliberate use of the tools. Whether a particular
skill achieves that must be demonstrated by its own evaluations and CAD evidence.
