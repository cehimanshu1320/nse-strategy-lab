# ADR-0005: Derive historical 52-week extrema from daily bars

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Strategies may use a stock's 52-week high and low, and the Price Explorer
should make those values inspectable. The project imports daily NSE bhavcopy
bars for a multi-year period. NSE's separate 52 Week High Low Report includes
corporate-action-adjusted values, while bhavcopy provides actual unadjusted
daily prices. The report is not currently part of the historical importer.

## Decision

Derive `high_52w` and `low_52w` from stored daily prices in the read/query layer:

- `high_52w` is the maximum daily `high` for that symbol and series over the
  trailing 364 calendar days, including the current row's date.
- `low_52w` is the minimum daily `low` over the same period.
- A row uses only observations with dates on or before its own date.
- The canonical Parquet price records remain source-faithful and unadjusted;
  derived fields are not duplicated in the stored price partitions.

This produces a historical as-of value for every loaded session and avoids
lookahead. Corrections to stored daily bars flow through the derived values
without a separate feature rebuild.

## Consequences

- Price queries, CSV exports, and strategy code using the price query service
  can consume the same 52-week fields.
- The raw query's values remain raw-price extrema. The adjusted price query
  separately derives adjusted extrema using the point-in-time event rules in
  [ADR-0006](ADR-0006-corporate-action-adjustments.md).
- Each consumer must select and label its price basis; raw extrema can be
  distorted around corporate actions.
