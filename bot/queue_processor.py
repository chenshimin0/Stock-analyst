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
    from ai_analyzer import analyze_stock
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

try:
    from sector_lifecycle import analyze_sector_lifecycle, analyze_sector_by_name
except ImportError:
    analyze_sector_lifecycle = None
    analyze_sector_by_name = None

# ---- config ----
QUEUE_DIR = os.getenv("QUEUE_DIR", "/Users/shiminchen/stock-analysis-system/backend/queue")
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


def save_report_to_web(code: str, name: str, quote: dict, ind: dict,
                       flow: dict, news: list, sc: dict, kline: list = None,
                       ai_data: dict = None, order_news: list = None,
                       sector_data: dict = None):
    """Save the complete analysis report to the web backend."""
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

        if ai_data:
            expert_data = ai_data.get("expert_opinions", {})
            recommendation = ai_data.get("recommendation", {})
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

            ai_scoring = ai_data.get("scoring_factors", {})
            if ai_scoring:
                scoring_factors = {
                    "momentum": ai_scoring.get("momentum", momentum_factors),
                    "revenue": ai_scoring.get("revenue", revenue_factors),
                    "risk": ai_scoring.get("risk", risk_factors),
                }
                if sector_data:
                    scoring_factors["hot_sector_bonus"] = sector_data.get("bonus", 0)
                    scoring_factors["hot_sector"] = hot_sector_factors

            fin_snapshot = ai_data.get("financial_snapshot", {})
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
            events_data = []
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

        # 2. DeepSeek AI analysis (runs BEFORE final sector resolution)
        ai_data = None
        if _AI_AVAILABLE:
            try:
                ai_data = analyze_stock(quote, ind, flow, news, kline, order_news)
                logger.info(f"AI analysis done for {code} {name}")
            except Exception as e:
                logger.warning(f"AI analysis failed for {code}, falling back to basic: {e}")

        # 3. Re-resolve sector from AI tags + re-score with AI qualitative adjustment
        if ai_data:
            if analyze_sector_by_name:
                tags = ai_data.get("tags", [])
                if tags:
                    ai_sector = tags[0]
                    current_sector = sector_data.get("sector_name", "") if sector_data else ""
                    if ai_sector != current_sector:
                        logger.info(f"Using AI tag sector: '{ai_sector}' (was: '{current_sector}')")
                        new_sd = analyze_sector_by_name(ai_sector, code)
                        if new_sd:
                            sector_data = new_sd

            sector_bonus = sector_data.get("bonus", 0) if sector_data else 0
            ai_scoring = ai_data.get("scoring_factors")
            sc = score_stock(quote, ind, flow, news, sector_bonus, ai_scoring=ai_scoring)
            logger.info(f"Re-scored with AI factors: total={sc['total']} ({sc['label']})")

        # 4. Save to web backend
        save_report_to_web(code, name, quote, ind, flow, news, sc,
                           kline, ai_data, order_news, sector_data)

        # 5. Print report summary
        report = format_report_text(code)
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
