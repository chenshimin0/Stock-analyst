import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'stock_analysis.db')}")

# Tencent Finance API (fast, reliable, used by price_service)
TENCENT_API_URL = "http://qt.gtimg.cn/q={codes}"
# Sina API kept as backup (may be unreachable from some regions)
SINA_API_URL = "https://hq.sinajs.cn/list={codes}"
SINA_REFERER = "https://finance.sina.com.cn"

CACHE_TTL_SECONDS = 30
WIN_RATE_PERIODS = [7, 15, 30, 90, 180]

CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8888",
    "http://127.0.0.1:8888",
    "http://101.36.106.113:8888",
]
