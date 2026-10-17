"""Shared-cash, long-only daily-bar portfolio backtester."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nse_strategy_lab.domain.corporate_actions import (
    SHARE_ACTIONS,
    validate_corporate_actions,
)


REQUIRED_BAR_COLUMNS = {"date", "symbol", "open", "close"}
REQUIRED_SIGNAL_COLUMNS = {"date", "symbol", "entry", "exit"}


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    open_positions: pd.DataFrame
    metrics: dict[str, float]


def _validate_input(bars: pd.DataFrame, signals: pd.DataFrame) -> None:
    missing_bars = REQUIRED_BAR_COLUMNS - set(bars.columns)
    missing_signals = REQUIRED_SIGNAL_COLUMNS - set(signals.columns)
    if missing_bars:
        raise ValueError(f"Price data is missing columns: {', '.join(sorted(missing_bars))}")
    if missing_signals:
        raise ValueError(
            f"Signals are missing columns: {', '.join(sorted(missing_signals))}"
        )
    if bars.duplicated(["date", "symbol"]).any():
        raise ValueError("Price data has duplicate date/symbol rows.")
    if (bars[["open", "close"]] <= 0).any().any():
        raise ValueError("Open and close prices must be positive.")


def run_backtest(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    config: BacktestConfig | None = None,
    corporate_actions: pd.DataFrame | None = None,
) -> BacktestResult:
    """Run a cash-constrained portfolio simulation.

    Signals from session t are executed at session t+1 open. Existing positions
    are exited before new entries on the same open. Entry candidates divide the
    cash then available equally; whole shares only are purchased.
    """
    config = config or BacktestConfig()
    if config.initial_cash <= 0 or config.fee_rate < 0 or config.slippage_bps < 0:
        raise ValueError("Cash must be positive; fees and slippage cannot be negative.")
    _validate_input(bars, signals)

    ordered_bars = bars.copy()
    ordered_bars["date"] = pd.to_datetime(ordered_bars["date"], errors="raise")
    ordered_bars = ordered_bars.sort_values(["date", "symbol"])
    actions = validate_corporate_actions(
        corporate_actions if corporate_actions is not None else pd.DataFrame()
    )
    ordered_signals = signals.copy()
    ordered_signals["date"] = pd.to_datetime(ordered_signals["date"], errors="raise")
    if ordered_signals.duplicated(["date", "symbol"]).any():
        raise ValueError("Signals have duplicate date/symbol rows.")

    # Schedule each signal on the next available bar for that symbol. This is
    # robust to symbols with occasional missing sessions in the imported data.
    scheduled_signals = ordered_bars[["date", "symbol"]].merge(
        ordered_signals[["date", "symbol", "entry", "exit"]],
        on=["date", "symbol"],
        how="left",
    )
    scheduled_signals[["entry", "exit"]] = scheduled_signals[["entry", "exit"]].fillna(False)
    scheduled_signals[["entry", "exit"]] = scheduled_signals.groupby("symbol", sort=False)[
        ["entry", "exit"]
    ].shift(1).fillna(False)
    signal_map = scheduled_signals.set_index(["date", "symbol"])[["entry", "exit"]]
    sessions = list(ordered_bars.groupby("date", sort=True))
    cash = float(config.initial_cash)
    positions: dict[str, dict[str, float | pd.Timestamp]] = {}
    dividend_receivables: list[dict[str, object]] = []
    completed_trades: list[dict[str, object]] = []
    daily_records: list[dict[str, object]] = []
    slippage = config.slippage_bps / 10_000

    for session_index, (date, session_bars) in enumerate(sessions):
        prices = session_bars.set_index("symbol")
        todays_signals = signal_map.xs(date, level="date")

        session_date = date.date()
        still_outstanding = []
        for receivable in dividend_receivables:
            if receivable["pay_date"] <= session_date:
                cash += float(receivable["amount"])
            else:
                still_outstanding.append(receivable)
        dividend_receivables = still_outstanding

        todays_actions = actions[actions["ex_date"] == session_date]
        # A dividend entitlement belongs to positions held through the prior
        # close. It remains a receivable until the stated payment date.
        for action in todays_actions[todays_actions["action_type"] == "dividend"].itertuples(index=False):
            position = positions.get(action.symbol)
            if position is not None:
                dividend_receivables.append(
                    {
                        "symbol": action.symbol,
                        "ex_date": action.ex_date,
                        "pay_date": action.pay_date,
                        "amount": float(position["quantity"]) * float(action.cash_per_share),
                    }
                )

        # Apply split/bonus share multipliers before ex-date open fills. Existing
        # holders keep their total cost basis; only per-share basis changes.
        for action in todays_actions[todays_actions["action_type"].isin(SHARE_ACTIONS)].itertuples(index=False):
            position = positions.get(action.symbol)
            if position is None:
                continue
            factor = float(action.share_factor)
            position["quantity"] = float(position["quantity"]) * factor
            position["entry_price"] = float(position["entry_price"]) / factor
            if "last_close" in position:
                position["last_close"] = float(position["last_close"]) / factor

        # Exit first so realized cash is available for entries on the same open.
        for symbol in list(positions):
            if symbol not in prices.index or symbol not in todays_signals.index:
                continue
            if not bool(todays_signals.at[symbol, "exit"]):
                continue
            position = positions.pop(symbol)
            fill = float(prices.at[symbol, "open"]) * (1 - slippage)
            quantity = float(position["quantity"])
            gross = quantity * fill
            fee = gross * config.fee_rate
            cash += gross - fee
            completed_trades.append(
                {
                    "symbol": symbol,
                    "entry_date": position["entry_date"],
                    "exit_date": date,
                    "entry_price": position["entry_price"],
                    "exit_price": fill,
                    "quantity": quantity,
                    "pnl": gross - fee - float(position["entry_cost"]),
                    "return_pct": (gross - fee) / float(position["entry_cost"]) - 1,
                    "status": "closed",
                }
            )

        candidates = []
        for symbol in prices.index:
            if symbol in positions or symbol not in todays_signals.index:
                continue
            if bool(todays_signals.at[symbol, "entry"]):
                candidates.append(symbol)

        if candidates and cash > 0:
            allocation = cash / len(candidates)
            for symbol in candidates:
                fill = float(prices.at[symbol, "open"]) * (1 + slippage)
                quantity = int(allocation / (fill * (1 + config.fee_rate)))
                if quantity <= 0:
                    continue
                gross = quantity * fill
                fee = gross * config.fee_rate
                total_cost = gross + fee
                if total_cost > cash:
                    continue
                cash -= total_cost
                positions[symbol] = {
                    "quantity": quantity,
                    "entry_date": date,
                    "entry_price": fill,
                    "entry_cost": total_cost,
                }

        market_value = 0.0
        for symbol, position in positions.items():
            if symbol in prices.index:
                position["last_close"] = float(prices.at[symbol, "close"])
            if "last_close" in position:
                market_value += float(position["quantity"]) * float(position["last_close"])
        receivable_value = sum(float(item["amount"]) for item in dividend_receivables)
        daily_records.append(
            {
                "date": date,
                "cash": cash,
                "market_value": market_value,
                "dividend_receivable": receivable_value,
                "equity": cash + market_value + receivable_value,
            }
        )

    equity = pd.DataFrame(daily_records).set_index("date")
    trades = pd.DataFrame(completed_trades)
    open_rows = []
    if sessions:
        for symbol, position in positions.items():
            last_close = float(position.get("last_close", np.nan))
            quantity = float(position["quantity"])
            open_rows.append(
                {
                    "symbol": symbol,
                    "entry_date": position["entry_date"],
                    "entry_price": position["entry_price"],
                    "quantity": quantity,
                    "last_close": last_close,
                    "unrealized_pnl": quantity * (last_close - float(position["entry_price"]))
                    if pd.notna(last_close)
                    else np.nan,
                }
            )
    open_positions = pd.DataFrame(open_rows)
    metrics = _summarize(equity, trades, config.initial_cash)
    return BacktestResult(equity, trades, open_positions, metrics)


def _summarize(equity: pd.DataFrame, trades: pd.DataFrame, initial_cash: float) -> dict[str, float]:
    if equity.empty:
        return {"total_return_pct": 0.0, "cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0, "closed_trades": 0.0, "win_rate_pct": 0.0}
    values = equity["equity"].astype(float)
    returns = values.pct_change().dropna()
    total_return = values.iloc[-1] / initial_cash - 1
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0)
    cagr = (values.iloc[-1] / initial_cash) ** (1 / years) - 1 if years > 0 else total_return
    drawdown = values / values.cummax() - 1
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 1 and returns.std() > 0 else 0.0
    closed = len(trades)
    win_rate = float((trades["pnl"] > 0).mean() * 100) if closed else 0.0
    return {
        "total_return_pct": float(total_return * 100),
        "cagr_pct": float(cagr * 100),
        "max_drawdown_pct": float(drawdown.min() * 100),
        "sharpe": float(sharpe),
        "closed_trades": float(closed),
        "win_rate_pct": win_rate,
    }
