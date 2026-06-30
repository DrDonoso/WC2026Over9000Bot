"""Revive — periodic @mention of inactive porra participants.

Candidate-selection and prompt-building functions are pure so Buffon can
unit-test them without Telegram or network I/O.

Scheduling model (self-rescheduling, quiet-aware):
- Each job run schedules exactly ONE next run via schedule_next_revive() in
  the finally block, on every exit path (success, quiet-skip, no-candidates,
  AIError, unexpected Exception).
- next_revive_delay() adds ±jitter to the base interval so runs are spread
  across the day rather than firing at a fixed clock time.
- is_quiet_hours() / next_revive_delay() push any run that would land in the
  configured quiet window to just after quiet_end:00 + random spread, so the
  bot never @mentions anyone at night.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytz

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


# -- pure candidate-selection functions ---------------------------------------


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
    - last_seen is older than inactive_days (or absent).
    - The user has NOT been mentioned within the last mention_cooldown_days.

    The result is sorted for deterministic round-robin rotation.
    """
    inactivity_delta = timedelta(days=inactive_days)
    cooldown_delta = timedelta(days=mention_cooldown_days)
    candidates: list[str] = []

    for username in porra_usernames:
        if not username:
            continue

        # inactivity check
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
                inactive = True  # unparseable timestamp -> treat as inactive

        if not inactive:
            continue

        # mention-cooldown check
        mentioned_iso = last_mentioned.get(username)
        if mentioned_iso is not None:
            try:
                mentioned_dt = datetime.fromisoformat(mentioned_iso)
                if mentioned_dt.tzinfo is None:
                    mentioned_dt = mentioned_dt.replace(tzinfo=timezone.utc)
                if (now - mentioned_dt) <= cooldown_delta:
                    continue  # mentioned too recently
            except Exception:
                pass  # unparseable -> skip cooldown check, allow candidate

        candidates.append(username)

    return sorted(candidates)


def select_candidate(candidates: list[str], rotate_index: int) -> tuple[str, int]:
    """Pick one candidate using round-robin rotation.

    Returns (chosen_username, new_rotate_index).
    candidates must be non-empty. The index wraps modulo len(candidates).
    """
    idx = rotate_index % len(candidates)
    chosen = candidates[idx]
    return chosen, rotate_index + 1


# -- pure scheduling helpers --------------------------------------------------


def is_quiet_hours(hour: int, quiet_start: int, quiet_end: int) -> bool:
    """Return True when hour (0-23) falls inside the configured quiet window.

    - quiet_start == quiet_end: no quiet window -> always False.
    - quiet_start > quiet_end (midnight wrap, e.g. 23->06):
      quiet when hour >= quiet_start OR hour < quiet_end.
    - quiet_start < quiet_end (same day, e.g. 01->06):
      quiet when quiet_start <= hour < quiet_end.
    """
    if quiet_start == quiet_end:
        return False
    if quiet_start > quiet_end:  # wraps midnight (e.g. 23 -> 06)
        return hour >= quiet_start or hour < quiet_end
    else:  # same-day window (e.g. 01 -> 06)
        return quiet_start <= hour < quiet_end


def next_revive_delay(
    base_seconds: int,
    jitter_seconds: int,
    now_local: datetime,
    quiet_start: int,
    quiet_end: int,
    rand: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return seconds until the next revive run.

    Algorithm:
    1. delay = base_seconds + rand(-jitter_seconds, +jitter_seconds),
       clamped to >= 60.
    2. target = now_local + timedelta(seconds=delay).
    3. If target lands in quiet hours: push to the next quiet_end:00
       at or after target, plus a rand(0, jitter_seconds) spread so
       multiple instances do not all wake at exactly quiet_end:00.
    4. Return final delay (float, seconds).

    rand is injectable so Buffon can test deterministically.
    """
    # 1. Base delay with symmetric jitter
    delay = base_seconds + rand(-jitter_seconds, jitter_seconds)
    delay = max(delay, 60.0)

    # 2. Target wall-clock time
    target = now_local + timedelta(seconds=delay)

    # 3. Push past quiet window if needed
    if is_quiet_hours(target.hour, quiet_start, quiet_end):
        # Next occurrence of quiet_end:00 at or after target
        wake = target.replace(hour=quiet_end, minute=0, second=0, microsecond=0)
        if wake <= target:
            wake += timedelta(days=1)
        # Spread runs across [quiet_end:00, quiet_end:00 + jitter) to avoid pile-ups
        spread = rand(0, jitter_seconds)
        wake += timedelta(seconds=spread)
        delay = (wake - now_local).total_seconds()

    return delay


def schedule_next_revive(job_queue, settings: Settings) -> None:
    """Schedule the next revive run as a one-shot PTB job.

    Uses the current local time, jitter, and quiet-hour window from settings.
    Called from revive_inactive_job's finally block to maintain the
    self-rescheduling loop.
    """
    now_local = datetime.now(pytz.timezone(settings.timezone))
    delay = next_revive_delay(
        settings.revive_check_interval_seconds,
        settings.revive_jitter_seconds,
        now_local,
        settings.revive_quiet_start_hour,
        settings.revive_quiet_end_hour,
    )
    job_queue.run_once(revive_inactive_job, when=delay, name="revive_inactive")


# -- pure prompt builders -----------------------------------------------------


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


# -- self-rescheduling periodic job -------------------------------------------


async def revive_inactive_job(context) -> None:  # noqa: ANN001
    """@mention one inactive porra participant if eligible, then reschedule.

    Self-rescheduling: the finally block ALWAYS calls schedule_next_revive
    when revive is enabled, so the loop continues on every exit path: success,
    quiet-hours skip, no-candidates, AIError, and unexpected Exception.

    Guards (before any work):
    - revive_enabled(settings) AND ai_enabled(settings)
    - ai_client present in bot_data
    - current local hour is NOT in the quiet window
    """
    settings: Settings | None = None
    try:
        settings = context.bot_data["settings"]

        if not revive_enabled(settings) or not ai_enabled(settings):
            return

        ai: AIClient | None = context.bot_data.get("ai_client")
        if ai is None:
            return

        # Quiet-hours guard — skip mention but still reschedule via finally
        now_local = datetime.now(pytz.timezone(settings.timezone))
        if is_quiet_hours(
            now_local.hour,
            settings.revive_quiet_start_hour,
            settings.revive_quiet_end_hour,
        ):
            log.info(
                "revive_inactive_job: quiet hours (%02d:00) — skipping mention",
                now_local.hour,
            )
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
    finally:
        # Always reschedule the next run when revive is enabled.
        if settings is not None and revive_enabled(settings):
            schedule_next_revive(context.job_queue, settings)
