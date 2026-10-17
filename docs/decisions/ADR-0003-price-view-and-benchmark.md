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
- Do not describe a strategy run on today's roster across older dates as a
  point-in-time Nifty 50 backtest. Historical constituent membership is a
  separate future data requirement.

## Consequences

- Charts can begin with a simple exchange-reported close series and explicitly
  disclose its adjustment status.
- Benchmark returns include the total-return concept represented by TRI;
  benchmark observations and source provenance must be stored alongside the
  benchmark identity.
- The current roster supports charting and prototyping, but introduces
  survivorship bias when applied to historical cross-sectional backtests.
- These product choices do not grant permission to collect or use NSE data;
  source rights remain governed by ADR-0002's open gate.
