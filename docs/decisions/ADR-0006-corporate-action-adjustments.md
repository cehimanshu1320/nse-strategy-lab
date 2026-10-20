# ADR-0006: Keep raw prices and derive point-in-time adjusted views

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Bhavcopy OHLCV is source-faithful but can contain mechanical gaps around bonus,
split, and dividend ex-dates. Rewriting those observations would harm
auditability; using raw series directly can create false strategy signals.
Strategies must not use a corporate action before it was publicly announced.

## Decision

- Keep `daily_prices` unchanged as exchange-reported raw observations.
- Store reviewed corporate actions in a separate `corporate_actions` Parquet
  ledger, keyed by symbol, series, action type, and ex-date. Retain
  announcement/ex-dates, the optional source `record_date`, terms, and source
  provenance. `ex_date` controls price restatement; `record_date` is retained
  for entitlement reconciliation and audit.
- Do not materialize a second adjusted-price table yet. Derive named adjusted
  OHLCV fields in the adjustment service from raw bars plus the action ledger.
  A chart snapshot is adjusted to its selected end date.
- For strategy evaluation, recompute the adjusted historical prefix as of each
  decision session. An event affects a signal only once its announcement and
  ex-dates are on or before that session, preventing lookahead.
- Bonus/split factors express total post-event shares per pre-event share. A
  1:1 bonus uses `share_factor=2`: earlier prices are divided by two and
  earlier volume is multiplied by two.
- Cash dividends adjust pre-ex-date OHLC by `(preceding adjusted close -
  dividend per share) / preceding adjusted close`; volume is unchanged. This is
  a price series adjustment, not a reinvested total-return series.
- Backtests receive signals from adjusted bars but execute and mark holdings at
  raw prices. At a bonus/split ex-date, multiply held quantity by the factor
  and divide per-share cost basis by it. Dividends create a receivable for
  positions held through the prior close; cash becomes spendable on pay date.
- Initially support bonus, split, and cash dividend. Tata Motors' reviewed
  2025 demerger is added as a specifically modeled distribution under
  [ADR-0010](ADR-0010-tata-motors-demerger-and-security-identity.md). Event
  data is explicitly imported/reviewed; app rendering never scrapes it.

## Consequences

- Raw exchange values remain auditable and comparable with the source.
- The UI can show raw and adjusted values together; adjusted 52-week extrema
  use the selected price basis.
- Strategy signals remain point-in-time. The prototype recomputes each date's
  prefix, which is simple and correct but can be slow on larger datasets; later
  optimization must preserve the same as-of behavior.
- Incorrect or missing event records can distort adjusted history, so the
  ledger requires a source URL or source-file identifier.
- Rights issues, mergers, and reorganizations other than the specifically
  modeled Tata Motors demerger remain unsupported. ADR-0010 defines the
  TATAMOTORS/TMPV identity, TMCV distribution, price basis, and portfolio
  treatment for that event.

## Alternatives considered

- **Rewrite raw prices in place:** rejected because this loses source values and
  makes audit/reconciliation difficult.
- **Store a permanently adjusted price table now:** deferred because adjusted
  values can change as events are announced or source corrections arrive.
- **Apply all known events to every historical signal:** rejected because it
  leaks future announcements into earlier decisions.
