"""Import a dated NSE all-company market-cap workbook."""

from __future__ import annotations

from pathlib import Path

from nse_strategy_lab.ingestion.parsers.nse_market_cap import (
    parse_nse_average_market_cap_workbook,
)
from nse_strategy_lab.storage.market_cap_store import LocalMarketCapStore


NSE_MARKET_CAP_PAGE = (
    "https://www.nseindia.com/static/regulations/listing-compliance/"
    "nse-market-capitalisation-all-companies"
)
NSE_MARKET_CAP_WORKBOOK_URL = (
    "https://nsearchives.nseindia.com/web/mediaattachment/2026-01/"
    "Average_MCAP_July2025ToDecember2025_20260102201101.xlsx"
)


def import_nse_market_cap_workbook(
    workbook_path: Path | str,
    *,
    data_dir: Path | str = Path("data"),
    source_url: str = NSE_MARKET_CAP_WORKBOOK_URL,
) -> dict[str, object]:
    """Archive and import NSE's average-market-cap workbook with its period."""
    input_path = Path(workbook_path)
    content = input_path.read_bytes()
    store = LocalMarketCapStore(data_dir)
    raw_path, source_file_id, retrieved_at = store.archive_source(content, input_path.name)
    observations = parse_nse_average_market_cap_workbook(
        content,
        source_file_id=source_file_id,
        source_url=source_url,
        retrieved_at=retrieved_at,
    )
    not_traded_rows = int(observations.attrs.get("not_traded_rows", 0))
    rows_written = store.save_observations(observations)
    first = observations.iloc[0]
    store.record_import(
        source_file_id=source_file_id,
        source_url=source_url,
        retrieved_at=retrieved_at,
        local_path=raw_path,
        rows_imported=rows_written,
        observation_type=str(first["observation_type"]),
        period_start=first["period_start"].isoformat(),
        period_end=first["period_end"].isoformat(),
    )
    return {
        "source_file_id": source_file_id,
        "raw_path": str(raw_path),
        "rows_written": rows_written,
        "not_traded_rows": not_traded_rows,
        "period_start": first["period_start"].isoformat(),
        "period_end": first["period_end"].isoformat(),
    }
