"""Picante — random spicy LLM replies to group messages.

Gate functions are pure (no Telegram I/O) so Buffon can unit-test them directly.
The orchestrator ``maybe_reply`` wires the gates to the AIClient and PTB update.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

import pytz

from worldcup_bot.ai.client import AIClient, AIError
from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.profiles import UserProfile, get_profile, load_profiles, save_profiles
from worldcup_bot.chat.state import ChatState, save_chat_state
from worldcup_bot.config import Settings, picante_profiles_enabled

log = logging.getLogger(__name__)

_SYSTEM = (
    "Eres el asistente gamberro del grupo de Telegram de una porra del Mundial 2026 entre amigos.\n"
    "MISIÓN: Suelta UN comentario pícaro e ingenioso sobre el ÚLTIMO MENSAJE. "
    "Es una intervención concisa y directa, no un resumen de la conversación.\n"
    "REGLA DE CONTEXTO: Si el bloque 'CONTEXTO RECIENTE' está claramente relacionado con el ÚLTIMO MENSAJE "
    "(mismo tema, conversación en curso o hilo que continúa), tenlo en cuenta y aprovéchalo — "
    "un callback o referencia al hilo hace el comentario más afilado y conectado. "
    "Si el contexto reciente no tiene relación con el último mensaje, ignóralo por completo y comenta solo el último mensaje.\n"
    "IDIOMA: Responde SIEMPRE en el mismo idioma del ÚLTIMO MENSAJE. "
    "Si el último mensaje está en catalán → responde en catalán. "
    "Si está en castellano → responde en castellano. No mezcles idiomas.\n"
    "TONO: Banter amigable con picardía — con chispa, pero nunca cruel. "
    "Prohibido: insultos reales, contenido sexual, información personal sensible, discursos de odio.\n"
    "FORMATO: 1-2 frases cortas, directas. Sin saludos ni presentaciones. "
    "Dirígete a quien escribió el último mensaje."
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


def build_picante_user_message(
    messages: list[dict],
    *,
    profiles: dict[str, UserProfile] | None = None,
    author_username: str = "",
    others_cap: int = 3,
) -> str:
    """Build the user prompt, highlighting the triggering message (messages[-1]).

    When *profiles* and *author_username* are provided, prepends a "PERFILES DEL
    GRUPO" block with the author's profile first, then up to *others_cap* other
    recently-seen users from the buffer.  If profiles is None or author_username
    is empty, the output is identical to the no-profiles behaviour.

    Never raises — all profile logic has silent fallbacks.
    """
    if not messages:
        return "(sin contexto)"

    def _fmt(m: dict) -> str:
        name = m.get("display_name") or m.get("username") or "?"
        text = m.get("text") or ""
        return f"{name}: {text}"

    trigger = messages[-1]
    prior = messages[:-1]

    parts: list[str] = []

    # ── Profiles block (optional) ────────────────────────────────────────────
    try:
        if profiles is not None and author_username:
            profile_parts: list[str] = []

            def _fmt_profile(p: UserProfile, label: str) -> str:
                lines = [label]
                if p.rasgos:
                    lines.append(f"Rasgos: {p.rasgos}")
                if p.equipo:
                    lines.append(f"Equipo favorito: {p.equipo}")
                if p.motes:
                    lines.append(f"Motes/apodos: {', '.join(p.motes)}")
                if p.temas:
                    lines.append(f"Temas/aficiones: {', '.join(p.temas)}")
                if p.tono:
                    lines.append(f"Tono a usar: {p.tono}")
                if p.piques_recientes:
                    recent = p.piques_recientes[-3:]  # last 3 for brevity
                    piques_str = " | ".join(r.get("texto", "") for r in recent if r.get("texto"))
                    if piques_str:
                        lines.append(f"Piques recientes: {piques_str}")
                return "\n".join(lines)

            author_profile = get_profile(profiles, author_username)
            if author_profile:
                profile_parts.append(_fmt_profile(author_profile, f"[AUTOR: {author_username}]"))

            # Collect other users seen in the buffer (excluding author), up to others_cap
            seen_in_buffer: list[str] = []
            for m in reversed(messages):
                u = m.get("username") or ""
                if u and u != author_username and u not in seen_in_buffer:
                    seen_in_buffer.append(u)
                if len(seen_in_buffer) >= others_cap:
                    break

            others_lines: list[str] = []
            for u in seen_in_buffer:
                p = get_profile(profiles, u)
                if p:
                    summary_parts = []
                    if p.equipo:
                        summary_parts.append(f"Equipo: {p.equipo}")
                    if p.tono:
                        summary_parts.append(f"Tono: {p.tono}")
                    if summary_parts:
                        others_lines.append(f"[{u}] {', '.join(summary_parts)}")

            if others_lines:
                profile_parts.append("[OTROS PARTICIPANTES RECIENTES]\n" + "\n".join(others_lines))

            if profile_parts:
                parts.append(
                    "PERFILES DEL GRUPO — úsalos para personalizar el comentario:\n\n"
                    + "\n\n".join(profile_parts)
                )
    except Exception as exc:
        log.warning("build_picante_user_message: profiles block error — %s", exc)

    # ── Context + trigger blocks ─────────────────────────────────────────────
    if prior:
        prior_block = "\n".join(_fmt(m) for m in prior)
        parts.append(
            "CONTEXTO RECIENTE — si está claramente relacionado con el ÚLTIMO MENSAJE, "
            "tenlo en cuenta y aprovéchalo; si no lo está, ignóralo por completo:\n" + prior_block
        )

    parts.append(
        "ÚLTIMO MENSAJE — responde a ESTE, en su mismo idioma:\n" + _fmt(trigger)
    )

    return "\n\n".join(parts)


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

        # ── Load profiles (best-effort — failures degrade gracefully) ─────────
        profiles: dict | None = None
        author_username = ""
        if picante_profiles_enabled(settings):
            try:
                profiles_path: str = context.bot_data.get("picante_profiles_path", "")
                if profiles_path:
                    profiles = load_profiles(profiles_path)
            except Exception as exc:
                log.warning("maybe_reply: load_profiles failed — %s — firing without profiles", exc)
                profiles = None
            try:
                author_username = (messages[-1].get("username") or "") if messages else ""
            except Exception:
                author_username = ""

        system = build_picante_system_prompt()
        user_msg = build_picante_user_message(
            messages,
            profiles=profiles,
            author_username=author_username,
            others_cap=settings.picante_profiles_others_cap,
        )

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

        # ── Persist pique into author's profile (best-effort) ─────────────────
        if picante_profiles_enabled(settings) and profiles is not None and author_username:
            try:
                now_utc_iso = datetime.now(timezone.utc).isoformat()
                profiles_path = context.bot_data.get("picante_profiles_path", "")
                if profiles_path:
                    # Re-load to get freshest state before mutating
                    fresh = load_profiles(profiles_path)
                    profile = fresh.get(author_username) or UserProfile(username=author_username)
                    piques = list(profile.piques_recientes)
                    piques.append({"ts": now_utc_iso, "texto": text[:200]})
                    piques = piques[-settings.picante_profiles_piques_cap:]
                    profile.piques_recientes = piques
                    fresh[author_username] = profile
                    save_profiles(profiles_path, fresh)
            except Exception as exc:
                log.warning("maybe_reply: persist pique failed — %s", exc)

    except AIError as exc:
        log.warning("picante: AI error — %s", exc)
    except Exception as exc:
        log.exception("picante: unexpected error — %s", exc)
