# Data dictionary

## `daily_prices` (prototype)

One NSE cash-market security and series per trading date. The prototype uses
`(trade_date, symbol, series)` as its natural key; a dated instrument mapping
will replace symbol-only identity before broad historical research.

| Field | Type | Meaning / rules |
|---|---|---|
| `trade_date` | date | Exchange trading date from the source report; must match the requested report date. |
| `symbol` | string | Uppercase NSE trading symbol from the bhavcopy. Display identifier, not permanent identity. |
| `series` | string | NSE equity series; the first parser retains `EQ` series only. |
| `open` | float | Exchange-reported opening price, INR per share, unadjusted. |
| `high` | float | Exchange-reported daily high, INR per share, unadjusted. |
| `low` | float | Exchange-reported daily low, INR per share, unadjusted. |
| `close` | float | Exchange-reported closing price, INR per share, unadjusted. |
| `volume` | integer | Total traded quantity in shares. |
| `turnover` | float or null | Source-reported traded value. Unit equivalence across legacy and UDiFF inputs is not confirmed; do not compare across formats until verified. |
| `trade_count` | integer or null | Source-reported number of trades. |
| `source_file_id` | string | SHA-256 checksum of the immutable raw ZIP file. |

The price query service also returns two derived fields for research and display.
They are computed from the canonical daily rows at query time, so the source
Parquet keeps only exchange-reported values and corrections to historical bars
automatically flow into the result.

| Field | Type | Meaning / rules |
|---|---|---|
| `high_52w` | float | Maximum daily `high` for the same symbol and series in the trailing 364 calendar days, including the row's own date. |
| `low_52w` | float | Minimum daily `low` for the same symbol and series in the trailing 364 calendar days, including the row's own date. |

The calculation uses only data dated on or before each row, preventing lookahead
in historical strategy signals. Raw queries use unadjusted bhavcopy prices.
Adjusted queries derive these fields from the adjusted OHLCV basis below.

OHLC must be positive and satisfy `low <= open, close <= high`. Volume must be
nonnegative. Corporate-action-adjusted prices are not stored in this dataset;
they are derived from these raw prices and the separate action ledger.

## `corporate_actions` (Parquet ledger)

One reviewed event per symbol, equity series, action type, and ex-date. It is
stored separately at `data/curated/corporate_actions/actions.parquet`. Imports
use `nse-strategy-lab import-actions <csv>` and merge by the natural key
`(symbol, series, action_type, ex_date)`.

| Field | Type | Meaning / rules |
|---|---|---|
| `symbol` | string | Uppercase NSE symbol. |
| `series` | string | Uppercase security series, normally `EQ`. |
| `action_type` | string | `bonus`, `split`, or `dividend`. |
| `announcement_date` | date | Public announcement date; required for point-in-time eligibility. |
| `ex_date` | date | Date from which the action is reflected in exchange prices. |
| `record_date` | date or null | NSE's shareholder-record date for eligibility; retained from the export or filing for reconciliation. It does not trigger price adjustment. |
| `share_factor` | float or null | Total shares after / before event. A 1:1 bonus uses `2`; required for bonus/split. |
| `cash_per_share` | float or null | Dividend amount per share entitled on the ex-date; required for dividends. |
| `pay_date` | date or null | Payment date; required before dividend cash is spendable in the backtest. |
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
on pay date. Rights issues, mergers, and other complex events are unsupported.
Keep raw columns for reconciliation.

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
