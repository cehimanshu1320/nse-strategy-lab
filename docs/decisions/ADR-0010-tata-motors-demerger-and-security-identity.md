# ADR-0010: Model the Tata Motors demerger across its two securities

- Status: accepted
- Date: 2026-10-19
- Owners: project

This decision extends the initial action support described in
[ADR-0006](ADR-0006-corporate-action-adjustments.md) for the Tata Motors event.
Other mergers and reorganizations remain out of scope until separately
verified and modeled.

## Context

The NSE symbol changed from TATAMOTORS to TMPV for the continuing passenger
vehicle, EV, and JLR company effective 2025-10-24. The commercial-vehicle
business was distributed as a separate TMCV security at one share per eligible
parent share. The record/ex-date was 2025-10-14. The NSE special pre-open
session established a ₹400 reference price for the surviving security; the
previous close was ₹660.75, implying a ₹260.75 reference for the distributed
share. TMCV traded in BE from 2025-11-12 through 2025-11-25 and EQ from
2025-11-26.

## Decision

- Keep source bhavcopy rows unchanged and keyed by their reported symbol.
- Map TATAMOTORS and TMPV to one derived stable instrument identity, with the
  symbol change effective 2025-10-24. Map TMCV to a different instrument.
- Restate pre-ex-date TATAMOTORS OHLC to the surviving TMPV basis using
  `400 / preceding close`; do not change volume or raw values. Do not adjust
  bars on or after the ex-date.
- On the ex-date, backtests distribute one TMCV share for every eligible
  parent share held through the prior close. Allocate original entry cost
  between TMPV and TMCV using the relative ₹400 and ₹260.75 reference values.
- Mark distributed TMCV shares at ₹260.75 until a TMCV exchange bar exists;
  use actual raw bars thereafter. TMCV is not an alias or predecessor of TMPV.
- Preserve TMCV's BE-to-EQ series transition as source rows for the same
  security identity.
- Store the reviewed canonical event in
  `configs/corporate_actions/tata_motors_demerger_2025.csv`; import it into
  local Parquet with the normal `import-actions` command. Do not auto-approve
  other corporate-action candidates.

## Consequences

- Selecting TMPV in the Price Explorer includes the prior TATAMOTORS ticker
  history, displays the source ticker, and offers raw or demerger-adjusted
  prices. Selecting TMCV displays its independent listing history.
- A portfolio holding through the demerger retains both resulting positions
  and the original combined cost basis, preventing the share distribution from
  appearing as an artificial loss.
- Existing raw Parquet and corporate-action ledgers remain readable. New
  action fields are nullable for existing events; no raw-market-data rewrite
  is needed. Missing local TMCV BE rows can be restored from archived bhavcopy
  ZIPs using the normal parser/import path.
- The current symbol map is domain code, not a complete NSE instrument master.
  New rename/reorganization mappings still require an explicit reviewed entry.

## Evidence

- [Tata Motors scheme announcement](https://www.tatamotors.com/press-releases/demerger-of-cv-business-undertaking-of-tata-motors-ltd-into-a-separate-listed-company/)
- [NSE special pre-open session circular](https://nsearchives.nseindia.com/content/circulars/CMTR70614.pdf)
- [NSE symbol-change circular](https://nsearchives.nseindia.com/content/circulars/FAOP70882.pdf)
- The archived NSE bhavcopy for 2025-10-13 reports the ₹660.75 previous close;
  the 2025-10-14 bhavcopy reports the ₹400 open following price discovery.
- Tata Motors CV confirms listing under TMCV from 2025-11-12:
  [TMCV results and listing note](https://cv.tatamotors.com/news/tata-motors-limited-formerly-tml-commercial-vehicles-ltd-Q2-FY26-results-commercial-vehicles-segment-financials)

## Alternatives considered

- **Concatenate the two symbols without an adjustment:** rejected because the
  exchange price drop reflects the distributed CV business, not a market loss
  in the surviving TMPV security.
- **Apply a 1:1 price multiplier:** rejected because the 1:1 ratio describes
  share entitlement, while the two securities have different reference prices.
- **Rewrite raw history or merge TMCV into TMPV:** rejected because raw exchange
  evidence and the two resulting securities must remain separately auditable.
