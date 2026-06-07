"""
Sector pick scheduler. Runs at 20:00 each day.
For each in_progress / completed pick, fills T+5/10/20 prices from K-line.
Marks pick as 'completed' when all 3 milestones are filled.
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Path setup so 'app' and 'sector_*' modules resolve
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.sector_pick import SectorPick, SectorPickStock  # noqa: E402
from sector_tracker import get_t_n_data_for_stock, is_trading_day_today  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sector-scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger("sector_scheduler")


def run_daily_tracking() -> None:
    """Top-level job: process all active picks for today."""
    if not is_trading_day_today():
        logger.info("Not a trading day, skip.")
        return
    db: Session = SessionLocal()
    try:
        picks = (
            db.query(SectorPick)
            .filter(SectorPick.status.in_(["in_progress", "completed"]))
            .order_by(SectorPick.id)
            .all()
        )
        logger.info(f"Processing {len(picks)} active picks")
        for pick in picks:
            process_pick(db, pick)
    finally:
        db.close()


def process_pick(db: Session, pick: SectorPick) -> None:
    all_done = True
    for stock in pick.stocks:
        if stock.t5_pct is not None and stock.t10_pct is not None and stock.t20_pct is not None:
            continue  # already filled
        data = get_t_n_data_for_stock(
            stock.stock_code, pick.created_at.date(), stock.t0_price or 0
        )
        for key, val in data.items():
            setattr(stock, key, val)
        if not all([stock.t5_pct, stock.t10_pct, stock.t20_pct]):
            all_done = False
    if all_done and pick.status == "in_progress":
        pick.status = "completed"
        pick.completed_at = datetime.utcnow()
        logger.info(f"Pick {pick.id} ({pick.sector_name}) marked completed")
    db.commit()


def main() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_daily_tracking,
        CronTrigger(hour=20, minute=0, timezone="Asia/Shanghai"),
        id="sector_daily",
        replace_existing=True,
    )
    logger.info("Scheduler started; will run at 20:00 Asia/Shanghai daily.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
