"""Python strategy definitions used by the research app."""

from collections.abc import Callable

import pandas as pd


def moving_average_cross(
    bars: pd.DataFrame, fast_window: int = 20, slow_window: int = 50
) -> pd.DataFrame:
    """Enter on a fast/slow moving-average cross and exit on the reverse cross.

    Signals are calculated using each session's closing price. The backtest engine
    executes them at the next available session's open.
    """
    if fast_window < 1 or slow_window <= fast_window:
        raise ValueError("Require 1 <= fast_window < slow_window.")

    ordered = bars.sort_values(["symbol", "date"])
    close = ordered.groupby("symbol", sort=False)["close"]
    fast = close.transform(lambda series: series.rolling(fast_window).mean())
    slow = close.transform(lambda series: series.rolling(slow_window).mean())
    above = fast > slow
    prior_above = above.groupby(ordered["symbol"], sort=False).shift(1).fillna(False)

    signals = ordered[["date", "symbol"]].copy()
    signals["entry"] = above & ~prior_above
    signals["exit"] = ~above & prior_above
    return signals


StrategyFunction = Callable[..., pd.DataFrame]

STRATEGIES: dict[str, StrategyFunction] = {
    "Moving average cross": moving_average_cross,
}
