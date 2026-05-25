"""
China Stock Analyst Telegram Bot (v2 — thin client)
=====================================================
Receives stock codes → validates → queues for Claude Code skill processing.
Data fetching delegated to a-stock-data skill, analysis to china-stock-analyst.

Run: python telegram_bot.py
"""
import asyncio
import io
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Data layer — uses a-stock-data skill APIs
from astock_data import get_quote

# AI analysis (DeepSeek)
try:
    from ai_analyzer import analyze_stock
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

# AKShare for code validation
try:
    import akshare as ak
    _AK_AVAILABLE = True
except ImportError:
    _AK_AVAILABLE = False

# EasyOCR (lazy init)
_OCR_READER = None


def _get_ocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr
        _OCR_READER = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        logger.info("OCR engine initialized")
    return _OCR_READER


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("stock_bot")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
STOCK_CODE_RE = re.compile(r"\b[0368]\d{5}\b")
COMPARE_KW_RE = re.compile(r"(对比|比较|vs|pk|哪个好|选哪|推荐)", re.IGNORECASE)
TOP_N_RE = re.compile(
    r"(?:选出|推荐|最好的?|最优的?|挑|只要)\s*(\d+|前\s*\d+|一两|二三|三四|四五)\s*(?:只|个|支)",
    re.IGNORECASE,
)
CN_NUM_MAP = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_RECENT_CODES: dict = {}  # {chat_id: (timestamp, set_of_codes)}

WEB_API_URL = os.getenv("WEB_API_URL", "http://localhost:8000/api")
QUEUE_DIR = os.getenv("QUEUE_DIR", "/Users/shiminchen/stock-analysis-system/backend/queue")

# Stock name → code map
NAME_TO_CODE = {
    "茅台": "600519", "贵州茅台": "600519",
    "宁德": "300750", "宁德时代": "300750",
    "比亚迪": "002594",
    "五粮液": "000858",
    "杰克": "603337", "杰克科技": "603337",
    "贵州燃气": "600903",
    "新疆众和": "600888",
    "微光": "002801", "微光股份": "002801",
    "九牧王": "601566",
    "艾华": "603989", "艾华集团": "603989",
    "雅运": "603790", "雅运股份": "603790",
    "金徽酒": "603919",
}

# Market spot cache
_SPOT_CACHE = None
_SPOT_CACHE_TTL = 10


def _get_spot_df():
    global _SPOT_CACHE
    now = time.time()
    if _SPOT_CACHE and (now - _SPOT_CACHE[0]) < _SPOT_CACHE_TTL:
        return _SPOT_CACHE[1]
    if not _AK_AVAILABLE:
        return None
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                _SPOT_CACHE = (now, df)
                return df
        except Exception as e:
            logger.warning(f"Spot fetch failed (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(1)
    return None


# ============================================================
# Queue
# ============================================================

def _make_slug_safe(name: str) -> str:
    try:
        from pypinyin import pinyin, Style
        initials = pinyin(name, style=Style.FIRST_LETTER)
        return "".join([i[0].upper() for i in initials])
    except ImportError:
        return name.replace(" ", "")


def _save_pending_to_web(code: str, name: str, price: float):
    """Create a pending placeholder report in the web backend."""
    try:
        payload = {
            "stock_code": code,
            "stock_name": name,
            "report_date": str(date.today()),
            "price_at_report": price,
            "momentum_score": 0,
            "revenue_score": 0,
            "risk_score": 0,
            "total_score": 0,
            "label": "分析中...",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{WEB_API_URL}/reports", data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"Pending report created: {code} {name}")
    except Exception as e:
        logger.warning(f"Create pending report failed: {e}")


def queue_analysis(code: str, name: str = ""):
    """Queue an analysis request for Claude Code skill processing."""
    try:
        os.makedirs(QUEUE_DIR, exist_ok=True)
        req = {
            "stock_code": code,
            "stock_name": name,
            "requested_at": datetime.now().isoformat(),
        }
        fpath = os.path.join(QUEUE_DIR, f"{code}.json")
        with open(fpath, "w") as f:
            json.dump(req, f)
        logger.info(f"Analysis request queued: {fpath}")
    except Exception as e:
        logger.error(f"Queue write failed: {e}")


# ============================================================
# Code resolution & validation
# ============================================================

def _resolve_codes(text: str) -> list:
    text = text.strip()
    codes = STOCK_CODE_RE.findall(text)
    if codes:
        return list(dict.fromkeys(codes))
    for name, code in NAME_TO_CODE.items():
        if name in text:
            return [code]
    return []


def _validate_codes(codes: list) -> list:
    if not _AK_AVAILABLE or not codes:
        return codes
    valid = []
    try:
        df = _get_spot_df()
        if df is None:
            return codes
        all_codes = set(df["代码"].values)
        for c in codes:
            if c in all_codes:
                valid.append(c)
            else:
                logger.info(f"Filtered invalid code: {c}")
    except Exception as e:
        logger.error(f"Code validation failed, keeping all: {e}")
        return codes
    return valid


def _extract_top_n(text: str) -> int:
    if not text:
        return 0
    m = TOP_N_RE.search(text)
    if not m:
        m2 = re.search(r"前\s*(\d+|[一二两三四五六七八九十])", text)
        if m2:
            raw = m2.group(1)
            return CN_NUM_MAP.get(raw, int(raw) if raw.isdigit() else 0)
        return 0
    raw = m.group(1)
    if raw.startswith("前"):
        raw = raw[1:]
    if raw.isdigit():
        return int(raw)
    return CN_NUM_MAP.get(raw.strip(), 0)


def _dedup_codes(chat_id, codes: list) -> tuple:
    now = datetime.now()
    key = str(chat_id)
    if key in _RECENT_CODES:
        prev_time, prev_codes = _RECENT_CODES[key]
        if (now - prev_time).total_seconds() < 120:
            overlap = set(codes) & prev_codes
            merged = list(dict.fromkeys(codes + list(prev_codes)))
            _RECENT_CODES[key] = (now, set(merged))
            return merged, len(overlap)
    _RECENT_CODES[key] = (now, set(codes))
    return codes, 0


# ============================================================
# Bot command handlers
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "A股智能分析助手 v2 已就绪\n\n"
        "直接发送股票代码或名称，自动进入分析队列。\n"
        "支持单只分析 / 多只对比 / 截图识别。\n\n"
        "发送 /help 查看完整用法。"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "=== A股智能分析助手 ===\n\n"
        "直接发送股票代码或名称即可分析：\n"
        "  603337              → 分析单只股票\n"
        "  茅台 / 宁德时代      → 股票名称也支持\n\n"
        "多只股票对比：\n"
        "  对比 600519 000858   → 对比分析\n"
        "  600519 000858        → 两个以上代码自动对比\n"
        "  推荐 前3             → 精选排名前N只\n\n"
        "截图识别：\n"
        "  发送股票列表截图      → OCR自动识别并分析\n\n"
        "命令：\n"
        "  /delete <代码>        → 删除指定股票的报告\n"
        "  /help                → 显示本帮助"
    )


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a stock report by stock code."""
    if not context.args:
        await update.message.reply_text("用法: /delete <股票代码>\n例如: /delete 603375")
        return

    code = context.args[0].strip()
    if not re.match(r"^\d{6}$", code):
        await update.message.reply_text(f"无效的股票代码: {code}，请输入6位数字代码。")
        return

    try:
        # 1. Fetch all reports and find by stock_code
        req = urllib.request.Request(
            f"{WEB_API_URL}/reports",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        reports = json.loads(resp.read())

        matching = [r for r in reports if r.get("stock_code") == code]
        if not matching:
            await update.message.reply_text(f"未找到 {code} 的报告。")
            return

        report_id = matching[0].get("id")
        stock_name = matching[0].get("stock_name", code)

        # 2. Delete the report
        del_req = urllib.request.Request(
            f"{WEB_API_URL}/reports/{report_id}",
            method="DELETE",
        )
        urllib.request.urlopen(del_req, timeout=10)

        await update.message.reply_text(f"已删除 {stock_name} ({code}) 的报告。")
    except Exception as e:
        logger.error(f"Delete failed for {code}: {e}")
        await update.message.reply_text(f"删除 {code} 失败: {e}")


# ============================================================
# Message handler
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    codes = _resolve_codes(text)
    chat_id = update.message.chat_id

    if not codes:
        await update.message.reply_text(
            "未识别到 A 股代码或名称。请发送 6 位代码（如 603337）或股票名称（如 茅台）。"
        )
        return

    codes = _validate_codes(codes)
    codes, overlap = _dedup_codes(chat_id, codes)
    if not codes:
        await update.message.reply_text("所有代码均无效，请确认代码正确。")
        return

    is_compare = bool(COMPARE_KW_RE.search(text)) or len(codes) >= 2
    top_n = _extract_top_n(text)

    if is_compare:
        count = len(codes)
        msg = f"已收到 {count} 只股票" + (f"（精选前{top_n}）" if top_n else "") + "，入队分析中..."
        await update.message.reply_text(msg)
        for code in codes:
            quote = get_quote(code)
            name = quote.get("name", "")
            price = quote.get("price", 0)
            if name and price > 0:
                _save_pending_to_web(code, name, price)
            queue_analysis(code, name)
        return

    # Single stock
    code = codes[0]
    quote = get_quote(code)
    name = quote.get("name", "")
    price = quote.get("price", 0)

    if not name or price <= 0:
        await update.message.reply_text(f"无法获取 {code} 的实时行情，请确认代码正确或稍后重试。")
        return

    # Quick preview
    chg = quote.get("change_pct", 0)
    pe = quote.get("pe", 0)
    mv = quote.get("total_mv", 0)
    preview = (
        f"${name}$ ({code}) 已入队分析\n\n"
        f"现价: {price:.2f} ({chg:+.2f}%)\n"
        f"PE: {pe:.1f}  市值: {mv / 1e8:.1f}亿\n\n"
        f"数据采集与AI分析进行中，请稍候..."
    )
    await update.message.reply_text(preview)

    _save_pending_to_web(code, name, price)
    queue_analysis(code, name)


# ============================================================
# Screenshot OCR handler
# ============================================================

async def _send_long_message(update: Update, text: str) -> bool:
    try:
        if len(text) <= 4000:
            await update.message.reply_text(text)
            return True
        parts = [text[i:i + 3900] for i in range(0, len(text), 3900)]
        for i, part in enumerate(parts):
            prefix = f"({i + 1}/{len(parts)})\n" if len(parts) > 1 else ""
            await update.message.reply_text(prefix + part)
        return True
    except Exception as e:
        logger.error(f"Send long message failed: {e}")
        return False


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    caption = update.message.caption or ""
    chat_id = update.message.chat_id

    try:
        status_msg = await update.message.reply_text("正在识别截图（OCR + 入队分析）...")
    except Exception:
        status_msg = None

    # Download
    try:
        file = await context.bot.get_file(photo.file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        bio.seek(0)
        image_bytes = bio.read()
    except Exception as e:
        logger.error(f"Photo download failed: {e}")
        if status_msg:
            try:
                await status_msg.edit_text(f"图片下载失败: {e}")
            except Exception:
                pass
        return

    # OCR
    try:
        import numpy as np
        from PIL import Image
        reader = _get_ocr_reader()
        image = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(image)
        results = reader.readtext(img_array)
        results.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
        texts = [r[1] for r in results if r[2] > 0.3]
        text = "\n".join(texts)
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        if status_msg:
            try:
                await status_msg.edit_text(f"OCR 识别失败: {e}")
            except Exception:
                pass
        return

    if not text or len(text.strip()) < 5:
        if status_msg:
            try:
                await status_msg.edit_text("未能从截图中识别出有效文字，请确认截图清晰。")
            except Exception:
                pass
        return

    codes = _resolve_codes(text)
    if caption:
        codes_from_caption = _resolve_codes(caption)
        for c in codes_from_caption:
            if c not in codes:
                codes.append(c)

    if not codes:
        preview = text[:400]
        if status_msg:
            try:
                await status_msg.edit_text(f"未识别到 A 股代码。\n\n识别文字:\n{preview}")
            except Exception:
                pass
        return

    codes = _validate_codes(codes)
    codes, overlap = _dedup_codes(chat_id, codes)
    if not codes:
        if status_msg:
            try:
                await status_msg.edit_text("识别到的代码均无效（可能 OCR 误读），请手动输入。")
            except Exception:
                pass
        return

    top_n = _extract_top_n(caption) or _extract_top_n(text)
    dup_note = f" [已去重{overlap}只]" if overlap >= 3 else ""

    if status_msg:
        try:
            await status_msg.edit_text(f"识别到 {len(codes)} 只: {', '.join(codes)}{dup_note}，入队分析中...")
        except Exception:
            pass

    for code in codes:
        quote = get_quote(code)
        name = quote.get("name", "")
        price = quote.get("price", 0)
        if name and price > 0:
            _save_pending_to_web(code, name, price)
        queue_analysis(code, name)

    await asyncio.sleep(1)

    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass


# ============================================================
# Main
# ============================================================

def main():
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(
        read_timeout=30.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=30.0,
        httpx_kwargs={"trust_env": False},
    )

    app = Application.builder().token(BOT_TOKEN).request(request).build()

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Global error: {context.error}", exc_info=context.error)
        if update and hasattr(update, "message") and update.message:
            try:
                await update.message.reply_text("处理请求时出错，请重试。")
            except Exception:
                pass

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Bot v2 starting (thin client mode — queues to Claude Code skills)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
