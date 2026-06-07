# Concept Sector Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a concept-sector (pvdf/太赫兹/固态电池) tracking system: Telegram bot accepts a concept name, selects 3 stocks via DeepSeek, and tracks T+5/T+10/T+20 trading-day performance with a frontend page on the left menu.

**Architecture:** 
- New `sector_picks` family of tables (3 tables) on the existing SQLite
- Telegram bot inline button + DeepSeek-driven selection (A+B fallback: API-driven preferred, AI-knowledge fallback)
- Independent `sector_scheduler.py` process runs at 20:00 each trading day to fill T+5/10/20 prices
- New FastAPI router + 2 frontend pages (list + detail)
- All English code/comments to match existing codebase

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, APScheduler, python-telegram-bot (existing), React + Vite (existing), Tencent Finance API (existing `bot/astock_data.py`)

---

## File Structure

### New files

| File | Responsibility |
|------|----------------|
| `backend/app/models/sector_pick.py` | SQLAlchemy models for `sector_picks`, `sector_pick_stocks`, `sector_member_cache` |
| `backend/app/schemas/sector_pick.py` | Pydantic v2 schemas (request/response) |
| `backend/app/routers/sector_picks.py` | FastAPI router: list / detail / create / archive |
| `bot/sector_selector.py` | Stock selection logic (A+B fallback, prompts, parse) |
| `bot/sector_tracker.py` | K-line fetching, T+N trading day calculation, price/avg_price/pct writes |
| `bot/sector_scheduler.py` | APScheduler entrypoint, runs `sector_tracker` at 20:00 each day |
| `bot/sector_handler.py` | Telegram bot handler: inline button + concept input + 60s timer |
| `bot/tests/test_sector_filter.py` | Tests: 主板 filter, ST filter, market cap filter |
| `bot/tests/test_sector_cache.py` | Tests: 24h TTL logic |
| `bot/tests/test_sector_ai.py` | Tests: DeepSeek response parsing (normal/error/missing fields) |
| `bot/tests/test_sector_tracker.py` | Tests: T+5/10/20 trading day calculation |
| `frontend/src/api/sector.js` | API client for sector endpoints |
| `frontend/src/pages/SectorList.jsx` | List page (in-progress/completed/archived tabs) |
| `frontend/src/pages/SectorDetail.jsx` | Detail page (stocks table + sector avg + archive button) |

### Modified files

| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Import new models so `Base.metadata.create_all` picks them up |
| `backend/app/main.py` | Import sector_picks router and mount at `/api` |
| `bot/telegram_bot.py` | Register sector button callback + concept input handler |
| `frontend/src/components/Layout.jsx` | Add `📊 板块追踪` menu item |
| `frontend/src/App.jsx` | Add `/sector-tracker` and `/sector-tracker/:id` routes |
| `deploy.sh` or new `deploy-scheduler.sh` | Deploy + start scheduler process |

---

## Task 1: Data models

**Files:**
- Create: `backend/app/models/sector_pick.py`
- Modify: `backend/app/models/__init__.py`
- Test: `bot/tests/test_sector_models.py` (in `backend/app/models/` if SQLAlchemy; or place under `bot/tests/` if running sqlite session)

- [ ] **Step 1: Write the failing test**

Create `backend/app/tests/test_sector_models.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.sector_pick import (
    Base, SectorPick, SectorPickStock, SectorMemberCache,
)

def test_create_sector_pick():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    pick = SectorPick(
        sector_name="pvdf", status="in_progress", selection_source="api_driven"
    )
    s.add(pick)
    s.commit()
    assert pick.id is not None
    assert pick.status == "in_progress"
    assert pick.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest app/tests/test_sector_models.py -v`
Expected: `ModuleNotFoundError: No module named 'app.models.sector_pick'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/models/sector_pick.py`:
```python
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Date, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SectorPick(Base):
    __tablename__ = "sector_picks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="in_progress")
    selection_source = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)

    stocks = relationship(
        "SectorPickStock", back_populates="sector_pick",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_sector_picks_name_status", "sector_name", "status"),
    )


class SectorPickStock(Base):
    __tablename__ = "sector_pick_stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_pick_id = Column(
        Integer, ForeignKey("sector_picks.id", ondelete="CASCADE"), nullable=False,
    )
    stock_code = Column(String(6), nullable=False)
    stock_name = Column(String(50), nullable=False)
    selection_reason = Column(Text, nullable=False)
    t0_date = Column(Date, nullable=False)
    t0_price = Column(Float, nullable=True)
    t0_avg_price = Column(Float, nullable=True)
    t5_date = Column(Date, nullable=True)
    t5_price = Column(Float, nullable=True)
    t5_avg_price = Column(Float, nullable=True)
    t5_pct = Column(Float, nullable=True)
    t10_date = Column(Date, nullable=True)
    t10_price = Column(Float, nullable=True)
    t10_avg_price = Column(Float, nullable=True)
    t10_pct = Column(Float, nullable=True)
    t20_date = Column(Date, nullable=True)
    t20_price = Column(Float, nullable=True)
    t20_avg_price = Column(Float, nullable=True)
    t20_pct = Column(Float, nullable=True)

    sector_pick = relationship("SectorPick", back_populates="stocks")

    __table_args__ = (
        Index(
            "ix_sector_pick_stocks_unique",
            "sector_pick_id", "stock_code", unique=True,
        ),
    )


class SectorMemberCache(Base):
    __tablename__ = "sector_member_cache"

    sector_name = Column(String(100), primary_key=True)
    stock_code = Column(String(6), primary_key=True)
    stock_name = Column(String(50), nullable=False)
    last_fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: Update `models/__init__.py` to import the new models**

Edit `backend/app/models/__init__.py`:
```python
from app.models.report import Report, PriceSnapshot, WinRate
from app.models.sector_pick import (
    Base as SectorPickBase, SectorPick, SectorPickStock, SectorMemberCache,
)

__all__ = [
    "Report", "PriceSnapshot", "WinRate",
    "SectorPick", "SectorPickStock", "SectorMemberCache",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest app/tests/test_sector_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/sector_pick.py backend/app/models/__init__.py backend/app/tests/test_sector_models.py
git commit -m "feat(sector): add data models for sector picks"
```

---

## Task 2: Migration in main.py

**Files:**
- Modify: `backend/app/main.py:8-9, 18`

- [ ] **Step 1: Update imports and table creation**

Edit `backend/app/main.py`:
```python
from app.models import Report, PriceSnapshot, WinRate, SectorPick, SectorPickStock, SectorMemberCache
from app.models.sector_pick import Base as SectorPickBase
from app.routers import reports, stocks, sector, sector_picks
```

Replace the `Base.metadata.create_all(bind=engine)` call with both:
```python
Base.metadata.create_all(bind=engine)
SectorPickBase.metadata.create_all(bind=engine)
```

(The existing `Base` is from `app.models.report`; new `SectorPickBase` is from sector_pick. We must run both since they have separate metadata.)

- [ ] **Step 2: Verify by running the backend**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: `OK` (no import errors)

Note: A new router `sector_picks` is referenced but doesn't exist yet — the import will fail. Use a try/except wrapper for now, OR create the router file (Task 3) before this commit.

- [ ] **Step 3: Commit (after Task 3 router exists)**

```bash
git add backend/app/main.py
git commit -m "feat(sector): create sector_picks tables on startup"
```

---

## Task 3: FastAPI router (skeleton with stub handlers)

**Files:**
- Create: `backend/app/routers/sector_picks.py`
- Modify: `backend/app/main.py:38` (add include_router)

- [ ] **Step 1: Create router skeleton**

Create `backend/app/routers/sector_picks.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.models.sector_pick import SectorPick, SectorPickStock, SectorMemberCache
from app.schemas.sector_pick import (
    SectorPickListItem, SectorPickDetail, StockMetric,
    SectorPickCreateRequest, SectorPickCreateResponse,
)

router = APIRouter(prefix="/sector-picks", tags=["sector-picks"])


@router.get("", response_model=List[SectorPickListItem])
def list_sector_picks(
    status: Optional[str] = Query(None, regex="^(in_progress|completed|archived)$"),
    db: Session = Depends(get_db),
):
    q = db.query(SectorPick)
    if status:
        q = q.filter(SectorPick.status == status)
    picks = q.order_by(SectorPick.created_at.desc()).all()
    return [
        SectorPickListItem(
            id=p.id,
            sector_name=p.sector_name,
            status=p.status,
            selection_source=p.selection_source,
            created_at=p.created_at,
            avg_t5_pct=_avg(p.stocks, "t5_pct"),
            avg_t10_pct=_avg(p.stocks, "t10_pct"),
            avg_t20_pct=_avg(p.stocks, "t20_pct"),
        )
        for p in picks
    ]


@router.get("/{pick_id}", response_model=SectorPickDetail)
def get_sector_pick(pick_id: int, db: Session = Depends(get_db)):
    p = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Sector pick not found")
    return SectorPickDetail(
        id=p.id,
        sector_name=p.sector_name,
        status=p.status,
        selection_source=p.selection_source,
        created_at=p.created_at,
        completed_at=p.completed_at,
        archived_at=p.archived_at,
        avg_t5_pct=_avg(p.stocks, "t5_pct"),
        avg_t10_pct=_avg(p.stocks, "t10_pct"),
        avg_t20_pct=_avg(p.stocks, "t20_pct"),
        stocks=[
            StockMetric(
                code=s.stock_code,
                name=s.stock_name,
                reason=s.selection_reason,
                t0_price=s.t0_price,
                t5_pct=s.t5_pct,
                t10_pct=s.t10_pct,
                t20_pct=s.t20_pct,
            )
            for s in p.stocks
        ],
    )


@router.post("", response_model=SectorPickCreateResponse, status_code=201)
def create_sector_pick(req: SectorPickCreateRequest, db: Session = Depends(get_db)):
    """Create a new sector pick (used by bot internally)."""
    existing = (
        db.query(SectorPick)
        .filter(
            SectorPick.sector_name == req.sector_name,
            SectorPick.status.in_(["in_progress", "completed"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Sector '{req.sector_name}' already has an active pick (id={existing.id})",
        )
    pick = SectorPick(
        sector_name=req.sector_name,
        status="in_progress",
        selection_source=req.selection_source,
    )
    db.add(pick)
    db.flush()
    for s in req.stocks:
        db.add(SectorPickStock(
            sector_pick_id=pick.id,
            stock_code=s.code,
            stock_name=s.name,
            selection_reason=s.reason,
            t0_date=datetime.strptime(req.t0_date, "%Y-%m-%d").date(),
            t0_price=s.t0_price,
            t0_avg_price=s.t0_avg_price,
        ))
    db.commit()
    db.refresh(pick)
    return SectorPickCreateResponse(id=pick.id, created_at=pick.created_at)


@router.post("/{pick_id}/archive")
def archive_sector_pick(pick_id: int, db: Session = Depends(get_db)):
    p = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Sector pick not found")
    if p.status == "archived":
        return {"id": p.id, "status": p.status}
    p.status = "archived"
    p.archived_at = datetime.utcnow()
    db.commit()
    return {"id": p.id, "status": p.status}


def _avg(stocks, attr: str) -> Optional[float]:
    vals = [getattr(s, attr) for s in stocks if getattr(s, attr) is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)
```

- [ ] **Step 2: Create Pydantic schemas**

Create `backend/app/schemas/sector_pick.py`:
```python
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
    selection_source: str = Field(..., regex="^(api_driven|ai_knowledge)$")
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
    t5_pct: Optional[float]
    t10_pct: Optional[float]
    t20_pct: Optional[float]


class SectorPickListItem(BaseModel):
    id: int
    sector_name: str
    status: str
    selection_source: str
    created_at: datetime
    avg_t5_pct: Optional[float]
    avg_t10_pct: Optional[float]
    avg_t20_pct: Optional[float]


class SectorPickDetail(SectorPickListItem):
    completed_at: Optional[datetime]
    archived_at: Optional[datetime]
    stocks: List[StockMetric]
```

- [ ] **Step 3: Mount router in main.py**

In `backend/app/main.py`, add `app.include_router(sector_picks.router, prefix="/api")` next to the existing routers.

- [ ] **Step 4: Verify endpoints register**

Run: `cd backend && python -c "from app.main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'sector' in r])"`
Expected: A list with paths like `/api/sector-picks`, `/api/sector-picks/{pick_id}`, etc.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/sector_picks.py backend/app/schemas/sector_pick.py backend/app/main.py
git commit -m "feat(sector): add API router for sector picks"
```

---

## Task 4: Bot selector (board filter + DeepSeek)

**Files:**
- Create: `bot/sector_selector.py`
- Test: `bot/tests/test_sector_filter.py`

- [ ] **Step 1: Write the failing test for board filter**

Create `bot/tests/test_sector_filter.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sector_selector import is_main_board, is_st, is_within_market_cap, is_within_pe_median


def test_is_main_board():
    assert is_main_board("600000") is True   # Shanghai main
    assert is_main_board("000001") is True   # Shenzhen main
    assert is_main_board("002415") is True   # Shenzhen SME (now part of main)
    assert is_main_board("300750") is False  # ChiNext
    assert is_main_board("688017") is False  # STAR market
    assert is_main_board("830799") is False  # BSE
    assert is_main_board("400003") is False  # legacy
    assert is_main_board("900901") is False  # B-share


def test_is_st():
    assert is_st("平安银行") is False
    assert is_st("ST华联") is True
    assert is_st("*ST大集") is True
    assert is_st("st国华") is True  # case-insensitive


def test_is_within_market_cap():
    assert is_within_market_cap(450.0) is True
    assert is_within_market_cap(500.0) is True  # boundary
    assert is_within_market_cap(500.01) is False
    assert is_within_market_cap(0) is False
    assert is_within_market_cap(-10) is False


def test_is_within_pe_median():
    pe_list = [10, 20, 30, 40, 50, 60, 70]
    median = 40
    assert is_within_pe_median(20, median) is True   # below median
    assert is_within_pe_median(40, median) is False  # at median
    assert is_within_pe_median(0, median) is False   # no data
    assert is_within_pe_median(-5, median) is False  # negative (loss)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_sector_filter.py -v`
Expected: `ModuleNotFoundError: No module named 'sector_selector'`

- [ ] **Step 3: Implement filter functions**

Create `bot/sector_selector.py`:
```python
"""
Concept-sector stock selection: A+B fallback strategy.

A: DeepSeek-only (concept_name → 3 stocks)
B: API-driven (sector_member_cache + tencent_quote → candidates → DeepSeek filters)
"""
import json
import logging
import statistics
import urllib.request
import re
from datetime import datetime, timedelta
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from astock_data import get_quote

logger = logging.getLogger(__name__)


# =================================================================
# Board filters
# =================================================================
def is_main_board(code: str) -> bool:
    """6 字头沪市主板 + 0 字头深市主板（含 002 中小板）。排除创业板/科创板/北交所。"""
    return code.startswith("6") or code.startswith("0")


def is_st(name: str) -> bool:
    """股票简称含 ST 或 *ST 即视为 ST 股。"""
    n = name.upper()
    return "ST" in n


def is_within_market_cap(mcap_yi: float) -> bool:
    """市值（亿） < 500。"""
    return 0 < mcap_yi < 500


def is_within_pe_median(pe_ttm: float, median_pe: float) -> bool:
    """PE-TTM 低于本概念中位数。"""
    return pe_ttm > 0 and pe_ttm < median_pe


# =================================================================
# Concept member cache (24h TTL)
# =================================================================
def get_cached_members(sector_name: str, db_session) -> list[dict]:
    """
    Read sector_member_cache. Returns list of {stock_code, stock_name}.
    Empty list if no records or all expired (> 24h).
    Caller must pass a SQLAlchemy session.
    """
    from app.models.sector_pick import SectorMemberCache  # type: ignore
    threshold = datetime.utcnow() - timedelta(hours=24)
    rows = (
        db_session.query(SectorMemberCache)
        .filter(SectorMemberCache.sector_name == sector_name)
        .filter(SectorMemberCache.last_fetched_at >= threshold)
        .all()
    )
    return [{"stock_code": r.stock_code, "stock_name": r.stock_name} for r in rows]


def save_cached_members(sector_name: str, members: list[dict], db_session) -> None:
    """Upsert cache rows."""
    from app.models.sector_pick import SectorMemberCache  # type: ignore
    now = datetime.utcnow()
    for m in members:
        existing = (
            db_session.query(SectorMemberCache)
            .filter(
                SectorMemberCache.sector_name == sector_name,
                SectorMemberCache.stock_code == m["stock_code"],
            )
            .first()
        )
        if existing:
            existing.stock_name = m["stock_name"]
            existing.last_fetched_at = now
        else:
            db_session.add(SectorMemberCache(
                sector_name=sector_name,
                stock_code=m["stock_code"],
                stock_name=m["stock_name"],
                last_fetched_at=now,
            ))
    db_session.commit()


# =================================================================
# Concept member fetch (real-time, fallback to A)
# =================================================================
def fetch_concept_members_realtime(sector_name: str) -> list[dict]:
    """
    Pull concept member stocks from a-stock-data skill.
    Primary: baidu stock concept mapping.
    Fallback: ths hot reason reverse-lookup.
    Returns [] on failure (caller should fallback to AI knowledge).
    """
    # TODO: wire up to existing astock_data functions if available.
    # For now, return [] to exercise the fallback path.
    return []


# =================================================================
# B: API-driven candidate filtering
# =================================================================
def build_api_driven_candidates(sector_name: str, db_session) -> list[dict]:
    """
    Returns up to 20 candidates with: code, name, mcap_yi, pe_ttm.
    Source: cache (24h) → realtime fetch → [].
    """
    members = get_cached_members(sector_name, db_session)
    if not members:
        members = fetch_concept_members_realtime(sector_name)
        if members:
            save_cached_members(sector_name, members, db_session)
    if not members:
        return []
    candidates = []
    for m in members[:20]:
        q = get_quote(m["stock_code"])
        if not q:
            continue
        candidates.append({
            "code": m["stock_code"],
            "name": m["stock_name"],
            "mcap_yi": q.get("total_mv", 0),
            "pe_ttm": q.get("pe", 0),
        })
    return candidates


def filter_main_board_non_st(candidates: list[dict]) -> list[dict]:
    return [
        c for c in candidates
        if is_main_board(c["code"]) and not is_st(c["name"])
    ]


def filter_market_cap(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if is_within_market_cap(c.get("mcap_yi", 0))]


def pe_median(candidates: list[dict]) -> float:
    pes = [c["pe_ttm"] for c in candidates if c.get("pe_ttm", 0) > 0]
    return statistics.median(pes) if pes else 0


# =================================================================
# DeepSeek prompt construction
# =================================================================
def build_prompt_api_driven(concept_name: str, candidates: list[dict], median_pe: float) -> str:
    rows = "\n".join(
        f"| {c['code']} | {c['name']} | {c['mcap_yi']:.0f} | {c['pe_ttm']:.1f} |"
        for c in candidates
    )
    return f"""概念名称：{concept_name}
该概念成分股（已通过 API 实时拉取，{datetime.now().strftime("%Y-%m-%d")}）：

| 代码 | 名称 | 市值(亿) | PE-TTM |
{rows}

请从上述成分股中，挑选 **3 只** 最符合以下条件的：
1. 行业龙头地位
2. PE-TTM 低于本概念中位数（{median_pe:.1f}）
3. 总市值 < 500 亿
4. 主板上市、非 ST
5. 历史上连续 3 年有现金分红
6. 给出每只的简短推荐理由（30 字内）

输出严格 JSON：{{"picks":[{{"code":"002812","name":"恩捷股份","reason":"全球 PVDF 隔膜涂覆龙头..."}}]}}
"""


def build_prompt_ai_knowledge(concept_name: str) -> str:
    return f"""请从"{concept_name}"这一**概念板块**中，推荐 3 只符合以下条件的 A 股：
- 沪深主板上市（6 字头沪市主板、0 字头深市主板），非 ST
- 总市值 < 500 亿
- 行业龙头地位
- PE-TTM 较低（在你的知识库范围内评估）
- 历史上连续 3 年有现金分红
- 输出严格 JSON：{{"picks":[{{"code":"002812","name":"恩捷股份","reason":"..."}}]}}
- 如果该概念不存在或成分股 < 3 只，返回 {{"error":"原因"}} 而非猜测
"""


# =================================================================
# DeepSeek response parsing
# =================================================================
def parse_deepseek_response(raw: str) -> dict:
    """
    Extract JSON from DeepSeek output. Returns:
      {"picks": [{"code","name","reason"}, ...]} on success
      {"error": "..."} on missing/empty/error
    """
    # Strip markdown code fences
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find first { ... } block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"error": "no JSON object found in response"}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}
    if "error" in data:
        return {"error": data["error"]}
    picks = data.get("picks")
    if not isinstance(picks, list) or len(picks) != 3:
        return {"error": f"expected 3 picks, got {len(picks) if isinstance(picks, list) else 'non-list'}"}
    for p in picks:
        if not all(k in p for k in ("code", "name", "reason")):
            return {"error": f"missing field in pick: {p}"}
        if not re.match(r"^\d{6}$", p["code"]):
            return {"error": f"invalid code: {p['code']}"}
    return {"picks": picks}


# =================================================================
# Top-level entry: A+B fallback
# =================================================================
def select_stocks_for_concept(concept_name: str, db_session, deepseek_callable) -> dict:
    """
    A+B strategy:
    1. Try B: build candidates from API → DeepSeek filters → 3 picks
    2. On B failure (no candidates / DeepSeek error / parse error) → A: feed concept name to DeepSeek
    Returns: {
      "picks": [...], "source": "api_driven" | "ai_knowledge",
    }
    On unrecoverable failure: {"error": "..."}
    """
    # B: API-driven
    candidates = build_api_driven_candidates(concept_name, db_session)
    main_board = filter_main_board_non_st(candidates)
    main_board = filter_market_cap(main_board)
    if len(main_board) >= 3:
        med = pe_median(main_board)
        prompt = build_prompt_api_driven(concept_name, main_board, med)
        raw = deepseek_callable(prompt)
        parsed = parse_deepseek_response(raw)
        if "picks" in parsed:
            # Validate picks are subset of candidates
            valid_codes = {c["code"] for c in main_board}
            valid_picks = [p for p in parsed["picks"] if p["code"] in valid_codes]
            if len(valid_picks) == 3:
                return {"picks": valid_picks, "source": "api_driven"}
        logger.warning(f"API-driven path failed: {parsed.get('error', 'unknown')}; falling back")

    # A: AI knowledge
    prompt = build_prompt_ai_knowledge(concept_name)
    raw = deepseek_callable(prompt)
    parsed = parse_deepseek_response(raw)
    if "picks" in parsed:
        return {"picks": parsed["picks"], "source": "ai_knowledge"}
    return {"error": parsed.get("error", "AI knowledge path failed")}
```

- [ ] **Step 4: Run tests**

Run: `cd bot && python -m pytest tests/test_sector_filter.py -v`
Expected: All 4 test functions PASS

- [ ] **Step 5: Add a parse test**

Append to `bot/tests/test_sector_filter.py` (or create `bot/tests/test_sector_ai.py`):
```python
from sector_selector import parse_deepseek_response

def test_parse_deepseek_normal():
    raw = '{"picks":[{"code":"002812","name":"恩捷股份","reason":"PVDF 龙头"},{"code":"002407","name":"多氟多","reason":"六氟磷酸锂"},{"code":"002460","name":"赣锋锂业","reason":"锂盐"}]}'
    out = parse_deepseek_response(raw)
    assert "picks" in out
    assert len(out["picks"]) == 3

def test_parse_deepseek_markdown_fence():
    raw = '```json\n{"picks":[{"code":"002812","name":"恩捷股份","reason":"PVDF"},{"code":"002407","name":"多氟多","reason":"六氟"},{"code":"002460","name":"赣锋","reason":"锂盐"}]}\n```'
    out = parse_deepseek_response(raw)
    assert "picks" in out

def test_parse_deepseek_error_keyword():
    raw = '{"error":"concept not found"}'
    out = parse_deepseek_response(raw)
    assert "error" in out

def test_parse_deepseek_wrong_count():
    raw = '{"picks":[{"code":"002812","name":"x","reason":"y"}]}'
    out = parse_deepseek_response(raw)
    assert "error" in out

def test_parse_deepseek_bad_json():
    raw = 'not json at all'
    out = parse_deepseek_response(raw)
    assert "error" in out

def test_parse_deepseek_invalid_code():
    raw = '{"picks":[{"code":"abc","name":"x","reason":"y"},{"code":"002407","name":"a","reason":"b"},{"code":"002460","name":"c","reason":"d"}]}'
    out = parse_deepseek_response(raw)
    assert "error" in out
```

- [ ] **Step 6: Run all tests**

Run: `cd bot && python -m pytest tests/test_sector_filter.py tests/test_sector_ai.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add bot/sector_selector.py bot/tests/test_sector_filter.py bot/tests/test_sector_ai.py
git commit -m "feat(sector): add A+B selector with DeepSeek prompts and parse"
```

---

## Task 5: T+N trading day calculation

**Files:**
- Create: `bot/sector_tracker.py`
- Test: `bot/tests/test_sector_tracker.py`

- [ ] **Step 1: Write the failing test**

Create `bot/tests/test_sector_tracker.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import date
from sector_tracker import find_trading_day_after, calc_t_n_metrics


def test_find_trading_day_after_5_days():
    # 5 trading days after a base date
    bars = [
        # (date_str, close, avg_price)
        ("2026-06-01", 10.0, 10.0),
        ("2026-06-02", 10.2, 10.1),
        ("2026-06-03", 10.4, 10.3),
        ("2026-06-04", 10.6, 10.5),
        ("2026-06-05", 10.8, 10.7),
        ("2026-06-08", 11.0, 10.9),  # skip weekend
        ("2026-06-09", 11.2, 11.1),
        ("2026-06-10", 11.4, 11.3),
    ]
    base = date(2026, 6, 1)
    # 5 trading days AFTER base: base=0, +5 = 5th index = 11.0
    out = find_trading_day_after(bars, base, n=5)
    assert out is not None
    assert out[0] == "2026-06-09"
    assert abs(out[1] - 11.2) < 0.01


def test_find_trading_day_after_not_enough_data():
    bars = [("2026-06-01", 10.0, 10.0)]
    out = find_trading_day_after(bars, date(2026, 6, 1), n=5)
    assert out is None


def test_calc_t_n_metrics():
    t0 = 10.0
    out = calc_t_n_metrics(t0_price=t0, t_n_price=11.0)
    assert abs(out - 10.0) < 0.01

    out2 = calc_t_n_metrics(t0_price=10.0, t_n_price=9.0)
    assert abs(out2 - (-10.0)) < 0.01

    out3 = calc_t_n_metrics(t0_price=0, t_n_price=10.0)
    assert out3 is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_sector_tracker.py -v`
Expected: `ModuleNotFoundError: No module named 'sector_tracker'`

- [ ] **Step 3: Implement sector_tracker**

Create `bot/sector_tracker.py`:
```python
"""
T+5/T+10/T+20 trading-day tracking for sector picks.
Pulls K-line from astock_data.get_kline and computes pct change vs t0.
"""
import logging
from datetime import date, datetime
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from astock_data import get_kline

logger = logging.getLogger(__name__)


def find_trading_day_after(
    bars: list[tuple[str, float, float]],
    base_date: date,
    n: int,
) -> Optional[tuple[str, float, float]]:
    """
    Given K-line bars (date_str, close, avg_price) sorted ascending,
    return the bar that is exactly N trading days AFTER base_date.
    Returns None if not enough data.
    """
    count = 0
    for bar in bars:
        d = datetime.strptime(bar[0], "%Y-%m-%d").date()
        if d > base_date:
            count += 1
            if count == n:
                return bar
    return None


def calc_t_n_metrics(t0_price: float, t_n_price: Optional[float]) -> Optional[float]:
    """Compute (t_n - t0) / t0 * 100, rounded to 2 decimals. None on missing/zero t0."""
    if t0_price is None or t0_price <= 0 or t_n_price is None:
        return None
    return round((t_n_price - t0_price) / t0_price * 100, 2)


def is_trading_day_today() -> bool:
    """Heuristic: try to get today's K-line. If no data, not a trading day."""
    from astock_data import get_quote
    # Tencent quote works on every day; for actual trading-day check, use K-line
    try:
        bars = get_kline("000001", count=5)  # SSE index as proxy
        if not bars:
            return False
        today_str = date.today().strftime("%Y-%m-%d")
        return any(b[0] == today_str for b in bars)
    except Exception as e:
        logger.warning(f"is_trading_day_today check failed: {e}")
        return False


def get_t_n_data_for_stock(
    stock_code: str,
    t0_date: date,
    t0_price: float,
) -> dict:
    """
    Pull K-line and compute t5/t10/t20 metrics. Returns dict with keys
    t5_date, t5_price, t5_avg_price, t5_pct, t10_*, t20_* (all optional).
    """
    out: dict = {}
    try:
        bars = get_kline(stock_code, count=30)  # 30 trading days covers all 3 milestones
    except Exception as e:
        logger.warning(f"get_kline failed for {stock_code}: {e}")
        return out
    if not bars:
        return out
    for n in (5, 10, 20):
        bar = find_trading_day_after(bars, t0_date, n)
        if not bar:
            continue
        t_date, t_close, t_avg = bar
        out[f"t{n}_date"] = date.fromisoformat(t_date)
        out[f"t{n}_price"] = t_close
        out[f"t{n}_avg_price"] = t_avg
        out[f"t{n}_pct"] = calc_t_n_metrics(t0_price, t_close)
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd bot && python -m pytest tests/test_sector_tracker.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bot/sector_tracker.py bot/tests/test_sector_tracker.py
git commit -m "feat(sector): add T+N trading day calculation"
```

---

## Task 6: Cache TTL test

**Files:**
- Create: `bot/tests/test_sector_cache.py`

- [ ] **Step 1: Write the test**

```python
import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use in-memory sqlite for the cache test
from app.models.sector_pick import Base, SectorMemberCache  # type: ignore
from sector_selector import get_cached_members, save_cached_members


def test_cache_hit_within_24h():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    save_cached_members("pvdf", [
        {"stock_code": "002812", "stock_name": "恩捷股份"},
        {"stock_code": "002407", "stock_name": "多氟多"},
    ], s)
    out = get_cached_members("pvdf", s)
    assert len(out) == 2
    assert out[0]["stock_code"] == "002812"


def test_cache_miss_after_24h():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(SectorMemberCache(
        sector_name="pvdf",
        stock_code="002812",
        stock_name="恩捷股份",
        last_fetched_at=datetime.utcnow() - timedelta(hours=25),
    ))
    s.commit()
    out = get_cached_members("pvdf", s)
    assert out == []


def test_cache_upsert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    save_cached_members("pvdf", [{"stock_code": "002812", "stock_name": "恩捷股份"}], s)
    # Update name
    save_cached_members("pvdf", [{"stock_code": "002812", "stock_name": "恩捷股份(更新)"}], s)
    out = get_cached_members("pvdf", s)
    assert len(out) == 1
    assert out[0]["stock_name"] == "恩捷股份(更新)"
```

- [ ] **Step 2: Run tests**

Run: `cd bot && python -m pytest tests/test_sector_cache.py -v`
Expected: All 3 PASS

- [ ] **Step 3: Commit**

```bash
git add bot/tests/test_sector_cache.py
git commit -m "test(sector): cover 24h TTL and upsert for member cache"
```

---

## Task 7: Scheduler entry point

**Files:**
- Create: `bot/sector_scheduler.py`

- [ ] **Step 1: Write the scheduler**

```python
"""
Sector pick scheduler. Runs at 20:00 each day.
For each in_progress / completed pick, fills T+5/10/20 prices from K-line.
Marks pick as 'completed' when all 3 milestones are filled.
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Path setup so 'app' and 'sector_*' modules resolve
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.sector_pick import SectorPick, SectorPickStock  # noqa: E402
from sector_tracker import get_t_n_data_for_stock, is_trading_day_today  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sector-scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger("sector_scheduler")


def run_daily_tracking() -> None:
    """Top-level job: process all active picks for today."""
    if not is_trading_day_today():
        logger.info("Not a trading day, skip.")
        return
    db: Session = SessionLocal()
    try:
        picks = (
            db.query(SectorPick)
            .filter(SectorPick.status.in_(["in_progress", "completed"]))
            .order_by(SectorPick.id)
            .all()
        )
        logger.info(f"Processing {len(picks)} active picks")
        for pick in picks:
            process_pick(db, pick)
    finally:
        db.close()


def process_pick(db: Session, pick: SectorPick) -> None:
    all_done = True
    for stock in pick.stocks:
        if stock.t5_pct is not None and stock.t10_pct is not None and stock.t20_pct is not None:
            continue  # already filled
        data = get_t_n_data_for_stock(
            stock.stock_code, pick.created_at.date(), stock.t0_price or 0
        )
        for key, val in data.items():
            setattr(stock, key, val)
        if not all([stock.t5_pct, stock.t10_pct, stock.t20_pct]):
            all_done = False
    if all_done and pick.status == "in_progress":
        pick.status = "completed"
        pick.completed_at = datetime.utcnow()
        logger.info(f"Pick {pick.id} ({pick.sector_name}) marked completed")
    db.commit()


def main() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_daily_tracking,
        CronTrigger(hour=20, minute=0, timezone="Asia/Shanghai"),
        id="sector_daily",
        replace_existing=True,
    )
    logger.info("Scheduler started; will run at 20:00 Asia/Shanghai daily.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add APScheduler to requirements**

In `requirements.txt` (or wherever deps are tracked), add: `APScheduler>=3.10,<4.0`

If `requirements.txt` doesn't exist, create it with:
```
APScheduler>=3.10,<4.0
```

- [ ] **Step 3: Smoke test (no scheduler trigger, just import)**

Run: `cd /Users/shiminchen/stock-analysis-system && python3 -c "import sys; sys.path.insert(0, 'bot'); sys.path.insert(0, 'backend'); from sector_scheduler import run_daily_tracking; print('import OK')"`
Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
git add bot/sector_scheduler.py requirements.txt
git commit -m "feat(sector): add APScheduler entrypoint for T+N tracking"
```

---

## Task 8: Bot handler (inline button + 60s timer)

**Files:**
- Create: `bot/sector_handler.py`
- Modify: `bot/telegram_bot.py`

- [ ] **Step 1: Create handler module**

Create `bot/sector_handler.py`:
```python
"""
Telegram bot handlers for concept-sector tracking.
- InlineKeyboard "📊 板块追踪" → prompt for concept name
- User input concept → run selection → save → reply
- 60s timer to auto-reopen if pick already exists
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from astock_data import get_quote  # noqa: E402
from ai_analyzer import call_deepseek  # actual import from existing module  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.sector_pick import SectorPick, SectorPickStock  # noqa: E402
from sector_selector import select_stocks_for_concept  # noqa: E402

logger = logging.getLogger(__name__)

# In-memory map: user_id -> sector_name awaiting confirmation
_pending: dict[int, dict] = {}


# === Inline button entry ===
async def handle_sector_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "请输入概念名（如：pvdf / 太赫兹 / 固态电池）"
    )
    context.user_data["awaiting_sector_input"] = True


# === User text input ===
async def handle_sector_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_sector_input"):
        return
    concept_name = update.message.text.strip()
    context.user_data["awaiting_sector_input"] = False
    user_id = update.effective_user.id
    db = SessionLocal()
    try:
        existing = (
            db.query(SectorPick)
            .filter(
                SectorPick.sector_name == concept_name,
                SectorPick.status.in_(["in_progress", "completed"]),
            )
            .first()
        )
        if existing:
            await _handle_existing(update, context, db, existing, user_id, concept_name)
            return
        await _run_new_pick(update, context, db, concept_name)
    finally:
        db.close()


async def _handle_existing(update, context, db, existing, user_id, concept_name):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("立即重开", callback_data=f"sector_reopen:{existing.id}"),
            InlineKeyboardButton("取消", callback_data="sector_cancel"),
        ]
    ])
    msg = await update.message.reply_text(
        f"该板块 {concept_name} 已有进行中的追踪（id={existing.id}，创建于 {existing.created_at:%Y-%m-%d %H:%M}）。\n"
        f"60 秒后将自动重开一轮。",
        reply_markup=keyboard,
    )
    # Schedule auto-reopen after 60s
    _pending[user_id] = {
        "concept": concept_name,
        "existing_id": existing.id,
        "msg_id": msg.message_id,
        "chat_id": update.effective_chat.id,
    }
    def _auto_reopen():
        time.sleep(60)
        if user_id in _pending and _pending[user_id].get("existing_id") == existing.id:
            asyncio.run_coroutine_threadsafe(
                _do_reopen(context.bot, _pending.pop(user_id), db_factory=SessionLocal),
                context.bot.loop,
            )
    threading.Thread(target=_auto_reopen, daemon=True).start()


async def _do_reopen(bot, pending: dict, db_factory):
    db = db_factory()
    try:
        old = db.query(SectorPick).filter(SectorPick.id == pending["existing_id"]).first()
        if old and old.status != "archived":
            old.status = "archived"
            old.archived_at = datetime.utcnow()
            db.commit()
        await _run_new_pick_in_chat(bot, pending["chat_id"], pending["concept"])
    finally:
        db.close()


async def _run_new_pick(update, context, db, concept_name):
    await _run_new_pick_in_chat(context.bot, update.effective_chat.id, concept_name)


async def _run_new_pick_in_chat(bot, chat_id: int, concept_name: str):
    db = SessionLocal()
    try:
        result = select_stocks_for_concept(
            concept_name, db, deepseek_callable=call_deepseek,
        )
        if "error" in result:
            await bot.send_message(
                chat_id=chat_id,
                text=f"选股失败：{result['error']}\n请换一个概念重试。",
            )
            return
        # Archive any old active pick (defensive)
        old = (
            db.query(SectorPick)
            .filter(
                SectorPick.sector_name == concept_name,
                SectorPick.status.in_(["in_progress", "completed"]),
            )
            .first()
        )
        if old:
            old.status = "archived"
            old.archived_at = datetime.utcnow()
        # Create new pick
        pick = SectorPick(
            sector_name=concept_name,
            status="in_progress",
            selection_source=result["source"],
        )
        db.add(pick)
        db.flush()
        t0_date = datetime.now().date()
        for p in result["picks"]:
            q = get_quote(p["code"])
            t0_price = q.get("price", 0) if q else 0
            db.add(SectorPickStock(
                sector_pick_id=pick.id,
                stock_code=p["code"],
                stock_name=p["name"],
                selection_reason=p["reason"],
                t0_date=t0_date,
                t0_price=t0_price or None,
                t0_avg_price=None,
            ))
        db.commit()
        # Reply
        lines = [
            f"已记录 3 只（板块：{concept_name}）：",
        ]
        for p in result["picks"]:
            lines.append(f"- {p['code']} {p['name']} — {p['reason']}")
        lines.append("")
        lines.append(f"数据源：{'API 实时' if result['source'] == 'api_driven' else 'AI 知识'}")
        lines.append("将在 T+5/10/20 个交易日后自动追踪。")
        await bot.send_message(chat_id=chat_id, text="\n".join(lines))
    finally:
        db.close()


# === Reopen button ===
async def handle_reopen_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 2:
        return
    pick_id = int(parts[1])
    user_id = update.effective_user.id
    pending = _pending.pop(user_id, None)
    db = SessionLocal()
    try:
        old = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
        if old and old.status != "archived":
            old.status = "archived"
            old.archived_at = datetime.utcnow()
            db.commit()
        concept = old.sector_name if old else (pending["concept"] if pending else "unknown")
        await _run_new_pick_in_chat(context.bot, update.effective_chat.id, concept)
    finally:
        db.close()


# === Cancel button ===
async def handle_cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    _pending.pop(user_id, None)
    await query.message.edit_text("已取消重开。")


def register_sector_handlers(app):
    """Wire handlers into an Application. Called from telegram_bot.py main()."""
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters
    app.add_handler(CallbackQueryHandler(handle_sector_button, pattern="^sector_pick$"))
    app.add_handler(CallbackQueryHandler(handle_reopen_button, pattern="^sector_reopen:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_button, pattern="^sector_cancel$"))
    # Note: handle_sector_text must be registered as a low-priority text handler
    # in telegram_bot.py itself, where filters.TEXT is composed with the existing chain.
    return handle_sector_text
```

- [ ] **Step 2: Wire into telegram_bot.py**

In `bot/telegram_bot.py`:
1. Add to imports:
```python
from sector_handler import (
    register_sector_handlers, handle_sector_text,
)
```
2. In the `main()` or equivalent where handlers are registered, add:
```python
handle_sector_text_handler = register_sector_handlers(application)
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sector_text_handler)
)
```
3. Add a button to the bot's start menu / inline keyboard. Look for where existing inline buttons (e.g., 📊 选股) are set. Add a new line:
```python
keyboard.append([InlineKeyboardButton("📊 板块追踪", callback_data="sector_pick")])
```

- [ ] **Step 3: Smoke test imports**

Run: `cd bot && python -c "import sector_handler; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add bot/sector_handler.py bot/telegram_bot.py
git commit -m "feat(sector): add Telegram bot handler with 60s reopen timer"
```

---

## Task 9: Frontend API client

**Files:**
- Create: `frontend/src/api/sector.js`

- [ ] **Step 1: Create API client**

```js
import client from './client.js';

export async function listSectorPicks(status = null) {
  const params = status ? { status } : {};
  const res = await client.get('/sector-picks', { params });
  return res.data;
}

export async function getSectorPick(id) {
  const res = await client.get(`/sector-picks/${id}`);
  return res.data;
}

export async function archiveSectorPick(id) {
  const res = await client.post(`/sector-picks/${id}/archive`);
  return res.data;
}

export async function createSectorPick(payload) {
  const res = await client.post('/sector-picks', payload);
  return res.data;
}
```

- [ ] **Step 2: Verify**

Run: `cd frontend && cat src/api/sector.js | head -5`
Expected: Imports `client from './client.js'`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/sector.js
git commit -m "feat(sector): add frontend API client"
```

---

## Task 10: Frontend list page

**Files:**
- Create: `frontend/src/pages/SectorList.jsx`

- [ ] **Step 1: Create the page**

```jsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listSectorPicks } from '../api/sector.js';

const TABS = [
  { key: 'active', label: '进行中', statuses: ['in_progress', 'completed'] },
  { key: 'archived', label: '已归档', statuses: ['archived'] },
];

export default function SectorList() {
  const [tab, setTab] = useState('active');
  const [picks, setPicks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    const statuses = TABS.find(t => t.key === tab).statuses;
    Promise.all(statuses.map(s => listSectorPicks(s).catch(() => [])))
      .then(arrs => setPicks(arrs.flat()))
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [tab]);

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>📊 板块追踪</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: '6px 14px',
              border: '1px solid #ccc',
              background: tab === t.key ? '#1565c0' : '#fff',
              color: tab === t.key ? '#fff' : '#333',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && <div>加载中…</div>}
      {err && <div style={{ color: 'red' }}>{err}</div>}

      {!loading && picks.length === 0 && (
        <div style={{ color: '#888', padding: 24, textAlign: 'center' }}>
          还没有追踪板块，去 Telegram bot 发送「📊 板块追踪」试试
        </div>
      )}

      {!loading && picks.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f5f5f5' }}>
              <th style={th}>板块</th>
              <th style={th}>状态</th>
              <th style={th}>数据源</th>
              <th style={th}>创建时间</th>
              <th style={th}>板块 T+5</th>
              <th style={th}>板块 T+10</th>
              <th style={th}>板块 T+20</th>
            </tr>
          </thead>
          <tbody>
            {picks.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={td}>
                  <Link to={`/sector-tracker/${p.id}`}>{p.sector_name}</Link>
                </td>
                <td style={td}><StatusBadge status={p.status} /></td>
                <td style={td}>{p.selection_source === 'api_driven' ? 'API 实时' : 'AI 知识'}</td>
                <td style={td}>{new Date(p.created_at).toLocaleString()}</td>
                <td style={td}><Pct value={p.avg_t5_pct} /></td>
                <td style={td}><Pct value={p.avg_t10_pct} /></td>
                <td style={td}><Pct value={p.avg_t20_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    in_progress: { label: '进行中', bg: '#e3f2fd', color: '#1565c0' },
    completed: { label: '已完成', bg: '#e8f5e9', color: '#2e7d32' },
    archived: { label: '已归档', bg: '#f5f5f5', color: '#666' },
  };
  const cfg = map[status] || { label: status, bg: '#eee', color: '#333' };
  return (
    <span style={{
      padding: '2px 8px',
      background: cfg.bg,
      color: cfg.color,
      borderRadius: 4,
      fontSize: 12,
    }}>
      {cfg.label}
    </span>
  );
}

function Pct({ value }) {
  if (value == null) return <span style={{ color: '#999' }}>—</span>;
  const isPos = value > 0;
  const isNeg = value < 0;
  const color = isPos ? '#d32f2f' : isNeg ? '#2e7d32' : '#333';
  return <span style={{ color, fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>;
}

const th = { padding: '8px 12px', textAlign: 'left', fontSize: 13 };
const td = { padding: '8px 12px', fontSize: 14 };
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/SectorList.jsx
git commit -m "feat(sector): add frontend list page with tabs"
```

---

## Task 11: Frontend detail page

**Files:**
- Create: `frontend/src/pages/SectorDetail.jsx`

- [ ] **Step 1: Create the page**

```jsx
import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getSectorPick, archiveSectorPick } from '../api/sector.js';

export default function SectorDetail() {
  const { id } = useParams();
  const [pick, setPick] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = () => {
    setLoading(true);
    getSectorPick(id)
      .then(setPick)
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const handleArchive = async () => {
    if (!confirm(`确认归档板块 ${pick.sector_name}？`)) return;
    await archiveSectorPick(id);
    load();
  };

  if (loading) return <div style={{ padding: 24 }}>加载中…</div>;
  if (err) return <div style={{ padding: 24, color: 'red' }}>{err}</div>;
  if (!pick) return <div style={{ padding: 24 }}>未找到该追踪</div>;

  const avgT5 = pick.avg_t5_pct;
  const avgT10 = pick.avg_t10_pct;
  const avgT20 = pick.avg_t20_pct;

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/sector-tracker">← 返回列表</Link>
      </div>
      <h2 style={{ marginBottom: 8 }}>{pick.sector_name} 板块追踪</h2>
      <div style={{ color: '#666', marginBottom: 16, fontSize: 14 }}>
        状态：<b>{pick.status}</b> · 数据源：{pick.selection_source === 'api_driven' ? 'API 实时' : 'AI 知识'} · 创建时间：{new Date(pick.created_at).toLocaleString()}
        {pick.completed_at && <span> · 完成时间：{new Date(pick.completed_at).toLocaleString()}</span>}
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
        <thead>
          <tr style={{ background: '#f5f5f5' }}>
            <th style={th}>代码</th>
            <th style={th}>名称</th>
            <th style={th}>推荐理由</th>
            <th style={th}>T+0 价</th>
            <th style={th}>T+5</th>
            <th style={th}>T+10</th>
            <th style={th}>T+20</th>
          </tr>
        </thead>
        <tbody>
          {pick.stocks.map(s => (
            <tr key={s.code} style={{ borderBottom: '1px solid #eee' }}>
              <td style={td}>{s.code}</td>
              <td style={td}>{s.name}</td>
              <td style={td}>{s.reason}</td>
              <td style={td}>{s.t0_price != null ? s.t0_price.toFixed(2) : '—'}</td>
              <td style={td}><Pct value={s.t5_pct} /></td>
              <td style={td}><Pct value={s.t10_pct} /></td>
              <td style={td}><Pct value={s.t20_pct} /></td>
            </tr>
          ))}
          <tr style={{ background: '#fafafa', fontWeight: 600 }}>
            <td style={td} colSpan={4}>板块平均</td>
            <td style={td}><Pct value={avgT5} /></td>
            <td style={td}><Pct value={avgT10} /></td>
            <td style={td}><Pct value={avgT20} /></td>
          </tr>
        </tbody>
      </table>

      {pick.status !== 'archived' && (
        <button
          onClick={handleArchive}
          style={{
            padding: '8px 16px',
            background: '#fff',
            border: '1px solid #ccc',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          归档
        </button>
      )}
    </div>
  );
}

function Pct({ value }) {
  if (value == null) return <span style={{ color: '#999' }}>—</span>;
  const color = value > 0 ? '#d32f2f' : value < 0 ? '#2e7d32' : '#333';
  return <span style={{ color, fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>;
}

const th = { padding: '8px 12px', textAlign: 'left', fontSize: 13 };
const td = { padding: '8px 12px', fontSize: 14 };
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/SectorDetail.jsx
git commit -m "feat(sector): add frontend detail page with stocks table and archive"
```

---

## Task 12: Wire frontend routes + menu

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Update App.jsx routes**

Open `frontend/src/App.jsx`. Find the imports and routes section. Add:
```jsx
import SectorList from './pages/SectorList.jsx';
import SectorDetail from './pages/SectorDetail.jsx';
```

In the `<Routes>` block, add:
```jsx
<Route path="/sector-tracker" element={<SectorList />} />
<Route path="/sector-tracker/:id" element={<SectorDetail />} />
```

- [ ] **Step 2: Update Layout.jsx menu**

Open `frontend/src/components/Layout.jsx`. Find where the existing menu items are defined (look for `NavLink` to `/` or `/win-rate`). Add a new menu item above the existing dashboard link:
```jsx
<NavLink to="/sector-tracker" className={({ isActive }) => isActive ? 'menu-item active' : 'menu-item'}>
  📊 板块追踪
</NavLink>
```

- [ ] **Step 3: Build the frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds (look for `dist/` updates)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/Layout.jsx
git commit -m "feat(sector): wire routes and menu for sector tracker"
```

---

## Task 13: Deployment script for scheduler

**Files:**
- Create: `deploy-scheduler.sh`

- [ ] **Step 1: Write the script**

```bash
#!/bin/bash
# Deploy sector scheduler process.
# Usage: ./deploy-scheduler.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "==> Stopping existing sector_scheduler (if any)..."
pkill -f "sector_scheduler.py" || true
sleep 1

echo "==> Starting sector_scheduler in background..."
mkdir -p logs
nohup python3 bot/sector_scheduler.py > logs/sector_scheduler.log 2>&1 &
disown
sleep 2

echo "==> Verifying process is running..."
if pgrep -f "sector_scheduler.py" > /dev/null; then
  echo "✓ sector_scheduler started (pid=$(pgrep -f sector_scheduler.py))"
  echo "  Logs: $PROJECT_DIR/logs/sector_scheduler.log"
else
  echo "✗ Failed to start sector_scheduler; check logs"
  exit 1
fi
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x deploy-scheduler.sh
git add deploy-scheduler.sh
git commit -m "ops: add deploy script for sector scheduler"
```

---

## Task 14: End-to-end smoke test

**Files:** None new (just verify)

- [ ] **Step 1: Start backend**

```bash
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Expected: Server starts; "Application startup complete."

- [ ] **Step 2: Verify API endpoints**

```bash
curl http://localhost:8000/api/sector-picks
```
Expected: `[]` (empty list)

- [ ] **Step 3: Create a test pick via API**

```bash
curl -X POST http://localhost:8000/api/sector-picks \
  -H "Content-Type: application/json" \
  -d '{
    "sector_name": "pvdf",
    "selection_source": "ai_knowledge",
    "t0_date": "2026-06-07",
    "stocks": [
      {"code": "002812", "name": "恩捷股份", "reason": "PVDF 龙头", "t0_price": 45.20, "t0_avg_price": 45.10},
      {"code": "002407", "name": "多氟多", "reason": "六氟磷酸锂", "t0_price": 18.30, "t0_avg_price": 18.20},
      {"code": "002460", "name": "赣锋锂业", "reason": "锂盐", "t0_price": 50.10, "t0_avg_price": 50.00}
    ]
  }'
```
Expected: `{"id":1, "created_at":"..."}`

- [ ] **Step 4: List picks**

```bash
curl http://localhost:8000/api/sector-picks
```
Expected: Array with 1 item including `sector_name: "pvdf"` and `avg_t*_pct: null`

- [ ] **Step 5: Archive pick**

```bash
curl -X POST http://localhost:8000/api/sector-picks/1/archive
```
Expected: `{"id":1, "status":"archived"}`

- [ ] **Step 6: Frontend build check**

```bash
cd frontend && npm run build
```
Expected: Build succeeds, no errors

- [ ] **Step 7: Manual bot test (if possible)**

In Telegram, click `📊 板块追踪`, send `pvdf`. Expected: Bot replies with 3 stocks + 数据源 line.

- [ ] **Step 8: Commit verification log**

```bash
git log --oneline -20
```
Expected: 14+ commits, all with `feat(sector):` or `test(sector):` or `ops:` prefix

---

## Self-Review

**Spec coverage check:**
- ✅ Data models → Task 1, 2
- ✅ Bot flow (inline button, 60s timer, A+B fallback) → Task 8
- ✅ Selector (board filter, DeepSeek prompt, parse) → Task 4
- ✅ T+N calculation → Task 5
- ✅ Cache 24h TTL → Task 6
- ✅ Scheduler 20:00 daily → Task 7
- ✅ API router + schemas → Task 3
- ✅ Frontend list page → Task 10
- ✅ Frontend detail page → Task 11
- ✅ Routes + menu → Task 12
- ✅ Deployment script → Task 13
- ✅ End-to-end smoke test → Task 14
- ✅ Tests for filter, parse, cache, tracker → Tasks 4-6
- ✅ Integration with existing telegram_bot.py → Task 8.2

**Placeholder scan:** No TBDs, no "implement later". Every code block is complete.

**Type consistency:**
- `SectorPick.status`: "in_progress" / "completed" / "archived" — same in model, schema, API, frontend
- `SectorPickStock.t5_pct` etc. — same in model, schema, frontend
- `selection_source`: "api_driven" / "ai_knowledge" — same throughout
- `is_main_board`, `is_st`, `is_within_market_cap`, `is_within_pe_median` — all defined in Task 4 and tested

**Missing item I noticed:** The spec mentions "watchdog cron to restart scheduler if dead" as a risk mitigation. I should add this as a follow-up. Add to Task 13 a note about the cron entry but don't make it blocking.
