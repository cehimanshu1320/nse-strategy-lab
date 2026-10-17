"""Parquet price store and SQLite ingestion catalog."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from nse_strategy_lab.domain.market_data import PRICE_COLUMNS, PRICE_KEY, PARSER_VERSION
from nse_strategy_lab.domain.corporate_actions import (
    ACTION_COLUMNS,
    ACTION_KEY,
    validate_corporate_actions,
)
from nse_strategy_lab.ingestion.sources.nse.bhavcopy_client import DownloadedReport


class LocalPriceStore:
    def __init__(self, data_dir: Path | str = Path("data")) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "nse" / "cm_bhavcopy"
        self.curated_dir = self.data_dir / "curated" / "daily_prices"
        self.corporate_actions_path = (
            self.data_dir / "curated" / "corporate_actions" / "actions.parquet"
        )
        self.corporate_action_candidates_path = (
            self.data_dir
            / "curated"
            / "corporate_action_candidates"
            / "candidates.parquet"
        )
        self.corporate_action_raw_dir = self.data_dir / "raw" / "nse" / "corporate_actions"
        self.catalog_path = self.data_dir / "catalog.sqlite"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_catalog()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.catalog_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_catalog(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingest_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    requested_start TEXT NOT NULL,
                    requested_end TEXT NOT NULL,
                    status TEXT NOT NULL,
                    files_downloaded INTEGER NOT NULL DEFAULT 0,
                    files_skipped INTEGER NOT NULL DEFAULT 0,
                    rows_written INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT
                );
                CREATE TABLE IF NOT EXISTS source_files (
                    source_file_id TEXT PRIMARY KEY,
                    trade_date TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    parser_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quality_issues (
                    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    trade_date TEXT,
                    source_file_id TEXT,
                    severity TEXT NOT NULL,
                    rule_name TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS corporate_action_imports (
                    source_file_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    rows_staged INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT,
                    coverage_start TEXT,
                    coverage_end TEXT
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(corporate_action_imports)"
                ).fetchall()
            }
            for column in ("coverage_start", "coverage_end"):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE corporate_action_imports ADD COLUMN {column} TEXT"
                    )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start_run(self, start: date, end: date) -> str:
        run_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO ingest_runs (run_id, started_at, requested_start, requested_end, status) "
                "VALUES (?, ?, ?, ?, 'running')",
                (run_id, self._now(), start.isoformat(), end.isoformat()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        files_downloaded: int,
        files_skipped: int,
        rows_written: int,
        error_summary: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE ingest_runs SET completed_at=?, status=?, files_downloaded=?, "
                "files_skipped=?, rows_written=?, error_summary=? WHERE run_id=?",
                (
                    self._now(),
                    status,
                    files_downloaded,
                    files_skipped,
                    rows_written,
                    error_summary,
                    run_id,
                ),
            )

    def save_raw(self, report: DownloadedReport) -> tuple[Path, str, bool]:
        target_dir = self.raw_dir / f"{report.trade_date:%Y}" / f"{report.trade_date:%m}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / report.filename
        if target.exists():
            existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            return target, existing_hash, False

        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(report.content)
        temporary.replace(target)
        checksum = hashlib.sha256(report.content).hexdigest()
        return target, checksum, True

    def record_source(
        self,
        report: DownloadedReport,
        path: Path,
        checksum: str,
        source_format: str,
    ) -> str:
        source_file_id = checksum
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO source_files "
                "(source_file_id, trade_date, source_format, source_url, retrieved_at, "
                "local_path, sha256, size_bytes, parser_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_file_id,
                    report.trade_date.isoformat(),
                    source_format,
                    report.url,
                    self._now(),
                    str(path),
                    checksum,
                    path.stat().st_size,
                    PARSER_VERSION,
                ),
            )
        return source_file_id

    def upsert_prices(self, prices: pd.DataFrame) -> int:
        if prices.empty:
            return 0
        count = 0
        working = prices[PRICE_COLUMNS].copy()
        working["trade_date"] = pd.to_datetime(working["trade_date"])
        working["_year"] = working["trade_date"].dt.year
        working["_month"] = working["trade_date"].dt.month

        for (year, month), incoming in working.groupby(["_year", "_month"]):
            partition_dir = self.curated_dir / f"year={year}" / f"month={month:02d}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            partition_path = partition_dir / "prices.parquet"
            incoming = incoming.drop(columns=["_year", "_month"])
            if partition_path.exists():
                existing = pd.read_parquet(partition_path)
                replace_keys = incoming[PRICE_KEY].drop_duplicates()
                existing = existing.merge(replace_keys.assign(_replace=True), on=PRICE_KEY, how="left")
                existing = existing[existing["_replace"].isna()].drop(columns="_replace")
                combined = pd.concat([existing, incoming], ignore_index=True)
            else:
                combined = incoming
            combined = combined.drop_duplicates(PRICE_KEY, keep="last")
            combined = combined.sort_values(PRICE_KEY).reset_index(drop=True)
            temporary = partition_path.with_suffix(".parquet.part")
            combined.to_parquet(temporary, index=False, engine="pyarrow")
            temporary.replace(partition_path)
            count += len(incoming)
        return count

    def upsert_corporate_actions(self, actions: pd.DataFrame) -> int:
        """Idempotently merge validated event records into the action ledger."""
        normalized = validate_corporate_actions(actions)
        if normalized.empty:
            return 0
        path = self.corporate_actions_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            for column in ACTION_COLUMNS:
                if column not in existing:
                    existing[column] = None
            existing = existing[~existing.set_index(ACTION_KEY).index.isin(
                normalized.set_index(ACTION_KEY).index
            )]
            combined = pd.concat([existing[ACTION_COLUMNS], normalized], ignore_index=True)
        else:
            combined = normalized
        combined = combined.drop_duplicates(ACTION_KEY, keep="last").sort_values(
            ACTION_KEY
        )
        temporary = path.with_suffix(".parquet.part")
        combined.to_parquet(temporary, index=False, engine="pyarrow")
        temporary.replace(path)
        return len(normalized)

    def save_action_export(
        self,
        contents: bytes,
        *,
        filename: str,
        source_url: str,
        coverage_start: date | None = None,
        coverage_end: date | None = None,
    ) -> tuple[Path, str, str]:
        """Archive an exact NSE action export and register its provenance."""
        checksum = hashlib.sha256(contents).hexdigest()
        source_file_id = checksum
        retrieved_at = self._now()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "actions.csv"
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT local_path FROM corporate_action_imports WHERE source_file_id=?",
                (source_file_id,),
            ).fetchone()
        if existing and Path(existing["local_path"]).exists():
            target = Path(existing["local_path"])
        else:
            target_dir = self.corporate_action_raw_dir / checksum[:2]
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{checksum}_{safe_name}"
            if not target.exists():
                temporary = target.with_suffix(target.suffix + ".part")
                temporary.write_bytes(contents)
                temporary.replace(target)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO corporate_action_imports "
                "(source_file_id, source_url, retrieved_at, local_path, sha256, "
                "size_bytes, status, coverage_start, coverage_end) "
                "VALUES (?, ?, ?, ?, ?, ?, 'received', ?, ?)",
                (
                    source_file_id,
                    source_url,
                    retrieved_at,
                    str(target),
                    checksum,
                    len(contents),
                    coverage_start.isoformat() if coverage_start else None,
                    coverage_end.isoformat() if coverage_end else None,
                ),
            )
            if existing and not Path(existing["local_path"]).exists():
                connection.execute(
                    "UPDATE corporate_action_imports SET local_path=? "
                    "WHERE source_file_id=?",
                    (str(target), source_file_id),
                )
        return target, source_file_id, retrieved_at

    def finish_action_export(
        self,
        source_file_id: str,
        *,
        status: str,
        rows_staged: int = 0,
        error_summary: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE corporate_action_imports SET status=?, rows_staged=?, "
                "error_summary=? WHERE source_file_id=?",
                (status, rows_staged, error_summary, source_file_id),
            )

    def merge_action_candidates(
        self,
        candidates: pd.DataFrame,
        *,
        coverage_start: date | None = None,
        coverage_end: date | None = None,
    ) -> dict[str, object]:
        """Merge candidates and report additions, edits, and covered-snapshot gaps."""
        if candidates.empty:
            return {
                "rows_staged": 0, "new": 0, "changed": 0,
                "unchanged": 0, "missing": 0,
            }
        unique_candidates = candidates.drop_duplicates("candidate_id", keep="last")
        path = self.corporate_action_candidates_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            for column in unique_candidates.columns:
                if column not in existing:
                    existing[column] = None
        else:
            existing = pd.DataFrame(columns=unique_candidates.columns)

        comparison_columns = [
            "symbol", "company_name", "series", "purpose", "face_value", "ex_date",
            "record_date", "book_closure_start_date", "book_closure_end_date",
            "event_type_guess", "share_factor_guess", "cash_per_share_guess",
        ]

        def comparable(value: object) -> str:
            if pd.isna(value):
                return ""
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value).strip()

        existing_by_id = existing.drop_duplicates("candidate_id", keep="last").set_index(
            "candidate_id", drop=False
        ) if not existing.empty else pd.DataFrame()
        statuses: dict[str, str] = {}
        merged_incoming = []
        for _, row in unique_candidates.iterrows():
            candidate_id = row["candidate_id"]
            if existing_by_id.empty or candidate_id not in existing_by_id.index:
                discovery_status = "new"
                prior = None
            else:
                prior = existing_by_id.loc[candidate_id]
                if isinstance(prior, pd.DataFrame):
                    prior = prior.iloc[-1]
                changed = any(
                    comparable(row.get(column)) != comparable(prior.get(column))
                    for column in comparison_columns
                )
                was_missing = prior.get("discovery_status") == "missing"
                discovery_status = "changed" if changed or was_missing else "unchanged"

            current = row.to_dict()
            current["discovery_status"] = discovery_status
            if prior is not None and discovery_status == "unchanged":
                current["review_status"] = prior.get("review_status", "needs_review")
                current["review_notes"] = prior.get("review_notes", "")
            elif discovery_status == "changed":
                current["review_status"] = "needs_review"
                current["review_notes"] = (
                    (
                        "Source row reappeared after a missing snapshot; verify the event again. "
                        if prior is not None and prior.get("discovery_status") == "missing"
                        else "Source row changed since prior export; verify the event again. "
                    )
                    + str(row.get("review_notes") or "")
                ).strip()
            statuses[str(candidate_id)] = discovery_status
            merged_incoming.append(current)

        merged_incoming = pd.DataFrame(merged_incoming)
        incoming_ids = set(merged_incoming["candidate_id"])
        missing_rows = pd.DataFrame(columns=existing.columns)
        if coverage_start is not None and coverage_end is not None and not existing.empty:
            if coverage_start > coverage_end:
                raise ValueError("coverage_start cannot be later than coverage_end.")
            existing_dates = pd.to_datetime(existing["ex_date"], errors="coerce").dt.date
            missing_mask = (
                ~existing["candidate_id"].isin(incoming_ids)
                & existing_dates.ge(coverage_start)
                & existing_dates.le(coverage_end)
            )
            if "discovery_status" in existing:
                missing_mask &= existing["discovery_status"].ne("missing")
            missing_rows = existing.loc[missing_mask].copy()
            if not missing_rows.empty:
                missing_rows["discovery_status"] = "missing"
                missing_rows["review_status"] = "needs_review"
                missing_rows["missing_source_file_id"] = str(candidates["source_file_id"].iloc[0])
                notes = missing_rows.get(
                    "review_notes", pd.Series("", index=missing_rows.index)
                ).fillna("").astype(str)
                missing_rows["review_notes"] = notes.map(
                    lambda note: (
                        note + " " if note else ""
                    ) + "Absent from a later export covering this ex-date; verify whether "
                    "the source row was withdrawn or the export was incomplete."
                )
                existing.loc[missing_mask, "discovery_status"] = "missing"
                existing.loc[missing_mask, "review_status"] = "needs_review"
                existing.loc[missing_mask, "missing_source_file_id"] = str(
                    candidates["source_file_id"].iloc[0]
                )
                existing.loc[missing_mask, "review_notes"] = missing_rows["review_notes"]
        existing = existing[~existing["candidate_id"].isin(incoming_ids)]
        combined = pd.concat([existing, merged_incoming], ignore_index=True)
        combined = combined.drop_duplicates("candidate_id", keep="last").sort_values(
            ["ex_date", "symbol", "purpose"], na_position="last"
        )
        temporary = path.with_suffix(".parquet.part")
        combined.to_parquet(temporary, index=False, engine="pyarrow")
        temporary.replace(path)
        source_file_id = str(candidates["source_file_id"].iloc[0])
        review_path = path.parent / f"review_{source_file_id[:16]}.csv"
        changes_path = path.parent / f"changes_{source_file_id[:16]}.csv"
        source_review = candidates.copy()
        source_review["discovery_status"] = source_review["candidate_id"].map(statuses)
        source_review.to_csv(review_path, index=False)
        change_rows = pd.concat(
            [
                merged_incoming[merged_incoming["discovery_status"].isin(["new", "changed"])],
                missing_rows,
            ],
            ignore_index=True,
            sort=False,
        )
        change_rows.to_csv(changes_path, index=False)
        return {
            "rows_staged": len(unique_candidates),
            "new": sum(value == "new" for value in statuses.values()),
            "changed": sum(value == "changed" for value in statuses.values()),
            "unchanged": sum(value == "unchanged" for value in statuses.values()),
            "missing": len(missing_rows),
            "review_path": review_path,
            "changes_path": changes_path,
        }

    def upsert_action_candidates(self, candidates: pd.DataFrame) -> int:
        """Compatibility wrapper for code that only needs the staged row count."""
        return int(self.merge_action_candidates(candidates)["rows_staged"])

    def create_action_review_template(
        self,
        output_path: Path | str,
        *,
        symbols: set[str] | None = None,
        action_types: set[str] | None = None,
        include_existing: bool = False,
    ) -> Path:
        """Create a human-verification worksheet; guesses are kept as hints only."""
        if not self.corporate_action_candidates_path.exists():
            raise FileNotFoundError("No staged corporate-action candidates were found.")
        candidates = pd.read_parquet(self.corporate_action_candidates_path)
        allowed_types = action_types or {"bonus", "split", "dividend"}
        mask = candidates["series"].eq("EQ") & candidates["event_type_guess"].isin(allowed_types)
        mask &= candidates["review_status"].eq("needs_review")
        if not include_existing and not symbols and "discovery_status" in candidates:
            mask &= candidates["discovery_status"].isin(["new", "changed", "missing"])
        if symbols:
            mask &= candidates["symbol"].isin({symbol.upper() for symbol in symbols})
        selected = candidates[mask].drop_duplicates("candidate_id").copy()
        template = pd.DataFrame(
            {
                "candidate_id": selected["candidate_id"],
                "symbol": selected["symbol"],
                "series": selected["series"],
                "purpose": selected["purpose"],
                "ex_date": selected["ex_date"],
                "record_date": selected["record_date"],
                "suggested_action_type": selected["event_type_guess"],
                "suggested_share_factor": selected["share_factor_guess"],
                "suggested_cash_per_share": selected["cash_per_share_guess"],
                "action_type": "",
                "announcement_date": "",
                "share_factor": "",
                "cash_per_share": "",
                "pay_date": "",
                "terms": selected["purpose"],
                "source_url": "",
                "source_file_id": selected["source_file_id"],
                "review_status": "needs_review",
                "review_notes": selected["review_notes"],
            }
        )
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        template.to_csv(target, index=False)
        return target

    def update_action_candidate_reviews(self, reviews: pd.DataFrame) -> int:
        """Persist approval/rejection states from a reviewed worksheet."""
        if reviews.empty or not self.corporate_action_candidates_path.exists():
            return 0
        if not {"candidate_id", "review_status"}.issubset(reviews.columns):
            raise ValueError("Review worksheet requires candidate_id and review_status columns.")
        invalid_statuses = set(reviews["review_status"].dropna().astype(str).str.lower()) - {
            "needs_review", "approved", "rejected"
        }
        if invalid_statuses:
            raise ValueError(f"Unsupported review statuses: {sorted(invalid_statuses)}")
        candidates = pd.read_parquet(self.corporate_action_candidates_path)
        update = reviews.dropna(subset=["candidate_id"]).drop_duplicates("candidate_id", keep="last")
        update["review_status"] = update["review_status"].astype(str).str.lower()
        status_map = update.set_index("candidate_id")["review_status"].to_dict()
        candidates["review_status"] = candidates.apply(
            lambda row: status_map.get(row["candidate_id"], row["review_status"]), axis=1
        )
        if "review_notes" in update:
            notes_map = update.set_index("candidate_id")["review_notes"].to_dict()
            candidates["review_notes"] = candidates.apply(
                lambda row: notes_map.get(row["candidate_id"], row["review_notes"]), axis=1
            )
        temporary = self.corporate_action_candidates_path.with_suffix(".parquet.part")
        candidates.to_parquet(temporary, index=False, engine="pyarrow")
        temporary.replace(self.corporate_action_candidates_path)
        return len(update)

    def load_corporate_actions(self, symbol: str | None = None) -> pd.DataFrame:
        if not self.corporate_actions_path.exists():
            return pd.DataFrame(columns=ACTION_COLUMNS)
        actions = pd.read_parquet(self.corporate_actions_path)
        for column in ACTION_COLUMNS:
            if column not in actions:
                actions[column] = None
        actions = actions[ACTION_COLUMNS]
        if symbol:
            actions = actions[actions["symbol"] == symbol.upper()]
        return actions.sort_values(ACTION_KEY).reset_index(drop=True)

    def load_prices(
        self,
        *,
        symbol: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        paths = [str(path) for path in self.curated_dir.glob("year=*/month=*/prices.parquet")]
        if not paths:
            return pd.DataFrame(columns=PRICE_COLUMNS)

        clauses: list[str] = []
        parameters: list[object] = [paths]
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol.upper())
        if start:
            clauses.append("trade_date >= ?")
            parameters.append(start)
        if end:
            clauses.append("trade_date <= ?")
            parameters.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # Calculate point-in-time extrema across full stored history before
        # applying the requested display range. Calendar-time RANGE means
        # weekends and exchange holidays do not shorten the 52-week window.
        query = (
            "WITH history AS ("
            " SELECT trade_date, symbol, series, open, high, low, close, volume, "
            "        turnover, trade_count, source_file_id, "
            "        MAX(high) OVER (PARTITION BY symbol, series ORDER BY trade_date "
            "          RANGE BETWEEN INTERVAL 364 DAYS PRECEDING AND CURRENT ROW) AS high_52w, "
            "        MIN(low) OVER (PARTITION BY symbol, series ORDER BY trade_date "
            "          RANGE BETWEEN INTERVAL 364 DAYS PRECEDING AND CURRENT ROW) AS low_52w "
            " FROM read_parquet(?)"
            ") SELECT * FROM history"
            f"{where} ORDER BY trade_date, symbol"
        )
        with duckdb.connect(database=":memory:") as connection:
            return connection.execute(query, parameters).df()

    def list_symbols(self) -> list[str]:
        paths = [str(path) for path in self.curated_dir.glob("year=*/month=*/prices.parquet")]
        if not paths:
            return []
        with duckdb.connect(database=":memory:") as connection:
            rows = connection.execute(
                "SELECT DISTINCT symbol FROM read_parquet(?) ORDER BY symbol", [paths]
            ).fetchall()
        return [row[0] for row in rows]

    def latest_trade_date(self) -> date | None:
        paths = [str(path) for path in self.curated_dir.glob("year=*/month=*/prices.parquet")]
        if not paths:
            return None
        with duckdb.connect(database=":memory:") as connection:
            value = connection.execute(
                "SELECT MAX(trade_date) FROM read_parquet(?)", [paths]
            ).fetchone()[0]
        if isinstance(value, datetime):
            return value.date()
        return value

    def import_status(self) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT started_at, completed_at, requested_start, requested_end, status, "
                "files_downloaded, files_skipped, rows_written, error_summary "
                "FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
