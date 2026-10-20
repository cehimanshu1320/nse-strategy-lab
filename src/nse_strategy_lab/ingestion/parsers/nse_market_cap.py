"""Parser for NSE's dated all-company average-market-cap workbook."""

from __future__ import annotations

import re
import zipfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"x": MAIN_NS}
EXPECTED_HEADERS = ("Rank", "Symbol", "Company Name")


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref)
    if not letters:
        raise ValueError(f"Invalid workbook cell reference: {cell_ref}")
    result = 0
    for letter in letters.group():
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall("x:si", NS)]


def _sheet_rows(archive: zipfile.ZipFile, shared: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", NS):
        cells: list[str] = []
        for cell in row.findall("x:c", NS):
            index = _column_index(cell.attrib["r"])
            while len(cells) <= index:
                cells.append("")
            value = cell.findtext("x:v", default="", namespaces=NS)
            if cell.attrib.get("t") == "s" and value:
                value = shared[int(value)]
            cells[index] = value.strip()
        rows.append(cells)
    return rows


def _period_from_header(header: str) -> tuple[date, date]:
    match = re.search(
        r"from\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+to\s+"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        header,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Could not read market-cap period from header: {header!r}")
    return tuple(datetime.strptime(value, "%B %d, %Y").date() for value in match.groups())  # type: ignore[return-value]


def parse_nse_average_market_cap_workbook(
    content: bytes,
    *,
    source_file_id: str,
    source_url: str,
    retrieved_at: str,
) -> pd.DataFrame:
    """Parse a verified NSE workbook; values are normalized from lakh to crore."""
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            shared = _read_shared_strings(archive)
            rows = _sheet_rows(archive, shared)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("Input is not a readable NSE market-cap XLSX workbook") from exc

    if not rows or len(rows[0]) < 4:
        raise ValueError("NSE market-cap workbook has no four-column header")
    headers = tuple(rows[0][:3])
    if headers != EXPECTED_HEADERS:
        raise ValueError(f"Unexpected NSE market-cap columns: {headers!r}")
    value_header = rows[0][3]
    if "average market capitalisation" not in value_header.lower() or "lakhs" not in value_header.lower():
        raise ValueError(f"Unsupported NSE market-cap measure or unit: {value_header!r}")
    period_start, period_end = _period_from_header(value_header)

    records: list[dict[str, object]] = []
    seen_symbols: set[str] = set()
    not_traded = 0
    for row_number, row in enumerate(rows[1:], start=2):
        if not row or not any(row):
            continue
        if len(row) >= 4 and row[0].strip().lower().startswith("note:") and not row[1]:
            continue
        if len(row) < 4 or not row[1]:
            raise ValueError(f"Incomplete NSE market-cap row {row_number}")
        symbol = row[1].strip().upper()
        if symbol in seen_symbols:
            raise ValueError(f"Duplicate NSE market-cap symbol {symbol} at row {row_number}")
        seen_symbols.add(symbol)
        try:
            rank = int(row[0])
        except ValueError as exc:
            raise ValueError(f"Invalid rank at row {row_number}") from exc
        if rank <= 0:
            raise ValueError(f"Non-positive rank at row {row_number}")
        if row[3].strip().lower() == "not traded during the period":
            not_traded += 1
            continue
        try:
            value_inr_lakh = float(row[3].replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"Invalid market-cap value at row {row_number}") from exc
        if value_inr_lakh <= 0:
            raise ValueError(f"Non-positive market-cap value at row {row_number}")
        records.append(
            {
                "observation_type": "average_period",
                "as_of_date": None,
                "period_start": period_start,
                "period_end": period_end,
                "symbol": symbol,
                "isin": None,
                "market_cap_inr_crore": value_inr_lakh / 100.0,
                "source_url": source_url,
                "source_file_id": source_file_id,
                "retrieved_at": retrieved_at,
            }
        )
    if not records:
        raise ValueError("NSE market-cap workbook contains no company observations")
    frame = pd.DataFrame.from_records(records)
    frame.attrs["not_traded_rows"] = not_traded
    return frame
