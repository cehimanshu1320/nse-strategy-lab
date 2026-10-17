"""Point-in-time corporate-action price and share-volume adjustments."""

from __future__ import annotations

from datetime import date

import pandas as pd

from nse_strategy_lab.domain.corporate_actions import (
    SHARE_ACTIONS,
    validate_corporate_actions,
)


PRICE_FIELDS = ("open", "high", "low", "close")


def adjust_price_history(
    bars: pd.DataFrame,
    actions: pd.DataFrame,
    *,
    as_of_date: date,
) -> pd.DataFrame:
    """Restate historical bars to the share basis effective on ``as_of_date``.

    Only events announced and effective by the requested date are applied.
    Source columns are preserved; adjusted values are emitted as separate,
    explicitly named columns.
    """
    if bars.empty:
        result = bars.copy()
        for field in PRICE_FIELDS:
            result[f"{field}_adjusted"] = pd.Series(dtype="float64")
        if "volume" in result:
            result["volume_adjusted"] = pd.Series(dtype="float64")
        return result

    date_column = "trade_date" if "trade_date" in bars else "date"
    required = {date_column, "symbol", *PRICE_FIELDS}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"Price history is missing columns: {sorted(missing)}")

    result = bars.copy().sort_values(["symbol", date_column]).reset_index(drop=True)
    if "series" not in result:
        result["series"] = "EQ"
    result[date_column] = pd.to_datetime(result[date_column]).dt.date
    for field in PRICE_FIELDS:
        result[f"{field}_adjusted"] = pd.to_numeric(result[field], errors="raise").astype(float)
    if "volume" in result:
        result["volume_adjusted"] = pd.to_numeric(result["volume"], errors="raise").astype(float)

    normalized_actions = validate_corporate_actions(actions)
    eligible = normalized_actions[
        (normalized_actions["announcement_date"] <= as_of_date)
        & (normalized_actions["ex_date"] <= as_of_date)
    ].copy()
    # For multiple same-day events, apply share-basis changes before cash
    # distributions so the dividend amount is interpreted per ex-date share.
    eligible["_action_order"] = eligible["action_type"].map(
        {"bonus": 0, "split": 0, "dividend": 1}
    )
    eligible = eligible.sort_values(["ex_date", "_action_order"])
    for action in eligible.itertuples(index=False):
        mask = (
            (result["symbol"] == action.symbol)
            & (result["series"] == action.series)
            & (result[date_column] < action.ex_date)
        )
        if action.action_type in SHARE_ACTIONS:
            result.loc[mask, [f"{field}_adjusted" for field in PRICE_FIELDS]] *= (
                1.0 / float(action.share_factor)
            )
            if "volume_adjusted" in result:
                result.loc[mask, "volume_adjusted"] *= float(action.share_factor)
        elif action.action_type == "dividend" and mask.any():
            prior = result[
                (result["symbol"] == action.symbol)
                & (result["series"] == action.series)
                & (result[date_column] < action.ex_date)
            ].sort_values(date_column)
            prior_close = float(prior.iloc[-1]["close_adjusted"])
            adjustment_factor = (prior_close - float(action.cash_per_share)) / prior_close
            if adjustment_factor <= 0:
                raise ValueError(
                    f"Dividend on {action.symbol} at {action.ex_date} is not smaller "
                    "than the preceding adjusted close."
                )
            result.loc[mask, [f"{field}_adjusted" for field in PRICE_FIELDS]] *= (
                adjustment_factor
            )

    return result


def strategy_bars_from_adjusted(adjusted: pd.DataFrame) -> pd.DataFrame:
    """Expose adjusted OHLCV under the conventional strategy column names."""
    result = adjusted.copy()
    for field in PRICE_FIELDS:
        result[field] = result[f"{field}_adjusted"]
    if "volume_adjusted" in result:
        result["volume"] = result["volume_adjusted"]
    date_column = "date" if "date" in result else "trade_date"
    result["high_52w"] = float("nan")
    result["low_52w"] = float("nan")
    for _, indexes in result.groupby("symbol", sort=False).groups.items():
        group = result.loc[indexes].sort_values(date_column)
        dates = pd.DatetimeIndex(pd.to_datetime(group[date_column]))
        highs = pd.Series(group["high"].to_numpy(), index=dates)
        lows = pd.Series(group["low"].to_numpy(), index=dates)
        result.loc[group.index, "high_52w"] = highs.rolling("364D", closed="both").max().to_numpy()
        result.loc[group.index, "low_52w"] = lows.rolling("364D", closed="both").min().to_numpy()
    return result


def point_in_time_signals(strategy, raw_bars: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Evaluate a strategy on an action-adjusted history as of every session.

    Recomputing each date's prefix is intentionally simple and correct for the
    prototype. It prevents a later split/bonus from changing earlier signals.
    The strategy receives only data dated through its decision session.
    """
    if raw_bars.empty:
        return pd.DataFrame(columns=["date", "symbol", "entry", "exit"])
    date_column = "date" if "date" in raw_bars else "trade_date"
    ordered = raw_bars.copy()
    ordered[date_column] = pd.to_datetime(ordered[date_column]).dt.date
    outputs = []
    for decision_date in sorted(ordered[date_column].unique()):
        prefix = ordered[ordered[date_column] <= decision_date]
        adjusted = adjust_price_history(prefix, actions, as_of_date=decision_date)
        strategy_input = strategy_bars_from_adjusted(adjusted)
        signals = strategy(strategy_input)
        current = signals[pd.to_datetime(signals["date"]).dt.date == decision_date]
        outputs.append(current)
    if not outputs:
        return pd.DataFrame(columns=["date", "symbol", "entry", "exit"])
    return pd.concat(outputs, ignore_index=True).drop_duplicates(["date", "symbol"], keep="last")
