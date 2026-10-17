"""Pure calendar calculations for persisted schedules."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def next_weekday_occurrence(
    after: datetime,
    *,
    timezone: str,
    hour: int,
    minute: int,
    inclusive: bool = False,
) -> datetime:
    """Return the next weekday slot in the schedule's timezone."""
    zone = ZoneInfo(timezone)
    local_after = after.astimezone(zone)
    candidate = local_after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < local_after or (candidate == local_after and not inclusive):
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate
