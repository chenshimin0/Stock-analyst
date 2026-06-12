from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import CORS_ORIGINS
from app.database import engine, Base
from app.models import Report, PriceSnapshot, WinRate, SectorPick, SectorPickStock, SectorMemberCache
from app.models import StrategyPick, StrategyPickStock
from app.models.sector_pick import Base as SectorPickBase
from app.models.strategy_pick import Base as StrategyPickBase
from app.routers import reports, stocks, sector, sector_picks, strategy

Base.metadata.create_all(bind=engine)
SectorPickBase.metadata.create_all(bind=engine)
StrategyPickBase.metadata.create_all(bind=engine)

# Migration: add missing columns if not exists (SQLite)
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("reports")]
    for col_name in ["filtered_concept_boards", "revenue_composition_raw", "adjusted_price_at_report", "fund_flow_recent", "last_limit_up_date", "last_limit_up_days_ago"]:
        if col_name not in cols:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE reports ADD COLUMN {col_name} JSON"))
                conn.commit()
except Exception:
    pass

app = FastAPI(title="Stock Analysis Report System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router, prefix="/api")
app.include_router(stocks.router, prefix="/api")
app.include_router(sector.router, prefix="/api")
app.include_router(sector_picks.router, prefix="/api")
app.include_router(strategy.router, prefix="/api")

# Serve frontend in production
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

# Jinja2 custom filter for score coloring
from app.routers.reports import _tpl_env

def score_class(value):
    if isinstance(value, (int, float)):
        if value > 0:
            return "pos"
        elif value < 0:
            return "neg"
        return "neu"
    return "neu"

_tpl_env.filters["score_class"] = score_class
