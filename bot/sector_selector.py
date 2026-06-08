"""
Concept-sector stock selection: A+B fallback strategy.

A: DeepSeek-only (concept_name -> 3 stocks)
B: API-driven (sector_member_cache + tencent_quote -> candidates -> DeepSeek filters)
"""
import json
import logging
import statistics
import urllib.request
import re
from datetime import datetime, timedelta, date as _date
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from astock_data import get_quote
try:
    from astock_data_10jqka import get_hot_reasons as _ths_hot_reason
except ImportError:
    _ths_hot_reason = None

logger = logging.getLogger(__name__)


# =================================================================
# Board filters
# =================================================================
def is_main_board(code: str) -> bool:
    """6-prefix Shanghai main + 0-prefix Shenzhen main (incl 002 SME). Excludes ChiNext/STAR/BSE."""
    if code.startswith("688"):
        return False  # STAR market
    return code.startswith("6") or code.startswith("0")


def is_st(name: str) -> bool:
    """Stock name contains ST or *ST -> ST stock."""
    n = name.upper()
    return "ST" in n




# =================================================================
# Concept member cache (24h TTL)
# =================================================================
def get_cached_members(sector_name: str, db_session) -> list[dict]:
    """
    Read sector_member_cache. Returns list of {stock_code, stock_name}.
    Empty list if no records or all expired (> 24h).
    Caller must pass a SQLAlchemy session.
    """
    from app.models.sector_pick import SectorMemberCache  # type: ignore
    threshold = datetime.utcnow() - timedelta(hours=24)
    rows = (
        db_session.query(SectorMemberCache)
        .filter(SectorMemberCache.sector_name == sector_name)
        .filter(SectorMemberCache.last_fetched_at >= threshold)
        .all()
    )
    return [{"stock_code": r.stock_code, "stock_name": r.stock_name} for r in rows]


def save_cached_members(sector_name: str, members: list[dict], db_session) -> None:
    """Upsert cache rows."""
    from app.models.sector_pick import SectorMemberCache  # type: ignore
    now = datetime.utcnow()
    for m in members:
        existing = (
            db_session.query(SectorMemberCache)
            .filter(
                SectorMemberCache.sector_name == sector_name,
                SectorMemberCache.stock_code == m["stock_code"],
            )
            .first()
        )
        if existing:
            existing.stock_name = m["stock_name"]
            existing.last_fetched_at = now
        else:
            db_session.add(SectorMemberCache(
                sector_name=sector_name,
                stock_code=m["stock_code"],
                stock_name=m["stock_name"],
                last_fetched_at=now,
            ))
    db_session.commit()


# =================================================================
# Concept member fetch (real-time, fallback to A)
# =================================================================
def fetch_concept_members_realtime(sector_name: str) -> list[dict]:
    """
    Real-time concept member fetch.
    Strategy: scan ths hot reason over the last N trading days, find rows
    where the "reason" tag list contains the concept name (case-insensitive
    substring). Dedupe by stock_code.
    Returns [] on any failure (caller falls back to AI knowledge).
    """
    if not _ths_hot_reason:
        logger.debug("astock_data_10jqka.get_hot_reasons unavailable; skipping realtime fetch")
        return []

    target = sector_name.strip().lower()
    if not target:
        return []

    members: dict[str, dict] = {}
    # Last 7 calendar days (~5 trading days) — gives us enough signal even
    # if the current session had a quiet theme.
    lookback_days = 7
    for i in range(lookback_days):
        d = (_date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            rows = _ths_hot_reason(d)
        except Exception as e:
            logger.warning(f"get_hot_reasons({d}) failed: {e}")
            continue
        if not rows:
            continue
        for row in rows:
            reason = str(row.get("reason", "")).lower()
            if not reason or target not in reason:
                continue
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code or not name:
                continue
            if not re.match(r"^\d{6}$", code):
                continue
            if code in members:
                continue
            members[code] = {"stock_code": code, "stock_name": name}
    return list(members.values())


# =================================================================
# Concept candidate pool (live quotes + industry hint)
# =================================================================
# Maps concept name (or alias) -> SW industry code for Tencent industry filter.
# If a concept isn't in this table, we fall back to scanning 同花顺热点 reason
# tags (broader but still useful) and then ask DeepSeek to reason.
_CONCEPT_INDUSTRY_HINTS = {
    "pvdf": ["化工", "氟化工", "化学制品"],
    "氟化工": ["化工", "化学制品"],
    "太赫兹": ["通信", "电子"],
    "固态电池": ["电池", "新能源"],
    "钠电池": ["电池", "新能源"],
    "机器人": ["机械", "自动化设备"],
    "cpo": ["通信设备", "电子"],
    "算力": ["计算机", "通信"],
    "ai": ["计算机", "电子"],
}


def build_concept_candidate_pool(sector_name: str, db_session, max_candidates: int = 40) -> list[dict]:
    """
    Build a candidate pool of A-share stocks related to the given concept.
    Sources (merged + deduped):
      1. 同花顺热点 reason tags (last 7 days, case-insensitive substring)
      2. SectorMemberCache (24h TTL) from prior picks
    Then filter to: main board + non-ST + market cap <= 1000 亿 (relaxed)
    Add live quote data: mcap_yi, pe_ttm.
    Returns: list of {code, name, industry, mcap_yi, pe_ttm}.
    """
    # Source 1: realtime hot reason
    realtime = fetch_concept_members_realtime(sector_name)
    members: dict[str, dict] = {m["stock_code"]: m for m in (realtime or [])}
    # Source 2: cache
    cached = get_cached_members(sector_name, db_session)
    for m in cached:
        members.setdefault(m["stock_code"], m)
    if not members:
        return []

    candidates = []
    for m in list(members.values())[:max_candidates]:
        q = get_quote(m["stock_code"])
        if not q:
            continue
        code = m["stock_code"]
        if not is_main_board(code) or is_st(m["stock_name"]):
            continue
        # No market cap or PE filter — DeepSeek decides who's a leader.
        # Just require Tencent to give us a live price (mc > 0 means it's a real stock).
        mc = q.get("total_mv", 0)
        if mc <= 0:
            continue
        pe = q.get("pe", 0)
        candidates.append({
            "code": code,
            "name": m["stock_name"],
            "industry": "",  # filled later if available
            "mcap_yi": mc,
            "pe_ttm": pe if pe > 0 else 0,
        })
    # If we have < 5 candidates, try expanding the realtime window
    if len(candidates) < 5:
        logger.info(f"Only {len(candidates)} candidates for '{sector_name}', considering broader pool")
    return candidates[:max_candidates]



def build_prompt_ai_knowledge(concept_name: str, candidates=None) -> str:
    """
    Prompt for DeepSeek to pick 3 stocks.
    If `candidates` is non-empty, the prompt shows the live data table and asks
    DeepSeek to pick FROM the table. Otherwise (fallback), it asks DeepSeek
    to use its own knowledge.
    """
    if not candidates:
        return f"""请从"{concept_name}"这一**概念板块**中，推荐 3 只 A 股：
- 沪深主板上市（6 字头沪市主板、0 字头深市主板），非 ST
- **必须**与「{concept_name}」概念有真实业务关联（不是擦边球）
- 优先行业龙头
- 输出严格 JSON：{{"picks":[{{"code":"002812","name":"恩捷股份","reason":"..."}}]}}
- 如果该概念不存在或成分股 < 3 只，返回 {{"error":"原因"}} 而非猜测
"""
    rows = "\n".join(
        f"| {c['code']} | {c['name']} | {c['mcap_yi']:.0f} | {c['pe_ttm']:.1f} |"
        for c in candidates
    )
    return f"""请从下方「{concept_name}」相关 A 股候选池中，挑选 **3 只** 股票。

**硬性条件**：
1. 沪深主板上市（6 字头沪市主板、0 字头深市主板），排除 300/688/8 字头
2. 非 ST
3. **必须**与「{concept_name}」概念有真实业务关联

**优先标准**：
- 行业龙头地位
- 主营产品直接覆盖「{concept_name}」相关产品/技术

（市值、PE、分红记录仅供参考，不作为硬性门槛）

**候选池**（已通过 API 实时拉取 {datetime.now().strftime("%Y-%m-%d")}）：

| 代码 | 名称 | 市值(亿) | PE-TTM |
{rows}

**输出格式（严格 JSON，无其他文字）**：
{{"picks": [
  {{"code": "600378", "name": "昊华科技", "reason": "PVDF 中试线 + 氟橡胶龙头"}},
  {{"code": "...", "name": "...", "reason": "..."}},
  {{"code": "...", "name": "...", "reason": "..."}}
]}}
"""


# =================================================================
# DeepSeek response parsing
# =================================================================
def parse_deepseek_response(raw: str) -> dict:
    """
    Extract JSON from DeepSeek output. Returns:
      {"picks": [{"code","name","reason"}, ...]} on success
      {"error": "..."} on missing/empty/error
    """
    # Strip markdown code fences
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find first { ... } block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"error": "no JSON object found in response"}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}
    if "error" in data:
        return {"error": data["error"]}
    picks = data.get("picks")
    if not isinstance(picks, list) or len(picks) != 3:
        return {"error": f"expected 3 picks, got {len(picks) if isinstance(picks, list) else 'non-list'}"}
    for p in picks:
        if not all(k in p for k in ("code", "name", "reason")):
            return {"error": f"missing field in pick: {p}"}
        if not re.match(r"^\d{6}$", p["code"]):
            return {"error": f"invalid code: {p['code']}"}
    return {"picks": picks}


# =================================================================
# Post-filter: consistency check + sanity (board, ST)
# =================================================================
def validate_picks(picks: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Minimal validator: only verify what's NOT a business judgment.
    - 主板 (excludes 300/688/8/4/9) — structural
    - 非 ST — structural
    - Tencent has live quote for the code — sanity (no fabricated codes)

    NOT checked here (DeepSeek's call):
    - Market cap size (DeepSeek decides who's the leader)
    - PE-TTM value (DeepSeek decides valuation)
    - Business relevance to concept (DeepSeek's domain)
    """
    valid = []
    rejected = []
    for p in picks:
        code = p.get("code", "")
        name = p.get("name", "")
        reasons = []
        if not re.match(r"^\d{6}$", code):
            reasons.append(f"{code} 不是 6 位代码")
        elif not is_main_board(code):
            reasons.append(f"{code} 非主板（科创/创业/B 股/北交所）")
        if is_st(name):
            reasons.append(f"{name} 含 ST")
        # Sanity: can Tencent actually quote this code?
        q = get_quote(code)
        if not q:
            reasons.append(f"{code} 拉不到实时行情（代码可能不存在）")
        if reasons:
            rejected.append({**p, "reject_reasons": reasons})
        else:
            valid.append(p)
    return valid, rejected


# =================================================================
# Top-level entry: A+B fallback
# =================================================================
def select_stocks_for_concept(concept_name: str, db_session, deepseek_callable) -> dict:
    """
    Strategy: build a candidate pool (hint, not strict whitelist), ask
    DeepSeek to pick 3. Pass the pool to the prompt as a "you may want
    to consider these". Validator only checks structural rules (主板,
    非 ST, 6-digit, Tencent has live quote).

    The pool is NOT enforced as a whitelist — DeepSeek can pick stocks
    not in the pool if it knows they're better candidates (e.g. for
    cold concepts where the pool has 0-1 stocks).
    """
    MAX_RETRIES = 2

    candidates = build_concept_candidate_pool(concept_name, db_session)
    # If pool has < 3 stocks, the prompt becomes confusing ("pick 3 from 1").
    # Fall back to pure-knowledge mode so DeepSeek picks freely.
    if len(candidates) < 3:
        candidates = None
        source = "ai_knowledge"
    else:
        source = "candidates"

    rejected_codes: list[str] = []
    rejected_reasons: list[str] = []
    for attempt in range(MAX_RETRIES):
        rejected_note = ""
        if attempt > 0:
            rejected_note = "\n\n注意：上一次 picks 中以下代码被系统拒收，请重新选股时避开：\n" + \
                "\n".join(f"- {c} ({r})" for c, r in zip(rejected_codes, rejected_reasons)) + \
                "\n请重新推荐 3 只合规股票。"
        if source == "candidates":
            prompt = build_prompt_ai_knowledge(concept_name, candidates) + rejected_note
        else:
            prompt = build_prompt_ai_knowledge(concept_name, None) + rejected_note
        raw = deepseek_callable(prompt)
        parsed = parse_deepseek_response(raw)
        if "picks" not in parsed:
            break
        # NOTE: candidate pool is a HINT in the prompt, not a strict
        # whitelist. We do NOT filter DeepSeek's picks to the pool here.
        valid, rejected = validate_picks(parsed["picks"])
        rejected_codes = [p["code"] for p in rejected]
        rejected_reasons = ["; ".join(p.get("reject_reasons", [])) for p in rejected]
        if len(valid) >= 3:
            return {"picks": valid[:3], "source": source, "rejected": rejected}
    return {"error": f"选股经过 {MAX_RETRIES} 轮仍无法凑齐 3 只合规股票。已拒绝: {rejected_codes or '无'}"}
