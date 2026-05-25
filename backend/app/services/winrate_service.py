from datetime import date, timedelta, datetime
from sqlalchemy.orm import Session

from app.config import WIN_RATE_PERIODS
from app.models import Report, WinRate, PriceSnapshot
from app.services.price_service import PriceService


class WinRateService:
    @staticmethod
    async def calculate_win_rates(db: Session, report_id: int) -> list[dict]:
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            return []

        results = []
        today = date.today()

        for period_days in WIN_RATE_PERIODS:
            target_date = report.report_date + timedelta(days=period_days)

            # Check existing first
            existing = db.query(WinRate).filter(
                WinRate.report_id == report_id,
                WinRate.period_days == period_days,
            ).first()

            if existing and existing.is_win is not None:
                results.append({
                    "period_days": period_days,
                    "is_win": existing.is_win,
                    "price_at_period": existing.price_at_period,
                    "change_pct": existing.change_pct,
                    "target_date": target_date,
                })
                continue

            # Future date — not yet calculable
            if target_date > today:
                results.append({
                    "period_days": period_days,
                    "is_win": None,
                    "price_at_period": None,
                    "change_pct": None,
                    "target_date": target_date,
                })
                continue

            # Try price_snapshots first
            snapshot = db.query(PriceSnapshot).filter(
                PriceSnapshot.report_id == report_id,
                PriceSnapshot.date <= target_date,
            ).order_by(PriceSnapshot.date.desc()).first()

            price_at_period = snapshot.price if snapshot else None

            # Fall back to akshare
            if price_at_period is None:
                price_at_period = await PriceService.get_historical_price(
                    report.stock_code,
                    target_date.strftime("%Y%m%d"),
                )
                if price_at_period is not None:
                    db.add(PriceSnapshot(
                        report_id=report_id,
                        date=target_date,
                        price=price_at_period,
                    ))
                    db.commit()

            if price_at_period is not None and report.price_at_report > 0:
                is_win = price_at_period > report.price_at_report
                change_pct = round((price_at_period - report.price_at_report) / report.price_at_report * 100, 2)
            else:
                is_win = None
                change_pct = None

            # Upsert win_rate
            if existing:
                existing.is_win = is_win
                existing.price_at_period = price_at_period
                existing.change_pct = change_pct
            else:
                db.add(WinRate(
                    report_id=report_id,
                    period_days=period_days,
                    is_win=is_win,
                    price_at_period=price_at_period,
                    change_pct=change_pct,
                ))
            db.commit()

            results.append({
                "period_days": period_days,
                "is_win": is_win,
                "price_at_period": price_at_period,
                "change_pct": change_pct,
                "target_date": target_date,
            })

        return results

    @staticmethod
    def get_aggregate_stats(db: Session) -> list[dict]:
        all_wr = db.query(WinRate).filter(WinRate.is_win.isnot(None)).all()
        stats = {}
        for wr in all_wr:
            key = wr.period_days
            if key not in stats:
                stats[key] = {"win_count": 0, "total_count": 0, "total_change": 0.0}
            stats[key]["total_count"] += 1
            stats[key]["total_change"] += wr.change_pct or 0
            if wr.is_win:
                stats[key]["win_count"] += 1

        results = []
        for pd_days in WIN_RATE_PERIODS:
            s = stats.get(pd_days, {"win_count": 0, "total_count": 0, "total_change": 0.0})
            total = s["total_count"]
            results.append({
                "period_days": pd_days,
                "win_count": s["win_count"],
                "total_count": total,
                "win_rate": round(s["win_count"] / total * 100, 1) if total > 0 else 0,
                "avg_change_pct": round(s["total_change"] / total, 2) if total > 0 else 0,
            })
        return results
