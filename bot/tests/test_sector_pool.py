"""Tests for build_concept_candidate_pool (candidate pool builder)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from sector_selector import build_concept_candidate_pool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.sector_pick import Base, SectorMemberCache


def _empty_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_empty_pool_returns_list(monkeypatch):
    """Both realtime and cache empty -> returns []. No AttributeError."""
    from sector_selector import fetch_concept_members_realtime
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [],
    )
    db = _empty_db()
    out = build_concept_candidate_pool("nonexistent_concept", db)
    assert out == []


def test_cache_only_works(monkeypatch):
    """When realtime returns [] but cache has rows -> pool built from cache."""
    from sector_selector import fetch_concept_members_realtime
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [],
    )
    # Mock get_quote
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "600378": {"code": "600378", "name": "昊华科技", "total_mv": 499.82, "pe": 38.34, "pb": 2.42},
    }.get(code, {}))
    db = _empty_db()
    db.add(SectorMemberCache(
        sector_name="pvdf", stock_code="600378", stock_name="昊华科技",
    ))
    db.commit()
    out = build_concept_candidate_pool("pvdf", db)
    assert len(out) == 1
    assert out[0]["code"] == "600378"
    assert out[0]["name"] == "昊华科技"
    assert out[0]["mcap_yi"] == 499.82


def test_realtime_only_works(monkeypatch):
    """When cache empty but realtime has rows -> pool built from realtime."""
    from sector_selector import fetch_concept_members_realtime
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [{"stock_code": "002812", "stock_name": "恩捷股份"}] if name == "pvdf" else [],
    )
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "002812": {"code": "002812", "name": "恩捷股份", "total_mv": 450, "pe": 25, "pb": 5},
    }.get(code, {}))
    db = _empty_db()
    out = build_concept_candidate_pool("pvdf", db)
    assert len(out) == 1
    assert out[0]["code"] == "002812"


def test_cache_and_realtime_merged(monkeypatch):
    """Realtime + cache merged with realtime-first precedence (setdefault)."""
    from sector_selector import fetch_concept_members_realtime
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [{"stock_code": "002812", "stock_name": "恩捷股份(新版)"}],
    )
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "002812": {"code": "002812", "name": "X", "total_mv": 450, "pe": 25, "pb": 5},
        "600378": {"code": "600378", "name": "Y", "total_mv": 499, "pe": 38, "pb": 2},
    }.get(code, {}))
    db = _empty_db()
    db.add(SectorMemberCache(sector_name="pvdf", stock_code="600378", stock_name="昊华科技"))
    db.add(SectorMemberCache(sector_name="pvdf", stock_code="002812", stock_name="恩捷股份(旧)"))
    db.commit()
    out = build_concept_candidate_pool("pvdf", db)
    codes = {c["code"] for c in out}
    assert codes == {"002812", "600378"}
    # 002812 should keep the realtime name (newer)
    by_code = {c["code"]: c for c in out}
    assert by_code["002812"]["name"] == "恩捷股份(新版)"


def test_accepts_large_cap_leader(monkeypatch):
    """Large-cap leaders (e.g. 贵州茅台 1500 亿) are accepted into pool.
    Size is DeepSeek's call, not the pool's."""
    from sector_selector import fetch_concept_members_realtime
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [
            {"stock_code": "002812", "stock_name": "恩捷股份"},
            {"stock_code": "600519", "stock_name": "贵州茅台"},
        ],
    )
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "002812": {"code": "002812", "name": "恩捷股份", "total_mv": 450, "pe": 25, "pb": 5},
        "600519": {"code": "600519", "name": "贵州茅台", "total_mv": 1500, "pe": 25, "pb": 5},
    }.get(code, {}))
    db = _empty_db()
    out = build_concept_candidate_pool("test", db)
    assert len(out) == 2
    codes = {c["code"] for c in out}
    assert codes == {"002812", "600519"}


# =================================================================
# select_stocks_for_concept tests (pool as HINT, not whitelist)
# =================================================================
def test_select_accepts_picks_outside_small_pool(monkeypatch):
    """When the candidate pool has only 1 stock but DeepSeek picks 3, all 3
    should be accepted (pool is hint not strict whitelist)."""
    from sector_selector import (
        select_stocks_for_concept,
        fetch_concept_members_realtime,
    )
    # Pool has only 1 stock
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [{"stock_code": "002407", "stock_name": "多氟多"}],
    )
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "002407": {"code": "002407", "name": "多氟多", "total_mv": 358, "pe": 75, "pb": 5},
        "600309": {"code": "600309", "name": "万华化学", "total_mv": 2268, "pe": 17, "pb": 2},
        "600141": {"code": "600141", "name": "兴发集团", "total_mv": 351, "pe": 24, "pb": 1},
    }.get(code, {}))
    # DeepSeek returns 3 picks, only 1 in the pool
    deepseek_response = '{"picks":[{"code":"600309","name":"万华化学","reason":"龙头"},{"code":"002407","name":"多氟多","reason":"六氟"},{"code":"600141","name":"兴发集团","reason":"电子特气"}]}'
    def fake_deepseek(prompt):
        return deepseek_response
    db = _empty_db()
    result = select_stocks_for_concept("六氟化钨", db, fake_deepseek)
    assert "error" not in result
    assert len(result["picks"]) == 3
    codes = {p["code"] for p in result["picks"]}
    assert codes == {"600309", "002407", "600141"}


def test_select_rejects_fabricated_code(monkeypatch):
    """DeepSeek makes up a code that Tencent can't quote -> rejected, retry."""
    from sector_selector import select_stocks_for_concept
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [],
    )
    from sector_selector import get_quote
    # Tencent only knows 600309; DeepSeek invents 999999 and 888888
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "600309": {"code": "600309", "name": "万华化学", "total_mv": 2268, "pe": 17, "pb": 2},
    }.get(code, {}))
    # First attempt: DeepSeek returns 1 valid + 2 fabricated
    # Second attempt: DeepSeek returns same (no feedback because no rejected)
    # -> eventually error since retry won't help
    deepseek_response = '{"picks":[{"code":"600309","name":"万华化学","reason":"龙头"},{"code":"999999","name":"虚构A","reason":"x"},{"code":"888888","name":"虚构B","reason":"y"}]}'
    def fake_deepseek(prompt):
        return deepseek_response
    db = _empty_db()
    result = select_stocks_for_concept("test", db, fake_deepseek)
    assert "error" in result


def test_select_falls_back_to_knowledge_when_pool_too_small(monkeypatch):
    """When pool has only 1 stock, the prompt becomes confusing
    ('pick 3 from 1'). We should fall back to pure-knowledge mode."""
    from sector_selector import select_stocks_for_concept
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [{"stock_code": "600378", "stock_name": "昊华科技"}],  # pool=1
    )
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "600378": {"code": "600378", "name": "昊华科技", "total_mv": 500, "pe": 38, "pb": 2},
        "002407": {"code": "002407", "name": "多氟多", "total_mv": 358, "pe": 75, "pb": 5},
        "600141": {"code": "600141", "name": "兴发集团", "total_mv": 351, "pe": 24, "pb": 1},
        "600309": {"code": "600309", "name": "万华化学", "total_mv": 2268, "pe": 17, "pb": 2},
    }.get(code, {}))
    # Verify the prompt sent to DeepSeek does NOT include the 1-stock table
    captured_prompts = []
    def fake_deepseek(prompt):
        captured_prompts.append(prompt)
        return '{"picks":[{"code":"600378","name":"昊华科技","reason":"六氟"},{"code":"002407","name":"多氟多","reason":"氟化工"},{"code":"600141","name":"兴发集团","reason":"电子特气"}]}'
    db = _empty_db()
    result = select_stocks_for_concept("六氟化钨", db, fake_deepseek)
    assert "error" not in result
    assert len(result["picks"]) == 3
    # Source should be ai_knowledge (not candidates)
    assert result["source"] == "ai_knowledge"
    # Prompt should NOT include the 1-stock candidate table
    assert "候选池" not in captured_prompts[0]


def test_filters_out_chinext(monkeypatch):
    """300-prefix stocks (创业板) are filtered out."""
    from sector_selector import fetch_concept_members_realtime
    monkeypatch.setattr(
        "sector_selector.fetch_concept_members_realtime",
        lambda name: [{"stock_code": "300750", "stock_name": "宁德时代"}],
    )
    from sector_selector import get_quote
    monkeypatch.setattr("sector_selector.get_quote", lambda code: {
        "300750": {"code": "300750", "name": "宁德时代", "total_mv": 1000, "pe": 20, "pb": 5},
    }.get(code, {}))
    db = _empty_db()
    out = build_concept_candidate_pool("test", db)
    assert out == []
