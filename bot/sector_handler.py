"""
Telegram bot handlers for concept-sector tracking.
- InlineKeyboard "📊 板块追踪" → prompt for concept name
- User input concept → run selection → save → reply
- 60s timer to auto-reopen if pick already exists
"""
import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from astock_data import get_quote  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.sector_pick import SectorPick, SectorPickStock  # noqa: E402
from sector_selector import select_stocks_for_concept  # noqa: E402
from ai_analyzer import call_deepseek_raw  # noqa: E402

logger = logging.getLogger(__name__)


# Real DeepSeek call delegated to ai_analyzer. Caller (sector_selector) parses JSON.
def call_deepseek(prompt: str) -> str:
    """Thin wrapper around ai_analyzer.call_deepseek_raw. Returns raw model text."""
    return call_deepseek_raw(prompt)


# In-memory map: user_id -> sector_name awaiting confirmation
_pending: dict[int, dict] = {}


# === Inline button entry ===
async def handle_sector_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "请输入概念名（如：pvdf / 太赫兹 / 固态电池）"
    )
    context.user_data["awaiting_sector_input"] = True


# === User text input ===
async def handle_sector_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text_override: str = None):
    if not context.user_data.get("awaiting_sector_input"):
        return
    raw = text_override if text_override is not None else (update.message.text or "")
    concept_name = raw.strip()
    context.user_data["awaiting_sector_input"] = False
    user_id = update.effective_user.id
    db = SessionLocal()
    try:
        existing = (
            db.query(SectorPick)
            .filter(
                SectorPick.sector_name == concept_name,
                SectorPick.status.in_(["in_progress", "completed"]),
            )
            .first()
        )
        if existing:
            await _handle_existing(update, context, db, existing, user_id, concept_name)
            return
        await _run_new_pick(update, context, db, concept_name)
    finally:
        db.close()


async def _handle_existing(update, context, db, existing, user_id, concept_name):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("立即重开", callback_data=f"sector_reopen:{existing.id}"),
            InlineKeyboardButton("取消", callback_data="sector_cancel"),
        ]
    ])
    msg = await update.message.reply_text(
        f"该板块 {concept_name} 已有进行中的追踪（id={existing.id}，创建于 {existing.created_at:%Y-%m-%d %H:%M}）。\n"
        f"60 秒后将自动重开一轮。",
        reply_markup=keyboard,
    )
    # Schedule auto-reopen after 60s
    _pending[user_id] = {
        "concept": concept_name,
        "existing_id": existing.id,
        "msg_id": msg.message_id,
        "chat_id": update.effective_chat.id,
    }

    def _auto_reopen():
        time.sleep(60)
        if user_id in _pending and _pending[user_id].get("existing_id") == existing.id:
            asyncio.run_coroutine_threadsafe(
                _do_reopen(context.bot, _pending.pop(user_id), db_factory=SessionLocal),
                context.bot.loop,
            )

    threading.Thread(target=_auto_reopen, daemon=True).start()


async def _do_reopen(bot, pending: dict, db_factory):
    db = db_factory()
    try:
        old = db.query(SectorPick).filter(SectorPick.id == pending["existing_id"]).first()
        if old and old.status != "archived":
            old.status = "archived"
            old.archived_at = datetime.utcnow()
            db.commit()
        await _run_new_pick_in_chat(bot, pending["chat_id"], pending["concept"])
    finally:
        db.close()


async def _run_new_pick(update, context, db, concept_name):
    await _run_new_pick_in_chat(context.bot, update.effective_chat.id, concept_name)


async def _run_new_pick_in_chat(bot, chat_id: int, concept_name: str):
    db = SessionLocal()
    try:
        result = select_stocks_for_concept(
            concept_name, db, deepseek_callable=call_deepseek,
        )
        if "error" in result:
            await bot.send_message(
                chat_id=chat_id,
                text=f"选股失败：{result['error']}\n请换一个概念重试。",
            )
            return
        # Archive any old active pick (defensive)
        old = (
            db.query(SectorPick)
            .filter(
                SectorPick.sector_name == concept_name,
                SectorPick.status.in_(["in_progress", "completed"]),
            )
            .first()
        )
        if old:
            old.status = "archived"
            old.archived_at = datetime.utcnow()
        # Create new pick
        pick = SectorPick(
            sector_name=concept_name,
            status="in_progress",
            selection_source=result["source"],
        )
        db.add(pick)
        db.flush()
        t0_date = datetime.now().date()
        for p in result["picks"]:
            q = get_quote(p["code"])
            t0_price = q.get("price", 0) if q else 0
            db.add(SectorPickStock(
                sector_pick_id=pick.id,
                stock_code=p["code"],
                stock_name=p["name"],
                selection_reason=p["reason"],
                t0_date=t0_date,
                t0_price=t0_price or None,
                t0_avg_price=None,
            ))
        db.commit()
        # Reply
        lines = [
            f"已记录 3 只（板块：{concept_name}）：",
        ]
        for p in result["picks"]:
            lines.append(f"- {p['code']} {p['name']} — {p['reason']}")
        lines.append("")
        lines.append(f"数据源：{'API 实时' if result['source'] == 'api_driven' else 'AI 知识'}")
        if result.get("rejected"):
            lines.append("")
            lines.append("⚠️ 以下股票被后置校验拒绝（不合规，未选入）：")
            for r in result["rejected"][:3]:
                rs = "; ".join(r.get("reject_reasons", []))
                lines.append(f"  · {r['code']} {r['name']} — {rs}")
        lines.append("")
        lines.append("将在 T+5/10/20 个交易日后自动追踪。")
        await bot.send_message(chat_id=chat_id, text="\n".join(lines))
    finally:
        db.close()


# === Reopen button ===
async def handle_reopen_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 2:
        return
    pick_id = int(parts[1])
    user_id = update.effective_user.id
    pending = _pending.pop(user_id, None)
    db = SessionLocal()
    try:
        old = db.query(SectorPick).filter(SectorPick.id == pick_id).first()
        if old and old.status != "archived":
            old.status = "archived"
            old.archived_at = datetime.utcnow()
            db.commit()
        concept = old.sector_name if old else (pending["concept"] if pending else "unknown")
        await _run_new_pick_in_chat(context.bot, update.effective_chat.id, concept)
    finally:
        db.close()


# === Cancel button ===
async def handle_cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    _pending.pop(user_id, None)
    await query.message.edit_text("已取消重开。")


def register_sector_handlers(app):
    """Wire handlers into an Application. Called from telegram_bot.py main()."""
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(handle_sector_button, pattern="^sector_pick$"))
    app.add_handler(CallbackQueryHandler(handle_reopen_button, pattern="^sector_reopen:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_button, pattern="^sector_cancel$"))
    # Note: handle_sector_text must be registered as a low-priority text handler
    # in telegram_bot.py itself, where filters.TEXT is composed with the existing chain.
    return handle_sector_text
