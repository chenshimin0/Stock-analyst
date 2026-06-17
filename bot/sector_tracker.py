"""
T+5/T+10/T+20 trading-day tracking for sector picks.
Pulls K-line from astock_data.get_kline and computes pct change vs t0.
"""
import logging
from datetime import date, datetime
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from astock_data import get_kline

logger = logging.getLogger(__name__)


def _kline_to_bars(raw: list) -> list:
    """
    Convert astock_data.get_kline dict output to (date_str, close, avg_price) tuples.

    astock_data.get_kline returns:
        [{"date": "YYYY-MM-DD", "open": ..., "high": ..., "low": ...,
          "close": ..., "volume": ...}, ...]

    avg_price is approximated as (open + high + low + close) / 4 — a typical
    proxy when true avg_price is not exposed by the upstream API.
    """
    bars = []
    for b in raw:
        date_str = b.get("date") or b.get("day")
        if not date_str:
            continue
        close = float(b.get("close", 0) or 0)
        if close <= 0:
            continue
        o = float(b.get("open", 0) or 0)
        h = float(b.get("high", 0) or 0)
        l = float(b.get("low", 0) or 0)
        avg_price = (o + h + l + close) / 4.0 if (o + h + l) > 0 else close
        bars.append((date_str[:10], close, round(avg_price, 4)))
    return bars


def find_trading_day_after(
    bars: list,
    base_date: date,
    n: int,
):
    """
    Given K-line bars (date_str, close, avg_price) sorted ascending,
    return the bar that is exactly N trading days AFTER base_date.
    Returns None if not enough data.
    """
    count = 0
    for bar in bars:
        d = datetime.strptime(bar[0], "%Y-%m-%d").date()
        if d > base_date:
            count += 1
            if count == n:
                return bar
    return None


def calc_t_n_metrics(t0_price, t_n_price) -> Optional[float]:
    """Compute (t_n - t0) / t0 * 100, rounded to 2 decimals. None on missing/zero t0."""
    if t0_price is None or t0_price <= 0 or t_n_price is None:
        return None
    return round((t_n_price - t0_price) / t0_price * 100, 2)


def is_trading_day_today() -> bool:
    """Heuristic: try to get today's K-line. If no data, not a trading day."""
    from astock_data import get_quote
    # Tencent quote works on every day; for actual trading-day check, use K-line
    try:
        bars = get_kline("000001", count=5)  # SSE index as proxy
        if not bars:
            return False
        today_str = date.today().strftime("%Y-%m-%d")
        return any((b.get("date") or b.get("day", ""))[:10] == today_str for b in bars)
    except Exception as e:
        logger.warning(f"is_trading_day_today check failed: {e}")
        return False


def get_t_n_data_for_stock(
    stock_code: str,
    t0_date: date,
    t0_price,
) -> dict:
    """
    Pull K-line and compute t5/t10/t20 metrics. Returns dict with keys
    t5_date, t5_price, t5_avg_price, t5_pct, t10_*, t20_* (all optional).
    """
    out = {}
    try:
        raw_bars = get_kline(stock_code, count=30)  # 30 trading days covers all 3 milestones
    except Exception as e:
        logger.warning(f"get_kline failed for {stock_code}: {e}")
        return out
    if not raw_bars:
        return out
    bars = _kline_to_bars(raw_bars)
    if not bars:
        return out
    for n in (3, 5, 10, 20):
        bar = find_trading_day_after(bars, t0_date, n)
        if not bar:
            continue
        t_date_str, t_close, t_avg = bar
        out[f"t{n}_date"] = date.fromisoformat(t_date_str)
        out[f"t{n}_price"] = t_close
        out[f"t{n}_avg_price"] = t_avg
        out[f"t{n}_pct"] = calc_t_n_metrics(t0_price, t_close)
    return out
