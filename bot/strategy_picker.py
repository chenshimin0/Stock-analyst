"""
Run the strategy pick per strategy definition.

Uses iwencai API (hexin-v token) as the primary screener.
Falls back to EastMoney screener if token is expired.

Two entry points:
  run_one_strategy(strategy_id) -> dict  : single strategy, sync
  run_all_enabled()             -> list  : all enabled strategies (called by scheduler)

Returns dict {ok, batch_id, hit_count, errors, message}.
"""
import json
import logging
import re
import sys
import time
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


def _get_industry_em(code: str) -> str | None:
    """东财 F10 公司概况拿行业分类（EM2016，如「商贸零售-零售-百货」）。

    免登录、无需 cookie，作为问财免费额度不带行业列时的兜底。
    失败返回 None（静默，不影响选股落库）。
    """
    if not code or len(code) != 6:
        return None
    if code.startswith(("6", "9")):
        prefix = "SH"
    elif code.startswith(("4", "8")):
        prefix = "BJ"
    else:
        prefix = "SZ"
    url = (f"https://emweb.securities.eastmoney.com"
           f"/PC_HSF10/CompanySurvey/PageAjax?code={prefix}{code}")
    try:
        import gzip as _gzip
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = None
        for attempt in range(2):  # 东财偶发抽风，重试一次
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read()
                # 东财有时返回 gzip 压缩体（无论客户端是否声明 Accept-Encoding）
                if raw[:2] == b"\x1f\x8b":
                    raw = _gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8"))
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"get_industry_em({code}) retry: {e}")
                    continue
                raise
        jbzl = (data or {}).get("jbzl") or []
        em = str((jbzl[0].get("EM2016") or "")).strip() if jbzl else ""
        return em or None
    except Exception as e:
        logger.warning(f"get_industry_em({code}) failed: {e}")
        return None


# ============================================================
# AI 推荐：每次跑出结果后，让 AI 根据当前市场热点/趋势挑一只最值得买的
# ============================================================
_AI_SYSTEM = (
    "你是一位资深A股短线分析师，擅长捕捉市场热点与板块轮动趋势。"
    "只输出一个JSON对象，不要任何解释、不要markdown围栏、不要自述。"
)


def _should_ai_pick(strategy: Strategy) -> bool:
    """所有策略跑出结果后都由 AI 挑一只（原来是吸筹专属，现已全量开放）。"""
    return bool(strategy)


def _ai_pick_one(strategy: Strategy, stock_rows: list[dict]) -> str | None:
    """把候选股票基础信息喂给 AI，让它根据当前市场热点/趋势挑一只最值得买的。

    返回被挑中的 6 位股票代码；AI 失败/未推荐/推荐不在候选中 -> None
    （静默跳过标记，绝不影响选股落库）。
    """
    if not stock_rows:
        return None

    lines = []
    for s in stock_rows:
        parts = [f"{s['code']} {s['name']}"]
        if s.get("industry"):
            parts.append(f"行业: {s['industry']}")
        biz = s.get("business_summary") or ""
        if biz:
            parts.append(f"主营: {biz[:80]}")
        lines.append("- " + " | ".join(parts))
    candidates = "\n".join(lines)

    today = _hkt_now().strftime("%Y-%m-%d")
    prompt = f"""今天是 {today}。以下是「{strategy.name}」策略今日选出的 {len(stock_rows)} 只候选股票：

{candidates}

请根据当前的市场热点、板块轮动和主力资金流向趋势，判断这 {len(stock_rows)} 只里哪一只最值得买入。
只推荐一只，严格按以下 JSON 格式输出：
{{"code": "6位股票代码", "reason": "一句话理由（30字内，说明契合的热点/趋势）"}}

若认为没有一只值得买，输出 {{"code": null, "reason": "不推荐理由"}}。
股票代码必须来自上面的候选列表，名称与代码必须匹配。"""
    try:
        # 懒加载：strategy_picker 运行在 scheduler 进程里，避免 import 副作用
        from ai_analyzer import call_qwen_raw
        raw = call_qwen_raw(prompt, system=_AI_SYSTEM)
    except Exception as e:
        logger.warning(f"[{strategy.name}] AI 推荐调用失败，本次不标记: {e}")
        return None

    text = raw.strip()
    # 容忍 ```json ... ``` 围栏
    for opener in ("```json", "```"):
        if opener in text:
            text = text.split(opener, 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
            break
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            logger.warning(f"[{strategy.name}] AI 推荐无 JSON 可解析: {raw[:200]}")
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            logger.warning(f"[{strategy.name}] AI 推荐 JSON 解析失败: {raw[:200]}")
            return None

    code = str(data.get("code") or "").strip()
    if not code:
        logger.info(f"[{strategy.name}] AI 本次不推荐买入: {data.get('reason', '')}")
        return None
    code = code.split(".")[0]
    valid = {s["code"] for s in stock_rows}
    if code not in valid:
        logger.warning(f"[{strategy.name}] AI 推荐的 {code} 不在候选中，忽略")
        return None
    logger.info(f"[{strategy.name}] AI 推荐买入: {code} ({data.get('reason', '')})")
    return code


# ============================================================
# 排序子句对齐：问财网页会按查询里的「从高到低排序」子句排序展示，
# 但 wap API 返回的是原始顺序（不排）。max_stocks 截「前 N 只」必须
# 与网页看到的前 N 只一致，所以落库前按排序子句对返回行重排。
# 实际写法有多种：周成交量(从高到低排序)、(周成交量)从高到低排序、
# 按周涨跌幅从小到大排序 —— 统一按方向词定位、向前截取字段名。
# ============================================================
_DIR_RE = re.compile(
    r"(?:从|由)(?:高|大|低|小)到(?:高|大|低|小)(?:排序)?|降序|倒序|升序|正序"
)
_BRACE_RE = re.compile(r"\{(.)\}")
_DATE_RE = re.compile(r"\[[^\]]*\]")


def _norm_field(name: str) -> str:
    """把问财字段名归一化：{(}周成交量[20260915]{/}区间成交量[..]{)} → (周成交量/区间成交量)"""
    return _DATE_RE.sub("", _BRACE_RE.sub(r"\1", name))


def _lcs(a: str, b: str) -> int:
    """最长公共子串长度（小字符串，O(n*m) 足够）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _detect_query_sort(query_text: str, rows: list[dict]):
    """在查询文本里找排序方向词，向前截取字段名，并在返回行字段中找最匹配的列。

    返回 (field_name, reverse)；找不到方向词或匹配度过低时返回 None。
    """
    if not query_text or not rows:
        return None
    best = None  # (score, field, reverse)
    for m in _DIR_RE.finditer(query_text):
        direction = m.group(0)
        reverse = not any(w in direction for w in ("低到", "小到", "升序", "正序"))
        before = query_text[: m.start()]
        # 优先取紧邻的括号包字段：(周成交量/近5日成交量)从高到低排序
        mm = re.search(r"\(([^()（）]+)\)\s*$", before)
        if mm:
            key_txt = mm.group(1)
        else:
            # 否则取方向词前、上一个分隔符之后的片段：
            # 周成交量(从高到低排序) / 按周涨跌幅从小到大排序
            seg = re.split(r"[，,；;。]", before)[-1]
            key_txt = seg.strip().lstrip("按").rstrip("(（").strip()
        if len(key_txt) < 2:
            continue
        parts = [p for p in re.split(r"[/／与和]", key_txt) if len(p) >= 2] or [key_txt]
        # key 本身是复合指标（如 周成交量/近5日成交量）时，优先匹配同样
        # 带分隔符的复合列，避免「周成交量」这种单项列靠子串蹭到同分
        key_is_composite = any(sep in key_txt for sep in ("/", "／", "与", "和"))
        for f in rows[0].keys():
            nf = _norm_field(f)
            score = sum(_lcs(p, nf) for p in parts)
            if score < 3:
                continue
            # 排除没有任何数值的列（如「389/5562」式排名、股票简称）
            if not any(_to_float(r.get(f)) is not None for r in rows[:20]):
                continue
            sep_bonus = 1 if key_is_composite and any(
                sep in nf for sep in ("/", "与", "和")) else 0
            cand = (score, sep_bonus)
            if best is None or cand > (best[0], best[1]):
                best = (score, sep_bonus, f, reverse)
    return (best[2], best[3]) if best else None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sort_rows_by_query(rows: list[dict], query_text: str) -> list[dict]:
    """按查询文本的排序子句重排 API 返回行；无子句/无匹配字段时原样返回。"""
    detected = _detect_query_sort(query_text, rows)
    if not detected:
        return rows
    field, reverse = detected
    present, missing = [], []
    for i, r in enumerate(rows):
        v = _to_float(r.get(field))
        (present if v is not None else missing).append((v, i, r))
    present.sort(key=lambda t: t[0], reverse=reverse)  # 稳定排序
    ordered = [r for _, _, r in present] + [r for _, _, r in missing]
    logger.info(f"按查询排序子句重排: field={field!r} reverse={reverse} "
                f"({len(present)} 有值 + {len(missing)} 缺值置尾)")
    return ordered


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

    # Normalise full-width Chinese punctuation to ASCII equivalents,
    # because the iwencai API may not handle full-width chars correctly.
    _query = strategy.query_text.replace("；", ";").replace("，", ",")

    # iwencai via Playwright 浏览器（绕过 chameleon 反爬验证码）
    # 失败重试：浏览器冷启动可能遇到网络超时（ERR_TIMED_OUT）等瞬时故障，
    # 一个策略每天往往只有一个时间点，错过就没了，所以最多重试 3 次。
    rows = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            from iwc_browser import query as iwc_query
            rows = iwc_query(_query, perpage=100)
            break
        except Exception as e:
            last_err = e
            logger.warning(f"[{strategy.name}] iwencai attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(15)  # 失败时 iwc_browser 会关闭会话，下次重试将冷启动
    if rows is None:
        out["message"] = f"iwencai 查询失败(已重试3次): {last_err}"
        out["errors"].append(str(last_err))
        logger.error(f"[{strategy.name}] iwencai crashed after retries")
        return out
    if not rows:
        out["ok"] = True
        out["message"] = "iwencai 今日返回 0 条"
        # Still create a StrategyPick record so frontend can show runs with 0 hits
        pick = StrategyPick(
            strategy_id=strategy.id,
            status="completed",
            hit_count=0,
            created_at=now,
        )
        db.add(pick)
        db.commit()
        out["batch_id"] = pick.id
        out["hit_count"] = 0
        logger.info(f"[{strategy.name}] {out['message']} (batch={pick.id})")
        return out
    logger.info(f"[{strategy.name}] iwencai returned {len(rows)} rows")

    # 对齐问财网页排序：网页按查询里的排序子句展示，API 原始顺序没排，
    # max_stocks 截「前 N 只」前必须重排，否则截到的不是网页上的前 N 只
    rows = _sort_rows_by_query(rows, strategy.query_text)

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
        # Industry format: "电子-半导体-数字芯片设计" → take last segment
        industry_full = (r.get("所属同花顺行业") or "").strip()
        industry = industry_full.split("-")[-1] if industry_full else None
        business = (r.get("经营范围") or "").strip()
        # 问财免费额度可能不带行业列，缺失时走 10jqka F10 → 东财 F10 兜底
        if not industry:
            ind_fb = (_get_industry_business(code).get("industry") or "") or _get_industry_em(code) or ""
            ind_fb = ind_fb.strip()
            # 兼容「A - B - C」与「A — B」两种分隔格式，取最后一段
            industry = ind_fb.split("—")[-1].split("-")[-1].strip() or None
            if industry:
                logger.info(f"[{strategy.name}] {code} 行业兜底(东财F10): {industry}")
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

    # max_stocks：只保留问财返回顺序的前 N 只（NULL/0 = 全部保留）
    max_stocks = getattr(strategy, "max_stocks", None)
    if max_stocks and max_stocks > 0 and len(stock_rows) > max_stocks:
        stock_rows = stock_rows[:max_stocks]
        logger.info(f"[{strategy.name}] max_stocks={max_stocks}，从 {len(rows)} 条截取前 {max_stocks} 只")

    # AI 推荐：根据当前市场热点/趋势挑一只最值得买的，用于前端高亮
    ai_code = _ai_pick_one(strategy, stock_rows) if _should_ai_pick(strategy) else None

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
            ai_recommended=(ai_code is not None and s["code"] == ai_code),
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
