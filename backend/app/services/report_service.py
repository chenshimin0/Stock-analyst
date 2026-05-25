from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.models import Report
from app.schemas import ReportCreate
from app.services.price_service import PriceService
from pypinyin import pinyin, Style


def _make_slug(name: str) -> str:
    initials = pinyin(name, style=Style.FIRST_LETTER)
    return ''.join([i[0].upper() for i in initials])


class ReportService:
    @staticmethod
    def create_report(db: Session, data: ReportCreate) -> Report:
        existing = (
            db.query(Report)
            .filter(Report.stock_code == data.stock_code)
            .first()
        )
        if existing:
            existing.report_date = data.report_date
            existing.stock_name = data.stock_name
            existing.slug = _make_slug(data.stock_name)
            existing.price_at_report = data.price_at_report
            existing.momentum_score = data.momentum_score
            existing.revenue_score = data.revenue_score
            existing.risk_score = data.risk_score
            existing.total_score = data.total_score
            existing.label = data.label
            existing.financial_data = data.financial_data
            existing.technical_data = data.technical_data
            existing.events_data = data.events_data
            existing.expert_data = data.expert_data
            existing.recommendation = data.recommendation
            existing.scoring_factors = data.scoring_factors
            existing.ai_analysis = data.ai_analysis
            db.commit()
            db.refresh(existing)
            return existing

        report = Report(
            stock_code=data.stock_code,
            stock_name=data.stock_name,
            slug=_make_slug(data.stock_name),
            report_date=data.report_date,
            price_at_report=data.price_at_report,
            momentum_score=data.momentum_score,
            revenue_score=data.revenue_score,
            risk_score=data.risk_score,
            total_score=data.total_score,
            label=data.label,
            financial_data=data.financial_data,
            technical_data=data.technical_data,
            events_data=data.events_data,
            expert_data=data.expert_data,
            recommendation=data.recommendation,
            scoring_factors=data.scoring_factors,
            ai_analysis=data.ai_analysis,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report

    @staticmethod
    def get_report(db: Session, report_id: int) -> Optional[Report]:
        return db.query(Report).filter(Report.id == report_id).first()

    @staticmethod
    def get_all_reports(db: Session) -> list[Report]:
        return db.query(Report).order_by(Report.created_at.desc()).all()

    @staticmethod
    async def get_reports_with_performance(db: Session, sort: str = "performance", order: str = "desc") -> list[dict]:
        reports = db.query(Report).order_by(Report.created_at.desc()).all()
        if not reports:
            return []

        codes = list({r.stock_code for r in reports})
        prices = await PriceService.get_realtime_prices_batch(codes)
        price_map = {p["code"]: p for p in prices if p}

        results = []
        for r in reports:
            current = price_map.get(r.stock_code, {})
            current_price = current.get("price")
            perf_score = None
            if current_price and r.price_at_report > 0:
                perf_score = round((current_price - r.price_at_report) / r.price_at_report * 100, 2)

            results.append({
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "slug": r.slug,
                "report_date": r.report_date,
                "price_at_report": r.price_at_report,
                "current_price": current_price,
                "performance_score": perf_score,
                "momentum_score": r.momentum_score,
                "revenue_score": r.revenue_score,
                "risk_score": r.risk_score,
                "total_score": r.total_score,
                "label": r.label,
                "created_at": r.created_at,
            })

        reverse = order.lower() != "asc"
        if sort == "total_score":
            results.sort(key=lambda x: x.get("total_score") or 0, reverse=reverse)
        elif sort == "date":
            results.sort(key=lambda x: str(x.get("report_date", "")), reverse=reverse)
        else:
            results.sort(key=lambda x: x.get("performance_score") or -9999, reverse=reverse)
        return results

    @staticmethod
    async def get_all_reports_winrates(db: Session) -> list[dict]:
        """Return all reports with their win rate data as a flat list."""
        from app.services.winrate_service import WinRateService

        reports = db.query(Report).order_by(Report.created_at.desc()).all()
        results = []
        for r in reports:
            periods = await WinRateService.calculate_win_rates(db, r.id)
            results.append({
                "report_id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "report_date": str(r.report_date),
                "price_at_report": r.price_at_report,
                "total_score": r.total_score,
                "label": r.label,
                "periods": periods,
            })
        return results

    @staticmethod
    async def get_report_with_realtime(db: Session, report_id: int) -> Optional[dict]:
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            return None

        price_data = await PriceService.get_realtime_price(report.stock_code)
        current_price = price_data.get("price") if price_data else None

        return {
            "id": report.id,
            "stock_code": report.stock_code,
            "stock_name": report.stock_name,
            "report_date": report.report_date,
            "price_at_report": report.price_at_report,
            "current_price": current_price,
            "momentum_score": report.momentum_score,
            "revenue_score": report.revenue_score,
            "risk_score": report.risk_score,
            "total_score": report.total_score,
            "label": report.label,
            "financial_data": report.financial_data,
            "technical_data": report.technical_data,
            "events_data": report.events_data,
            "expert_data": report.expert_data,
            "recommendation": report.recommendation,
            "scoring_factors": report.scoring_factors,
            "ai_analysis": report.ai_analysis,
            "created_at": report.created_at,
            "realtime": price_data,
        }
