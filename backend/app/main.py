from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import CORS_ORIGINS
from app.database import engine, Base
from app.models import Report, PriceSnapshot, WinRate
from app.routers import reports, stocks, sector

Base.metadata.create_all(bind=engine)

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
