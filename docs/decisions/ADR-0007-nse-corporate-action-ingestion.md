# ADR-0007: Stage NSE corporate-action exports before approval

- **Status:** Accepted
- **Date:** 2026-10-13; automated retrieval accepted 2026-10-17

The launchd operating mechanism described below was superseded on 2026-10-17
by [ADR-0008](ADR-0008-durable-scheduler-and-hosted-runner.md). The action
source, validation, archiving, candidate review, and explicit promotion
decisions in this ADR remain accepted.

## Context

The NSE public Corporate Actions page exposes CSV exports with symbol, series,
purpose, face value, ex-date, record date, and book-closure dates. Purpose text
is not a sufficient canonical event contract for every action: exact terms,
announcement date, dividend payment date, and complex consideration may need
the linked company filing. A durable workflow must support all listed symbols,
retain source evidence, and avoid treating guesses as adjustment facts.

## Decision

- Use the CSV export offered by NSE's public Corporate Actions page as the
  market-wide discovery input. An explicit CLI job retrieves the same export
  through the page's current CSV route, using an inclusive rolling window of
  five years before today through one year ahead. This route is not a versioned
  public API; keep it isolated in the NSE source adapter, validate every
  response, and fail closed if NSE changes or blocks it. The Streamlit app
  never downloads or mutates data during page rendering.
- Archive the exact CSV bytes under `data/raw/nse/corporate_actions/`, keyed by
  SHA-256, and record source URL, retrieval time, path, size, parse status, and
  staged row count in SQLite.
- Parse every symbol in the export into a review-candidate dataset. Preserve
  the NSE purpose text and dates; infer an event-type/factor guess only as a
  convenience. Mark every candidate `needs_review` and retain unclassified
  and unsupported event types rather than dropping them.
- Compare each staged export with prior candidates and label rows new, changed,
  unchanged, or missing from the latest export. Preserve review decisions for
  unchanged rows and reset changed or missing rows to `needs_review`. Mark a
  prior candidate missing only when the caller supplies the date window covered
  by the export. Missing is a review signal, never an instruction to delete an
  approved ledger event.
- Provide a review worksheet for supported `EQ` bonus, split, and dividend
  candidates. Guessed terms are shown only as hints; the reviewer enters
  verified canonical terms and explicitly marks each accepted row `approved`.
- Store the NSE `record_date` in the canonical event ledger when available.
  Price adjustment continues to use `ex_date`; `record_date` supports
  reconciliation and entitlement review.
- Require a reviewer to verify event terms and announcement details against
  the linked company filing. Only completed, supported canonical records can
  be imported into the `corporate_actions` adjustment ledger.
- Make corporate-action discovery a weekday after-close operating requirement.
  The schedule is defined independently from the execution host. Local
  app-start catch-up and manual triggers use the same `refresh-actions`
  workflow; a future hosted deployment uses a worker or managed scheduler.
  `stage-nse-actions` remains available for manual exports if the page route
  changes. See ADR-0008 for run history, leases, and catch-up behavior.
- Record the inclusive rolling range in the source manifest. It covers the
  project's five-year price research horizon and one year of announced future
  actions. The downloader accepts explicit dates for bounded recovery or
  historical imports.
- Keep candidate collection broad across NSE-listed symbols; current Nifty 50
  membership is not a collection filter. Restrict adjusted-price features
  separately to event types the engine can model correctly.
- NSE's daily `Bhavcopy (PR)` ZIP is listed on the official All Reports page,
  and the exchange circular documents its name and public website location.
  The 2026-10-15 sample validation below confirms it can be a short-horizon
  supplementary discovery feed, but it cannot replace the five-year CSV
  baseline. The PR feed is not the active corporate-action input because the
  page CSV provides a rolling market-wide snapshot and fuller fields.

## Consequences

- The original export and row-level provenance can be audited and reparsed if
  the NSE format changes.
- A prior candidate absent from a later export within the declared coverage
  window appears in the delta file as `missing`. Reviewers verify whether NSE
  withdrew the row or the export was incomplete; the canonical action ledger
  remains untouched until a person resolves it.
- Parser heuristics never directly change adjusted prices; human-reviewed
  promotion is a deliberate second step.
- Only rows explicitly marked approved in the review worksheet are promoted;
  unapproved worksheet rows remain candidates. Existing ledgers without
  `record_date` remain readable and acquire a null value until updated.
- Daily retrieval uses the page's currently observed CSV route, which NSE may
  change without notice. Strict CSV and header validation prevents an error
  page or changed format from replacing staged candidates. On failure, the
  operator can use the visible page export and manual staging command.
  Repeated exports are checksum-archived and candidate merging is idempotent;
  new candidates remain separate from approved ledger events.
- Historical coverage and inclusion of all desired actions must be measured
  during Nifty 50 and broader-symbol pilots. Gaps require filing research or a
  later source decision.

## Pilot observation

On 2026-10-13, the public page accepted a custom 2021-10-13 through 2026-10-13
range and displayed historical rows across the selected span. The first export
was archived and staged: 11,838 source rows
became 11,835 unique candidates across 2,358 symbols. Three repeated candidate
groups account for the difference; the per-export review CSV preserves every
source row while the shared candidate Parquet deduplicates by `candidate_id`.
The later review workflow matched the RELIANCE 2024 bonus candidate to the
already-reviewed canonical event, imported its NSE `record_date`, and marked
that candidate approved; it did not add a second action. Other candidates
remain pending review. The custom range is not encoded in the page URL; operators must pass
`--start-date` and `--end-date` to retain this coverage metadata. This pilot
proves the export can be imported for the selected five-year span, not that the
export is complete or that every series is eligible. The Equity view included
`GS` and `IV` alongside `EQ`, so preserve series identity and establish the
included cash-equity series before promoting records into the strategy event
ledger.

On 2026-10-15, NSE's [All Reports page](https://www.nseindia.com/all-reports)
provided `PR141026.zip`; NSE's [2025 Press Files Report circular](https://nsearchives.nseindia.com/content/circulars/CMTR70563.pdf)
documents the daily PR ZIP name and website location. The ZIP's `readme.txt`
identifies `bc14102026.csv` as the corporate-action details file.
That member had 160 rows across 90 symbols, including 9 `EQ` rows, but its
nonblank ex-dates covered only 2026-10-14 through 2026-10-16. Rows repeat
across trading series (for example `EQ`, `BE`, and `BL`). Its fields are
`SERIES`, `SYMBOL`, `SECURITY`, `RECORD_DT`, book-closure dates, `EX_DT`,
no-delivery dates, and abbreviated `PURPOSE`; it has no company filing URL,
announcement date, face value, or dividend pay date. The UI CSV has a longer
history and fuller company name/face-value fields, while still requiring filing
verification for complete terms.

**Validation decision:** do not replace the rolling Corporate Actions CSV
baseline with the PR ZIP. The ZIP sample is a near-term snapshot, not five-year
history, and its abbreviated fields are insufficient to promote adjustment
terms. It may supplement daily discovery if later checks show that it adds
useful coverage. The page CSV remains the rolling historical and daily
snapshot source. The inspected sample is archived at
`data/raw/nse/corporate_action_press_files/2026/10/PR141026.zip` with SHA-256
`6434932493e2084515cfa2a85b44865b51fb0a2e361ca40fc95c1f0bb7c3d134`.

## Alternatives considered

- **Promote summary rows directly to the adjustment ledger:** rejected because
  the export can omit required terms and contains free-text purpose labels.
- **Automate the page's current CSV route:** accepted for this local research
  prototype because it is the route invoked by NSE's visible export control
  and supplies the selected page data as CSV. It is not a documented API
  contract; isolate it, validate responses strictly, and retain manual page
  export as a fallback.
- **Filter collection to the current Nifty 50:** rejected because the ledger
  discovery history should support arbitrary symbols and future universe changes.
