"""Download NSE's public Corporate Actions CSV export.

The export link on NSE's Corporate Actions page currently calls the site's
corporate-actions CSV route. That route is not a versioned public API, so this
client keeps the page URL, request shape, and strict response checks together
in the NSE source adapter. A changed or blocked response fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import time

import requests

from nse_strategy_lab.ingestion.parsers.corporate_actions import NSE_ACTIONS_URL


NSE_ACTIONS_EXPORT_URL = "https://www.nseindia.com/api/corporates-corporateActions"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class DownloadedActionExport:
    """An exact CSV response and its source metadata."""

    content: bytes
    filename: str
    url: str
    coverage_start: date
    coverage_end: date


class NseCorporateActionsClient:
    """Fetch the CSV offered by NSE's public Corporate Actions page."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 45,
        retry_count: int = 3,
        retry_delay_seconds: float = 2,
    ) -> None:
        if timeout_seconds <= 0 or retry_count < 1 or retry_delay_seconds < 0:
            raise ValueError("Invalid timeout, retry count, or retry delay.")
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.retry_delay_seconds = retry_delay_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "text/csv,text/plain,*/*",
                "Referer": NSE_ACTIONS_URL,
                "Origin": "https://www.nseindia.com",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def download(self, coverage_start: date, coverage_end: date) -> DownloadedActionExport:
        """Warm an NSE session and download one inclusive date-window export."""
        if coverage_start > coverage_end:
            raise ValueError("coverage_start cannot be later than coverage_end.")

        params = {
            "index": "equities",
            "from_date": coverage_start.strftime("%d-%m-%Y"),
            "to_date": coverage_end.strftime("%d-%m-%Y"),
            "csv": "true",
        }
        last_error: Exception | None = None

        for attempt in range(self.retry_count):
            try:
                page = self._session.get(NSE_ACTIONS_URL, timeout=self.timeout_seconds)
                page.raise_for_status()
                response = self._session.get(
                    NSE_ACTIONS_EXPORT_URL,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                content = response.content
                self._validate_csv_response(content, response.headers.get("Content-Type", ""))
                filename = self._filename(response.headers.get("Content-Disposition", ""))
                if not filename:
                    filename = (
                        f"CF-CA-equities-{coverage_start:%d-%m-%Y}"
                        f"-to-{coverage_end:%d-%m-%Y}.csv"
                    )
                return DownloadedActionExport(
                    content=content,
                    filename=filename,
                    url=response.url,
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                )
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.retry_count:
                    time.sleep(self.retry_delay_seconds * (2**attempt))

        raise RuntimeError(
            "Could not retrieve a valid NSE Corporate Actions CSV after "
            f"{self.retry_count} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def _validate_csv_response(content: bytes, content_type: str) -> None:
        if not content:
            raise ValueError("NSE returned an empty Corporate Actions response.")
        sample = content[:2048].lstrip().lower()
        if sample.startswith((b"<!doctype html", b"<html", b"{", b"[")):
            raise ValueError("NSE returned HTML/JSON instead of the requested CSV export.")
        if b"," not in sample or b"symbol" not in sample or b"purpose" not in sample:
            raise ValueError("NSE response does not look like the expected CSV export.")
        if content_type and not any(
            token in content_type.lower() for token in ("csv", "text", "octet-stream")
        ):
            raise ValueError(f"Unexpected NSE response content type: {content_type}")

    @staticmethod
    def _filename(content_disposition: str) -> str | None:
        for part in content_disposition.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key.lower() == "filename":
                return value.strip().strip('"')
        return None
