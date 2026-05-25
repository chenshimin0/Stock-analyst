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

from astock_data import get_quote, get_kline, get_fund_flow
from deep_report import compute_indicators, score_stock, fetch_rich_news, format_report_text
from queue_processor import save_report_to_web

try:
    from sector_lifecycle import analyze_sector_lifecycle
except ImportError:
    analyze_sector_lifecycle = None

try:
    from ai_analyzer import analyze_stock
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

    quote = get_quote(code)
    name = quote.get("name", name)
    price = quote.get("price", 0)

    if not name or price <= 0:
        print(f"FAILED: Cannot get quote for {code}")
        return False

    print(f"  Price: {price:.2f} ({quote.get('change_pct', 0):+.2f}%)")

    kline = get_kline(code, 120)
    ind = compute_indicators(kline) if kline else {}
    flow = get_fund_flow(code)

    rich = fetch_rich_news(code, name)
    all_news = rich["news_items"] + rich["order_events"] + rich["major_events"]
    order_news = rich["order_events"]

    sector_data = None
    if analyze_sector_lifecycle:
        sector_data = analyze_sector_lifecycle(code)
    sector_bonus = sector_data.get("bonus", 0) if sector_data else 0
    if sector_data:
        print(f"  Sector: {sector_data.get('sector_name', '')} -> {sector_data.get('phase_cn', '')} ({sector_bonus:+.1f})")

    sc = score_stock(quote, ind, flow, all_news, sector_bonus)

    print(f"  Score: {sc['total']} -> {sc['label']}")
    print(f"  News: {len(all_news)} items ({len(order_news)} orders)")

    ai_data = None
    if _AI_AVAILABLE:
        try:
            print("  Running AI analysis...")
            ai_data = analyze_stock(quote, ind, flow, all_news, kline, order_news)
            print("  AI analysis done")
        except Exception as e:
            logger.warning(f"AI analysis failed for {code}: {e}")

    save_report_to_web(code, name, quote, ind, flow, all_news, sc, kline, ai_data, order_news, sector_data)
    print(f"  Report saved to web backend")

    # Print summary
    print(format_report_text(code)[:300])

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
