"""Entry point: python -m worldcup_bot

Builds the Telegram Application, registers all handlers, starts polling.
"""

from __future__ import annotations

import asyncio
import html
import logging
import shutil
import sys
from datetime import datetime, time as dtime
from pathlib import Path

import pytz
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.commentators import generate_porra_commentary, pick_commentator
from worldcup_bot.ai.daily_update import generate_daily_update
from worldcup_bot.ai.goal_extractor import extract_scorer
from worldcup_bot.api.client import FootballAPIError
from worldcup_bot.bot.formatters import bold_person_names, team_flag
from worldcup_bot.bot.handlers import (
    cmd_actual,
    cmd_ayer,
    cmd_clasificacion,
    cmd_en_directo,
    cmd_estadisticas,
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
from worldcup_bot.porra.live import build_state, diff_live, load_live, render_porra_context, save_live
from worldcup_bot.reddit.notifier import (
    _is_silent_hour,
    build_goal_keyboard,
    format_disallowed_message,
    format_new_goal_message,
)
from worldcup_bot.reddit.parser import parse_goal_events
from worldcup_bot.reddit.scanner import RedditMatchScanner, _teams_match
from worldcup_bot.reddit.score_state import GoalDelta, diff_scores, load_scores, save_scores
from worldcup_bot.reddit.clip_finder import find_goal_clip
from worldcup_bot.reddit.clip_store import (
    add_entry as _cs_add_entry,
    goal_token as _cs_goal_token,
    load_clips,
    prune_old_entries,
    save_clips,
)
from worldcup_bot.reddit.downloader import MediaDownloader
from worldcup_bot.reddit.video import VideoTooLargeError, compress_if_needed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# Max search attempts before giving up on a clip (~18 min at 45s interval)
_MAX_CLIP_ATTEMPTS = 25


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


async def _enrich_scorer(
    delta: GoalDelta,
    match,
    scanner: RedditMatchScanner,
    settings: Settings,
) -> tuple[str | None, str | None]:
    """Try to find scorer + minute via Reddit thread → OpenAI → parse_goal_events.

    Returns (scorer | None, minute | None). Never raises.
    """
    try:
        permalink = await asyncio.to_thread(
            scanner.find_match_thread, match.home_name, match.away_name
        )
        if permalink is None:
            log.info(
                "_enrich_scorer: no Reddit thread for %s vs %s",
                match.home_name, match.away_name,
            )
            return None, None

        thread_text = await asyncio.to_thread(scanner.get_thread_body, permalink)
        if not thread_text:
            return None, None

        if ai_enabled(settings):
            ai = AIClient(
                settings.openai_api_key,
                settings.openai_base_url,
                settings.openai_model,
            )
            scorer, minute = await extract_scorer(
                ai=ai,
                thread_text=thread_text,
                scoring_team=delta.scoring_team,
                home_team=match.home_name,
                away_team=match.away_name,
                new_home=delta.new_home,
                new_away=delta.new_away,
            )
            if scorer:
                return scorer, minute

        # Fallback: parse_goal_events — find the most recent goal for the scoring team
        events = parse_goal_events(thread_text)
        for event in reversed(events):
            if (
                event.home_score == delta.new_home
                and event.away_score == delta.new_away
                and _teams_match(event.scoring_team, delta.scoring_team)
            ):
                return event.scorer, event.minute_text

        return None, None

    except Exception as exc:
        log.warning(
            "_enrich_scorer failed for %s vs %s: %s",
            match.home_name, match.away_name, exc,
        )
        return None, None


async def _process_goal_delta(
    delta: GoalDelta,
    match,
    scanner: RedditMatchScanner,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    silent: bool,
) -> None:
    """Send a goal or disallowed notification for a single score-change delta."""
    if delta.kind == "disallowed":
        text = format_disallowed_message(
            home_name=match.home_name,
            away_name=match.away_name,
            home_score=delta.new_home,
            away_score=delta.new_away,
            home_tla=match.home_tla,
            away_tla=match.away_tla,
        )
        await context.bot.send_message(
            chat_id=settings.telegram_group_id,
            text=text,
            parse_mode="HTML",
            disable_notification=silent,
        )
        log.info(
            "Disallowed goal sent: %s vs %s (%d-%d)",
            match.home_name, match.away_name, delta.new_home, delta.new_away,
        )
        return

    scorer, minute = await _enrich_scorer(delta, match, scanner, settings)

    text = format_new_goal_message(
        scoring_team=delta.scoring_team,
        home_name=match.home_name,
        away_name=match.away_name,
        home_score=delta.new_home,
        away_score=delta.new_away,
        home_tla=match.home_tla,
        away_tla=match.away_tla,
        scorer=scorer,
        minute=minute,
    )
    sent = await context.bot.send_message(
        chat_id=settings.telegram_group_id,
        text=text,
        parse_mode="HTML",
        disable_notification=silent,
    )
    log.info(
        "Goal notification sent: %s vs %s (%d-%d) scorer=%s minute=%s",
        match.home_name, match.away_name, delta.new_home, delta.new_away,
        scorer, minute,
    )

    # Record a clip-store entry so poll_goal_clips_job can search in the background
    clips_path = f"{settings.state_dir}/goal_clips.json"
    clip_data: dict = context.bot_data.setdefault("clip_store", {})
    token_key = f"{match.id}:{delta.scoring_team}:{delta.new_home}-{delta.new_away}"
    tok = _cs_goal_token(token_key)
    _cs_add_entry(
        clip_data,
        token=tok,
        chat_id=settings.telegram_group_id,
        message_id=sent.message_id,
        home_name=match.home_name,
        away_name=match.away_name,
        home_tla=match.home_tla,
        away_tla=match.away_tla,
        home_score=delta.new_home,
        away_score=delta.new_away,
        scoring_team=delta.scoring_team,
        scorer=scorer,
        minute=minute,
    )
    save_clips(clips_path, clip_data)
    log.debug("Clip-store entry created: token=%s key=%s", tok, token_key)


# ── polling job ───────────────────────────────────────────────────────────────


async def poll_goals_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: detect new goals via football-data score changes.

    Detection strategy (score-based, block 1):
    1. Load persistent score state from live_scores.json.
    2. Get all matches from football-data.org (cached).
    3. Relevant matches: IN_PLAY / PAUSED, OR FINISHED that we were tracking.
    4. First-seen match → SEED (store current score, notify nothing).
    5. Subsequent tick: diff against stored score.
       Score increase → goal notification (enrich via Reddit + OpenAI/parse fallback).
       Score decrease → disallowed-goal notification.
    6. Persist updated state.

    Night-silent: 00:00–08:59 local → disable_notification=True (still sends).
    """
    try:
        settings: Settings = context.bot_data["settings"]
        state_path = f"{settings.state_dir}/live_scores.json"

        scores: dict = load_scores(state_path)

        if context.bot_data.get("reddit_scanner") is None:
            context.bot_data["reddit_scanner"] = RedditMatchScanner(
                user_agent=settings.reddit_user_agent
            )
        scanner: RedditMatchScanner = context.bot_data["reddit_scanner"]

        client = make_client(settings)
        try:
            all_matches = client.get_all_matches()
        except FootballAPIError as exc:
            log.warning("poll_goals_job: could not get matches: %s", exc)
            return

        # IN_PLAY/PAUSED are live; FINISHED matches already in state catch final goals + FT
        relevant = [
            m for m in all_matches
            if m.status in ("IN_PLAY", "PAUSED")
            or (m.status == "FINISHED" and str(m.id) in scores)
        ]

        if not relevant:
            return

        local_tz = pytz.timezone(settings.timezone)
        now_local = datetime.now(local_tz)
        silent = _is_silent_hour(now_local)

        changed = False

        for match in relevant:
            match_key = str(match.id)
            stored = scores.get(match_key)

            deltas = diff_scores(stored, match)

            if stored is None:
                log.info(
                    "poll_goals_job: seeding match %d (%s vs %s) at %d-%d",
                    match.id, match.home_name, match.away_name,
                    match.home_score or 0, match.away_score or 0,
                )
                scores[match_key] = {
                    "home": match.home_score or 0,
                    "away": match.away_score or 0,
                    "status": match.status,
                }
                changed = True
                continue

            if not deltas:
                if scores[match_key].get("status") != match.status:
                    scores[match_key]["status"] = match.status
                    changed = True
                continue

            for delta in deltas:
                try:
                    await _process_goal_delta(
                        delta, match, scanner, settings, context, silent
                    )
                except Exception as exc:
                    log.error(
                        "poll_goals_job: error processing delta for match %d: %s",
                        match.id, exc,
                    )

            scores[match_key] = {
                "home": match.home_score or 0,
                "away": match.away_score or 0,
                "status": match.status,
            }
            changed = True

        if changed:
            save_scores(state_path, scores)

    except Exception as exc:
        log.exception("poll_goals_job: unexpected error (will retry next tick): %s", exc)


# ── background clip-search job ────────────────────────────────────────────────


async def poll_goal_clips_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: search Reddit for goal clips and edit goal messages once found.

    For every clip-store entry with status='searching':
    1. Increment attempts.  If > _MAX_CLIP_ATTEMPTS → mark 'timeout', give up.
    2. Call find_goal_clip (sync, via asyncio.to_thread).  None → persist attempts,
       continue.
    3. Found: download, compress if needed, move to persistent clips volume, then
       edit the original goal message to add the 'Ver gol' inline keyboard.
    4. Any per-entry exception is caught so one failure cannot disrupt others.
    5. Prune entries/files older than 7 days each tick.
    """
    try:
        settings: Settings = context.bot_data["settings"]
        clips_path = f"{settings.state_dir}/goal_clips.json"
        clips_dir = Path(settings.state_dir) / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)

        # Use the authoritative in-memory state; fall back to disk only if absent
        clip_data: dict = context.bot_data.setdefault(
            "clip_store", load_clips(clips_path)
        )

        if context.bot_data.get("reddit_scanner") is None:
            context.bot_data["reddit_scanner"] = RedditMatchScanner(
                user_agent=settings.reddit_user_agent
            )
        scanner: RedditMatchScanner = context.bot_data["reddit_scanner"]

        # Prune old entries / clip files each tick
        prune_old_entries(clip_data, clips_dir)

        searching = {
            tok: entry
            for tok, entry in clip_data.items()
            if entry.get("status") == "searching"
        }
        if not searching:
            return

        changed = False

        for token, entry in searching.items():
            try:
                entry["attempts"] = entry.get("attempts", 0) + 1
                changed = True

                if entry["attempts"] > _MAX_CLIP_ATTEMPTS:
                    entry["status"] = "timeout"
                    log.info(
                        "poll_goal_clips_job: token %s timed out after %d attempts",
                        token,
                        entry["attempts"],
                    )
                    continue

                # Parse minute string ("45+2" → 45, None → 0)
                minute_str = entry.get("minute") or "0"
                try:
                    minute = int(str(minute_str).split("+")[0].rstrip("'"))
                except (ValueError, IndexError):
                    minute = 0
                scorer = entry.get("scorer") or ""

                media_url: str | None = await asyncio.to_thread(
                    find_goal_clip,
                    scanner,
                    entry["home_name"],
                    entry["away_name"],
                    entry["home_score"],
                    entry["away_score"],
                    scorer,
                    minute,
                )

                if media_url is None:
                    log.debug(
                        "poll_goal_clips_job: no clip yet for token %s (attempt %d)",
                        token,
                        entry["attempts"],
                    )
                    continue

                # Download to temp path
                downloader = MediaDownloader()
                temp_path = await downloader.download(media_url)
                if temp_path is None:
                    log.warning(
                        "poll_goal_clips_job: download returned None for token %s", token
                    )
                    continue

                try:
                    # Compress in temp dir if over 50 MB
                    send_path = await compress_if_needed(temp_path)

                    # Move to persistent clips volume
                    persistent_path = clips_dir / f"{token}.mp4"
                    if persistent_path.exists():
                        persistent_path.unlink()
                    shutil.move(str(send_path), str(persistent_path))

                    # Edit the original goal message to add the 'Ver gol' keyboard
                    try:
                        await context.bot.edit_message_reply_markup(
                            chat_id=entry["chat_id"],
                            message_id=entry["message_id"],
                            reply_markup=build_goal_keyboard(token),
                        )
                    except Exception as edit_exc:
                        log.warning(
                            "poll_goal_clips_job: could not edit message for token %s: %s",
                            token,
                            edit_exc,
                        )

                    entry["status"] = "ready"
                    entry["clip_path"] = str(persistent_path)
                    log.info(
                        "poll_goal_clips_job: clip ready for token %s → %s",
                        token,
                        persistent_path,
                    )

                except VideoTooLargeError as exc:
                    log.warning(
                        "poll_goal_clips_job: clip too large for token %s: %s", token, exc
                    )
                    entry["status"] = "timeout"

                finally:
                    # Clean up any temp file that was not moved
                    try:
                        if temp_path.exists():
                            temp_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            except Exception as exc:
                log.exception(
                    "poll_goal_clips_job: error processing token %s: %s", token, exc
                )

        if changed:
            save_clips(clips_path, clip_data)

    except Exception as exc:
        log.exception("poll_goal_clips_job: unexpected error: %s", exc)


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

                    if ai_enabled(settings) and bool(ranking):
                        ai = AIClient(
                            settings.openai_api_key,
                            settings.openai_base_url,
                            settings.openai_model,
                        )
                        persona = pick_commentator()
                        context_text = render_porra_context(live_diff, ranking)
                        raw_commentary = await generate_porra_commentary(ai, persona, context_text)
                        commentary_text = bold_person_names(raw_commentary, participant_names)
                        log.info(
                            "Generated porra commentary (%s) for match %d", persona, match_id
                        )

                    save_live(live_path, new_state)

                except Exception as exc:
                    log.error("Part B failed for match %d: %s", match_id, exc)

                # ── Section 1 (always): final result ─────────────────────────
                h_flag = team_flag(match.home_tla)
                a_flag = team_flag(match.away_tla)
                hs = match.home_score if match.home_score is not None else 0
                as_ = match.away_score if match.away_score is not None else 0
                h_name = html.escape(match.home_name, quote=False)
                a_name = html.escape(match.away_name, quote=False)
                if match.winner == "HOME_TEAM":
                    h_name = f"<b>{h_name}</b>"
                elif match.winner == "AWAY_TEAM":
                    a_name = f"<b>{a_name}</b>"
                result_section = (
                    f"🏁 <b>Final</b>\n"
                    f"{h_flag} {h_name} {hs}-{as_} {a_name} {a_flag}"
                )

                # ── Assemble sections and always send ─────────────────────────
                sections: list[str] = [result_section]
                if stats_text:
                    sections.append(stats_text)
                if commentary_text:
                    sections.append(commentary_text)
                combined = "\n\n---\n\n".join(sections)

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
    app.bot_data["reddit_scanner"] = None
    # Load persistent clip-store from disk (restart resilience: 'ready' entries
    # keep working, 'searching' entries resume in poll_goal_clips_job)
    clips_path = f"{settings.state_dir}/goal_clips.json"
    app.bot_data["clip_store"] = load_clips(clips_path)
    # In-flight lock set — tokens currently being processed by cmd_ver_gol_callback
    app.bot_data["vergol_inflight"] = set()
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
        CommandHandler("estadisticas", cmd_estadisticas),
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
        "Goal notifier enabled (score-based) — polling football-data every %ds for group %s",
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

        app.job_queue.run_repeating(
            poll_goal_clips_job,
            interval=45,
            first=20,
            name="poll_goal_clips",
        )
        log.info(
            "Goal-clip searcher enabled — polling every 45s for group %s",
            settings.telegram_group_id,
        )

    app.run_polling()


if __name__ == "__main__":
    main()
