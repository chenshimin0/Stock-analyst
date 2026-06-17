"""
Mac-side iwencai token refresh script.

Uses Playwright to visit iwencai.com, extract the v= cookie, validate it
via in-browser API call (bypasses Nginx IP filtering), and push to server.

Run:
    python3 bot/refresh_token_mac.py

Cron (every 4 hours):
    0 */4 * * * cd ~/stock-analysis-system && python3 bot/refresh_token_mac.py >> /tmp/iwc_refresh.log 2>&1
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
TOKEN_FILE = ROOT / "bot" / ".iwc_token"
SERVER = "ubuntu@101.36.106.113"
SERVER_TOKEN_PATH = "/home/ubuntu/stock-analysis-system/bot/.iwc_token"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print("[{}] {}".format(now_str, msg), flush=True)


def get_and_validate_token():
    """Visit iwencai, get v= cookie, validate via in-browser fetch."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("ERROR: playwright not installed")
        return None

    log("Launching browser ...")
    with sync_playwright() as p:
        profile_dir = str(Path.home() / ".iwc_browser_profile")
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()
        log("Visiting iwencai.com ...")
        try:
            page.goto(
                "https://www.iwencai.com/",
                wait_until="domcontentloaded",
                timeout=20000,
            )
        except Exception as e:
            log("Page load error: {} — continuing anyway".format(e))
        page.wait_for_timeout(5000)

        # Extract v= cookie
        cookies = context.cookies()
        token = None
        for c in cookies:
            if c["name"] == "v" and "iwencai" in c.get("domain", ""):
                token = c["value"]
                break

        if not token:
            log("ERROR: no v= cookie found")
            context.close()
            return None

        log("Got token: {}...".format(token[:25]))

        # Validate by calling the API from inside the browser page
        # (Same origin → no Nginx IP block)
        log("Validating token via in-browser API call ...")
        try:
            result = page.evaluate("""
                async (q) => {
                    const fd = new URLSearchParams({
                        source: 'Ths_iwencai_Xuangu',
                        version: '2.0',
                        question: q,
                        perpage: '3',
                        page: '1',
                        secondary_intent: 'stock',
                        add_info: JSON.stringify({
                            urp: {scene: 1, company: 1, business: 1},
                            contentType: 'json',
                            searchInfo: true,
                        }),
                        log_info: JSON.stringify({input_type: 'typewrite'}),
                    });
                    const r = await fetch(
                        '/unifiedwap/unified-wap/v2/result/get-robot-data',
                        {
                            method: 'POST',
                            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                            body: fd.toString(),
                            credentials: 'include',
                        }
                    );
                    return await r.json();
                }
            """, "均线多头排列")
        except Exception as e:
            log("In-browser API call failed: {}".format(e))
            context.close()
            return None

        context.close()

    if result and result.get("status_code") == 0:
        log("Token validated OK")
        return token
    else:
        msg = result.get("status_msg", str(result)[:80]) if result else "no response"
        log("Token invalid: {}".format(msg))
        return None


def push_to_server():
    """scp the token file to the server."""
    result = subprocess.run(
        ["scp", str(TOKEN_FILE), "{}:{}".format(SERVER, SERVER_TOKEN_PATH)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        log("scp failed: {}".format(result.stderr.strip()))
        return False

    subprocess.run(
        ["ssh", SERVER,
         "chmod 600 {} && sudo chown ubuntu:ubuntu {}".format(
             SERVER_TOKEN_PATH, SERVER_TOKEN_PATH)],
        capture_output=True, timeout=15,
    )
    log("Token pushed to server")
    return True


def main():
    token = get_and_validate_token()
    if not token:
        return 1

    # Save locally
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)

    # Push to server
    push_to_server()

    log("Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
