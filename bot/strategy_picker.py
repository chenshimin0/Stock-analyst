"""
Run the daily 14:30 iwencai strategy pick.

Steps:
  1. iwc_client.query(STRATEGY_QUERY) -> hit list (code, name, ...)
  2. For each hit, get realtime price from tencent_quote for t0_price
  3. For each hit, fetch industry / business_summary from 10jqka F10
  4. Create StrategyPick + bulk-insert StrategyPickStock
  5. Return summary dict

Safe to call manually for testing:
    sudo backend/venv/bin/python3 -m bot.strategy_picker
"""
import asyncio
import logging
import sys
from datetime import date as _date
from pathlib import Path

# Path setup: app.* and iwc_client both resolve
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models.strategy_pick import StrategyPick, StrategyPickStock  # noqa: E402
from iwc_client import IwcLoginError, IwcQueryError, STRATEGY_NAME, STRATEGY_QUERY, query  # noqa: E402

logger = logging.getLogger("strategy_picker")


def _get_realtime_price(code: str) -> float | None:
    """Real-time price from Tencent (used as t0_price at 14:30)."""
    try:
        from astock_data import get_quote
        q = get_quote(code)
        p = q.get("price", 0)
        return float(p) if p and p > 0 else None
    except Exception as e:
        logger.warning(f"get_quote({code}) failed: {e}")
        return None


def _get_industry_business(code: str) -> dict:
    """Industry + business from 10jqka F10. Best-effort; empty dict on failure."""
    try:
        from astock_data_10jqka import get_industry_business
        return get_industry_business(code)
    except Exception as e:
        logger.warning(f"get_industry_business({code}) failed: {e}")
        return {}


def run_strategy() -> dict:
    """One-shot run. Returns:
       {ok, batch_id, hit_count, errors, message}
    """
    today = _date.today()
    db = SessionLocal()
    result = {
        "ok": False,
        "batch_id": None,
        "hit_count": 0,
        "errors": [],
        "message": "",
    }
    try:
        # 1) Query iwencai
        try:
            rows = query(STRATEGY_QUERY, perpage=50)
        except IwcLoginError as e:
            result["message"] = f"Cookie 问题: {e}"
            result["errors"].append(str(e))
            logger.error(result["message"])
            return result
        except IwcQueryError as e:
            result["message"] = f"iwencai 查询失败: {e}"
            result["errors"].append(str(e))
            logger.error(result["message"])
            return result

        if not rows:
            result["ok"] = True
            result["message"] = "iwencai 今日返回 0 条，不创建 batch"
            logger.info(result["message"])
            return result

        # 2) Build StrategyPick header
        pick = StrategyPick(
            strategy_name=STRATEGY_NAME,
            query_text=STRATEGY_QUERY,
            status="in_progress",
            hit_count=len(rows),
            created_at=today,
        )
        db.add(pick)
        db.flush()  # get pick.id

        # 3) Per-stock enrichment
        for r in rows:
            code = (r.get("code") or "").strip()
            name = (r.get("name") or r.get("stock_name") or "").strip()
            if not code or not name:
                continue
            # Try multiple name keys (response field name varies)
            name = r.get("name") or name
            t0_price = _get_realtime_price(code)
            ind_biz = _get_industry_business(code)
            db.add(StrategyPickStock(
                strategy_pick_id=pick.id,
                stock_code=code,
                stock_name=name,
                industry=ind_biz.get("industry"),
                business_summary=ind_biz.get("business_summary"),
                selection_reason=None,  # iwencai doesn't return per-row reason
                t0_date=today,
                t0_price=t0_price,
            ))
        db.commit()

        result["ok"] = True
        result["batch_id"] = pick.id
        result["hit_count"] = len(rows)
        result["message"] = f"已创建 batch {pick.id}，命中 {len(rows)} 只"
        logger.info(result["message"])
        return result
    except Exception as e:
        db.rollback()
        result["errors"].append(f"unexpected: {e}")
        result["message"] = f"未预期错误: {e}"
        logger.exception("run_strategy failed")
        return result
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [strategy-picker] %(levelname)s %(message)s")
    out = run_strategy()
    print()
    print("Result:")
    for k, v in out.items():
        print(f"  {k}: {v}")
    sys.exit(0 if out["ok"] else 1)
