"""Infrastructure orchestration for the local app-start scheduler."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from nse_strategy_lab.config.schedules import ScheduleDefinition
from nse_strategy_lab.scheduling.repository import SchedulerRepository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LocalScheduler:
    """Persistent weekday scheduler backed by the local SQLite catalog."""

    def __init__(
        self,
        repository: SchedulerRepository,
        *,
        schedules: dict[str, ScheduleDefinition],
        handlers: dict[str, Callable[[], object]],
        poll_seconds: float = 20.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.repository = repository
        self.schedule_definitions = schedules
        self.handlers = handlers
        missing_handlers = set(schedules) - set(handlers)
        if missing_handlers:
            raise ValueError(
                f"Scheduled jobs have no application handler: {sorted(missing_handlers)}"
            )
        self.poll_seconds = poll_seconds
        self.clock = clock
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._start_lock = threading.Lock()
        self.worker_id = f"{uuid.uuid4()}:{threading.get_ident()}"

    def initialize_schedules(self) -> None:
        now = self.clock()
        for job_id, definition in self.schedule_definitions.items():
            self.repository.ensure_schedule(
                job_id=job_id,
                name=definition.name,
                description=definition.description,
                run_hour=definition.hour,
                run_minute=definition.minute,
                timezone_name=definition.timezone,
                cadence=definition.cadence,
                catch_up_policy=definition.catch_up_policy,
                now=now,
            )

    def start(self) -> None:
        self.initialize_schedules()
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="nse-local-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the runner, primarily for orderly shutdown and test cleanup."""
        self._stop.set()
        self.wake()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    def enqueue_manual(self, job_id: str) -> str:
        if job_id not in self.handlers:
            raise KeyError(f"No handler is registered for job {job_id!r}.")
        occurrence_id = self.repository.enqueue_manual(job_id, self.clock())
        self.wake()
        return occurrence_id

    def enqueue_due(self) -> int:
        count = self.repository.enqueue_due(self.clock())
        self.wake()
        return count

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.repository.enqueue_due(self.clock())
                self._run_pending()
            except Exception:
                # The runner stays alive if a transient catalog problem occurs.
                logger.exception("Local scheduler iteration failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def _run_pending(self) -> None:
        while True:
            lease = timedelta(minutes=5)
            occurrence = self.repository.claim_next(self.worker_id, self.clock(), lease)
            if occurrence is None:
                return
            occurrence_id = str(occurrence["occurrence_id"])
            job_id = str(occurrence["job_id"])
            heartbeat_stop = threading.Event()

            def renew_lease() -> None:
                while not heartbeat_stop.wait(60):
                    try:
                        renewed = self.repository.renew_lease(
                            occurrence_id,
                            self.worker_id,
                            now=self.clock(),
                            lease=lease,
                        )
                    except Exception:
                        logger.exception("Could not renew scheduler lease for %s", occurrence_id)
                        continue
                    if not renewed:
                        logger.error("Scheduler lease was lost for %s", occurrence_id)
                        return

            heartbeat = threading.Thread(
                target=renew_lease,
                name=f"nse-scheduler-lease-{occurrence_id[:8]}",
                daemon=True,
            )
            heartbeat.start()
            try:
                handler = self.handlers.get(job_id)
                if handler is None:
                    raise KeyError(f"No handler is registered for job {job_id!r}.")
                result = handler()
                summary = json.dumps(result, default=str, sort_keys=True)
                heartbeat_stop.set()
                heartbeat.join()
                finished = self.repository.finish(
                    occurrence_id,
                    now=self.clock(),
                    worker_id=self.worker_id,
                    result_summary=summary,
                )
                if not finished:
                    logger.error("Could not finish scheduler occurrence %s: claim was lost", occurrence_id)
            except Exception as exc:
                heartbeat_stop.set()
                heartbeat.join()
                finished = self.repository.finish(
                    occurrence_id,
                    now=self.clock(),
                    worker_id=self.worker_id,
                    error_summary=f"{type(exc).__name__}: {exc}",
                )
                if not finished:
                    logger.error("Could not record failure for %s: claim was lost", occurrence_id)

    def schedules(self) -> list[dict[str, object]]:
        return self.repository.list_schedules()

    def occurrences(self, limit: int = 50) -> list[dict[str, object]]:
        return self.repository.recent_occurrences(limit)

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        if job_id not in self.schedule_definitions:
            raise KeyError(f"Unknown scheduled job: {job_id}")
        self.repository.set_enabled(job_id, enabled)
        if enabled:
            self.enqueue_due()

    def retry(self, occurrence_id: str) -> bool:
        changed = self.repository.retry(occurrence_id, self.clock())
        if changed:
            self.wake()
        return changed
