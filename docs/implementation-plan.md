# NSE Strategy Lab implementation plan

**Status:** Proposed implementation sequence
**Updated:** 2026-10-17

For the current milestone, open gates, and next action, see
[`project-status.md`](project-status.md). Keep milestone definitions here and
update both documents when scope or sequencing changes.

## 1. Goal and first release

Build a private, single-user research app for NSE cash equities. The first usable
release will provide:

- Five years of daily price history for an initial Nifty 50 watchlist.
- A repeatable daily import that can recover missed trading dates.
- A price explorer with a close-price chart, volume, and inspectable daily rows.
- A clean boundary between data ingestion, storage, strategy code, backtesting,
  and the Streamlit UI.

The initial release is for historical research and review. It will not place
orders, provide real-time data, or claim that backtests represent the exact
historical Nifty 50 universe until point-in-time constituent data is available.

## 2. Decisions for the first release

| Area | First-release decision |
|---|---|
| Universe | Current Nifty 50 constituents, captured with an effective date and source file. |
| Price history | At least five years of daily OHLCV; retain the exchange-reported values as raw prices. |
| Initial event data | Discover actions from NSE CSV exports for all symbols, archive and stage candidates for review, then promote verified supported events to a separate ledger. Defer bulk/block deals until price ingestion is stable. |
| Data source | Prototype with date-based direct NSE bhavcopy archive URLs through an explicit CLI importer; reassess the source after testing. |
| Price basis and benchmark | Preserve raw exchange-reported bars and derive an explicitly labeled, point-in-time corporate-action-adjusted view from an action ledger. Use NIFTY 50 TRI as the initial benchmark, subject to an allowed source. |
| Local storage | Immutable original report files, normalized Parquet datasets, and a small SQLite catalog for import metadata. Use DuckDB to query Parquet for the app and research workflows. |
| Refresh | Run the explicit local importer for missing sessions. The importer remains outside Streamlit. |
| Scheduling and hosting | Local app-start catch-up with a persistent scheduler dashboard. Keep job definitions independent of the runner; hosted deployments use a dedicated worker/managed scheduler and durable shared storage. |

### Universe caveat

The current Nifty 50 roster is a useful initial watchlist, but applying today's
50 names to all five prior years creates survivorship bias in portfolio
backtests. Store current watchlist membership separately from historical index
membership. Add effective-dated historical constituents before labeling a
cross-sectional strategy as a historical Nifty 50 backtest.

## 3. Data tables

The first implementation should use these logical tables. Price and event
records live in Parquet; small operational records live in the SQLite catalog.

### Market data in Parquet

| Dataset | Grain and key | Important fields |
|---|---|---|
| `daily_prices` | One security/series per trading date; key `(trade_date, instrument_id, series)` | `symbol`, `open`, `high`, `low`, `close`, `volume`, `turnover`, `trade_count`, `source_file_id` where available. Keep exchange-reported prices unadjusted. Price queries derive trailing 364-calendar-day `high_52w` and `low_52w` as-of each row. |
| `daily_security_stats` | One security per date for supplemental daily exchange metrics | `deliverable_quantity`, `deliverable_percent`, and other fields when available from a separate report. Keep source provenance. |
| `corporate_actions` | One action per security/action event; key `(symbol, series, action_type, ex_date)` | `action_type`, `announcement_date`, `ex_date`, `share_factor` or `cash_per_share`, `pay_date`, terms, source URL/file ID. Bonus/split factors adjust historical price/volume; dividends adjust historical price and portfolio cash accounting. |
| `corporate_action_candidates` | One candidate row per NSE export entry | Original purpose text and dates, inferred event type/terms, review status/notes, source export checksum and URL. Candidates never adjust prices. |
| `deals` | One disclosed deal | `deal_date`, `available_at`, `instrument_id`, `deal_type`, buyer/seller, quantity, price, source. Add only after price history is dependable. |
| `index_membership` | One membership interval per index/security | `index_code`, `instrument_id`, `valid_from`, `valid_to`, source. Needed for point-in-time Nifty 50 testing. |

### Reference and operational data in SQLite

| Table | Purpose |
|---|---|
| `instruments` | Stable internal ID, exchange, ISIN when available, and dated symbol/series mappings. A ticker is a display value, not a permanent identity. |
| `watchlist_membership` | Dated membership in the initial Nifty 50 watchlist, including the source and capture date of the constituent list. |
| `source_files` | Report name, trade date, retrieval time, local raw-file path, SHA-256, byte size, and parser/schema version. |
| `ingest_runs` | Job start/end, requested date range, status, inserted/updated row counts, and error summary. |
| `job_schedules` | Stable job definitions, weekday local time, enabled state, catch-up policy, and next due occurrence. |
| `job_occurrences` | Unique scheduled/manual executions, transactional claims/leases, timestamps, result summaries, and errors. |
| `quality_issues` | Row/file/date, rule name, severity, observed value, and resolution status. Suspicious data is flagged, not silently discarded. |
| `corporate_action_imports` | One row per unique NSE action-export checksum | Source URL, retrieval time, inclusive selected date range when known, immutable raw path, byte count, parser status, staged row count, and parse error if any. |
| `research_runs` | Later: strategy code revision, parameters, universe, cost assumptions, input data snapshot, and result paths. |

Parquet should be partitioned by dataset and month (or year if monthly files
become too small). Avoid one file per symbol or one tiny file per day. The raw
NSE files and all market data are excluded from Git.

## 4. Import and processing workflow

Every import follows the same sequence:

1. **Discover:** determine the latest available exchange report/trading date;
   do not assume a report exists for every calendar day.
2. **Download:** fetch the official report and save it unchanged under the raw
   archive, organized by source, report type, and trade date.
3. **Identify format:** select a parser using report type and format version.
   The five-year period crosses NSE's July 2024 bhavcopy format change, so both
   legacy and UDiFF inputs must map to the same canonical schema.
4. **Normalize:** parse dates and numeric fields, trim identifiers, resolve the
   instrument mapping, and attach source-file provenance.
5. **Validate:** check report/date consistency, duplicate keys, positive OHLC,
   `low <= open/close <= high`, nonnegative volume, unexpected missing
   securities, and unusually large price changes. Large changes are warnings
   because they can be genuine or corporate-action related.
6. **Promote atomically:** write a temporary normalized partition, then replace
   the active partition only after parsing and validation succeed. A failed
   import leaves the last accepted dataset available.
7. **Record:** persist the run, file checksum, counts, and quality findings in
   the catalog.

Imports must be idempotent: rerunning the same source report/date updates or
confirms the same natural keys rather than duplicating rows. Historical
backfill and daily refresh should use the same parser and validation path.

### Corporate-action collection

1. On weekdays after close, `nse-strategy-lab refresh-actions` downloads the
   NSE Corporate Actions CSV export using the rolling range from five years
   ago through one year ahead.
2. The NSE source adapter warms a web session, requests the page's current CSV
   route, validates the response, archives the exact bytes and records its
   selected range, then stages all candidate rows. An empty response, an
   HTML/JSON error page, or missing CSV fields fails closed. To stage a manual
   download if the route changes, use `stage-nse-actions`.
3. Review candidates against each company's NSE announcement/filing
   attachment. Confirm announcement date, event ratio or cash amount, and
   payment/consideration details. Unclassified and unsupported events remain
   staged; they are neither discarded nor applied to prices.
4. Promote only completed and supported records with
   `nse-strategy-lab import-actions <reviewed-actions.csv>`.
5. Compare candidate coverage against the price universe and inspect
   unexplained ex-date price/volume discontinuities. Repeat exports in bounded
   date ranges if NSE limits export size or history.

The scheduled local job automates retrieval, validation, archiving, and staging
of the official page CSV. Its underlying route is not a versioned public API,
so a page change produces a failure and notification rather than a silent
partial import. NSE lists a daily `Bhavcopy (PR)` ZIP on [All Reports](https://www.nseindia.com/all-reports)
and documents the ZIP's naming and website location in its
[2025 Press Files Report circular](https://nsearchives.nseindia.com/content/circulars/CMTR70563.pdf),
whose `readme.txt` identifies the ZIP member `bcddmmyyyy.csv` as corporate
action details. The 2026-10-14 report's member contains a three-day ex-date
window and lacks full filing terms, so it cannot replace the five-year CSV
baseline. It remains a possible near-term supplement after the download flow
and multi-day coverage are validated (ADR-0007).

Candidate comparison also flags prior rows missing from a later export when
their ex-dates fall within that export's recorded coverage window. These rows
need review and are never automatically removed from the approved action
ledger.

### Five-year bootstrap

1. Download representative daily bhavcopies from both sides of the July 2024
   format change using the date-based archive URLs.
2. Confirm field definitions and compare overlapping dates where available.
3. Use the same daily archive route for the five-year backfill and refresh.
4. Backfill in bounded date batches with a checkpoint after each accepted
   batch. Produce a coverage report per symbol (first date, last date, missing
   sessions, duplicates, and flagged prices).
5. Reconcile a sample of symbols/dates against NSE's security-wise archive.

NSE's public report page lists daily CM-UDiFF bhavcopy archives and identifies
the July 2024 transition from the older format. The project owner has selected
NSE bhavcopy archives for prototype imports and will revisit the source after
testing. The terms ambiguity and current assumption are recorded in ADR-0004.

## 5. Daily refresh

The explicit `refresh` CLI command runs independently from the app and imports
missing reports. It should:

- Check the report source and import the latest available trading date.
- Retry a small number of times with backoff if the report is not published
  yet; then record a clear `pending`/`failed` run instead of showing stale data
  as current.
- Find missing trading dates from the last accepted date and catch up after
  holidays, outages, or the local computer being asleep.
- Use a lock so two jobs cannot update the same partition concurrently.
- Expose last successful trade date and import status to the dashboard.

The accepted scheduler design uses a local app-start runner with persistent
SQLite run history, missed-run recovery, and manual controls in a Schedulers
view. Each job defines its catch-up policy. This replaces the macOS LaunchAgent
once implemented; until then the existing LaunchAgent remains installed but
cannot read the checkout under `Documents`. The price refresh and corporate
action refresh remain separate jobs. Hosted deployments use the same
framework-independent job services with a dedicated worker or managed
scheduler and durable shared storage; the Streamlit web process alone is not
the hosted scheduler.
Do not use Streamlit's local filesystem as the data store.

## 6. Price Explorer

Add a `Price Explorer` view to the Streamlit app with:

- A Nifty 50 symbol selector and date range options (1M, 6M, 1Y, 5Y, custom).
- A time-based closing-price line chart and a volume chart below it.
- A daily data table with CSV download for the selected symbol/range.
- Query-derived trailing 364-calendar-day 52-week high and low in the daily
  table and as selected-range-end summary metrics (see ADR-0005); the selected
  raw or adjusted basis is explicit.
- Last loaded trading date, source, and a visible data-quality/missing-session
  indicator.
- A `Corporate-action adjusted` / `Raw NSE prices` selector. The adjusted view
  shows raw and derived OHLCV side by side and names the chart's as-of date.
  See ADR-0006 for adjustment and point-in-time strategy rules.

The app queries only the selected symbol and date range through DuckDB. Cache
the loaded slice with a bounded time-to-live and invalidate it using the latest
successful import ID/date. The UI must never run the bulk importer as a side
effect of a page render.

## 7. Repository structure

Keep the Streamlit entry point thin. Business logic and data access live in the
installable Python package so the same functions can be called by the UI, CLI,
scheduled job, and future API.

```text
nse-strategy-lab/
├── app.py                         # Streamlit entry point; UI wiring only
├── pyproject.toml                 # Package metadata and dependencies
├── configs/                       # Non-secret source and app settings
├── docs/
│   ├── implementation-plan.md
│   ├── architecture.md
│   └── data-dictionary.md
├── src/nse_strategy_lab/
│   ├── domain/                    # IDs, schema contracts, domain types
│   ├── ingestion/
│   │   ├── sources/nse/           # NSE report client and source adapter
│   │   ├── parsers/               # Legacy and UDiFF report parsers
│   │   └── jobs/                  # Backfill and daily refresh workflows
│   ├── quality/                   # Data checks and coverage reports
│   ├── storage/                   # Parquet and SQLite repositories
│   ├── universe/                  # Watchlist and dated index membership
│   ├── domain/corporate_actions.py # Event schema and validation
│   ├── services/adjustments.py    # Point-in-time adjusted strategy bars
│   ├── strategies/                # Pure Python signal generation
│   ├── backtesting/               # Shared-cash execution and metrics
│   ├── services/                  # Import, query, run, and compare use cases
│   └── ui/                        # Shared Streamlit page helpers
├── scripts/                       # Local admin/backfill entry points
├── tests/                         # Parser, quality, storage, and engine checks
└── data/                          # Local data only; Git-ignored
    ├── raw/
    ├── curated/
    └── catalog.sqlite
```

Use typed data contracts at module boundaries. NSE client code should know about
NSE report formats; the rest of the app should know only the canonical schema.
Keep strategies free of file/network I/O. Keep portfolio execution rules in
one backtesting engine. UI pages call service functions rather than writing
SQL or downloading reports directly.

## 8. Implementation milestones

### Milestone 0 — Source and format proof

- Import a small date range covering both legacy and UDiFF report formats.
- Confirm field mappings and review coverage/quality output.
- **Exit condition:** demonstrate an idempotent, checkpointable import over a
  small date range and document coverage. Reassess the source after testing.

### Milestone 1 — Data foundation

- Add canonical schemas, instrument mapping, catalog, raw-file manifest, and
  local Parquet/DuckDB query layer.
- Add format-specific parsers and validation/coverage reporting.
- **Exit condition:** the same sample files can be imported repeatedly without
  duplicate rows, and failures leave the prior accepted data intact.

### Milestone 2 — Nifty 50 five-year backfill

- Capture the dated Nifty 50 constituent list and import five years for those
  securities.
- Resume from checkpoints and produce a per-symbol coverage report.
- **Exit condition:** all expected symbols have an explained date range;
  missing sessions and anomalies are visible and reconciled or documented.

### Milestone 3 — Price Explorer

- Add symbol/range selection, close and volume charts, inspectable rows, export,
  and import freshness/quality indicators.
- **Exit condition:** users can select each watchlist symbol and inspect the
  imported five-year range without loading unrelated market history.

### Milestone 4 — Reliable local refresh

- Add idempotency, locking, catch-up, logs, and a clear import-status surface.
- Keep refresh as an explicit local CLI command during the prototype; add a
  scheduler after the source path has been validated.
- **Exit condition:** a missed or repeated import does not lose or duplicate
  data, and the app shows the latest successfully imported date.

### Milestone 5 — Research readiness (in progress)

- Import reviewed bonus, split, and dividend events into a provenance-aware
  ledger; derive adjusted chart snapshots and point-in-time strategy bars.
- Keep backtest fills on raw bars and apply share/cash actions to held positions.
- Add historical Nifty 50 membership effective dates before claiming
  point-in-time Nifty 50 portfolio results.
- Persist reproducible strategy run inputs and outputs.
- **Current prototype:** raw/adjusted Price Explorer, action CSV import, and
  raw-fill corporate-action accounting are wired. Full event coverage,
  historical-universe membership, and reproducibility records remain open.
- **Collection path:** export archiving, checksum manifest, all-symbol
  candidate parsing, review CSV output, and automated retrieval through NSE's
  current page-export route are implemented. The initial five-year snapshot
  contains 11,838 source rows and 11,835 unique candidates across 2,358 symbols.
  The 2026-10-17 refresh contained 11,845 source rows and 11,842 candidates
  (19 new and 5 missing from the prior snapshot); none were approved
  automatically. Review event terms, series eligibility, and completeness
  before approving rows. The route is unversioned, so the downloader validates
  every response and keeps manual CSV staging as a fallback. Candidate change
  detection, a verification worksheet, and explicit approved-row promotion
  remain in place. Daily LaunchAgent execution still needs macOS folder access
  resolved because the repository is under `Documents`.

### Milestone 6 — Related datasets and hosting

- Add bulk/block deals and other events as separate source adapters/tables.
- Move to hosted durable storage and a scheduled worker only if remote access
  or machine-off scheduling becomes important.

### Scheduler implementation — accepted, next

- Add a framework-independent job registry for corporate-action and price
  refresh, with cadence and per-job catch-up rules.
- Persist schedule definitions, due occurrences, run history, errors, and
  execution claims in SQLite for the local single-user deployment.
- Start a guarded background runner with the local app; keep network/import
  work out of Streamlit page rendering.
- Add a Schedulers view for last/next run, status, errors, individual manual
  trigger, and run-all-due action.
- Replace/uninstall the current LaunchAgent only after the app-start runner
  and manual run controls are implemented and verified.
- Preserve an adapter boundary for a future PostgreSQL-backed run repository
  and hosted worker/managed scheduler. Add those only when deploying remotely.

#### Initial implementation plan and defaults

1. Keep operational schedule settings in `configs/schedules.toml` and persist
   them in `job_schedules` in the existing SQLite catalog. On app startup,
   synchronize changes to cadence/time/timezone while preserving the persisted
   enabled state. Defaults are corporate actions at 18:30 Asia/Kolkata, then
   price refresh at 18:40.
2. On app startup and periodically while the process is open, find due
   schedules and insert unique `job_occurrences`. Coalesce missed weekdays to
   one current run per job. Claim one occurrence transactionally with a
   five-minute lease renewed every minute; an expired claim can be recovered
   after a process crash.
3. Inject application handlers and a scheduler repository into a
   framework-independent daemon runner; select SQLite in the app composition
   root. Keep handler registration there and job workflows in shared
   application services used by both CLI and scheduler. The runner must not
   depend on the data handlers or concrete database implementation. Corporate
   actions refresh the rolling five-year export plus one year forward and stage
   candidates only. Price refresh starts after the latest imported session;
   when the store is empty, it imports only the latest 14 calendar days so app
   startup cannot trigger the five-year backfill.
4. Add scheduler controls for enabled state, manual per-job runs, run-all-due,
   recent status/result/error history, and retrying failed runs. Manual and
   scheduled execution use the same handler and accounting path.
5. Verify automatic due-run creation, manual enqueue, success/failure
   persistence, retry, duplicate claim exclusion, app restart recovery, and
   both existing import handlers. Only after automatic and manual action
   refreshes are confirmed should the old LaunchAgent be removed.

**Implementation state (2026-10-17):** SQLite schedule and occurrence
repositories, TOML weekday schedule configuration, injected application
handlers, an app-process background runner, and the Schedulers workspace are
implemented. Fourteen unit and Streamlit UI tests pass, covering schedule
configuration, catch-up, persistent state, claims/lease recovery, retries,
shared CLI/scheduler refresh use cases, background app-start dispatch, handler
dispatch, and rendering the Schedulers workspace. Live NSE refresh verification
remains open. The old LaunchAgent remains installed until automatic and manual
refreshes are confirmed. The
single-user local runner is not the hosted deployment solution; a dedicated
worker and shared database remain deferred.

## 9. Source references

- [NSE Security-wise Archives (Equities)](https://www.nseindia.com/report-detail/eq_security)
- [NSE All Reports](https://www.nseindia.com/all-reports)
- [NSE Corporate Actions](https://www.nseindia.com/companies-listing/corporate-filings-actions)
- [NSE Corporate Announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements)
- [NSE Terms of Use](https://www.nseindia.com/static/nse-terms-of-use)
- [NSE Data Sharing & Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
- [NSE MCP information and disclaimer](https://www.nseindia.com/nse-mcp)
- [NSE Data Sharing & Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
- [NSE data list for research and analysis](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Data%20list%20under%20NSE%20Data%20Sharing%20Policy%20for%20Research%20and%20Analysis_20250728.pdf)
- [Nifty 50 index and constituents](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty--50)
