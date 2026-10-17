"""Import and stage an NSE corporate-actions CSV export."""

from datetime import date, datetime, timedelta
from pathlib import Path

from nse_strategy_lab.ingestion.parsers.corporate_actions import (
    NSE_ACTIONS_URL,
    parse_nse_action_export,
)
from nse_strategy_lab.ingestion.sources.nse.corporate_actions_client import (
    NseCorporateActionsClient,
)
from nse_strategy_lab.storage.price_store import LocalPriceStore


def stage_nse_action_export(
    path: Path | str,
    *,
    data_dir: Path | str = Path("data"),
    source_url: str = NSE_ACTIONS_URL,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
) -> dict[str, object]:
    """Archive a source export, parse it, and stage every row for review.

    The operation never promotes rows into the corporate-action ledger. A
    parser failure is recorded against the preserved source file for audit.
    """
    csv_path = Path(path)
    return stage_nse_action_export_bytes(
        csv_path.read_bytes(),
        filename=csv_path.name,
        data_dir=data_dir,
        source_url=source_url,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )


def stage_nse_action_export_bytes(
    contents: bytes,
    *,
    filename: str,
    data_dir: Path | str = Path("data"),
    source_url: str = NSE_ACTIONS_URL,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
) -> dict[str, object]:
    """Archive and stage exact downloaded bytes without an inbox copy."""
    if (coverage_start is None) != (coverage_end is None):
        raise ValueError("Both coverage_start and coverage_end must be provided together.")
    if coverage_start and coverage_end and coverage_start > coverage_end:
        raise ValueError("coverage_start cannot be later than coverage_end.")
    store = LocalPriceStore(data_dir)
    raw_path, source_file_id, retrieved_at = store.save_action_export(
        contents,
        filename=filename,
        source_url=source_url,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    try:
        candidates = parse_nse_action_export(
            contents,
            source_file_id=source_file_id,
            source_url=source_url,
            source_filename=filename,
            imported_at=retrieved_at,
        )
        merge_result = store.merge_action_candidates(
            candidates,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )
        rows_staged = int(merge_result["rows_staged"])
    except Exception as exc:
        store.finish_action_export(
            source_file_id,
            status="parse_failed",
            error_summary=str(exc),
        )
        raise

    store.finish_action_export(
        source_file_id,
        status="staged_for_review",
        rows_staged=rows_staged,
    )
    if candidates.empty:
        review_path = (
            store.corporate_action_candidates_path.parent
            / f"review_{source_file_id[:16]}.csv"
        )
        candidates.to_csv(review_path, index=False)
        merge_result = {
            "new": 0,
            "changed": 0,
            "unchanged": 0,
            "missing": 0,
            "changes_path": review_path,
        }
    return {
        "source_file_id": source_file_id,
        "raw_path": raw_path,
        "review_path": merge_result["review_path"] if "review_path" in merge_result else review_path,
        "changes_path": merge_result["changes_path"],
        "source_rows": len(candidates),
        "rows_staged": rows_staged,
        "new_candidates": merge_result["new"],
        "changed_candidates": merge_result["changed"],
        "unchanged_candidates": merge_result["unchanged"],
        "missing_candidates": merge_result["missing"],
        "review_required": rows_staged,
    }


def stage_action_inbox(
    path: Path | str,
    *,
    data_dir: Path | str = Path("data"),
    source_url: str = NSE_ACTIONS_URL,
    coverage_start: date,
    coverage_end: date,
    max_age_hours: float = 96,
) -> dict[str, object]:
    """Stage a manually downloaded NSE CSV as a fallback to scheduled retrieval."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"No corporate-actions export found at {csv_path}. Download the NSE CSV "
            "and save it to the scheduled inbox before the next run."
        )
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive.")
    age = datetime.now().astimezone() - datetime.fromtimestamp(
        csv_path.stat().st_mtime
    ).astimezone()
    if age > timedelta(hours=max_age_hours):
        raise ValueError(
            f"Corporate-actions export is stale ({age.total_seconds() / 3600:.1f} hours old; "
            f"maximum {max_age_hours:g}). Replace {csv_path} with a fresh NSE export."
        )
    return stage_nse_action_export(
        csv_path,
        data_dir=data_dir,
        source_url=source_url,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )


def refresh_nse_action_export(
    *,
    data_dir: Path | str = Path("data"),
    coverage_start: date,
    coverage_end: date,
    client: NseCorporateActionsClient | None = None,
) -> dict[str, object]:
    """Download the rolling NSE page export, archive it, and stage candidates."""
    downloader = client or NseCorporateActionsClient()
    downloaded = downloader.download(coverage_start, coverage_end)
    return stage_nse_action_export_bytes(
        downloaded.content,
        filename=downloaded.filename,
        data_dir=data_dir,
        source_url=downloaded.url,
        coverage_start=downloaded.coverage_start,
        coverage_end=downloaded.coverage_end,
    )
