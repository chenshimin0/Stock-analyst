"""
Deep Report builder — constructs analysis reports from a-stock-data layer.
=======================================================================
Data fetching via astock_data.py (a-stock-data skill APIs).
News classification + report formatting.
"""

import json
import logging
import re
import urllib.request
from datetime import date
from typing import Optional

from astock_data import get_quote, get_kline, get_fund_flow, search_news

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
    """Fetch and classify news from EastMoney search API."""
    result = {"news_items": [], "order_events": [], "major_events": []}
    raw_news = search_news(code, name, page_size=15)

    # Dedup by title
    seen = set()
    unique = []
    for n in raw_news:
        key = n.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(n)

    general, orders, majors = classify_news(unique)
    result["news_items"] = general[:15]
    result["order_events"] = orders[:10]
    result["major_events"] = majors[:10]

    logger.info(
        f"Rich news for {code}: news={len(result['news_items'])}, "
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

def score_stock(quote: dict, ind: dict, flow: dict, news: list, sector_bonus: float = 0) -> dict:
    """Dual-track scoring: momentum (40%) + revenue quality (35%) + risk (25%) + sector."""
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
        r -= 2.0
    news_text = " ".join(n.get("title", "") for n in news)
    if re.search(r"(增长|大增|超预期|扭亏)", news_text):
        r += 1.0
    if re.search(r"(下滑|亏损|下降|预亏)", news_text):
        r -= 1.0
    scores["revenue"] = round(max(1, min(10, r)), 1)

    # Risk
    risk = 6.0
    change = abs(quote.get("change_pct", 0))
    if change > 9:
        risk -= 2
    elif change > 5:
        risk -= 1
    if quote.get("pe", 0) > 100:
        risk -= 2
    if ind.get("rsi", 50) > 80:
        risk -= 1.5
    elif ind.get("rsi", 50) > 70:
        risk -= 0.5
    if main_net < 0:
        risk -= 0.5
    scores["risk"] = round(max(1, min(10, risk)), 1)

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

    # Sector lifecycle
    sector_data = None
    try:
        from sector_lifecycle import analyze_sector_lifecycle
        sector_data = analyze_sector_lifecycle(code)
    except Exception as e:
        logger.warning(f"Sector analysis skipped: {e}")

    sector_bonus = sector_data.get("bonus", 0) if sector_data else 0
    sc = score_stock(quote, ind, flow, all_news, sector_bonus)

    return {
        "quote": quote, "name": name, "code": code,
        "ind": ind, "flow": flow, "news": all_news,
        "order_news": order_news, "sc": sc,
        "kline": kline, "sector_data": sector_data,
    }


def format_report_text(code: str) -> str:
    """Build a plain-text analysis report (used by queue processor)."""
    data = build_analysis_data(code)
    if not data:
        return f"无法获取 {code} 的数据，请稍后重试。"

    quote = data["quote"]
    ind = data["ind"]
    flow = data["flow"]
    news = data["news"]
    sc = data["sc"]
    sd = data["sector_data"]
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

    if ind and "error" not in ind:
        lines.append("=== 技术面 ===")
        lines.append(f"MA5: {ind['ma5']}  MA20: {ind['ma20']}  MA60: {ind['ma60']}")
        lines.append(f"MACD: DIF={ind['dif']}  DEA={ind['dea']}  柱={ind['macd_bar']}")
        lines.append(f"RSI: {ind['rsi']}  ATR: {ind['atr']}  量比: {ind['vol_ratio']}")
        lines.append(f"压力位: {ind['resistance']}  支撑位: {ind['support']}")

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
