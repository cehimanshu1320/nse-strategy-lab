# Development workflow and shared context

## Source of truth

- `AGENTS.md`: instructions every coding chat/agent should follow.
- `docs/project-status.md`: current milestone, open gates, and next action.
- `docs/implementation-plan.md`: scope, milestone definitions, and gates.
- `docs/architecture.md`: module boundaries, data flow, and invariants.
- `docs/decisions/`: durable decisions and their rationale.
- `README.md`: short project overview and how to run the current version.
- `docs/data-dictionary.md`: canonical fields and formats (create when the
  first importer schema is agreed).

Chat history is not a durable requirements store. At the end of a workstream,
use the closeout checklist in `AGENTS.md`. Update affected documentation in the
same change as the implementation, not in a later cleanup task.

## Starting a new chat or workstream

1. Read `AGENTS.md`, `README.md`, the implementation plan, architecture, and
   relevant ADRs.
2. Inspect `git status`, current diffs, and the latest project files before
   editing.
3. State the workstream's goal, scope, files/modules owned, dependencies, and
   acceptance criteria.
4. If any design decision is unresolved, write down the assumption or ask the
   project owner before creating an incompatible interface.
5. At handoff, record what changed, what was verified, unresolved items, and
   the next concrete action in `docs/project-status.md`.

## Parallel development

Parallel work is appropriate when contracts are stable and modules are
independent. Good future workstreams include a report parser, price explorer,
or strategy module after the canonical schema is agreed. Avoid parallel work
on shared contracts or the same files.

For each parallel task, identify:

- One owner and a bounded set of files.
- Inputs/outputs and the canonical schema/service interface it uses.
- Dependencies on other workstreams.
- Acceptance criteria and required validation.

Use separate branches or worktrees for concurrent changes. Before integration,
review each diff, resolve interface conflicts, and update project docs. Do not
assume another chat's memory is current; use these files and the branch state.

## Change workflow

1. Make one cohesive change at a time.
2. Keep raw-data, parser, storage, service, and UI responsibilities separate.
3. Add or update focused validation for changed data contracts and behavior.
4. Update the implementation plan and docs when behavior or decisions change.
5. Review `git diff` and `git status` for unrelated changes before handoff.
6. Complete the required closeout checklist in the root `AGENTS.md`.

## Decision lifecycle

Use an ADR when a choice affects multiple modules or has meaningful migration
cost. Proposed choices remain open. When accepted, update the ADR status and
ensure the implementation plan describes the resulting work. When changing an
accepted choice, add a superseding ADR rather than rewriting history.

## Milestone reconciliation

At the end of each milestone, compare the implemented behavior and current
configuration against `project-status.md`, `implementation-plan.md`,
`architecture.md`, and relevant ADRs. Mark completed work, move deferred items
explicitly, and update the next action before beginning parallel work for the
next milestone. Do not leave a milestone marked complete while its documented
exit condition is unmet.
