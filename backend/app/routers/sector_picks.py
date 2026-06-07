from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.models.sector_pick import SectorPick, SectorPickStock, SectorMemberCache
from app.schemas.sector_pick import (
    SectorPickListItem, SectorPickDetail, StockMetric,
    SectorPickCreateRequest, SectorPickCreateResponse,
)

router = APIRouter(prefix="/sector-picks", tags=["sector-picks"])


@router.get("", response_model=List[SectorPickListItem])
def list_sector_picks(
    status: Optional[str] = Query(None, pattern="^(in_progress|completed|archived)$"),
    db: Session = Depends(get_db),
):
    q = db.query(SectorPick)
    if status:
        q = q.filter(SectorPick.status == status)
    picks = q.order_by(SectorPick.created_at.desc()).all()
    return [
        SectorPickListItem(
            id=p.id,
            sector_name=p.sector_name,
            status=p.status,
            selection_source=p.selection_source,
            created_at=p.created_at,
            avg_t5_pct=_avg(p.stocks, "t5_pct"),
            avg_t10_pct=_avg(p.stocks, "t10_pct"),
            avg_t20_pct=_avg(p.stocks, "t20_pct"),
        )
        for p in picks
    ]


@router.get("/{pick_id}", response_model=SectorPickDetail)
def get_sector_pick(pick_id: int, db: Session = Depends(get_db)):
    p = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Sector pick not found")
    return SectorPickDetail(
        id=p.id,
        sector_name=p.sector_name,
        status=p.status,
        selection_source=p.selection_source,
        created_at=p.created_at,
        completed_at=p.completed_at,
        archived_at=p.archived_at,
        avg_t5_pct=_avg(p.stocks, "t5_pct"),
        avg_t10_pct=_avg(p.stocks, "t10_pct"),
        avg_t20_pct=_avg(p.stocks, "t20_pct"),
        stocks=[
            StockMetric(
                code=s.stock_code,
                name=s.stock_name,
                reason=s.selection_reason,
                t0_price=s.t0_price,
                t5_pct=s.t5_pct,
                t10_pct=s.t10_pct,
                t20_pct=s.t20_pct,
            )
            for s in p.stocks
        ],
    )


@router.post("", response_model=SectorPickCreateResponse, status_code=201)
def create_sector_pick(req: SectorPickCreateRequest, db: Session = Depends(get_db)):
    """Create a new sector pick (used by bot internally)."""
    existing = (
        db.query(SectorPick)
        .filter(
            SectorPick.sector_name == req.sector_name,
            SectorPick.status.in_(["in_progress", "completed"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Sector '{req.sector_name}' already has an active pick (id={existing.id})",
        )
    pick = SectorPick(
        sector_name=req.sector_name,
        status="in_progress",
        selection_source=req.selection_source,
    )
    db.add(pick)
    db.flush()
    for s in req.stocks:
        db.add(SectorPickStock(
            sector_pick_id=pick.id,
            stock_code=s.code,
            stock_name=s.name,
            selection_reason=s.reason,
            t0_date=datetime.strptime(req.t0_date, "%Y-%m-%d").date(),
            t0_price=s.t0_price,
            t0_avg_price=s.t0_avg_price,
        ))
    db.commit()
    db.refresh(pick)
    return SectorPickCreateResponse(id=pick.id, created_at=pick.created_at)


@router.post("/{pick_id}/archive")
def archive_sector_pick(pick_id: int, db: Session = Depends(get_db)):
    p = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Sector pick not found")
    if p.status == "archived":
        return {"id": p.id, "status": p.status}
    p.status = "archived"
    p.archived_at = datetime.utcnow()
    db.commit()
    return {"id": p.id, "status": p.status}


@router.delete("/{pick_id}")
def delete_sector_pick(pick_id: int, db: Session = Depends(get_db)):
    """Hard-delete a sector pick and its stocks. Cascades to sector_pick_stocks."""
    p = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Sector pick not found")
    db.delete(p)  # cascade=delete-orphan on stocks relationship
    db.commit()
    return {"detail": "deleted", "id": pick_id}


def _avg(stocks, attr: str) -> Optional[float]:
    vals = [getattr(s, attr) for s in stocks if getattr(s, attr) is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)
