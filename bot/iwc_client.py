"""
iwencai (同花顺) query client.

Loads encrypted cookies from 10jqka_cookies.enc, sends the verified
POST to get-robot-data, parses the structured stock list out of the
xuangu_tableV1 component.

NOTE on auto-login:
    The 10jqka upass login flow uses chameleon.js (anti-bot SDK with
    fingerprinting + captcha). Pure server-side automated login is not
    feasible from this server IP. Cookie refresh is a manual step:
        sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie
    which prompts you to paste a fresh Cookie header from your browser
    (open https://search.10jqka.com.cn/ in Chrome, copy the Cookie
    request header from DevTools).
"""
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Allow `from iwc_client import ...` to work from any CWD
_BOT_DIR = Path(__file__).parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

from crypto_utils import decrypt  # noqa: E402

IWC_ENDPOINT = (
    "https://search.10jqka.com.cn/unifiedwap/unified-wap/v2/result/get-robot-data"
)
COOKIES_ENC = _BOT_DIR / "10jqka_cookies.enc"
ENCRYPT_PASSPHRASE = "wwFblXr9ZyaobfcjNoZhApJZZqUs52+3"
COOKIE_FRESH_TTL_SEC = 24 * 3600  # treat cookies fresh for 24h
SOURCE = "Ths_iwencai_Xuangu"
VERSION = "2.0"


class IwcLoginError(Exception):
    """Cookie file missing or invalid (cannot auto-login from server)."""


class IwcQueryError(Exception):
    """Query failed (HTTP error, parse error, or empty result)."""


def _load_cookies_from_disk() -> dict:
    """Decrypt 10jqka_cookies.enc and return cookie dict."""
    if not COOKIES_ENC.exists():
        raise IwcLoginError(
            f"Cookie file not found: {COOKIES_ENC}. "
            f"Run `python3 -m bot.refresh_iwc_cookie` first."
        )
    with open(COOKIES_ENC, "r") as f:
        encrypted = f.read().strip()
    try:
        cookie_str = decrypt(encrypted, ENCRYPT_PASSPHRASE)
    except Exception as e:
        raise IwcLoginError(f"Failed to decrypt cookies: {e}")
    cookies = {}
    for item in cookie_str.split("; "):
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k] = v
    return cookies


def _is_cookie_fresh() -> bool:
    """True if cookie file mtime is within COOKIE_FRESH_TTL_SEC."""
    if not COOKIES_ENC.exists():
        return False
    age = time.time() - COOKIES_ENC.stat().st_mtime
    return age < COOKIE_FRESH_TTL_SEC


def get_valid_cookies(refresh_if_stale: bool = True) -> dict:
    """Return cookies. Raises IwcLoginError if missing.

    If refresh_if_stale and cookies are older than TTL, raises IwcLoginError
    with a clear message — auto-refresh is not supported (see module docstring).
    """
    if not COOKIES_ENC.exists():
        raise IwcLoginError(
            "No cookies file. Run `sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie`"
        )
    if refresh_if_stale and not _is_cookie_fresh():
        age_h = (time.time() - COOKIES_ENC.stat().st_mtime) / 3600
        raise IwcLoginError(
            f"Cookies are {age_h:.1f}h old (TTL {COOKIE_FRESH_TTL_SEC/3600:.0f}h). "
            f"Run `sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie`"
        )
    return _load_cookies_from_disk()


def query(question: str, perpage: int = 50, page: int = 1) -> list[dict]:
    """Run an iwencai question and return the structured stock list.

    Returns list of dicts with at least: code, name. Other fields vary
    by query but commonly include: 最新价, 涨跌幅:前复权, 总市值, dde大单净量, etc.

    Raises IwcQueryError on HTTP / parse failure.
    Raises IwcLoginError on missing/expired cookies.
    """
    cookies = get_valid_cookies()
    # hexin-v header is a hexin gateway anti-bot token; it lives in cookies
    # under key 'v' — re-extract and use as the hexin-v header value.
    hexin_v = cookies.get("v")
    if not hexin_v:
        raise IwcLoginError("Cookie file missing 'v' field (hexin-v token)")

    add_info = {
        "urp": {"scene": 1, "company": 1, "business": 1},
        "contentType": "json",
        "searchInfo": True,
    }
    body = urllib.parse.urlencode([
        ("source", SOURCE),
        ("version", VERSION),
        ("query_area", ""),
        ("block_list", ""),
        ("add_info", json.dumps(add_info, ensure_ascii=False)),
        ("question", question),
        ("perpage", str(perpage)),
        ("page", str(page)),
        ("secondary_intent", "stock"),
        ("log_info", json.dumps({"input_type": "click"})),
        ("rsh", str(cookies.get("userid", "0"))),
    ]).encode("utf-8")

    req = urllib.request.Request(IWC_ENDPOINT, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/120.0.0.0 Safari/537.36")
    req.add_header("Referer", "https://search.10jqka.com.cn/")
    req.add_header("Origin", "https://search.10jqka.com.cn")
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
    # Cookie header (full cookie string)
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req.add_header("Cookie", cookie_str)
    # hexin-v header (the same value as cookie 'v', sent as separate header)
    req.add_header("hexin-v", hexin_v)

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read()
    except urllib.error.HTTPError as e:
        raise IwcQueryError(f"HTTP {e.code} from iwencai: {e.reason}") from e
    except Exception as e:
        raise IwcQueryError(f"iwencai request failed: {e}") from e

    try:
        data = json.loads(raw)
    except Exception as e:
        raise IwcQueryError(f"iwencai returned non-JSON: {raw[:200]}") from e

    if data.get("status_code") != 0:
        raise IwcQueryError(
            f"iwencai status_code={data.get('status_code')} msg={data.get('status_msg')}"
        )

    # Path: data.answer[0].txt[0].content.components[0].data.datas
    try:
        comps = data["data"]["answer"][0]["txt"][0]["content"]["components"]
    except (KeyError, IndexError, TypeError) as e:
        raise IwcQueryError(f"iwencai response structure unexpected: {e}") from e

    if not comps:
        raise IwcQueryError("iwencai returned 0 components (empty result)")

    # Find xuangu_tableV1 (the stock-list component)
    rows = []
    for c in comps:
        if c.get("show_type") == "xuangu_tableV1":
            rows = c.get("data", {}).get("datas", []) or []
            break

    if not rows:
        # 0 hits is a valid outcome (e.g. 选股条件太严), not an error
        logger.info(f"iwencai query returned 0 rows: {question[:60]}")
        return []

    # Normalize: add code/stock_code aliases, strip date suffixes
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        # iwencai uses 'code' as the bare 6-digit number
        code = r.get("code") or r.get("stock_code")
        if not code:
            continue
        # '最新价' is the latest close / realtime price
        out.append(r)
    return out


# =========================================================================
# Strategy-specific query (the "连续三日流入" strategy)
# =========================================================================
STRATEGY_NAME = "连续三日流入"
STRATEGY_QUERY = (
    "均线多头排列;非st的股票;主板上市公司;大单3日净量持续流入;"
    "成交额>=1亿;总市值>=200亿;涨幅小于10%"
)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Cookie fresh: {_is_cookie_fresh()}")
    print(f"Query: {STRATEGY_QUERY}")
    try:
        rows = query(STRATEGY_QUERY, perpage=50)
        print(f"Got {len(rows)} rows")
        for r in rows[:5]:
            print(f"  {r.get('code')} {r.get('最新价')} {r.get('涨跌幅:前复权')}")
    except (IwcLoginError, IwcQueryError) as e:
        print(f"Error: {e}")
