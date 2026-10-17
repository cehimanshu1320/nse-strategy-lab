"""Parse NSE's corporate-actions CSV export into reviewable candidates.

The listing export is a discovery source, not an approved canonical ledger:
event terms can be abbreviated and the export does not provide every field
needed for backtest accounting. Candidates therefore always require review.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re

import pandas as pd


NSE_ACTIONS_URL = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
CANDIDATE_COLUMNS = [
    "candidate_id",
    "symbol",
    "company_name",
    "series",
    "purpose",
    "face_value",
    "ex_date",
    "record_date",
    "book_closure_start_date",
    "book_closure_end_date",
    "event_type_guess",
    "share_factor_guess",
    "cash_per_share_guess",
    "review_status",
    "review_notes",
    "discovery_status",
    "source_file_id",
    "source_url",
    "source_filename",
    "imported_at",
]


def _header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


_HEADER_ALIASES = {
    "symbol": "symbol",
    "companyname": "company_name",
    "company": "company_name",
    "series": "series",
    "purpose": "purpose",
    "facevalue": "face_value",
    "exdate": "ex_date",
    "recorddate": "record_date",
    "bookclosurestartdate": "book_closure_start_date",
    "bookclosureenddate": "book_closure_end_date",
}


def _text(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _date(value: object):
    if pd.isna(value) or not str(value).strip():
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.date()


def _classify_and_extract(purpose: str | None) -> tuple[str, float | None, float | None]:
    text = (purpose or "").strip()
    lowered = text.lower()

    bonus = re.search(r"bonus\s*(\d+)\s*[:/]\s*(\d+)", lowered)
    if bonus:
        new_shares, existing_shares = map(float, bonus.groups())
        factor = 1 + new_shares / existing_shares if existing_shares else None
        return "bonus", factor, None

    split = re.search(
        r"from\s*(?:rs\.?|re\.?)\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*"
        r"(?:per\s+share\s*)?to\s*(?:rs\.?|re\.?)\s*(\d+(?:\.\d+)?)",
        lowered,
    )
    if "split" in lowered or "sub-division" in lowered or "sub division" in lowered:
        if split and float(split.group(2)) > 0:
            return "split", float(split.group(1)) / float(split.group(2)), None
        return "split", None, None

    consolidation = re.search(
        r"from\s*(?:rs\.?|re\.?)\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*"
        r"(?:per\s+share\s*)?to\s*(?:rs\.?|re\.?)\s*(\d+(?:\.\d+)?)",
        lowered,
    )
    if "consolidat" in lowered:
        factor = None
        if consolidation and float(consolidation.group(2)) > 0:
            factor = float(consolidation.group(1)) / float(consolidation.group(2))
        return "consolidation", factor, None

    if "dividend" in lowered:
        amount = re.search(r"(?:rs\.?|re\.?)\s*(\d+(?:\.\d+)?)", lowered)
        return "dividend", None, float(amount.group(1)) if amount else None
    if "rights" in lowered:
        return "rights", None, None
    if any(word in lowered for word in ("merger", "amalgamation")):
        return "merger_or_amalgamation", None, None
    if any(word in lowered for word in ("demerger", "hive-off", "hive off", "spin-off", "spin off")):
        return "demerger_or_spin_off", None, None
    if "buyback" in lowered:
        return "buyback", None, None
    if "warrant" in lowered or "secured premium note" in lowered or "spn" in lowered:
        return "security_distribution_or_warrant", None, None
    return "other_or_unclassified", None, None


def parse_nse_action_export(
    contents: bytes,
    *,
    source_file_id: str,
    source_url: str,
    source_filename: str,
    imported_at: str,
) -> pd.DataFrame:
    """Return all rows as review-required candidates, preserving unknown types."""
    try:
        source = pd.read_csv(BytesIO(contents))
    except Exception as exc:
        raise ValueError(f"Could not read NSE corporate-actions CSV: {exc}") from exc
    if source.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)

    renamed = {}
    for column in source.columns:
        normalized = _HEADER_ALIASES.get(_header_key(column))
        if normalized:
            renamed[column] = normalized
    source = source.rename(columns=renamed)
    required = {"symbol", "purpose", "ex_date"}
    missing = required - set(source.columns)
    if missing:
        raise ValueError(
            "NSE action export is missing expected columns after header mapping: "
            + ", ".join(sorted(missing))
        )
    for column in (
        "company_name", "series", "face_value", "record_date",
        "book_closure_start_date", "book_closure_end_date",
    ):
        if column not in source:
            source[column] = None

    rows = []
    for _, source_row in source.iterrows():
        symbol = _text(source_row["symbol"])
        series = _text(source_row["series"])
        purpose = _text(source_row["purpose"])
        ex_date = _date(source_row["ex_date"])
        event_type, share_factor, cash_per_share = _classify_and_extract(purpose)
        record_date = _date(source_row["record_date"])
        stable_identity = "|".join(
            str(value or "")
            for value in (symbol, series, purpose, ex_date, record_date)
        )
        candidate_id = sha256(stable_identity.encode("utf-8")).hexdigest()
        notes = ["Verify event terms and announcement against the linked company filing."]
        if not symbol or not ex_date:
            notes.append("Symbol or ex-date is missing/invalid in the export row.")
        if event_type in {"split", "consolidation"} and share_factor is None:
            notes.append("Could not derive a share factor from the purpose text.")
        if event_type == "dividend" and cash_per_share is None:
            notes.append("Could not derive a dividend amount from the purpose text.")
        if event_type in {"rights", "merger_or_amalgamation", "demerger_or_spin_off"}:
            notes.append("Event type is staged for research only; adjustment is unsupported.")
        rows.append(
            {
                "candidate_id": candidate_id,
                "symbol": symbol.upper() if symbol else None,
                "company_name": _text(source_row["company_name"]),
                "series": series.upper() if series else None,
                "purpose": purpose,
                "face_value": _text(source_row["face_value"]),
                "ex_date": ex_date,
                "record_date": record_date,
                "book_closure_start_date": _date(source_row["book_closure_start_date"]),
                "book_closure_end_date": _date(source_row["book_closure_end_date"]),
                "event_type_guess": event_type,
                "share_factor_guess": share_factor,
                "cash_per_share_guess": cash_per_share,
                "review_status": "needs_review",
                "review_notes": " ".join(notes),
                "discovery_status": "pending_comparison",
                "source_file_id": source_file_id,
                "source_url": source_url,
                "source_filename": source_filename,
                "imported_at": imported_at,
            }
        )
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
