"""
10jqka (同花顺) Data Layer — direct HTTP APIs with retry mechanism.
===================================================================
Covers: real-time quote (d.10jqka.com.cn realhead), K-line, minute data,
EPS forecast (basic.10jqka.com.cn worth), hot-stock reasons (zx.10jqka.com.cn),
industry comparison (basic.10jqka.com.cn field), financial tables (F10 pages).

All endpoints are JSONP / HTML-table based, zero auth required.
"""

import gzip
import json
import logging
import os
import random
import re
import time
import urllib.request
import urllib.parse
from datetime import date as _date
from io import BytesIO
from typing import Optional

logger = logging.getLogger("astock_data_10jqka")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REFERER = "https://stockpage.10jqka.com.cn/"

# ---------------------------------------------------------------------------
# Retry utility
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 10, max_retries: int = 3,
              extra_headers: dict = None, decode_gzip: bool = True) -> bytes:
    """GET with exponential backoff retry. Returns raw bytes."""
    headers = {"User-Agent": UA, "Referer": REFERER}
    if extra_headers:
        headers.update(extra_headers)

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=timeout)
            raw = resp.read()
            if decode_gzip and raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = (2 ** attempt) + random.uniform(0, 0.5)
            logger.debug(f"Retry {attempt + 1}/{max_retries} for {url[:80]} after {delay:.1f}s: {e}")
            time.sleep(delay)
    return b""


def _parse_jsonp(raw: bytes) -> dict:
    """Parse 10jqka JSONP response: callback_name({...})"""
    text = raw.decode("utf-8", errors="replace")
    m = re.search(r"\((\{.*\})\)", text, re.DOTALL)
    if not m:
        return {}
    return json.loads(m.group(1))


# ---------------------------------------------------------------------------
# Market prefix
# ---------------------------------------------------------------------------

def _prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


# ===================================================================
# 1. Real-time quote — d.10jqka.com.cn realhead
# ===================================================================

# Known field-ID → label mapping (10jqka HQ bridge field codes).
# Verified against realhead_v2.html template element IDs.
_FIELD_MAP = {
    "5": "code",
    "6": "last_close",
    "7": "open",
    "8": "high",
    "9": "low",
    "10": "price",
    "12": "market_id",
    "13": "volume",
    "14": "inner_vol",
    "15": "outer_vol",
    "17": "turnover_vol",
    "19": "amount",
    "24": "bid1_price",
    "25": "bid1_vol",
    "30": "ask1_price",
    "31": "ask1_vol",
    "37": "bid2_price",
    "38": "bid2_vol",
    "39": "ask2_price",
    "49": "ask2_vol",
    "51": "bid3_price",
    "66": "ask3_price",
    "69": "limit_up",
    "70": "limit_down",
    "74": "bid3_vol",
    "75": "ask3_vol",
    "85": "bid4_vol",
    "90": "ask4_vol",
    "92": "ask4_price",
    "95": "bid5_vol",
    "96": "ask5_vol",
    "127": "pe_dynamic",
    "130": "vol_ratio_val",
    "223": "main_net_5d",
    "224": "main_net_10d",
    "225": "main_net_20d",
    "226": "main_net_60d",
    "237": "main_net_120d",
    "238": "main_net_250d",
    "259": "main_net_1y",
    "260": "main_net_2y",
    # Additional decoded fields from realhead data
    "1968584": "turnover_pct",
    "2034120": "pe_ttm",
    "1378761": "pb",
    "3475914": "total_mv",
    "3541450": "float_mv",
    "526792": "change_rate_5d",
    "395720": "amplitude",
    "1149395": "dividend_yield",
    "1771976": "weighted_vol_ratio",
    "592920": "change_pct",
    "134152": "amount_yi",
}


def get_realtime_10jqka(code: str) -> dict:
    """Get real-time quote from 10jqka realhead JSONP API.

    Returns dict with: code, name, price, last_close, open, high, low,
    volume, amount, limit_up, limit_down, change_pct, turnover_pct,
    pe_ttm, pb, total_mv, float_mv, amplitude, vol_ratio_val.
    Also includes raw items dict for debugging.
    """
    url = f"http://d.10jqka.com.cn/v2/realhead/hs_{code}/last.js"
    try:
        raw = _http_get(url, timeout=8)
        d = _parse_jsonp(raw)
        if not d:
            return {}

        items = d.get("items", {})
        result = {"code": code, "name": d.get("name", ""), "stop": d.get("stop", 0),
                  "time": d.get("time", ""), "_raw_items": items}

        for field_id, label in _FIELD_MAP.items():
            val = items.get(field_id)
            if val is not None and val != "" and val != "-":
                try:
                    result[label] = float(val)
                except (ValueError, TypeError):
                    result[label] = val
            elif val == "":
                result[label] = None

        # price is the canonical field
        if result.get("price", 0) <= 0:
            return {}
        return result
    except Exception as e:
        logger.warning(f"10jqka realhead failed for {code}: {e}")
        return {}


# ===================================================================
# 2. Daily K-line — d.10jqka.com.cn line
# ===================================================================

def get_kline_10jqka(code: str, count: int = 120) -> list:
    """Fetch daily K-line from 10jqka JSONP API.

    Returns list of {date, open, high, low, close, volume, amount, turnover}.
    Data format: date,open,high,low,close,volume,amount,turnover,,,0
    """
    url = f"http://d.10jqka.com.cn/v2/line/hs_{code}/01/last.js"
    try:
        raw = _http_get(url, timeout=10)
        d = _parse_jsonp(raw)
        if not d:
            return []
        data_str = d.get("data", "")
        if not data_str:
            return []
        result = []
        lines = data_str.split(";")
        for line in lines:
            parts = line.split(",")
            if len(parts) < 8:
                continue
            result.append({
                "date": parts[0],
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "turnover": float(parts[7]) if parts[7] else 0,
            })
        # Return last `count` bars
        return result[-count:] if count and len(result) > count else result
    except Exception as e:
        logger.warning(f"10jqka K-line failed for {code}: {e}")
        return []


# ===================================================================
# 3. Minute time series — d.10jqka.com.cn time
# ===================================================================

def get_minute_data(code: str) -> dict:
    """Fetch intraday minute-level time series.

    Returns {date, name, pre_close, open, stop, isTrading, points: [{time, price, vol, avg_price, amount}]}
    """
    url = f"http://d.10jqka.com.cn/v2/time/hs_{code}/last.js"
    try:
        raw = _http_get(url, timeout=8)
        d = _parse_jsonp(raw)
        stock_data = d.get(f"hs_{code}", {})
        if not stock_data:
            return {}

        data_str = stock_data.get("data", "")
        points = []
        if data_str:
            for line in data_str.split(";"):
                parts = line.split(",")
                if len(parts) >= 4:
                    points.append({
                        "time": parts[0],
                        "price": float(parts[1]),
                        "volume": float(parts[2]) if len(parts) > 2 else 0,
                        "avg_price": float(parts[3]) if len(parts) > 3 else 0,
                    })

        return {
            "date": stock_data.get("date", ""),
            "name": stock_data.get("name", ""),
            "open": stock_data.get("open", 0),
            "stop": stock_data.get("stop", 0),
            "isTrading": stock_data.get("isTrading", 0),
            "pre_close": stock_data.get("pre", 0),
            "points": points,
            "dots_count": stock_data.get("dotsCount", 0),
            "trade_times": stock_data.get("tradeTime", []),
        }
    except Exception as e:
        logger.warning(f"10jqka minute data failed for {code}: {e}")
        return {}


# ===================================================================
# 4. EPS forecast — basic.10jqka.com.cn worth.html
# ===================================================================

def _parse_html_tables(text: str) -> list:
    """Parse HTML tables using BeautifulSoup (more robust than pd.read_html for 10jqka).

    Returns list of {columns: [str], rows: [{col: val}]} dicts.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "lxml")
        tables = []
        for table in soup.find_all("table"):
            all_rows = table.find_all("tr")
            if len(all_rows) < 1:
                continue
            # Extract headers from first row
            header_cells = all_rows[0].find_all(["th", "td"])
            headers = [c.get_text(strip=True) for c in header_cells]
            if not headers:
                continue
            rows = []
            for tr in all_rows[1:]:
                cells = tr.find_all(["th", "td"])
                if not cells:
                    continue
                row = {}
                for i, cell in enumerate(cells):
                    key = headers[i] if i < len(headers) else str(i)
                    row[key] = cell.get_text(strip=True)
                rows.append(row)
            tables.append({"columns": headers, "rows": rows})
        return tables
    except ImportError:
        logger.debug("BeautifulSoup not available, trying pandas fallback")
        return _parse_html_tables_pandas(text)


def _parse_html_tables_pandas(text: str) -> list:
    """Fallback HTML table parser using pandas."""
    try:
        import pandas as pd
        dfs = pd.read_html(BytesIO(text.encode()), flavor="lxml")
        tables = []
        for df in dfs:
            cols = [str(c) for c in df.columns]
            rows = []
            for _, row in df.iterrows():
                r = {}
                for i, val in enumerate(row):
                    try:
                        v = float(val) if val is not None and str(val).replace(".", "").replace("-", "").isdigit() else str(val)
                    except (ValueError, TypeError):
                        v = str(val) if val is not None else ""
                    r[cols[i] if i < len(cols) else str(i)] = v
                rows.append(r)
            tables.append({"columns": cols, "rows": rows})
        return tables
    except Exception:
        return []


def get_eps_forecast(code: str) -> dict:
    """Fetch institutional consensus EPS forecast from 10jqka F10 worth page.

    Parses HTML table using BeautifulSoup.
    Returns {raw_html_cols: [str], rows: [dict]} or {} on failure.
    """
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    try:
        raw = _http_get(url, timeout=15, max_retries=2)
        text = raw.decode("gbk", errors="replace")
        tables = _parse_html_tables(text)
        if not tables:
            return {}

        # Find the EPS forecast table (summary table with annual consensus)
        target = None
        for t in tables:
            col_text = " ".join(t["columns"])
            if any(kw in col_text for kw in ["每股收益", "均值", "预测机构", "一致预期", "净利润"]) and t["rows"]:
                target = t
                break

        if target is None:
            target = tables[0]

        # Clean: convert numeric strings to floats
        clean_rows = []
        for row in target["rows"]:
            r = {}
            for k, v in row.items():
                try:
                    r[k] = float(v) if v and v.replace(".", "").replace("-", "").replace("%", "").isdigit() else v
                except (ValueError, TypeError):
                    r[k] = v
            clean_rows.append(r)

        return {
            "raw_html_cols": target["columns"],
            "rows": clean_rows,
        }
    except Exception as e:
        logger.warning(f"EPS forecast failed for {code}: {e}")
        return {}


# ===================================================================
# 5. Hot stocks with reason tags — zx.10jqka.com.cn
# ===================================================================

def get_hot_reasons(target_date: str = None) -> list:
    """Fetch today's strong-performing stocks with editorial reason tags.

    Returns list of {code, name, reason, close, change_pct, turnover, amount, ...}
    Each stock has a "reason" field = manual editorial tags (e.g. "算力租赁+AI政务").
    """
    if target_date is None:
        target_date = _date.today().strftime("%Y-%m-%d")

    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{target_date}/orderby/date/orderway/desc/charset/GBK/"
    try:
        raw = _http_get(url, timeout=10, max_retries=2,
                        extra_headers={"Referer": "http://zx.10jqka.com.cn/"})
        data = json.loads(raw.decode("gbk", errors="replace"))
        if data.get("errocode", 0) != 0:
            logger.warning(f"Hot reasons API error: {data.get('errormsg', '')}")
            return []

        rows = data.get("data") or []
        result = []
        for item in rows:
            result.append({
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "reason": item.get("reason", ""),
                "close": item.get("close", 0),
                "change_pct": item.get("zhangfu", 0),
                "change_amt": item.get("zhangdie", 0),
                "turnover": item.get("huanshou", 0),
                "amount": item.get("chengjiaoe", 0),
                "volume": item.get("chengjiaoliang", 0),
                "dde_net": item.get("ddejingliang", 0),
                "market": item.get("market", ""),
            })
        return result
    except Exception as e:
        logger.warning(f"Hot reasons failed: {e}")
        return []


def get_stock_hot_reason(code: str) -> Optional[str]:
    """Get the hot reason tag for a specific stock today."""
    try:
        hot_list = get_hot_reasons()
        for item in hot_list:
            if item["code"] == code:
                return item["reason"]
    except Exception:
        pass
    return None


# ===================================================================
# 6. Financial data — basic.10jqka.com.cn F10 pages (HTML tables)
# ===================================================================

def _fetch_f10_html_tables(code: str, page: str) -> list:
    """Fetch a 10jqka F10 page and extract all HTML tables as dicts."""
    url = f"https://basic.10jqka.com.cn/{code}/{page}.html"
    try:
        raw = _http_get(url, timeout=15, max_retries=2)
        text = raw.decode("gbk", errors="replace")
        return _parse_html_tables(text)
    except Exception as e:
        logger.warning(f"F10 {page} failed for {code}: {e}")
        return []


def get_finance_summary(code: str) -> dict:
    """Extract key financial indicators from F10 finance page."""
    try:
        tables = _fetch_f10_html_tables(code, "finance")
        if not tables:
            return {}
        result = {"tables": []}
        for i, t in enumerate(tables):
            result["tables"].append({
                "index": i,
                "columns": t["columns"],
                "rows": t["rows"][:20],
            })
        return result
    except Exception as e:
        logger.warning(f"Finance summary failed for {code}: {e}")
        return {}


def get_industry_comparison(code: str) -> dict:
    """Extract industry comparison data from F10 field page.

    Parses industry ranking table: stock vs industry peers on PE/PB/ROE/market cap etc.
    """
    try:
        tables = _fetch_f10_html_tables(code, "field")
        if not tables:
            return {}
        result = {"tables": []}
        for i, t in enumerate(tables):
            result["tables"].append({
                "index": i,
                "columns": t["columns"],
                "rows": t["rows"][:30],
            })
        return result
    except Exception as e:
        logger.warning(f"Industry comparison failed for {code}: {e}")
        return {}


def get_company_info(code: str) -> dict:
    """Extract company basic info from F10 company page."""
    try:
        tables = _fetch_f10_html_tables(code, "company")
        if not tables:
            return {}
        result = {"tables": []}
        for i, t in enumerate(tables):
            result["tables"].append({
                "index": i,
                "columns": t["columns"],
                "rows": t["rows"][:15],
            })
        return result
    except Exception as e:
        logger.warning(f"Company info failed for {code}: {e}")
        return {}


# ===================================================================
# 7. Bulk fetch — all 10jqka data for a single stock
# ===================================================================

def fetch_all_10jqka(code: str) -> dict:
    """Fetch all available 10jqka data for a stock. Returns a consolidated dict."""
    result = {"code": code, "source": "10jqka"}

    # Real-time quote
    rt = get_realtime_10jqka(code)
    result["realtime"] = rt

    # K-line (full history, last 250 bars for analysis)
    kline = get_kline_10jqka(code, count=250)
    result["kline"] = kline

    # Minute data (only during trading hours)
    minute = get_minute_data(code)
    result["minute"] = minute

    # EPS forecast
    eps = get_eps_forecast(code)
    result["eps_forecast"] = eps

    # Hot reason (if in hot list today)
    hot_reason = get_stock_hot_reason(code)
    result["hot_reason"] = hot_reason

    # Financial summary (heavy, skip by default for speed)
    # result["finance"] = get_finance_summary(code)
    # result["industry_compare"] = get_industry_comparison(code)
    # result["company"] = get_company_info(code)

    return result


# ===================================================================
# 7b. Concept boards from 10jqka F10 (requires login cookies)
# ===================================================================


def _load_10jqka_cookies() -> dict:
    """Load 10jqka cookies from encrypted cache. Returns dict of cookies or empty dict."""
    try:
        from crypto_utils import decrypt
        enc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "10jqka_cookies.enc")
        if not os.path.exists(enc_path):
            return {}
        with open(enc_path, "r") as f:
            encrypted = f.read().strip()
        passphrase = "wwFblXr9ZyaobfcjNoZhApJZZqUs52+3"
        cookie_str = decrypt(encrypted, passphrase)
        cookies = {}
        for item in cookie_str.split("; "):
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k] = v
        return cookies
    except Exception as e:
        logger.debug(f"Failed to load 10jqka cookies: {e}")
        return {}


def get_concept_boards_10jqka(code: str) -> list:
    """Get concept/thematic boards for a stock from 10jqka F10 concept page.

    Requires login cookies in 10jqka_cookies.enc. Falls back to empty list.
    Returns list of {board_name, board_code, reason}.
    """
    cookies = _load_10jqka_cookies()
    if not cookies.get("sess_tk"):
        logger.debug("No valid 10jqka session cookie, skipping concept boards")
        return []

    url = f"https://basic.10jqka.com.cn/{code}/concept.html"
    try:
        raw = _http_get(url, timeout=15, max_retries=1,
                        extra_headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())})
        text = raw.decode("gbk", errors="replace")

        # Parse concept table rows: <td class="gnName" clid="ID">NAME</td>
        import re
        rows = re.findall(r'<td class="gnName"[^>]*clid="(\d+)"[^>]*>\s*(\S+?)\s*</td>', text)
        if not rows:
            # Try alternative pattern for the cList gnName format
            rows = re.findall(r'clid="(\d+)"[^>]*>\s*<span[^>]*>([^<]+)</span>', text, re.DOTALL)
            if not rows:
                # Try simpler pattern
                rows = re.findall(r'clid="(\d+)"[^>]*>\s*(\S+?)\s*<', text)

        boards = []
        seen = set()
        for clid, name in rows:
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                boards.append({
                    "board_name": name,
                    "board_code": f"GN{clid}",
                    "source": "10jqka",
                })
        logger.info(f"10jqka concept boards for {code}: {len(boards)} boards")
        return boards
    except Exception as e:
        logger.warning(f"10jqka concept boards failed for {code}: {e}")
        return []


# ===================================================================
# 8. Utility: enrich existing quote dict with 10jqka data
# ===================================================================

def enrich_quote_10jqka(quote: dict) -> dict:
    """Enhance an existing quote dict (from Tencent API) with 10jqka realtime fields.

    Only adds fields that Tencent doesn't provide. Existing fields are NOT overwritten.
    """
    code = quote.get("code", "")
    if not code:
        return quote

    try:
        rt = get_realtime_10jqka(code)
        if not rt:
            return quote

        # Merge new fields (don't overwrite existing)
        new_fields = {
            "limit_up": rt.get("limit_up"),
            "limit_down": rt.get("limit_down"),
            "bid1_price": rt.get("bid1_price"),
            "bid1_vol": rt.get("bid1_vol"),
            "ask1_price": rt.get("ask1_price"),
            "ask1_vol": rt.get("ask1_vol"),
            "turnover_pct": rt.get("turnover_pct"),
            "amount_yi": rt.get("amount_yi"),
            "change_rate_5d": rt.get("change_rate_5d"),
            "main_net_5d": rt.get("main_net_5d"),
            "main_net_10d": rt.get("main_net_10d"),
            "main_net_20d": rt.get("main_net_20d"),
            "amplitude": rt.get("amplitude"),
            "vol_ratio_val": rt.get("vol_ratio_val"),
        }
        for k, v in new_fields.items():
            if v is not None and k not in quote:
                quote[k] = v
    except Exception as e:
        logger.debug(f"enrich_quote_10jqka: {e}")

    return quote
