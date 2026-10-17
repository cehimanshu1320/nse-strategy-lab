# ADR-0002: Local data storage and source strategy

- Status: accepted (local storage architecture)
- Date: 2026-10-13
- Owners: project

## Context

The app is single-user and daily-frequency, and the initial goal is to keep
operating costs low while retaining enough provenance to reproduce research.
NSE exposes a five-year per-security history view and daily bhavcopy reports.
The project owner selected NSE bhavcopy archives for the prototype, as recorded
in ADR-0004. This ADR addresses storage architecture independently of that
source choice.

## Decision

Use the following local architecture for files obtained through the prototype
workflow:

- Preserve original files as immutable raw inputs with checksums.
- Store normalized price/event data as Parquet, partitioned by date range.
- Store small import manifests and quality findings in SQLite.
- Query Parquet through DuckDB.
- Run the importer separately from the Streamlit process.

The source adapter and local storage are separate boundaries. If the source
changes after prototype testing, the same canonical storage and query layer can
be retained.

## Consequences

- The proposed local storage design avoids hosted database or compute costs;
  it does not guarantee that the required market data itself is free.
- Source-format changes are isolated to adapters/parsers.
- Market data is not committed to Git.
- Hosting later requires durable object storage and a separate scheduled job;
  Streamlit's local filesystem is not the source of truth.
- This ADR does not grant data rights or select a future automated source.

## Alternatives considered

- Supabase/Postgres was deferred until cloud access, multiple users, or
  concurrent metadata writes are needed.
- A single DuckDB database file for all canonical data was considered; Parquet
  plus DuckDB query layer keeps the data portable and avoids coupling the
  archive to one database file.
