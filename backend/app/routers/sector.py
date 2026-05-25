import sys
import os
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

# Allow importing from the sibling bot directory
_bot_dir = Path(__file__).parent.parent.parent.parent / "bot"
if str(_bot_dir) not in sys.path:
    sys.path.insert(0, str(_bot_dir))

from ai_analyzer import analyze_sector_industry_chain, recommend_stocks_by_sector

router = APIRouter(prefix="/sector", tags=["sector"])


class SectorAnalysisRequest(BaseModel):
    query: str
    top_n: int = 5


@router.post("/analyze")
async def sector_industry_chain_analysis(req: SectorAnalysisRequest):
    """板块产业链深度分析：上下游图谱 + 低PE/低股价/分红/龙头筛选"""
    result = analyze_sector_industry_chain(req.query, req.top_n)
    return result


@router.post("/recommend")
async def sector_recommend_stocks(req: SectorAnalysisRequest):
    """板块相关股票推荐"""
    result = recommend_stocks_by_sector(req.query, req.top_n)
    return result


@router.get("/analyze")
async def sector_analyze_get(
    query: str = Query(..., description="板块名称或主题"),
    top_n: int = Query(5, ge=1, le=10, description="推荐股票数量"),
):
    """GET方式板块产业链分析"""
    result = analyze_sector_industry_chain(query, top_n)
    return result
