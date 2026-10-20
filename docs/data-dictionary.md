# Data dictionary

## `daily_prices` (prototype)

One NSE cash-market security and series per trading date. The prototype uses
`(trade_date, symbol, series)` as its source-row natural key. Exchange symbols
remain unchanged in Parquet. Research queries derive `instrument_id` and
`source_symbol` from the effective-dated mappings in
`src/nse_strategy_lab/domain/instruments.py`; this currently joins
TATAMOTORS→TMPV and keeps TMCV separate.

| Field | Type | Meaning / rules |
|---|---|---|
| `trade_date` | date | Exchange trading date from the source report; must match the requested report date. |
| `symbol` | string | Uppercase NSE trading symbol from the bhavcopy. Display identifier, not permanent identity. |
| `series` | string | NSE equity series; the parser retains `EQ` and `BE` (trade-to-trade) rows. Other series are excluded from this research dataset. |
| `open` | float | Exchange-reported opening price, INR per share, unadjusted. |
| `high` | float | Exchange-reported daily high, INR per share, unadjusted. |
| `low` | float | Exchange-reported daily low, INR per share, unadjusted. |
| `close` | float | Exchange-reported closing price, INR per share, unadjusted. |
| `volume` | integer | Total traded quantity in shares. |
| `turnover` | float or null | Source-reported traded value. Unit equivalence across legacy and UDiFF inputs is not confirmed; do not compare across formats until verified. |
| `trade_count` | integer or null | Source-reported number of trades. |
| `source_file_id` | string | SHA-256 checksum of the immutable raw ZIP file. |

The price query service also returns derived fields for research and display.
They are computed from the canonical daily rows at query time, so the source
Parquet keeps only exchange-reported values and corrections to historical bars
automatically flow into the result.

| Field | Type | Meaning / rules |
|---|---|---|
| `high_52w` | float | Maximum daily `high` for the same instrument and series in the trailing 364 calendar days, including the row's own date. |
| `low_52w` | float | Minimum daily `low` for the same instrument and series in the trailing 364 calendar days, including the row's own date. |
| `instrument_id` | string | Derived stable identity used to combine date-effective symbols and keep distinct securities separate. Unknown tickers temporarily use their ticker as the identity. |
| `source_symbol` | string | Exact ticker from the exchange report before any query-level company identity mapping. |

The calculation uses only data dated on or before each row, preventing lookahead
in historical strategy signals. Raw queries use unadjusted bhavcopy prices.
Adjusted queries derive these fields from the adjusted OHLCV basis below.

OHLC must be positive and satisfy `low <= open, close <= high`. Volume must be
nonnegative. Corporate-action-adjusted prices are not stored in this dataset;
they are derived from these raw prices and the separate action ledger.

## `market_cap_observations` (Parquet)

One NSE-reported market-cap observation per symbol and source date/period. This
is separate from daily prices and contains no calculated or carried-forward
values. Raw NSE source files are preserved under `data/raw/nse/market_cap/`;
normalized observations are stored under
`data/curated/market_cap_observations/`; import provenance belongs in the
SQLite catalog. See [ADR-0011](decisions/ADR-0011-nse-market-cap-snapshots.md).

| Field | Type | Meaning / rules |
|---|---|---|
| `observation_type` | string | `total_snapshot` for a quote-page point-in-time value or `average_period` for NSE's period average. |
| `as_of_date` | date or null | Date attached to a point-in-time quote; null for period-average observations. Never substitute retrieval date. |
| `period_start`, `period_end` | date or null | Inclusive source period for average observations; null for point-in-time quotes. |
| `symbol` | string | NSE symbol shown by the source for the observation. |
| `isin` | string or null | NSE security ISIN when present. The current all-company workbook does not provide it. |
| `market_cap_inr_crore` | decimal/float | NSE-reported value normalized to ₹ crore. The 2025 workbook provides average market cap in ₹ lakh, converted by the unit factor 100; no market-cap calculation. |
| `source_url` | string | URL of the exact NSE source file or quote page. |
| `source_file_id` | string | SHA-256 checksum identifying the immutable raw response/file. |
| `retrieved_at` | timestamp | UTC time the raw source response was captured. |

An absent observation is unknown, not zero. Workbook rows marked “Not traded
during the period” are omitted and counted in the import output. Do not carry a
value between dates or use a current snapshot in historical backtests. Free-
float market cap is a different measure and is not part of this initial
dataset. Company-size labels require a separate explicit classification rule
and effective date.

## `corporate_actions` (Parquet ledger)

One reviewed event per source ticker, equity series, action type, and ex-date. It is
stored separately at `data/curated/corporate_actions/actions.parquet`. Imports
use `nse-strategy-lab import-actions <csv>` and merge by the natural key
`(symbol, series, action_type, ex_date)`.

| Field | Type | Meaning / rules |
|---|---|---|
| `symbol` | string | Uppercase NSE symbol. |
| `series` | string | Uppercase security series, normally `EQ`. |
| `action_type` | string | `bonus`, `split`, `dividend`, or a specifically reviewed `demerger`. |
| `announcement_date` | date | Public announcement date; required for point-in-time eligibility. |
| `ex_date` | date | Date from which the action is reflected in exchange prices. |
| `record_date` | date or null | NSE's shareholder-record date for eligibility; retained from the export or filing for reconciliation. It does not trigger price adjustment. |
| `share_factor` | float or null | Total shares after / before event. A 1:1 bonus uses `2`; required for bonus/split. |
| `cash_per_share` | float or null | Dividend amount per share entitled on the ex-date; required for dividends. |
| `pay_date` | date or null | Payment date; required before dividend cash is spendable in the backtest. |
| `distributed_symbol`, `distributed_series` | string or null | Child security and its first traded NSE series for a demerger distribution. |
| `distribution_ratio` | float or null | Child shares issued per eligible parent share. |
| `surviving_reference_price` | float or null | Exchange price-discovery reference for one share in the surviving parent security. |
| `distributed_reference_price` | float or null | Exchange or documented reference value for one distributed child share. |
| `terms` | string or null | Human-readable ratio or event terms. |
| `source_url` | string or null | Source filing/report URL. At least one provenance field is required. |
| `source_file_id` | string or null | Identifier/checksum for a locally retained source document. |

## Derived adjusted view

The adjustment service returns `open_adjusted`, `high_adjusted`,
`low_adjusted`, `close_adjusted`, and (when volume exists) `volume_adjusted`,
while retaining raw columns. For bonus/split events announced and effective by
the selected as-of date, bars before the ex-date are divided by
`share_factor`; their volume is multiplied by that factor. Bars on/after the
ex-date stay on the exchange-reported share basis. A chart restates visible
history to its selected end date. Each strategy decision instead receives its
own as-of prefix, so future announcements cannot change past signals.

Cash dividends adjust pre-ex-date OHLC by `(preceding adjusted close -
dividend per share) / preceding adjusted close`, with volume unchanged. This is
not a reinvested total-return series. The engine separately accounts for
dividend receivables when shares are held through the prior close and adds cash
on pay date.

For a reviewed demerger, pre-ex-date parent OHLC is restated by
`surviving_reference_price / preceding adjusted close`; volume is unchanged.
The portfolio engine distributes `distribution_ratio` child shares to each
parent share held through the prior close, allocates the original cost basis
between the parent and child using their documented reference values, and
marks the child at its reference price until an exchange bar is available.
Tata Motors is the implemented demerger case. Other reorganizations remain
unsupported until their terms and accounting are explicitly modeled. Keep raw
columns for reconciliation.

## Derived Tata Motors identity

| Raw exchange symbol | Date interval | Derived `instrument_id` | Research/display symbol |
|---|---|---|---|
| `TATAMOTORS` | Through 2025-10-23 | `TATA_MOTORS_PV` | `TMPV` |
| `TMPV` | From 2025-10-24 | `TATA_MOTORS_PV` | `TMPV` |
| `TMCV` | From its 2025-11-12 trading start | `TATA_MOTORS_CV` | `TMCV` |

The Price Explorer shows TMPV as one company history, retains each row's
`source_symbol`, and adjusts pre-demerger history to the ₹400 surviving-company
reference price discovered on 2025-10-14. TMCV remains a separate company and
has no generated prices before its first trading session.

## `corporate_action_candidates` (review staging)

One row per distinct summary event parsed from an NSE Corporate Actions CSV
export. Stored at
`data/curated/corporate_action_candidates/candidates.parquet`; each source
export also produces a CSV review file in that directory. This dataset is not
used by price adjustments or strategy code.

| Field | Type | Meaning / rules |
|---|---|---|
| `candidate_id` | string | SHA-256 of normalized symbol, series, purpose, ex-date, and record-date fields; used to deduplicate repeated exports in the shared candidate dataset. Per-export review CSVs preserve all source rows. |
| `symbol`, `company_name`, `series` | string | NSE identifiers/names as exported; symbol and series are normalized to uppercase. |
| `purpose` | string | Original NSE purpose text; retained for audit and manual interpretation. |
| `face_value` | string or null | Face-value text from the listing export. |
| `ex_date`, `record_date`, `book_closure_start_date`, `book_closure_end_date` | date or null | Parsed NSE dates; absent/invalid dates remain null for review. |
| `event_type_guess` | string | Parser classification only. It is not the canonical action type and cannot drive adjustments. |
| `share_factor_guess`, `cash_per_share_guess` | float or null | Best-effort extraction from purpose text; requires filing verification. |
| `review_status` | string | New candidates start as `needs_review`; unchanged rows retain review status, while changed or missing rows return to `needs_review`. |
| `review_notes` | string | Why/how the candidate needs review, including parse limitations. |
| `discovery_status` | string | `new`, `changed`, `unchanged`, or `missing` relative to the preceding staged snapshot. A candidate is `missing` when it is absent from an export whose declared coverage window includes its ex-date; this is a review flag, never a ledger deletion. |
| `missing_source_file_id` | string or null | Checksum ID of the export in which a previously staged candidate was first found missing. |
| `source_file_id` | string | SHA-256 of the exact archived NSE export bytes. |
| `source_url`, `source_filename`, `imported_at` | string | NSE export page URL, original filename, and UTC retrieval time. The selected range is stored with the source-file manifest. |

## Corporate-action import manifest (SQLite)

`corporate_action_imports` records each unique export checksum, source URL,
retrieval time, inclusive date range selected for the export when known,
immutable raw path, byte count, parser status, staged row count, and any parse
failure. The stage command also writes an all-row review CSV and a new/changed
delta CSV. Raw exports are stored under
`data/raw/nse/corporate_actions/`. The CLI stages the entire export without a
symbol filter; only separately reviewed, supported rows enter the canonical
`corporate_actions` Parquet ledger.
