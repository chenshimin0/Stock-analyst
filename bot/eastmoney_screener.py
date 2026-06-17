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
# Stock universe via mootdx + Tencent batch quotes
# (push2 clist rc=102 — blocked/invalid, so we use mootdx for stock list
#  and Tencent qt.gtimg.cn for real-time filtering)
# ---------------------------------------------------------------------------

# Lazy cache for stock list (mootdx TCP call, ~2s)
_STOCK_LIST_CACHE = None


# Valid A-stock code prefixes
_A_STOCK_PREFIXES = (
    "600", "601", "603", "605",           # Shanghai main board
    "688", "689",                          # Shanghai STAR
    "000", "001", "002", "003", "004",    # Shenzhen main/sme
    "300", "301",                          # Shenzhen ChiNext
    "800", "830", "831", "832", "833",    # Beijing Stock Exchange
    "834", "835", "836", "837", "838",
    "839", "870", "871", "872", "873", "874",
    "875", "876", "877", "878", "879",
    "920",
)


def _get_all_stocks() -> list[dict]:
    """Get all A-stock codes + names via mootdx. Cached per process."""
    global _STOCK_LIST_CACHE
    if _STOCK_LIST_CACHE is not None:
        return _STOCK_LIST_CACHE
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        # stock_all() returns a DataFrame with all securities
        df = client.stock_all()
        stocks = []
        for _, row in df.iterrows():
            code = str(row["code"]).strip()
            name = str(row.get("name", "")).strip().replace("\x00", "")
            # Must be 6-digit code and match known A-stock prefixes
            if len(code) == 6 and code.isdigit() and code[:3] in _A_STOCK_PREFIXES and name:
                stocks.append({"code": code, "name": name})
        _STOCK_LIST_CACHE = stocks
        logger.info(f"mootdx: loaded {len(stocks)} A-stocks")
        return stocks
    except Exception as e:
        logger.warning(f"mootdx stock list failed: {e}")
        return []


def _filter_by_board(stocks: list[dict], conditions: dict) -> list[dict]:
    """Filter stocks by board type based on code prefix.

    主板: 600-605 (Shanghai), 000-004 (Shenzhen)
    创业板: 300-301
    科创板: 688-689
    """
    MAIN_SH = ("600", "601", "603", "605")
    MAIN_SZ = ("000", "001", "002", "003", "004")
    GEM = ("300", "301")
    STAR = ("688", "689")

    result = []
    for s in stocks:
        code = s["code"]
        if conditions.get("main_board"):
            if code.startswith(MAIN_SH) or code.startswith(MAIN_SZ):
                result.append(s)
        elif conditions.get("gem"):
            if code.startswith(GEM):
                result.append(s)
        elif conditions.get("star"):
            if code.startswith(STAR):
                result.append(s)
        else:
            result.append(s)
    return result


def _batch_tencent_quote(stocks: list[dict], batch_size: int = 80) -> dict[str, dict]:
    """Batch query Tencent API for real-time quotes.

    Returns dict: {code: {price, change_pct, turnover, market_cap, pe_ttm, ...}}
    """
    result = {}
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i + batch_size]
        prefixed = []
        for s in batch:
            code = s["code"]
            if code.startswith(("6", "9")):
                prefixed.append(f"sh{code}")
            elif code.startswith("8"):
                prefixed.append(f"bj{code}")
            else:
                prefixed.append(f"sz{code}")
        url = "http://qt.gtimg.cn/q=" + ",".join(prefixed)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read().decode("gbk", errors="replace")
        except Exception as e:
            logger.warning(f"Tencent batch query failed at offset {i}: {e}")
            continue

        for line in raw.strip().split(";"):
            if "=" not in line or '"' not in line:
                continue
            try:
                key = line.split("=")[0].split("_")[-1]
                vals = line.split('"')[1].split("~")
                code = key[2:]
                if len(vals) < 53:
                    continue
                result[code] = {
                    "name": vals[1],
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                    "turnover": float(vals[37]) * 10000 if vals[37] else 0,
                    "market_cap": float(vals[44]) * 1e8 if vals[44] else 0,
                    "pe_ttm": float(vals[39]) if vals[39] else 0,
                }
            except (IndexError, ValueError):
                continue
    return result


def _fetch_candidates(conditions: dict) -> list[dict]:
    """Fetch stock candidates using mootdx + Tencent (replaces push2 clist).

    Returns list of dicts with: code, name, price, change_pct, turnover,
    market_cap, pe_ttm.
    """
    # Step 1: Get stock universe
    all_stocks = _get_all_stocks()
    if not all_stocks:
        raise ScreenerQueryError("无法获取股票列表 (mootdx)")

    # Step 2: Filter by board
    filtered = _filter_by_board(all_stocks, conditions)
    logger.info(f"After board filter: {len(filtered)} stocks")

    if not filtered:
        return []

    # Step 3: Batch query Tencent for real-time data
    quotes = _batch_tencent_quote(filtered, batch_size=80)
    logger.info(f"Tencent returned quotes for {len(quotes)} stocks")

    # Step 4: Apply numeric filters (market cap, turnover, change)
    candidates = []
    for s in filtered:
        q = quotes.get(s["code"])
        if not q:
            continue
        # Market cap filter (in 亿)
        if conditions.get("market_cap_min"):
            if q["market_cap"] < conditions["market_cap_min"] * 1e8:
                continue
        # Turnover filter (in 亿)
        if conditions.get("turnover_min"):
            if q["turnover"] < conditions["turnover_min"] * 1e8:
                continue
        # Change % max
        if conditions.get("change_max") is not None:
            if q["change_pct"] >= conditions["change_max"]:
                continue
        # Change % min
        if conditions.get("change_min") is not None:
            if q["change_pct"] <= conditions["change_min"]:
                continue
        candidates.append({
            "code": s["code"],
            "name": s["name"],
            **q,
        })

    logger.info(f"After numeric filters: {len(candidates)} candidates")
    return candidates


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
            f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=80"
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

        # Check last N days: 主力净流入 (大单+超大单合计, index 1) must be > 0 for each day.
        # iwencai DDE aggregates large+super-large orders; push2his splits them.
        # Using 主力净流入 (combined) gives closer alignment.
        for line in klines[-days:]:
            p = line.split(",")
            if len(p) < 3:
                return False
            main_net = float(p[1]) if p[1] != "-" else 0
            if main_net <= 0:
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

    # --- Fetch candidates via mootdx + Tencent ---
    try:
        stocks = _fetch_candidates(conditions)
    except ScreenerQueryError:
        raise
    except Exception as e:
        raise ScreenerQueryError(f"选股查询失败: {e}")

    logger.info(f"Tencent screener returned {len(stocks)} candidates")

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
