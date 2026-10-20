# ADR-0001: Research scope and execution model

- Status: accepted
- Date: 2026-10-13
- Owners: project

## Context

The initial product is for one person to explore and compare strategies on
Indian equities without creating a general-purpose public trading platform.

## Decision

- Start with NSE cash equities and daily/swing strategies.
- Use Python modules to define strategies; do not build a visual rule editor in
  the first release.
- Start with a Nifty 50 watchlist and at least five years of daily OHLCV.
- Use one shared-cash, long-only portfolio model in the initial backtester.
- Signals computed from a close execute no earlier than the next available
  session's open in the initial fill model.
- Keep the product local and private while validating data and research
  behavior; no order placement or live trading in this scope.

## Consequences

- Strategy code stays inspectable and versionable in Git.
- Shared-cash results account for competing entries and constrained capital.
- The captured Nifty 50 roster is the initial set of companies to research.
  Strategies operate on explicitly selected companies; they do not claim to
  recreate the Nifty 50 index portfolio or its historical membership.
- Costs/slippage and fill semantics must be stored with every research run.

## Alternatives considered

- A no-code strategy editor was deferred because Python is the chosen first
  interface and the editor would add significant UI complexity.
- Live trading and intraday/options data were deferred to keep the first data
  and execution model manageable.
