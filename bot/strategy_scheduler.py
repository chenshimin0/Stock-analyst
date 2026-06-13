"""
Strategy scheduler (multi-strategy).

Reads enabled strategies from db on startup and every 10 min after.
Each strategy has its own cron (HH:MM, weekdays). Tracker job runs 20:00 daily.

To reload after adding/editing a strategy: just wait up to 10 min, or
restart the scheduler. (A future API endpoint could call reload() directly.)
"""
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Strategy  # noqa: E402
from strategy_picker import run_one_strategy, run_all_enabled  # noqa: E402
from strategy_tracker import track_all_picks  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [strategy-scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger("strategy_scheduler")


def _safe_pick_one(sid: int) -> None:
    try:
        r = run_one_strategy(sid)
        logger.info(f"strategy #{sid} pick -> ok={r['ok']} batch={r.get('batch_id')} hits={r.get('hit_count')}")
    except Exception as e:
        logger.error(f"strategy #{sid} pick crashed: {e}\n{traceback.format_exc()}")


def _safe_track() -> None:
    try:
        r = track_all_picks()
        logger.info(f"track_all_picks -> {r}")
    except Exception as e:
        logger.error(f"track_all_picks crashed: {e}\n{traceback.format_exc()}")


def _parse_cron(spec: str) -> tuple[int, int]:
    """Parse 'HH:MM' to (hour, minute). Default 14:30 on bad input."""
    try:
        h, m = spec.split(":", 1)
        return int(h), int(m)
    except Exception:
        return 14, 30


def reload_pick_jobs(scheduler: BlockingScheduler) -> int:
    """Sync scheduler jobs with db. Returns count of enabled strategies."""
    db = SessionLocal()
    try:
        enabled = db.query(Strategy).filter(Strategy.enabled == True).all()
    finally:
        db.close()

    # Remove all old pick jobs
    for job in scheduler.get_jobs():
        if job.id.startswith("strategy_pick_"):
            scheduler.remove_job(job.id)

    # Re-add
    for s in enabled:
        h, m = _parse_cron(s.schedule_cron)
        scheduler.add_job(
            _safe_pick_one,
            CronTrigger(hour=h, minute=m, day_of_week="mon-fri",
                        timezone="Asia/Shanghai"),
            args=[s.id],
            id=f"strategy_pick_{s.id}",
            replace_existing=True,
        )
        logger.info(f"  scheduled strategy {s.id} ({s.name}) at {h:02d}:{m:02d} weekdays")
    return len(enabled)


def main() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    reload_pick_jobs(scheduler)
    # Tracker runs once a day at 20:00 weekdays
    scheduler.add_job(
        _safe_track,
        CronTrigger(hour=20, minute=0, day_of_week="mon-fri",
                    timezone="Asia/Shanghai"),
        id="strategy_track",
        replace_existing=True,
    )
    # Reload pick jobs every 10 min so DB edits take effect without restart
    scheduler.add_job(
        lambda: reload_pick_jobs(scheduler),
        CronTrigger(minute="*/10", timezone="Asia/Shanghai"),
        id="strategy_reload",
        replace_existing=True,
    )
    logger.info("Scheduler started. Tracker=20:00 weekdays, reload=every 10 min.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
