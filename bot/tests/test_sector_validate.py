"""Tests for the post-filter that rejects DeepSeek picks violating hard rules."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sector_selector import validate_picks


def _mock_quote(monkeypatch, quotes_by_code: dict):
    """Patch astock_data.get_quote to return canned data per code."""
    from sector_selector import get_quote  # noqa
    def fake(code):
        return quotes_by_code.get(code, {})
    monkeypatch.setattr("sector_selector.get_quote", fake)


def test_validate_rejects_chinext(monkeypatch):
    """300750 宁德时代 should be rejected (创业板)."""
    _mock_quote(monkeypatch, {
        "300750": {"code": "300750", "name": "宁德时代", "pe": 20, "total_mv": 1000},
    })
    picks = [{"code": "300750", "name": "宁德时代", "reason": "龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("非主板" in r["reject_reasons"][0] for r in rejected)


def test_validate_rejects_star_market(monkeypatch):
    """688981 中芯国际 should be rejected (科创板)."""
    _mock_quote(monkeypatch, {
        "688981": {"code": "688981", "name": "中芯国际", "pe": 50, "total_mv": 300},
    })
    picks = [{"code": "688981", "name": "中芯国际", "reason": "芯片龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert len(rejected) == 1


def test_validate_rejects_oversized_market_cap(monkeypatch):
    """市值 1500 亿 > 1000 上限应被拒."""
    _mock_quote(monkeypatch, {
        "600703": {"code": "600703", "name": "三安光电", "pe": 30, "total_mv": 1500},
    })
    picks = [{"code": "600703", "name": "三安光电", "reason": "LED 龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("市值" in r and "1000" in r for r in rejected[0]["reject_reasons"])


def test_validate_accepts_1000yi_leader(monkeypatch):
    """市值 1000 亿（含）的行业龙头应被接受（用户优先级：龙头 > 市值要求）."""
    _mock_quote(monkeypatch, {
        "600519": {"code": "600519", "name": "贵州茅台", "pe": 25, "total_mv": 999.99},
    })
    picks = [{"code": "600519", "name": "贵州茅台", "reason": "白酒龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 1
    assert len(rejected) == 0


def test_validate_rejects_negative_pe(monkeypatch):
    """亏损股 PE 负数应被拒."""
    _mock_quote(monkeypatch, {
        "600111": {"code": "600111", "name": "北方稀土", "pe": -50, "total_mv": 400},
    })
    picks = [{"code": "600111", "name": "北方稀土", "reason": "稀土"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("亏损" in r for r in rejected[0]["reject_reasons"])


def test_validate_rejects_st(monkeypatch):
    """ST 股应被拒."""
    _mock_quote(monkeypatch, {
        "000789": {"code": "000789", "name": "ST华联", "pe": 10, "total_mv": 50},
    })
    picks = [{"code": "000789", "name": "ST华联", "reason": "x"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("ST" in r for r in rejected[0]["reject_reasons"])


def test_validate_accepts_clean_picks(monkeypatch):
    """合规股票应被接受."""
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


def test_validate_mixed_clean_and_dirty(monkeypatch):
    """1 只合规 + 2 只脏数据：返回 1 valid + 2 rejected，调用方应触发 DeepSeek 重试."""
    _mock_quote(monkeypatch, {
        "002812": {"code": "002812", "name": "恩捷股份", "pe": 25, "total_mv": 450},
        "600703": {"code": "600703", "name": "三安光电", "pe": -169, "total_mv": 843},
        "300750": {"code": "300750", "name": "宁德时代", "pe": 20, "total_mv": 1000},
    })
    picks = [
        {"code": "002812", "name": "恩捷股份", "reason": "PVDF"},
        {"code": "600703", "name": "三安光电", "reason": "x"},
        {"code": "300750", "name": "宁德时代", "reason": "y"},
    ]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 1
    assert len(rejected) == 2
    assert {r["code"] for r in rejected} == {"600703", "300750"}


# =================================================================
# New prompt tests (single-path: candidate pool or AI knowledge)
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
    # Market cap rendered as integer (499.82 -> 500), so check for code only
    assert "硬性条件" in p
    assert "候选池" in p


def test_prompt_without_candidates_uses_knowledge():
    from sector_selector import build_prompt_ai_knowledge
    p = build_prompt_ai_knowledge("pvdf", None)
    assert "pvdf" in p
    assert "概念板块" in p
    assert "候选池" not in p  # no table when no candidates
    # Knowledge prompt uses bullet list, not "硬性条件" header
    assert "沪深主板" in p
    assert "总市值" in p


def test_prompt_with_empty_candidates_uses_knowledge():
    from sector_selector import build_prompt_ai_knowledge
    p = build_prompt_ai_knowledge("太赫兹", [])
    assert "太赫兹" in p
    assert "候选池" not in p
