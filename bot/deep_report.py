"""
Deep Report builder — constructs analysis reports from a-stock-data layer.
=======================================================================
Data fetching via astock_data.py (a-stock-data skill APIs).
News classification + report formatting.
"""

import json
import logging
import os
import re
import sys
import urllib.request
from datetime import date
from typing import Optional

from astock_data import get_quote, get_kline, get_fund_flow, search_news, get_concept_boards, get_financial_data_em, get_peer_comparison_em, get_revenue_composition_em
from astock_data_10jqka import (
    get_realtime_10jqka, get_kline_10jqka, get_eps_forecast,
    get_stock_hot_reason, get_industry_comparison, enrich_quote_10jqka,
)

# Ensure scripts dir is importable for eastmoney_news_search
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
if os.path.isdir(_SCRIPTS_DIR) and _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

logger = logging.getLogger("deep_report")

# ---------------------------------------------------------------------------
# News classification
# ---------------------------------------------------------------------------

ORDER_KEYWORDS = [
    "订单", "合同", "中标", "签约", "协议", "承揽", "承包", "预中标",
    "中标候选", "供货合同", "销售合同", "框架协议", "战略合作",
    "获得订单", "签订", "中标公告", "中标通知", "合同签订",
    "批量采购", "采购合同", "意向书", "备忘录",
]
MAJOR_KEYWORDS = [
    "定增", "重组", "并购", "收购", "出售资产", "增持", "减持",
    "回购", "分红", "送转", "高管变更", "业绩预告", "业绩快报",
    "停牌", "复牌", "立案", "处罚", "问询", "澄清",
    "新股", "IPO", "解除质押", "质押", "限售解禁",
    "扩产", "投资", "新建", "项目投产", "技术突破",
    "战略规划", "股权激励", "员工持股",
]


def classify_news(news_items: list) -> tuple:
    """Classify news into order/contract, major events, general."""
    order_events, major_events, general_news = [], [], []
    for item in news_items:
        title = item.get("title", "")
        content = item.get("content", "") or ""
        combined = title + content
        is_order = any(kw in combined for kw in ORDER_KEYWORDS)
        is_major = any(kw in combined for kw in MAJOR_KEYWORDS)
        if is_order:
            order_events.append(item)
        if is_major:
            major_events.append(item)
        if not is_order and not is_major:
            general_news.append(item)
    return general_news, order_events, major_events


def fetch_rich_news(code: str, name: str = "") -> dict:
    """Fetch and classify news from multiple sources."""
    result = {"news_items": [], "order_events": [], "major_events": []}
    all_news = []

    # Source 1: EastMoney search API (astock_data)
    try:
        raw_news = search_news(code, name, page_size=15)
        all_news.extend(raw_news)
    except Exception as e:
        logger.warning(f"EastMoney search failed for {code}: {e}")

    # Source 2: EastMoney API via stock_utils (with API key, better results)
    try:
        from stock_utils import eastmoney_news_search
        resp = eastmoney_news_search(
            question=f"{code} {name}".strip(),
            stock_code=code,
            stock_name=name,
            page_size=15,
            timeout=8,
        )
        if resp.get("success"):
            for item in resp.get("items", []):
                all_news.append({
                    "title": item.get("title", ""),
                    "content": item.get("trunk", ""),
                    "source": item.get("source", ""),
                    "date": item.get("publish_time", ""),
                    "url": item.get("link", ""),
                })
    except Exception as e:
        logger.debug(f"eastmoney_news_search failed for {code}: {e}")

    # Source 3: akshare 东方财富新闻
    try:
        import akshare as ak
        ak_news = ak.stock_news_em(symbol=code)
        if ak_news is not None and not ak_news.empty:
            for _, row in ak_news.head(15).iterrows():
                all_news.append({
                    "title": str(row.get("标题", "")),
                    "content": str(row.get("内容", "")),
                    "source": str(row.get("来源", "资讯")),
                    "date": str(row.get("发布时间", "")),
                    "url": str(row.get("链接", "")),
                })
    except Exception as e:
        logger.debug(f"akshare stock_news_em failed for {code}: {e}")

    # Dedup by title
    seen = set()
    unique = []
    for n in all_news:
        key = n.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(n)

    # Filter out news where target code is misattributed to another company
    # e.g. a news article writes "高新发展（000682.SZ）" but 000682 is 东方电子
    if name:
        _PAT_WRONG_CODE = re.compile(
            r'([一-鿿]{2,10})[（(]' + re.escape(code) + r'\.[A-Z]{2}[）)]'
        )
        filtered = []
        for n in unique:
            content = (n.get("title", "") or "") + (n.get("content", "") or "")
            bad = False
            for m in _PAT_WRONG_CODE.finditer(content):
                if m.group(1) != name:
                    logger.warning(
                        f"Filtered misattributed news for {code}: "
                        f"'{m.group(1)}' != '{name}' — {n.get('title', '')[:50]}"
                    )
                    bad = True
                    break
            if not bad:
                filtered.append(n)
        unique = filtered

    general, orders, majors = classify_news(unique)
    result["news_items"] = general[:15]
    result["order_events"] = orders[:10]
    result["major_events"] = majors[:10]

    logger.info(
        f"Rich news for {code}: total={len(unique)}, news={len(result['news_items'])}, "
        f"orders={len(result['order_events'])}, majors={len(result['major_events'])}"
    )
    return result


# ---------------------------------------------------------------------------
# Technical indicators
# ---------------------------------------------------------------------------

def calc_ma(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0
    return sum(closes[-period:]) / period


def calc_macd(closes: list, fast=12, slow=26, signal=9) -> tuple:
    if len(closes) < slow + signal:
        return 0, 0, 0
    ema_fast = closes[0]
    ema_slow = closes[0]
    kf = 2 / (fast + 1)
    ks = 2 / (slow + 1)
    difs = []
    for p in closes:
        ema_fast = p * kf + ema_fast * (1 - kf)
        ema_slow = p * ks + ema_slow * (1 - ks)
        difs.append(ema_fast - ema_slow)
    dea = sum(difs[-signal:]) / signal
    for d in difs[-signal:]:
        dea = d * (2 / (signal + 1)) + dea * (1 - 2 / (signal + 1))
    dif = difs[-1]
    macd_bar = 2 * (dif - dea)
    return round(dif, 3), round(dea, 3), round(macd_bar, 3)


def compute_indicators(kline: list) -> dict:
    """Compute technical indicators from K-line data."""
    if len(kline) < 26:
        return {"error": "K-line data insufficient"}
    closes = [k["close"] for k in kline]
    highs = [k["high"] for k in kline]
    lows = [k["low"] for k in kline]
    volumes = [k["volume"] for k in kline]

    latest = closes[-1]
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else 0
    dif, dea, macd_bar = calc_macd(closes)

    # ATR(14)
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else 0

    # RSI(14)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(d if d > 0 else 0)
        losses.append(abs(d) if d < 0 else 0)
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 0
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

    recent_20_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    recent_20_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)

    vol5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
    vol20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
    vol_ratio = vol5 / vol20 if vol20 > 0 else 0

    return {
        "latest": round(latest, 2),
        "ma5": round(ma5, 2), "ma10": round(ma10, 2),
        "ma20": round(ma20, 2), "ma60": round(ma60, 2),
        "dif": dif, "dea": dea, "macd_bar": macd_bar,
        "atr": round(atr, 2), "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "resistance": round(recent_20_high, 2),
        "support": round(recent_20_low, 2),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_stock(quote: dict, ind: dict, flow: dict, news: list, sector_bonus: float = 0,
                ai_scoring: dict = None) -> dict:
    """Dual-track scoring: momentum (40%) + revenue quality (35%) + risk (25%) + sector.

    ai_scoring: optional AI-generated scoring_factors for qualitative adjustment.
    """
    scores = {}

    # Momentum
    m = 5.0
    if ind.get("macd_bar", 0) > 0:
        m += 1.0
    if ind.get("ma5", 0) > ind.get("ma20", 0):
        m += 0.8
    if ind.get("rsi", 50) > 50:
        m += 0.5
    if ind.get("vol_ratio", 0) > 1.2:
        m += 0.7
    main_net = flow.get("main_net", 0)
    if main_net > 0:
        m += 0.5
    elif main_net < 0:
        m -= 0.5
    if ind.get("ma20", 0) > 0:
        dev = abs(quote.get("price", 0) - ind["ma20"]) / ind["ma20"]
        if dev > 0.2:
            m -= 1.5
        elif dev > 0.1:
            m -= 0.5
    scores["momentum"] = round(max(1, min(10, m)), 1)

    # Revenue quality
    r = 5.0
    pe = quote.get("pe", 0)
    if 0 < pe < 25:
        r += 1.5
    elif 25 <= pe < 50:
        r += 0.5
    elif pe >= 100:
        r -= 1.5
    news_text = " ".join(n.get("title", "") for n in news)
    if re.search(r"(增长|大增|超预期|扭亏|上涨|高增|翻倍)", news_text):
        r += 1.0
    if re.search(r"(下滑|亏损|下降|预亏|暴跌)", news_text):
        r -= 1.0
    scores["revenue"] = round(max(1, min(10, r)), 1)

    # Risk — softened technical penalties for high-growth leaders
    risk = 7.0
    change = abs(quote.get("change_pct", 0))
    if change > 9:
        risk -= 1.5
    elif change > 5:
        risk -= 0.5
    if quote.get("pe", 0) > 100:
        risk -= 1.5
    if ind.get("rsi", 50) > 80:
        risk -= 1.0
    elif ind.get("rsi", 50) > 70:
        risk -= 0.5
    if main_net < 0:
        risk -= 0.5

    # Qualitative adjustment from AI scoring factors
    if ai_scoring:
        ai_risk = ai_scoring.get("risk", [])
        pos_count = sum(1 for item in ai_risk if item[1] == "pos")
        neg_count = sum(1 for item in ai_risk if item[1] == "neg")
        if pos_count > neg_count:
            risk += 1.0 + (pos_count - neg_count) * 0.5
        elif pos_count > 0:
            risk += 0.5
        # Clamp after adjustment
        risk = max(1, min(10, risk))

    scores["risk"] = round(risk, 1)

    total = scores["momentum"] * 0.4 + scores["revenue"] * 0.35 + scores["risk"] * 0.25 + sector_bonus
    label = "回避" if total < 4.5 else ("可做" if total >= 6.5 else "观察")

    return {
        "momentum": scores["momentum"], "revenue": scores["revenue"],
        "risk": scores["risk"], "total": round(total, 2), "label": label,
        "sector_bonus": sector_bonus,
    }


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def build_analysis_data(code: str) -> Optional[dict]:
    """Build complete analysis data dict for a stock — ready for DeepSeek + web save."""
    quote = get_quote(code)
    name = quote.get("name", "")
    price = quote.get("price", 0)
    if not name or price <= 0:
        logger.error(f"Cannot get quote for {code}")
        return None

    kline = get_kline(code, 120)
    ind = compute_indicators(kline) if kline else {}
    flow = get_fund_flow(code)

    rich = fetch_rich_news(code, name)
    all_news = rich["news_items"] + rich["order_events"] + rich["major_events"]
    order_news = rich["order_events"]

    # ---- 10jqka data layer (parallel-friendly, each call has retry) ----
    data_10jqka = {}
    eps_forecast = {}
    hot_reason = None
    industry_compare = {}
    kline_10jqka = []
    quote_10jqka = {}

    try:
        quote_10jqka = get_realtime_10jqka(code)
        enrich_quote_10jqka(quote)  # merge 10jqka fields into main quote
    except Exception as e:
        logger.debug(f"10jqka realtime skipped: {e}")

    try:
        kline_10jqka = get_kline_10jqka(code, count=250)
        logger.info(f"10jqka K-line for {code}: {len(kline_10jqka)} bars")
    except Exception as e:
        logger.debug(f"10jqka K-line skipped: {e}")

    try:
        eps_forecast = get_eps_forecast(code)
        if eps_forecast:
            logger.info(f"EPS forecast for {code}: {eps_forecast.get('raw_html_cols', [])}")
    except Exception as e:
        logger.debug(f"EPS forecast skipped: {e}")

    try:
        hot_reason = get_stock_hot_reason(code)
        if hot_reason:
            logger.info(f"Hot reason for {code}: {hot_reason}")
    except Exception as e:
        logger.debug(f"Hot reason skipped: {e}")

    try:
        industry_compare = get_industry_comparison(code)
        if industry_compare:
            logger.info(f"Industry comparison for {code}: {len(industry_compare.get('tables', []))} tables")
    except Exception as e:
        logger.debug(f"Industry comparison skipped: {e}")

    # ---- 10jqka data assembled ----
    data_10jqka = {
        "realtime": quote_10jqka,
        "kline": kline_10jqka,
        "eps_forecast": eps_forecast,
        "hot_reason": hot_reason,
        "industry_compare": industry_compare,
    }

    # If 10jqka kline has more data, use it for indicator computation
    # (10jqka provides longer history — up to full history from IPO)
    if kline_10jqka and len(kline_10jqka) > len(kline):
        ind_10jqka = compute_indicators(kline_10jqka)
        if ind_10jqka and "error" not in ind_10jqka:
            if "error" in ind:
                ind = ind_10jqka  # primary K-line failed, use 10jqka entirely
                logger.info(f"Indicators from 10jqka K-line (MA5={ind.get('ma5')}, MA60={ind.get('ma60')})")
            else:
                for key in ["ma60", "rsi", "atr"]:
                    if ind_10jqka.get(key, 0) and (not ind.get(key)):
                        ind[key] = ind_10jqka[key]
                logger.info(f"Indicators enriched from 10jqka K-line (MA60={ind.get('ma60')})")

    # Concept boards
    # Primary: pywencai (no cookies needed, always available, more relevant)
    # Fallback: 10jqka F10 (needs cookies) -> EastMoney
    concept_boards = []
    try:
        from astock_data import get_pywencai_concept_boards
        concept_boards = get_pywencai_concept_boards(code)
        if concept_boards:
            logger.info(f"Concept boards from pywencai for {code}: {[c['board_name'] for c in concept_boards[:10]]}")
    except Exception as e:
        logger.debug(f"pywencai concept boards unavailable: {e}")
    if not concept_boards:
        try:
            from astock_data_10jqka import get_concept_boards_10jqka
            concept_boards = get_concept_boards_10jqka(code)
            if concept_boards:
                logger.info(f"Concept boards from 10jqka for {code}: {[c['board_name'] for c in concept_boards[:10]]}")
        except Exception as e:
            logger.debug(f"10jqka concept boards unavailable: {e}")
    if not concept_boards:
        try:
            concept_boards = get_concept_boards(code)
            logger.info(f"Concept boards from EastMoney for {code}: {[c['board_name'] for c in concept_boards[:10]]}")
        except Exception as e:
            logger.warning(f"Concept boards skipped: {e}")

    # ---- Financial data from East Money datacenter ----
    financial_data = {}
    try:
        financial_data = get_financial_data_em(code, years=5)
        logger.info(f"Financial data for {code}: {len(financial_data.get('annual', []))} years")
    except Exception as e:
        logger.warning(f"Financial data skipped: {e}")

    # ---- Peer comparison from 10jqka F10 ----
    peer_comparison = {}
    try:
        peer_comparison = get_peer_comparison_em(code)
        logger.info(f"Peer comparison for {code}: {len(peer_comparison.get('peers', []))} peers")
    except Exception as e:
        logger.warning(f"Peer comparison skipped: {e}")

    # Revenue composition (主营构成) from EastMoney
    revenue_composition = {}
    try:
        revenue_composition = get_revenue_composition_em(code)
        if revenue_composition:
            by_prod = revenue_composition.get("by_product", [])
            logger.info(f"Revenue composition for {code}: {len(by_prod)} products, {revenue_composition.get('report_date', '')}")
    except Exception as e:
        logger.warning(f"Revenue composition skipped: {e}")

    # Sector lifecycle — prefer concept boards (10jqka or EastMoney) over industry classification
    sector_data = None
    try:
        from sector_lifecycle import analyze_sector_lifecycle, analyze_sector_by_name
        sector_data = analyze_sector_lifecycle(code)
        # Prefer 10jqka concept boards (more accurate); EastMoney has is_precise filter
        is_10jqka = any(c.get("source") == "10jqka" for c in concept_boards)
        if is_10jqka:
            # 10jqka boards are ordered by relevance — try top 5
            candidates = [c["board_name"] for c in concept_boards[:5]]
        else:
            # EastMoney: filter precise, sort by specificity
            precise = [c for c in concept_boards if c.get("is_precise")]
            industry_name = sector_data.get("sector_name", "") if sector_data else ""
            def _concept_score(c):
                name = c.get("board_name", "")
                specificity = len(name)
                overlap = len(set(name) & set(industry_name)) if industry_name else 0
                rank = c.get("board_rank", 99)
                return (overlap * 10 + specificity, -rank)
            precise_sorted = sorted(precise, key=_concept_score, reverse=True)
            candidates = [c["board_name"] for c in precise_sorted[:5]]
        # Try candidates, pick first that yields valid sector
        for cand_name in candidates:
            new_sd = analyze_sector_by_name(cand_name, code)
            if new_sd:
                logger.info(
                    f"Sector from concept board: '{cand_name}' "
                    f"(was: '{sector_data.get('sector_name', '')}' from industry)"
                )
                sector_data = new_sd
                break
    except Exception as e:
        logger.warning(f"Sector analysis skipped: {e}")

    sector_bonus = sector_data.get("bonus", 0) if sector_data else 0
    sc = score_stock(quote, ind, flow, all_news, sector_bonus)

    # Build filtered concept boards: hot/trending boards + core boards, max 10
    hot_keywords = set()
    if sector_data and sector_data.get("sector_name"):
        hot_keywords.add(sector_data["sector_name"])
    if hot_reason:
        for kw in re.split(r'[+、，,]+', hot_reason):
            kw = kw.strip()
            if len(kw) >= 2:
                hot_keywords.add(kw)

    filtered_boards = []
    # Pass 1: hot boards (matching sector name or hot reason keywords)
    for cb in concept_boards:
        bn = cb.get("board_name", "")
        is_hot = any(
            kw in bn or bn in kw
            for kw in hot_keywords
        ) if hot_keywords else False
        if is_hot:
            filtered_boards.append(cb)

    # Pass 2: core boards (first from original list, not already in filtered)
    seen = {cb["board_name"] for cb in filtered_boards}
    for cb in concept_boards:
        if cb["board_name"] not in seen:
            filtered_boards.append(cb)
            seen.add(cb["board_name"])
        if len(filtered_boards) >= 10:
            break

    # ---- pywencai valuation & events (zero-config, always available) ----
    pywencai_valuation = {}
    try:
        from astock_data import get_pywencai_valuation
        pywencai_valuation = get_pywencai_valuation(code)
        if pywencai_valuation:
            logger.info(f"pywencai valuation for {code}: PE={pywencai_valuation.get('pe_current')}, "
                       f"PE%={pywencai_valuation.get('pe_percentile')}")
    except Exception as e:
        logger.debug(f"pywencai valuation skipped: {e}")

    pywencai_events = []
    try:
        from astock_data import get_pywencai_recent_events
        pywencai_events = get_pywencai_recent_events(code)
        if pywencai_events:
            logger.info(f"pywencai events for {code}: {len(pywencai_events)} events")
    except Exception as e:
        logger.debug(f"pywencai events skipped: {e}")

    # Enrich data_10jqka with pywencai data
    data_10jqka["pywencai_valuation"] = pywencai_valuation
    data_10jqka["pywencai_events"] = pywencai_events

    return {
        "quote": quote, "name": name, "code": code,
        "ind": ind, "flow": flow, "news": all_news,
        "order_news": order_news, "sc": sc,
        "kline": kline, "sector_data": sector_data,
        "concept_boards": concept_boards,
        "filtered_concept_boards": filtered_boards,
        "data_10jqka": data_10jqka,
        "financial_data": financial_data,
        "peer_comparison": peer_comparison,
        "revenue_composition": revenue_composition,
        "pywencai_valuation": pywencai_valuation,
        "pywencai_events": pywencai_events,
    }


def format_report_text(code: str, data: dict = None) -> str:
    """Build a plain-text analysis report.

    If `data` is provided it must contain quote, ind, flow, news, sc,
    sector_data, name, concept_boards. Otherwise data is fetched fresh.
    """
    if data is None:
        data = build_analysis_data(code)
    if not data:
        return f"无法获取 {code} 的数据，请稍后重试。"

    quote = data["quote"]
    ind = data["ind"]
    flow = data["flow"]
    news = data.get("news", [])
    sc = data["sc"]
    sd = data.get("sector_data")
    name = data["name"]
    p = quote.get("price", 0)
    chg = quote.get("change_pct", 0)

    label_emoji = {"可做": "可做", "观察": "观察", "回避": "回避"}.get(sc["label"], "??")

    mv = quote.get("total_mv", 0)
    mv_str = f"{mv:.1f}亿" if mv > 0 else "N/A"
    lines = [
        f"{label_emoji} {name} ({code})  [{sc['label']}]",
        f"现价: {p:.2f}  涨跌: {chg:+.2f}%",
        f"PE: {quote.get('pe', 0):.1f}  市值: {mv_str}",
        "",
    ]

    if sd:
        lines.append("=== 板块分析 ===")
        lines.append(f"板块: {sd.get('sector_name', '')} | 周期: {sd.get('phase_cn', '')} | 因子: {sd.get('bonus', 0):+.1f}")
        for sig in sd.get("signals", []):
            lines.append(f"  - {sig}")
        lines.append("")

    # Concept boards — show filtered (hot + core), fall back to all
    cbs = data.get("filtered_concept_boards") or data.get("concept_boards", [])
    if cbs:
        lines.append("=== 概念板块 ===")
        lines.append("  ".join(f"#{c['board_name']}" for c in cbs[:8]))
        lines.append("")

    # 10jqka enrichment
    d10jqka = data.get("data_10jqka", {}) or {}
    if d10jqka:
        hot_reason = d10jqka.get("hot_reason")
        if hot_reason:
            lines.append(f"热点归因: {hot_reason}")
            lines.append("")
        eps = d10jqka.get("eps_forecast", {}) or {}
        eps_rows = eps.get("rows", [])
        if eps_rows:
            lines.append("=== 机构一致预期 ===")
            for row in eps_rows[:3]:
                line_parts = []
                for k, v in row.items():
                    line_parts.append(f"{k}={v}")
                lines.append(" | ".join(line_parts))
            lines.append("")

    if ind and "error" not in ind:
        lines.append("=== 技术面 ===")
        lines.append(f"MA5: {ind.get('ma5', 0)}  MA20: {ind.get('ma20', 0)}  MA60: {ind.get('ma60', 0)}")
        lines.append(f"MACD: DIF={ind.get('dif', 0)}  DEA={ind.get('dea', 0)}  柱={ind.get('macd_bar', 0)}")
        lines.append(f"RSI: {ind.get('rsi', 0)}  ATR: {ind.get('atr', 0)}  量比: {ind.get('vol_ratio', 0)}")
        lines.append(f"压力位: {ind.get('resistance', 0)}  支撑位: {ind.get('support', 0)}")

    if flow:
        lines.append("")
        lines.append("=== 资金面 ===")
        main_net = flow.get("main_net", 0)
        lines.append(f"主力净流入: {main_net / 1e4:.2f}亿 ({flow.get('main_pct', 0):.1f}%)")

    if news:
        lines.append("")
        lines.append("=== 最新资讯 ===")
        for n in news[:3]:
            t = (n.get("title", "") or "")[:60]
            lines.append(f"- {t}")

    lines.append("")
    lines.append("=== 双轨评分 ===")
    lines.append(f"短线动量: {sc['momentum']}  营收质量: {sc['revenue']}  风险约束: {sc['risk']}")
    if sd:
        lines.append(f"板块因子: {sd.get('bonus', 0):+.1f} ({sd.get('phase_cn', '')})")
    lines.append(f"加权总分: {sc['total']}  =>  {sc['label']}")
    lines.append("")
    lines.append("[警告] 仅供参考，不构成投资建议")

    return "\n".join(lines)
