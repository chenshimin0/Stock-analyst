"""
T+3 / T+7 / T+15 / T+30 tracking for strategy picks.

For each active StrategyPickStock:
  1. Pull K-line via astock_data.get_kline
  2. For each milestone n in {3, 7, 15, 30}, find the n-th trading day
     after t0_date and compute pct change vs t0_price
  3. Upsert back to the row (only fills None columns; doesn't overwrite)

When all stocks in a StrategyPick have t30_pct filled, mark the
StrategyPick as completed (and set completed_at).
"""
import logging
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models.strategy_pick import StrategyPick, StrategyPickStock  # noqa: E402
from sector_tracker import (  # noqa: E402
    find_trading_day_after, calc_t_n_metrics, is_trading_day_today,
    _kline_to_bars,
)

logger = logging.getLogger("strategy_tracker")

MILESTONES = (1, 3, 7, 15, 30)


def _get_kline(stock_code: str) -> list:
    """Get ~50 trading days of K-line as (date, close, avg) tuples."""
    try:
        from astock_data import get_kline
        return _kline_to_bars(get_kline(stock_code, count=50))
    except Exception as e:
        logger.warning(f"get_kline({stock_code}) failed: {e}")
        return []


def _fill_one_stock(db, stock: StrategyPickStock) -> int:
    """Fill any unfilled t_n columns for one stock. Returns # of fields filled."""
    if stock.t0_price is None or stock.t0_price <= 0:
        # Picker's t0_price must be set first; if missing skip
        return 0

    bars = _get_kline(stock.stock_code)
    if not bars:
        return 0

    t0_date = stock.t0_date
    filled = 0
    for n in MILESTONES:
        # Only fill if currently null
        if getattr(stock, f"t{n}_pct") is not None:
            continue
        bar = find_trading_day_after(bars, t0_date, n)
        if not bar:
            # Not enough trading days yet (n too far in future)
            continue
        bar_date_str, bar_close, _avg = bar
        bar_date = _date.fromisoformat(bar_date_str)
        # Only fill if bar date is in the past (don't speculate today's K-line)
        # Actually, fill as long as we have the bar (Tencent K-line includes
        # today once the day closes; until then the close is yesterday's)
        pct = calc_t_n_metrics(stock.t0_price, bar_close)
        setattr(stock, f"t{n}_date", bar_date)
        setattr(stock, f"t{n}_price", bar_close)
        setattr(stock, f"t{n}_pct", pct)
        filled += 1
    if filled:
        db.add(stock)
    return filled


def track_all_picks() -> dict:
    """Process all in_progress strategy picks. Returns summary."""
    if not is_trading_day_today():
        return {"skipped": True, "reason": "not a trading day"}

    db = SessionLocal()
    summary = {
        "skipped": False,
        "picks_processed": 0,
        "stocks_updated": 0,
        "fields_filled": 0,
        "picks_completed": 0,
        "errors": [],
    }
    try:
        picks = (
            db.query(StrategyPick)
            .filter(StrategyPick.status.in_(["in_progress", "completed"]))
            .all()
        )
        for pick in picks:
            summary["picks_processed"] += 1
            all_t30_done = True
            for stock in pick.stocks:
                if stock.t30_pct is not None:
                    continue
                try:
                    n = _fill_one_stock(db, stock)
                    summary["fields_filled"] += n
                    if n > 0:
                        summary["stocks_updated"] += 1
                except Exception as e:
                    summary["errors"].append(f"{stock.stock_code}: {e}")
                if stock.t30_pct is None:
                    all_t30_done = False
            if all_t30_done and pick.status == "in_progress":
                pick.status = "completed"
                from datetime import datetime
                pick.completed_at = datetime.utcnow()
                summary["picks_completed"] += 1
                logger.info(f"StrategyPick {pick.id} -> completed")
        db.commit()
        return summary
    except Exception as e:
        db.rollback()
        summary["errors"].append(f"unexpected: {e}")
        logger.exception("track_all_picks failed")
        return summary
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [strategy-tracker] %(levelname)s %(message)s")
    out = track_all_picks()
    print()
    for k, v in out.items():
        print(f"  {k}: {v}")
