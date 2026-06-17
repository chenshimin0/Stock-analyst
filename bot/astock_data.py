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
import requests
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
        bars = client.bars(symbol=code, category=4, offset=count)
        if bars is None or len(bars) == 0:
            return []
        # mootdx returns a pandas DataFrame; convert to list of dicts
        import pandas as pd
        if isinstance(bars, pd.DataFrame):
            bars = bars.to_dict("records")
        return [
            {
                "date": str(b.get("datetime", "") if isinstance(b, dict) else getattr(b, "datetime", ""))[:10],
                "open": float(b.get("open", 0) if isinstance(b, dict) else getattr(b, "open", 0)),
                "high": float(b.get("high", 0) if isinstance(b, dict) else getattr(b, "high", 0)),
                "low": float(b.get("low", 0) if isinstance(b, dict) else getattr(b, "low", 0)),
                "close": float(b.get("close", 0) if isinstance(b, dict) else getattr(b, "close", 0)),
                "volume": float(b.get("vol", 0) if isinstance(b, dict) else getattr(b, "vol", 0)),
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
    """Get individual stock fund flow from EastMoney push2 API (latest day only)."""
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


def get_fund_flow_recent(code: str, days: int = 3) -> list:
    """Get individual stock fund flow for recent N days.

    Returns list of {date, main_net, main_pct, super_large_net, large_net,
                     medium_net, retail_net} dicts (oldest first), or [] on failure.
    """
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?"
        f"lmt={days}&klt=1&secid={secid}&fields1=f1,f2,f3,f7&fields2="
        f"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
    )
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://quote.eastmoney.com/"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return []
        out = []
        for line in klines[-days:]:
            p = line.split(",")
            if len(p) < 7:
                continue
            out.append({
                "date": p[0],
                "main_net": float(p[4]) if p[4] != "-" else 0,
                "main_pct": float(p[5]) if p[5] != "-" else 0,
                "super_large_net": float(p[6]) if p[6] != "-" else 0,
                "large_net": float(p[7]) if len(p) > 7 and p[7] != "-" else 0,
                "medium_net": float(p[8]) if len(p) > 8 and p[8] != "-" else 0,
                "retail_net": float(p[9]) if len(p) > 9 and p[9] != "-" else 0,
            })
        return out
    except Exception as e:
        logger.warning(f"Fund flow recent failed for {code}: {e}")
        return []


def get_last_limit_up_date(code: str, lookback_days: int = 120) -> Optional[str]:
    """Find the most recent limit-up date for a stock.

    Returns date string YYYY-MM-DD or None if no limit-up in the period.
    Uses Tencent K-line data (前复权) and checks if close >= limit-up price.
    """
    from datetime import datetime, timedelta
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    today = datetime.now()
    start = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        f"param={prefix}{code},day,{start},{end},500,qfq"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read()
        if raw[:2] == b'\x1f\x8b':
            import gzip as _gzip
            raw = _gzip.decompress(raw)
        data = json.loads(raw)
        key = f"{prefix}{code}"
        if key not in data.get("data", {}):
            return None
        klines = data["data"][key].get("qfqday") or data["data"][key].get("day") or []
        if not klines:
            return None
        # Sort chronologically (oldest first) and compute (today_close - prev_close) / prev_close
        # Verified against EastMoney data — this is the canonical way (前复权 K-line 用
        # 收盘价对比而非开/收对比，因为除权日开盘价已调整会导致失真)
        bars = []
        for bar in klines:
            if len(bar) < 3:
                continue
            try:
                bars.append((str(bar[0]), float(bar[1]), float(bar[2])))
            except (ValueError, TypeError):
                continue
        bars.sort(key=lambda x: x[0])
        # Walk backwards (newest first) to find the MOST RECENT limit-up day
        for i in range(len(bars) - 1, 0, -1):
            prev_close = bars[i-1][2]
            today_close = bars[i][2]
            if prev_close <= 0:
                continue
            change_pct = (today_close - prev_close) / prev_close * 100
            # 主板涨停 10%，科创/创业 20%，ST 5%；统一用 ≥9.5% 简化判断
            if change_pct >= 9.5:
                return bars[i][0]  # already in YYYY-MM-DD format
        return None
    except Exception as e:
        logger.warning(f"Last limit-up fetch failed for {code}: {e}")
        return None


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


# ===================================================================
# 7. Concept boards — EastMoney CoreConception API
# ===================================================================

def get_concept_boards(code: str) -> list:
    """Get all concept/theme boards for a stock from EastMoney.

    Returns list of {board_name, board_code, is_precise, board_rank}.
    Example: CPO概念, 光通信, 5G, 华为概念 etc.
    """
    market = "SH" if code.startswith("6") else "SZ"
    url = (
        f"https://emweb.securities.eastmoney.com/"
        f"PC_HSF10/CoreConception/PageAjax?code={market}{code}"
    )
    headers = {"Referer": "https://emweb.securities.eastmoney.com/"}

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read()
        if raw[:2] == b'\x1f\x8b':
            import gzip
            raw = gzip.decompress(raw)
        data = json.loads(raw)
        boards = []
        for item in data.get("ssbk", []):
            boards.append({
                "board_name": item.get("BOARD_NAME", ""),
                "board_code": f"BK{item['BOARD_CODE']}" if item.get("BOARD_CODE") else "",
                "is_precise": item.get("IS_PRECISE", "0") == "1",
                "board_rank": item.get("BOARD_RANK", 99),
            })
        return boards
    except Exception as e:
        logger.warning(f"get_concept_boards failed for {code}: {e}")
        return []


# ===================================================================
# 7. Financial data — East Money datacenter API (RPT_F10_FINANCE_MAINFINADATA)
#    Covers: income statement, balance sheet, cash flow, R&D, valuation metrics.
#    Returns structured financial data for multi-year analysis.
# ===================================================================

_EM_DATACENTER = "https://datacenter.eastmoney.com/api/data/v1/get"
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _em_get(report_name: str, filter_str: str, page_size: int = 20,
            sort_columns: str = "REPORT_DATE", sort_types: str = "-1") -> list:
    """Generic East Money datacenter API fetcher with retry."""
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortTypes": sort_types,
        "sortColumns": sort_columns,
        "filter": filter_str,
        "source": "WEB",
        "client": "WEB",
    }
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{_EM_DATACENTER}?{query}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_EM_HEADERS)
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return (data.get("result") or {}).get("data") or []
            return []
        except Exception as e:
            if attempt == 2:
                logger.warning(f"EM datacenter failed: {e}")
                return []
            time.sleep(1 + attempt * 0.5)
    return []


def get_financial_data_em(code: str, years: int = 5) -> dict:
    """Fetch multi-year financial indicators from East Money datacenter.

    Returns:
      - "annual": list of dicts, each with year, revenue(亿), revenue_yoy(%),
        net_profit(亿), net_profit_yoy(%), deducted_profit(亿), deducted_profit_yoy(%),
        gross_margin(%), net_margin(%), roe_weighted(%), debt_ratio(%),
        current_ratio, eps, bvps, cf_oper(亿), rd_expense(亿), rd_rev_ratio(%),
        total_assets(亿), total_equity(亿), total_shares(亿), staff_num
      - "latest_quarter": same keys for most recent quarter (may be Q1/Q2/Q3)
    Returns {} on failure.
    """
    try:
        rows = _em_get("RPT_F10_FINANCE_MAINFINADATA",
                        f'(SECURITY_CODE="{code}")',
                        page_size=years * 5)

        def _to_yi(val) -> float:
            """Convert raw yuan to yi (divide by 1e8)."""
            if val is None:
                return 0.0
            return round(float(val) / 1e8, 2)

        def _pct(val) -> float:
            if val is None:
                return 0.0
            return round(float(val), 2)

        def _parse_row(r: dict) -> dict:
            """Parse a single data row into the structured format."""
            total_shares = float(r.get("TOTAL_SHARE") or 0)
            return {
                "year": int((r["REPORT_DATE"] or "")[:4]) if r.get("REPORT_DATE") else 0,
                "report_date": (r.get("REPORT_DATE") or "")[:10],
                "revenue": _to_yi(r.get("TOTALOPERATEREVE")),
                "revenue_yoy": _pct(r.get("TOTALOPERATEREVETZ")),
                "net_profit": _to_yi(r.get("PARENTNETPROFIT")),
                "net_profit_yoy": _pct(r.get("PARENTNETPROFITTZ")),
                "deducted_profit": _to_yi(r.get("KCFJCXSYJLR")),
                "deducted_profit_yoy": _pct(r.get("KCFJCXSYJLRTZ")),
                "gross_margin": _pct(r.get("XSMLL")),
                "net_margin": _pct(r.get("XSJLL")),
                "roe_weighted": _pct(r.get("ROEJQ")),
                "debt_ratio": _pct(r.get("ZCFZL")),
                "current_ratio": _pct(r.get("LD")),
                "eps": _pct(r.get("EPSJB")),
                "bvps": _pct(r.get("BPS")),
                "cf_oper": _to_yi((r.get("MGJYXJJE") or 0) * total_shares) if total_shares else 0,
                "rd_expense": _to_yi(r.get("RDEXPEND")),
                "rd_rev_ratio": _pct(r.get("PRATIO")),
                "rd_personnel": r.get("RDPERSONNEL"),
                "total_assets": _to_yi(r.get("TOTAL_ASSETS_PK")),
                "total_equity": _to_yi(r.get("TOTAL_EQUITY_PK")),
                "total_shares": round(total_shares / 1e8, 2) if total_shares else 0,
                "staff_num": r.get("STAFF_NUM"),
                "report_type": r.get("REPORT_TYPE", ""),
            }

        all_rows = [_parse_row(r) for r in rows if r.get("REPORT_DATE")]
        # Sort by date descending
        all_rows.sort(key=lambda x: x["report_date"], reverse=True)

        # Separate annual reports from quarterly
        annual = [r for r in all_rows if r["report_type"] == "年报"]
        # Cap at requested years
        annual = annual[:years]

        # Latest quarterly (Q1, half-year, Q3)
        quarters = [r for r in all_rows if r["report_type"] != "年报"]
        latest_quarter = quarters[0] if quarters else {}

        result = {"annual": annual}
        if latest_quarter:
            result["latest_quarter"] = latest_quarter
        return result
    except Exception as e:
        logger.warning(f"get_financial_data_em failed for {code}: {e}")
        return {}


def get_peer_comparison_em(code: str) -> dict:
    """Get peer company financial comparison data.

    Uses 10jqka industry comparison page to extract structured peer metrics.
    Selects the table with highest total revenue (annual data), deduplicates,
    and returns top peers sorted by revenue.

    Returns {"peers": [...], "industry_name": ""} or {} on failure.
    """
    try:
        from astock_data_10jqka import get_industry_comparison
        ic = get_industry_comparison(code)
        tables = ic.get("tables", [])
        if not tables:
            return {}

        def _parse_num(val_str: str) -> float:
            if not val_str:
                return 0.0
            s = str(val_str).replace(",", "").replace("%", "").strip()
            if "亿" in s:
                return float(s.replace("亿", ""))
            if "万" in s:
                return float(s.replace("万", "")) / 10000
            try:
                return float(s)
            except ValueError:
                return 0.0

        # Pick the table with the highest total revenue (annual data, not quarterly)
        best_rows = []
        best_rev = 0
        for t in tables:
            cols = t.get("columns", [])
            rows = t.get("rows", [])
            if not any(kw in "".join(cols) for kw in ["股票简称", "股票代码"]):
                continue
            total_rev = sum(_parse_num(r.get("营业总收入(元)", "0")) for r in rows)
            if total_rev > best_rev:
                best_rev = total_rev
                best_rows = rows

        if not best_rows:
            return {}

        # Deduplicate and build peer list
        seen = set()
        peers = []
        for row in best_rows:
            peer_code = str(row.get("股票代码", "")).strip()
            peer_name = str(row.get("股票简称", "")).strip()
            if not peer_code or not peer_name or peer_code in seen:
                continue
            seen.add(peer_code)

            equity_ratio = _parse_num(row.get("股东权益比率", "0"))
            rev = _parse_num(row.get("营业总收入(元)", "0"))
            np_val = _parse_num(row.get("净利润(元)", "0"))
            gm = _parse_num(row.get("销售毛利率", "0"))
            roe = _parse_num(row.get("净资产收益率", "0"))

            peers.append({
                "code": peer_code,
                "name": peer_name,
                "revenue": rev,
                "net_profit": np_val,
                "gross_margin": gm,
                "roe": roe,
                "debt_ratio": round(100 - equity_ratio, 1) if equity_ratio else None,
                "eps": _parse_num(row.get("每股收益(元)", "0")),
                "bvps": _parse_num(row.get("每股净资产(元)", "0")),
                "total_assets": _parse_num(row.get("总资产(元)", "0")),
                "market_cap": None,
                "pe": None,
                "pb": None,
            })

        # Sort by revenue desc, limit to top 30
        peers.sort(key=lambda x: x["revenue"], reverse=True)
        peers = peers[:30]

        return {"peers": peers, "industry_name": ""}
    except Exception as e:
        logger.warning(f"get_peer_comparison_em failed for {code}: {e}")
        return {}


def get_revenue_composition_em(code: str) -> dict:
    """Get revenue composition (主营构成) from EastMoney F10 BusinessAnalysis API.

    Returns {"by_product": [...], "by_region": [...], "report_date": "..."} or {} on failure.
    Each item: {"name": str, "revenue": float, "ratio_pct": float, "gross_margin_pct": float}
    """
    try:
        url = (
            "https://emweb.securities.eastmoney.com/PC_HSF10/"
            "BusinessAnalysis/PageAjax"
        )
        params = {"code": f"{'SH' if code.startswith(('6', '9')) else 'SZ'}{code}"}
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://emweb.securities.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        d = r.json()
        zygcfx = d.get("zygcfx", [])
        if not zygcfx:
            return {}

        # Get latest report date's data
        dates = sorted(set(item["REPORT_DATE"] for item in zygcfx), reverse=True)
        latest = dates[0] if dates else ""

        def _parse_items(op_type: str) -> list:
            items = [
                i for i in zygcfx
                if i["REPORT_DATE"] == latest and str(i.get("MAINOP_TYPE", "")) == op_type
            ]
            # Sort by ratio descending, filter out "其他(补充)" noise if there are enough items
            items.sort(key=lambda x: x.get("MBI_RATIO", 0), reverse=True)
            result = []
            for i in items:
                name = i.get("ITEM_NAME", "").strip()
                # Skip "其他" type entries unless they're significant
                if "补充" in name or "内部抵消" in name or "分部间抵销" in name:
                    continue
                ratio = i.get("MBI_RATIO", 0)
                if isinstance(ratio, (int, float)):
                    ratio = round(ratio * 100, 2)  # API returns decimal, convert to %
                result.append({
                    "name": name,
                    "revenue": i.get("MAIN_BUSINESS_INCOME", 0),
                    "ratio_pct": ratio,
                    "gross_margin_pct": round(i.get("GROSS_RPOFIT_RATIO", 0) * 100, 2)
                    if i.get("GROSS_RPOFIT_RATIO") is not None else None,
                })
            return result[:8]  # top 8 items max

        by_product = _parse_items("2")
        by_region = _parse_items("3")

        if not by_product and not by_region:
            return {}

        return {
            "by_product": by_product,
            "by_region": by_region,
            "report_date": latest[:10] if latest else "",
        }
    except Exception as e:
        logger.warning(f"get_revenue_composition_em failed for {code}: {e}")
        return {}
