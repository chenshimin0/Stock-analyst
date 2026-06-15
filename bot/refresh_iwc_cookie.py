"""
Refresh the iwencai cookie by pasting a Cookie header from your browser.

Usage (on server):
    sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie

Steps:
  1. Open https://search.10jqka.com.cn/ in Chrome (no login needed)
  2. F12 → Network → any request → copy the `Cookie:` request header value
  3. Paste it below

The cookie is written in plaintext to bot/.iwc_cookie (mode 0o600).
"""
import os
import sys
import time
from pathlib import Path

_BOT_DIR = Path(__file__).parent
COOKIE_FILE = _BOT_DIR / ".iwc_cookie"


def main():
    print("=" * 60)
    print("iwencai Cookie 刷新工具")
    print("=" * 60)
    print()
    print("操作步骤:")
    print("  1. 浏览器打开 https://search.10jqka.com.cn/ (不用登录账号)")
    print("  2. F12 → Network → 任意点一个 request")
    print("  3. 复制请求头里的 Cookie: 完整 value")
    print("  4. 粘到下面 (单独一行)")
    print()
    print("提示: Cookie 通常含 'v=...' 字段 (hexin-v 反爬 token)。")
    print()

    try:
        import getpass
        raw = getpass.getpass("Cookie: ").strip()
    except EOFError:
        raw = sys.stdin.read().strip()

    if not raw:
        print("空输入，退出")
        return 1

    if "v=" not in raw:
        print("ERROR: cookie 缺少 'v=' 字段 (hexin-v token)")
        return 1

    COOKIE_FILE.write_text(raw + "\n", encoding="utf-8")
    os.chmod(COOKIE_FILE, 0o600)
    os.utime(COOKIE_FILE, (time.time(), time.time()))

    print()
    print(f"✓ Saved {len(raw)} chars to {COOKIE_FILE} (mode 0o600)")
    print()
    print("Test query:")
    print("  sudo backend/venv/bin/python3 -m bot.iwc_client")
    return 0


if __name__ == "__main__":
    sys.exit(main())
