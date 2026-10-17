"""Persistence port required by the scheduler runner."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

class SchedulerRepository(Protocol):
    """Contract for durable schedule and occurrence state."""

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
    ) -> None: ...

    def list_schedules(self) -> list[dict[str, object]]: ...

    def set_enabled(self, job_id: str, enabled: bool) -> None: ...

    def enqueue_due(self, now: datetime) -> int: ...

    def enqueue_manual(self, job_id: str, now: datetime) -> str: ...

    def claim_next(self, worker_id: str, now: datetime, lease: timedelta) -> dict[str, object] | None: ...

    def renew_lease(
        self, occurrence_id: str, worker_id: str, *, now: datetime, lease: timedelta
    ) -> bool: ...

    def finish(
        self,
        occurrence_id: str,
        *,
        now: datetime,
        worker_id: str,
        result_summary: str | None = None,
        error_summary: str | None = None,
    ) -> bool: ...

    def retry(self, occurrence_id: str, now: datetime) -> bool: ...

    def recent_occurrences(self, limit: int = 50) -> list[dict[str, object]]: ...
