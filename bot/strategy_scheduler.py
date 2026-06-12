"""
Strategy scheduler.

- 14:30 weekdays: run_strategy() (iwenc pick)
- 20:00 weekdays: track_all_picks() (T+3/7/15/30 fill)

Mirrors bot/sector_scheduler.py structure.
"""
import logging
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from strategy_picker import run_strategy  # noqa: E402
from strategy_tracker import track_all_picks  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [strategy-scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger("strategy_scheduler")


def _safe_run_pick() -> None:
    try:
        result = run_strategy()
        logger.info(f"run_strategy -> {result}")
    except Exception as e:
        logger.error(f"run_strategy crashed: {e}\n{traceback.format_exc()}")


def _safe_run_track() -> None:
    try:
        result = track_all_picks()
        logger.info(f"track_all_picks -> {result}")
    except Exception as e:
        logger.error(f"track_all_picks crashed: {e}\n{traceback.format_exc()}")


def main() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    # Pick at 14:30 every weekday (Mon-Fri)
    scheduler.add_job(
        _safe_run_pick,
        CronTrigger(hour=14, minute=30, day_of_week="mon-fri",
                    timezone="Asia/Shanghai"),
        id="strategy_pick",
        replace_existing=True,
    )
    # Track at 20:00 every weekday (after A-share close)
    scheduler.add_job(
        _safe_run_track,
        CronTrigger(hour=20, minute=0, day_of_week="mon-fri",
                    timezone="Asia/Shanghai"),
        id="strategy_track",
        replace_existing=True,
    )
    logger.info("Scheduler started; pick=14:30, track=20:00 (Asia/Shanghai, Mon-Fri)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
