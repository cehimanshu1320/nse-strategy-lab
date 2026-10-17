"""Parse NSE legacy and UDiFF cash-market bhavcopy ZIP files."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import pandas as pd

from nse_strategy_lab.domain.market_data import PRICE_COLUMNS


def _read_csv_from_zip(content: bytes) -> pd.DataFrame:
    try:
        with ZipFile(BytesIO(content)) as archive:
            csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(csv_names) != 1:
                raise ValueError(f"Expected one CSV in bhavcopy ZIP; found {len(csv_names)}")
            with archive.open(csv_names[0]) as csv_file:
                frame = pd.read_csv(csv_file)
                frame.columns = frame.columns.astype(str).str.strip()
                return frame
    except BadZipFile as exc:
        raise ValueError("NSE bhavcopy is not a valid ZIP file") from exc


def _legacy_prices(frame: pd.DataFrame, trade_date: date, source_file_id: str) -> pd.DataFrame:
    required = {"SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Legacy bhavcopy is missing columns: {sorted(missing)}")

    timestamp = frame["TIMESTAMP"] if "TIMESTAMP" in frame.columns else pd.Series(
        [trade_date] * len(frame), index=frame.index
    )
    result = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(timestamp, errors="coerce"),
            "symbol": frame["SYMBOL"].astype("string").str.strip().str.upper(),
            "series": frame["SERIES"].astype("string").str.strip().str.upper(),
            "open": frame["OPEN"],
            "high": frame["HIGH"],
            "low": frame["LOW"],
            "close": frame["CLOSE"],
            "volume": frame["TOTTRDQTY"],
            "turnover": frame.get("TOTTRDVAL"),
            "trade_count": frame.get("TOTALTRADES"),
            "source_file_id": source_file_id,
        }
    )
    result["trade_date"] = result["trade_date"].fillna(pd.Timestamp(trade_date)).dt.date
    result = result[result["series"] == "EQ"]
    return _coerce_and_validate(result, trade_date)


def _udiff_prices(frame: pd.DataFrame, trade_date: date, source_file_id: str) -> pd.DataFrame:
    required = {
        "TradDt",
        "TckrSymb",
        "SctySrs",
        "OpnPric",
        "HghPric",
        "LwPric",
        "ClsPric",
        "TtlTradgVol",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"UDiFF bhavcopy is missing columns: {sorted(missing)}")

    if "SctySgmt" in frame.columns:
        frame = frame[frame["SctySgmt"].astype("string").str.upper().isin(["CM", "E"])]
    if "FinInstrmTp" in frame.columns:
        frame = frame[frame["FinInstrmTp"].astype("string").str.upper().isin(["STK", "EQ"])]

    result = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(frame["TradDt"], errors="coerce"),
            "symbol": frame["TckrSymb"].astype("string").str.strip().str.upper(),
            "series": frame["SctySrs"].astype("string").str.strip().str.upper(),
            "open": frame["OpnPric"],
            "high": frame["HghPric"],
            "low": frame["LwPric"],
            "close": frame["ClsPric"],
            "volume": frame["TtlTradgVol"],
            "turnover": frame.get("TtlTrfVal"),
            "trade_count": frame.get("TtlNbOfTxsExctd"),
            "source_file_id": source_file_id,
        }
    )
    result["trade_date"] = result["trade_date"].fillna(pd.Timestamp(trade_date)).dt.date
    result = result[result["series"] == "EQ"]
    return _coerce_and_validate(result, trade_date)


def _coerce_and_validate(frame: pd.DataFrame, expected_date: date) -> pd.DataFrame:
    frame = frame[PRICE_COLUMNS].copy()
    numeric = ["open", "high", "low", "close", "volume", "turnover", "trade_count"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["volume"] = frame["volume"].fillna(0).astype("int64")
    frame["trade_count"] = frame["trade_count"].astype("Int64")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date

    if frame.empty:
        raise ValueError(f"No EQ-series rows found in bhavcopy for {expected_date}")
    if frame["symbol"].isna().any() or frame["symbol"].eq("").any():
        raise ValueError("Bhavcopy contains an empty symbol")
    if frame["trade_date"].ne(expected_date).any():
        raise ValueError(f"Bhavcopy trade date does not match requested date {expected_date}")
    if frame[PRICE_COLUMNS[:2]].isna().any().any():
        raise ValueError("Bhavcopy contains missing date/symbol keys")
    if frame.duplicated(["trade_date", "symbol", "series"]).any():
        raise ValueError("Bhavcopy contains duplicate date/symbol/series rows")
    if frame[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("Bhavcopy contains missing OHLC values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Bhavcopy contains non-positive OHLC values")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any():
        raise ValueError("Bhavcopy has low greater than open or close")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise ValueError("Bhavcopy has high less than open or close")
    if (frame["volume"] < 0).any():
        raise ValueError("Bhavcopy has negative volume")
    return frame.sort_values(["symbol", "series"]).reset_index(drop=True)


def parse_bhavcopy(content: bytes, trade_date: date, source_file_id: str) -> pd.DataFrame:
    frame = _read_csv_from_zip(content)
    if {"TradDt", "TckrSymb"}.issubset(frame.columns):
        return _udiff_prices(frame, trade_date, source_file_id)
    if {"SYMBOL", "SERIES"}.issubset(frame.columns):
        return _legacy_prices(frame, trade_date, source_file_id)
    raise ValueError(f"Unrecognized NSE bhavcopy columns: {list(frame.columns[:12])}")
