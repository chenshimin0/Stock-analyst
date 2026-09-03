"""
问财选股（Playwright 浏览器版）——绕过 chameleon 反爬验证码。

背景：问财 2026-08-26 起对非浏览器请求（pywencai/requests/urllib/curl_cffi）
弹出「同花顺信息安全」验证码（chameleon 反爬 + captcha），返回 401 captcha_url。
本模块用 Playwright 真实浏览器打开问财首页，在页面 context 内 fetch 新接口，
复用 iwc_client_v2._parse_response 解析结果。

注意：所有 Playwright 操作都在独立的 worker 线程里执行（ThreadPoolExecutor），
因为 APScheduler 的 BlockingScheduler 在 asyncio 事件循环里运行 job，
而 Playwright 的 Sync API 不能在 asyncio loop 里使用（会报
"using Playwright Sync API inside the asyncio loop"）。

用法：
    from iwc_browser import query
    rows = query("均线多头排列;非st的股票;...", perpage=100)
    # rows: list[dict]，字段含 股票代码/股票简称/所属同花顺行业/经营范围/最新价 等
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from iwc_client_v2 import _parse_response, IwcQueryError

logger = logging.getLogger("iwc_browser")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

IWENCAI_HOME = "https://www.iwencai.com/"
IWENCAI_API = "https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"

# --- Playwright 会话（只在 _executor 的 worker 线程内访问，无需额外锁） ---
_pw = None
_browser = None
_context = None
_page = None
_last_used = 0.0
IDLE_TIMEOUT = 600.0  # 10 分钟空闲后关闭浏览器（预留，当前常驻复用）

# 单线程 executor：串行执行所有 Playwright 操作，隔离 APScheduler 的 asyncio loop。
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="iwc-pw")


def _ensure_page():
    """懒加载 Playwright 浏览器 + 打开问财首页。只能在 executor 线程内调用。"""
    global _pw, _browser, _context, _page, _last_used
    now = time.time()
    if _page is not None and not _page.is_closed():
        _last_used = now
        return _page
    from playwright.sync_api import sync_playwright
    logger.info("启动 Playwright 浏览器并打开问财首页…")
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox",
              "--disable-blink-features=AutomationControlled"],
    )
    _context = _browser.new_context(
        user_agent=UA, locale="zh-CN", viewport={"width": 1440, "height": 900},
    )
    _page = _context.new_page()
    _page.goto(IWENCAI_HOME, wait_until="domcontentloaded", timeout=40000)
    _page.wait_for_timeout(6000)  # 等 chameleon JS 建立验证状态
    _last_used = time.time()
    return _page


def _close():
    """关闭浏览器会话。只能在 executor 线程内调用。"""
    global _pw, _browser, _context, _page
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _pw = _browser = _context = _page = None


_FETCH_JS = f"""
async (body) => {{
    const r = await fetch('{IWENCAI_API}', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
        body: body,
    }});
    return {{status: r.status, text: await r.text()}};
}}
"""


def _do_fetch(body: str) -> dict:
    """在 executor 线程内执行浏览器 fetch。失败时关闭会话并抛出。"""
    try:
        pg = _ensure_page()
        return pg.evaluate(_FETCH_JS, body)
    except Exception:
        _close()
        raise


def query(question, perpage=100, page=1):
    """在浏览器 context 内 fetch 问财选股 API。返回 list[dict]。"""
    params = {
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
    }
    body = urlencode(params)

    try:
        res = _executor.submit(_do_fetch, body).result()
    except Exception as e:
        raise IwcQueryError(f"Playwright 查询失败: {e}")

    text = res.get("text", "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise IwcQueryError(f"iwencai 返回非 JSON: {text[:200]}")

    status = data.get("status_code")
    if status != 0:
        msg = data.get("status_msg") or "unknown"
        raise IwcQueryError(f"iwencai API error [{status}]: {msg}")

    return _parse_response(data)


def shutdown():
    """显式关闭浏览器和 executor（进程退出前调用）。"""
    try:
        _executor.submit(_close).result(timeout=15)
    except Exception:
        pass
    _executor.shutdown(wait=False)
