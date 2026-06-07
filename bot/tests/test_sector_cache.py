import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use in-memory sqlite for the cache test
from app.models.sector_pick import Base, SectorMemberCache  # type: ignore
from sector_selector import get_cached_members, save_cached_members


def test_cache_hit_within_24h():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    save_cached_members("pvdf", [
        {"stock_code": "002812", "stock_name": "恩捷股份"},
        {"stock_code": "002407", "stock_name": "多氟多"},
    ], s)
    out = get_cached_members("pvdf", s)
    assert len(out) == 2
    codes = {m["stock_code"] for m in out}
    assert codes == {"002812", "002407"}


def test_cache_miss_after_24h():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(SectorMemberCache(
        sector_name="pvdf",
        stock_code="002812",
        stock_name="恩捷股份",
        last_fetched_at=datetime.utcnow() - timedelta(hours=25),
    ))
    s.commit()
    out = get_cached_members("pvdf", s)
    assert out == []


def test_cache_upsert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    save_cached_members("pvdf", [{"stock_code": "002812", "stock_name": "恩捷股份"}], s)
    # Update name
    save_cached_members("pvdf", [{"stock_code": "002812", "stock_name": "恩捷股份(更新)"}], s)
    out = get_cached_members("pvdf", s)
    assert len(out) == 1
    assert out[0]["stock_name"] == "恩捷股份(更新)"
