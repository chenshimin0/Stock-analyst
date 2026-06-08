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
