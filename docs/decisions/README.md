# Decision records

`docs/project-status.md` summarizes current accepted choices and open gates;
the ADR is the detailed record and rationale. Update both when a decision is
accepted, rejected, or superseded.

Architecture Decision Records (ADRs) capture decisions that affect multiple
modules or are costly to reverse. Keep them short and append-only: do not erase
the reasoning when a decision changes. Mark the old record superseded and add a
new ADR linking to it.

## When to write an ADR

Write one when choosing or changing a data provider, canonical data contract,
storage/deployment model, backtest semantics, or a dependency that shapes the
architecture. Routine implementation details do not need an ADR.

## Template

```markdown
# ADR-NNNN: Short decision title

- Status: proposed | accepted | superseded
- Date: YYYY-MM-DD
- Owners: project

## Context
What problem or constraint requires a decision?

## Decision
What are we choosing?

## Consequences
Benefits, costs, constraints, and migration implications.

## Alternatives considered
Options and why they were not chosen.
```

## Records

- [ADR-0001: Research scope and execution model](ADR-0001-research-scope.md)
- [ADR-0002: Local data storage and source strategy](ADR-0002-local-data-storage.md)
- [ADR-0003: Price views, initial universe, and benchmark](ADR-0003-price-view-and-benchmark.md)
- [ADR-0004: Initial NSE file acquisition](ADR-0004-nse-file-acquisition.md)
- [ADR-0005: Derive historical 52-week extrema from daily bars](ADR-0005-52-week-extrema.md)
- [ADR-0006: Keep raw prices and derive point-in-time adjusted views](ADR-0006-corporate-action-adjustments.md)
- [ADR-0007: Stage NSE corporate-action exports before approval](ADR-0007-nse-corporate-action-ingestion.md)
- [ADR-0008: Keep scheduled jobs independent from their runner](ADR-0008-durable-scheduler-and-hosted-runner.md)
- [ADR-0009: Research selected companies, not historical index membership](ADR-0009-company-selection-not-index-replication.md)
- [ADR-0010: Model the Tata Motors demerger across its two securities](ADR-0010-tata-motors-demerger-and-security-identity.md)
- [ADR-0011: Store NSE-reported market-cap snapshots](ADR-0011-nse-market-cap-snapshots.md)
