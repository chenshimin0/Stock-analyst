from fastapi import APIRouter

from app.schemas import StockPrice
from app.services.price_service import PriceService

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/{code}/price", response_model=StockPrice)
async def get_stock_price(code: str):
    data = await PriceService.get_realtime_price(code)
    if data:
        return StockPrice(**data)
    return StockPrice(
        code=code, name="N/A", price=0, open=0, high=0, low=0,
        prev_close=0, change_pct=0, date="", time="",
    )


@router.post("/prices", response_model=list[StockPrice])
async def get_stock_prices(codes: list[str]):
    data = await PriceService.get_realtime_prices_batch(codes)
    return [StockPrice(**d) for d in data]
