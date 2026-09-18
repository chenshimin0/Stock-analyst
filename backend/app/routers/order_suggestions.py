"""
Order suggestion router — semi-auto trading.

Endpoints:
  GET  /api/order-suggestions                  list recent suggestions
  POST /api/order-suggestions/generate         generate (+push) for a batch
  POST /api/order-suggestions/{id}/status      mark bought / ignored / pending
  POST /api/order-suggestions/test-push        ServerChan test message
  GET  /api/order-config                       get risk config
  PUT  /api/order-config                       update risk config
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Strategy, StrategyPick, OrderSuggestion, OrderConfig
from app.schemas import (
    OrderSuggestionOut, OrderSuggestionStatusUpdate, OrderGenerateRequest,
    OrderConfigOut, OrderConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/order-suggestions", tags=["order-suggestions"])

config_router = APIRouter(prefix="/order-config", tags=["order-config"])

VALID_STATUS = {"pending", "bought", "ignored"}


@router.get("", response_model=list[OrderSuggestionOut])
def list_suggestions(limit: int = 100, strategy_id: Optional[int] = None,
                     db: Session = Depends(get_db)):
    q = db.query(OrderSuggestion).order_by(OrderSuggestion.id.desc())
    if strategy_id:
        q = q.filter(OrderSuggestion.strategy_id == strategy_id)
    return q.limit(min(limit, 500)).all()


@router.post("/generate")
def generate_suggestions(req: OrderGenerateRequest, db: Session = Depends(get_db)):
    """手动触发：为一个批次生成建议单并（可选）推送到微信。

    batch_id 缺省时取 strategy_id 的最新批次；两者都缺则取全局最新批次。
    """
    # 延迟导入：bot 模块会改 sys.path
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent.parent.parent
    for p in (str(root / "bot"),):
        if p not in sys.path:
            sys.path.insert(0, p)
    from order_notifier import generate_for_batch

    batch_id = req.batch_id
    if batch_id is None:
        q = db.query(StrategyPick).order_by(StrategyPick.id.desc())
        if req.strategy_id:
            s = db.query(Strategy).filter(Strategy.id == req.strategy_id).first()
            if not s:
                raise HTTPException(404, f"Strategy {req.strategy_id} not found")
            q = q.filter(StrategyPick.strategy_id == req.strategy_id)
        latest = q.first()
        if not latest:
            raise HTTPException(404, "没有可用批次")
        batch_id = latest.id
    out = generate_for_batch(batch_id, push=req.push)
    if not out.get("ok"):
        raise HTTPException(400, out.get("message", "生成失败"))
    return out


@router.post("/{sid}/status", response_model=OrderSuggestionOut)
def update_status(sid: int, body: OrderSuggestionStatusUpdate,
                  db: Session = Depends(get_db)):
    if body.status not in VALID_STATUS:
        raise HTTPException(422, f"status 必须是 {sorted(VALID_STATUS)} 之一")
    row = db.query(OrderSuggestion).filter(OrderSuggestion.id == sid).first()
    if not row:
        raise HTTPException(404, "建议单不存在")
    row.status = body.status
    db.commit()
    db.refresh(row)
    return row


@router.post("/test-push")
def test_push_endpoint():
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent.parent.parent
    if str(root / "bot") not in sys.path:
        sys.path.insert(0, str(root / "bot"))
    from order_notifier import test_push
    if not test_push():
        raise HTTPException(502, "Server酱推送失败，请检查 serverchan.enc 与 token")
    return {"ok": True, "message": "测试消息已推送，请在微信查看"}


@config_router.get("", response_model=OrderConfigOut)
def get_order_config(db: Session = Depends(get_db)):
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent.parent.parent
    if str(root / "bot") not in sys.path:
        sys.path.insert(0, str(root / "bot"))
    from order_notifier import get_config
    return get_config(db)


@config_router.put("", response_model=OrderConfigOut)
def update_order_config(body: OrderConfigUpdate, db: Session = Depends(get_db)):
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent.parent.parent
    if str(root / "bot") not in sys.path:
        sys.path.insert(0, str(root / "bot"))
    from order_notifier import get_config
    cfg = get_config(db)
    if body.per_order_amount is not None and body.per_order_amount > 0:
        cfg.per_order_amount = body.per_order_amount
    if body.max_daily_amount is not None and body.max_daily_amount > 0:
        cfg.max_daily_amount = body.max_daily_amount
    if body.max_shares_per_stock is not None:
        cfg.max_shares_per_stock = body.max_shares_per_stock or None
    if body.push_enabled is not None:
        cfg.push_enabled = body.push_enabled
    db.commit()
    db.refresh(cfg)
    return cfg
