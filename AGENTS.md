# Project guidance

Read these files before making substantial changes:

1. `README.md` for the current product and local setup.
2. `docs/project-status.md` for the current milestone and next action.
3. `docs/implementation-plan.md` for scope, milestones, and open gates.
4. `docs/architecture.md` for module boundaries and data-flow invariants.
5. Relevant records under `docs/decisions/` before changing an agreed decision.

## Working rules

- Keep the first release private, local-first, daily-frequency, and focused on
  NSE cash-equity research with the Nifty 50 as its initial strategy watchlist.
  Reusable reference/event collection (including corporate-action discovery)
  should not be restricted to current Nifty 50 symbols unless the user asks.
- Do not add order placement, live trading, or a new data vendor without an
  explicit scope decision.
- Keep external downloads and report-format knowledge inside source adapters
  and parsers. Convert inputs to the canonical schema before other modules use
  them.
- Preserve original source files and provenance. Never silently overwrite raw
  market data or silently accept a failed/partial import.
- Keep raw exchange-reported prices separate from corporate-action-adjusted
  values. Label adjustment assumptions anywhere prices are displayed or used.
- Keep strategy functions free of network, filesystem, and UI code. The shared
  portfolio engine owns signal timing, fills, cash, costs, and accounting.
- Keep Streamlit pages focused on presentation and user input. Call application
  services for data access and research workflows; do not place ingestion or
  domain logic in page scripts.
- Keep local data, credentials, and generated backtest output out of Git.
- Preserve backwards compatibility for canonical data schemas. If a schema or
  boundary changes, document a migration and update the data dictionary.
- Before editing, inspect `git status` and avoid overwriting unrelated user
  changes. Do not commit or publish unless asked.
- When a decision changes, update or supersede its ADR and update the plan and
  architecture page in the same change.
- When the project owner accepts a decision in chat, record it in the relevant
  ADR and reconcile `docs/project-status.md` before starting implementation
  that depends on it. If the decision is still tentative, record it as an open
  question/proposal rather than treating it as accepted.

## Required closeout for every workstream

Before calling a task complete, review the code change and answer these
questions. Documentation updates are part of the change, not follow-up cleanup.

1. Did the task change scope, a milestone, a gate, or the next action? Update
   `docs/project-status.md` and, if milestone definitions changed,
   `docs/implementation-plan.md`.
2. Did it change a cross-module decision, including one accepted by the owner
   in chat? Add/update an ADR. Accepted decisions must not be left only in chat
   or silently edited in the architecture page.
3. Did it change a module boundary, data flow, invariant, or deployment model?
   Update `docs/architecture.md`.
4. Did it change a canonical field, type, key, unit, null rule, or adjustment
   meaning? Update `docs/data-dictionary.md` in the same change.
5. Did it change setup, commands, or user-visible behavior? Update `README.md`
   or the relevant usage docs.
6. If no docs need changing, state why in the handoff/review summary. Do not
   make a documentation-only change to unrelated pages just to check a box.

After closeout, ensure the project-status page points at the next concrete
action and that no accepted decision is contradicted by the implementation.

## Parallel work

- Start each workstream by reading this file and the project context documents.
- Give each parallel workstream a bounded scope, named file ownership, an agreed
  interface, and acceptance criteria.
- Avoid concurrent edits to the same files. Prefer separate branches/worktrees
  for independent work; integrate only after reviewing each diff.
- Coordinate shared contracts first (canonical schemas, service APIs, and
  storage interfaces). Do not let UI, importer, and backtest work invent
  conflicting representations of prices or instruments.
- Keep this file, the plan, architecture, and ADRs as the durable context. Chat
  history is useful discussion, but not the source of truth for project state.
