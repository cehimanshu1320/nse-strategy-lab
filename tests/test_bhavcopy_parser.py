from __future__ import annotations

from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest

from nse_strategy_lab.ingestion.parsers.bhavcopy import parse_bhavcopy


def zipped_csv(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("bhavcopy.csv", frame.to_csv(index=False))
    return buffer.getvalue()


@pytest.mark.parametrize("format_name", ["legacy", "udiff"])
def test_parser_preserves_eq_and_be_but_excludes_other_series(format_name: str) -> None:
    if format_name == "legacy":
        frame = pd.DataFrame(
            {
                "SYMBOL": ["JIOFIN", "RELIANCE", "OTHER"],
                "SERIES": ["BE", "EQ", "BL"],
                "OPEN": [250.0, 2900.0, 10.0],
                "HIGH": [260.0, 2950.0, 11.0],
                "LOW": [240.0, 2890.0, 9.0],
                "CLOSE": [255.0, 2940.0, 10.5],
                "TOTTRDQTY": [100, 200, 300],
                "TIMESTAMP": ["2023-08-21"] * 3,
            }
        )
        trade_date = date(2023, 8, 21)
    else:
        frame = pd.DataFrame(
            {
                "TradDt": ["2024-07-08"] * 3,
                "TckrSymb": ["JIOFIN", "RELIANCE", "OTHER"],
                "SctySrs": ["BE", "EQ", "BL"],
                "SctySgmt": ["CM"] * 3,
                "FinInstrmTp": ["STK"] * 3,
                "OpnPric": [250.0, 2900.0, 10.0],
                "HghPric": [260.0, 2950.0, 11.0],
                "LwPric": [240.0, 2890.0, 9.0],
                "ClsPric": [255.0, 2940.0, 10.5],
                "TtlTradgVol": [100, 200, 300],
            }
        )
        trade_date = date(2024, 7, 8)

    prices = parse_bhavcopy(zipped_csv(frame), trade_date, "test-source")

    assert list(zip(prices["symbol"], prices["series"], strict=True)) == [
        ("JIOFIN", "BE"),
        ("RELIANCE", "EQ"),
    ]
