"""Effective-dated symbol identity for securities used by research workflows.

Market rows retain the exact NSE ticker in ``symbol``. These helpers add a
derived stable identity when multiple tickers refer to the same security over
time; they do not rewrite source records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


TATA_MOTORS_PV = "TATA_MOTORS_PV"
TATA_MOTORS_CV = "TATA_MOTORS_CV"


@dataclass(frozen=True)
class SymbolPeriod:
    symbol: str
    instrument_id: str
    valid_from: date
    valid_to: date | None
    current_symbol: str


SYMBOL_PERIODS = (
    SymbolPeriod(
        "TATAMOTORS", TATA_MOTORS_PV, date(1900, 1, 1), date(2025, 10, 23), "TMPV"
    ),
    SymbolPeriod("TMPV", TATA_MOTORS_PV, date(2025, 10, 24), None, "TMPV"),
    # TMLCV shares were issued to eligible holders on the 2025-10-14 record
    # date and began trading as TMCV on 2025-11-12.
    SymbolPeriod("TMCV", TATA_MOTORS_CV, date(2025, 10, 14), None, "TMCV"),
)


def symbol_period(symbol: str, on_date: date) -> SymbolPeriod | None:
    normalized = str(symbol).strip().upper()
    for period in SYMBOL_PERIODS:
        if period.symbol == normalized and period.valid_from <= on_date:
            if period.valid_to is None or on_date <= period.valid_to:
                return period
    return None


def instrument_id_for(symbol: str, on_date: date) -> str:
    normalized = str(symbol).strip().upper()
    # A strategy may label a historical bar with the company's current symbol
    # (TMPV) even though the source report used TATAMOTORS at that date.
    aliases = [period for period in SYMBOL_PERIODS if period.symbol == normalized]
    if aliases:
        return aliases[0].instrument_id
    period = symbol_period(normalized, on_date)
    return period.instrument_id if period else normalized


def current_symbol_for_instrument(instrument_id: str) -> str:
    for period in reversed(SYMBOL_PERIODS):
        if period.instrument_id == instrument_id:
            return period.current_symbol
    return instrument_id


def source_symbols_for(symbol: str) -> tuple[str, ...]:
    """Return ticker aliases belonging to the same security as ``symbol``."""
    normalized = str(symbol).strip().upper()
    matching = [period for period in SYMBOL_PERIODS if period.symbol == normalized]
    if not matching:
        return (normalized,)
    instrument_ids = {period.instrument_id for period in matching}
    return tuple(
        dict.fromkeys(
            period.symbol
            for period in SYMBOL_PERIODS
            if period.instrument_id in instrument_ids
        )
    )


def attach_instrument_identity(
    frame: pd.DataFrame,
    *,
    date_column: str,
    symbol_column: str = "symbol",
    canonical_symbol: bool = False,
) -> pd.DataFrame:
    """Add identity columns while retaining the source ticker separately.

    When ``canonical_symbol`` is true, ``symbol`` is set to the current ticker
    for that instrument. ``source_symbol`` always preserves the report ticker.
    Unknown companies use their NSE ticker as a stable local identity until a
    full instrument master is introduced.
    """
    result = frame.copy()
    if result.empty:
        if "source_symbol" not in result:
            result["source_symbol"] = pd.Series(dtype="string")
        result["instrument_id"] = pd.Series(dtype="string")
        return result

    dates = pd.to_datetime(result[date_column], errors="raise").dt.date
    source_symbols = result[symbol_column].astype(str).str.strip().str.upper()
    result["source_symbol"] = source_symbols
    identities: list[str] = []
    current_symbols: list[str] = []
    for source_symbol, on_date in zip(source_symbols, dates, strict=True):
        identity = instrument_id_for(source_symbol, on_date)
        current_symbols.append(
            current_symbol_for_instrument(identity)
            if identity != source_symbol
            else source_symbol
        )
        identities.append(identity)
    result["instrument_id"] = identities
    result["instrument_symbol"] = current_symbols
    if canonical_symbol:
        result[symbol_column] = current_symbols
    return result


def current_symbol_for_source(symbol: str) -> str:
    """Return the canonical current ticker for a known identity alias."""
    normalized = str(symbol).strip().upper()
    for period in SYMBOL_PERIODS:
        if period.symbol == normalized:
            return period.current_symbol
    return normalized
