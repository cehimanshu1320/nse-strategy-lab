# NSE Strategy Lab

A local-first Python research app for daily NSE equity strategies. The first
version runs coded strategies against uploaded daily price history using one
shared cash balance.

## Project context

- [Current project status and next action](docs/project-status.md).
- [Implementation plan](docs/implementation-plan.md): scope and milestones.
- [Architecture](docs/architecture.md): system boundaries and data flow.
- [Decision records](docs/decisions/README.md): durable design decisions.
- [Development workflow](docs/development-workflow.md): onboarding and
  parallel work guidance.

Coding chats and agents should read the root [AGENTS.md](AGENTS.md) before
making substantial changes.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
streamlit run app.py
```

Install the test extra and run the unit and Streamlit UI tests with:

```bash
pip install -e ".[test]"
python -m pytest
```

Dependencies include the local market-data store and NSE import CLI. Once
installed, start an explicit five-year import with:

```bash
nse-strategy-lab backfill
```

For a small first import, pass a short date range and one or more symbols:

```bash
nse-strategy-lab backfill --start 2024-07-01 --end 2024-07-12 --symbols RELIANCE,SBIN
```

The importer stores original ZIPs under `data/raw/`, normalized monthly
Parquet under `data/curated/`, and provenance/import status in
`data/catalog.sqlite`. Run `nse-strategy-lab refresh` to catch up from the
latest imported session. The Streamlit app reads local data only; it never
starts downloads during page rendering.

To download the rolling five-year history plus one year of announced future
NSE corporate actions and stage it for review, run:

```bash
nse-strategy-lab refresh-actions
```

This archives the exact export under `data/raw/nse/corporate_actions/`, records
its checksum and import status in `data/catalog.sqlite`, and stages candidates
for every symbol in `data/curated/corporate_action_candidates/`. A review CSV is
written beside the candidate Parquet, along with a CSV containing new or changed
rows. Staging reports candidates that are new, changed, unchanged, or missing
from a later export within the declared date window. Missing rows are flagged
for review and never remove approved ledger events. Guessed
event types/ratios are review hints only and never alter prices. The inclusive
export range is stored in the SQLite manifest. Candidates are
collected for all symbols, independent of the current Nifty 50 strategy
watchlist. The route is not a versioned public API; the NSE adapter validates
the response and fails closed if the page changes or returns an error. If that
happens, download the CSV manually from the [NSE Corporate Actions
page](https://www.nseindia.com/companies-listing/corporate-filings-actions)
and stage it with `stage-nse-actions <csv> --start-date YYYY-MM-DD --end-date
YYYY-MM-DD`.

### Local scheduled refreshes

The app's **Schedulers** workspace stores schedule definitions and run history
in `data/catalog.sqlite`. While the app process is open, a background runner
checks weekday schedules in Asia/Kolkata time: corporate actions at 18:30 and
daily prices at 18:40. When the app starts, missed weekday occurrences are
coalesced into one current run for each job. Each schedule has a **Run** button
to queue only that job immediately, without changing its enabled state. The
single **Run all due jobs** button beside the scheduled-job list queues every
enabled job that is due now. The app must remain open for clock-based runs; due
work is checked again the next time it starts.

Operational cadence, run time, timezone, and catch-up policy are in
`configs/schedules.toml`. Edit that file and restart the app to apply schedule
changes; the enabled/disabled choice remains persisted in the local catalog.
Job behavior is registered separately in the app and remains in application
services.

The corporate-action job archives the exact rolling export and stages
candidates for review. It never approves events. The price job catches up from
the last imported session; if no prices are loaded, it starts with only the
most recent 14 calendar days. Use the explicit `backfill` command for the
five-year initial history.

The previous macOS LaunchAgent was removed after the app runner's live manual
refreshes succeeded. The app runner is the active local scheduler; it requires
the Streamlit process to remain open for clock-based runs.

Run the automated refresh immediately:

```bash
nse-strategy-lab refresh-actions
```

The NSE All Reports page also lists a daily `Bhavcopy (PR)` ZIP, and NSE
documents its filename and website location in the [Press Files Report
circular](https://nsearchives.nseindia.com/content/circulars/CMTR70563.pdf).
We inspected the ZIP's corporate-action CSV: the sample covered only three
ex-dates and omitted filing-level terms such as announcement and dividend-pay
dates. It cannot replace the five-year CSV export. The sample is preserved at
`data/raw/nse/corporate_action_press_files/2026/10/PR141026.zip`; see
[ADR-0007](docs/decisions/ADR-0007-nse-corporate-action-ingestion.md) for the
field and coverage findings.

Create a verification worksheet for pending supported NSE equity events. When
symbols are supplied, it includes all pending events for those symbols; without
symbols, it limits the worksheet to the latest export's new/changed candidates.
Limit it to the symbols being researched to keep filing review manageable:

```bash
nse-strategy-lab export-action-review \
  --symbols RELIANCE,SBIN \
  --output data/curated/corporate_action_candidates/review_watchlist.csv
```

Verify each row against its company filing. Fill `action_type`,
`announcement_date`, and the verified share/dividend terms; dividends also need
`pay_date`. Keep `record_date` from NSE when present, set `review_status` to
`approved`, and add the filing URL. Guessed values are deliberately kept in
separate `suggested_*` columns. Import only approved rows:

```bash
nse-strategy-lab import-reviewed-actions \
  data/curated/corporate_action_candidates/review_watchlist.csv
```

The command validates required fields, promotes approved rows to the canonical
ledger, and leaves unapproved rows out of price adjustments. `record_date` is
retained for audit; adjusted history is triggered by `ex_date`.

For already canonical, reviewed datasets, the lower-level `import-actions`
command is also available. Required columns are
`symbol,series,action_type,announcement_date,ex_date`; `record_date` is optional;
bonus/split rows also need `share_factor`, and dividend rows need
`cash_per_share,pay_date`. Every row
must include `source_url` or `source_file_id`. Example:

```bash
nse-strategy-lab import-actions actions.csv
```

The Price Explorer defaults to the corporate-action-adjusted view and also
offers raw exchange prices. Adjusted history is derived from raw prices and the
action ledger; no duplicate adjusted-price table is stored. The backtest page
can accept the same action CSV: strategies receive point-in-time adjusted
history, while simulated fills and marks use raw prices. Bonus/split events
adjust held share counts; dividends adjust historical signal prices and are
credited to portfolio cash on pay date. Rights issues and complex
reorganizations are not modeled yet.

By default, imported Parquet includes every `EQ`-series security in each daily
bhavcopy. Pass `--symbols` to limit curated rows to a comma-separated list; the
original source ZIP is still retained unchanged.

## Price CSV format

Provide one row per session and symbol with at least these columns:

```text
date,symbol,open,close
2024-01-02,RELIANCE,2580,2590
```

`high`, `low`, and `volume` can also be included. Signals are computed from
closing data and orders execute at the next available session's open. The
portfolio is long-only, uses whole shares, sells before buying on each open,
and divides available cash equally among simultaneous entry signals. Fees and
slippage are configurable in the app.

## Add a strategy

Create a function in `src/nse_strategy_lab/strategies.py` that accepts the bars
DataFrame and returns `date`, `symbol`, `entry`, and `exit` columns. Register it
in `STRATEGIES`. The engine owns execution timing and portfolio accounting so
strategy comparisons use the same assumptions.

## Data notes

The prototype imports date-based NSE CM bhavcopy archives using legacy and
UDiFF parsers. The owner has chosen this source for the testing phase; the
source is subject to reassessment after testing. Market data is local-only and
excluded from Git. Canonical stored prices are exchange-reported and
unadjusted. See
[`docs/data-dictionary.md`](docs/data-dictionary.md) for fields and
[`docs/decisions/ADR-0004-nse-file-acquisition.md`](docs/decisions/ADR-0004-nse-file-acquisition.md)
for the source decision.
