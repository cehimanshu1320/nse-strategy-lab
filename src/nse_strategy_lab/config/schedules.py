"""Load and validate operational schedule definitions from TOML."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ScheduleDefinition:
    job_id: str
    name: str
    description: str
    timezone: str
    cadence: str
    hour: int
    minute: int
    catch_up_policy: str


def load_schedule_definitions(path: Path | str) -> dict[str, ScheduleDefinition]:
    """Load schedules without importing or executing any job business logic."""
    with Path(path).open("rb") as source:
        raw = tomllib.load(source)
    definitions: dict[str, ScheduleDefinition] = {}
    for item in raw.get("jobs", []):
        definition = ScheduleDefinition(
            job_id=str(item["id"]),
            name=str(item["name"]),
            description=str(item["description"]),
            timezone=str(item["timezone"]),
            cadence=str(item["cadence"]),
            hour=int(item["hour"]),
            minute=int(item["minute"]),
            catch_up_policy=str(item["catch_up"]),
        )
        if not definition.job_id or definition.job_id in definitions:
            raise ValueError(f"Schedule job ID is empty or duplicated: {definition.job_id!r}")
        if definition.cadence != "weekdays":
            raise ValueError(f"Unsupported cadence for {definition.job_id}: {definition.cadence}")
        if not 0 <= definition.hour <= 23 or not 0 <= definition.minute <= 59:
            raise ValueError(f"Invalid local run time for {definition.job_id}.")
        if not definition.catch_up_policy:
            raise ValueError(f"Missing catch-up policy for {definition.job_id}.")
        try:
            ZoneInfo(definition.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Unknown timezone for {definition.job_id}: {definition.timezone}"
            ) from exc
        definitions[definition.job_id] = definition
    if not definitions:
        raise ValueError("At least one scheduled job is required.")
    return definitions
