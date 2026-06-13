"""StrategyPick + StrategyPickStock — per-run batch tables.

Mirrors the sector_pick.py pattern. Uses the same Base as Strategy
(models/strategy.py) so cross-model relationships resolve.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, Float, Date, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import relationship
from app.models.strategy import Base


class StrategyPick(Base):
    __tablename__ = "strategy_picks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False,
    )
    status = Column(String(20), nullable=False, default="in_progress")
    hit_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)

    strategy = relationship("Strategy", back_populates="picks")
    stocks = relationship(
        "StrategyPickStock", back_populates="strategy_pick",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_strategy_picks_strategy_status", "strategy_id", "status"),
        Index("ix_strategy_picks_created", "created_at"),
    )


class StrategyPickStock(Base):
    __tablename__ = "strategy_pick_stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_pick_id = Column(
        Integer, ForeignKey("strategy_picks.id", ondelete="CASCADE"), nullable=False,
    )
    stock_code = Column(String(6), nullable=False)
    stock_name = Column(String(50), nullable=False)
    industry = Column(String(80), nullable=True)
    business_summary = Column(Text, nullable=True)
    selection_reason = Column(Text, nullable=True)
    t0_date = Column(Date, nullable=False)
    t0_price = Column(Float, nullable=True)

    t3_date = Column(Date, nullable=True)
    t3_price = Column(Float, nullable=True)
    t3_pct = Column(Float, nullable=True)
    t7_date = Column(Date, nullable=True)
    t7_price = Column(Float, nullable=True)
    t7_pct = Column(Float, nullable=True)
    t15_date = Column(Date, nullable=True)
    t15_price = Column(Float, nullable=True)
    t15_pct = Column(Float, nullable=True)
    t30_date = Column(Date, nullable=True)
    t30_price = Column(Float, nullable=True)
    t30_pct = Column(Float, nullable=True)

    strategy_pick = relationship("StrategyPick", back_populates="stocks")

    __table_args__ = (
        Index(
            "ix_strategy_pick_stocks_unique",
            "strategy_pick_id", "stock_code", unique=True,
        ),
    )
