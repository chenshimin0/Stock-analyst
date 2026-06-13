"""
Run the iwencai strategy pick per strategy definition.

Two entry points:
  run_one_strategy(strategy_id) -> dict  : single strategy, sync
  run_all_enabled()             -> list  : all enabled strategies (called by scheduler)

Returns dict {ok, batch_id, hit_count, errors, message}.
"""
import logging
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Strategy, StrategyPick, StrategyPickStock  # noqa: E402
from iwc_client import IwcLoginError, IwcQueryError, query  # noqa: E402

logger = logging.getLogger("strategy_picker")


def _get_realtime_price(code: str) -> float | None:
    try:
        from astock_data import get_quote
        q = get_quote(code)
        p = q.get("price", 0)
        return float(p) if p and p > 0 else None
    except Exception as e:
        logger.warning(f"get_quote({code}) failed: {e}")
        return None


def _get_industry_business(code: str) -> dict:
    try:
        from astock_data_10jqka import get_industry_business
        return get_industry_business(code)
    except Exception as e:
        logger.warning(f"get_industry_business({code}) failed: {e}")
        return {}


def _pick_for(strategy: Strategy, db) -> dict:
    """One strategy: query, build batch, return result dict. Caller commits."""
    today = _date.today()
    out = {
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "ok": False,
        "batch_id": None,
        "hit_count": 0,
        "errors": [],
        "message": "",
    }
    try:
        rows = query(strategy.query_text, perpage=50)
    except IwcLoginError as e:
        out["message"] = f"Cookie 问题: {e}"
        out["errors"].append(str(e))
        logger.error(f"[{strategy.name}] {out['message']}")
        return out
    except IwcQueryError as e:
        out["message"] = f"iwencai 查询失败: {e}"
        out["errors"].append(str(e))
        logger.error(f"[{strategy.name}] {out['message']}")
        return out

    if not rows:
        out["ok"] = True
        out["message"] = "iwencai 今日返回 0 条"
        logger.info(f"[{strategy.name}] {out['message']}")
        return out

    pick = StrategyPick(
        strategy_id=strategy.id,
        status="in_progress",
        hit_count=len(rows),
        created_at=today,
    )
    db.add(pick)
    db.flush()

    for r in rows:
        code = (r.get("code") or "").strip()
        name = (r.get("name") or r.get("stock_name") or "").strip()
        if not code or not name:
            continue
        t0_price = _get_realtime_price(code)
        ind_biz = _get_industry_business(code)
        db.add(StrategyPickStock(
            strategy_pick_id=pick.id,
            stock_code=code,
            stock_name=name,
            industry=ind_biz.get("industry"),
            business_summary=ind_biz.get("business_summary"),
            selection_reason=None,
            t0_date=today,
            t0_price=t0_price,
        ))
    db.commit()

    out["ok"] = True
    out["batch_id"] = pick.id
    out["hit_count"] = len(rows)
    out["message"] = f"已创建 batch {pick.id}，命中 {len(rows)} 只"
    logger.info(f"[{strategy.name}] {out['message']}")
    return out


def run_one_strategy(strategy_id: int) -> dict:
    db = SessionLocal()
    try:
        s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not s:
            return {"ok": False, "message": f"Strategy {strategy_id} not found",
                    "errors": ["not found"], "batch_id": None, "hit_count": 0}
        return _pick_for(s, db)
    except Exception as e:
        db.rollback()
        logger.exception(f"run_one_strategy({strategy_id}) crashed")
        return {"ok": False, "message": f"未预期错误: {e}",
                "errors": [str(e)], "batch_id": None, "hit_count": 0}
    finally:
        db.close()


def run_all_enabled() -> list[dict]:
    """Run all enabled strategies sequentially. Used by scheduler + manual batch."""
    db = SessionLocal()
    results = []
    try:
        enabled = db.query(Strategy).filter(Strategy.enabled == True).all()
        for s in enabled:
            results.append(_pick_for(s, db))
    finally:
        db.close()
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [strategy-picker] %(levelname)s %(message)s")
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", help="run all enabled strategies")
    p.add_argument("--id", type=int, help="run one strategy by id")
    args = p.parse_args()
    if args.id:
        out = run_one_strategy(args.id)
        for k, v in out.items():
            print(f"  {k}: {v}")
        sys.exit(0 if out["ok"] else 1)
    if args.all:
        outs = run_all_enabled()
        for o in outs:
            print(f"  [{o.get('strategy_name')}] ok={o['ok']} batch={o.get('batch_id')} hits={o.get('hit_count')}")
        sys.exit(0)
    # default: all enabled
    outs = run_all_enabled()
    for o in outs:
        print(f"  [{o.get('strategy_name')}] ok={o['ok']} batch={o.get('batch_id')} hits={o.get('hit_count')}")
