"""
iwencai (同花顺) query client.

Sends a POST to `get-robot-data` and parses the structured stock list
out of the xuangu_tableV1 component.

Cookie handling
---------------
iwencai queries do NOT require an account login. A fresh browser visit
to https://search.10jqka.com.cn/ produces a `v=...` cookie (the
hexin-v anti-bot token) that grants ~1-2h of query access. To refresh:

    sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie

That writes the pasted Cookie header (plaintext) to `bot/.iwc_cookie`.

The cookie is intentionally NOT encrypted — iwc cookies are not
credentials, they're a per-session anti-bot token. The 0o600 file
permission is enough.
"""
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_BOT_DIR = Path(__file__).parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

IWC_ENDPOINT = (
    "https://search.10jqka.com.cn/unifiedwap/unified-wap/v2/result/get-robot-data"
)
COOKIE_FILE = _BOT_DIR / ".iwc_cookie"
COOKIE_FRESH_TTL_SEC = 6 * 3600  # 6h: iwc cookies get rate-limited well before 24h
SOURCE = "Ths_iwencai_Xuangu"
VERSION = "2.0"


class IwcLoginError(Exception):
    """Cookie file missing or unreadable."""


class IwcQueryError(Exception):
    """Query failed (HTTP error, parse error, or empty result)."""


def _load_cookie_header() -> str:
    """Read the raw Cookie header value from COOKIE_FILE.

    The file should contain the full `Cookie:` request header value
    (e.g. 'chat_bot_session_id=...; v=A8V6E1xa...'). Multiple lines
    are concatenated.
    """
    if not COOKIE_FILE.exists():
        raise IwcLoginError(
            f"Cookie file not found: {COOKIE_FILE}\n"
            f"Run `sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie` "
            f"and paste a Cookie header from your browser."
        )
    raw = COOKIE_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        raise IwcLoginError(
            f"Cookie file is empty: {COOKIE_FILE}\n"
            f"Run `sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie`."
        )
    return raw.replace("\n", " ").strip()


def _is_cookie_fresh() -> bool:
    if not COOKIE_FILE.exists():
        return False
    age = time.time() - COOKIE_FILE.stat().st_mtime
    return age < COOKIE_FRESH_TTL_SEC


def get_valid_cookies(refresh_if_stale: bool = True) -> str:
    """Return the raw Cookie header value. Raises IwcLoginError if missing.

    If refresh_if_stale and cookies are older than TTL, raises IwcLoginError
    with a clear message.
    """
    if not COOKIE_FILE.exists():
        raise IwcLoginError(
            "No cookie file. Run `sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie`"
        )
    if refresh_if_stale and not _is_cookie_fresh():
        age_h = (time.time() - COOKIE_FILE.stat().st_mtime) / 3600
        raise IwcLoginError(
            f"Cookie is {age_h:.1f}h old (TTL {COOKIE_FRESH_TTL_SEC/3600:.0f}h). "
            f"Run `sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie`"
        )
    return _load_cookie_header()


def _cookie_dict(cookie_str: str) -> dict:
    """Parse a Cookie header value into a dict (for extracting `v`)."""
    out = {}
    for item in cookie_str.split("; "):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k] = v.strip()
    return out


def query(question: str, perpage: int = 50, page: int = 1) -> list[dict]:
    """Run an iwencai question and return the structured stock list.

    Returns list of dicts with at least: code, 股票简称. Other fields vary
    by query but commonly include: 最新价, 涨跌幅:前复权, 总市值, dde大单净量, etc.

    Raises IwcQueryError on HTTP / parse failure.
    Raises IwcLoginError on missing/expired cookies.
    """
    cookie_str = get_valid_cookies()
    cookies = _cookie_dict(cookie_str)
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
    req.add_header("Cookie", cookie_str)
    req.add_header("hexin-v", hexin_v)

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read()
    except urllib.error.HTTPError as e:
        # Refresh the cookie hint when the gateway rejects us
        if e.code in (401, 403):
            raise IwcQueryError(
                f"HTTP {e.code} from iwencai (cookie may be expired/rate-limited). "
                f"Run `python3 -m bot.refresh_iwc_cookie`."
            ) from e
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
        logger.info(f"iwc query returned 0 rows: {question[:60]}")
        return []

    return [r for r in rows if isinstance(r, dict) and r.get("code")]


# =========================================================================
# Default test query (the "连续三日流入" strategy)
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
            print(f"  {r.get('code')} {r.get('股票简称')} {r.get('最新价')}")
    except (IwcLoginError, IwcQueryError) as e:
        print(f"Error: {e}")
