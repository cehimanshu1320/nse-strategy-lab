from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from nse_strategy_lab.config.schedules import load_schedule_definitions
from nse_strategy_lab.engine import BacktestConfig, run_backtest
from nse_strategy_lab.services.prices import (
    latest_import_status,
    latest_price_date,
    list_price_symbols,
    query_price_history,
    query_corporate_actions,
)
from nse_strategy_lab.services.adjustments import point_in_time_signals
from nse_strategy_lab.services.scheduler import LocalScheduler
from nse_strategy_lab.services.scheduled_refresh import build_refresh_handlers
from nse_strategy_lab.strategies import STRATEGIES
from nse_strategy_lab.storage.scheduler_store import SchedulerStore


st.set_page_config(page_title="NSE Strategy Lab", page_icon="📈", layout="wide")

DATA_DIR = Path(os.environ.get("NSE_STRATEGY_LAB_DATA_DIR", "data"))
SCHEDULE_CONFIG = Path(
    os.environ.get("NSE_STRATEGY_LAB_SCHEDULE_CONFIG", "configs/schedules.toml")
)


@st.cache_resource
def get_local_scheduler(data_dir: str, schedule_config: str) -> LocalScheduler:
    schedule_definitions = load_schedule_definitions(schedule_config)
    scheduler = LocalScheduler(
        repository=SchedulerStore(data_dir),
        schedules=schedule_definitions,
        handlers=build_refresh_handlers(
            data_dir,
            timezones={job_id: item.timezone for job_id, item in schedule_definitions.items()},
        ),
    )
    scheduler.start()
    return scheduler


@st.cache_data(ttl=300, max_entries=32)
def load_chart_prices(
    symbol: str,
    start: date,
    end: date,
    basis: str,
    import_marker: str,
    action_marker: str,
) -> pd.DataFrame:
    # Markers are included in the cache key to invalidate after source changes.
    del import_marker, action_marker
    return query_price_history(symbol, start, end, basis=basis, data_dir=DATA_DIR)


def show_price_explorer() -> None:
    st.header("Price explorer")
    st.caption("Daily NSE cash-market prices from locally imported bhavcopy files")

    symbols = list_price_symbols(DATA_DIR)
    latest_date = latest_price_date(DATA_DIR)
    status = latest_import_status(DATA_DIR)

    if not symbols or latest_date is None:
        st.info(
            "No market data has been imported yet. Run the local backfill command "
            "shown below, then refresh this page."
        )
        st.code("nse-strategy-lab backfill", language="bash")
        st.caption("The command downloads and imports one bhavcopy per available trading date.")
        return

    with st.sidebar:
        st.subheader("Price filters")
        symbol = st.selectbox("NSE symbol", symbols, index=0)
        basis_label = st.selectbox(
            "Price basis",
            ["Corporate-action adjusted", "Raw NSE prices"],
            index=0,
        )
        basis = "adjusted" if basis_label == "Corporate-action adjusted" else "raw"
        range_name = st.selectbox("Date range", ["1M", "6M", "1Y", "5Y", "All", "Custom"], index=3)

        if range_name == "Custom":
            selected_range = st.date_input(
                "Custom range",
                value=(max(date(1900, 1, 1), latest_date - timedelta(days=365)), latest_date),
                max_value=latest_date,
            )
        else:
            days = {"1M": 31, "6M": 183, "1Y": 365, "5Y": 365 * 5}.get(range_name)
            start_date = date(1900, 1, 1) if days is None else latest_date - timedelta(days=days)
            selected_range = (start_date, latest_date)

    if (
        not isinstance(selected_range, tuple)
        or len(selected_range) != 2
        or selected_range[0] is None
        or selected_range[1] is None
    ):
        st.warning("Choose both a start and end date.")
        return
    start_date, end_date = selected_range
    if start_date > end_date:
        st.warning("The start date must be before the end date.")
        return

    import_marker = str((status or {}).get("completed_at") or latest_date)
    action_records = query_corporate_actions(symbol, DATA_DIR)
    action_marker = str(
        pd.util.hash_pandas_object(action_records, index=False).sum()
        if not action_records.empty
        else "no-actions"
    )
    prices = load_chart_prices(
        symbol, start_date, end_date, basis, import_marker, action_marker
    )
    if prices.empty:
        st.info("No rows are available for this symbol and date range.")
        return

    if status:
        st.caption(
            f"Latest import status: {status['status']} · "
            f"{status['files_downloaded']} new files · {status['rows_written']:,} rows written"
        )
        if status.get("error_summary"):
            with st.expander("Latest import errors"):
                st.code(str(status["error_summary"]), language="text")

    action_count = 0
    if not action_records.empty:
        action_count = int(
            (
                (action_records["announcement_date"] <= end_date)
                & (action_records["ex_date"] <= end_date)
            ).sum()
        )
    if basis == "adjusted":
        st.caption(
            f"Corporate-action adjusted to {end_date.isoformat()} using {action_count} "
            "recorded event(s). Raw NSE values remain available in the table. "
            "52-week extrema use the adjusted price basis."
        )
    else:
        st.caption(
            "Raw exchange-reported OHLCV. Corporate actions are not adjusted; "
            "52-week extrema may be distorted across bonus or split dates."
        )
    with st.container(horizontal=True):
        st.metric("Latest imported session", latest_date.isoformat(), border=True)
        st.metric("Sessions in view", f"{len(prices):,}", border=True)
        st.metric("Last close", f"₹{float(prices['close'].iloc[-1]):,.2f}", border=True)
        st.metric("52-week high at range end", f"₹{float(prices['high_52w'].iloc[-1]):,.2f}", border=True)
        st.metric("52-week low at range end", f"₹{float(prices['low_52w'].iloc[-1]):,.2f}", border=True)

    with st.container(border=True):
        price_label = "Adjusted close" if basis == "adjusted" else "Raw close"
        st.subheader(f"{symbol} {price_label.lower()}")
        st.line_chart(
            prices,
            x="trade_date",
            y="close",
            alt=f"Daily {basis_label.lower()} closing price for {symbol}",
        )

    with st.container(border=True):
        st.subheader("Traded volume")
        st.bar_chart(
            prices,
            x="trade_date",
            y="volume",
            alt=f"Daily {basis_label.lower()} share volume for {symbol}",
        )

    visible_columns = ["trade_date", "symbol", "series"]
    if basis == "adjusted":
        visible_columns.extend(
            [
                "open_raw", "high_raw", "low_raw", "close_raw",
                "open_adjusted", "high_adjusted", "low_adjusted", "close_adjusted",
                "high_52w", "low_52w", "volume_raw", "volume_adjusted",
            ]
        )
    else:
        visible_columns.extend(
            ["open", "high", "low", "close", "high_52w", "low_52w", "volume"]
        )
    visible_columns.extend(["turnover", "trade_count"])
    st.dataframe(
        prices[visible_columns],
        hide_index=True,
        alt=f"Daily {basis_label.lower()} price rows for {symbol}",
    )
    st.download_button(
        "Download these rows as CSV",
        data=prices[visible_columns].to_csv(index=False).encode("utf-8"),
        file_name=f"{symbol.lower()}_{start_date}_{end_date}.csv",
        mime="text/csv",
    )


def show_backtest() -> None:
    st.header("Strategy backtest")
    st.caption("Run Python-coded daily strategies against an uploaded CSV")

    with st.sidebar:
        st.subheader("Backtest setup")
        uploaded_file = st.file_uploader("Price history (CSV)", type=["csv"])
        actions_file = st.file_uploader("Corporate actions (CSV, optional)", type=["csv"])
        strategy_name = st.selectbox("Strategy", list(STRATEGIES))
        initial_cash = st.number_input("Initial cash (₹)", min_value=1_000, value=1_000_000, step=50_000)
        fee_pct = st.number_input("Fees per side (%)", min_value=0.0, value=0.10, step=0.01)
        slippage_bps = st.number_input("Slippage per side (bps)", min_value=0.0, value=5.0, step=1.0)
        run_clicked = st.button("Run backtest", type="primary", disabled=uploaded_file is None)

    st.info(
        "Signals are calculated after the close and executed at the next session's open. "
        "Positions share one cash balance; exits run before entries, and simultaneous "
        "entry candidates split available cash equally."
    )

    if uploaded_file is None:
        st.markdown(
            "Upload a CSV with one row per trading date and symbol. Required columns: "
            "`date`, `symbol`, `open`, `close`. Optional columns include `high`, `low`, "
            "and `volume`. When an action CSV is provided, strategy signals use "
            "point-in-time adjusted bars while simulated fills use the uploaded raw bars."
        )
        st.code(
            "date,symbol,open,high,low,close,volume\n"
            "2024-01-02,RELIANCE,2580,2600,2570,2590,1234567",
            language="csv",
        )
    elif run_clicked:
        try:
            bars = pd.read_csv(uploaded_file, parse_dates=["date"])
            strategy = STRATEGIES[strategy_name]
            if actions_file is not None:
                actions = pd.read_csv(actions_file)
                signals = point_in_time_signals(strategy, bars, actions)
            else:
                actions = pd.DataFrame()
                signals = strategy(bars)
            result = run_backtest(
                bars,
                signals,
                BacktestConfig(
                    initial_cash=float(initial_cash),
                    fee_rate=float(fee_pct) / 100,
                    slippage_bps=float(slippage_bps),
                ),
                corporate_actions=actions,
            )
            st.session_state["last_result"] = result
            st.session_state["last_strategy"] = strategy_name
        except Exception as exc:
            st.error(f"Could not run this backtest: {exc}")

    result = st.session_state.get("last_result")
    if result is None:
        return

    st.subheader(st.session_state.get("last_strategy", "Backtest results"))
    metrics = result.metrics
    cards = st.columns(5)
    cards[0].metric("Total return", f"{metrics['total_return_pct']:.2f}%")
    cards[1].metric("CAGR", f"{metrics['cagr_pct']:.2f}%")
    cards[2].metric("Max drawdown", f"{metrics['max_drawdown_pct']:.2f}%")
    cards[3].metric("Sharpe", f"{metrics['sharpe']:.2f}")
    cards[4].metric("Closed trades", f"{int(metrics['closed_trades'])}")

    left, right = st.columns([2, 1])
    with left:
        st.subheader("Portfolio equity (₹)")
        equity_curve = result.equity_curve.reset_index()
        st.line_chart(
            equity_curve,
            x="date",
            y="equity",
            alt="Portfolio equity through the backtest",
        )
    with right:
        st.metric("Win rate", f"{metrics['win_rate_pct']:.1f}%")
        st.metric("Ending cash", f"₹{result.equity_curve['cash'].iloc[-1]:,.0f}")
        st.metric("Open positions", len(result.open_positions))

    st.subheader("Closed trades")
    st.dataframe(result.trades, width="stretch", hide_index=True, alt="Closed backtest trades")
    st.subheader("Open positions")
    st.dataframe(result.open_positions, width="stretch", hide_index=True, alt="Open backtest positions")


def show_schedulers(scheduler: LocalScheduler) -> None:
    st.header("Schedulers")
    st.caption(
        "Weekday jobs use their configured time zones. The runner works while this app process is open; "
        "missed work is checked on the next app start."
    )

    schedules = scheduler.schedules()
    with st.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="distribute",
    ):
        st.subheader("Scheduled jobs")
        run_due_jobs = st.button(
            "Run all due jobs",
            key="run_all_due_jobs",
            icon=":material/playlist_play:",
            help="Queue every enabled schedule that is due now.",
        )
    if run_due_jobs:
        count = scheduler.enqueue_due()
        if count:
            st.success(f"Queued {count} due job(s).")
        else:
            st.info("No scheduled jobs are due.")

    for schedule in schedules:
        job_id = str(schedule["job_id"])
        left, middle, right = st.columns([3, 2, 2])
        left.markdown(f"**{schedule['name']}**")
        left.caption(schedule["description"])
        middle.caption(
            f"Weekdays at {int(schedule['run_hour']):02d}:{int(schedule['run_minute']):02d} "
            f"· {schedule['timezone']}"
        )
        next_due = datetime.fromisoformat(str(schedule["next_run_at"])).astimezone(
            ZoneInfo(str(schedule["timezone"]))
        )
        middle.caption(f"Next due: {next_due:%Y-%m-%d %H:%M %Z}")
        enabled = right.checkbox(
            "Enabled",
            value=bool(schedule["enabled"]),
            key=f"scheduler_enabled_{job_id}",
        )
        if enabled != bool(schedule["enabled"]):
            scheduler.set_enabled(job_id, enabled)
            st.rerun()

    st.caption(
        "Corporate-action refresh stages review candidates; it never approves actions."
    )

    st.subheader("Recent runs")
    occurrences = scheduler.occurrences()
    if not occurrences:
        st.info("No scheduled runs yet.")
        return
    display = [
        {
            "Job": row["job_name"],
            "Trigger": row["trigger_type"],
            "Status": row["status"],
            "Scheduled for": row["scheduled_for"],
            "Started": row["started_at"] or "",
            "Completed": row["completed_at"] or "",
            "Result": row["result_summary"] or "",
            "Error": row["error_summary"] or "",
        }
        for row in occurrences
    ]
    st.dataframe(display, hide_index=True, alt="Recent scheduled and manual job runs")
    for row in occurrences:
        if row["status"] == "failed":
            with st.expander(f"Failed: {row['job_name']} · {row['completed_at'] or row['created_at']}"):
                st.code(str(row["error_summary"] or "No error detail recorded."))
                if st.button("Retry this run", key=f"retry_{row['occurrence_id']}"):
                    scheduler.retry(str(row["occurrence_id"]))
                    st.rerun()


st.title("NSE Strategy Lab")
st.caption("Local-first research workspace for daily NSE equity strategies")
scheduler = get_local_scheduler(str(DATA_DIR), str(SCHEDULE_CONFIG))

with st.sidebar:
    st.selectbox(
        "Workspace",
        ["Price explorer", "Strategy backtest", "Schedulers"],
        key="workspace",
    )

if st.session_state.workspace == "Price explorer":
    show_price_explorer()
elif st.session_state.workspace == "Strategy backtest":
    show_backtest()
else:
    show_schedulers(scheduler)
