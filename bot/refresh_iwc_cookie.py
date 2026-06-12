"""
Refresh the iwencai cookie file from a browser Cookie header.

Usage (on server):
    sudo backend/venv/bin/python3 -m bot.refresh_iwc_cookie

Then either:
  1. Paste a full Cookie header value (e.g. from Chrome DevTools)
  2. Or paste cookie name=value; name=value; ...

The cookie string is encrypted with the same Fernet key as
10jqka_cookies.enc and written back to disk.
"""
import getpass
import sys
import time
from pathlib import Path

_BOT_DIR = Path(__file__).parent
sys.path.insert(0, str(_BOT_DIR))

from crypto_utils import encrypt  # noqa: E402

ENCRYPT_PASSPHRASE = "wwFblXr9ZyaobfcjNoZhApJZZqUs52+3"
COOKIES_ENC = _BOT_DIR / "10jqka_cookies.enc"


def main():
    print("=" * 60)
    print("iwencai Cookie 刷新工具")
    print("=" * 60)
    print()
    print("操作步骤:")
    print("  1. 在浏览器打开 https://search.10jqka.com.cn/")
    print("  2. 登录你的同花顺账号")
    print("  3. 打开 DevTools (F12) → Network → 任一 request")
    print("  4. 找到 Cookie 请求头（或 hexin-v 响应头）")
    print("  5. 完整复制 Cookie 值粘贴到下面")
    print()
    print("示例格式 (一行):")
    print("  Hm_lvt_xxx=123; PHPSESSID=abc; userid=873448943; v=Ax-IZmUCifp...")
    print()

    raw = getpass.getpass("Cookie (输入隐藏): ").strip()
    if not raw:
        print("空输入，退出")
        return 1

    # If they pasted a full Cookie header value, it might be one big string
    # of "name=value; name=value". Normalize to "; " separator.
    cookie_str = raw.replace("\n", " ").strip()
    # Validate that we got at least the required keys
    must_have = ("v",)
    missing = [k for k in must_have if f"{k}=" not in cookie_str]
    if missing:
        print(f"ERROR: cookie missing required fields: {missing}")
        print("       需要 'v' 字段（hexin-v token）")
        return 1

    # Encrypt and write
    encrypted = encrypt(cookie_str, ENCRYPT_PASSPHRASE)
    COOKIES_ENC.write_text(encrypted)

    # Touch the file to current mtime (so freshness check passes)
    now = time.time()
    import os
    os.utime(COOKIES_ENC, (now, now))

    print()
    print(f"✓ Saved encrypted cookies to {COOKIES_ENC}")
    print(f"  Size: {len(cookie_str)} chars")
    print()
    print("Test query:")
    print("  sudo backend/venv/bin/python3 -m bot.iwc_client")
    return 0


if __name__ == "__main__":
    sys.exit(main())
