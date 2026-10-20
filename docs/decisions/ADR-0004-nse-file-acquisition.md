# ADR-0004: Initial NSE file acquisition

- Status: accepted for the prototype
- Date: 2026-10-13
- Scope amended: 2026-10-18 to retain BE alongside EQ
- Owners: project

## Context

The project owner wants to start with NSE market data for private research and
does not plan to redistribute it. NSE publishes daily CM-UDiFF bhavcopy
archives. The project owner has decided to use NSE data during the prototype
and revisit the source after testing. The source terms contain restrictions on
automated collection and simulation; this records the owner's working
interpretation, not a legal determination.

## Decision

- Use date-specific NSE CM bhavcopy archive URLs for the prototype backfill
  and daily refresh. Select legacy-format archives before the UDiFF transition
  and CM-UDiFF archives from the transition onward.
- Current UDiFF pattern: `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`.
- Legacy pattern: `https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip`.
- Use the UDiFF pattern from 2024-07-08 onward; the NSE report page marks the
  previous CM bhavcopy formats discontinued from that date.
- Keep the downloader in an explicit CLI job, never in Streamlit page rendering.
- Save original ZIP files, checksums, retrieval metadata, normalized prices,
  and import results locally.
- Retain `EQ` and `BE` cash-equity series from CM bhavcopies. `BE` rows are
  needed to capture a security's early trading history when NSE lists it in
  trade-to-trade before moving it to `EQ` (for example, JIOFIN in 2023).
  Exclude non-cash-equity series and preserve the source `series` value in the
  canonical key; do not coalesce rows across series.
- Revisit the data source before the project moves beyond the prototype.

## Consequences

- A single daily bhavcopy supplies the market-wide rows needed for all current
  watchlist symbols and simplifies data coverage checks.
- The importer must handle both legacy and UDiFF formats because the five-year
  backfill crosses the July 2024 format change.
- The published restriction on simulation remains a known unresolved
  interpretation issue for backtesting and automated collection; the project
  owner's current interpretation is recorded so prototype work can proceed.
- The importer remains source-adapter based so a later licensed source can be
  added without changing canonical storage or the dashboard.
