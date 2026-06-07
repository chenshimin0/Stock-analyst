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
from datetime import datetime, timedelta
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from astock_data import get_quote

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


def is_within_market_cap(mcap_yi: float) -> bool:
    """Market cap (in 100M CNY) <= 500."""
    return 0 < mcap_yi <= 500


def is_within_pe_median(pe_ttm: float, median_pe: float) -> bool:
    """PE-TTM below concept median."""
    return pe_ttm > 0 and pe_ttm < median_pe


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
    Pull concept member stocks from a-stock-data skill.
    Primary: baidu stock concept mapping.
    Fallback: ths hot reason reverse-lookup.
    Returns [] on failure (caller should fallback to AI knowledge).
    """
    # TODO: wire up to existing astock_data functions if available.
    # For now, return [] to exercise the fallback path.
    return []


# =================================================================
# B: API-driven candidate filtering
# =================================================================
def build_api_driven_candidates(sector_name: str, db_session) -> list[dict]:
    """
    Returns up to 20 candidates with: code, name, mcap_yi, pe_ttm.
    Source: cache (24h) -> realtime fetch -> [].
    """
    members = get_cached_members(sector_name, db_session)
    if not members:
        members = fetch_concept_members_realtime(sector_name)
        if members:
            save_cached_members(sector_name, members, db_session)
    if not members:
        return []
    candidates = []
    for m in members[:20]:
        q = get_quote(m["stock_code"])
        if not q:
            continue
        candidates.append({
            "code": m["stock_code"],
            "name": m["stock_name"],
            "mcap_yi": q.get("total_mv", 0),
            "pe_ttm": q.get("pe", 0),
        })
    return candidates


def filter_main_board_non_st(candidates: list[dict]) -> list[dict]:
    return [
        c for c in candidates
        if is_main_board(c["code"]) and not is_st(c["name"])
    ]


def filter_market_cap(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if is_within_market_cap(c.get("mcap_yi", 0))]


def pe_median(candidates: list[dict]) -> float:
    pes = [c["pe_ttm"] for c in candidates if c.get("pe_ttm", 0) > 0]
    return statistics.median(pes) if pes else 0


# =================================================================
# DeepSeek prompt construction
# =================================================================
def build_prompt_api_driven(concept_name: str, candidates: list[dict], median_pe: float) -> str:
    rows = "\n".join(
        f"| {c['code']} | {c['name']} | {c['mcap_yi']:.0f} | {c['pe_ttm']:.1f} |"
        for c in candidates
    )
    return f"""Concept name: {concept_name}
Concept member stocks (fetched via API in real-time, {datetime.now().strftime("%Y-%m-%d")}):

| Code | Name | Market Cap (yi) | PE-TTM |
{rows}

Please select **3** stocks from the above that best match:
1. Industry leader position
2. PE-TTM below concept median ({median_pe:.1f})
3. Market cap < 500 yi
4. Listed on main board, not ST
5. Has paid cash dividends for 3 consecutive years
6. Give a short reason (within 30 chars) for each

Output strict JSON: {{"picks":[{{"code":"002812","name":"Enjie","reason":"Global PVDF coating leader..."}}]}}
"""


def build_prompt_ai_knowledge(concept_name: str) -> str:
    return f"""From the concept sector "{concept_name}", recommend 3 A-shares that match:
- Listed on Shanghai/Shenzhen main board (6-prefix Shanghai, 0-prefix Shenzhen), not ST
- Market cap < 500 yi
- Industry leader position
- Low PE-TTM (estimate within your knowledge)
- Has paid cash dividends for 3 consecutive years
- Output strict JSON: {{"picks":[{{"code":"002812","name":"Enjie","reason":"..."}}]}}
- If concept does not exist or has fewer than 3 members, return {{"error":"reason"}} instead of guessing
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
# Top-level entry: A+B fallback
# =================================================================
def select_stocks_for_concept(concept_name: str, db_session, deepseek_callable) -> dict:
    """
    A+B strategy:
    1. Try B: build candidates from API -> DeepSeek filters -> 3 picks
    2. On B failure (no candidates / DeepSeek error / parse error) -> A: feed concept name to DeepSeek
    Returns: {
      "picks": [...], "source": "api_driven" | "ai_knowledge",
    }
    On unrecoverable failure: {"error": "..."}
    """
    # B: API-driven
    candidates = build_api_driven_candidates(concept_name, db_session)
    main_board = filter_main_board_non_st(candidates)
    main_board = filter_market_cap(main_board)
    if len(main_board) >= 3:
        med = pe_median(main_board)
        prompt = build_prompt_api_driven(concept_name, main_board, med)
        raw = deepseek_callable(prompt)
        parsed = parse_deepseek_response(raw)
        if "picks" in parsed:
            # Validate picks are subset of candidates
            valid_codes = {c["code"] for c in main_board}
            valid_picks = [p for p in parsed["picks"] if p["code"] in valid_codes]
            if len(valid_picks) == 3:
                return {"picks": valid_picks, "source": "api_driven"}
        logger.warning(f"API-driven path failed: {parsed.get('error', 'unknown')}; falling back")

    # A: AI knowledge
    prompt = build_prompt_ai_knowledge(concept_name)
    raw = deepseek_callable(prompt)
    parsed = parse_deepseek_response(raw)
    if "picks" in parsed:
        return {"picks": parsed["picks"], "source": "ai_knowledge"}
    return {"error": parsed.get("error", "AI knowledge path failed")}
