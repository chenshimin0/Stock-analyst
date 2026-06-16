"""
Stock screener using EastMoney push2 API — replaces iwencai dependency.

Uses the public push2.eastmoney.com API to screen A-stocks by:
- Board type (主板/创业板/科创板) — server-side
- Market cap, turnover, price change — server-side
- MA alignment (均线多头排列) — client-side via Tencent K-line
- Big-order net flow (大单N日净量持续流入) — client-side via push2his

Fully automatic — no cookies, no login, no browser.
"""
import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

_BOT_DIR = Path(__file__).parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

PUSH2_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ---------------------------------------------------------------------------
# Query pattern parsers
# ---------------------------------------------------------------------------
RE_MARKET_CAP_MIN = re.compile(r"总市值(?:大于|高于|>=|>|≥|=|＝)\s*(\d+)亿")
RE_TURNOVER_MIN   = re.compile(r"成交额(?:大于|高于|>=|>|≥|=|＝)\s*(\d+)亿")
RE_CHANGE_MAX     = re.compile(r"涨幅(?:小于|低于|不超过|<=|<|≤)\s*(\d+)%?")
RE_CHANGE_MIN     = re.compile(r"涨幅(?:大于|高于|不小于|>=|>|≥)\s*(\d+)%?")
RE_MA_BULL = re.compile(r"均线多头排列")
RE_BIG_ORDER_ND = re.compile(r"大单(\d+)日净量持续流入")
RE_MAIN_BOARD = re.compile(r"主板")
RE_GEM = re.compile(r"创业板")
RE_STAR = re.compile(r"科创板")
RE_NON_ST = re.compile(r"非[stST]+")

# push2 market/board codes
BOARD_MAIN = ["m:0+t+6", "m:0+t+7"]      # SH + SZ main board
BOARD_GEM  = ["m:0+t+8"]                  # 创业板
BOARD_STAR = ["m:1+t+23"]                 # 科创板
EXCLUDE_ST = ["b:ST", "m:0+t+13"]         # ST board exclusion

# Fields we pull from push2 clist
PUSH2_FIELDS = (
    "f2,f3,f6,f8,f12,f14,f15,f16,f17,f18,f20,f21,f115,f161,f162,f163,f164"
)

# ---------------------------------------------------------------------------
# Error types (mirror iwc_client interface)
# ---------------------------------------------------------------------------
class ScreenerQueryError(Exception):
    """Query failed (HTTP error, parse error, or empty result)."""


# ---------------------------------------------------------------------------
# Condition parser
# ---------------------------------------------------------------------------
def _parse_conditions(query: str) -> dict:
    """Parse a semicolon-separated Chinese query into structured conditions."""
    cond = {
        "market_cap_min": None,   # in 亿 (100M yuan)
        "turnover_min": None,     # in 亿
        "change_max": None,       # in %
        "change_min": None,       # in %
        "main_board": False,
        "gem": False,
        "star": False,
        "non_st": False,
        "ma_bull": False,
        "big_order_days": 0,      # N days of consecutive positive big-order net flow
    }

    m = RE_MARKET_CAP_MIN.search(query)
    if m:
        cond["market_cap_min"] = int(m.group(1))

    m = RE_TURNOVER_MIN.search(query)
    if m:
        cond["turnover_min"] = int(m.group(1))

    m = RE_CHANGE_MAX.search(query)
    if m:
        cond["change_max"] = int(m.group(1))

    m = RE_CHANGE_MIN.search(query)
    if m:
        cond["change_min"] = int(m.group(1))

    if RE_MA_BULL.search(query):
        cond["ma_bull"] = True

    m = RE_BIG_ORDER_ND.search(query)
    if m:
        cond["big_order_days"] = int(m.group(1))

    if RE_MAIN_BOARD.search(query):
        cond["main_board"] = True
    if RE_GEM.search(query):
        cond["gem"] = True
    if RE_STAR.search(query):
        cond["star"] = True
    if RE_NON_ST.search(query):
        cond["non_st"] = True

    return cond


# ---------------------------------------------------------------------------
# push2 clist — bulk stock screening
# ---------------------------------------------------------------------------
def _fetch_from_push2(fs_filters: list[str], perpage: int = 200) -> list[dict]:
    """Fetch stocks from EastMoney push2 clist API with given filters.

    Returns up to `perpage` stocks matching the filter criteria.
    """
    all_stocks = []
    page = 1
    max_pages = 3  # safety: never fetch more than 600 stocks total

    while page <= max_pages:
        params = {
            "pn": str(page),
            "pz": str(min(perpage, 200)),
            "po": "0",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": ",".join(fs_filters),
            "fields": PUSH2_FIELDS,
        }
        qs = urllib.parse.urlencode(params)
        url = f"{PUSH2_CLIST_URL}?{qs}"
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise ScreenerQueryError(f"push2 HTTP {e.code}: {e.reason}")
        except Exception as e:
            raise ScreenerQueryError(f"push2 request failed: {e}")

        result = data.get("data")
        if not result:
            break

        stocks = result.get("diff") or []
        if not stocks:
            break

        for s in stocks:
            all_stocks.append({
                "code": (s.get("f12") or "").strip(),
                "name": (s.get("f14") or "").strip(),
                "price": float(s.get("f2", 0) or 0),
                "change_pct": float(s.get("f3", 0) or 0),
                "turnover": float(s.get("f6", 0) or 0),
                "market_cap": float(s.get("f20", 0) or 0),
                "pe_ttm": float(s.get("f115", 0) or 0),
                "big_order_net": float(s.get("f161", 0) or 0),
                "super_large_net": float(s.get("f162", 0) or 0),
                "large_net": float(s.get("f163", 0) or 0),
            })

        total = result.get("total", 0)
        if page * 200 >= total or len(stocks) < 200:
            break
        page += 1

    return all_stocks


# ---------------------------------------------------------------------------
# Client-side checks (MA alignment + fund flow)
# ---------------------------------------------------------------------------

def _check_ma_bull(code: str) -> bool:
    """Check if stock has 均线多头排列 (MA5 > MA10 > MA20 > MA60).

    Uses Sina K-line API (HTTP, fast) with simple MA computation.
    """
    try:
        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        url = (
            f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=60&ma=no&datalen=80"
        )
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("utf-8", errors="replace")
        bars = json.loads(raw)
        if not isinstance(bars, list) or len(bars) < 60:
            return False

        closes = [float(b["close"]) for b in bars if b.get("close")]
        if len(closes) < 60:
            return False

        # Compute simple MAs
        def sma(data, n):
            return sum(data[-n:]) / n

        ma5  = sma(closes, 5)
        ma10 = sma(closes, 10)
        ma20 = sma(closes, 20)
        ma60 = sma(closes, 60)

        return ma5 > ma10 > ma20 > ma60
    except Exception as e:
        logger.debug(f"MA check failed for {code}: {e}")
        return False


def _check_big_order_flow(code: str, days: int = 3) -> bool:
    """Check if stock has N consecutive days of positive 大单净量 (big-order net flow).

    Uses push2his API (HTTP, fast).
    """
    try:
        secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?"
            f"lmt={days}&klt=1&secid={secid}&fields1=f1,f2,f3,f7&fields2="
            f"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
        )
        req = urllib.request.Request(url, headers={
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": UA,
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        klines = data.get("data", {}).get("klines", [])
        if not klines or len(klines) < days:
            return False

        # Check last N days: large_net (index 7) must be > 0 for each day
        for line in klines[-days:]:
            p = line.split(",")
            if len(p) < 8:
                return False
            large_net = float(p[7]) if p[7] != "-" else 0
            if large_net <= 0:
                return False
        return True
    except Exception as e:
        logger.debug(f"Fund flow check failed for {code}: {e}")
        return False


def _apply_client_filters(stocks: list[dict], conditions: dict,
                          max_workers: int = 10) -> list[dict]:
    """Apply MA and fund-flow checks concurrently. Returns filtered list."""
    if not stocks:
        return []

    need_ma = conditions.get("ma_bull", False)
    need_flow = conditions.get("big_order_days", 0)

    if not need_ma and not need_flow:
        return stocks

    flow_days = conditions["big_order_days"]
    results = []

    def check_one(s):
        code = s["code"]
        if need_ma and not _check_ma_bull(code):
            return None
        if need_flow > 0 and not _check_big_order_flow(code, flow_days):
            return None
        return s

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check_one, s): s for s in stocks}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if r is not None:
                    results.append(r)
            except Exception:
                pass

    # Restore original order (push2 already sorts by change% desc)
    seen = {s["code"] for s in results}
    return [s for s in stocks if s["code"] in seen]


# ---------------------------------------------------------------------------
# ST name filter (push2 doesn't always exclude ST perfectly)
# ---------------------------------------------------------------------------
def _is_st(stock: dict) -> bool:
    name = stock.get("name", "")
    code = stock.get("code", "")
    if "ST" in name or "*ST" in name:
        return True
    # Check code prefixes known to be ST/risk-warning
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query(question: str, perpage: int = 50, page: int = 1) -> list[dict]:
    """Screen A-stocks matching the Chinese query conditions.

    Args:
        question: Semicolon-separated Chinese conditions, e.g.
                  "均线多头排列;非st的股票;主板上市公司;大单3日净量持续流入;
                   成交额>=1亿;总市值>=200亿;涨幅小于10%"
        perpage: Max stocks to return.
        page: Page number (1-indexed).

    Returns:
        List of dicts with keys: code, name, price, change_pct, turnover,
        market_cap, pe_ttm.

    Raises ScreenerQueryError on failure.
    """
    conditions = _parse_conditions(question)
    logger.info(f"Parsed conditions: {conditions}")

    # --- Build push2 filter string ---
    fs_parts = []

    # Board selection
    if conditions["main_board"]:
        fs_parts.extend(BOARD_MAIN)
    if conditions["gem"]:
        fs_parts.extend(BOARD_GEM)
    if conditions["star"]:
        fs_parts.extend(BOARD_STAR)

    # Default: all A-stocks if no board specified
    if not fs_parts:
        fs_parts = ["m:0+t+6", "m:0+t+7", "m:0+t+8", "m:1+t+23"]

    # Market cap filter (push2 field f20 is in yuan, market_cap_min is in 亿)
    if conditions["market_cap_min"]:
        fs_parts.append(f"f20>{int(conditions['market_cap_min'] * 1e8)}")

    # Turnover filter (f6 is in yuan, turnover_min is in 亿)
    if conditions["turnover_min"]:
        fs_parts.append(f"f6>{int(conditions['turnover_min'] * 1e8)}")

    # Price change filter
    if conditions["change_max"] is not None:
        fs_parts.append(f"f3<{conditions['change_max']}")
    if conditions["change_min"] is not None:
        fs_parts.append(f"f3>{conditions['change_min']}")

    logger.info(f"push2 fs filter: {fs_parts}")

    # --- Fetch from push2 ---
    try:
        stocks = _fetch_from_push2(fs_parts, perpage=300)
    except ScreenerQueryError:
        raise
    except Exception as e:
        raise ScreenerQueryError(f"push2 query failed: {e}")

    logger.info(f"push2 returned {len(stocks)} candidates")

    if not stocks:
        return []

    # --- Post-filter: ST, MA, fund flow ---
    if conditions["non_st"]:
        stocks = [s for s in stocks if not _is_st(s)]
        logger.info(f"After ST filter: {len(stocks)}")

    # Apply expensive per-stock checks
    stocks = _apply_client_filters(stocks, conditions)
    logger.info(f"After client filters: {len(stocks)}")

    # Paginate
    start = (page - 1) * perpage
    end = start + perpage
    page_stocks = stocks[start:end]

    # Format result — match what strategy_picker expects:
    # At minimum: code, name. Optionally: 股票简称 for name extraction.
    result = []
    for s in page_stocks:
        result.append({
            "code": s["code"],
            "股票简称": s["name"],
            "name": s["name"],
            "最新价": s["price"],
            "涨跌幅:前复权": s["change_pct"],
            "总市值": s["market_cap"] / 1e8,
            "成交额": s["turnover"],
        })

    return result


# =========================================================================
# Default test query (matches the "连续三日流入" strategy)
# =========================================================================
STRATEGY_NAME = "连续三日流入"
STRATEGY_QUERY = (
    "均线多头排列;非st的股票;主板上市公司;大单3日净量持续流入;"
    "成交额>=1亿;总市值>=200亿;涨幅小于10%"
)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    print(f"Query: {STRATEGY_QUERY}")
    try:
        rows = query(STRATEGY_QUERY, perpage=50)
        print(f"Got {len(rows)} rows")
        for r in rows[:10]:
            print(f"  {r.get('code')} {r.get('股票简称')} "
                  f"价格={r.get('最新价')} 涨跌={r.get('涨跌幅:前复权')}%")
    except ScreenerQueryError as e:
        print(f"Error: {e}")
