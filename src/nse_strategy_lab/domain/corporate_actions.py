"""Canonical corporate-action event schema for the research prototype."""

from __future__ import annotations

ACTION_COLUMNS = [
    "symbol",
    "series",
    "action_type",
    "announcement_date",
    "ex_date",
    "record_date",
    "share_factor",
    "cash_per_share",
    "pay_date",
    "terms",
    "source_url",
    "source_file_id",
]

ACTION_KEY = ["symbol", "series", "action_type", "ex_date"]
SHARE_ACTIONS = {"bonus", "split"}
SUPPORTED_ACTIONS = SHARE_ACTIONS | {"dividend"}


def validate_corporate_actions(actions):
    """Return normalized actions or raise for malformed/unsupported events."""
    import pandas as pd

    if actions.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    required_columns = {
        "symbol",
        "series",
        "action_type",
        "announcement_date",
        "ex_date",
    }
    missing = required_columns - set(actions.columns)
    if missing:
        raise ValueError(f"Corporate actions are missing columns: {sorted(missing)}")

    result = actions.copy()
    for column in ACTION_COLUMNS:
        if column not in result:
            result[column] = None
    result = result[ACTION_COLUMNS]
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    result["series"] = result["series"].astype(str).str.strip().str.upper()
    result["action_type"] = result["action_type"].astype(str).str.strip().str.lower()
    if result[["symbol", "series"]].isin(["", "NAN", "NONE"]).any().any():
        raise ValueError("Corporate actions require a symbol and series.")
    unsupported = set(result["action_type"]) - SUPPORTED_ACTIONS
    if unsupported:
        raise ValueError(f"Unsupported corporate action types: {sorted(unsupported)}")

    for column in ("announcement_date", "ex_date", "record_date", "pay_date"):
        raw_values = result[column]
        parsed = pd.to_datetime(raw_values, errors="coerce")
        supplied = raw_values.notna() & raw_values.astype(str).str.strip().ne("")
        if (supplied & parsed.isna()).any():
            raise ValueError(f"Corporate actions contain an invalid {column}.")
        result[column] = parsed.dt.date
    if result["ex_date"].isna().any():
        raise ValueError("Corporate actions require a valid ex_date.")
    if result["announcement_date"].isna().any():
        raise ValueError("Corporate actions require a valid announcement_date.")
    source_values = result[["source_url", "source_file_id"]].fillna("").astype(str).apply(
        lambda column: column.str.strip()
    )
    if source_values.eq("").all(axis=1).any():
        raise ValueError("Corporate actions require a source_url or source_file_id.")

    result["share_factor"] = pd.to_numeric(result["share_factor"], errors="coerce")
    result["cash_per_share"] = pd.to_numeric(result["cash_per_share"], errors="coerce")
    for _, action in result.iterrows():
        if action["action_type"] in SHARE_ACTIONS:
            if pd.isna(action["share_factor"]) or action["share_factor"] <= 0:
                raise ValueError("Bonus/split actions require a positive share_factor.")
        elif action["action_type"] == "dividend":
            if pd.isna(action["cash_per_share"]) or action["cash_per_share"] < 0:
                raise ValueError("Dividend actions require a nonnegative cash_per_share.")
            if pd.isna(action["pay_date"]):
                raise ValueError("Dividend actions require a pay_date for portfolio accounting.")
            if action["pay_date"] < action["ex_date"]:
                raise ValueError("Dividend pay_date cannot precede its ex_date.")

    if result.duplicated(ACTION_KEY).any():
        raise ValueError("Corporate actions contain duplicate natural keys.")
    return result.sort_values(ACTION_KEY).reset_index(drop=True)
