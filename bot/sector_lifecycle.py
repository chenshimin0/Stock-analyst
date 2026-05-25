"""
Sector Lifecycle Analysis for Chinese A-Stocks.

Analyzes sector/板块 trends by using top constituent stocks as a proxy
for the sector index, then detecting the lifecycle phase to adjust stock scores.

Phases:
  主升期 (Main Uptrend)  +0.5    启动期 (Early Stage)    +0.3
  筑底期 (Bottom Build)   +0.2    盘整期 (Consolidation)   0.0
  高潮期 (Peak/Climax)    -0.3    衰退期 (Decline)        -0.5
"""

import gzip as _gzip
import json
import logging
import os
import time
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# curl_cffi needed for board-list APIs (TLS fingerprinting required)
try:
    from curl_cffi import requests as cffi_requests
    _CFFI_AVAILABLE = True
except ImportError:
    _CFFI_AVAILABLE = False

# ---- cache ----
_board_map_cache = None
_board_map_cache_time = 0
_CACHE_TTL = 3600  # 1 hour


# ============================================================
# K-line & indicator helpers (self-contained, same logic as telegram_bot)
# ============================================================

def _get_kline_sina(code: str, days: int = 90) -> list:
    """Fetch daily K-line from Sina Finance."""
    prefix = "sh" if code.startswith("6") else "sz"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={days}"
    )
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read()
        if raw[:2] == b'\x1f\x8b':
            import gzip as _gzip
            raw = _gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))
        if not data:
            return []
        return [
            {"date": d["day"], "open": float(d["open"]), "high": float(d["high"]),
             "low": float(d["low"]), "close": float(d["close"]), "volume": float(d["volume"])}
            for d in data
        ]
    except Exception as e:
        logger.warning(f"Sina K-line failed {code}: {e}")
        return []


def _calc_ma(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0
    return sum(closes[-period:]) / period


def _calc_macd(closes: list, fast=12, slow=26, signal=9) -> tuple:
    if len(closes) < slow + signal:
        return 0, 0, 0
    ema_fast = closes[0]
    ema_slow = closes[0]
    kf = 2 / (fast + 1)
    ks = 2 / (slow + 1)
    difs = []
    for p in closes:
        ema_fast = p * kf + ema_fast * (1 - kf)
        ema_slow = p * ks + ema_slow * (1 - ks)
        difs.append(ema_fast - ema_slow)
    dea = sum(difs[-signal:]) / signal
    kd = 2 / (signal + 1)
    for d in difs[-signal:]:
        dea = d * kd + dea * (1 - kd)
    dif = difs[-1]
    macd_bar = 2 * (dif - dea)
    return round(dif, 3), round(dea, 3), round(macd_bar, 3)


def _calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(d if d > 0 else 0)
        losses.append(abs(d) if d < 0 else 0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)


def _compute_indicators(kline: list) -> dict:
    """Compute technical indicators from K-line data."""
    if len(kline) < 26:
        return {}
    closes = [k["close"] for k in kline]
    highs = [k["high"] for k in kline]
    lows = [k["low"] for k in kline]
    volumes = [k["volume"] for k in kline]

    ma5 = _calc_ma(closes, 5)
    ma10 = _calc_ma(closes, 10)
    ma20 = _calc_ma(closes, 20)
    dif, dea, macd_bar = _calc_macd(closes)
    rsi = _calc_rsi(closes)
    latest = closes[-1]

    # volume ratio: 5-day avg vs 20-day avg
    vol5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
    vol20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
    vol_ratio = round(vol5 / vol20, 2) if vol20 > 0 else 0

    # price change over 10/20 days
    chg_10d = round((closes[-1] / closes[-10] - 1) * 100, 1) if len(closes) >= 10 else 0
    chg_20d = round((closes[-1] / closes[-20] - 1) * 100, 1) if len(closes) >= 20 else 0

    # deviation from MA20
    dev_ma20 = round((latest - ma20) / ma20 * 100, 1) if ma20 > 0 else 0

    return {
        "latest": latest, "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "dif": dif, "dea": dea, "macd_bar": macd_bar, "rsi": rsi,
        "vol_ratio": vol_ratio, "chg_10d": chg_10d, "chg_20d": chg_20d,
        "dev_ma20": dev_ma20,
    }


# ============================================================
# Sector detection
# ============================================================

def _get_stock_sector(code: str) -> Optional[str]:
    """Get the sector/industry name for a stock via East Money F10 API.

    Uses the CompanySurveyAjax endpoint which returns sshy (所属行业) field.
    Works from mainland China IPs where push2 API is blocked.
    """
    market = "SH" if code.startswith("6") else "SZ"
    url = (
        f"https://emweb.securities.eastmoney.com/"
        f"PC_HSF10/CompanySurvey/CompanySurveyAjax?code={market}{code}"
    )
    headers = {"Referer": "https://emweb.securities.eastmoney.com/"}

    # Try curl_cffi first (TLS impersonation)
    if _CFFI_AVAILABLE:
        try:
            resp = cffi_requests.get(url, headers=headers, impersonate="chrome120", timeout=10)
            if resp.status_code == 200:
                raw = resp.content
                if raw[:2] == b'\x1f\x8b':
                    raw = _gzip.decompress(raw)
                data = json.loads(raw)
                sector = data.get("jbzl", {}).get("sshy", "")
                if sector:
                    return sector
        except Exception:
            pass

    # Fallback to urllib
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read()
        if raw[:2] == b'\x1f\x8b':
            raw = _gzip.decompress(raw)
        data = json.loads(raw)
        sector = data.get("jbzl", {}).get("sshy", "")
        return sector if sector else None
    except Exception as e:
        logger.warning(f"get_stock_sector failed for {code}: {e}")
        return None


def _get_stock_concept_boards(code: str) -> list:
    """Get all concept boards for a stock from East Money CoreConception API.

    Returns list of {board_name, board_code, is_precise, board_rank}.
    Works from mainland China IPs (emweb domain, not push2).
    """
    market = "SH" if code.startswith("6") else "SZ"
    url = (
        f"https://emweb.securities.eastmoney.com/"
        f"PC_HSF10/CoreConception/PageAjax?code={market}{code}"
    )
    headers = {"Referer": "https://emweb.securities.eastmoney.com/"}

    try:
        if _CFFI_AVAILABLE:
            try:
                resp = cffi_requests.get(url, headers=headers, impersonate="chrome120", timeout=10)
                if resp.status_code == 200:
                    raw = resp.content
                    if raw[:2] == b'\x1f\x8b':
                        raw = _gzip.decompress(raw)
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
            except Exception:
                pass

        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read()
        if raw[:2] == b'\x1f\x8b':
            raw = _gzip.decompress(raw)
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
        logger.warning(f"get_stock_concept_boards failed for {code}: {e}")
        return []


# ---- dynamic board cache (grows organically as stocks are analyzed) ----
_board_dynamic_cache = None
_board_cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "board_cache.json")


def _load_board_cache() -> dict:
    """Load the growing dynamic board cache from disk."""
    global _board_dynamic_cache
    if _board_dynamic_cache is not None:
        return _board_dynamic_cache
    try:
        if os.path.exists(_board_cache_file):
            with open(_board_cache_file, "r") as f:
                _board_dynamic_cache = json.load(f)
            logger.info(f"Board cache loaded: {len(_board_dynamic_cache)} boards")
        else:
            _board_dynamic_cache = {}
    except Exception as e:
        logger.warning(f"Failed to load board cache: {e}")
        _board_dynamic_cache = {}
    return _board_dynamic_cache


def _save_board_cache():
    """Persist the dynamic board cache to disk."""
    global _board_dynamic_cache
    try:
        with open(_board_cache_file, "w") as f:
            json.dump(_board_dynamic_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save board cache: {e}")


def _update_board_cache_from_stock(code: str) -> dict:
    """Fetch a stock's concept boards and add the stock to each board's cache.

    Returns the updated cache dict.
    """
    cache = _load_board_cache()
    concepts = _get_stock_concept_boards(code)
    if not concepts:
        return cache

    updated = False
    for c in concepts:
        name = c["board_name"]
        bk = c["board_code"]
        if not name or not bk:
            continue
        if name not in cache:
            cache[name] = {"bk_code": bk, "constituents": []}
        entry = cache[name]
        if "bk_code" not in entry or not entry["bk_code"]:
            entry["bk_code"] = bk
        if code not in entry.setdefault("constituents", []):
            entry["constituents"].append(code)
            updated = True

    if updated:
        _save_board_cache()
        logger.info(f"Board cache updated from {code}: {len(concepts)} concepts")

    return cache


def _load_sector_map() -> dict:
    """Load sector mapping from static JSON file (primary) or live API (fallback)."""
    global _board_map_cache, _board_map_cache_time

    now = time.time()
    if _board_map_cache is not None and (now - _board_map_cache_time) < _CACHE_TTL:
        return _board_map_cache

    # 1. Try static JSON file (deployed with server, no API dependency)
    map_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_map.json")
    try:
        if os.path.exists(map_file):
            with open(map_file, "r") as f:
                data = json.load(f)
            mapping = {
                "stock_map": data.get("stock_sectors", {}),
                "sectors": data.get("sectors", {}),
            }
            _board_map_cache = mapping
            _board_map_cache_time = now
            logger.info(f"Sector map loaded from file: {len(mapping['sectors'])} sectors")
            return mapping
    except Exception as e:
        logger.warning(f"Failed to load sector_map.json: {e}")

    # 2. Fallback: live API (push2, may be blocked)
    mapping = _fetch_board_map_live()
    if mapping:
        _board_map_cache = mapping
        _board_map_cache_time = now
    return _board_map_cache or {"stock_map": {}, "sectors": {}}


def _fetch_board_map_live() -> Optional[dict]:
    """Fallback: fetch board mapping from push2 API (may not work from mainland CN)."""
    if not _CFFI_AVAILABLE:
        return None

    try:
        resp = cffi_requests.get(
            "https://push2.eastmoney.com/api/qt/clist/get?"
            "fs=m:90&fid=f3&pn=1&pz=5000&fields=f12,f14",
            headers={"Referer": "https://quote.eastmoney.com/"},
            impersonate="chrome120",
            timeout=15,
        )
        d = json.loads(resp.text)
        if d.get("rc") != 0:
            return None

        diff = d.get("data", {}).get("diff", {})
        boards = {}
        for item in diff.values():
            name = item.get("f14", "")
            code = item.get("f12", "")
            if name and code:
                boards[name] = code
        return {"stock_map": {}, "sectors": {}, "_boards": boards}
    except Exception as e:
        logger.warning(f"Live board map fetch failed: {e}")
        return None


def _sector_name_variants(name: str) -> list:
    """Generate search variants for a sector name to enable fuzzy matching.

    "芯片概念" → ["芯片概念", "芯片"] (strips common suffixes)
    "汽车芯片" → ["汽车芯片"]
    """
    variants = [name]
    import re
    # Strip common East Money board suffixes
    base = re.sub(r"(概念|板块|产业|行业|题材)$", "", name).strip()
    if base and base != name:
        variants.append(base)
    return variants


def _fuzzy_find_in_dict(name: str, candidates: dict) -> Optional[str]:
    """Find a matching entry in a {name: info_dict} collection.

    Tries: exact match → substring match → keyword match → suffix-stripped match.
    Returns the matched name, or None.
    """
    # 1. Exact match
    if name in candidates:
        return name

    import re
    base = re.sub(r"[Ⅰ-ⅫⅠ-Ⅻ]+$", "", name).strip()

    # 2. Substring match: "芯片概念" is in "芯片概念Ⅱ" or vice versa
    for cname in candidates:
        if base and (base in cname or cname in base):
            return cname

    # 3. Keyword match: "芯片概念" → "芯片" matches "汽车芯片", "国产芯片"
    # Extract core keywords (2+ char chunks without common suffixes)
    suffixes = ["概念", "板块", "产业", "行业", "题材"]
    keywords = base
    for sfx in suffixes:
        if keywords.endswith(sfx):
            keywords = keywords[:-len(sfx)].strip()
    if keywords and len(keywords) >= 2 and keywords != base:
        for cname in candidates:
            if keywords in cname:
                return cname

    return None


def _find_board_code(sector_name: str, hint_code: str = "") -> Optional[str]:
    """Match a sector name to its BK board code.

    Checks: static map → dynamic cache → CoreConception via hint_code.
    """
    smap = _load_sector_map()
    sectors = smap.get("sectors", {})

    # 1. Static map
    match = _fuzzy_find_in_dict(sector_name, sectors)
    if match:
        return sectors[match].get("bk_code")

    # 2. Dynamic board cache
    cache = _load_board_cache()
    match = _fuzzy_find_in_dict(sector_name, cache)
    if match:
        return cache[match].get("bk_code")

    # 3. Try live board list
    boards = smap.get("_boards", {})
    if not boards:
        live = _fetch_board_map_live()
        if live:
            boards = live.get("_boards", {})
    match = _fuzzy_find_in_dict(sector_name, boards)
    if match:
        return boards[match]

    # 4. Try CoreConception with hint stock to discover board
    if hint_code:
        concepts = _get_stock_concept_boards(hint_code)
        concept_map = {c["board_name"]: c for c in concepts}
        match = _fuzzy_find_in_dict(sector_name, concept_map)
        if match:
            bk = concept_map[match]["board_code"]
            if bk:
                _update_board_cache_from_stock(hint_code)
                return bk

    return None


def _get_board_constituents(sector_name: str, top_n: int = 8, hint_code: str = "") -> list:
    """Get top N constituent stocks for a sector.

    Checks: static map → dynamic cache → CoreConception fallback.
    """
    smap = _load_sector_map()
    sectors = smap.get("sectors", {})

    # 1. Static map (exact + fuzzy)
    match = _fuzzy_find_in_dict(sector_name, sectors)
    if match:
        cons = sectors[match].get("constituents", [])
        if cons:
            return cons[:top_n]

    # 2. Dynamic board cache
    cache = _load_board_cache()
    match = _fuzzy_find_in_dict(sector_name, cache)
    if match:
        cons = cache[match].get("constituents", [])
        if cons:
            return cons[:top_n]

    # 3. Try to seed cache from hint stock
    if hint_code:
        _update_board_cache_from_stock(hint_code)
        cache = _load_board_cache()
        match = _fuzzy_find_in_dict(sector_name, cache)
        if match:
            cons = cache[match].get("constituents", [])
            if cons:
                return cons[:top_n]

    # 4. Live API fallback
    bk_code = _find_board_code(sector_name, hint_code)
    if bk_code and _CFFI_AVAILABLE:
        try:
            resp = cffi_requests.get(
                f"https://push2.eastmoney.com/api/qt/clist/get?"
                f"fs=b:{bk_code}&fid=f20&po=1&pn=1&pz={top_n}&fields=f12,f14",
                headers={"Referer": "https://quote.eastmoney.com/"},
                impersonate="chrome120",
                timeout=10,
            )
            d = json.loads(resp.text)
            diff = d.get("data", {}).get("diff", {})
            return [item["f12"] for item in diff.values() if item.get("f12")]
        except Exception as e:
            logger.warning(f"Live constituents failed for {bk_code}: {e}")

    return []


# ============================================================
# Lifecycle detection
# ============================================================

def _compute_composite(stock_codes: list) -> Optional[dict]:
    """Compute composite sector indicators from top constituent stocks.

    Fetches K-lines for each stock, computes individual indicators,
    then averages them to produce a sector-level picture.
    """
    if not stock_codes:
        return None

    all_inds = []
    for i, code in enumerate(stock_codes):
        if i > 0:
            time.sleep(1.5)  # avoid Sina rate limit (456)
        kline = _get_kline_sina(code, 90)
        if not kline or len(kline) < 26:
            continue
        ind = _compute_indicators(kline)
        if ind:
            all_inds.append(ind)

    if len(all_inds) < 1:
        return None

    n = len(all_inds)
    composite = {
        "stocks_analyzed": n,
        "total_stocks": len(stock_codes),
        # averages
        "avg_rsi": round(sum(i["rsi"] for i in all_inds) / n, 1),
        "avg_vol_ratio": round(sum(i["vol_ratio"] for i in all_inds) / n, 2),
        "avg_chg_10d": round(sum(i["chg_10d"] for i in all_inds) / n, 1),
        "avg_chg_20d": round(sum(i["chg_20d"] for i in all_inds) / n, 1),
        "avg_dev_ma20": round(sum(i["dev_ma20"] for i in all_inds) / n, 1),
        # MA alignment: % of stocks with MA5 > MA10 > MA20
        "pct_ma_bull": round(sum(1 for i in all_inds if i["ma5"] > i["ma10"] > i["ma20"]) / n * 100, 1),
        "pct_ma_bear": round(sum(1 for i in all_inds if i["ma5"] < i["ma10"] < i["ma20"]) / n * 100, 1),
        # MACD: % with positive histogram
        "pct_macd_pos": round(sum(1 for i in all_inds if i["macd_bar"] > 0) / n * 100, 1),
        # MACD expanding: DIF rising (compare DIF to 5 days ago — use positive macd_bar as proxy for expansion)
        "pct_macd_strong": round(sum(1 for i in all_inds if i["macd_bar"] > 0 and i["dif"] > 0) / n * 100, 1),
        # Price above MA20
        "pct_above_ma20": round(sum(1 for i in all_inds if i["latest"] > i["ma20"]) / n * 100, 1),
        # Stocks with positive 20d change
        "pct_positive_20d": round(sum(1 for i in all_inds if i["chg_20d"] > 0) / n * 100, 1),
    }

    # Calculate trend strength (avg daily return over period)
    composite["trend_strength"] = round(composite["avg_chg_20d"], 1)

    return composite


def _detect_phase(comp: dict) -> dict:
    """Detect lifecycle phase from composite indicators."""
    pct_ma_bull = comp["pct_ma_bull"]
    pct_ma_bear = comp["pct_ma_bear"]
    pct_macd_pos = comp["pct_macd_pos"]
    pct_macd_strong = comp["pct_macd_strong"]
    avg_rsi = comp["avg_rsi"]
    avg_vol = comp["avg_vol_ratio"]
    avg_chg_10d = comp["avg_chg_10d"]
    avg_chg_20d = comp["avg_chg_20d"]
    avg_dev = comp["avg_dev_ma20"]
    pct_above_ma20 = comp["pct_above_ma20"]

    signals = []
    phase = "consolidation"
    phase_cn = "盘整期"
    bonus = 0.0

    # 衰退期 (Decline): MA bearish alignment dominant, MACD negative, 20d drop > 5%
    if pct_ma_bear >= 60 and avg_chg_20d < -5:
        phase = "decline"
        phase_cn = "衰退期"
        bonus = -0.5
        signals.append("均线空头排列占主导")
        signals.append(f"板块20日跌幅 {avg_chg_20d:.1f}%")
        if pct_macd_pos < 30:
            signals.append("MACD普遍走弱")

    # 高潮期 (Peak): RSI overbought OR price far above MA20, MACD narrowing
    elif (avg_rsi > 75 or avg_dev > 20) and pct_macd_strong < 50:
        phase = "peak"
        phase_cn = "高潮期"
        bonus = -0.3
        if avg_rsi > 75:
            signals.append(f"RSI {avg_rsi:.1f} 高位超买")
        if avg_dev > 20:
            signals.append(f"偏离MA20 {avg_dev:.1f}% 过大")
        signals.append("MACD动能衰减")

    # 主升期 (Main Uptrend): MA bull alignment, MACD positive & strong, good volume, rising
    elif pct_ma_bull >= 60 and pct_macd_strong >= 60 and avg_vol > 0.9 and avg_chg_10d > 2:
        phase = "main_uptrend"
        phase_cn = "主升期"
        bonus = 0.5
        signals.append("均线多头排列")
        signals.append("MACD持续上行")
        if avg_vol > 1.2:
            signals.append("量能配合良好")
        signals.append(f"板块10日涨幅 {avg_chg_10d:+.1f}%")

    # 启动期 (Early Stage): price crossed above MA20, MACD turning positive, moderate volume
    elif pct_above_ma20 >= 50 and pct_macd_pos >= 50 and avg_chg_10d > 0 and avg_rsi < 65:
        phase = "early_stage"
        phase_cn = "启动期"
        bonus = 0.3
        if pct_above_ma20 >= 60:
            signals.append("多数成分股站上MA20")
        if pct_macd_pos >= 50:
            signals.append("MACD转正")
        signals.append(f"板块10日涨幅 {avg_chg_10d:+.1f}%")

    # 筑底期 (Bottom Building): price near MA20, RSI 30-50, flat/slightly positive
    elif abs(avg_dev) < 4 and 30 <= avg_rsi <= 50 and avg_chg_20d > -5:
        phase = "bottom_build"
        phase_cn = "筑底期"
        bonus = 0.2
        signals.append(f"价格贴近MA20 (±{abs(avg_dev):.1f}%)")
        signals.append(f"RSI {avg_rsi:.1f} 中性偏低")
        if avg_vol < 0.8:
            signals.append("缩量筑底")

    # Default: 盘整期 (Consolidation)
    else:
        phase = "consolidation"
        phase_cn = "盘整期"
        bonus = 0.0
        if pct_ma_bull > pct_ma_bear:
            signals.append("多数均线偏多排列")
        elif pct_ma_bear > pct_ma_bull:
            signals.append("多数均线偏空排列")
        signals.append(f"板块10日涨跌 {avg_chg_10d:+.1f}%")
        signals.append("无明确方向信号")

    return {
        "phase": phase,
        "phase_cn": phase_cn,
        "bonus": bonus,
        "signals": signals,
        "trend_strength": comp["trend_strength"],
    }


# ============================================================
# Direct sector analysis (by name, bypassing stock→sector detection)
# ============================================================

def analyze_sector_by_name(sector_name: str, code: str = "") -> Optional[dict]:
    """Analyze a named sector directly — used when sector is known (e.g. from AI tags).

    If code is provided, uses it to dynamically discover the board via CoreConception
    and seed the growing cache. This allows the system to handle any AI tag without
    needing manual mapping entries.

    Returns None if analysis can't be performed (non-blocking).
    Returns dict with: phase, phase_cn, bonus, signals, sector_name, trend_strength
    """
    try:
        # 0. Seed dynamic cache from this stock (grows organically over time)
        if code:
            _update_board_cache_from_stock(code)

        # 1. Find board code (with hint code for CoreConception fallback)
        bk_code = _find_board_code(sector_name, code)
        if not bk_code:
            logger.info(f"No board code match for sector '{sector_name}'")
            return None

        # 2. Get top constituents (with hint code for cache seeding)
        constituents = _get_board_constituents(sector_name, top_n=8, hint_code=code)
        if not constituents:
            logger.info(f"No constituents found for sector '{sector_name}'")
            return None

        # 3. Compute composite indicators (allow single-stock for dynamic boards)
        comp = _compute_composite(constituents)
        if not comp:
            logger.info(f"Insufficient data to compute composite for {bk_code}")
            return None

        # 4. Detect phase
        result = _detect_phase(comp)
        result["sector_name"] = sector_name
        result["bk_code"] = bk_code
        result["constituents_count"] = comp["stocks_analyzed"]

        logger.info(
            f"Sector lifecycle for '{sector_name}' ({bk_code}): "
            f"{result['phase_cn']} bonus={result['bonus']:+.1f} "
            f"({comp['stocks_analyzed']} stocks)"
        )
        return result

    except Exception as e:
        logger.warning(f"analyze_sector_by_name failed for '{sector_name}': {e}")
        return None


# ============================================================
# Main entry point
# ============================================================

def analyze_sector_lifecycle(code: str) -> Optional[dict]:
    """Analyze sector lifecycle for a stock and return phase + score bonus.

    Returns None if analysis can't be performed (non-blocking).
    Returns dict with: phase, phase_cn, bonus, signals, sector_name, trend_strength
    """
    try:
        # 1. Get sector name — check static stock→sector mapping first, then F10 API
        smap = _load_sector_map()
        stock_map = smap.get("stock_map", {})
        raw_sector = stock_map.get(code)
        if isinstance(raw_sector, list):
            sector_name = raw_sector[0] if raw_sector else None
        else:
            sector_name = raw_sector
        if sector_name:
            logger.info(f"Using mapped sector for {code}: {sector_name}")
        else:
            sector_name = _get_stock_sector(code)
        if not sector_name:
            logger.info(f"No sector found for {code}")
            return None

        # 2-4. Delegate to shared analysis function
        return analyze_sector_by_name(sector_name, code)

    except Exception as e:
        logger.warning(f"Sector lifecycle analysis failed for {code}: {e}")
        return None
