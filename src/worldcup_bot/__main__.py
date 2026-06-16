"""Entry point: python -m worldcup_bot

Builds the Telegram Application, registers all handlers, starts polling.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, time as dtime

import pytz
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from worldcup_bot.api.client import FootballAPIError
from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.commentators import generate_porra_commentary, pick_commentator
from worldcup_bot.ai.daily_update import generate_daily_update
from worldcup_bot.bot.formatters import bold_person_names
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
from worldcup_bot.espn.client import ESPNClient
from worldcup_bot.espn.formatter import format_match_stats
from worldcup_bot.porra import predictions as pred_loader
from worldcup_bot.porra.engine import compute_general_ranking
from worldcup_bot.porra.live import build_state, diff_live, load_live, render_changes_text, save_live
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


# ── finished-match stats + porra commentary job ───────────────────────────────


async def poll_finished_matches_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: detect newly-finished matches, post stats card + porra commentary.

    Dedup strategy: on the FIRST run, all currently-finished match ids are seeded
    into finished_seen WITHOUT sending — prevents re-firing for pre-existing finished
    matches on startup.  On subsequent runs, each newly-finished id triggers:
      Part A — ESPN stats card (HTML)
      Part B — porra ranking diff + AI commentary (if AI enabled)
    """
    try:
        settings: Settings = context.bot_data["settings"]

        # Lazy-init ESPN client
        if context.bot_data.get("espn_client") is None:
            context.bot_data["espn_client"] = ESPNClient(
                league_slug=settings.espn_league_slug
            )
        espn_client: ESPNClient = context.bot_data["espn_client"]

        # Lazy-init scanner (shared with goal-notifier)
        if context.bot_data.get("reddit_scanner") is None:
            context.bot_data["reddit_scanner"] = RedditMatchScanner(
                user_agent=settings.reddit_user_agent
            )
        scanner: RedditMatchScanner = context.bot_data["reddit_scanner"]

        client = make_client(settings)
        try:
            all_matches = client.get_all_matches()
        except FootballAPIError as exc:
            log.warning("poll_finished_matches_job: could not get matches: %s", exc)
            return

        finished_ids = {m.id for m in all_matches if m.status == "FINISHED"}

        # ── seed on first run ─────────────────────────────────────────────────
        if "finished_seen" not in context.bot_data:
            context.bot_data["finished_seen"] = set(finished_ids)
            log.info(
                "poll_finished_matches_job: seeded %d already-finished matches (no sends)",
                len(finished_ids),
            )
            return

        finished_seen: set = context.bot_data["finished_seen"]
        new_ids = finished_ids - finished_seen

        if not new_ids:
            return

        matches_by_id = {m.id: m for m in all_matches}
        live_path = f"{settings.state_dir}/porra_live.json"

        for match_id in new_ids:
            try:
                match = matches_by_id.get(match_id)
                if match is None:
                    finished_seen.add(match_id)
                    continue

                stats_text: str | None = None
                commentary_text: str | None = None

                # ── Part A: ESPN stats card ───────────────────────────────────
                try:
                    game_id = await asyncio.to_thread(
                        scanner.get_espn_game_id, match.home_name, match.away_name
                    )
                    if game_id:
                        stats = await asyncio.to_thread(espn_client.get_match_stats, game_id)
                        if stats:
                            stats_text = format_match_stats(match, stats)
                            log.info(
                                "Fetched ESPN stats for match %d (%s vs %s)",
                                match_id,
                                match.home_name,
                                match.away_name,
                            )
                        else:
                            log.info(
                                "No ESPN stats for match %d (game_id=%s)", match_id, game_id
                            )
                    else:
                        log.info(
                            "No ESPN game_id found for match %d (%s vs %s)",
                            match_id,
                            match.home_name,
                            match.away_name,
                        )
                except Exception as exc:
                    log.error("Part A failed for match %d: %s", match_id, exc)

                # ── Part B: porra ranking diff + AI commentary ────────────────
                try:
                    predictions = pred_loader.load(settings.predictions_path)
                    ranking = compute_general_ranking(predictions, client, official=False)
                    participant_names = [e.display_name for e in ranking]
                    new_state = build_state(ranking)
                    old_state = load_live(live_path)
                    live_diff = diff_live(old_state, new_state)

                    if live_diff.changed and ai_enabled(settings):
                        ai = AIClient(
                            settings.openai_api_key,
                            settings.openai_base_url,
                            settings.openai_model,
                        )
                        persona = pick_commentator()
                        changes_text = render_changes_text(live_diff)
                        raw_commentary = await generate_porra_commentary(ai, persona, changes_text)
                        commentary_text = bold_person_names(raw_commentary, participant_names)
                        log.info(
                            "Generated porra commentary (%s) for match %d", persona, match_id
                        )

                    save_live(live_path, new_state)

                except Exception as exc:
                    log.error("Part B failed for match %d: %s", match_id, exc)

                # ── Combine and send ONE message ──────────────────────────────
                if stats_text and commentary_text:
                    combined = stats_text + "\n\n----\n\n" + commentary_text
                elif stats_text:
                    combined = stats_text
                elif commentary_text:
                    combined = commentary_text
                else:
                    combined = None

                if combined:
                    await context.bot.send_message(
                        chat_id=settings.telegram_group_id,
                        text=combined,
                        parse_mode="HTML",
                    )
                    log.info(
                        "Sent match-finish message for match %d (%s vs %s)",
                        match_id,
                        match.home_name,
                        match.away_name,
                    )

            except Exception as exc:
                log.error("poll_finished_matches_job: error processing match %d: %s", match_id, exc)
            finally:
                finished_seen.add(match_id)

        context.bot_data["finished_seen"] = finished_seen

    except Exception as exc:
        log.exception("poll_finished_matches_job: unexpected error: %s", exc)


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
    # finished-match tracker: seeded on first poll_finished_matches_job run
    app.bot_data["espn_client"] = None

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

    if settings.telegram_group_id:
        app.job_queue.run_repeating(
            poll_finished_matches_job,
            interval=settings.finished_poll_interval_seconds,
            first=15,
            name="poll_finished_matches",
        )
        log.info(
            "Finished-match notifier enabled — polling every %ds for group %s",
            settings.finished_poll_interval_seconds,
            settings.telegram_group_id,
        )

    app.run_polling()


if __name__ == "__main__":
    main()
