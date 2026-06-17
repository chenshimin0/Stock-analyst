"""
Run the strategy pick per strategy definition.

Uses iwencai API (hexin-v token) as the primary screener.
Falls back to EastMoney screener if token is expired.

Two entry points:
  run_one_strategy(strategy_id) -> dict  : single strategy, sync
  run_all_enabled()             -> list  : all enabled strategies (called by scheduler)

Returns dict {ok, batch_id, hit_count, errors, message}.
"""
import logging
import sys
from datetime import datetime, date as _date, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Strategy, StrategyPick, StrategyPickStock  # noqa: E402

logger = logging.getLogger("strategy_picker")

HKT = timezone(timedelta(hours=8))


def _hkt_now() -> datetime:
    return datetime.now(HKT)

def _get_stock_code(row: dict) -> str:
    """Extract stock code from iwc or eastmoney row."""
    # iwc format: "股票代码": "603678.SH"
    code = (row.get("股票代码") or row.get("code") or "").strip()
    if "." in code:
        code = code.split(".")[0]
    return code


def _get_stock_name(row: dict) -> str:
    """iwc returns the stock name under various keys depending on
    query type. Try them in order of specificity.
    """
    for key in ("股票简称", "name", "stock_name", "简称"):
        v = row.get(key)
        if v and str(v).strip():
            return str(v).strip()
    return ""


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
    now = _hkt_now()
    out = {
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "ok": False,
        "batch_id": None,
        "hit_count": 0,
        "errors": [],
        "message": "",
    }

    # iwencai via pywencai (no token needed, handles anti-bot internally)
    try:
        import pywencai
        df = pywencai.get(
            query=strategy.query_text,
            sort_key='成交金额', sort_order='desc',
            loop=False,
        )
        if df is None or df.empty:
            out["ok"] = True
            out["message"] = "iwencai 今日返回 0 条"
            logger.info(f"[{strategy.name}] {out['message']}")
            return out
        # Convert DataFrame rows to dicts
        rows = []
        for _, row in df.iterrows():
            r = {}
            for col in df.columns:
                r[col] = row[col]
            rows.append(r)
        logger.info(f"[{strategy.name}] pywencai returned {len(rows)} rows")
    except Exception as e:
        out["message"] = f"pywencai 查询失败: {e}"
        out["errors"].append(str(e))
        logger.exception(f"[{strategy.name}] pywencai crashed")
        return out

    # Build stock rows from pywencai DataFrame output
    stock_rows = []
    skipped = 0
    for r in rows:
        code = _get_stock_code(r)
        name = _get_stock_name(r)
        if not code or not name:
            logger.warning(f"[{strategy.name}] skipping row missing code/name: {r}")
            skipped += 1
            continue
        # pywencai returns industry and business info directly
        industry = (r.get("所属同花顺行业") or "").strip()
        business = (r.get("经营范围") or "").strip()
        stock_rows.append({
            "code": code,
            "name": name,
            "t0_price": _get_realtime_price(code),
            "industry": industry if industry else None,
            "business_summary": business[:200] if business else None,
        })

    if not stock_rows:
        out["ok"] = True
        out["message"] = f"iwencai 返回 {len(rows)} 条但全部缺少 code/name，跳过"
        logger.warning(f"[{strategy.name}] {out['message']}")
        return out

    pick = StrategyPick(
        strategy_id=strategy.id,
        status="in_progress",
        hit_count=len(stock_rows),
        created_at=now,
    )
    db.add(pick)
    db.flush()

    for s in stock_rows:
        db.add(StrategyPickStock(
            strategy_pick_id=pick.id,
            stock_code=s["code"],
            stock_name=s["name"],
            industry=s.get("industry"),
            business_summary=s.get("business_summary"),
            selection_reason=None,
            t0_date=today,
            t0_price=s["t0_price"],
        ))
    db.commit()

    out["ok"] = True
    out["batch_id"] = pick.id
    out["hit_count"] = len(stock_rows)
    msg = f"已创建 batch {pick.id}，命中 {len(stock_rows)} 只"
    if skipped:
        msg += f"（跳过 {skipped} 条缺字段）"
    out["message"] = msg
    logger.info(f"[{strategy.name}] {msg}")
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
