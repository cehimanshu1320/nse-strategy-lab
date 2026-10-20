# ADR-0011: Store NSE-reported market-cap observations

- Status: accepted
- Date: 2026-10-20
- Owners: project

## Context

Company size is useful for selecting and comparing research candidates. The
daily NSE bhavcopy contains prices and turnover, but no market capitalization.
Reconstructing market cap locally would require point-in-time share counts and
additional corporate-action handling. NSE company quote pages report total and
free-float market-cap values directly, while NSE's all-company market-cap page
publishes dated reference files at irregular intervals.

## Decision

- Use the NSE company quote page's **Total Market Cap (₹ Cr.)** for point-in-time
  observations. Do not calculate or replace the reported value. Free-float
  market cap is a distinct measure and is out of scope for the initial dataset.
- Preserve source observations for companies selected for research, including
  companies outside the current Nifty 50. When an NSE all-company file is
  imported, retain its full available company coverage. Record the quote's
  as-of date or workbook period, retrieval time, symbol, ISIN when available,
  measure, value, source URL, and checksum of the retained raw response. Never
  backfill missing dates by carrying a later value backward or calculating one.
- Preserve source responses under `data/raw/nse/market_cap/`; store normalized
  observations in a separate `market_cap_observations` Parquet dataset under
  `data/curated/market_cap_observations/`. Keep small import/run provenance in
  `data/catalog.sqlite`.
- NSE's all-company workbook is accepted as a distinct `average_period`
  observation when it reports an average market-cap period. Preserve its exact
  period start/end and unit semantics. Do not present the period average as a
  point-in-time total-cap snapshot. For the downloaded July 1–December 31, 2025
  workbook, NSE reports average market capitalization in rupees lakh; normalize
  to ₹ crore by dividing the reported unit by 100.
- Store all market-cap observations in `data/curated/market_cap_observations/`
  with raw sources under `data/raw/nse/market_cap/` and import metadata in
  `data/catalog.sqlite`.
- The irregular all-company workbook is imported explicitly on demand. Do not
  schedule it as a daily job. The current importer uses the downloadable
  workbook listed on NSE's [Eligibility based on Market Capitalisation page](https://www.nseindia.com/static/regulations/listing-compliance/nse-market-capitalisation-all-companies).
  Refresh cadence: **manual, once when NSE publishes a new workbook**; NSE does
  not provide a fixed publication interval on that page, so the app does not
  poll it and no scheduler is configured. Quote-page snapshots remain a
  possible additional source for current values, gated on validating response
  semantics and data-use terms. They are not currently imported.
- A point-in-time snapshot supports classification only as of its recorded
  date; a period average supports classification only for its stated period.
  Do not use current values in historical backtests. Any large/mid/small-cap
  labels must use a separately documented classification rule and effective
  date.
- Before automated bulk retrieval is enabled, validate the NSE response
  contract, quote timestamp/value semantics, sample values, and applicable
  NSE data-use terms. Fail closed if the page or response changes. Do not
  redistribute stored NSE data.

## Consequences

- The app can use NSE-published values without maintaining share-count history
  or deriving market capitalization.
- NSE's published all-company workbook is an average across a six-month period,
  not a daily history. Coverage is limited to dates and periods NSE publishes.
- The source route is a public web page rather than a versioned bulk API, so
  its adapter needs response validation and source archiving. Automated
  collection remains gated on the source-contract and terms checks above.
- Market-cap snapshots remain separate from `daily_prices`; the latter stays
  faithful to the bhavcopy schema.

## Alternatives considered

- Calculate market cap from closing prices and shares outstanding: rejected for
  the initial feature because it requires additional point-in-time inputs and
  reconciliation logic.
- Use an external data vendor: rejected because an official NSE-reported value
  is available and the project has not approved a new vendor.
- Treat NSE's dated regulatory workbook as point-in-time total market cap:
  rejected when the workbook explicitly reports a period average.
