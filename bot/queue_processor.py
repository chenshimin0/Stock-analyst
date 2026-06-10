"""
Queue Processor — monitors the queue directory and processes stock analysis requests.
======================================================================================
Flow: read queue → astock_data → deep_report (indicators + scoring) → DeepSeek AI → save to web.

Designed to run as a standalone daemon or via Claude Code cron/loop.
Usage: python queue_processor.py [--once] [--watch]
"""

import json
import logging
import os
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

# Ensure bot directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from astock_data import get_quote
from deep_report import build_analysis_data, format_report_text, score_stock

try:
    from ai_analyzer import analyze_stock, analyze_stock_natural
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

try:
    from sector_lifecycle import analyze_sector_lifecycle, analyze_sector_by_name
except ImportError:
    analyze_sector_lifecycle = None
    analyze_sector_by_name = None

# ---- config ----
QUEUE_DIR = os.getenv("QUEUE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "queue"))
WEB_API_URL = os.getenv("WEB_API_URL", "http://localhost:8000/api")
POLL_INTERVAL = int(os.getenv("QUEUE_POLL_INTERVAL", "15"))  # seconds

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("queue_processor")


# ============================================================
# Web backend integration
# ============================================================

def _make_slug_safe(name: str) -> str:
    try:
        from pypinyin import pinyin, Style
        initials = pinyin(name, style=Style.FIRST_LETTER)
        return "".join([i[0].upper() for i in initials])
    except ImportError:
        return name.replace(" ", "")


def _build_default_experts(ind: dict, p: float, ma20: float,
                            stop_loss: float = None, atr_pct: float = 0) -> dict:
    """Build default expert opinions dict from technical indicators."""
    return {
        "技术分析派": {
            "conclusion": "MA多头排列" if ind.get("ma5", 0) > ind.get("ma20", 0) else "短期整理中",
            "key_points": [
                "当前价 {:.2f}，MA5={:.2f}，MA20={:.2f}".format(p, ind.get("ma5", 0), ind.get("ma20", 0)),
                "MACD DIF={:.3f}，{}状态".format(ind.get("dif", 0), "金叉" if ind.get("macd_bar", 0) > 0 else "死叉"),
                "RSI={:.1f}，{}".format(ind.get("rsi", 0), "偏多" if ind.get("rsi", 0) >= 50 else "偏弱"),
                "量比={:.2f}".format(ind.get("vol_ratio", 0)),
            ],
        },
        "风险控制官": {
            "conclusion": "止损={:.2f}".format(stop_loss) if stop_loss else "数据不足",
            "key_points": [
                "建议止损: {:.2f}".format(stop_loss) if stop_loss else "待定",
                "MA20支撑: {:.2f}".format(ma20) if ma20 > 0 else "待定",
            ],
        },
    }


def save_report_to_web(code: str, name: str, quote: dict, ind: dict,
                       flow: dict, news: list, sc: dict, kline: list = None,
                       ai_data: dict = None, order_news: list = None,
                       sector_data: dict = None, concept_boards: list = None,
                       filtered_concept_boards: list = None,
                       data_10jqka: dict = None, financial_data_raw: dict = None,
                       peer_comparison_raw: dict = None,
                       revenue_composition: dict = None):
    """Save the complete analysis report to the web backend."""
    # Ensure revenue composition is always populated — retry if empty
    if not revenue_composition or not revenue_composition.get("by_product"):
        try:
            from astock_data import get_revenue_composition_em
            rc = get_revenue_composition_em(code)
            if rc and rc.get("by_product"):
                revenue_composition = rc
                logger.info("Revenue composition re-fetched for %s: %d products",
                           code, len(rc["by_product"]))
        except Exception as e:
            logger.warning("Revenue composition re-fetch failed for %s: %s", code, e)

    # === New: 最近涨停日 (limit-up detection works reliably via Tencent K-line) ===
    last_limit_up_date = None
    last_limit_up_days_ago = None
    try:
        from astock_data import get_last_limit_up_date
        from datetime import date as _date
        last_limit_up_date = get_last_limit_up_date(code, lookback_days=180)
        if last_limit_up_date:
            try:
                lud = _date.fromisoformat(last_limit_up_date)
                last_limit_up_days_ago = (_date.today() - lud).days
            except Exception:
                last_limit_up_days_ago = None
    except Exception as e:
        logger.warning("Limit-up fetch failed for %s: %s", code, e)
    # Note: fund_flow_recent is left empty because EastMoney push2 API is blocked from this server
    fund_flow_recent = []
    try:
        p = quote.get("price", 0)
        atr = ind.get("atr", 0)
        ma20 = ind.get("ma20", 0)
        change_pct = quote.get("change_pct", 0)

        # --- scoring factors ---
        momentum_factors = []
        if ind.get("macd_bar", 0) > 0:
            momentum_factors.append(["MACD金叉状态，动能向上", "pos"])
        else:
            momentum_factors.append(["MACD偏弱", "neg"])
        rsi_val = ind.get("rsi", 50)
        if rsi_val >= 50:
            momentum_factors.append([f"RSI {rsi_val}，偏多未超买", "pos"])
        else:
            momentum_factors.append([f"RSI {rsi_val}，偏弱", "neg"])
        vol_ratio = ind.get("vol_ratio", 0)
        if vol_ratio > 1.2:
            momentum_factors.append([f"量比 {vol_ratio}，放量", "pos"])
        elif vol_ratio > 0.8:
            momentum_factors.append(["量比正常", "neu"])
        else:
            momentum_factors.append(["量能萎缩", "neg"])
        if ma20 > 0:
            dev_20 = abs(p - ma20) / ma20 * 100
            if dev_20 < 3:
                momentum_factors.append([f"偏离MA20 {dev_20:.1f}%，正常", "pos"])
            elif dev_20 < 5:
                momentum_factors.append([f"偏离MA20 {dev_20:.1f}%，偏高", "neu"])
            else:
                momentum_factors.append([f"偏离MA20 {dev_20:.1f}%，过高", "neg"])
        if change_pct > 0:
            momentum_factors.append([f"当日涨{change_pct:+.2f}%", "pos"])
        elif change_pct < 0:
            momentum_factors.append([f"当日跌{change_pct:+.2f}%", "neg"])

        revenue_factors = []
        pe = quote.get("pe", 0)
        if 0 < pe < 30:
            revenue_factors.append([f"PE {pe:.1f}，估值合理", "pos"])
        elif pe < 60:
            revenue_factors.append([f"PE {pe:.1f}，估值适中", "neu"])
        else:
            revenue_factors.append([f"PE {pe:.1f}，估值偏高", "neg"])
        if quote.get("total_mv", 0) > 0:
            revenue_factors.append([f"总市值 {quote['total_mv']:.0f}亿", "neu"])

        risk_factors = []
        atr_pct = atr / p * 100 if p > 0 else 0
        if atr_pct < 3:
            risk_factors.append([f"ATR {atr_pct:.1f}%，波动适中", "pos"])
        elif atr_pct < 5:
            risk_factors.append([f"ATR {atr_pct:.1f}%，波动偏高", "neu"])
        else:
            risk_factors.append([f"ATR {atr_pct:.1f}%，波动较高", "neg"])
        if rsi_val < 80:
            risk_factors.append(["RSI未超买，回调风险可控", "pos"])
        else:
            risk_factors.append(["RSI超买，注意回调", "neg"])
        if ma20 > 0:
            risk_factors.append([f"MA20 {ma20:.2f} 强支撑", "pos"])

        support = ind.get("support", 0)
        resistance = ind.get("resistance", 0)
        stop_loss = round(max(p - 1.5 * atr, support * 0.97), 2) if atr > 0 and p > 0 else None

        scoring_factors = {
            "momentum": momentum_factors,
            "revenue": revenue_factors,
            "risk": risk_factors,
        }

        if sector_data:
            sector_bonus = sector_data.get("bonus", 0)
            scoring_factors["hot_sector_bonus"] = sector_bonus
            hot_sector_factors = []
            hot_sector_factors.append([f"所属板块: {sector_data.get('sector_name', '')}", "neu"])
            hot_sector_factors.append([
                f"板块周期: {sector_data.get('phase_cn', '')}",
                "pos" if sector_bonus > 0 else ("neg" if sector_bonus < 0 else "neu")
            ])
            for sig in sector_data.get("signals", []):
                hot_sector_factors.append([sig, "pos" if sector_bonus > 0 else ("neg" if sector_bonus < 0 else "neu")])
            scoring_factors["hot_sector"] = hot_sector_factors

        # --- events_data: always built from news, regardless of AI ---
        events_data = []
        seen_titles = set()
        if order_news:
            for n in order_news[:5]:
                title = n.get("title", "")
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                events_data.append({
                    "title": title,
                    "impact": "利好",
                    "summary": (n.get("content", "") or title)[:200],
                    "source": n.get("source", "公告"),
                    "date": n.get("date", ""),
                    "url": n.get("url", ""),
                })
        if news:
            for n in news[:10]:
                title = n.get("title", "")
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                combined = title + (n.get("content", "") or "")
                impact = "中性"
                if any(kw in combined for kw in ["增长", "大涨", "突破", "利好", "签约", "中标", "投产", "扭亏", "高增", "回购"]):
                    impact = "利好"
                elif any(kw in combined for kw in ["下滑", "亏损", "下降", "预亏", "减持", "处罚", "监管", "问询", "风险"]):
                    impact = "利空"
                events_data.append({
                    "title": title,
                    "impact": impact,
                    "summary": (n.get("content", "") or n.get("source", ""))[:200],
                    "source": n.get("source", ""),
                    "date": n.get("date", ""),
                    "url": n.get("url", ""),
                })

        if ai_data:
            is_markdown_v2 = ai_data.get("_format") == "markdown_v2"
            expert_data = ai_data.get("expert_opinions", {})
            recommendation = ai_data.get("recommendation", {})
            ai_scoring = ai_data.get("scoring_factors", {})

            # Markdown v2: extract expert_data/recommendation from parsed sections
            if is_markdown_v2:
                if not expert_data:
                    expert_data = _build_default_experts(ind, p, ma20, stop_loss, atr_pct)
                if not recommendation:
                    rec_text = ai_data.get("recommendation_and_risk", "")
                    recommendation = {
                        "short_term": rec_text[:200] if rec_text else "详见AI分析",
                        "stop_loss": f"{stop_loss:.2f}" if stop_loss else "待定",
                        "position_advice": "参考AI分析建议",
                        "risk_warning": f"ATR波动率{atr_pct:.1f}%，注意仓位管理" if atr_pct > 3 else "详见风险提示",
                    }

            if ai_scoring:
                scoring_factors = {
                    "momentum": ai_scoring.get("momentum", momentum_factors),
                    "revenue": ai_scoring.get("revenue", revenue_factors),
                    "risk": ai_scoring.get("risk", risk_factors),
                }
                if sector_data:
                    scoring_factors["hot_sector_bonus"] = sector_data.get("bonus", 0)
                    scoring_factors["hot_sector"] = hot_sector_factors

            # Financial snapshot: prefer crawled data for markdown_v2
            fin_snapshot = ai_data.get("financial_snapshot", {})
            if is_markdown_v2 and not fin_snapshot and financial_data_raw:
                ann = (financial_data_raw.get("annual") or [])
                latest_ann = ann[-1] if ann else {}
                fin_snapshot = {
                    "revenue": latest_ann.get("revenue", "N/A"),
                    "revenue_yoy": "{:+.1f}%".format(latest_ann["revenue_yoy"]) if latest_ann.get("revenue_yoy") is not None else "N/A",
                    "net_profit": latest_ann.get("net_profit", "N/A"),
                    "net_profit_yoy": "{:+.1f}%".format(latest_ann["net_profit_yoy"]) if latest_ann.get("net_profit_yoy") is not None else "N/A",
                    "gross_margin": "{:.1f}%".format(latest_ann["gross_margin"]) if latest_ann.get("gross_margin") is not None else "N/A",
                    "roe": "{:.1f}%".format(latest_ann["roe_weighted"]) if latest_ann.get("roe_weighted") is not None else "N/A",
                    "debt_ratio": "{:.1f}%".format(latest_ann["debt_ratio"]) if latest_ann.get("debt_ratio") is not None else "N/A",
                    "dividend_yield": "N/A",
                    "pe_ttm": str(pe) if pe > 0 else "N/A",
                    "pb": "N/A",
                }

            # ALWAYS override critical fields with real API data (avoid AI hallucination)
            real_pb = quote.get("pb", 0)
            if real_pb and real_pb > 0:
                fin_snapshot["pb"] = f"{real_pb:.2f}"
            if not fin_snapshot.get("pe_ttm") or fin_snapshot.get("pe_ttm") == "N/A":
                if pe > 0:
                    fin_snapshot["pe_ttm"] = f"{pe:.1f}"

            # Override company_profile with real F10 data
            try:
                import urllib.request, gzip
                market = "SH" if code.startswith(("6", "9")) else "SZ"
                f10_url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={market}{code}"
                req = urllib.request.Request(f10_url, headers={"Referer": "https://emweb.securities.eastmoney.com/"})
                raw = urllib.request.urlopen(req, timeout=5).read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                import json as _json
                f10 = _json.loads(raw)
                jbzl = f10.get("jbzl", {}) or {}
                fxxg = f10.get("fxxg", {}) or {}

                cp = ai_data.get("company_profile", {}) or {}
                if not cp.get("full_name") or cp.get("full_name") == "数据暂缺":
                    cp["full_name"] = jbzl.get("gsmc", code)
                if not cp.get("founded_listed") or "数据暂缺" in str(cp.get("founded_listed", "")):
                    clrq = (fxxg.get("clrq") or "")[:4]
                    ssrq = (fxxg.get("ssrq") or "")[:4]
                    if clrq and ssrq:
                        cp["founded_listed"] = f"成立{clrq}年 / 上市{ssrq}年"
                if not cp.get("headquarters") or cp.get("headquarters") == "数据暂缺":
                    if jbzl.get("bgdz"):
                        cp["headquarters"] = jbzl["bgdz"]
                if not cp.get("industry") or cp.get("industry") == "数据暂缺":
                    if jbzl.get("sshy"):
                        cp["industry"] = jbzl["sshy"]

                # Auto-compute business_segments from revenue_composition_raw
                if revenue_composition and revenue_composition.get("by_product"):
                    bp = revenue_composition["by_product"]
                    total = sum(p.get("revenue", 0) for p in bp)
                    if total > 0 and (not cp.get("business_segments") or
                                       any("数据暂缺" in str(seg.get("revenue_share", "")) for seg in cp.get("business_segments", []))):
                        cp["business_segments"] = [
                            {
                                "name": p["name"],
                                "revenue_share": f"约{p['ratio_pct']}%",
                                "description": f"营收{p['revenue']/1e8:.1f}亿，毛利率{p.get('gross_margin_pct', 0)}%" if p.get('gross_margin_pct') is not None else f"营收{p['revenue']/1e8:.1f}亿"
                            } for p in bp[:5]
                        ]

                ai_data["company_profile"] = cp
            except Exception as e:
                logger.warning(f"F10 company info fetch failed for {code}: {e}")
            financial_data = {
                "市盈率(动态)": f"{pe:.1f}倍" if pe > 0 else "N/A",
                "总市值(亿)": f"{quote.get('total_mv', 0):.1f}" if quote.get('total_mv', 0) > 0 else "N/A",
                "当日涨跌幅": f"{change_pct:+.2f}%",
                "换手率": f"{quote.get('turnover', 0):.2f}%" if quote.get('turnover', 0) else "N/A",
                "成交量(手)": f"{quote.get('volume', 0) / 1e4:.0f}万" if quote.get('volume', 0) > 0 else "N/A",
                "营收(亿)": fin_snapshot.get("revenue", "N/A"),
                "营收增速": fin_snapshot.get("revenue_yoy", "N/A"),
                "净利(亿)": fin_snapshot.get("net_profit", "N/A"),
                "净利增速": fin_snapshot.get("net_profit_yoy", "N/A"),
                "毛利率": fin_snapshot.get("gross_margin", "N/A"),
                "ROE": fin_snapshot.get("roe", "N/A"),
                "资产负债率": fin_snapshot.get("debt_ratio", "N/A"),
                "股息率": fin_snapshot.get("dividend_yield", "N/A"),
                "PE(TTM)": fin_snapshot.get("pe_ttm", str(pe) if pe > 0 else "N/A"),
                "PB": fin_snapshot.get("pb", "N/A"),
            }
            ai_analysis = ai_data
        else:
            expert_data = {
                "技术分析派": {
                    "conclusion": f"MA多头排列" if ind.get("ma5", 0) > ind.get("ma20", 0) else "短期整理中",
                    "key_points": [
                        f"当前价 {p:.2f}，MA5={ind.get('ma5', 0):.2f}，MA20={ind.get('ma20', 0):.2f}",
                        f"MACD DIF={ind.get('dif', 0):.3f}，{'金叉' if ind.get('macd_bar', 0) > 0 else '死叉'}状态",
                        f"RSI={ind.get('rsi', 0):.1f}，{'偏多' if ind.get('rsi', 0) >= 50 else '偏弱'}",
                        f"量比={ind.get('vol_ratio', 0):.2f}",
                    ],
                },
                "风险控制官": {
                    "conclusion": f"止损={stop_loss:.2f}" if stop_loss else "数据不足",
                    "key_points": [
                        f"建议止损: {stop_loss:.2f}" if stop_loss else "待定",
                        f"MA20支撑: {ma20:.2f}" if ma20 > 0 else "待定",
                    ],
                },
            }
            recommendation = {
                "short_term": f"入场区间 {support:.2f}-{p:.2f}" if support > 0 else "待定",
                "stop_loss": f"{stop_loss:.2f}（1.5倍ATR止损）" if stop_loss else "待定",
                "position_advice": "3-5成仓位，分2-3次建仓",
                "risk_warning": f"ATR波动率{atr_pct:.1f}%，注意仓位管理" if atr_pct > 3 else "技术面正常",
            }
            financial_data = {
                "市盈率(动态)": f"{pe:.1f}倍" if pe > 0 else "N/A",
                "总市值(亿)": f"{quote.get('total_mv', 0):.1f}" if quote.get('total_mv', 0) > 0 else "N/A",
                "当日涨跌幅": f"{change_pct:+.2f}%",
                "换手率": f"{quote.get('turnover', 0):.2f}%" if quote.get('turnover', 0) else "N/A",
                "成交量(手)": f"{quote.get('volume', 0) / 1e4:.0f}万" if quote.get('volume', 0) > 0 else "N/A",
            }
            ai_analysis = None

        payload = {
            "stock_code": code,
            "stock_name": name,
            "report_date": str(date.today()),
            "price_at_report": p,
            "momentum_score": sc.get("momentum", 0),
            "revenue_score": sc.get("revenue", 0),
            "risk_score": sc.get("risk", 0),
            "total_score": sc.get("total", 0),
            "label": sc.get("label", ""),
            "scoring_factors": scoring_factors,
            "sector_data": sector_data,
            "technical_data": {
                "当前价格": f"{p:.2f} ({change_pct:+.2f}%)",
                "ATR(14)": f"{atr:.2f} ({atr_pct:.1f}%)",
                "RSI(14)": ind.get("rsi", 0),
                "MA5": ind.get("ma5", 0),
                "MA10": ind.get("ma10", 0),
                "MA20": ind.get("ma20", 0),
                "MA60": ind.get("ma60", 0),
                "量比(5/20日)": ind.get("vol_ratio", 0),
                "MACD DIF": ind.get("dif", 0),
                "support_1": f"{support:.2f} (20日低点)",
                "support_2": f"{ma20:.2f} (MA20)" if ma20 > 0 else "--",
                "resistance_1": f"{resistance:.2f} (20日高点)",
                "resistance_2": f"{p * 1.05:.2f} (+5%)" if p > 0 else "--",
                "近5日均量": f"{ind.get('vol_ratio', 0) * 100:.0f}%" if ind.get('vol_ratio') else "--",
            },
            "financial_data": financial_data,
            "events_data": events_data,
            "expert_data": expert_data,
            "recommendation": recommendation,
            "ai_analysis": ai_analysis,
            "concept_boards": concept_boards or [],
            "filtered_concept_boards": filtered_concept_boards or [],
            "sector_data": sector_data,
            "data_10jqka": data_10jqka or {},
            "financial_data_raw": financial_data_raw or {},
            "peer_comparison_raw": peer_comparison_raw or {},
            "revenue_composition_raw": revenue_composition or {},
            "fund_flow_recent": fund_flow_recent,
            "last_limit_up_date": last_limit_up_date,
            "last_limit_up_days_ago": last_limit_up_days_ago,
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{WEB_API_URL}/reports", data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"Report saved to web: {code} {name} score={sc.get('total', 0)} label={sc.get('label', '')}")
    except Exception as e:
        logger.warning(f"Save report to web failed (backend may be down): {e}")


# ============================================================
# Queue processing
# ============================================================

def process_one(code: str, name: str = "") -> bool:
    """Process a single stock analysis request. Returns True on success.

    Flow: data → AI first → extract sector from AI tags → sector lifecycle → score → save.
    """
    logger.info(f"Processing: {code} {name}")
    try:
        # 1. Data layer (a-stock-data skill APIs)
        data = build_analysis_data(code)
        if not data:
            logger.error(f"Data fetch failed for {code}")
            return False

        quote = data["quote"]
        name = data["name"] or name
        ind = data["ind"]
        flow = data["flow"]
        news = data["news"]
        order_news = data["order_news"]
        sc = data["sc"]
        kline = data["kline"]
        sector_data = data.get("sector_data")
        concept_boards = data.get("concept_boards", [])
        filtered_concept_boards = data.get("filtered_concept_boards", [])
        data_10jqka = data.get("data_10jqka", {})
        financial_data = data.get("financial_data", {})
        peer_comparison = data.get("peer_comparison", {})
        revenue_composition = data.get("revenue_composition", {})

        # 2. DeepSeek AI analysis — runs both structured JSON + natural Markdown
        ai_data = None
        if _AI_AVAILABLE:
            # Phase A: structured JSON analysis (primary — all data sections)
            try:
                ai_data = analyze_stock(quote, ind, flow, news, kline, order_news, data_10jqka, financial_data, peer_comparison, revenue_composition)
                logger.info("AI structured analysis done for %s %s", code, name)
            except Exception as e:
                logger.warning("AI structured analysis failed for %s: %s", code, e)

            # Phase B: natural Markdown analysis (supplement — narrative sections)
            try:
                ai_md = analyze_stock_natural(quote, ind, flow, news, kline, order_news, data_10jqka, financial_data, peer_comparison, revenue_composition)
                if ai_data and ai_md:
                    # Merge: keep all structured JSON fields, add narrative Markdown sections
                    ai_data["_format"] = "merged"
                    for md_key in ["financial_analysis", "business_and_logic",
                                   "order_and_strategy", "recommendation_and_risk"]:
                        md_val = ai_md.get(md_key, "")
                        if md_val:
                            ai_data["md_" + md_key] = md_val
                    # Use Markdown tags if more specific than JSON tags
                    md_tags = ai_md.get("tags", [])
                    json_tags = ai_data.get("tags", [])
                    if md_tags and (not json_tags or len(md_tags) > len(json_tags)):
                        pass  # keep JSON tags (more reliable from structured prompt)
                    logger.info("AI narrative analysis merged for %s %s", code, name)
                elif ai_md and not ai_data:
                    ai_data = ai_md  # fallback: use Markdown if JSON failed
                    logger.info("AI narrative only (JSON failed) for %s %s", code, name)
            except Exception as e:
                logger.warning("AI narrative analysis failed for %s: %s", code, e)

        # 3. Re-resolve sector: try all AI tags against concept boards, pick best match.
        # Board position matters: earlier boards (index 0) are more relevant to the stock.
        # Score = text_match_score × (1 + position_weight).
        if ai_data and analyze_sector_by_name:
            tags = ai_data.get("tags", [])
            current_sector = sector_data.get("sector_name", "") if sector_data else ""
            candidates = []  # (name, score)
            for idx, board in enumerate(concept_boards):
                board_name = board["board_name"]
                # Position weight: first board gets +0.5, decays to 0 at index 20+
                pos_weight = max(0, 0.5 * (1 - idx / 20))
                best_tag_score = 0.0
                for tag in tags:
                    if tag == current_sector:
                        continue
                    if tag in board_name:
                        # Tag is a substring of board name (e.g. "氟化工" in "氟化工概念")
                        best_tag_score = max(best_tag_score, 0.95)
                    elif board_name in tag:
                        # Board name is a substring of tag
                        best_tag_score = max(best_tag_score, 0.9)
                    elif tag and board_name:
                        # Partial character overlap fallback
                        overlap = len(set(tag) & set(board_name)) / max(len(tag), len(board_name))
                        best_tag_score = max(best_tag_score, overlap * 0.7)
                if best_tag_score > 0:
                    candidates.append((board_name, best_tag_score * (1 + pos_weight)))
                elif idx < 5:
                    # Top-5 boards always considered (low base score from position alone)
                    if board_name != current_sector:
                        candidates.append((board_name, 0.3 * (1 + pos_weight)))
            # Try candidates in score order, pick first valid sector
            matched = None
            for cand_name, score in sorted(candidates, key=lambda x: -x[1]):
                new_sd = analyze_sector_by_name(cand_name, code)
                if new_sd:
                    matched = cand_name
                    sector_data = new_sd
                    break
            if matched:
                logger.info(f"AI tag '{matched}' -> sector '{sector_data.get('sector_name', '')}' (was: '{current_sector}')")

        if ai_data:
            sector_bonus = sector_data.get("bonus", 0) if sector_data else 0
            ai_scoring = ai_data.get("scoring_factors")
            sc = score_stock(quote, ind, flow, news, sector_bonus, ai_scoring=ai_scoring)
            logger.info(f"Re-scored with AI factors: total={sc['total']} ({sc['label']})")

        # 4. Save to web backend
        save_report_to_web(code, name, quote, ind, flow, news, sc,
                           kline, ai_data, order_news, sector_data, concept_boards,
                           filtered_concept_boards,
                           data_10jqka, financial_data, peer_comparison,
                           revenue_composition=revenue_composition)

        # 5. Print report summary (use updated sc & sector_data)
        data["sc"] = sc
        data["sector_data"] = sector_data
        report = format_report_text(code, data=data)
        logger.info(f"Report generated for {code} {name}\n{report[:500]}...")

        return True
    except Exception as e:
        logger.error(f"Process failed for {code}: {e}", exc_info=True)
        return False


def process_queue():
    """Process all pending items in the queue directory."""
    if not os.path.isdir(QUEUE_DIR):
        logger.warning(f"Queue directory does not exist: {QUEUE_DIR}")
        return

    files = sorted(
        [f for f in os.listdir(QUEUE_DIR) if f.endswith(".json")],
        key=lambda f: os.path.getmtime(os.path.join(QUEUE_DIR, f)),
    )

    if not files:
        logger.debug("Queue is empty")
        return

    logger.info(f"Found {len(files)} queued item(s)")

    for fname in files:
        fpath = os.path.join(QUEUE_DIR, fname)
        try:
            with open(fpath) as f:
                req = json.load(f)
            code = req.get("stock_code", "")
            name = req.get("stock_name", "")

            if not code:
                logger.warning(f"Invalid queue entry: {fname}")
                os.remove(fpath)
                continue

            success = process_one(code, name)

            if success:
                os.remove(fpath)
                logger.info(f"Completed & removed: {fname}")
            else:
                # Keep the file for retry, but rename to avoid infinite loop
                fail_path = fpath + ".failed"
                os.rename(fpath, fail_path)
                logger.warning(f"Failed, moved to: {fail_path}")

        except json.JSONDecodeError:
            logger.warning(f"Corrupt queue file: {fname}, removing")
            os.remove(fpath)
        except Exception as e:
            logger.error(f"Error processing {fname}: {e}")


# ============================================================
# Main
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Queue Processor for Stock Analysis")
    parser.add_argument("--once", action="store_true", help="Process queue once and exit")
    parser.add_argument("--watch", action="store_true", help="Watch queue continuously")
    parser.add_argument("--code", type=str, help="Process a single stock code directly")
    args = parser.parse_args()

    if args.code:
        success = process_one(args.code)
        sys.exit(0 if success else 1)

    if args.once:
        process_queue()
        return

    if args.watch:
        logger.info(f"Watching queue directory: {QUEUE_DIR} (poll every {POLL_INTERVAL}s)")
        while True:
            try:
                process_queue()
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
            time.sleep(POLL_INTERVAL)

    # Default: --once
    process_queue()


if __name__ == "__main__":
    main()
