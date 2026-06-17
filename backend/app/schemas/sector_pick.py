from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class StockCreate(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    name: str
    reason: str
    t0_price: Optional[float] = None
    t0_avg_price: Optional[float] = None


class SectorPickCreateRequest(BaseModel):
    sector_name: str = Field(..., max_length=100)
    selection_source: str = Field(..., pattern="^(api_driven|ai_knowledge)$")
    t0_date: str  # YYYY-MM-DD
    stocks: List[StockCreate] = Field(..., min_items=3, max_items=3)


class SectorPickCreateResponse(BaseModel):
    id: int
    created_at: datetime


class StockMetric(BaseModel):
    code: str
    name: str
    reason: str
    t0_price: Optional[float]
    t3_pct: Optional[float]
    t5_pct: Optional[float]
    t10_pct: Optional[float]
    t20_pct: Optional[float]


class SectorPickListItem(BaseModel):
    id: int
    sector_name: str
    status: str
    selection_source: str
    created_at: datetime
    avg_t3_pct: Optional[float]
    avg_t5_pct: Optional[float]
    avg_t10_pct: Optional[float]
    avg_t20_pct: Optional[float]


class SectorPickDetail(SectorPickListItem):
    completed_at: Optional[datetime]
    archived_at: Optional[datetime]
    stocks: List[StockMetric]
