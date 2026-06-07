from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.sector_pick import (
    Base, SectorPick, SectorPickStock, SectorMemberCache,
)

def test_create_sector_pick():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    pick = SectorPick(
        sector_name="pvdf", status="in_progress", selection_source="api_driven"
    )
    s.add(pick)
    s.commit()
    assert pick.id is not None
    assert pick.status == "in_progress"
    assert pick.created_at is not None
