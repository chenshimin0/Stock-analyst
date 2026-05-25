from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.schemas import ReportCreate, ReportSummary, ReportDetail, ReportUpdate, WinRateResponse, WinRatePeriod, AggregateWinRate
from app.services.report_service import ReportService
from app.services.winrate_service import WinRateService
from app.models import Report
from app.services.price_service import PriceService
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import json

router = APIRouter(prefix="/reports", tags=["reports"])

_tpl_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates"))
)


@router.get("", response_model=list[ReportSummary])
async def list_reports(
    sort: str = Query("performance", alias="sort"),
    order: str = Query("desc", alias="order"),
    db: Session = Depends(get_db),
):
    return await ReportService.get_reports_with_performance(db, sort=sort, order=order)


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    format: str = Query("json", alias="format"),
    db: Session = Depends(get_db),
):
    # Try numeric ID first, then slug lookup
    data = None
    if report_id.isdigit():
        data = await ReportService.get_report_with_realtime(db, int(report_id))
    if not data:
        report = db.query(Report).filter(Report.slug == report_id).order_by(Report.created_at.desc()).first()
        if report:
            data = await ReportService.get_report_with_realtime(db, report.id)
    if not data:
        return {"detail": "Report not found"}, 404

    if format == "html":
        template = _tpl_env.get_template("report.html")
        html = template.render(**data)
        return HTMLResponse(content=html)

    return data


@router.post("", response_model=ReportDetail)
def create_report(data: ReportCreate, db: Session = Depends(get_db)):
    report = ReportService.create_report(db, data)
    return report


@router.delete("/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        return {"detail": "Report not found"}, 404
    db.delete(report)
    db.commit()
    return {"detail": "deleted", "id": report_id}


@router.put("/{report_id}", response_model=ReportDetail)
def update_report(report_id: int, data: ReportUpdate, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        return {"detail": "Report not found"}, 404
    update_data = data.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(report, key, val)
    db.commit()
    db.refresh(report)
    return report


@router.get("/{report_id}/winrate", response_model=WinRateResponse)
async def get_report_winrate(report_id: int, db: Session = Depends(get_db)):
    periods = await WinRateService.calculate_win_rates(db, report_id)
    return WinRateResponse(
        report_id=report_id,
        periods=[WinRatePeriod(**p) for p in periods],
    )


@router.get("/winrate/all")
async def get_all_reports_winrates(db: Session = Depends(get_db)):
    return await ReportService.get_all_reports_winrates(db)


@router.get("/winrate/aggregate", response_model=list[AggregateWinRate])
def get_aggregate_winrate(db: Session = Depends(get_db)):
    return [AggregateWinRate(**s) for s in WinRateService.get_aggregate_stats(db)]
