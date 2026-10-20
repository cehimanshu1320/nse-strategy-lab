"""Immutable raw archive and local stores for NSE market-cap observations."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


MARKET_CAP_COLUMNS = [
    "observation_type",
    "as_of_date",
    "period_start",
    "period_end",
    "symbol",
    "isin",
    "market_cap_inr_crore",
    "source_url",
    "source_file_id",
    "retrieved_at",
]


class LocalMarketCapStore:
    """Persist dated observations separately from daily price data."""

    def __init__(self, data_dir: Path | str = Path("data")) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "nse" / "market_cap"
        self.observations_path = (
            self.data_dir / "curated" / "market_cap_observations" / "observations.parquet"
        )
        self.catalog_path = self.data_dir / "catalog.sqlite"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.catalog_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS market_cap_imports (
                    source_file_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    observation_type TEXT NOT NULL,
                    period_start TEXT,
                    period_end TEXT,
                    rows_imported INTEGER NOT NULL,
                    status TEXT NOT NULL
                )"""
            )

    def archive_source(self, content: bytes, filename: str) -> tuple[Path, str, str]:
        checksum = hashlib.sha256(content).hexdigest()
        retrieved_at = datetime.now(timezone.utc).isoformat()
        target_dir = self.raw_dir / datetime.now(timezone.utc).strftime("%Y/%m")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            target = target_dir / f"{target.stem}_{checksum[:12]}{target.suffix}"
        if not target.exists():
            target.write_bytes(content)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Refusing to overwrite different raw NSE file: {target}")
        return target, checksum, retrieved_at

    def save_observations(self, observations: pd.DataFrame) -> int:
        missing = set(MARKET_CAP_COLUMNS).difference(observations.columns)
        if missing:
            raise ValueError("Market-cap observations missing fields: " + ", ".join(sorted(missing)))
        self.observations_path.parent.mkdir(parents=True, exist_ok=True)
        current = self.load_observations()
        combined = pd.concat([current, observations[MARKET_CAP_COLUMNS]], ignore_index=True)
        natural_key = ["observation_type", "as_of_date", "period_start", "period_end", "symbol"]
        combined = combined.sort_values("retrieved_at").drop_duplicates(natural_key, keep="last")
        combined.to_parquet(self.observations_path, index=False)
        return len(observations)

    def record_import(
        self,
        *,
        source_file_id: str,
        source_url: str,
        retrieved_at: str,
        local_path: Path,
        rows_imported: int,
        observation_type: str,
        period_start: str | None,
        period_end: str | None,
    ) -> None:
        with sqlite3.connect(self.catalog_path) as connection:
            connection.execute(
                """INSERT INTO market_cap_imports
                (source_file_id,source_url,retrieved_at,local_path,sha256,size_bytes,
                 observation_type,period_start,period_end,rows_imported,status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_file_id) DO UPDATE SET
                  rows_imported=excluded.rows_imported,status=excluded.status""",
                (
                    source_file_id,
                    source_url,
                    retrieved_at,
                    str(local_path),
                    source_file_id,
                    local_path.stat().st_size,
                    observation_type,
                    period_start,
                    period_end,
                    rows_imported,
                    "completed",
                ),
            )

    def load_observations(self) -> pd.DataFrame:
        if not self.observations_path.exists():
            return pd.DataFrame(columns=MARKET_CAP_COLUMNS)
        observations = pd.read_parquet(self.observations_path)
        missing = set(MARKET_CAP_COLUMNS).difference(observations.columns)
        if missing:
            raise ValueError("Stored market-cap observations missing fields: " + ", ".join(sorted(missing)))
        return observations[MARKET_CAP_COLUMNS].copy()
