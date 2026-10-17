# Architecture overview

This document describes the intended system boundaries for the first release.
`project-status.md` is the source of current progress and next action;
`implementation-plan.md` defines the milestones; ADRs record why important
choices were made. If this page and an accepted ADR disagree, reconcile them in
the same change that changes the decision.

## System context

```text
NSE date-based bhavcopy archives
    │
    ▼
Explicit CLI downloader ──► Raw archive (immutable ZIP files + checksums)
    │
    ▼
Versioned parsers ──► Canonical schemas ──► Quality checks
                                          │
                                          ▼
                     Curated raw Parquet + action ledger + catalog
                               │                    │
                               ▼                    ▼
                       DuckDB query layer     Explicit CLI import job
                               │
                    ┌──────────┴───────────┐
                    ▼                      ▼
              Price Explorer        Research services
                                           │
                               Adjustments → strategies
                                    raw execution → backtests
```

```text
NSE public Corporate Actions CSV export
    │
    ▼
NSE CSV source adapter ◄── Scheduled job service ◄── Local app runner
    │                         ▲                              │
    └────► Raw archive + checksum                 Scheduler status UI
                              │
                              ▼
                      Candidate parser
                              │
                              ▼
                       Review candidates
                              │
                  Verify linked company filing
                              │
                              ▼
              Approved corporate_actions ledger
```

The Streamlit app is a client of application services. The importer is an
explicit command-line job. Rendering a page must not download data or mutate
stored prices. The current prototype uses the direct archive URL patterns
recorded in ADR-0004 and will reassess its source after testing.

## Module responsibilities

- **Source adapters:** know how to acquire NSE daily reports or preserve a
  downloaded corporate-action export. They record source metadata and save
  original bytes. They do not define strategy-ready price semantics.
- **Scheduler service:** owns job definitions, due-time calculations,
  catch-up policy, run history, retries, and manual triggers. It calls
  application services and never promotes review candidates. The local runner
  starts with the app and checks for due jobs; the future hosted runner is a
  worker or managed scheduler. Streamlit displays status and enqueues requests.
  The current weekday defaults are corporate-action refresh at 18:30 and price
  refresh at 18:40 Asia/Kolkata. These definitions and their enabled state are
  persisted in SQLite, separately from the runner. Operational settings live
  in `configs/schedules.toml`; the app composition root injects handlers for
  the stable job IDs and a scheduler repository, so the runner has no
  import-workflow or SQLite dependencies.
  CLI and scheduled refreshes call the same application refresh use cases.
- **NSE source adapter:** warms a web session and requests the current CSV route
  used by the public page's export control. Responses are validated before
  staging; changed, blocked, empty, or malformed responses produce a logged
  error. Manual page exports remain a fallback.
- **Parser:** knows one report layout/version and converts it into a canonical
  record. Legacy and UDiFF parsers may coexist behind one parser interface.
  Corporate-action summary rows are parsed into review candidates, not directly
  into approved adjustment events.
- **Domain/schema:** defines instrument identity, canonical prices, events, and
  validation rules independently of NSE column names.
- **Quality service:** checks coverage, keys, price constraints, and anomalies.
  It distinguishes hard failures from reviewable warnings.
- **Storage:** writes raw files, curated Parquet partitions, and import metadata.
  Repository methods hide file paths and SQL from application/UI code.
- **Application services:** orchestrate backfill, daily refresh, price queries,
  and reproducible research runs.
- **Strategies:** calculate signals from supplied canonical data and
  parameters. They do not download, persist, or render data.
- **Backtest engine:** turns strategy signals into fills and portfolio state
  under one shared-cash accounting model.
- **Streamlit UI:** accepts symbol/date/strategy selections and displays service
  results. It does not contain parsers, portfolio accounting, or raw SQL.

## Data layers

1. **Raw:** exact downloaded report files, immutable and identified by source,
   report type, trade date, retrieval time, and checksum.
2. **Canonical:** normalized exchange-reported daily prices and reviewed
   corporate actions in separate Parquet datasets. `daily_prices` is always
   unadjusted. Actions include announcement/ex-dates and source provenance.
3. **Derived:** adjusted OHLCV, indicators, backtest results, and charts. The
   adjustment service derives a chart snapshot from raw bars plus actions; it
   does not persist duplicate adjusted prices. Strategy signals are recomputed
   on each date's point-in-time adjusted prefix, while fills and position marks
   use raw bars. Share actions update held quantity and per-share basis;
   dividends become receivables until pay date.

Raw prices remain unchanged. Corporate-action adjustment is a derived layer
with an explicit method; it is never an invisible edit to exchange values.

## Contracts and invariants

- A security uses a stable internal `instrument_id`; symbol/series mappings are
  date-effective because symbols can change.
- A daily price row is unique on `(trade_date, instrument_id, series)`.
- Every canonical row retains source-file/run provenance.
- An import is idempotent for the same report/date and can be safely retried.
- A new data partition is promoted only after parsing and required checks pass.
- Missing sessions, source delays, and suspicious prices are visible to users.
- Signals formed using session `t` close execute no earlier than the next
  available session for that instrument, according to the configured fill
  model.
- Future corporate actions cannot affect earlier signals: an event is eligible
  only after its announcement date and ex-date. Supported event types and
  accounting rules are in ADR-0006.
- Research runs identify strategy revision, parameters, universe, costs, and
  input-data snapshot.
- Current Nifty 50 watchlist membership and historical index membership are
  separate concepts. Current constituents alone do not establish a
  point-in-time historical universe.

## Intended local deployment

- Import jobs run as application services outside Streamlit page rendering.
  Locally, a process-scoped runner checks schedules when the app starts, while
  a scheduler page displays persisted runs and accepts manual triggers. Jobs
  use the same execution path whether due or manually requested.
- SQLite stores local schedules and run history in `job_schedules` and
  `job_occurrences`. An atomic claim, five-minute lease renewed each minute,
  and unique occurrence key
  prevent duplicate execution across reruns and sessions. Missed weekdays
  coalesce to one current run; a price refresh imports from the latest accepted
  session, or only the recent 14-day window when no price data exists. The
  local runner cannot execute while the app is closed; it catches up on next
  startup according to each job's policy. Failed occurrences can be retried
  from the Schedulers workspace.
- Schedule settings are read from `configs/schedules.toml` at app startup and
  synchronized into SQLite. Editing the file and restarting updates cadence,
  time, timezone, and catch-up policy while preserving the enabled/disabled
  choice. Job behavior stays in application handlers registered by the app.
- Parquet is the durable market-data format; SQLite stores the small import
  catalog; DuckDB queries Parquet for charts and research.
- Corporate actions are explicitly imported from a reviewed CSV into their own
  Parquet ledger. NSE action exports are separately archived and staged for
  review across all symbols; rendering the dashboard never scrapes or mutates
  data. A weekday 18:30 local schedule retrieves the rolling official CSV,
  archives and stages it, and records retrieval or validation errors. The
  page's current export route is not versioned, so manual CSV export
  remains the recovery path. Staging marks
  candidates new, changed, unchanged, or missing from the declared export
  window; a review worksheet promotes only
  explicitly approved supported events. `record_date` is retained for audit,
  while adjusted prices remain driven by `ex_date`. See ADR-0007.
- NSE's daily `Bhavcopy (PR)` ZIP contains a corporate-action member according
  to the ZIP readme, but the inspected sample covers only three ex-dates and
  omits filing-level terms. Keep it supplementary; it cannot replace the
  rolling Corporate Actions CSV snapshot or historical baseline.
- Streamlit reads curated data and calls application services.
- `data/`, credentials, and generated outputs are excluded from Git.

If hosted later, preserve the job definitions and application-service
boundaries, move raw/curated data to durable object storage, and run ingestion
through a dedicated worker or managed scheduler. Replace the local SQLite
scheduler repository with a durable shared database before using multiple
workers or web instances. Do not rely on Streamlit process startup as the
hosted scheduler. Add other shared server metadata only when required.
