from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import time

from nse_strategy_lab.config.schedules import (
    ScheduleDefinition,
    load_schedule_definitions,
)
from nse_strategy_lab.ingestion.jobs import bhavcopy_import
from nse_strategy_lab.ingestion.sources.nse.bhavcopy_client import DownloadedReport
from nse_strategy_lab.services import refresh as refresh_service
from nse_strategy_lab.services.scheduler import LocalScheduler
from nse_strategy_lab.scheduling.calendar import next_weekday_occurrence
from nse_strategy_lab.storage.scheduler_store import SchedulerStore
from streamlit.testing.v1 import AppTest


UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


def schedule_config(
    *,
    job_id: str = "sample",
    hour: int = 18,
    minute: int = 30,
) -> ScheduleDefinition:
    return ScheduleDefinition(
        job_id=job_id,
        name="Sample job",
        description="For scheduler tests",
        timezone="Asia/Kolkata",
        cadence="weekdays",
        hour=hour,
        minute=minute,
        catch_up_policy="coalesce",
    )


def test_project_schedule_config_is_operational_and_valid() -> None:
    schedules = load_schedule_definitions(Path("configs/schedules.toml"))

    assert schedules["corporate_action_refresh"].hour == 18
    assert schedules["corporate_action_refresh"].minute == 30
    assert schedules["price_refresh"].minute == 40
    assert schedules["price_refresh"].timezone == "Asia/Kolkata"


def test_next_weekday_occurrence_skips_weekend_and_respects_timezone() -> None:
    friday_evening_utc = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)

    following = next_weekday_occurrence(
        friday_evening_utc,
        timezone="Asia/Kolkata",
        hour=18,
        minute=30,
    )

    assert following == datetime(2026, 10, 19, 18, 30, tzinfo=IST)


def test_schedule_config_rejects_duplicate_ids_and_invalid_times(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.toml"
    duplicate.write_text(
        '''[[jobs]]\nid="one"\nname="One"\ndescription="x"\ntimezone="UTC"\n'''
        '''cadence="weekdays"\nhour=18\nminute=0\ncatch_up="coalesce"\n'''
        '''[[jobs]]\nid="one"\nname="Two"\ndescription="x"\ntimezone="UTC"\n'''
        '''cadence="weekdays"\nhour=18\nminute=0\ncatch_up="coalesce"\n''',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicated"):
        load_schedule_definitions(duplicate)

    invalid_time = tmp_path / "invalid-time.toml"
    invalid_time.write_text(
        '''[[jobs]]\nid="one"\nname="One"\ndescription="x"\ntimezone="UTC"\n'''
        '''cadence="weekdays"\nhour=25\nminute=0\ncatch_up="coalesce"\n''',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid local run time"):
        load_schedule_definitions(invalid_time)


def test_due_schedules_coalesce_missed_weekdays_and_are_idempotent(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    definition = schedule_config()
    friday = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    store.ensure_schedule(
        job_id=definition.job_id,
        name=definition.name,
        description=definition.description,
        run_hour=definition.hour,
        run_minute=definition.minute,
        timezone_name=definition.timezone,
        cadence=definition.cadence,
        catch_up_policy=definition.catch_up_policy,
        now=friday,
    )
    monday_after_due = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)

    assert store.enqueue_due(monday_after_due) == 1
    assert store.enqueue_due(monday_after_due) == 0
    occurrence = store.recent_occurrences()[0]
    assert occurrence["scheduled_for"] == "2026-10-19T13:00:00+00:00"
    schedule = store.list_schedules()[0]
    assert schedule["next_run_at"] == "2026-10-20T13:00:00+00:00"


def test_schedule_config_updates_operational_fields_but_preserves_enabled_state(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    friday = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    fields = {
        "job_id": "sample",
        "name": "Sample job",
        "description": "For scheduler tests",
        "run_hour": 18,
        "run_minute": 30,
        "timezone_name": "Asia/Kolkata",
        "cadence": "weekdays",
        "catch_up_policy": "coalesce",
        "now": friday,
    }
    store.ensure_schedule(**fields)
    store.set_enabled("sample", False)
    store.ensure_schedule(
        **{
            **fields,
            "name": "Updated schedule",
            "run_hour": 19,
            "now": friday + timedelta(days=1),
        }
    )

    schedule = store.list_schedules()[0]
    assert schedule["enabled"] == 0
    assert schedule["name"] == "Updated schedule"
    assert schedule["run_hour"] == 19
    assert schedule["next_run_at"] == "2026-10-19T14:00:00+00:00"


def test_claims_are_exclusive_and_expired_lease_is_recovered(tmp_path: Path) -> None:
    store_a = SchedulerStore(tmp_path)
    store_b = SchedulerStore(tmp_path)
    now = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    store_a.ensure_schedule(
        job_id="sample",
        name="Sample job",
        description="test",
        run_hour=18,
        run_minute=30,
        timezone_name="Asia/Kolkata",
        cadence="weekdays",
        catch_up_policy="coalesce",
        now=now,
    )
    store_a.enqueue_manual("sample", now)
    store_a.enqueue_manual("sample", now + timedelta(seconds=1))

    first_claim = store_a.claim_next("worker-a", now, timedelta(minutes=5))
    assert first_claim is not None
    assert store_a.renew_lease(
        str(first_claim["occurrence_id"]),
        "worker-a",
        now=now + timedelta(minutes=4),
        lease=timedelta(minutes=5),
    )
    assert store_b.claim_next("worker-b", now + timedelta(minutes=4), timedelta(minutes=5)) is None
    assert store_b.claim_next("worker-b", now + timedelta(minutes=8), timedelta(minutes=5)) is None
    recovered = store_b.claim_next("worker-b", now + timedelta(minutes=10), timedelta(minutes=5))

    assert recovered is not None
    assert recovered["occurrence_id"] == first_claim["occurrence_id"]
    assert recovered["worker_id"] == "worker-b"


def test_failed_occurrence_can_be_retried(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    now = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    store.ensure_schedule(
        job_id="sample",
        name="Sample job",
        description="test",
        run_hour=18,
        run_minute=30,
        timezone_name="Asia/Kolkata",
        cadence="weekdays",
        catch_up_policy="coalesce",
        now=now,
    )
    occurrence_id = store.enqueue_manual("sample", now)
    claimed = store.claim_next("worker", now, timedelta(minutes=5))
    assert claimed is not None
    store.finish(
        occurrence_id,
        now=now,
        worker_id=str(claimed["worker_id"]),
        error_summary="network unavailable",
    )

    assert store.retry(occurrence_id, now + timedelta(minutes=1))
    retried = store.claim_next("worker", now + timedelta(minutes=1), timedelta(minutes=5))
    assert retried is not None
    assert retried["occurrence_id"] == occurrence_id
    assert store.retry(occurrence_id, now + timedelta(minutes=2)) is False


def test_scheduler_dispatches_injected_handler_and_persists_result(tmp_path: Path) -> None:
    called: list[str] = []
    scheduler = LocalScheduler(
        repository=SchedulerStore(tmp_path),
        schedules={"sample": schedule_config()},
        handlers={"sample": lambda: called.append("ran") or {"rows": 3}},
    )
    scheduler.initialize_schedules()
    occurrence_id = scheduler.repository.enqueue_manual("sample", datetime.now(UTC))

    scheduler._run_pending()

    assert called == ["ran"]
    row = scheduler.occurrences()[0]
    assert row["occurrence_id"] == occurrence_id
    assert row["status"] == "succeeded"
    assert row["result_summary"] == '{"rows": 3}'


def test_app_start_runner_enqueues_due_occurrence_and_stops_cleanly(tmp_path: Path) -> None:
    fixed_now = datetime(2026, 10, 20, 13, 30, tzinfo=UTC)  # Tuesday, 19:00 IST
    scheduler = LocalScheduler(
        repository=SchedulerStore(tmp_path),
        schedules={"sample": schedule_config()},
        handlers={"sample": lambda: {"started": True}},
        poll_seconds=0.01,
        clock=lambda: fixed_now,
    )

    scheduler.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            occurrences = scheduler.occurrences()
            if occurrences and occurrences[0]["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert occurrences
        assert occurrences[0]["trigger_type"] == "scheduled"
        assert occurrences[0]["status"] == "succeeded"
    finally:
        scheduler.stop()
    assert scheduler._thread is not None and not scheduler._thread.is_alive()


def test_scheduler_records_handler_failure_without_leaking_business_exceptions(tmp_path: Path) -> None:
    scheduler = LocalScheduler(
        repository=SchedulerStore(tmp_path),
        schedules={"sample": schedule_config()},
        handlers={"sample": lambda: (_ for _ in ()).throw(RuntimeError("vendor unavailable"))},
    )
    scheduler.initialize_schedules()
    scheduler.repository.enqueue_manual("sample", datetime.now(UTC))

    scheduler._run_pending()

    row = scheduler.occurrences()[0]
    assert row["status"] == "failed"
    assert row["error_summary"] == "RuntimeError: vendor unavailable"


def test_price_refresh_handler_catches_up_from_latest_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Store:
        def latest_trade_date(self):
            return date(2026, 10, 15)

    monkeypatch.setattr(refresh_service, "LocalPriceStore", lambda _: Store())
    captured: dict[str, object] = {}

    def importer(start, end, **kwargs):
        captured.update(start=start, end=end, **kwargs)
        return {"errors": 0, "files_downloaded": 2, "files_skipped": 1, "rows_written": 50}

    result = refresh_service.refresh_missing_prices(
        tmp_path,
        today=date(2026, 10, 20),
        importer=importer,
    )

    assert captured["start"].isoformat() == "2026-10-07"
    assert captured["end"].isoformat() == "2026-10-20"
    assert captured["stop_on_error"] is True
    assert result["rows_written"] == 50
    assert result["price_scope"] == "all EQ- and BE-series securities present in each NSE bhavcopy"


def test_price_refresh_empty_store_uses_limited_window_and_surfaces_import_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class EmptyStore:
        def latest_trade_date(self):
            return None

    monkeypatch.setattr(refresh_service, "LocalPriceStore", lambda _: EmptyStore())
    captured: dict[str, object] = {}

    def importer(start, end, **kwargs):
        captured.update(start=start, end=end, **kwargs)
        return {"errors": 0, "files_downloaded": 0, "files_skipped": 10, "rows_written": 0}

    refresh_service.refresh_missing_prices(
        tmp_path,
        today=__import__("datetime").date(2026, 10, 20),
        importer=importer,
    )
    assert (captured["end"] - captured["start"]).days + 1 == 14
    assert captured["stop_on_error"] is True

    def broken_importer(start, end, **kwargs):
        return {"errors": 1, "files_downloaded": 0, "files_skipped": 0, "rows_written": 0}

    failed = refresh_service.refresh_missing_prices(
        tmp_path,
        today=date(2026, 10, 20),
        importer=broken_importer,
    )
    assert failed["errors"] == 1


def test_price_import_stops_at_first_failed_session_when_refreshing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts: list[date] = []
    recorded_sources: list[date] = []
    finished: dict[str, object] = {}

    class Store:
        def __init__(self, data_dir):
            self.raw_dir = Path(data_dir) / "raw"
            self.raw_dir.mkdir(parents=True)

        def start_run(self, start, end):
            return "run-id"

        def save_raw(self, report):
            return self.raw_dir / report.filename, "checksum", True

        def record_source(self, report, path, checksum, source_format):
            recorded_sources.append(report.trade_date)

        def upsert_prices(self, prices):
            return 1

        def finish_run(self, run_id, **kwargs):
            finished.update(kwargs)

    class Client:
        def download(self, trade_date):
            attempts.append(trade_date)
            return DownloadedReport(trade_date, "https://example.test/report.zip", b"PK", "report.zip")

    def parse(content, trade_date, checksum):
        raise ValueError("unrecognized archive format")

    monkeypatch.setattr(bhavcopy_import, "LocalPriceStore", Store)
    monkeypatch.setattr(bhavcopy_import, "NseBhavcopyClient", Client)
    monkeypatch.setattr(bhavcopy_import, "parse_bhavcopy", parse)

    result = bhavcopy_import.import_bhavcopy_range(
        date(2026, 10, 19),
        date(2026, 10, 21),
        data_dir=tmp_path,
        progress=lambda _: None,
        stop_on_error=True,
    )

    assert attempts == [date(2026, 10, 19)]
    assert recorded_sources == []
    assert result["errors"] == 1
    assert result["failed_dates"] == ["2026-10-19"]
    assert finished["status"] == "completed_with_errors"


def test_corporate_action_handler_delegates_to_existing_staging_workflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def refresh(**kwargs):
        captured.update(kwargs)
        return {
            "source_rows": 2,
            "rows_staged": 2,
            "new_candidates": 1,
            "changed_candidates": 0,
            "missing_candidates": 0,
            "review_path": tmp_path / "review.csv",
            "changes_path": tmp_path / "changes.csv",
        }

    monkeypatch.setattr(refresh_service, "refresh_nse_action_export", refresh)
    result = refresh_service.refresh_action_candidates(
        tmp_path,
        today=date(2026, 10, 20),
    )

    assert captured["coverage_start"] == date(2021, 10, 20)
    assert captured["coverage_end"] == date(2027, 10, 20)
    assert result["rows_staged"] == 2
    assert result["review_path"] == tmp_path / "review.csv"


def test_schedulers_workspace_renders_without_running_background_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    config_path = app_path.parent / "configs" / "schedules.toml"
    monkeypatch.setenv("NSE_STRATEGY_LAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NSE_STRATEGY_LAB_SCHEDULE_CONFIG", str(config_path))
    monkeypatch.setattr(
        LocalScheduler,
        "start",
        lambda scheduler: scheduler.initialize_schedules(),
    )
    due_calls: list[bool] = []
    monkeypatch.setattr(
        LocalScheduler,
        "enqueue_due",
        lambda scheduler: due_calls.append(True) or 2,
    )
    manual_calls: list[str] = []
    monkeypatch.setattr(
        LocalScheduler,
        "enqueue_manual",
        lambda scheduler, job_id: manual_calls.append(job_id) or "manual-occurrence",
    )

    app = AppTest.from_file(str(app_path), default_timeout=10).run()
    assert not app.exception
    app.selectbox(key="workspace").select("Schedulers").run()

    assert not app.exception
    assert any(element.value == "Schedulers" for element in app.header)
    assert any("Corporate-action refresh" in element.value for element in app.markdown)
    button_keys = {element.key for element in app.button}
    assert "run_all_due_jobs" in button_keys
    assert "run_job_corporate_action_refresh" in button_keys
    assert "run_job_price_refresh" in button_keys
    app.button(key="run_job_corporate_action_refresh").click().run()

    assert not app.exception
    assert manual_calls == ["corporate_action_refresh"]
    assert any("Corporate-action refresh queued." in element.value for element in app.success)

    app.button(key="run_all_due_jobs").click().run()

    assert not app.exception
    assert due_calls == [True]
    assert any("queued 2 due job(s)" in element.value.lower() for element in app.success)
