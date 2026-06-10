"""Smoke test for fetch_concept_members_realtime — runs against live THS API.

Prints diagnostic info; does not assert on counts because the API depends
on the date (weekend/holiday, theme activity, rate limits).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from sector_selector import fetch_concept_members_realtime

# Concepts that are likely to appear in 同花顺热点 reason tags over a multi-day window.
# Mix of trending themes; not exhaustive.
SAMPLES = [
    "算力",        # 算力租赁/算力概念
    "机器人",      # 机器人概念
    "AI",          # AI 通用
    "固态电池",
    "CPO",
    "PVDF",
    "太赫兹",
]

for concept in SAMPLES:
    print(f"\n--- concept: {concept!r} ---")
    try:
        members = fetch_concept_members_realtime(concept)
    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        continue
    print(f"  found {len(members)} member(s)")
    for m in members[:10]:
        print(f"    {m['stock_code']}  {m['stock_name']}")
