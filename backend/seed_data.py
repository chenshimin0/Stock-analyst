import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.models import Report, PriceSnapshot, WinRate
from app.services.report_service import ReportService
from app.schemas import ReportCreate
from datetime import date

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Check if data exists
if db.query(Report).first():
    print("Database already seeded. Skipping.")
    db.close()
    sys.exit(0)

# Load existing report data
data_path = os.path.expanduser("~/Desktop/sumeida_report_data.json")
with open(data_path, "r", encoding="utf-8") as f:
    raw = json.load(f)

report = ReportCreate(
    stock_code=raw["basic_info"]["code"],
    stock_name=raw["basic_info"]["name"],
    report_date=date.fromisoformat(raw["date"]),
    price_at_report=raw["realtime"]["price"],
    momentum_score=raw["scoring"]["momentum_score"],
    revenue_score=raw["scoring"]["revenue_score"],
    risk_score=raw["scoring"]["risk_score"],
    total_score=raw["scoring"]["total_score"],
    label=raw["scoring"]["label"],
    financial_data={
        "periods": raw["financial"]["periods"],
        "revenue_label": raw["financial"]["revenue_label"],
        "parent_profit_label": raw["financial"]["parent_profit_label"],
        "eps": raw["financial"]["eps"],
    },
    technical_data=raw["technicals"],
    events_data=raw["events"],
    expert_data=raw["expert_analysis"],
    recommendation=raw["recommendation"],
)

result = ReportService.create_report(db, report)
print(f"Seeded report: id={result.id}, stock={result.stock_name}, date={result.report_date}")

db.close()
print("Seeding complete.")
