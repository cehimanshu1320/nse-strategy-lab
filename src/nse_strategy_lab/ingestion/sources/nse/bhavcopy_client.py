"""Download NSE cash-market daily bhavcopy ZIP files by trading date."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import requests

UDIFF_START_DATE = date(2024, 7, 8)
NSE_ARCHIVE_ROOT = "https://nsearchives.nseindia.com"


def bhavcopy_url(trade_date: date) -> str:
    """Return the archive URL for the date's known NSE report format."""
    if trade_date >= UDIFF_START_DATE:
        filename = f"BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv.zip"
        return f"{NSE_ARCHIVE_ROOT}/content/cm/{filename}"

    month = trade_date.strftime("%b").upper()
    filename = f"cm{trade_date:%d}{month}{trade_date:%Y}bhav.csv.zip"
    return (
        f"{NSE_ARCHIVE_ROOT}/content/historical/EQUITIES/"
        f"{trade_date:%Y}/{month}/{filename}"
    )


@dataclass(frozen=True)
class DownloadedReport:
    trade_date: date
    url: str
    content: bytes
    filename: str


class NseBhavcopyClient:
    """Small synchronous client; it does not crawl report pages."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30,
        retry_count: int = 3,
        request_interval_seconds: float = 1.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.request_interval_seconds = request_interval_seconds
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "NSEStrategyLab/0.1 (personal research prototype)",
                "Accept": "application/zip,application/octet-stream,*/*",
            }
        )

    def download(self, trade_date: date) -> DownloadedReport | None:
        """Download one date, returning None when no archive exists for it."""
        url = bhavcopy_url(trade_date)
        last_error: Exception | None = None

        for attempt in range(self.retry_count):
            wait = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self._session.get(url, timeout=self.timeout_seconds)
                self._last_request_at = time.monotonic()
                if response.status_code in (404, 410):
                    return None
                response.raise_for_status()
                if not response.content.startswith(b"PK"):
                    raise ValueError(f"NSE returned a non-ZIP response for {trade_date}")
                return DownloadedReport(
                    trade_date=trade_date,
                    url=url,
                    content=response.content,
                    filename=url.rsplit("/", maxsplit=1)[-1],
                )
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.retry_count:
                    time.sleep(2**attempt)

        raise RuntimeError(f"Could not download NSE bhavcopy for {trade_date}: {last_error}")
