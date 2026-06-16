"""Entry point: python -m worldcup_bot

Builds the Telegram Application, registers all handlers, starts polling.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, time as dtime

import pytz
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from worldcup_bot.api.client import FootballAPIError
from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.daily_update import generate_daily_update
from worldcup_bot.bot.handlers import (
    _goal_token,
    cmd_actual,
    cmd_ayer,
    cmd_clasificacion,
    cmd_en_directo,
    cmd_general,
    cmd_hoy,
    cmd_lista_aciertos,
    cmd_lista_aciertos_actual,
    cmd_mis_predicciones,
    cmd_participantes,
    cmd_siguiente,
    cmd_simula_gol,
    cmd_start,
    cmd_tongo,
    cmd_update_diario,
    cmd_ver_gol_callback,
    make_client,
)
from worldcup_bot.config import Settings, ai_enabled, load_settings
from worldcup_bot.reddit.notifier import (
    _is_silent_hour,
    build_goal_keyboard,
    format_goal_notification,
)
from worldcup_bot.reddit.parser import compute_new_goals
from worldcup_bot.reddit.scanner import RedditMatchScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# ── daily AI update job ───────────────────────────────────────────────────────


async def daily_update_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily job: post AI-generated Spanish recap to the Telegram group."""
    try:
        settings: Settings = context.bot_data["settings"]
        client = make_client(settings)
        ai = AIClient(
            settings.openai_api_key,
            settings.openai_base_url,
            settings.openai_model,
        )
        text = await generate_daily_update(client, ai, settings)
        if text is None:
            log.info("Daily update skipped: no matches yesterday or today")
            return
        await context.bot.send_message(chat_id=settings.telegram_group_id, text=text, parse_mode="HTML")
    except Exception:
        log.exception("daily_update_job failed")


# ── polling job ───────────────────────────────────────────────────────────────


async def poll_goals_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: discover new Reddit match-thread goals and notify the group.

    Scheduled every settings.goal_poll_interval_seconds seconds.
    TELEGRAM_GROUP_ID is guaranteed set by load_settings (RuntimeError if missing).

    Dedup strategy: on the FIRST poll for a thread, all current goal keys are
    seeded into the notified set WITHOUT sending — prevents spamming goals that
    existed before the bot started watching.  On subsequent polls, any new key
    triggers a notification.
    """
    try:
        settings: Settings = context.bot_data["settings"]

        # Lazy-initialise dedup state
        if "notified_goal_keys" not in context.bot_data:
            context.bot_data["notified_goal_keys"] = set()
        if "seeded_threads" not in context.bot_data:
            context.bot_data["seeded_threads"] = set()

        # Lazy-initialise the scanner (persists session + state across ticks)
        if context.bot_data.get("reddit_scanner") is None:
            context.bot_data["reddit_scanner"] = RedditMatchScanner(
                user_agent=settings.reddit_user_agent
            )
        scanner: RedditMatchScanner = context.bot_data["reddit_scanner"]

        # Get live matches — cheapest call first
        client = make_client(settings)
        try:
            live = client.get_live_matches()
        except FootballAPIError as exc:
            log.warning("poll_goals_job: could not get live matches: %s", exc)
            return

        if not live:
            return

        # Scan Reddit for matched threads
        thread_results = scanner.scan_live_matches(live)

        notified: set[str] = context.bot_data["notified_goal_keys"]
        seeded: set[str] = context.bot_data["seeded_threads"]

        local_tz = pytz.timezone(settings.timezone)
        now_local = datetime.now(local_tz)
        silent = _is_silent_hour(now_local)

        if "goal_clips" not in context.bot_data:
            context.bot_data["goal_clips"] = {}

        for result in thread_results:
            thread_id = result.thread.post_id
            new_goals, notified, seeded = compute_new_goals(
                thread_id, result.events, notified, seeded
            )
            for event in new_goals:
                token = _goal_token(event.key)
                context.bot_data["goal_clips"][token] = {
                    "home_team": event.home_team,
                    "away_team": event.away_team,
                    "home_score": event.home_score,
                    "away_score": event.away_score,
                    "scorer": event.scorer,
                    "minute_text": event.minute_text,
                    "scoring_team": event.scoring_team,
                    "home_tla": result.home_tla,
                    "away_tla": result.away_tla,
                    "status": "pending",
                }
                text = format_goal_notification(
                    event,
                    home_tla=result.home_tla,
                    away_tla=result.away_tla,
                )
                keyboard = build_goal_keyboard(token)
                try:
                    await context.bot.send_message(
                        chat_id=settings.telegram_group_id,
                        text=text,
                        reply_markup=keyboard,
                        disable_notification=silent,
                    )
                    log.info(
                        "Goal notification sent: %s (thread %s)", event.key, thread_id
                    )
                except Exception as exc:
                    log.error(
                        "Failed to send goal notification for %s: %s",
                        event.key,
                        exc,
                    )

        # Persist updated dedup sets
        context.bot_data["notified_goal_keys"] = notified
        context.bot_data["seeded_threads"] = seeded

    except Exception as exc:
        log.exception("poll_goals_job: unexpected error (will retry next tick): %s", exc)


# ── app builder ───────────────────────────────────────────────────────────────


def build_app(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Store settings in bot_data for handler access
    app.bot_data["settings"] = settings
    # Initialise dedup state eagerly so tests can inspect it
    app.bot_data["notified_goal_keys"] = set()
    app.bot_data["seeded_threads"] = set()
    app.bot_data["reddit_scanner"] = None
    # goal_clips maps short token → goal context dict for "Ver gol" callbacks
    app.bot_data["goal_clips"] = {}
    # in-flight lock set — tokens currently being processed (non-blocking guard)
    app.bot_data["vergol_inflight"] = set()
    # Telegram file_id cache: media_url → file_id (skip re-upload on repeat sends)
    app.bot_data["clip_file_ids"] = {}

    handlers = [
        CommandHandler("start", cmd_start),
        CommandHandler("clasificacion", cmd_clasificacion),
        CommandHandler("actual", cmd_actual),
        CommandHandler("porra", cmd_actual),
        CommandHandler("listaaciertos", cmd_lista_aciertos),
        CommandHandler("listaaciertosactual", cmd_lista_aciertos_actual),
        CommandHandler("endirecto", cmd_en_directo),
        CommandHandler("hoy", cmd_hoy),
        CommandHandler("ayer", cmd_ayer),
        CommandHandler("siguiente", cmd_siguiente),
        CommandHandler("general", cmd_general),
        CommandHandler("tongo", cmd_tongo),
        # New approved improvements
        CommandHandler("mispredicciones", cmd_mis_predicciones),
        CommandHandler("participantes", cmd_participantes),
        # "Ver gol" inline button handler
        CallbackQueryHandler(cmd_ver_gol_callback, pattern=r"^vergol:"),
        # Test / utility
        CommandHandler("simulagol", cmd_simula_gol),
        CommandHandler("updatediario", cmd_update_diario),
    ]

    for handler in handlers:
        app.add_handler(handler)

    return app


def main() -> None:
    # Inject the OS/container trust store so requests trusts corporate CA certs
    # (handles environments with SSL inspection / self-signed certificate chains).
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass

    try:
        settings = load_settings()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    log.info(
        "Starting WorldCup2026 bot | competition=%s | predictions=%s",
        settings.competition_code,
        settings.predictions_path,
    )

    app = build_app(settings)

    log.info(
        "Goal notifier enabled — polling Reddit every %ds for group %s",
        settings.goal_poll_interval_seconds,
        settings.telegram_group_id,
    )
    app.job_queue.run_repeating(
        poll_goals_job,
        interval=settings.goal_poll_interval_seconds,
        first=10,
        name="poll_goals",
    )

    if ai_enabled(settings) and settings.telegram_group_id:
        tz = pytz.timezone(settings.timezone)
        app.job_queue.run_daily(
            daily_update_job,
            time=dtime(hour=settings.daily_update_hour, minute=0, tzinfo=tz),
            name="daily_update",
        )
        log.info(
            "Daily AI update enabled — posting at %02d:00 %s to group %s",
            settings.daily_update_hour,
            settings.timezone,
            settings.telegram_group_id,
        )
    else:
        log.info(
            "Daily AI update DISABLED — set OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL to enable."
        )

    app.run_polling()


if __name__ == "__main__":
    main()
