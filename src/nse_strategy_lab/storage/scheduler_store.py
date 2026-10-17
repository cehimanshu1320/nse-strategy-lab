"""SQLite persistence for local job schedules and execution history."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nse_strategy_lab.scheduling.calendar import next_weekday_occurrence


UTC = timezone.utc


class SchedulerStore:
    """Small repository for scheduler state in the existing local catalog."""

    def __init__(self, data_dir: Path | str = Path("data")) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "catalog.sqlite"
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_schedules (
                    job_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    cadence TEXT NOT NULL,
                    run_hour INTEGER NOT NULL,
                    run_minute INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    catch_up_policy TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    occurrence_key TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    lease_until TEXT,
                    worker_id TEXT,
                    result_summary TEXT,
                    error_summary TEXT,
                    FOREIGN KEY(job_id) REFERENCES job_schedules(job_id)
                );
                CREATE INDEX IF NOT EXISTS idx_job_occurrences_queue
                    ON job_occurrences(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_job_occurrences_job_time
                    ON job_occurrences(job_id, scheduled_for DESC);
                """
            )

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat(timespec="seconds")

    def ensure_schedule(
        self,
        *,
        job_id: str,
        name: str,
        description: str,
        run_hour: int,
        run_minute: int,
        timezone_name: str,
        cadence: str,
        catch_up_policy: str,
        now: datetime,
    ) -> None:
        if cadence != "weekdays":
            raise ValueError(f"Unsupported schedule cadence: {cadence}")
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone)
        scheduled_today = local_now.replace(
            hour=run_hour, minute=run_minute, second=0, microsecond=0
        )
        stamp = self._iso(local_now)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM job_schedules WHERE job_id=?", (job_id,)
            ).fetchone()
            if existing is None:
                if local_now.weekday() < 5:
                    initial_due = scheduled_today
                else:
                    initial_due = next_weekday_occurrence(
                        local_now,
                        timezone=timezone_name,
                        hour=run_hour,
                        minute=run_minute,
                    )
                connection.execute(
                    """INSERT INTO job_schedules
                       (job_id, name, description, timezone, cadence, run_hour,
                        run_minute, enabled, catch_up_policy, next_run_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        job_id, name, description, timezone_name, cadence,
                        run_hour, run_minute, catch_up_policy,
                        self._iso(initial_due), stamp, stamp,
                    ),
                )
                return

            schedule_changed = any(
                existing[column] != value
                for column, value in (
                    ("timezone", timezone_name),
                    ("cadence", cadence),
                    ("run_hour", run_hour),
                    ("run_minute", run_minute),
                    ("catch_up_policy", catch_up_policy),
                )
            )
            metadata_changed = (
                existing["name"] != name or existing["description"] != description
            )
            if schedule_changed or metadata_changed:
                next_due = next_weekday_occurrence(
                    local_now,
                    timezone=timezone_name,
                    hour=run_hour,
                    minute=run_minute,
                ) if schedule_changed else datetime.fromisoformat(existing["next_run_at"])
                connection.execute(
                    """UPDATE job_schedules SET name=?, description=?, timezone=?,
                       cadence=?, run_hour=?, run_minute=?, catch_up_policy=?,
                       next_run_at=?, updated_at=? WHERE job_id=?""",
                    (
                        name, description, timezone_name, cadence, run_hour,
                        run_minute, catch_up_policy, self._iso(next_due), stamp, job_id,
                    ),
                )

    def list_schedules(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_schedules ORDER BY run_hour, run_minute, job_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE job_schedules SET enabled=?, updated_at=? WHERE job_id=?",
                (int(enabled), self._iso(datetime.now(UTC)), job_id),
            )

    def enqueue_due(self, now: datetime) -> int:
        now = now.astimezone(UTC)
        added = 0
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM job_schedules WHERE enabled=1"
            ).fetchall()
            for schedule in rows:
                due = datetime.fromisoformat(schedule["next_run_at"]).astimezone(UTC)
                if due > now:
                    continue
                # Coalesce missed weekdays into one current run per job.
                scheduled_for = due
                while True:
                    following = next_weekday_occurrence(
                        scheduled_for,
                        timezone=schedule["timezone"],
                        hour=int(schedule["run_hour"]),
                        minute=int(schedule["run_minute"]),
                    )
                    if following > now:
                        break
                    scheduled_for = following
                occurrence_key = f"scheduled:{schedule['job_id']}:{self._iso(scheduled_for)}"
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO job_occurrences
                       (occurrence_id, occurrence_key, job_id, scheduled_for,
                        trigger_type, status, created_at)
                       VALUES (?, ?, ?, ?, 'scheduled', 'pending', ?)""",
                    (str(uuid.uuid4()), occurrence_key, schedule["job_id"],
                     self._iso(scheduled_for), self._iso(now)),
                )
                added += cursor.rowcount
                next_run = next_weekday_occurrence(
                    now,
                    timezone=schedule["timezone"],
                    hour=int(schedule["run_hour"]),
                    minute=int(schedule["run_minute"]),
                )
                connection.execute(
                    "UPDATE job_schedules SET next_run_at=?, updated_at=? WHERE job_id=?",
                    (self._iso(next_run), self._iso(now), schedule["job_id"]),
                )
        return added

    def enqueue_manual(self, job_id: str, now: datetime) -> str:
        occurrence_id = str(uuid.uuid4())
        stamp = self._iso(now)
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM job_schedules WHERE job_id=?", (job_id,)
            ).fetchone()
            if not exists:
                raise KeyError(f"Unknown scheduled job: {job_id}")
            connection.execute(
                """INSERT INTO job_occurrences
                   (occurrence_id, occurrence_key, job_id, scheduled_for,
                    trigger_type, status, created_at)
                   VALUES (?, ?, ?, ?, 'manual', 'pending', ?)""",
                (occurrence_id, f"manual:{job_id}:{occurrence_id}", job_id, stamp, stamp),
            )
        return occurrence_id

    def claim_next(self, worker_id: str, now: datetime, lease: timedelta) -> dict[str, object] | None:
        now_stamp = self._iso(now)
        lease_until = self._iso(now + lease)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT occurrence_id, lease_until FROM job_occurrences WHERE status='running'"
            ).fetchall()
            expired = [
                row["occurrence_id"]
                for row in active
                if row["lease_until"]
                and datetime.fromisoformat(row["lease_until"]).astimezone(UTC)
                <= now.astimezone(UTC)
            ]
            for occurrence_id in expired:
                connection.execute(
                    """UPDATE job_occurrences SET status='pending', worker_id=NULL,
                       lease_until=NULL, started_at=NULL WHERE occurrence_id=?""",
                    (occurrence_id,),
                )
            row = connection.execute(
                """SELECT o.* FROM job_occurrences o
                   WHERE o.status='pending'
                     AND NOT EXISTS (
                       SELECT 1 FROM job_occurrences active
                       WHERE active.job_id=o.job_id AND active.status='running'
                     )
                   ORDER BY o.created_at, o.occurrence_id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                """UPDATE job_occurrences SET status='running', started_at=?,
                   worker_id=?, lease_until=? WHERE occurrence_id=? AND status='pending'""",
                (now_stamp, worker_id, lease_until, row["occurrence_id"]),
            )
            if updated.rowcount != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM job_occurrences WHERE occurrence_id=?",
                (row["occurrence_id"],),
            ).fetchone()
            return dict(claimed)

    def renew_lease(
        self,
        occurrence_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease: timedelta,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE job_occurrences SET lease_until=?
                   WHERE occurrence_id=? AND worker_id=? AND status='running'""",
                (self._iso(now + lease), occurrence_id, worker_id),
            )
        return cursor.rowcount == 1

    def finish(
        self,
        occurrence_id: str,
        *,
        now: datetime,
        worker_id: str,
        result_summary: str | None = None,
        error_summary: str | None = None,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE job_occurrences SET status=?, completed_at=?, lease_until=NULL,
                   result_summary=?, error_summary=?
                   WHERE occurrence_id=? AND worker_id=? AND status='running'""",
                ("failed" if error_summary else "succeeded", self._iso(now),
                 result_summary, error_summary, occurrence_id, worker_id),
            )
        return cursor.rowcount == 1

    def retry(self, occurrence_id: str, now: datetime) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE job_occurrences SET status='pending', created_at=?, started_at=NULL,
                   completed_at=NULL, lease_until=NULL, worker_id=NULL, error_summary=NULL,
                   result_summary=NULL WHERE occurrence_id=? AND status='failed'""",
                (self._iso(now), occurrence_id),
            )
        return cursor.rowcount == 1

    def recent_occurrences(self, limit: int = 50) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT o.*, s.name AS job_name FROM job_occurrences o
                   JOIN job_schedules s USING(job_id)
                   ORDER BY o.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
