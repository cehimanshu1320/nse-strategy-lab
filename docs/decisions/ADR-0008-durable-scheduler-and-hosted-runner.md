# ADR-0008: Keep scheduled jobs independent from their runner

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

The app needs corporate-action and price-data refresh jobs, a visible schedule
history, missed-run recovery, and manual controls. The current macOS LaunchAgent
cannot read the checkout under the protected `Documents` directory. Streamlit
also reruns page scripts and may run on hosts that sleep, restart, or use more
than one app instance, so page rendering cannot be the durable source of job
execution or run state.

## Decision

- Define each scheduled job as a framework-independent application service with
  a stable job ID, cadence, and explicit catch-up policy. Keep network, parsing,
  and ingestion code outside Streamlit page scripts.
- Keep operational cadence and timezone in `configs/schedules.toml`; register
  stable job IDs to application handlers in the app composition root. The
  scheduler runner accepts handlers by injection and has no dependency on the
  import workflows. Editing schedule configuration and restarting the app
  updates the persisted schedule while preserving its enabled state.
- For the current single-user local app, persist schedules, due occurrences,
  run history, and errors in the local SQLite catalog. On app process startup,
  a guarded local runner checks due work; it executes in the background so page
  rendering remains responsive. The Schedulers view reads persisted status and
  can enqueue an individual job or all due jobs for immediate execution.
- Use a database-backed claim/lease and unique occurrence key so Streamlit
  reruns, multiple sessions, and retries cannot start the same occurrence
  concurrently. Record success or failure and allow failed runs to be retried.
- Give each job a documented catch-up policy. Corporate-action discovery
  coalesces missed daily occurrences into one current rolling-export refresh;
  price ingestion catches up missing trading sessions through the existing
  idempotent importer. A manual run uses the same job service as a scheduled
  run.
- The local defaults are weekdays at 18:30 Asia/Kolkata for corporate actions
  and 18:40 for daily prices. When price storage is empty, scheduled refresh
  imports only the latest 14 calendar days; the five-year initial backfill
  remains an explicit user action. Schedule rows are seeded once and are not
  overwritten on app startup, so enabled state and future edits persist.
- App-start catch-up only runs after the app process starts. When hosted, keep
  the job definitions and application services, but use a dedicated worker or
  managed scheduler to run independently of Streamlit web-instance lifetime.
  Move coordination state to a durable shared database such as PostgreSQL
  before using multiple workers or app instances; retain a unique run key and
  atomic lease/claim semantics.
- Treat the Streamlit scheduler view as a control and status surface. It does
  not own schedule state or execute work during page rendering.

## Consequences

- The local app can recover due work when opened without requiring macOS
  `launchd` access to the repository. Jobs do not run while the app is closed.
- The same job functions can be invoked by a local startup runner, a manual UI
  action, a command-line interface, or a future hosted worker.
- The schedule/run repository needs a storage boundary so SQLite can serve the
  local prototype and a shared database can serve hosted multi-instance use.
- Catch-up means different things for different data sources. Coalescing a
  corporate-action refresh gets the latest rolling snapshot but cannot recreate
  exports that appeared and disappeared while the app was closed.
- A hosted Streamlit web process alone is not a reliable scheduler. Deploy a
  worker/managed scheduler and durable storage when hosted operation begins.

## Alternatives considered

- **Run downloads directly from page rendering:** rejected because Streamlit
  reruns pages and page access should remain responsive and side-effect free.
- **Use macOS LaunchAgent as the only local scheduler:** rejected because the
  current protected-folder access failure prevents it from reading the project
  script; it also couples scheduling to the local OS.
- **Keep scheduling embedded in Streamlit permanently:** rejected because
  hosted web instances can restart, sleep, or multiply, and may not share local
  files.
