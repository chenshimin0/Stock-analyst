"""
Strategy CRUD router + manual run / toggle.

Endpoints:
  GET    /api/strategies                  list all strategies (with pick counts)
  GET    /api/strategies/{id}             detail (definition only)
  POST   /api/strategies                  create
  PUT    /api/strategies/{id}             update (any subset)
  DELETE /api/strategies/{id}             delete (cascades to picks)
  POST   /api/strategies/{id}/toggle      flip enabled flag
  POST   /api/strategies/{id}/run         manual run (sync, returns {batch_id, hit_count})
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Strategy
from app.schemas import StrategyOut, StrategyCreate, StrategyUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _to_out(s: Strategy) -> StrategyOut:
    return StrategyOut(
        id=s.id,
        name=s.name,
        query_text=s.query_text,
        schedule_cron=s.schedule_cron,
        enabled=s.enabled,
        created_at=s.created_at,
        updated_at=s.updated_at,
        total_picks=len(s.picks),
        last_pick_at=max((p.created_at for p in s.picks), default=None),
    )


@router.get("", response_model=list[StrategyOut])
def list_strategies(db: Session = Depends(get_db)):
    rows = db.query(Strategy).order_by(Strategy.id).all()
    return [_to_out(s) for s in rows]


@router.get("/{sid}", response_model=StrategyOut)
def get_strategy(sid: int, db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == sid).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    return _to_out(s)


@router.post("", response_model=StrategyOut, status_code=201)
def create_strategy(data: StrategyCreate, db: Session = Depends(get_db)):
    if db.query(Strategy).filter(Strategy.name == data.name).first():
        raise HTTPException(409, f"Strategy name '{data.name}' already exists")
    s = Strategy(
        name=data.name,
        query_text=data.query_text,
        schedule_cron=data.schedule_cron,
        enabled=data.enabled,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.put("/{sid}", response_model=StrategyOut)
def update_strategy(sid: int, data: StrategyUpdate, db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == sid).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    if data.name is not None and data.name != s.name:
        if db.query(Strategy).filter(Strategy.name == data.name).first():
            raise HTTPException(409, f"Strategy name '{data.name}' already exists")
        s.name = data.name
    if data.query_text is not None:
        s.query_text = data.query_text
    if data.schedule_cron is not None:
        s.schedule_cron = data.schedule_cron
    if data.enabled is not None:
        s.enabled = data.enabled
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.delete("/{sid}")
def delete_strategy(sid: int, db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == sid).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    db.delete(s)
    db.commit()
    return {"detail": "deleted", "id": sid}


@router.post("/{sid}/toggle", response_model=StrategyOut)
def toggle_strategy(sid: int, db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == sid).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    s.enabled = not s.enabled
    db.commit()
    db.refresh(s)
    logger.info(f"Strategy {s.id} ({s.name}) -> enabled={s.enabled}")
    return _to_out(s)


@router.post("/{sid}/run")
def run_strategy_now(sid: int, db: Session = Depends(get_db)):
    """Run the picker synchronously for one strategy. Returns batch_id or
    descriptive message if iwc is unavailable (cookie stale etc).
    """
    s = db.query(Strategy).filter(Strategy.id == sid).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    # Import here to avoid circular: routers shouldn't import bot.*
    import sys
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parent.parent.parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    if str(_ROOT / "bot") not in sys.path:
        sys.path.insert(0, str(_ROOT / "bot"))
    from bot.strategy_picker import run_one_strategy
    result = run_one_strategy(sid)
    if not result.get("ok"):
        # Don't 500 — caller wants the message
        return {"ok": False, "message": result.get("message", ""),
                "errors": result.get("errors", [])}
    return {"ok": True, "batch_id": result.get("batch_id"),
            "hit_count": result.get("hit_count"),
            "message": result.get("message")}
