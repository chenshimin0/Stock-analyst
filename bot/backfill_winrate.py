"""Backfill WinRate rows for all reports.

Re-runs WinRateService.calculate_win_rates for each report so the cached
table gets populated. Safe to run multiple times — idempotent: existing
WinRate rows with is_win IS NOT NULL are returned from cache, otherwise
the live Tencent K-line fetch runs and writes a fresh row.

Usage:
    python3 -m bot.backfill_winrate [--report-ids 1,2,3] [--dry-run]

Run from project root with the venv active:
    cd /home/ubuntu/stock-analysis-system
    sudo backend/venv/bin/python3 -m bot.backfill_winrate
"""
import argparse
import asyncio
import sys
import time
from datetime import date
from pathlib import Path

# Path setup: allow backend.app.* imports when run as a script
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "bot"))

from app.database import SessionLocal  # noqa: E402
from app.models import Report, WinRate  # noqa: E402
from app.config import WIN_RATE_PERIODS  # noqa: E402
from app.services.winrate_service import WinRateService  # noqa: E402


async def backfill_one(report_id: int, db) -> dict:
    """Recompute winrate for a single report. Returns a summary dict."""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        return {"id": report_id, "error": "report not found"}
    today = date.today()
    expected_periods = WIN_RATE_PERIODS  # [7, 15, 30, 90, 180]
    target_dates = {
        p: report.report_date + __import__("datetime").timedelta(days=p)
        for p in expected_periods
    }
    # We re-run calculate_win_rates (it now checks target_date <= today
    # and fetches live K-line via Tencent).  Existing WinRate rows whose
    # is_win IS NOT NULL are short-circuited (returned from cache).
    # We force a full recompute by clearing them first.
    db.query(WinRate).filter(WinRate.report_id == report_id).delete()
    db.commit()
    try:
        periods = await WinRateService.calculate_win_rates(db, report_id)
    except Exception as e:
        return {"id": report_id, "stock": report.stock_code, "error": str(e)}
    # Summarize: which periods got values, which are still null
    out = {
        "id": report_id,
        "stock": report.stock_code,
        "name": report.stock_name,
        "report_date": str(report.report_date),
        "today": str(today),
        "results": {},
    }
    for p in periods:
        out["results"][p["period_days"]] = {
            "target": str(p["target_date"]),
            "change_pct": p["change_pct"],
            "is_win": p["is_win"],
        }
    return out


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-ids", help="comma-separated ids; default: all reports")
    parser.add_argument("--dry-run", action="store_true", help="print plan but don't write")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between reports")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.report_ids:
            ids = [int(x) for x in args.report_ids.split(",")]
            reports = db.query(Report).filter(Report.id.in_(ids)).all()
        else:
            reports = db.query(Report).order_by(Report.id.asc()).all()
        print(f"Backfilling {len(reports)} reports "
              f"({'DRY RUN' if args.dry_run else 'LIVE'})", flush=True)

        success = 0
        failed = 0
        for r in reports:
            if args.dry_run:
                print(f"  [skip] would backfill id={r.id} {r.stock_code} {r.stock_name}")
                continue
            t0 = time.time()
            result = await backfill_one(r.id, db)
            elapsed = time.time() - t0
            # Compact output: show id, stock, and per-period change_pct
            pcts = " ".join(
                f"{p}d:{result['results'].get(p, {}).get('change_pct')}"
                for p in [7, 15, 30, 90, 180]
            )
            err = result.get("error", "")
            print(
                f"  id={result['id']:>3} {result.get('stock', '?'):>6} "
                f"{result.get('name', '?')[:8]:>8} | {pcts} | {elapsed:.1f}s"
                f"{'  ERR=' + err if err else ''}",
                flush=True,
            )
            if err:
                failed += 1
            else:
                success += 1
            # Yield to event loop
            await asyncio.sleep(args.delay)
        print(f"\nDone. Success={success} Failed={failed}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
