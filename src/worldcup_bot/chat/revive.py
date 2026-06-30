"""Revive — periodic @mention of inactive porra participants.

Candidate-selection and prompt-building functions are pure so Buffon can
unit-test them without Telegram or network I/O.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from worldcup_bot.ai.client import AIClient, AIError
from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.state import ChatState, save_chat_state
from worldcup_bot.config import Settings, ai_enabled, revive_enabled

log = logging.getLogger(__name__)

_SYSTEM = (
    "Eres el asistente del grupo de Telegram de una porra del Mundial 2026 entre amigos.\n"
    "Tu tarea: escribir UN mensaje corto y amigable para llamar la atención de un participante "
    "que lleva días sin aparecer por el chat, incorporándolo a la conversación actual de forma natural.\n"
    "Tono: cálido, con gracia, sin agresividad — como un amigo que nota que otro se ha esfumado.\n"
    "Idioma: español principalmente; catalán cuando salga natural.\n"
    "IMPORTANTE: NO escribas el símbolo @ ni el nombre de usuario — el sistema lo añade automáticamente.\n"
    "Longitud: 1-2 frases. Muy conciso."
)


# ── pure candidate-selection functions ───────────────────────────────────────


def compute_inactive_candidates(
    last_seen: dict[str, str],
    last_mentioned: dict[str, str],
    porra_usernames: list[str],
    now: datetime,
    inactive_days: int,
    mention_cooldown_days: int,
) -> list[str]:
    """Return a sorted list of porra usernames eligible for a revive mention.

    A username is eligible when:
    - It is non-empty (required for a valid @mention).
    - ``last_seen`` is older than *inactive_days* (or absent — seeded at startup
      and never updated means never spoke, treated as inactive once enough time
      has elapsed from the seed timestamp).
    - The user has NOT been mentioned within the last *mention_cooldown_days*.

    The result is sorted for deterministic round-robin rotation.
    """
    inactivity_delta = timedelta(days=inactive_days)
    cooldown_delta = timedelta(days=mention_cooldown_days)
    candidates: list[str] = []

    for username in porra_usernames:
        if not username:
            continue

        # ── inactivity check ──────────────────────────────────────────────────
        seen_iso = last_seen.get(username)
        if seen_iso is None:
            inactive = True
        else:
            try:
                seen_dt = datetime.fromisoformat(seen_iso)
                if seen_dt.tzinfo is None:
                    seen_dt = seen_dt.replace(tzinfo=timezone.utc)
                inactive = (now - seen_dt) > inactivity_delta
            except Exception:
                inactive = True  # unparseable timestamp → treat as inactive

        if not inactive:
            continue

        # ── mention-cooldown check ────────────────────────────────────────────
        mentioned_iso = last_mentioned.get(username)
        if mentioned_iso is not None:
            try:
                mentioned_dt = datetime.fromisoformat(mentioned_iso)
                if mentioned_dt.tzinfo is None:
                    mentioned_dt = mentioned_dt.replace(tzinfo=timezone.utc)
                if (now - mentioned_dt) <= cooldown_delta:
                    continue  # mentioned too recently
            except Exception:
                pass  # unparseable → skip cooldown check, allow candidate

        candidates.append(username)

    return sorted(candidates)


def select_candidate(candidates: list[str], rotate_index: int) -> tuple[str, int]:
    """Pick one candidate using round-robin rotation.

    Returns ``(chosen_username, new_rotate_index)``.
    *candidates* must be non-empty.  The index wraps modulo ``len(candidates)``.
    """
    idx = rotate_index % len(candidates)
    chosen = candidates[idx]
    return chosen, rotate_index + 1


# ── pure prompt builders ──────────────────────────────────────────────────────


def build_revive_system_prompt() -> str:
    return _SYSTEM


def build_revive_user_message(
    target_username: str,
    target_display: str,
    messages: list[dict],
) -> str:
    """Build the user-prompt for the revive AI call."""
    ctx_lines: list[str] = []
    for m in messages:
        name = m.get("display_name") or m.get("username") or "?"
        text = m.get("text") or ""
        ctx_lines.append(f"{name}: {text}")

    context_block = (
        "\n".join(ctx_lines) if ctx_lines else "(sin mensajes recientes en el grupo)"
    )

    return (
        f"PARTICIPANTE INACTIVO:\n"
        f"  username: @{target_username}\n"
        f"  nombre: {target_display}\n\n"
        f"CONVERSACIÓN RECIENTE DEL GRUPO:\n{context_block}\n\n"
        f"Escribe el mensaje de vuelta para {target_display}. "
        f"No incluyas '@{target_username}' ni ningún símbolo @ — el sistema lo añade."
    )


# ── periodic job ──────────────────────────────────────────────────────────────


async def revive_inactive_job(context) -> None:  # noqa: ANN001
    """Periodic job: @mention one inactive porra participant if one is found.

    Guards:
    - revive_enabled(settings) AND ai_enabled(settings)
    - At least one inactive candidate exists after applying cooldowns
    """
    try:
        settings: Settings = context.bot_data["settings"]

        if not revive_enabled(settings) or not ai_enabled(settings):
            return

        ai: AIClient | None = context.bot_data.get("ai_client")
        if ai is None:
            return

        state: ChatState = context.bot_data["chat_state"]
        state_path: str = context.bot_data["chat_state_path"]
        buf: RingBuffer = context.bot_data["chat_buffer"]
        porra_usernames: list[str] = context.bot_data.get("porra_usernames", [])
        porra_display: dict[str, str] = context.bot_data.get("porra_display_names", {})

        now = datetime.now(timezone.utc)

        candidates = compute_inactive_candidates(
            state.last_seen,
            state.last_mentioned,
            porra_usernames,
            now,
            settings.revive_inactive_days,
            settings.revive_mention_cooldown_days,
        )

        if not candidates:
            log.info("revive_inactive_job: no inactive candidates — skipping")
            return

        username, new_index = select_candidate(candidates, state.rotate_index)
        target_display = porra_display.get(username) or f"@{username}"

        messages = buf.snapshot()
        system = build_revive_system_prompt()
        user_msg = build_revive_user_message(username, target_display, messages)

        text = await ai.complete(
            system,
            user_msg,
            temperature=settings.revive_temperature,
            max_completion_tokens=150,
        )

        await context.bot.send_message(
            chat_id=settings.telegram_group_id,
            text=f"@{username} {text}",
            parse_mode=None,
        )

        state.last_mentioned[username] = now.isoformat()
        state.rotate_index = new_index
        save_chat_state(state_path, state)

        log.info(
            "revive_inactive_job: mentioned @%s (rotate_index=%d, candidates=%d)",
            username,
            new_index,
            len(candidates),
        )

    except AIError as exc:
        log.warning("revive_inactive_job: AI error — %s", exc)
    except Exception as exc:
        log.exception("revive_inactive_job: unexpected error — %s", exc)
