from datetime import date

import pandas as pd
import pytest

from nse_strategy_lab.domain.corporate_actions import validate_corporate_actions
from nse_strategy_lab.domain.instruments import (
    TATA_MOTORS_CV,
    TATA_MOTORS_PV,
    attach_instrument_identity,
    source_symbols_for,
)
from nse_strategy_lab.engine import BacktestConfig, run_backtest
from nse_strategy_lab.services.adjustments import adjust_price_history
from nse_strategy_lab.services.prices import list_price_symbols, query_price_history
from nse_strategy_lab.storage.price_store import LocalPriceStore


DEMERGER = pd.DataFrame(
    [
        {
            "symbol": "TATAMOTORS",
            "series": "EQ",
            "action_type": "demerger",
            "announcement_date": date(2024, 8, 1),
            "ex_date": date(2025, 10, 14),
            "record_date": date(2025, 10, 14),
            "distributed_symbol": "TMCV",
            "distributed_series": "BE",
            "distribution_ratio": 1,
            "surviving_reference_price": 400,
            "distributed_reference_price": 260.75,
            "source_url": "https://nsearchives.nseindia.com/content/circulars/CMTR70614.pdf",
            "terms": "1:1 share distribution; exchange price-discovery references.",
        }
    ]
)


def test_tata_symbol_aliases_resolve_to_distinct_instruments() -> None:
    rows = pd.DataFrame(
        {
            "trade_date": ["2025-10-13", "2025-10-24", "2025-11-12"],
            "symbol": ["TATAMOTORS", "TMPV", "TMCV"],
        }
    )

    identified = attach_instrument_identity(
        rows, date_column="trade_date", canonical_symbol=True
    )

    assert identified["instrument_id"].tolist() == [
        TATA_MOTORS_PV,
        TATA_MOTORS_PV,
        TATA_MOTORS_CV,
    ]
    assert identified["symbol"].tolist() == ["TMPV", "TMPV", "TMCV"]
    assert identified["source_symbol"].tolist() == ["TATAMOTORS", "TMPV", "TMCV"]
    assert source_symbols_for("TMPV") == ("TATAMOTORS", "TMPV")
    assert source_symbols_for("TMCV") == ("TMCV",)


def test_demerger_validation_requires_separate_security_and_reference_prices() -> None:
    normalized = validate_corporate_actions(DEMERGER)
    assert normalized.loc[0, "distribution_ratio"] == 1

    invalid = DEMERGER.copy()
    invalid.loc[0, "distributed_symbol"] = "TATAMOTORS"
    with pytest.raises(ValueError, match="separate security"):
        validate_corporate_actions(invalid)


def test_demerger_adjusts_only_pre_event_parent_prices_to_survivor_reference() -> None:
    bars = pd.DataFrame(
        {
            "trade_date": ["2025-10-10", "2025-10-13", "2025-10-14", "2025-10-15"],
            "symbol": ["TATAMOTORS"] * 4,
            "series": ["EQ"] * 4,
            "open": [684.8, 679.0, 400.0, 403.0],
            "high": [688.6, 679.4, 421.55, 403.0],
            "low": [666.9, 658.1, 376.3, 388.0],
            "close": [678.95, 660.75, 395.45, 390.85],
            "volume": [100, 200, 300, 400],
        }
    )

    adjusted = adjust_price_history(bars, DEMERGER, as_of_date=date(2025, 10, 14))
    before_ex_date = adjust_price_history(
        bars, DEMERGER, as_of_date=date(2025, 10, 13)
    )

    assert before_ex_date.loc[1, "close_adjusted"] == pytest.approx(660.75)
    assert adjusted.loc[1, "close_adjusted"] == pytest.approx(400)
    assert adjusted.loc[0, "close_adjusted"] == pytest.approx(
        678.95 * 400 / 660.75
    )
    assert adjusted.loc[2, "close_adjusted"] == pytest.approx(395.45)
    assert adjusted.loc[1, "volume_adjusted"] == 200


def test_backtest_distributes_child_shares_and_allocates_original_cost_basis() -> None:
    bars = pd.DataFrame(
        [
            ("2025-10-10", "TATAMOTORS", "EQ", 660.75, 660.75),
            ("2025-10-13", "TATAMOTORS", "EQ", 660.75, 660.75),
            ("2025-10-14", "TATAMOTORS", "EQ", 400.0, 400.0),
            ("2025-10-15", "TATAMOTORS", "EQ", 400.0, 400.0),
            ("2025-11-12", "TMCV", "BE", 329.45, 329.45),
        ],
        columns=["date", "symbol", "series", "open", "close"],
    )
    signals = pd.DataFrame(
        [
            ("2025-10-10", "TATAMOTORS", True, False),
            ("2025-10-13", "TMPV", False, False),
            ("2025-10-14", "TMPV", False, True),
            ("2025-11-12", "TMCV", False, False),
        ],
        columns=["date", "symbol", "entry", "exit"],
    )

    result = run_backtest(
        bars,
        signals,
        BacktestConfig(initial_cash=660.75, fee_rate=0, slippage_bps=0),
        corporate_actions=DEMERGER,
    )

    event_equity = result.equity_curve.loc[pd.Timestamp("2025-10-14"), "equity"]
    assert event_equity == pytest.approx(660.75)
    assert len(result.trades) == 1
    assert result.trades.loc[0, "symbol"] == "TMPV"
    child = result.open_positions.set_index("symbol").loc["TMCV"]
    assert child["quantity"] == 1
    assert child["last_close"] == pytest.approx(329.45)
    assert child["entry_cost"] == pytest.approx(260.75)


def test_price_query_joins_parent_tickers_but_keeps_child_separate(tmp_path) -> None:
    store = LocalPriceStore(tmp_path)
    prices = pd.DataFrame(
        [
            ("2025-10-13", "TATAMOTORS", "EQ", 679.0, 679.4, 658.1, 660.75, 200),
            ("2025-10-14", "TATAMOTORS", "EQ", 400.0, 421.55, 376.3, 395.45, 300),
            ("2025-10-24", "TMPV", "EQ", 406.95, 408.5, 401.0, 403.3, 400),
            ("2025-11-12", "TMCV", "BE", 335.0, 345.0, 320.0, 329.45, 500),
        ],
        columns=["trade_date", "symbol", "series", "open", "high", "low", "close", "volume"],
    )
    prices["turnover"] = None
    prices["trade_count"] = None
    prices["source_file_id"] = "fixture"
    store.upsert_prices(prices)
    store.upsert_corporate_actions(DEMERGER)

    tmpv = query_price_history(
        "TMPV", date(2025, 10, 13), date(2025, 10, 24), basis="adjusted", data_dir=tmp_path
    )
    tmcv = query_price_history(
        "TMCV", date(2025, 11, 12), date(2025, 11, 12), basis="raw", data_dir=tmp_path
    )

    assert tmpv["source_symbol"].tolist() == ["TATAMOTORS", "TATAMOTORS", "TMPV"]
    assert tmpv["symbol"].eq("TMPV").all()
    assert tmpv.loc[tmpv["trade_date"] == date(2025, 10, 13), "close_adjusted"].iloc[0] == pytest.approx(400)
    assert tmcv["source_symbol"].tolist() == ["TMCV"]
    assert tmcv["symbol"].tolist() == ["TMCV"]
    assert list_price_symbols(tmp_path) == ["TMCV", "TMPV"]
