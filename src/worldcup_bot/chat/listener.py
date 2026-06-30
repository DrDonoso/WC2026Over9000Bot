"""Listener — MessageHandler callback for group text messages.

Filtering pipeline:
1. Wrong chat_id → return
2. Bot's own message → return
3. Command (starts with /) → return
4. Media with caption → return
5. Too short (< 5 chars) → return
6. Record to RingBuffer + update last_seen in ChatState
7. If picante_enabled → maybe_reply (probabilistic AI reply)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.picante import maybe_reply
from worldcup_bot.chat.state import ChatState
from worldcup_bot.config import Settings, picante_enabled

log = logging.getLogger(__name__)


async def on_group_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """PTB MessageHandler callback — filter, record, and optionally fire picante."""
    msg = update.effective_message
    if msg is None:
        return

    settings: Settings = context.bot_data["settings"]

    # 1. Reject messages from other chats (PTB filter handles GROUP type;
    #    this is belt-and-suspenders for our specific group_id).
    if settings.telegram_group_id and str(msg.chat_id) != str(
        settings.telegram_group_id
    ):
        return

    # 2. Reject the bot's own messages
    user = update.effective_user
    if user is None:
        return
    if user.id == context.bot.id:
        return

    # 3. Reject commands (PTB filter already excludes via ~filters.COMMAND;
    #    belt-and-suspenders in case of forwarded commands with altered entities).
    text = msg.text or ""
    if text.lstrip().startswith("/"):
        return

    # 4. Reject media messages that carry a caption (TEXT filter excludes pure
    #    media; this catches media+caption combos).
    if any(
        [
            msg.photo,
            msg.video,
            msg.animation,
            msg.sticker,
            msg.document,
            msg.voice,
            msg.video_note,
            msg.audio,
        ]
    ):
        return

    # 5. Reject too-short messages
    if not text or len(text.strip()) < 5:
        return

    # 6. Record to ring buffer
    username = (user.username or "").lower().strip()
    display_name = user.full_name or username or "unknown"
    now_utc = datetime.now(timezone.utc)

    buf: RingBuffer = context.bot_data["chat_buffer"]
    buf.append(
        username=username,
        display_name=display_name,
        user_id=user.id,
        text=text,
        timestamp=now_utc,
    )

    # 7. Update last_seen in-memory (persisted on next picante/revive event)
    state: ChatState = context.bot_data["chat_state"]
    if username:
        state.last_seen[username] = now_utc.isoformat()

    # 8. Maybe fire a picante reply
    if picante_enabled(settings):
        ai = context.bot_data.get("ai_client")
        if ai is not None:
            state_path: str = context.bot_data["chat_state_path"]
            await maybe_reply(update, context, buf, state, state_path, settings, ai)
