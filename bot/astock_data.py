"""
A-Stock Data Layer — wraps APIs from the a-stock-data skill.
=============================================================
Covers: real-time quotes (Tencent), K-line (mootdx/Sina),
fund flow (EastMoney push2), news (EastMoney search).

Zero custom scraping — all data via public HTTP/TCP APIs.
Reference: ~/.claude/skills/a-stock-data/SKILL.md
"""

import json
import logging
import re
import time
import urllib.request
from typing import Optional

logger = logging.getLogger("astock_data")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ---------------------------------------------------------------------------
# Market prefix
# ---------------------------------------------------------------------------

def _market(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


# ===================================================================
# 1. Real-time quotes — Tencent Finance API (qt.gtimg.cn)
#    Fields: price, PE/PB, market cap, turnover, change%, vol_ratio, etc.
# ===================================================================

def get_quote(code: str) -> dict:
    """Get real-time quote from Tencent Finance API.
    Returns dict with: code, name, price, change_pct, pe, pb, total_mv,
    turnover, high, low, open, volume, amount, vol_ratio, limit_up, limit_down.
    Returns empty dict on failure.
    """
    prefixed = f"{_market(code)}{code}"
    url = f"http://qt.gtimg.cn/q={prefixed}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk", errors="replace")
        match = re.search(r'"(.*?)"', raw)
        if not match:
            return {}
        fields = match.group(1).split("~")
        if len(fields) < 53:
            return {}
        name = fields[1]
        price = float(fields[3]) if fields[3] else 0
        if not name or price <= 0:
            return {}
        return {
            "code": code,
            "name": name,
            "price": price,
            "last_close": float(fields[4]) if fields[4] else 0,
            "open": float(fields[5]) if fields[5] else 0,
            "change_pct": float(fields[32]) if fields[32] else 0,
            "high": float(fields[33]) if fields[33] else 0,
            "low": float(fields[34]) if fields[34] else 0,
            "amount_wan": float(fields[37]) if fields[37] else 0,
            "turnover": float(fields[38]) if fields[38] else 0,
            "pe": float(fields[39]) if fields[39] else 0,
            "amplitude": float(fields[43]) if fields[43] else 0,
            "total_mv": float(fields[44]) if fields[44] else 0,
            "float_mv": float(fields[45]) if fields[45] else 0,
            "pb": float(fields[46]) if fields[46] else 0,
            "limit_up": float(fields[47]) if fields[47] else 0,
            "limit_down": float(fields[48]) if fields[48] else 0,
            "vol_ratio": float(fields[49]) if fields[49] else 0,
            "pe_static": float(fields[52]) if fields[52] else 0,
        }
    except Exception as e:
        logger.warning(f"Tencent quote failed for {code}: {e}")
        return {}


# ===================================================================
# 2. K-line via Sina Finance (HTTP, always available)
# ===================================================================

def get_kline_sina(code: str, days: int = 120) -> list:
    """Fetch daily K-line from Sina Finance. Returns list of dicts."""
    prefix = _market(code)
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={days}"
    )
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            import gzip
            raw = gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))
        if not data:
            return []
        return [
            {
                "date": d["day"],
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
                "volume": float(d["volume"]),
            }
            for d in data
        ]
    except Exception as e:
        logger.warning(f"Sina K-line failed for {code}: {e}")
        return []


# ===================================================================
# 3. K-line via mootdx (TCP, more reliable in mainland CN)
#    Requires: pip install mootdx
# ===================================================================

def get_kline_mootdx(code: str, count: int = 120) -> list:
    """Fetch daily K-line via mootdx TCP. Returns list of dicts."""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        market_code = 1 if code.startswith("6") else 0
        bars = client.bars(symbol=code, category=4, offset=count)
        if bars is None or len(bars) == 0:
            return []
        return [
            {
                "date": str(b.get("datetime", ""))[:10],
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
                "volume": float(b.get("vol", 0)),
            }
            for b in bars
        ]
    except ImportError:
        logger.debug("mootdx not installed, falling back to Sina")
        return []
    except Exception as e:
        logger.warning(f"mootdx K-line failed for {code}: {e}")
        return []


def get_kline(code: str, count: int = 120) -> list:
    """Get K-line data — mootdx first, Sina fallback."""
    kline = get_kline_mootdx(code, count)
    if kline:
        return kline
    return get_kline_sina(code, count)


# ===================================================================
# 4. Fund flow — EastMoney push2 API (individual stock fund flow)
# ===================================================================

def get_fund_flow(code: str) -> dict:
    """Get individual stock fund flow from EastMoney push2 API."""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?"
        f"lmt=0&klt=1&secid={secid}&fields1=f1,f2,f3,f7&fields2="
        f"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
    )
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://quote.eastmoney.com/"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return {}
        latest = klines[-1].split(",")
        if len(latest) < 7:
            return {}
        return {
            "date": latest[0],
            "main_net": float(latest[4]) if latest[4] != "-" else 0,  # 主力净流入(万)
            "main_pct": float(latest[5]) if latest[5] != "-" else 0,
            "super_large_net": float(latest[6]) if latest[6] != "-" else 0,
            "large_net": float(latest[7]) if len(latest) > 7 and latest[7] != "-" else 0,
            "medium_net": float(latest[8]) if len(latest) > 8 and latest[8] != "-" else 0,
            "retail_net": float(latest[9]) if len(latest) > 9 and latest[9] != "-" else 0,
        }
    except Exception as e:
        logger.warning(f"Fund flow failed for {code}: {e}")
        return {}


# ===================================================================
# 5. News — EastMoney search API
# ===================================================================

def search_news(code: str, name: str = "", page_size: int = 15) -> list:
    """Search news for a stock via EastMoney search API (JSONP)."""
    inner = json.dumps({
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default", "sort": "default",
                "pageIndex": 1, "pageSize": page_size,
                "preTag": "", "postTag": "",
            },
        },
    }, separators=(",", ":"))
    cb = "jQuery_news"
    url = f"https://search-api-web.eastmoney.com/search/jsonp?cb={cb}&param={urllib.parse.quote(inner)}"
    try:
        req = urllib.request.Request(url, headers={
            "Referer": "https://so.eastmoney.com/",
            "User-Agent": UA,
        })
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("utf-8", errors="replace")
        # Parse JSONP: jQuery_news_123(...)
        m = re.search(r"\((\{.*\})\)", raw, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(1))
        articles = data.get("result", {}).get("cmsArticleWebOld", [])
        # cmsArticleWebOld can be a list or dict with 'list' key
        if isinstance(articles, dict):
            articles = articles.get("list", [])
        items = []
        for a in articles:
            title = re.sub(r"<[^>]+>", "", a.get("title", ""))
            items.append({
                "title": title,
                "content": re.sub(r"<[^>]+>", "", a.get("content", ""))[:200],
                "source": a.get("mediaName", ""),
                "date": a.get("date", ""),
                "url": a.get("url", ""),
            })
        return items
    except Exception as e:
        logger.warning(f"News search failed for {code}: {e}")
        return []


# ===================================================================
# 6. Stock info — EastMoney push2 (sector, market cap, total shares)
# ===================================================================

def get_stock_info(code: str) -> dict:
    """Get basic stock info (sector, industry, shares) from EastMoney."""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get?"
        f"secid={secid}&fields=f57,f58,f100,f116,f117,f127,f162,f167"
    )
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://quote.eastmoney.com/"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read()).get("data", {})
        if not data:
            return {}
        return {
            "name": data.get("f58", ""),
            "industry": data.get("f100", ""),
            "total_mv": data.get("f116", 0),
            "float_mv": data.get("f117", 0),
            "sector_name": data.get("f127", ""),
            "pe": data.get("f162", 0),
            "turnover": data.get("f167", 0),
        }
    except Exception as e:
        logger.warning(f"Stock info failed for {code}: {e}")
        return {}
