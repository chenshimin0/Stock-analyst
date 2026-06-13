"""
Strategy (definition) model — one row per named strategy.

A StrategyPick batch is one cron run of a Strategy. The relationship is
1 Strategy -> N StrategyPick.

A Strategy carries:
- name: human label
- query_text: full iwencai query
- schedule_cron: "HH:MM" weekday format, defaults to 14:30
- enabled: scheduler skips disabled strategies

Note: StrategyPick.strategy_id FK is added in models/strategy_pick.py.
This is the parent table; it must be created before strategy_pick.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    query_text = Column(Text, nullable=False)
    schedule_cron = Column(String(20), nullable=False, default="14:30")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    picks = relationship("StrategyPick", back_populates="strategy")

    __table_args__ = (
        Index("ix_strategies_enabled", "enabled"),
    )
