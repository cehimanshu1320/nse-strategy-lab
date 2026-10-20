"""Read-only price queries for the Streamlit UI and research workflows."""

from datetime import date
from pathlib import Path

import pandas as pd

from nse_strategy_lab.storage.price_store import LocalPriceStore
from nse_strategy_lab.domain.instruments import (
    attach_instrument_identity,
    current_symbol_for_source,
    source_symbols_for,
)
from nse_strategy_lab.services.adjustments import (
    add_52_week_extrema,
    adjust_price_history,
    strategy_bars_from_adjusted,
)


def list_price_symbols(data_dir: Path | str = Path("data")) -> list[str]:
    store_symbols = LocalPriceStore(data_dir).list_symbols()
    return sorted({current_symbol_for_source(symbol) for symbol in store_symbols})


def query_daily_prices(
    symbol: str,
    start: date,
    end: date,
    data_dir: Path | str = Path("data"),
) -> pd.DataFrame:
    store = LocalPriceStore(data_dir)
    return _load_instrument_prices(store, symbol, start=start, end=end)


def _load_instrument_prices(
    store: LocalPriceStore,
    symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    frames = [
        store.load_prices(symbol=source, start=start, end=end)
        for source in source_symbols_for(symbol)
    ]
    rows = [frame for frame in frames if not frame.empty]
    if not rows:
        return pd.DataFrame(columns=store.load_prices(symbol=symbol).columns)
    combined = pd.concat(rows, ignore_index=True).sort_values(
        ["trade_date", "symbol", "series"]
    )
    combined = attach_instrument_identity(
        combined, date_column="trade_date", canonical_symbol=True
    )
    return combined.reset_index(drop=True)


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
    source_symbols = source_symbols_for(symbol)
    if basis == "raw":
        raw = _load_instrument_prices(store, symbol)
        if raw.empty:
            return raw
        raw = add_52_week_extrema(raw)
        date_values = pd.to_datetime(raw["trade_date"], errors="raise").dt.date
        return raw[date_values.between(start, end)].reset_index(drop=True)
    if basis != "adjusted":
        raise ValueError("Price basis must be 'raw' or 'adjusted'.")

    # Load complete history so the 52-week lookback is not truncated by the
    # visible chart range. All rows are restated to the selected end-date basis.
    raw_frames = [store.load_prices(symbol=source) for source in source_symbols]
    raw = pd.concat([frame for frame in raw_frames if not frame.empty], ignore_index=True)
    if raw.empty:
        return raw
    action_frames = [store.load_corporate_actions(source) for source in source_symbols]
    action_rows = [frame for frame in action_frames if not frame.empty]
    actions = pd.concat(action_rows, ignore_index=True) if action_rows else pd.DataFrame()
    adjusted = adjust_price_history(
        raw,
        actions,
        as_of_date=end,
    )
    adjusted = attach_instrument_identity(
        adjusted, date_column="trade_date", canonical_symbol=True
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
    store = LocalPriceStore(data_dir)
    if symbol is None:
        return store.load_corporate_actions()
    frames = [store.load_corporate_actions(source) for source in source_symbols_for(symbol)]
    actions = [frame for frame in frames if not frame.empty]
    if not actions:
        return store.load_corporate_actions(symbol)
    return pd.concat(actions, ignore_index=True).drop_duplicates().reset_index(drop=True)
