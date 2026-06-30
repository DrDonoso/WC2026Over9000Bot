"""Picante — random spicy LLM replies to group messages.

Gate functions are pure (no Telegram I/O) so Buffon can unit-test them directly.
The orchestrator ``maybe_reply`` wires the gates to the AIClient and PTB update.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime

import pytz

from worldcup_bot.ai.client import AIClient, AIError
from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.state import ChatState, save_chat_state
from worldcup_bot.config import Settings

log = logging.getLogger(__name__)

_SYSTEM = (
    "Eres el asistente cachondo y gamberro del grupo de Telegram de una porra del "
    "Mundial 2026 entre amigos.\n"
    "Tu misión: soltar UN comentario pícaro, ingenioso y con mucha gracia sobre la "
    "conversación reciente del grupo.\n"
    "Tono: banter amigable entre colegas — con chispa, pero nunca cruel. "
    "Prohibido: insultos reales, contenido sexual, información personal sensible, "
    "discursos de odio.\n"
    "Idioma: español principalmente; catalán cuando salga natural (como el grupo).\n"
    "Formato: máximo 2-3 frases cortas. Sin saludos, sin presentaciones — suéltalo directamente."
)


# ── pure gate functions ───────────────────────────────────────────────────────


def probability_gate(probability: float) -> bool:
    """Return True with probability *probability* (0.0–1.0).

    ``probability=0.20`` fires on ~1 in 5 calls.
    """
    return random.random() < probability


def cooldown_gate(last_ts: float, cooldown_seconds: int, now_ts: float) -> bool:
    """Return True when at least *cooldown_seconds* have elapsed since the last reply."""
    return (now_ts - last_ts) >= cooldown_seconds


def daily_cap_gate(count: int, max_per_day: int, last_date: str, today: str) -> bool:
    """Return True when the daily cap has not been reached for *today*.

    If *last_date* differs from *today* the counter is treated as 0 (new day).
    """
    if last_date != today:
        return True  # new calendar day — counter resets implicitly
    return count < max_per_day


def min_buffer_gate(buffer_len: int, min_buffer: int) -> bool:
    """Return True when the buffer contains at least *min_buffer* messages."""
    return buffer_len >= min_buffer


# ── pure prompt builders ──────────────────────────────────────────────────────


def build_picante_system_prompt() -> str:
    return _SYSTEM


def build_picante_user_message(messages: list[dict]) -> str:
    """Format buffered messages as ``'Nombre: texto'`` lines for the AI user prompt."""
    if not messages:
        return "(sin contexto)"
    lines = []
    for m in messages:
        name = m.get("display_name") or m.get("username") or "?"
        text = m.get("text") or ""
        lines.append(f"{name}: {text}")
    return "\n".join(lines)


# ── orchestrator ──────────────────────────────────────────────────────────────


async def maybe_reply(
    update,
    context,  # noqa: ANN001 — telegram.ext.ContextTypes.DEFAULT_TYPE
    buf: RingBuffer,
    state: ChatState,
    state_path: str,
    settings: Settings,
    ai: AIClient,
) -> None:
    """Run all gates; if all pass, call AI and reply to the triggering message.

    Gates (in order):
    1. min_buffer  — enough context messages in the buffer
    2. probability — random 1-in-N gate
    3. cooldown    — minimum seconds since last reply
    4. daily_cap   — max replies per calendar day (local tz)
    """
    try:
        tz = pytz.timezone(settings.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        now_ts = time.time()

        if not min_buffer_gate(len(buf), settings.picante_min_buffer):
            return
        if not probability_gate(settings.picante_probability):
            return
        if not cooldown_gate(
            state.picante_last_ts, settings.picante_cooldown_seconds, now_ts
        ):
            return
        if not daily_cap_gate(
            state.picante_daily_count,
            settings.picante_max_per_day,
            state.picante_last_date,
            today,
        ):
            return

        messages = buf.snapshot()
        system = build_picante_system_prompt()
        user_msg = build_picante_user_message(messages)

        text = await ai.complete(
            system,
            user_msg,
            temperature=settings.picante_temperature,
            max_completion_tokens=150,
        )

        await update.message.reply_text(text, parse_mode=None)

        # Persist updated counters
        state.picante_last_ts = now_ts
        if state.picante_last_date != today:
            state.picante_daily_count = 1
            state.picante_last_date = today
        else:
            state.picante_daily_count += 1
        save_chat_state(state_path, state)

        log.info(
            "picante: replied (today=%s, count=%d/%d)",
            today,
            state.picante_daily_count,
            settings.picante_max_per_day,
        )

    except AIError as exc:
        log.warning("picante: AI error — %s", exc)
    except Exception as exc:
        log.exception("picante: unexpected error — %s", exc)
