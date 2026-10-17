# Project status

**Last reconciled:** 2026-10-17
**Overall state:** Prototype implementation in progress using NSE bhavcopy archives.

## Current scope

- Private, local-first research app for NSE cash equities.
- Python-coded daily/swing strategies with a shared-cash portfolio model.
- Corporate-action discovery is broad across the NSE export; the initial
  strategy watchlist remains the current Nifty 50.
- Initial data universe: current Nifty 50 constituents, captured with an
  effective date, with at least five years of daily OHLCV for charting and early
  research.
- First visual data tool: a Price Explorer with a close-price time series,
  volume, underlying rows, 52-week high/low, and freshness/quality indicators.
- No order placement, intraday/options research, or public data redistribution
  in the first release.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| 0. Source and format proof | Complete for sample | Successfully downloaded and parsed RELIANCE legacy and UDiFF bhavcopies across 2023-10-30 to 2024-10-30. Full-universe coverage validation remains. See ADR-0004. |
| 1. Data foundation | In progress | Local raw archive, canonical daily prices, Parquet, SQLite catalog, and quality checks; RELIANCE sample is loaded locally. |
| 2. Five-year Nifty 50 backfill | Not started | Checkpointed import and per-symbol coverage report. |
| 3. Price Explorer | In progress | Local symbol/date selector, close chart, volume, and daily rows. |
| 4. Daily refresh | In progress | TOML schedule configuration, SQLite schedules/run history, injected refresh handlers, app-start runner, and Schedulers controls are implemented. Fourteen scheduler/service/UI tests pass; live NSE automatic/manual refresh verification remains. The existing LaunchAgent cannot access this checkout under `Documents`; remove it after live verification. |
| 5. Research readiness | In progress | Automated rolling NSE CSV retrieval is implemented and completed once on 2026-10-17. The refresh archived 11,845 source rows and staged 11,842 unique candidates across all symbols: 19 new and 5 missing rows were flagged; none were approved automatically. The weekday LaunchAgent is installed but macOS denied its access to this repository under `Documents`. Event verification, series eligibility, point-in-time membership, and reproducible run records remain. |
| 6. Related datasets/hosting | Deferred | Add after price ingestion is dependable and remote operation is needed. |

## Accepted decisions

- Read [ADR-0001](decisions/ADR-0001-research-scope.md) for research scope and
  initial execution model.
- Read [ADR-0003](decisions/ADR-0003-price-view-and-benchmark.md) for current
  Nifty 50 chart universe, raw/adjusted price views, and TRI benchmark.
- Read [ADR-0002](decisions/ADR-0002-local-data-storage.md) for the accepted
  local storage architecture.
- Read [ADR-0004](decisions/ADR-0004-nse-file-acquisition.md) for the accepted
  NSE bhavcopy prototype source and its known terms ambiguity.
- Read [ADR-0005](decisions/ADR-0005-52-week-extrema.md) for the historical
  52-week high/low calculation.
- Read [ADR-0006](decisions/ADR-0006-corporate-action-adjustments.md) for
  raw/adjusted price behavior, point-in-time signals, and portfolio accounting.
- Read [ADR-0007](decisions/ADR-0007-nse-corporate-action-ingestion.md) for
  archived NSE exports, review staging, and event-promotion rules.

## Open decisions and gates

- Confirm whether historical Nifty 50 membership snapshots can be sourced for
  point-in-time backtests.
- Define which NSE series count as eligible cash equities before promoting
  broad Corporate Actions candidates into the strategy event ledger.
- Finalize exact canonical price fields and units after inspecting source files;
  record them in `docs/data-dictionary.md` before relying on them downstream.

## Next concrete action

Run the app's automatic and manual corporate-action refreshes against NSE and
confirm successful run records and candidate staging. Remove the blocked
LaunchAgent after those live runs succeed. Review refreshed action candidates
against company filings; discovery alone does not adjust prices. After the
scheduler is verified, start the five-year Nifty 50 price backfill with
checkpoints and per-symbol coverage reporting.

## Latest handoff

The local RELIANCE sample covers 247 sessions from 2023-10-30 to 2024-10-30
around its 2024-10-28 1:1 bonus ex-date. That event is in the local Parquet
action ledger with its NSE filing URL. The app derives an adjusted chart view;
strategy signal generation can consume point-in-time adjusted bars, while
backtests use raw fills and account for held shares/dividends. The weekday
corporate-action LaunchAgent is installed, but a forced launch on 2026-10-17
showed macOS denied access to the project script (`Operation not permitted`);
reloading the agent does not prove it can run. The new CLI downloader
successfully retrieved the rolling export interactively on 2026-10-17. It
archived 11,845 source rows and staged 11,842 unique candidates (19 new, 5
missing); none were promoted. NSE corporate-action exports now have a raw
archive, checksum manifest, parser, candidate Parquet, and per-export review
CSV. The five-year export from 2021-10-13 through 2026-10-13 is archived and
staged. Its first snapshot had 11,838 source rows and 11,835 candidates; a later
re-export had 11,837 source rows and 11,834 unique incoming candidates. The
review workflow now generates focused worksheets.
The RELIANCE/SBIN worksheet initially had 11 pending candidates. The RELIANCE
2024 bonus candidate matched the existing reviewed ledger event; its NSE record
date is now retained and the candidate is marked approved. This updated the
existing event rather than adding a duplicate. The other 10 worksheet rows
remain unapproved; the ledger still has one action. This pilot does not
establish complete source coverage or series eligibility.

The official `PR141026.zip` sample was downloaded through NSE All Reports and
inspected. Its `bc14102026.csv` member had 160 rows across 90 symbols, including
9 EQ rows, with nonblank ex-dates spanning only 2026-10-14 through 2026-10-16.
It lacks filing-level terms and cannot replace the five-year CSV baseline. The
raw ZIP is archived under `data/raw/nse/corporate_action_press_files/`. The
schedule script now invokes the automated rolling CSV downloader. PR ZIP
retrieval remains a possible supplement; the rolling CSV is the active source.
