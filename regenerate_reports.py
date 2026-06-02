"""
Regenerate all existing reports with 5-minute intervals (v2).
Uses a-stock-data APIs + DeepSeek AI.

Run on server: cd /home/ubuntu/stock-analysis-system/bot && python3 regenerate_reports.py
"""
import sys
import os
import time
import logging

# Ensure bot directory is importable
_BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot")
sys.path.insert(0, _BOT_DIR)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("regenerate")

from deep_report import build_analysis_data, score_stock, format_report_text
from queue_processor import save_report_to_web

try:
    from sector_lifecycle import analyze_sector_lifecycle, analyze_sector_by_name
except ImportError:
    analyze_sector_lifecycle = None
    analyze_sector_by_name = None

try:
    from ai_analyzer import analyze_stock, analyze_stock_natural
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

STOCKS = [
    ("600584", "长电科技"),
    ("603337", "杰克科技"),
    ("000636", "风华高科"),
    ("002015", "协鑫能科"),
    ("002645", "华宏科技"),
    ("002281", "光迅科技"),
    ("001266", "宏英智能"),
    ("603283", "赛腾股份"),
]

INTERVAL_SECONDS = 5 * 60


def regenerate_one(code: str, name: str) -> bool:
    print(f"\n{'='*60}")
    print(f"Regenerating {name} ({code})...")
    print(f"{'='*60}")

    # Use build_analysis_data for full data pipeline (10jqka, concept boards, sector, etc.)
    data = build_analysis_data(code)
    if not data:
        print(f"FAILED: Cannot fetch data for {code}")
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

    price = quote.get("price", 0)
    print(f"  Price: {price:.2f} ({quote.get('change_pct', 0):+.2f}%)")

    if sector_data:
        print(f"  Sector: {sector_data.get('sector_name', '')} -> {sector_data.get('phase_cn', '')} ({sector_data.get('bonus', 0):+.1f})")
    if concept_boards:
        names = [c['board_name'] for c in concept_boards[:8]]
        print(f"  Concepts: {', '.join(names)}")

    print(f"  Score: {sc['total']} -> {sc['label']}")
    print(f"  News: {len(news)} items ({len(order_news)} orders)")

    # AI analysis — structured JSON (primary) + natural Markdown (supplement)
    ai_data = None
    if _AI_AVAILABLE:
        try:
            print("  Running AI structured analysis (JSON)...")
            ai_data = analyze_stock(quote, ind, flow, news, kline, order_news, data_10jqka, financial_data, peer_comparison, revenue_composition)
            print("  AI structured analysis done")
        except Exception as e:
            logger.warning(f"AI structured analysis failed for {code}: {e}")

        try:
            print("  Running AI narrative analysis (Markdown)...")
            ai_md = analyze_stock_natural(quote, ind, flow, news, kline, order_news, data_10jqka, financial_data, peer_comparison, revenue_composition)
            if ai_data and ai_md:
                ai_data["_format"] = "merged"
                for md_key in ["financial_analysis", "business_and_logic",
                               "order_and_strategy", "recommendation_and_risk"]:
                    md_val = ai_md.get(md_key, "")
                    if md_val:
                        ai_data["md_" + md_key] = md_val
                print("  AI narrative analysis merged")
            elif ai_md and not ai_data:
                ai_data = ai_md
                print("  AI narrative only (structured failed)")
        except Exception as e:
            logger.warning(f"AI narrative analysis failed for {code}: {e}")

    # Re-resolve sector using AI tags
    if ai_data and analyze_sector_by_name:
        tags = ai_data.get("tags", [])
        current_sector = sector_data.get("sector_name", "") if sector_data else ""
        matched = None
        for tag in tags:
            if tag == current_sector:
                continue
            new_sd = analyze_sector_by_name(tag, code)
            if new_sd:
                matched = tag
                sector_data = new_sd
                break
        if matched:
            print(f"  AI tag '{matched}' -> sector '{sector_data.get('sector_name', '')}' (was: '{current_sector}')")

    # Re-score with AI factors
    if ai_data:
        sector_bonus = sector_data.get("bonus", 0) if sector_data else 0
        ai_scoring = ai_data.get("scoring_factors")
        sc = score_stock(quote, ind, flow, news, sector_bonus, ai_scoring=ai_scoring)
        print(f"  Re-scored: {sc['total']} -> {sc['label']}")

    save_report_to_web(code, name, quote, ind, flow, news, sc,
                       kline, ai_data, order_news, sector_data, concept_boards,
                       filtered_concept_boards,
                       data_10jqka, financial_data, peer_comparison,
                       revenue_composition=revenue_composition)
    print(f"  Report saved to web backend")

    print(format_report_text(code, data=data)[:300])

    return True


def main():
    total = len(STOCKS)
    for i, (code, name) in enumerate(STOCKS):
        try:
            regenerate_one(code, name)
        except Exception as e:
            logger.error(f"Failed {code} {name}: {e}")

        if i < total - 1:
            next_name = STOCKS[i + 1][1]
            print(f"\n  Waiting {INTERVAL_SECONDS // 60} minutes until next ({next_name})...")
            time.sleep(INTERVAL_SECONDS)

    print(f"\n{'='*60}")
    print("All reports regenerated!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
