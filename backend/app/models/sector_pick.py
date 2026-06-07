from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Date, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SectorPick(Base):
    __tablename__ = "sector_picks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="in_progress")
    selection_source = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)

    stocks = relationship(
        "SectorPickStock", back_populates="sector_pick",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_sector_picks_name_status", "sector_name", "status"),
    )


class SectorPickStock(Base):
    __tablename__ = "sector_pick_stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_pick_id = Column(
        Integer, ForeignKey("sector_picks.id", ondelete="CASCADE"), nullable=False,
    )
    stock_code = Column(String(6), nullable=False)
    stock_name = Column(String(50), nullable=False)
    selection_reason = Column(Text, nullable=False)
    t0_date = Column(Date, nullable=False)
    t0_price = Column(Float, nullable=True)
    t0_avg_price = Column(Float, nullable=True)
    t5_date = Column(Date, nullable=True)
    t5_price = Column(Float, nullable=True)
    t5_avg_price = Column(Float, nullable=True)
    t5_pct = Column(Float, nullable=True)
    t10_date = Column(Date, nullable=True)
    t10_price = Column(Float, nullable=True)
    t10_avg_price = Column(Float, nullable=True)
    t10_pct = Column(Float, nullable=True)
    t20_date = Column(Date, nullable=True)
    t20_price = Column(Float, nullable=True)
    t20_avg_price = Column(Float, nullable=True)
    t20_pct = Column(Float, nullable=True)

    sector_pick = relationship("SectorPick", back_populates="stocks")

    __table_args__ = (
        Index(
            "ix_sector_pick_stocks_unique",
            "sector_pick_id", "stock_code", unique=True,
        ),
    )


class SectorMemberCache(Base):
    __tablename__ = "sector_member_cache"

    sector_name = Column(String(100), primary_key=True)
    stock_code = Column(String(6), primary_key=True)
    stock_name = Column(String(50), nullable=False)
    last_fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
