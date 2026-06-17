"""
iwencai API client (V2) — uses hexin-v token for authentication.

Token management:
  - Primary: hexin-v token stored in .iwc_token file (logged-in user token)
  - Fallback: auto-generate token from Playwright browser (free-tier, limited)
  - Token refresh: user runs `python3 -m bot.iwc_client_v2 --refresh` to update

Usage:
  python3 -m bot.iwc_client_v2              # test query
  python3 -m bot.iwc_client_v2 --refresh    # update token from env var
  from iwc_client_v2 import query           # use in strategy_picker
"""
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_BOT_DIR = Path(__file__).parent
TOKEN_FILE = _BOT_DIR / ".iwc_token"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
IWENCAI_API = "https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------
class IwcLoginError(Exception):
    """Token expired or invalid — user needs to refresh."""


class IwcQueryError(Exception):
    """Query failed (HTTP error, parse error, etc.)."""


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _load_token() -> str | None:
    """Load hexin-v token from file."""
    if not TOKEN_FILE.exists():
        return None
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token and not token.startswith("#"):
            return token
    except Exception:
        pass
    return None


def save_token(token: str):
    """Save hexin-v token to file (mode 0o600)."""
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    logger.info(f"Token saved to {TOKEN_FILE} ({len(token)} chars)")


def refresh_token():
    """Refresh the hexin-v token from environment or stdin."""
    token = os.environ.get("IWENCAI_HEXIN_V", "").strip()
    if not token:
        import getpass
        token = getpass.getpass("Paste hexin-v token (from browser cookie 'v=' or header 'hexin-v:'): ").strip()
    if not token:
        print("ERROR: No token provided")
        return 1

    # Validate by making a test query
    print(f"Testing token (first 10 chars: {token[:10]}...)...")
    try:
        result = _call_api("均线多头排列", perpage=5, page=1, token=token)
        if result:
            stocks = _parse_response(result)
            print(f"  OK — got {len(stocks)} stocks back")
            save_token(token)
            return 0
        else:
            print("  FAIL — API returned empty response (token may be expired)")
            return 1
    except IwcLoginError as e:
        print(f"  FAIL — {e}")
        return 1
    except Exception as e:
        print(f"  FAIL — {e}")
        return 1


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _call_api(question: str, perpage: int = 50, page: int = 1,
              token: str | None = None) -> dict | None:
    """Make a raw API call to iwencai. Returns parsed JSON or raises."""
    if token is None:
        token = _load_token()
    if not token:
        raise IwcLoginError("No hexin-v token configured. Run `python3 -m bot.iwc_client_v2 --refresh`")

    params = urllib.parse.urlencode({
        "source": "Ths_iwencai_Xuangu",
        "version": "2.0",
        "query_area": "",
        "block_list": "",
        "add_info": json.dumps({
            "urp": {"scene": 1, "company": 1, "business": 1},
            "contentType": "json",
            "searchInfo": True,
        }, separators=(",", ":")),
        "question": question,
        "perpage": str(perpage),
        "page": str(page),
        "secondary_intent": "stock",
        "log_info": json.dumps({"input_type": "typewrite"}, separators=(",", ":")),
    }).encode("utf-8")

    req = urllib.request.Request(IWENCAI_API, data=params, headers={
        "hexin-v": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.iwencai.com/",
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
    })

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise IwcLoginError(f"HTTP 403 from iwencai — token expired or IP blocked")
        raise IwcQueryError(f"HTTP {e.code} from iwencai")
    except Exception as e:
        raise IwcQueryError(f"Network error: {e}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise IwcQueryError(f"Invalid JSON response: {raw[:200]}")

    status = data.get("status_code")
    if status != 0:
        msg = data.get("status_msg", "unknown error")
        if status == -10001:
            raise IwcLoginError(f"Token expired or invalid: {msg}")
        raise IwcQueryError(f"iwencai API error [{status}]: {msg}")

    return data


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(data: dict) -> list[dict]:
    """Parse iwencai API response into stock list."""
    stocks = []
    answer = data.get("data", data).get("answer", [{}])[0]
    text_ans = answer.get("text_answer", "")
    logger.info(f"iwencai: {text_ans}")

    for block in answer.get("txt", []):
        for comp in block.get("content", {}).get("components", []):
            if comp.get("show_type") != "xuangu_tableV1":
                continue
            columns = {c["key"]: c for c in comp["data"]["columns"]}
            for row in comp["data"].get("datas", []):
                stock = {}
                for key, col_info in columns.items():
                    val = row.get(key, {})
                    if isinstance(val, dict):
                        val = val.get("val", "")
                    stock[key] = val
                stocks.append(stock)

    return stocks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query(question: str, perpage: int = 50, page: int = 1) -> list[dict]:
    """Query iwencai screener. Returns list of stock dicts.

    Each stock dict has keys like: 股票代码, 股票简称, 最新价, 涨跌幅:前复权,
    总市值, 成交额, etc. (field names depend on the query).

    Raises:
        IwcLoginError — token expired or missing
        IwcQueryError — API/network error
    """
    data = _call_api(question, perpage=perpage, page=page)
    return _parse_response(data)


# ---------------------------------------------------------------------------
# Auto-refresh token via Playwright persistent browser
# ---------------------------------------------------------------------------

# Persistent browser profile directory — keeps cookies across restarts
_BROWSER_PROFILE = _BOT_DIR / ".iwc_browser_profile"


def validate_token(token: str) -> bool:
    """Check if a token works by making a minimal API call. Returns True if valid."""
    try:
        data = _call_api("均线多头排列", perpage=1, page=1, token=token)
        result = _parse_response(data)
        # Token works if API returns successfully (even with 0 results)
        return True
    except IwcLoginError:
        return False
    except Exception:
        return False


def _extract_v_cookie(cookies: list[dict]) -> str | None:
    """Extract v= cookie from a cookie list."""
    for c in cookies:
        if c["name"] == "v" and c.get("domain", "").endswith("iwencai.com"):
            return c["value"]
    return None


def auto_refresh_token() -> bool:
    """Use Playwright persistent browser to get a fresh hexin-v token.

    Maintains a persistent browser profile at .iwc_browser_profile/ so login
    cookies survive restarts. If no login state exists, falls back to the
    auto-generated free-tier token.

    Returns True if token was refreshed successfully.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not available for auto-refresh")
        return False

    try:
        with sync_playwright() as p:
            # Use persistent context — cookies/localStorage survive restarts
            _BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

            context = p.chromium.launch_persistent_context(
                str(_BROWSER_PROFILE),
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = context.new_page()
            page.goto("https://www.iwencai.com/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)  # let anti-bot JS set the v= cookie

            # Extract v= cookie
            token = _extract_v_cookie(context.cookies())
            if not token:
                logger.warning("Auto-refresh: no v= cookie found")
                context.close()
                return False

            # Check if this token is from a logged-in session
            body = page.inner_text("body")
            is_logged_in = "退出" in body or "我的" in body
            logger.info(f"Auto-refresh: got token {token[:10]}... (logged_in={is_logged_in})")

            context.close()

            # Validate the token
            if validate_token(token):
                save_token(token)
                logger.info("Auto-refresh: token saved successfully")
                return True
            else:
                logger.warning("Auto-refresh: token validation failed (may be free-tier)")
                # Still save it — better than nothing
                save_token(token)
                return False

    except Exception as e:
        logger.warning(f"Auto-refresh failed: {e}")
        return False


def ensure_token() -> str:
    """Get a working token: stored token first, then try auto-refresh."""
    token = _load_token()
    if token and validate_token(token):
        return token

    # Stored token expired — try auto-refresh
    logger.info("Stored token expired, trying auto-refresh...")
    if auto_refresh_token():
        token = _load_token()
        if token:
            return token

    # Last resort: try force-refresh from browser even without login
    token = _load_token()
    if token:
        return token

    raise IwcLoginError(
        "No valid hexin-v token. Run `python3 -m bot.iwc_client_v2 --refresh` "
        "or set IWENCAI_HEXIN_V environment variable."
    )


# =========================================================================
# CLI
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        sys.exit(refresh_token())

    token = _load_token()
    if not token:
        print("No token found. Run with --refresh first.")
        sys.exit(1)

    question = "均线多头排列;非st的股票;主板上市公司;大单3日净量持续流入;成交额>=1亿;总市值>=200亿;涨幅小于7%；"
    print(f"Query: {question}")
    print()

    try:
        rows = query(question, perpage=50)
        print(f"Got {len(rows)} stocks:")
        for r in rows[:20]:
            code = r.get("股票代码", "").split(".")[0]
            name = r.get("股票简称", "")
            price = r.get("最新价", "")
            change = r.get("涨跌幅:前复权", "")
            mcap = r.get("总市值", "")
            turnover = r.get("成交额", "")
            print(f"  {code}  {name:<8s}  价格={price}  涨跌={change}%  市值={mcap}  成交={turnover}")
    except (IwcLoginError, IwcQueryError) as e:
        print(f"Error: {e}")
        sys.exit(1)
