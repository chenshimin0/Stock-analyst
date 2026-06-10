from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), nullable=False)
    slug = Column(String(50), nullable=True, index=True)
    report_date = Column(Date, nullable=False)
    price_at_report = Column(Float, nullable=False)
    momentum_score = Column(Float, nullable=False, default=0)
    revenue_score = Column(Float, nullable=False, default=0)
    risk_score = Column(Float, nullable=False, default=0)
    total_score = Column(Float, nullable=False, default=0)
    label = Column(String(20), nullable=False, default="观察")
    financial_data = Column(JSON, nullable=True)
    technical_data = Column(JSON, nullable=True)
    events_data = Column(JSON, nullable=True)
    expert_data = Column(JSON, nullable=True)
    recommendation = Column(JSON, nullable=True)
    scoring_factors = Column(JSON, nullable=True)
    ai_analysis = Column(JSON, nullable=True)
    concept_boards = Column(JSON, nullable=True)
    filtered_concept_boards = Column(JSON, nullable=True)
    sector_data = Column(JSON, nullable=True)
    data_10jqka = Column(JSON, nullable=True)
    financial_data_raw = Column(JSON, nullable=True)
    peer_comparison_raw = Column(JSON, nullable=True)
    revenue_composition_raw = Column(JSON, nullable=True)
    adjusted_price_at_report = Column(Float, nullable=True)
    fund_flow_recent = Column(JSON, nullable=True)
    last_limit_up_date = Column(String(20), nullable=True)
    last_limit_up_days_ago = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    price_snapshots = relationship("PriceSnapshot", back_populates="report", cascade="all, delete-orphan")
    win_rates = relationship("WinRate", back_populates="report", cascade="all, delete-orphan")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (UniqueConstraint("report_id", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    price = Column(Float, nullable=False)

    report = relationship("Report", back_populates="price_snapshots")


class WinRate(Base):
    __tablename__ = "win_rates"
    __table_args__ = (UniqueConstraint("report_id", "period_days"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    period_days = Column(Integer, nullable=False)
    is_win = Column(Boolean, nullable=True)
    price_at_period = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)

    report = relationship("Report", back_populates="win_rates")
