# ADR-0009: Research selected companies, not historical index membership

- Status: accepted
- Date: 2026-10-19
- Owners: project

## Context

The current Nifty 50 roster seeded the initial watchlist, which led to a
proposed requirement to obtain effective-dated Nifty 50 entries and exits for
historical backtests. The project owner clarified that research will select
companies directly and does not need to reproduce the index's changing
constituent portfolio.

## Decision

- Treat the captured Nifty 50 roster as a convenient starting list of
  companies, not as the universe definition for every strategy run.
- Strategies and research runs use explicitly selected companies and dates.
- Historical index membership is not a release gate or required dataset.
- Do not label results as a historical Nifty 50 portfolio/index-replication
  backtest. A future request to reproduce an index portfolio requires a
  separate scope decision and point-in-time constituent data.

## Consequences

- Current project data and strategies do not need historical Nifty 50 entry
  and exit dates.
- Run metadata and user-facing labels should identify selected companies rather
  than imply that current constituents were index members throughout the past.
- An index-membership dataset may be added later only for a separately scoped
  index-replication feature.

## Alternatives considered

- **Reconstruct historical Nifty 50 membership now:** deferred because the
  current research workflow selects companies directly and does not need to
  model index additions, removals, or index rebalancing.
