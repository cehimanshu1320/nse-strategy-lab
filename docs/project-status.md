# Project status

**Last reconciled:** 2026-10-20
**Overall state:** Prototype implementation in progress using NSE bhavcopy archives.

## Current scope

- Private, local-first research app for NSE cash equities.
- Python-coded daily/swing strategies with a shared-cash portfolio model.
- Corporate-action discovery is broad across the NSE export; the initial
  strategy watchlist remains the current Nifty 50.
- Initial strategy watchlist: current Nifty 50 constituents, captured with an
  effective date. Daily bhavcopy imports retain EQ and BE rows per ADR-0004; this
  broader archive supports the watchlist without changing the strategy
  universe.
- First visual data tool: a Price Explorer with a close-price time series,
  volume, underlying rows, 52-week high/low, and freshness/quality indicators.
- No order placement, intraday/options research, or public data redistribution
  in the first release.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| 0. Source and format proof | Complete for sample | Successfully downloaded and parsed RELIANCE legacy and UDiFF bhavcopies across 2023-10-30 to 2024-10-30. Full-universe coverage validation remains. See ADR-0004. |
| 1. Data foundation | In progress | Local raw archive, canonical daily prices, Parquet, SQLite catalog, and quality checks; price Parquet spans 2021-10-18 through 2026-10-19 with 1,520,810 rows across 3,062 symbols. The raw archive contains legacy and UDiFF formats. The first 700 symbols ranked by NSE July–December 2025 average market cap have been backfilled from cached bhavcopies for 2021-10-20 through 2026-10-19. All 700 have stored rows; six do not have observations through 2026-10-19: LTIM (2026-02-26), GUJGASLTD (2026-06-30), JBCHEPHARM (2026-07-16), GSPL (2026-05-11), AKZOINDIA (2026-04-13), and HEG (2026-09-21). All four runs recorded errors for uncached weekdays because DNS resolution failed; verify those dates from a network-enabled terminal before treating the batches as clean. |
| 2. Five-year Nifty 50 backfill | Complete with explained listing/identity limits | On 2026-10-18, imported the captured 50-symbol roster through 2026-10-16: 59,149 current-symbol rows, including 10 BE-series sessions for JIOFIN, with zero failed dates. Forty-six current EQ symbols start on 2021-10-18. NSE-confirmed prior symbols extend SHRIRAMFIN back to SRTRANSFIN (2021-10-18) and ETERNAL back to ZOMATO (2021-10-18). JIOFIN's own listing history starts 2023-08-21 in BE; its EQ rows start 2023-09-04. TATAMOTORS raw rows end 2025-10-23 and TMPV starts 2025-10-24; the reviewed demerger event now joins these for TMPV research views without modifying raw rows. TMCV history is restored from its first session on 2025-11-12: 10 BE rows through 2025-11-25, then EQ rows from 2025-11-26 through 2026-10-16. These 230 rows cover all 230 stored market sessions since listing. Current-ticker coverage report: `data/curated/reports/nifty50_backfill_coverage_2021-10-18_2026-10-18.csv`; symbol-history and comparability report: `data/curated/reports/nifty50_price_history_identity_2026-10-18.csv`. Price Parquet remains source-symbol-keyed; the derived effective-dated identity map joins TATAMOTORS/TMPV and keeps TMCV separate. Source roster and checksum metadata are under `data/raw/nse/index_constituents/`. |
| 3. Price Explorer | In progress | Local symbol and price-basis selectors, visible date-range presets and Price/Volume pills within the chart panel, nearest-session date/price/volume hover details, daily rows, and a Market Cap section that charts stored NSE observations. Imported NSE's July–December 2025 average market-cap workbook for 2,773 companies; 94 companies marked not traded in the period were excluded. These are period averages, not current point-in-time values. |
| 4. Daily refresh | In progress | TOML schedules and SQLite run history are implemented. Price refresh imports every EQ- and BE-series row in each bhavcopy; it rechecks 14 calendar days and stops on the first hard import error. On 2026-10-18, both manual scheduler jobs succeeded; an additional current CLI refresh also completed with no errors. A clock-triggered occurrence still needs observation with the app running after restart so the updated handler is loaded. |
| 5. Research readiness | In progress | The latest rolling NSE CSV export on 2026-10-18 archived 11,844 source rows and staged 11,841 candidates across all symbols. COASTCORP's candidate absent from the later snapshot matches the company's NSE-filed 2024 dividend notice for ₹1.20/share and the 2024-09-20 event date, but the candidate remains unapproved pending completion of required filing/payment metadata. Tata Motors demerger adjustment and portfolio distribution are implemented under ADR-0010. The NSE average-cap workbook importer and observations are implemented under ADR-0011. Automated quote-page snapshots remain gated on response semantics and data-use terms. Broader event coverage, event-series eligibility, and reproducible run records remain. Historical index membership is out of scope under ADR-0009. |
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
- Read [ADR-0009](decisions/ADR-0009-company-selection-not-index-replication.md)
  for the accepted direct-company research universe.
- Read [ADR-0010](decisions/ADR-0010-tata-motors-demerger-and-security-identity.md)
  for the TATAMOTORS/TMPV identity and TMCV distribution handling.
- Read [ADR-0011](decisions/ADR-0011-nse-market-cap-snapshots.md) for NSE
  market-cap measures, source rules, and storage decision.

## Open decisions and gates

- Define which NSE series count as eligible cash equities before promoting
  broad Corporate Actions candidates into the strategy event ledger. Price
  ingestion now preserves EQ and BE; action-ledger promotion remains EQ-only.
- Finalize exact canonical price fields and units after inspecting source files;
  record them in `docs/data-dictionary.md` before relying on them downstream.
- Validate NSE quote-page response/value/as-of semantics and data-use terms
  before automating point-in-time market-cap retrieval. The all-company workbook
  importer is manual because NSE publishes it irregularly.

## Next concrete action

Restart Streamlit to load the updated EQ/BE parser in the scheduled handler,
then observe clock-triggered price and corporate-action occurrences in
`job_occurrences`. Finish the COASTCORP filing review fields without promoting
the candidate until its required announcement/payment terms are verified.
For market cap, validate NSE quote response/as-of semantics and usage terms
before adding current quote snapshots; do not schedule the irregular average-
cap workbook.
For the current strategy-price batches, rerun ranks 1–700 from a network-enabled
terminal to confirm the uncached weekdays as holidays or source gaps; then
backfill market-cap ranks 701–800. Review the ticker histories ending before
2026-10-19 before using those names in a current-symbol strategy universe.
Historical Nifty 50 membership is not a gate: the accepted research universe
is the set of companies selected for each run. A persisted full NSE instrument
master remains future work; the current TATAMOTORS/TMPV/TMCV identity mapping is
explicitly scoped to the reviewed Tata event.

## Latest handoff

On 2026-10-18, the captured current 50-symbol roster was imported through the
latest available session, 2026-10-16. This includes verified rename histories
for SHRIRAMFIN and ETERNAL, JIOFIN's BE-to-EQ listing transition, and the
unadjusted TATAMOTORS history before TMPV. The local source and curated data
remain Git-ignored. The current price-refresh CLI completed after the EQ/BE
parser change with no errors; the app must restart before its scheduled handler
uses that parser. Both scheduler jobs have succeeded when manually triggered,
but a clock-triggered occurrence has not yet been observed.

The 2026-10-18 corporate-action export staged 11,841 candidates and flagged one
COASTCORP dividend row missing from the later snapshot. The company's NSE-filed
2024 notice supports the ₹1.20/share event, but required ledger metadata remains
under review and no candidate was promoted. Historical index membership was
removed from scope under ADR-0009. The Tata Motors demerger is now represented
by the reviewed event in the local ledger and checked-in import CSV. TMPV query
history joins the TATAMOTORS ticker and restates pre-event bars; backtests
distribute TMCV shares and allocate cost basis. Ten archived TMCV BE rows from
2025-11-12 through 2025-11-25 have been reparsed into local Parquet, followed
by the existing EQ series from 2025-11-26. Raw source files remain unchanged.

On 2026-10-20, imported NSE's all-company July 1–December 31, 2025 average
market-cap workbook. It contains 2,773 numeric observations and 94 rows marked
“Not traded during the period”; those rows were excluded rather than treated as
zero. The raw workbook and checksum are archived locally, with normalized
observations in a separate Parquet dataset. No market-cap scheduler was added:
NSE publishes this workbook irregularly and its values are six-month averages.
Current quote snapshots remain gated on source and terms validation.

On 2026-10-20, ranked that workbook by average market cap and ran price
backfills for ranks 1–100 and 101–300 over 2021-10-20 through 2026-10-19.
Together the cohorts contain 300 symbols, all with stored price rows; 297 reach
2026-10-19. LTIM ends on 2026-02-26, while GUJGASLTD and JBCHEPHARM end earlier
than 2026-10-19. Both runs reused 1,234 cached bhavcopies. The first run
processed 113,968 rows and recorded 71 DNS errors for uncached dates; the
second processed 218,713 rows and recorded 70 such errors. No new raw files
were downloaded. The reproducible selections are saved at
`data/curated/reports/market_cap_top_100_jul_dec_2025.csv` and
`data/curated/reports/market_cap_ranks_101_300_jul_dec_2025.csv`. Rerun both
cohorts from a network-enabled terminal to distinguish exchange holidays from
source gaps. Review the three stale ticker histories before using them as
current symbols.

On 2026-10-20, completed the ranks 301–500 price batch over 2021-10-20 through
2026-10-19 using cached bhavcopies. It contains 200 symbols and processed
206,811 rows; all selected symbols have stored rows, with GSPL and AKZOINDIA
ending before 2026-10-19. The run reused 1,234 cached bhavcopies, downloaded no
new raw files, and recorded 70 DNS errors for uncached weekdays. The selection
is saved at `data/curated/reports/market_cap_ranks_301_500_jul_dec_2025.csv`.
The ranks 1–500 batches now contain 500 symbols; five histories do not reach
2026-10-19. Their uncached dates remain pending network-enabled verification.

On 2026-10-20, completed the ranks 501–700 price batch over 2021-10-20 through
2026-10-19 using cached bhavcopies. It contains 200 symbols and processed
206,558 rows; all selected symbols have stored rows, with HEG ending on
2026-09-21. The run reused 1,234 cached bhavcopies, downloaded no new raw
files, and recorded 70 DNS errors for uncached weekdays. The selection is
saved at `data/curated/reports/market_cap_ranks_501_700_jul_dec_2025.csv`. The
ranks 1–700 batches now contain 700 symbols; six histories do not reach
2026-10-19. Rerun the batches from a network-enabled terminal to confirm the
uncached dates before continuing to ranks 701–800.

The RELIANCE sample continues to cover 247 sessions around its 2024-10-28 1:1
bonus ex-date; that reviewed event remains in the action ledger. The inspected
`PR141026.zip` sample covers only three ex-dates and lacks filing terms, so the
rolling Corporate Actions CSV remains the active source. The legacy macOS
LaunchAgent was removed; the app runner requires Streamlit to remain open.
