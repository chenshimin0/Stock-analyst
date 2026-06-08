"""Tests for the post-filter (consistency check + sanity only).

New design (per user 2026-06-08):
- validator = "accountant", NOT "analyst"
- DeepSeek decides "what to pick" (business judgment)
- validator only checks: 主板 + 非 ST + Tencent has live quote
- NO mcap/PE/industry filter — DeepSeek's call
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sector_selector import validate_picks


def _mock_quote(monkeypatch, quotes_by_code: dict):
    from sector_selector import get_quote  # noqa
    def fake(code):
        return quotes_by_code.get(code, {})
    monkeypatch.setattr("sector_selector.get_quote", fake)


def test_validate_rejects_chinext(monkeypatch):
    """300750 宁德时代 should be rejected (创业板 — structural rule)."""
    _mock_quote(monkeypatch, {
        "300750": {"code": "300750", "name": "宁德时代", "pe": 20, "total_mv": 1000},
    })
    picks = [{"code": "300750", "name": "宁德时代", "reason": "龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("非主板" in r for r in rejected[0]["reject_reasons"])


def test_validate_rejects_star_market(monkeypatch):
    """688981 中芯国际 should be rejected (科创板)."""
    _mock_quote(monkeypatch, {
        "688981": {"code": "688981", "name": "中芯国际", "pe": 50, "total_mv": 300},
    })
    picks = [{"code": "688981", "name": "中芯国际", "reason": "芯片龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert len(rejected) == 1


def test_validate_rejects_bj_stock(monkeypatch):
    """830xxx BSE stocks should be rejected."""
    _mock_quote(monkeypatch, {
        "830799": {"code": "830799", "name": "某北交所", "pe": 30, "total_mv": 50},
    })
    picks = [{"code": "830799", "name": "某北交所", "reason": "x"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("非主板" in r for r in rejected[0]["reject_reasons"])


def test_validate_accepts_large_leader(monkeypatch):
    """万华化学 2200 亿 (大盘龙头) is now ACCEPTED (DeepSeek's call)."""
    _mock_quote(monkeypatch, {
        "600309": {"code": "600309", "name": "万华化学", "pe": 17, "total_mv": 2268.3},
    })
    picks = [{"code": "600309", "name": "万华化学", "reason": "六氟化钨上游协同"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 1
    assert len(rejected) == 0


def test_validate_accepts_negative_pe_leader(monkeypatch):
    """亏损大盘股也接受（DeepSeek 知道这是周期底部）."""
    _mock_quote(monkeypatch, {
        "600111": {"code": "600111", "name": "北方稀土", "pe": -50, "total_mv": 400},
    })
    picks = [{"code": "600111", "name": "北方稀土", "reason": "稀土龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 1
    assert len(rejected) == 0


def test_validate_rejects_st(monkeypatch):
    """ST 股 should be rejected (sanity)."""
    _mock_quote(monkeypatch, {
        "000789": {"code": "000789", "name": "ST华联", "pe": 10, "total_mv": 50},
    })
    picks = [{"code": "000789", "name": "ST华联", "reason": "x"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("ST" in r for r in rejected[0]["reject_reasons"])


def test_validate_rejects_nonexistent_code(monkeypatch):
    """Code that Tencent can't quote is rejected (DeepSeek fabricated it)."""
    _mock_quote(monkeypatch, {})  # empty — no quotes available
    picks = [{"code": "999999", "name": "某虚构股", "reason": "x"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("拉不到" in r for r in rejected[0]["reject_reasons"])


def test_validate_rejects_malformed_code(monkeypatch):
    """Non-6-digit code is rejected."""
    _mock_quote(monkeypatch, {})
    picks = [{"code": "abc", "name": "x", "reason": "y"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("6 位" in r for r in rejected[0]["reject_reasons"])


def test_validate_accepts_clean_picks(monkeypatch):
    """3 合规股票应被接受."""
    _mock_quote(monkeypatch, {
        "002812": {"code": "002812", "name": "恩捷股份", "pe": 25, "total_mv": 450},
        "002407": {"code": "002407", "name": "多氟多", "pe": 20, "total_mv": 180},
        "002460": {"code": "002460", "name": "赣锋锂业", "pe": 30, "total_mv": 500},
    })
    picks = [
        {"code": "002812", "name": "恩捷股份", "reason": "PVDF"},
        {"code": "002407", "name": "多氟多", "reason": "六氟"},
        {"code": "002460", "name": "赣锋锂业", "reason": "锂盐"},
    ]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 3
    assert len(rejected) == 0


def test_validate_accepts_mixed_sizes(monkeypatch):
    """Mix of large + small cap all accepted (size is DeepSeek's call)."""
    _mock_quote(monkeypatch, {
        "600309": {"code": "600309", "name": "万华化学", "pe": 17, "total_mv": 2268},
        "002812": {"code": "002812", "name": "恩捷股份", "pe": 25, "total_mv": 450},
        "300750": {"code": "300750", "name": "宁德时代", "pe": 20, "total_mv": 1000},  # 创业板
    })
    picks = [
        {"code": "600309", "name": "万华化学", "reason": "大龙头"},
        {"code": "002812", "name": "恩捷股份", "reason": "中盘"},
        {"code": "300750", "name": "宁德时代", "reason": "创业板"}  # rejected: 非主板
    ]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 2
    assert len(rejected) == 1
    assert rejected[0]["code"] == "300750"


# =================================================================
# Prompt tests
# =================================================================
def test_prompt_with_candidates_includes_table():
    from sector_selector import build_prompt_ai_knowledge
    candidates = [
        {"code": "600378", "name": "昊华科技", "mcap_yi": 499.82, "pe_ttm": 38.34},
        {"code": "002812", "name": "恩捷股份", "mcap_yi": 450, "pe_ttm": 25},
    ]
    p = build_prompt_ai_knowledge("pvdf", candidates)
    assert "pvdf" in p
    assert "600378" in p
    assert "昊华科技" in p
    assert "硬性条件" in p
    assert "候选池" in p
    # No market cap hard requirement
    assert "1000 亿" not in p
    assert "≤ 500" not in p


def test_prompt_without_candidates_uses_knowledge():
    from sector_selector import build_prompt_ai_knowledge
    p = build_prompt_ai_knowledge("pvdf", None)
    assert "pvdf" in p
    assert "概念板块" in p
    assert "候选池" not in p
    # Knowledge prompt no longer hard-caps market cap
    assert "1000 亿" not in p


def test_prompt_with_empty_candidates_uses_knowledge():
    from sector_selector import build_prompt_ai_knowledge
    p = build_prompt_ai_knowledge("太赫兹", [])
    assert "太赫兹" in p
    assert "候选池" not in p
