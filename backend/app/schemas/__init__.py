from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class ReportCreate(BaseModel):
    stock_code: str
    stock_name: str
    report_date: date
    price_at_report: float
    momentum_score: float = 0
    revenue_score: float = 0
    risk_score: float = 0
    total_score: float = 0
    label: str = "观察"
    financial_data: Optional[dict] = None
    technical_data: Optional[dict] = None
    events_data: Optional[list] = None
    expert_data: Optional[dict] = None
    recommendation: Optional[dict] = None
    scoring_factors: Optional[dict] = None
    ai_analysis: Optional[dict] = None
    concept_boards: Optional[list] = None
    filtered_concept_boards: Optional[list] = None
    sector_data: Optional[dict] = None
    data_10jqka: Optional[dict] = None
    financial_data_raw: Optional[dict] = None
    peer_comparison_raw: Optional[dict] = None
    revenue_composition_raw: Optional[dict] = None


class ReportUpdate(BaseModel):
    stock_name: Optional[str] = None
    price_at_report: Optional[float] = None
    momentum_score: Optional[float] = None
    revenue_score: Optional[float] = None
    risk_score: Optional[float] = None
    total_score: Optional[float] = None
    label: Optional[str] = None
    financial_data: Optional[dict] = None
    technical_data: Optional[dict] = None
    events_data: Optional[list] = None
    expert_data: Optional[dict] = None
    recommendation: Optional[dict] = None
    scoring_factors: Optional[dict] = None
    concept_boards: Optional[list] = None
    sector_data: Optional[dict] = None


class ReportSummary(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    slug: Optional[str] = None
    report_date: date
    price_at_report: float
    current_price: Optional[float] = None
    performance_score: Optional[float] = None
    momentum_score: float
    revenue_score: float
    risk_score: float
    total_score: float
    label: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReportDetail(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    report_date: date
    price_at_report: float
    momentum_score: float
    revenue_score: float
    risk_score: float
    total_score: float
    label: str
    financial_data: Optional[dict] = None
    technical_data: Optional[dict] = None
    events_data: Optional[list] = None
    expert_data: Optional[dict] = None
    recommendation: Optional[dict] = None
    scoring_factors: Optional[dict] = None
    ai_analysis: Optional[dict] = None
    concept_boards: Optional[list] = None
    filtered_concept_boards: Optional[list] = None
    sector_data: Optional[dict] = None
    data_10jqka: Optional[dict] = None
    financial_data_raw: Optional[dict] = None
    peer_comparison_raw: Optional[dict] = None
    revenue_composition_raw: Optional[dict] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StockPrice(BaseModel):
    code: str
    name: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    change_pct: float
    date: str
    time: str


class WinRatePeriod(BaseModel):
    period_days: int
    is_win: Optional[bool] = None
    price_at_period: Optional[float] = None
    change_pct: Optional[float] = None
    target_date: date


class WinRateResponse(BaseModel):
    report_id: int
    periods: list[WinRatePeriod]


class AggregateWinRate(BaseModel):
    period_days: int
    win_count: int
    total_count: int
    win_rate: float
    avg_change_pct: float
