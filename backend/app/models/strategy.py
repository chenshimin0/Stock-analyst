"""
Strategy (definition) model — one row per named strategy.

A StrategyPick batch is one cron run of a Strategy. The relationship is
1 Strategy -> N StrategyPick.

A Strategy carries:
- name: human label
- query_text: full iwencai query
- schedule_cron: comma-separated "HH:MM" times, e.g. "09:35,14:45"
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
    # 最多保留股票数：跑批后只保留问财返回的前 N 只；NULL/0 = 全部保留
    max_stocks = Column(Integer, nullable=True)
    # 跑批成功后是否推送微信建议单（Server酱）；默认关，逐策略开启
    notify_wechat = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    picks = relationship(
        "StrategyPick", back_populates="strategy",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_strategies_enabled", "enabled"),
    )
