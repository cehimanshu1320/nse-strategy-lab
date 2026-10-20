"""Command-line interface for explicit NSE data imports."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from nse_strategy_lab.ingestion.jobs.bhavcopy_import import import_bhavcopy_range
from nse_strategy_lab.ingestion.jobs.corporate_action_import import (
    stage_action_inbox,
    stage_nse_action_export,
)
from nse_strategy_lab.ingestion.jobs.market_cap_import import (
    NSE_MARKET_CAP_WORKBOOK_URL,
    import_nse_market_cap_workbook,
)
from nse_strategy_lab.ingestion.parsers.corporate_actions import NSE_ACTIONS_URL
from nse_strategy_lab.services.refresh import (
    five_years_before,
    refresh_action_candidates,
    refresh_missing_prices,
)
from nse_strategy_lab.storage.price_store import LocalPriceStore


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must be YYYY-MM-DD") from exc


def _symbols(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {symbol.strip().upper() for symbol in value.split(",") if symbol.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(prog="nse-strategy-lab", description="Import NSE CM bhavcopy files")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser("backfill", help="download and import a date range")
    backfill.add_argument("--start", type=_date, default=None, help="YYYY-MM-DD (defaults to five years ago)")
    backfill.add_argument("--end", type=_date, default=date.today(), help="YYYY-MM-DD (defaults to today)")
    backfill.add_argument("--symbols", help="optional comma-separated NSE symbols")
    backfill.add_argument("--data-dir", type=Path, default=Path("data"))

    refresh = subparsers.add_parser("refresh", help="catch up imported data through today")
    refresh.add_argument("--from-date", type=_date, default=None, help="override the catalog's latest date")
    refresh.add_argument("--symbols", help="optional comma-separated NSE symbols")
    refresh.add_argument("--data-dir", type=Path, default=Path("data"))

    status = subparsers.add_parser("status", help="show local import status")
    status.add_argument("--data-dir", type=Path, default=Path("data"))

    actions = subparsers.add_parser("import-actions", help="import a reviewed corporate-actions CSV")
    actions.add_argument("csv", type=Path, help="CSV containing canonical corporate-action fields")
    actions.add_argument("--data-dir", type=Path, default=Path("data"))

    review_export = subparsers.add_parser(
        "export-action-review",
        help="create a verification worksheet for pending supported NSE candidates",
    )
    review_export.add_argument("--output", type=Path, required=True, help="review worksheet CSV output")
    review_export.add_argument("--symbols", help="optional comma-separated symbols to review")
    review_export.add_argument(
        "--types", nargs="+", choices=["bonus", "split", "dividend"],
        help="supported event types to include (defaults to all three)",
    )
    review_export.add_argument(
        "--all-pending", action="store_true",
        help="include all pending supported candidates, not only latest new/changed rows",
    )
    review_export.add_argument("--data-dir", type=Path, default=Path("data"))

    reviewed_actions = subparsers.add_parser(
        "import-reviewed-actions",
        help="promote only approved rows from a verification worksheet into the action ledger",
    )
    reviewed_actions.add_argument("csv", type=Path, help="completed action-review worksheet")
    reviewed_actions.add_argument("--data-dir", type=Path, default=Path("data"))

    action_export = subparsers.add_parser(
        "stage-nse-actions",
        help="archive and stage a downloaded NSE corporate-actions CSV for review",
    )
    action_export.add_argument("csv", type=Path, help="CSV downloaded from NSE Corporate Actions")
    action_export.add_argument(
        "--source-url",
        default=NSE_ACTIONS_URL,
        help="NSE page URL used for the export",
    )
    action_export.add_argument("--start-date", type=_date, help="inclusive export start date (YYYY-MM-DD)")
    action_export.add_argument("--end-date", type=_date, help="inclusive export end date (YYYY-MM-DD)")
    action_export.add_argument("--data-dir", type=Path, default=Path("data"))

    action_inbox = subparsers.add_parser(
        "stage-action-inbox",
        help="stage a fresh NSE export placed in the scheduled refresh inbox",
    )
    action_inbox.add_argument(
        "--csv",
        type=Path,
        default=Path("data/incoming/nse_corporate_actions.csv"),
        help="fresh NSE CSV copied to the scheduled-job inbox",
    )
    action_inbox.add_argument("--data-dir", type=Path, default=Path("data"))
    action_inbox.add_argument(
        "--max-age-hours", type=float, default=96,
        help="reject an export older than this many hours (default: 96)",
    )
    action_inbox.add_argument(
        "--start-date", type=_date,
        help="inclusive date range selected in NSE (default: five years ago)",
    )
    action_inbox.add_argument(
        "--end-date", type=_date,
        help="inclusive date range selected in NSE (default: one year ahead)",
    )
    action_inbox.add_argument(
        "--future-days", type=int, default=365,
        help="default export coverage beyond today (default: 365 days)",
    )

    action_refresh = subparsers.add_parser(
        "refresh-actions",
        help="download the rolling NSE Corporate Actions export and stage it for review",
    )
    action_refresh.add_argument(
        "--start-date", type=_date,
        help="inclusive export start date (default: five years ago)",
    )
    action_refresh.add_argument(
        "--end-date", type=_date,
        help="inclusive export end date (default: one year ahead)",
    )
    action_refresh.add_argument(
        "--future-days", type=int, default=365,
        help="default export coverage beyond today (default: 365 days)",
    )
    action_refresh.add_argument("--data-dir", type=Path, default=Path("data"))

    market_cap = subparsers.add_parser(
        "import-market-cap",
        help="archive and import an NSE all-company market-cap workbook",
    )
    market_cap.add_argument("workbook", type=Path, help="downloaded NSE XLSX workbook")
    market_cap.add_argument("--source-url", default=NSE_MARKET_CAP_WORKBOOK_URL)
    market_cap.add_argument("--data-dir", type=Path, default=Path("data"))

    args = parser.parse_args()
    if args.command == "import-market-cap":
        result = import_nse_market_cap_workbook(
            args.workbook,
            data_dir=args.data_dir,
            source_url=args.source_url,
        )
        print(
            f"Imported {result['rows_written']:,} NSE average market-cap observations "
            f"for {result['period_start']} to {result['period_end']}"
        )
        print(f"Excluded {result['not_traded_rows']:,} companies marked not traded in the source")
        print(f"Archived raw source: {result['raw_path']}")
        return

    if args.command == "status":
        store = LocalPriceStore(args.data_dir)
        print(f"Latest imported session: {store.latest_trade_date() or 'none'}")
        print(f"Catalog status: {store.import_status() or 'no imports yet'}")
        return

    if args.command == "import-actions":
        store = LocalPriceStore(args.data_dir)
        count = store.upsert_corporate_actions(pd.read_csv(args.csv))
        print(f"Imported or updated {count} corporate-action rows from {args.csv}")
        return

    if args.command == "export-action-review":
        store = LocalPriceStore(args.data_dir)
        output = store.create_action_review_template(
            args.output,
            symbols=_symbols(args.symbols),
            action_types=set(args.types) if args.types else None,
            include_existing=args.all_pending,
        )
        worksheet = pd.read_csv(output)
        print(f"Created review worksheet with {len(worksheet):,} candidates: {output}")
        print("Verify each row against its company filing; fill canonical fields and set review_status=approved.")
        return

    if args.command == "import-reviewed-actions":
        store = LocalPriceStore(args.data_dir)
        reviews = pd.read_csv(args.csv, keep_default_na=False)
        if "review_status" not in reviews:
            raise SystemExit("Review worksheet is missing review_status; no actions were imported.")
        reviews["review_status"] = reviews["review_status"].astype(str).str.strip().str.lower()
        approved_mask = reviews["review_status"].eq("approved")
        approved = reviews.loc[approved_mask].copy()
        if approved.empty:
            updated = store.update_action_candidate_reviews(reviews)
            print(f"No actions imported; recorded review decisions for {updated:,} candidates.")
            return
        if "source_url" not in approved or approved["source_url"].astype(str).str.strip().eq("").any():
            raise SystemExit("Every approved row needs its verified company-filing source_url.")
        count = store.upsert_corporate_actions(approved)
        store.update_action_candidate_reviews(reviews)
        pending_count = int((~approved_mask).sum())
        print(f"Imported or updated {count} approved corporate actions from {args.csv}")
        print(f"Left {pending_count:,} unapproved worksheet rows out of the adjustment ledger.")
        return

    if args.command == "stage-nse-actions":
        result = stage_nse_action_export(
            args.csv,
            data_dir=args.data_dir,
            source_url=args.source_url,
            coverage_start=args.start_date,
            coverage_end=args.end_date,
        )
        print(f"Archived export: {result['raw_path']}")
        print(
            f"Parsed {result['source_rows']:,} source rows; staged "
            f"{result['rows_staged']:,} unique candidates for review: {result['review_path']}"
        )
        print(
            f"Discovery changes: {result['new_candidates']:,} new, "
            f"{result['changed_candidates']:,} changed, "
            f"{result['unchanged_candidates']:,} unchanged, "
            f"{result['missing_candidates']:,} missing from this covered export. "
            f"Delta rows: {result['changes_path']}"
        )
        print("No rows were promoted to the adjusted-price action ledger.")
        return

    if args.command == "stage-action-inbox":
        if (args.start_date is None) != (args.end_date is None):
            raise SystemExit("Pass both --start-date and --end-date, or neither.")
        coverage_end = args.end_date or (date.today() + timedelta(days=args.future_days))
        coverage_start = args.start_date or five_years_before(date.today())
        result = stage_action_inbox(
            args.csv,
            data_dir=args.data_dir,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            max_age_hours=args.max_age_hours,
        )
        print(f"Archived export: {result['raw_path']}")
        print(
            f"Coverage {coverage_start} through {coverage_end}; parsed "
            f"{result['source_rows']:,} source rows and staged "
            f"{result['rows_staged']:,} unique candidates."
        )
        print(
            f"Discovery changes: {result['new_candidates']:,} new, "
            f"{result['changed_candidates']:,} changed, "
            f"{result['unchanged_candidates']:,} unchanged, "
            f"{result['missing_candidates']:,} missing from this covered export."
        )
        print(f"Review worksheet: {result['review_path']}")
        print(f"Delta rows: {result['changes_path']}")
        print("No rows were promoted to the adjusted-price action ledger.")
        return

    if args.command == "refresh-actions":
        if (args.start_date is None) != (args.end_date is None):
            raise SystemExit("Pass both --start-date and --end-date, or neither.")
        result = refresh_action_candidates(
            data_dir=args.data_dir,
            start=args.start_date,
            end=args.end_date,
            future_days=args.future_days,
        )
        print(f"Archived export: {result['raw_path']}")
        print(
            f"Coverage {result['coverage_start']} through {result['coverage_end']}; parsed "
            f"{result['source_rows']:,} source rows and staged "
            f"{result['rows_staged']:,} unique candidates."
        )
        print(
            f"Discovery changes: {result['new_candidates']:,} new, "
            f"{result['changed_candidates']:,} changed, "
            f"{result['unchanged_candidates']:,} unchanged, "
            f"{result['missing_candidates']:,} missing from this covered export."
        )
        print(f"Review worksheet: {result['review_path']}")
        print(f"Delta rows: {result['changes_path']}")
        print("No rows were promoted to the adjusted-price action ledger.")
        return

    if args.command == "refresh":
        result = refresh_missing_prices(
            data_dir=args.data_dir,
            from_date=args.from_date,
            today=date.today(),
        )
        print(result)
        if int(result.get("errors", 0)):
            raise SystemExit(1)
        return

    if args.command == "backfill":
        start = args.start or five_years_before(args.end)
        end = args.end
    else:
        raise SystemExit(f"Unsupported command: {args.command}")

    result = import_bhavcopy_range(
        start,
        end,
        data_dir=args.data_dir,
        symbols=_symbols(args.symbols),
    )
    print(result)
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
