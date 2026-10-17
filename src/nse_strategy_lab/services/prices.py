"""Read-only price queries for the Streamlit UI and research workflows."""

from datetime import date
from pathlib import Path

import pandas as pd

from nse_strategy_lab.storage.price_store import LocalPriceStore
from nse_strategy_lab.services.adjustments import adjust_price_history, strategy_bars_from_adjusted


def list_price_symbols(data_dir: Path | str = Path("data")) -> list[str]:
    return LocalPriceStore(data_dir).list_symbols()


def query_daily_prices(
    symbol: str,
    start: date,
    end: date,
    data_dir: Path | str = Path("data"),
) -> pd.DataFrame:
    return LocalPriceStore(data_dir).load_prices(symbol=symbol, start=start, end=end)


def query_price_history(
    symbol: str,
    start: date,
    end: date,
    *,
    basis: str = "raw",
    data_dir: Path | str = Path("data"),
) -> pd.DataFrame:
    """Load a raw or event-adjusted chart snapshot ending on ``end``."""
    store = LocalPriceStore(data_dir)
    if basis == "raw":
        return store.load_prices(symbol=symbol, start=start, end=end)
    if basis != "adjusted":
        raise ValueError("Price basis must be 'raw' or 'adjusted'.")

    # Load complete history so the 52-week lookback is not truncated by the
    # visible chart range. All rows are restated to the selected end-date basis.
    raw = store.load_prices(symbol=symbol)
    if raw.empty:
        return raw
    adjusted = adjust_price_history(
        raw,
        store.load_corporate_actions(symbol),
        as_of_date=end,
    )
    for field in ("open", "high", "low", "close", "volume"):
        if field in adjusted:
            adjusted[f"{field}_raw"] = adjusted[field]
    result = strategy_bars_from_adjusted(adjusted)
    result = result[(result["trade_date"] >= start) & (result["trade_date"] <= end)]
    return result.reset_index(drop=True)


def latest_price_date(data_dir: Path | str = Path("data")) -> date | None:
    return LocalPriceStore(data_dir).latest_trade_date()


def latest_import_status(data_dir: Path | str = Path("data")) -> dict[str, object] | None:
    return LocalPriceStore(data_dir).import_status()


def query_corporate_actions(
    symbol: str | None = None,
    data_dir: Path | str = Path("data"),
) -> pd.DataFrame:
    return LocalPriceStore(data_dir).load_corporate_actions(symbol)
