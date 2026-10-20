"""Download, preserve, parse, validate, and store a date range of bhavcopies."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from nse_strategy_lab.ingestion.parsers.bhavcopy import parse_bhavcopy
from nse_strategy_lab.ingestion.sources.nse.bhavcopy_client import (
    DownloadedReport,
    NseBhavcopyClient,
    bhavcopy_url,
)
from nse_strategy_lab.storage.price_store import LocalPriceStore


def _weekdays(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def _cached_report(store: LocalPriceStore, trade_date: date) -> DownloadedReport | None:
    url = bhavcopy_url(trade_date)
    filename = url.rsplit("/", maxsplit=1)[-1]
    path = store.raw_dir / f"{trade_date:%Y}" / f"{trade_date:%m}" / filename
    if not path.exists():
        return None
    return DownloadedReport(
        trade_date=trade_date,
        url=url,
        content=path.read_bytes(),
        filename=filename,
    )


def import_bhavcopy_range(
    start: date,
    end: date,
    *,
    data_dir: Path | str = Path("data"),
    symbols: set[str] | None = None,
    progress=print,
    stop_on_error: bool = False,
) -> dict[str, object]:
    if start > end:
        raise ValueError("Start date must be on or before end date")

    store = LocalPriceStore(data_dir)
    client = NseBhavcopyClient()
    run_id = store.start_run(start, end)
    downloaded = skipped = rows_written = 0
    no_report_dates: list[str] = []
    failed_dates: list[str] = []
    failures: list[str] = []

    try:
        for trade_date in _weekdays(start, end):
            try:
                report = _cached_report(store, trade_date)
                if report is None:
                    report = client.download(trade_date)
                    if report is None:
                        skipped += 1
                        no_report_dates.append(trade_date.isoformat())
                        progress(f"{trade_date}: no bhavcopy (holiday or unavailable)")
                        continue

                raw_path, checksum, was_saved = store.save_raw(report)
                if was_saved:
                    downloaded += 1
                else:
                    skipped += 1
                source_format = "udiff" if trade_date >= date(2024, 7, 8) else "legacy"
                prices = parse_bhavcopy(report.content, trade_date, checksum)
                if symbols:
                    prices = prices[prices["symbol"].isin({item.upper() for item in symbols})]
                store.record_source(report, raw_path, checksum, source_format)
                row_count = store.upsert_prices(prices)
                rows_written += row_count
                progress(f"{trade_date}: imported {row_count:,} rows ({source_format})")
            except Exception as exc:
                failures.append(f"{trade_date}: {type(exc).__name__}: {exc}")
                failed_dates.append(trade_date.isoformat())
                progress(f"{trade_date}: ERROR {exc}")
                if stop_on_error:
                    break
    finally:
        store.finish_run(
            run_id,
            status="completed_with_errors" if failures else "completed",
            files_downloaded=downloaded,
            files_skipped=skipped,
            rows_written=rows_written,
            error_summary="\n".join(failures) or None,
        )

    return {
        "run_id": run_id,
        "files_downloaded": downloaded,
        "files_skipped": skipped,
        "rows_written": rows_written,
        "errors": len(failures),
        "failed_dates": failed_dates,
        "no_report_dates": no_report_dates,
    }
