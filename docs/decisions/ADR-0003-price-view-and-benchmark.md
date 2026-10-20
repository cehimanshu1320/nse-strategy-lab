# ADR-0003: Price views, initial universe, and benchmark

- Status: accepted
- Date: 2026-10-13
- Owners: project

## Context

The first dashboard should make it easy to inspect the current Nifty 50
companies and compare strategy results to a relevant market benchmark. The
source price history and any corporate-action-adjusted series must remain
distinguishable.

## Decision

- Use the current Nifty 50 constituents as the initial charting watchlist and
  save each captured roster with its effective/capture date and source.
- Preserve exchange-reported OHLCV as the raw price basis. Do not overwrite it
  with adjusted values.
- Add a separate, clearly labeled adjusted-price view only after corporate
  actions and an adjustment method have been documented and validated.
- Use the NIFTY 50 Total Returns Index (TRI) as the initial strategy benchmark,
  subject to confirming an allowed, repeatable data source for it.
- Treat the captured roster as an initial company watchlist, not as a
  point-in-time reconstruction of the Nifty 50 index portfolio. Strategies
  research companies directly; historical index constituent membership is
  outside the current product scope.

## Consequences

- Charts can begin with a simple exchange-reported close series and explicitly
  disclose its adjustment status.
- Benchmark returns include the total-return concept represented by TRI;
  benchmark observations and source provenance must be stored alongside the
  benchmark identity.
- The current roster is a user-selected research starting point. Results must
  describe the selected companies and dates, not claim to represent historical
  Nifty 50 constituents.
- These product choices do not grant permission to collect or use NSE data;
  source rights remain governed by ADR-0002's open gate.
