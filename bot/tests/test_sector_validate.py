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
    """三安光电: 市值 843 亿 > 500."""
    _mock_quote(monkeypatch, {
        "600703": {"code": "600703", "name": "三安光电", "pe": -169, "total_mv": 843.64},
    })
    picks = [{"code": "600703", "name": "三安光电", "reason": "LED 龙头"}]
    valid, rejected = validate_picks(picks)
    assert len(valid) == 0
    assert any("市值" in r for r in rejected[0]["reject_reasons"])
    assert any("PE" in r or "亏损" in r for r in rejected[0]["reject_reasons"])


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
