"""Canonical daily cash-equity price rows used by storage and services."""

from __future__ import annotations

PRICE_COLUMNS = [
    "trade_date",
    "symbol",
    "series",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "trade_count",
    "source_file_id",
]

PRICE_KEY = ["trade_date", "symbol", "series"]
PARSER_VERSION = "nse-cm-bhavcopy-v1"
