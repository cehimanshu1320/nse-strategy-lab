"""Shared application use cases for refreshing local NSE datasets."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from nse_strategy_lab.ingestion.jobs.bhavcopy_import import import_bhavcopy_range
from nse_strategy_lab.ingestion.jobs.corporate_action_import import refresh_nse_action_export
from nse_strategy_lab.storage.price_store import LocalPriceStore


def five_years_before(end: date) -> date:
    try:
        return end.replace(year=end.year - 5)
    except ValueError:
        return end.replace(year=end.year - 5, day=28)


def refresh_action_candidates(
    data_dir: Path | str = Path("data"),
    *,
    start: date | None = None,
    end: date | None = None,
    today: date | None = None,
    future_days: int = 365,
) -> dict[str, object]:
    """Download the rolling action export and stage it without approving rows."""
    today = today or date.today()
    if (start is None) != (end is None):
        raise ValueError("Both start and end dates must be provided together.")
    coverage_start = start or five_years_before(today)
    coverage_end = end or (today + timedelta(days=future_days))
    if coverage_start > coverage_end:
        raise ValueError("Start date cannot be later than end date.")
    result = refresh_nse_action_export(
        data_dir=data_dir,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    return {
        **result,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }


def refresh_missing_prices(
    data_dir: Path | str = Path("data"),
    *,
    from_date: date | None = None,
    today: date | None = None,
    initial_window_days: int = 14,
    recheck_days: int = 14,
    importer: Callable[..., dict[str, object]] = import_bhavcopy_range,
) -> dict[str, object]:
    """Import EQ/BE rows, catching up and rechecking recent report dates."""
    today = today or date.today()
    if initial_window_days < 1:
        raise ValueError("initial_window_days must be positive.")
    if recheck_days < 1:
        raise ValueError("recheck_days must be positive.")
    latest = LocalPriceStore(data_dir).latest_trade_date()
    if from_date:
        start = from_date
    elif latest:
        catch_up_start = latest + timedelta(days=1)
        recheck_start = today - timedelta(days=recheck_days - 1)
        start = min(catch_up_start, recheck_start)
    else:
        start = today - timedelta(days=initial_window_days - 1)
    if start > today:
        return {
            "status": "already_current",
            "latest_session": latest.isoformat() if latest else None,
            "errors": 0,
            "price_scope": "all EQ- and BE-series securities present in each NSE bhavcopy",
        }
    result = importer(
        start,
        today,
        data_dir=data_dir,
        progress=lambda _: None,
        stop_on_error=True,
    )
    return {
        **result,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "price_scope": "all EQ- and BE-series securities present in each NSE bhavcopy",
    }
