"""Read-only market-cap observation queries for the application."""

from pathlib import Path

import pandas as pd

from nse_strategy_lab.domain.instruments import (
    attach_instrument_identity,
    source_symbols_for,
)
from nse_strategy_lab.storage.market_cap_store import (
    MARKET_CAP_COLUMNS,
    LocalMarketCapStore,
)


def query_market_cap_history(
    symbol: str,
    data_dir: Path | str = Path("data"),
) -> pd.DataFrame:
    """Return dated NSE market-cap observations for one selected company."""
    observations = LocalMarketCapStore(data_dir).load_observations()
    empty = pd.DataFrame(columns=[*MARKET_CAP_COLUMNS, "instrument_id"])
    if observations.empty:
        return empty

    for column in ("as_of_date", "period_start", "period_end"):
        observations[column] = pd.to_datetime(observations[column], errors="coerce").dt.date
    observations["symbol"] = observations["symbol"].astype(str).str.strip().str.upper()
    observations["market_cap_inr_crore"] = pd.to_numeric(
        observations["market_cap_inr_crore"], errors="raise"
    )
    observations = observations[observations["symbol"].isin(source_symbols_for(symbol))].copy()
    if observations.empty:
        return empty

    observations["identity_date"] = observations["as_of_date"].fillna(
        observations["period_end"]
    )
    observations = attach_instrument_identity(
        observations, date_column="identity_date", canonical_symbol=True
    )
    observations = observations[
        (observations["symbol"] == symbol.strip().upper())
        & observations["market_cap_inr_crore"].notna()
        & (observations["market_cap_inr_crore"] > 0)
    ].copy()
    if observations.empty:
        return empty

    observations["chart_date"] = observations["as_of_date"].fillna(
        observations["period_end"]
    )
    natural_key = [
        "observation_type",
        "as_of_date",
        "period_start",
        "period_end",
        "instrument_id",
    ]
    observations = observations.sort_values("retrieved_at").drop_duplicates(
        natural_key, keep="last"
    )
    return observations.sort_values("chart_date").reset_index(drop=True)
