import re
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


def _filter_concept_boards(concept_boards: list, sector_data: dict = None,
                            data_10jqka: dict = None, ai_analysis: dict = None,
                            max_count: int = 10) -> list:
    """Filter concept boards: hot/trending first, then core boards, max max_count."""
    if not concept_boards:
        return []
    if len(concept_boards) <= max_count:
        return concept_boards

    hot_keywords = set()
    if sector_data and sector_data.get("sector_name"):
        hot_keywords.add(sector_data["sector_name"])
    if data_10jqka:
        hot_reason = data_10jqka.get("hot_reason")
        if hot_reason:
            for kw in re.split(r'[+、，,]+', hot_reason):
                kw = kw.strip()
                if len(kw) >= 2:
                    hot_keywords.add(kw)
    if ai_analysis:
        tags = ai_analysis.get("tags") or []
        for tag in tags:
            tag = tag.strip()
            if len(tag) >= 2:
                hot_keywords.add(tag)

    filtered = []
    # Pass 1: hot boards
    for cb in concept_boards:
        bn = cb.get("board_name", "") if isinstance(cb, dict) else str(cb)
        is_hot = any(kw in bn or bn in kw for kw in hot_keywords) if hot_keywords else False
        if is_hot:
            filtered.append(cb)

    # Pass 2: core boards
    seen = {cb.get("board_name", "") if isinstance(cb, dict) else str(cb) for cb in filtered}
    for cb in concept_boards:
        bn = cb.get("board_name", "") if isinstance(cb, dict) else str(cb)
        if bn not in seen:
            filtered.append(cb)
            seen.add(bn)
        if len(filtered) >= max_count:
            break

    return filtered


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
            existing.concept_boards = data.concept_boards
            existing.filtered_concept_boards = data.filtered_concept_boards
            existing.sector_data = data.sector_data
            existing.data_10jqka = data.data_10jqka
            existing.financial_data_raw = data.financial_data_raw
            existing.peer_comparison_raw = data.peer_comparison_raw
            existing.revenue_composition_raw = data.revenue_composition_raw
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
            concept_boards=data.concept_boards,
            filtered_concept_boards=data.filtered_concept_boards,
            sector_data=data.sector_data,
            data_10jqka=data.data_10jqka,
            financial_data_raw=data.financial_data_raw,
            peer_comparison_raw=data.peer_comparison_raw,
            revenue_composition_raw=data.revenue_composition_raw,
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
    async def get_reports_with_performance(
        db: Session, sort: str = "performance", order: str = "desc",
        page: int = 1, page_size: int = 20,
    ) -> dict:
        reports = db.query(Report).order_by(Report.created_at.desc()).all()
        if not reports:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        codes = list({r.stock_code for r in reports})
        prices = await PriceService.get_realtime_prices_batch(codes)
        price_map = {p["code"]: p for p in prices if p}

        results = []
        for r in reports:
            current = price_map.get(r.stock_code, {})
            current_price = current.get("price")
            perf_score = None
            base_price = r.adjusted_price_at_report or r.price_at_report
            if current_price and base_price > 0:
                perf_score = round((current_price - base_price) / base_price * 100, 2)

            results.append({
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "slug": r.slug,
                "report_date": r.report_date,
                "price_at_report": r.price_at_report,
                "adjusted_price_at_report": r.adjusted_price_at_report,
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

        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "items": results[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    async def refresh_adjusted_prices(db: Session) -> dict:
        """Re-query 前复权 close prices for all reports and store them.

        Fetches K-line data once per stock, then looks up each report date.
        """
        reports = db.query(Report).all()
        if not reports:
            return {"updated": 0}

        # Group by stock code
        by_code: dict[str, list] = {}
        for r in reports:
            by_code.setdefault(r.stock_code, []).append(r)

        updated = 0
        for code, stock_reports in by_code.items():
            kline_data = await PriceService._fetch_kline_data(code)
            if not kline_data:
                continue

            for r in stock_reports:
                target = str(r.report_date).replace("-", "")
                price = PriceService._lookup_kline_close(kline_data, target)
                if price and price > 0:
                    r.adjusted_price_at_report = price
                    updated += 1

        db.commit()
        return {"updated": updated}

        db.commit()
        return {"updated": updated}

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
            "concept_boards": report.concept_boards,
            "filtered_concept_boards": report.filtered_concept_boards
            or _filter_concept_boards(
                report.concept_boards or [],
                sector_data=report.sector_data,
                data_10jqka=report.data_10jqka,
                ai_analysis=report.ai_analysis,
            ),
            "sector_data": report.sector_data,
            "data_10jqka": report.data_10jqka,
            "financial_data_raw": report.financial_data_raw,
            "peer_comparison_raw": report.peer_comparison_raw,
            "revenue_composition_raw": report.revenue_composition_raw,
            "created_at": report.created_at,
            "realtime": price_data,
        }
