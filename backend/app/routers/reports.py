from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.schemas import ReportCreate, ReportSummary, ReportDetail, ReportUpdate, WinRateResponse, WinRatePeriod, AggregateWinRate, PaginatedReports
from app.services.report_service import ReportService
from app.services.winrate_service import WinRateService
from app.models import Report
from app.services.price_service import PriceService
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import json
import re

router = APIRouter(prefix="/reports", tags=["reports"])


def _bg_refresh_fund_flow(report_id: int):
    """Background task: refresh fund flow data without blocking the page load."""
    import threading
    from app.database import SessionLocal

    def _run():
        db = SessionLocal()
        try:
            report = db.query(Report).filter(Report.id == report_id).first()
            if report:
                ReportService.refresh_fund_flow_if_stale(db, report)
        except Exception:
            pass
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


def _markdown_to_html(text: str) -> str:
    """Convert basic Markdown to HTML for report rendering."""
    if not text:
        return ""
    # Pre-process: break inline numbered items (1) 2) 3）etc.) into separate lines
    text = re.sub(r'(?<=[。；])\s*(\d+)[）)]\s*', r'\n\1) ', text)
    # Also handle cases where numbering starts mid-paragraph without Chinese punctuation
    text = re.sub(r'(?<=[：:])\s*(\d+)[）)]\s*', r'\n\1) ', text)
    lines = text.split("\n")
    result = []
    in_list = False
    in_olist = False
    for line in lines:
        stripped = line.strip()
        # Headers
        if stripped.startswith("### "):
            if in_list:
                result.append("</ul>")
                in_list = False
            if in_olist:
                result.append("</ol>")
                in_olist = False
            result.append("<h4>{}</h4>".format(stripped[4:]))
            continue
        if stripped.startswith("## "):
            if in_list:
                result.append("</ul>")
                in_list = False
            if in_olist:
                result.append("</ol>")
                in_olist = False
            result.append("<h3>{}</h3>".format(stripped[3:]))
            continue
        # Unordered list
        if stripped.startswith("- ") or stripped.startswith("* "):
            if in_olist:
                result.append("</ol>")
                in_olist = False
            if not in_list:
                result.append('<ul style="margin:4px 0;padding-left:18px">')
                in_list = True
            result.append("<li>{}</li>".format(_inline_markdown(stripped[2:])))
            continue
        # Numbered list (1) or 1.)
        m = re.match(r"^(\d+)[.)）]\s*(.*)", stripped)
        if m:
            if in_list:
                result.append("</ul>")
                in_list = False
            if not in_olist:
                result.append('<ol style="margin:4px 0;padding-left:20px">')
                in_olist = True
            result.append("<li>{}</li>".format(_inline_markdown(m.group(2))))
            continue
        # End of any list
        if in_list:
            result.append("</ul>")
            in_list = False
        if in_olist:
            result.append("</ol>")
            in_olist = False
        # Paragraphs (empty lines)
        if not stripped:
            result.append("<br>")
            continue
        # Bold markers like **动量因素(pos):** text
        result.append("<p style=margin:2px 0>{}</p>".format(_inline_markdown(stripped)))
    if in_list:
        result.append("</ul>")
    if in_olist:
        result.append("</ol>")
    return "\n".join(result)


def _inline_markdown(text: str) -> str:
    """Convert inline Markdown: **bold**, *italic*."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


_tpl_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates"))
)
_tpl_env.filters["markdown_html"] = _markdown_to_html
_tpl_env.filters["urlencode"] = lambda s: __import__("urllib.parse").parse.quote(str(s))


@router.get("", response_model=PaginatedReports)
async def list_reports(
    sort: str = Query("performance", alias="sort"),
    order: str = Query("desc", alias="order"),
    page: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, alias="page_size", ge=1, le=100),
    search: str = Query("", alias="search"),
    db: Session = Depends(get_db),
):
    return await ReportService.get_reports_with_performance(
        db, sort=sort, order=order, page=page, page_size=page_size, search=search,
    )


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    format: str = Query("json", alias="format"),
    db: Session = Depends(get_db),
):
    # Try numeric ID first, then slug lookup, then stock_code fallback
    data = None
    report = None
    if report_id.isdigit() and len(report_id) <= 4:
        report = db.query(Report).filter(Report.id == int(report_id)).first()
        if report:
            data = await ReportService.get_report_with_realtime(db, report.id)
            # Fire-and-forget: refresh fund flow in background thread, don't block page load
            _bg_refresh_fund_flow(report.id)
    if not data:
        report = (
            db.query(Report)
            .filter((Report.slug == report_id) | (Report.stock_code == report_id))
            .order_by(Report.created_at.desc())
            .first()
        )
        if report:
            data = await ReportService.get_report_with_realtime(db, report.id)
            _bg_refresh_fund_flow(report.id)
    if not data:
        raise HTTPException(status_code=404, detail="Report not found")

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
def delete_report(report_id: str, db: Session = Depends(get_db)):
    """Delete by numeric id, slug (e.g. 'HHKJ'), or stock code (e.g. '600378')."""
    q = db.query(Report)
    if report_id.isdigit() and len(report_id) <= 4:
        # Short numeric: treat as DB primary key
        report = q.filter(Report.id == int(report_id)).first()
    else:
        # Stock code (6-digit) or slug: match by stock_code or slug
        report = (
            q.filter((Report.slug == report_id) | (Report.stock_code == report_id))
            .order_by(Report.created_at.desc())
            .first()
        )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    rid = report.id
    db.delete(report)
    db.commit()
    return {"detail": "deleted", "id": rid}


@router.put("/{report_id}", response_model=ReportDetail)
def update_report(report_id: str, data: ReportUpdate, db: Session = Depends(get_db)):
    """Update by numeric id, slug, or stock code."""
    q = db.query(Report)
    if report_id.isdigit() and len(report_id) <= 4:
        report = q.filter(Report.id == int(report_id)).first()
    else:
        report = (
            q.filter((Report.slug == report_id) | (Report.stock_code == report_id))
            .order_by(Report.created_at.desc())
            .first()
        )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    update_data = data.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(report, key, val)
    db.commit()
    db.refresh(report)
    return report


@router.post("/{report_id}/rerun")
def rerun_report(report_id: str, db: Session = Depends(get_db)):
    """Delete existing report and queue stock for fresh re-analysis."""
    import os as _os, json as _json
    q = db.query(Report)
    if report_id.isdigit() and len(report_id) <= 4:
        report = q.filter(Report.id == int(report_id)).first()
    else:
        report = (
            q.filter((Report.slug == report_id) | (Report.stock_code == report_id))
            .order_by(Report.created_at.desc())
            .first()
        )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    stock_code = report.stock_code
    stock_name = report.stock_name

    # Delete existing report
    db.delete(report)
    db.commit()

    # Create pending placeholder immediately
    try:
        from app.schemas import ReportCreate
        from app.services.report_service import ReportService
        pending = ReportCreate(
            stock_code=stock_code,
            stock_name=stock_name,
            report_date=datetime.utcnow().date(),
            price_at_report=0,
            label="分析中...",
        )
        ReportService.create_report(db, pending)
    except Exception:
        pass  # silent — queue processor will create proper report anyway

    # Queue for re-analysis
    queue_dir = _os.getenv("QUEUE_DIR", "/home/ubuntu/stock-analysis-system/backend/queue")
    _os.makedirs(queue_dir, exist_ok=True)
    fpath = _os.path.join(queue_dir, f"{stock_code}.json")
    with open(fpath, "w") as f:
        _json.dump({"stock_code": stock_code, "stock_name": stock_name}, f)
    return {"detail": "deleted and re-queued", "stock_code": stock_code}


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


@router.post("/refresh-prices")
async def refresh_adjusted_prices(db: Session = Depends(get_db)):
    result = await ReportService.refresh_adjusted_prices(db)
    return result


@router.get("/winrate/aggregate", response_model=list[AggregateWinRate])
def get_aggregate_winrate(db: Session = Depends(get_db)):
    return [AggregateWinRate(**s) for s in WinRateService.get_aggregate_stats(db)]
