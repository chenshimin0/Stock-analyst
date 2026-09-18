"""OrderSuggestion + OrderConfig — semi-auto trading suggestion tables.

半自动下单：系统不碰真实交易，只做两件事——
1. 策略跑批成功后，按风控规则生成「建议订单」（标的/价格/股数/金额）
2. 通过 Server酱 推送到用户微信，由用户手动在券商 App 下单

OrderSuggestion: 一条建议单（一个批次里的一只股票）
OrderConfig: 全局配置（单笔金额/单日上限），单例行 id=1

Whitelist principle: AI can never invent targets — suggestions are only
generated from stocks already present in a StrategyPickStock batch.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, Index,
)
from app.models.strategy import Base


class OrderSuggestion(Base):
    __tablename__ = "order_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(
        Integer, ForeignKey("strategy_picks.id", ondelete="CASCADE"), nullable=False,
    )
    strategy_id = Column(Integer, nullable=False)

    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), nullable=False)
    suggested_price = Column(Float, nullable=True)   # 建议委托价（批次 t0_price）
    shares = Column(Integer, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0.0)

    # 风控结果：risk_ok=True 才值得下单；False 的行仅存档不推送下单建议
    risk_ok = Column(Boolean, nullable=False, default=True)
    risk_note = Column(Text, nullable=True)          # 风控拒绝原因（如超单日上限）

    # pending=待处理  bought=已下单  ignored=已忽略
    status = Column(String(20), nullable=False, default="pending")
    # 同一批次合一条消息推送；pushed 标记该建议单是否已随消息发出
    pushed = Column(Boolean, nullable=False, default=False)
    pushed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_order_suggestions_unique", "batch_id", "stock_code", unique=True),
        Index("ix_order_suggestions_created", "created_at"),
    )


class OrderConfig(Base):
    __tablename__ = "order_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 单笔建议金额（元）：股数 = floor(该值 / 价格 / 100) * 100
    per_order_amount = Column(Float, nullable=False, default=10000.0)
    # 单日建议总金额上限（元）：超出部分标记 risk_ok=False
    max_daily_amount = Column(Float, nullable=False, default=50000.0)
    # 单只股票最大建议股数（0/NULL = 不限制）
    max_shares_per_stock = Column(Integer, nullable=True)
    # 总开关：False 时跑批后不推送（生成逻辑仍可用手动触发）
    push_enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)
