"""Composition adapters from stable scheduler IDs to shared app use cases."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from nse_strategy_lab.services.refresh import (
    refresh_action_candidates,
    refresh_missing_prices,
)


def build_refresh_handlers(
    data_dir: Path | str,
    *,
    timezones: dict[str, str] | None = None,
) -> dict[str, Callable[[], object]]:
    """Bind scheduled job IDs to the same refresh use cases used by the CLI."""
    timezones = timezones or {}

    def today_in_schedule_timezone(job_id: str) -> date:
        return datetime.now(ZoneInfo(timezones.get(job_id, "Asia/Kolkata"))).date()

    def refresh_actions() -> object:
        return refresh_action_candidates(
            data_dir,
            today=today_in_schedule_timezone("corporate_action_refresh"),
        )

    def refresh_prices() -> object:
        result = refresh_missing_prices(
            data_dir,
            today=today_in_schedule_timezone("price_refresh"),
        )
        if int(result.get("errors", 0)):
            failed_dates = result.get("failed_dates") or []
            failed_date_summary = (
                f" First failed session: {failed_dates[0]}."
                if failed_dates
                else ""
            )
            raise RuntimeError(
                f"Price import had {result['errors']} failed session(s); "
                f"see the import catalog for details.{failed_date_summary}"
            )
        return result

    return {
        "corporate_action_refresh": refresh_actions,
        "price_refresh": refresh_prices,
    }
