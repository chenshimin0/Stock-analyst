from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.strategy_pick import StrategyPick, StrategyPickStock
from app.models.strategy import Strategy
from app.schemas import (
    StrategyPickListItem,
    StrategyPickDetail,
    StrategyStockMetric,
)

router = APIRouter(prefix="/strategy-picks", tags=["strategy-picks"])

PREVIEW_LIMIT = 8


def _avg(stocks, attr: str) -> Optional[float]:
    vals = [getattr(s, attr) for s in stocks if getattr(s, attr) is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _to_stock_metric(s: StrategyPickStock) -> StrategyStockMetric:
    return StrategyStockMetric(
        id=s.id,
        stock_code=s.stock_code,
        stock_name=s.stock_name,
        industry=s.industry,
        business_summary=s.business_summary,
        selection_reason=s.selection_reason,
        t0_date=s.t0_date,
        t0_price=s.t0_price,
        t3_date=s.t3_date, t3_price=s.t3_price, t3_pct=s.t3_pct,
        t7_date=s.t7_date, t7_price=s.t7_price, t7_pct=s.t7_pct,
        t15_date=s.t15_date, t15_price=s.t15_price, t15_pct=s.t15_pct,
        t30_date=s.t30_date, t30_price=s.t30_price, t30_pct=s.t30_pct,
    )


@router.get("", response_model=list[StrategyPickListItem])
def list_strategy_picks(
    status: Optional[str] = Query(None, pattern="^(in_progress|completed|archived)$"),
    strategy_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    """List strategy picks. Filter by status and/or strategy_id."""
    q = db.query(StrategyPick)
    if status:
        q = q.filter(StrategyPick.status == status)
    if strategy_id is not None:
        q = q.filter(StrategyPick.strategy_id == strategy_id)
    picks = q.order_by(StrategyPick.created_at.desc()).all()

    # Bulk-resolve strategy definitions in one query (avoid N+1)
    strat_ids = {p.strategy_id for p in picks}
    strat_map = {
        s.id: s for s in db.query(Strategy).filter(Strategy.id.in_(strat_ids)).all()
    } if strat_ids else {}

    out = []
    for p in picks:
        s_def = strat_map.get(p.strategy_id)
        out.append(StrategyPickListItem(
            id=p.id,
            strategy_id=p.strategy_id,
            status=p.status,
            hit_count=p.hit_count,
            created_at=p.created_at,
            completed_at=p.completed_at,
            query_text=s_def.query_text if s_def else "",
            strategy_name=s_def.name if s_def else f"#{p.strategy_id}",
            stocks_preview=[_to_stock_metric(s) for s in p.stocks[:PREVIEW_LIMIT]],
            avg_t3_pct=_avg(p.stocks, "t3_pct"),
            avg_t7_pct=_avg(p.stocks, "t7_pct"),
            avg_t15_pct=_avg(p.stocks, "t15_pct"),
            avg_t30_pct=_avg(p.stocks, "t30_pct"),
        ))
    return out


@router.get("/{pick_id}", response_model=StrategyPickDetail)
def get_strategy_pick(pick_id: int, db: Session = Depends(get_db)):
    p = db.query(StrategyPick).filter(StrategyPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Strategy pick not found")
    s_def = db.query(Strategy).filter(Strategy.id == p.strategy_id).first()
    return StrategyPickDetail(
        id=p.id,
        strategy_id=p.strategy_id,
        status=p.status,
        hit_count=p.hit_count,
        created_at=p.created_at,
        completed_at=p.completed_at,
        archived_at=p.archived_at,
        query_text=s_def.query_text if s_def else "",
        strategy_name=s_def.name if s_def else f"#{p.strategy_id}",
        avg_t3_pct=_avg(p.stocks, "t3_pct"),
        avg_t7_pct=_avg(p.stocks, "t7_pct"),
        avg_t15_pct=_avg(p.stocks, "t15_pct"),
        avg_t30_pct=_avg(p.stocks, "t30_pct"),
        stocks=[_to_stock_metric(s) for s in p.stocks],
    )


@router.post("/{pick_id}/archive")
def archive_strategy_pick(pick_id: int, db: Session = Depends(get_db)):
    p = db.query(StrategyPick).filter(StrategyPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Strategy pick not found")
    p.status = "archived"
    p.archived_at = datetime.utcnow()
    db.commit()
    return {"detail": "archived", "id": pick_id}
