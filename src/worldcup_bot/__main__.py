"""Entry point: python -m worldcup_bot

Builds the Telegram Application, registers all handlers, starts polling.
"""

from __future__ import annotations

import asyncio
import html
import logging
import shutil
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

import pytz
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.commentators import generate_porra_commentary, pick_commentator
from worldcup_bot.ai.daily_update import generate_daily_update
from worldcup_bot.ai.goal_extractor import extract_scorer
from worldcup_bot.ai.rich_image import run_rich_iteration
from worldcup_bot.api.client import FootballAPIError
from worldcup_bot.bot.formatters import bold_person_names, team_flag
from worldcup_bot.bot.handlers import (
    cmd_actual,
    cmd_ayer,
    cmd_clasificacion,
    cmd_endirecto_callback,
    cmd_en_directo,
    cmd_estadisticas,
    cmd_evolucion,
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
from worldcup_bot.config import Settings, ai_enabled, image_ai_enabled, load_settings
from worldcup_bot.espn.client import ESPNClient
from worldcup_bot.espn.formatter import format_match_stats
from worldcup_bot.porra import predictions as pred_loader
from worldcup_bot.porra.engine import compute_general_ranking
from worldcup_bot.porra.history import ensure_history
from worldcup_bot.porra.live import build_state, diff_live, load_live, render_porra_context, save_live
from worldcup_bot.reddit.notifier import (
    _is_silent_hour,
    build_goal_keyboard,
    format_disallowed_message,
    format_new_goal_message,
)
from worldcup_bot.reddit.parser import parse_goal_events
from worldcup_bot.reddit.scanner import RedditMatchScanner, _teams_match
from worldcup_bot.reddit.score_state import GoalDelta, diff_scores, load_scores, reconcile, save_scores
from worldcup_bot.reddit.finished_state import load_finished, save_finished
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

# A football match (including ET + penalties) never exceeds ~3 h; 4 h is a safe
# ceiling for "this match is definitely over regardless of football-data status".
MATCH_OVER_AGE = timedelta(hours=4)


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


# ── porra history backfill job ────────────────────────────────────────────────


async def history_backfill_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """One-shot / daily job: build per-jornada porra history into the state volume.

    Runs at startup (≈15s after launch) and once daily at 09:05 local time so
    newly-completed jornadas are captured automatically.  Never raises — any
    error is logged and swallowed so it cannot affect other jobs.
    """
    try:
        settings: Settings = context.bot_data["settings"]
        predictions = pred_loader.load(settings.predictions_path)
        if not predictions.get("participants"):
            log.info("history_backfill_job: no predictions loaded, skipping")
            return
        client = make_client(settings)
        history_path = f"{settings.state_dir}/porra_history.json"
        history = await asyncio.to_thread(
            ensure_history, client, predictions, settings, history_path
        )
        log.info(
            "history_backfill_job: porra history has %d jornadas", len(history)
        )
    except Exception:
        log.exception("history_backfill_job: error (non-fatal)")


# ── daily rich-image evolution job ───────────────────────────────────────────


async def rich_image_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily job: evolve the 'rich' image one wealth level and optionally send it."""
    settings: Settings = context.bot_data["settings"]
    if not image_ai_enabled(settings):
        log.info("rich_image_job: image AI not configured, skipping")
        return
    try:
        out_path, level, caption = await run_rich_iteration(settings)
        log.info("rich image iteration %d -> %s", level, out_path)
        if settings.telegram_group_id:
            with open(out_path, "rb") as photo_fh:
                await context.bot.send_photo(
                    chat_id=settings.telegram_group_id,
                    photo=photo_fh,
                    caption=caption,
                )
    except Exception:
        log.exception("rich_image_job: error (non-fatal)")


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


async def _notify_goal(
    match,
    new_home: int,
    new_away: int,
    scoring_team: str,
    scorer: str | None,
    minute: str | None,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    silent: bool,
) -> None:
    """Send a goal notification and register a clip-store entry.

    Shared by both the football-data poll path and the thread-based early-detection
    path.  Takes scorer/minute as explicit params so callers can supply their own
    source (e.g. the thread event's scorer, or the OpenAI-enriched scorer).
    """
    text = format_new_goal_message(
        scoring_team=scoring_team,
        home_name=match.home_name,
        away_name=match.away_name,
        home_score=new_home,
        away_score=new_away,
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
        match.home_name, match.away_name, new_home, new_away, scorer, minute,
    )

    # Register a clip-store entry so poll_goal_clips_job can search in the background
    clips_path = f"{settings.state_dir}/goal_clips.json"
    clip_data: dict = context.bot_data.setdefault("clip_store", {})
    token_key = f"{match.id}:{scoring_team}:{new_home}-{new_away}"
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
        home_score=new_home,
        away_score=new_away,
        scoring_team=scoring_team,
        scorer=scorer,
        minute=minute,
    )
    save_clips(clips_path, clip_data)
    log.debug("Clip-store entry created: token=%s key=%s", tok, token_key)


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
    await _notify_goal(
        match=match,
        new_home=delta.new_home,
        new_away=delta.new_away,
        scoring_team=delta.scoring_team,
        scorer=scorer,
        minute=minute,
        settings=settings,
        context=context,
        silent=silent,
    )


# ── polling job ───────────────────────────────────────────────────────────────


async def poll_goals_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: detect new goals via football-data score changes.

    Uses reconcile() with per-source "seen" so that a lagging source's catch-up
    never produces a false disallowed, and only the first source to detect a score
    change announces it.
    """
    try:
        settings: Settings = context.bot_data["settings"]
        state_path = f"{settings.state_dir}/live_scores.json"

        # Shared announced state — persisted across restarts.
        scores: dict = context.bot_data.setdefault("live_scores", load_scores(state_path))

        # Per-source seen — in-memory only (rebuilt by re-seeding on restart).
        seen_scores = context.bot_data.setdefault("seen_scores", {"api": {}, "thread": {}})
        seen_api: dict = seen_scores["api"]

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
            curr_home = int(match.home_score) if match.home_score is not None else 0
            curr_away = int(match.away_score) if match.away_score is not None else 0

            stored = scores.get(match_key)
            ann_homeaway = (
                {"home": int(stored["home"]), "away": int(stored["away"])}
                if stored is not None else None
            )

            source_seen = seen_api.get(match_key)
            deltas, new_seen, new_ann = reconcile(source_seen, ann_homeaway, curr_home, curr_away)

            # Always advance this source's seen baseline.
            seen_api[match_key] = new_seen

            if stored is None:
                # First-seen by any source: seed live_scores entry.
                log.info(
                    "poll_goals_job: seeding match %d (%s vs %s) at %d-%d",
                    match.id, match.home_name, match.away_name,
                    new_ann["home"], new_ann["away"],
                )
                scores[match_key] = {
                    "home": new_ann["home"],
                    "away": new_ann["away"],
                    "status": match.status,
                }
                changed = True
                continue

            if not deltas:
                # No goals/disallowed to announce, but status or lag-resolved score may change.
                announced_changed = (
                    new_ann["home"] != stored["home"] or new_ann["away"] != stored["away"]
                )
                status_changed = stored.get("status") != match.status
                if announced_changed or status_changed:
                    scores[match_key]["home"] = new_ann["home"]
                    scores[match_key]["away"] = new_ann["away"]
                    scores[match_key]["status"] = match.status
                    changed = True
                continue

            # Process deltas — fill in scoring_team before passing to handler.
            for delta in deltas:
                delta.scoring_team = (
                    match.home_name if delta.side == "home" else match.away_name
                )
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
                "home": new_ann["home"],
                "away": new_ann["away"],
                "status": match.status,
            }
            changed = True

        if changed:
            save_scores(state_path, scores)

    except Exception as exc:
        log.exception("poll_goals_job: unexpected error (will retry next tick): %s", exc)


# ── thread-based early goal detection job ─────────────────────────────────────


async def poll_thread_goals_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: detect goals from Reddit match thread BEFORE football-data reports them.

    Runs every 25 seconds.  Uses reconcile() with a per-source "thread" seen so that:
    - The thread's early detection works correctly when it's ahead of football-data.
    - A lagging football-data report never causes a false "disallowed" because the thread
      was already ahead.
    - A REAL VAR (thread's own score drops) triggers a disallowed message.
    - Thread scorer is taken directly from the GoalEvent — no OpenAI call needed.

    Only processes matches already seeded in live_scores by poll_goals_job (avoids
    replaying historical goals on startup).
    """
    try:
        settings: Settings = context.bot_data["settings"]
        state_path = f"{settings.state_dir}/live_scores.json"

        # Shared announced state.
        scores: dict = context.bot_data["live_scores"]

        # Per-source thread seen — in-memory only.
        seen_scores = context.bot_data.setdefault("seen_scores", {"api": {}, "thread": {}})
        seen_thread: dict = seen_scores["thread"]

        if context.bot_data.get("reddit_scanner") is None:
            context.bot_data["reddit_scanner"] = RedditMatchScanner(
                user_agent=settings.reddit_user_agent
            )
        scanner: RedditMatchScanner = context.bot_data["reddit_scanner"]

        client = make_client(settings)
        try:
            live_matches = client.get_live_matches()
        except FootballAPIError as exc:
            log.warning("poll_thread_goals_job: could not get live matches: %s", exc)
            return

        if not live_matches:
            return

        local_tz = pytz.timezone(settings.timezone)
        now_local = datetime.now(local_tz)
        silent = _is_silent_hour(now_local)

        try:
            results = await asyncio.to_thread(scanner.scan_live_matches, live_matches)
        except Exception as exc:
            log.exception("poll_thread_goals_job: scan_live_matches failed: %s", exc)
            return

        match_by_tla: dict[tuple[str, str], object] = {
            (m.home_tla, m.away_tla): m for m in live_matches
        }

        changed = False

        for result in results:
            try:
                match = match_by_tla.get((result.home_tla, result.away_tla))
                if match is None:
                    log.debug(
                        "poll_thread_goals_job: no match found for TLAs %s vs %s",
                        result.home_tla, result.away_tla,
                    )
                    continue

                key = str(match.id)

                # Only process matches already seeded by poll_goals_job.
                stored = scores.get(key)
                if stored is None:
                    log.debug(
                        "poll_thread_goals_job: match %d not yet seeded, skipping", match.id
                    )
                    continue

                events = result.events
                if not events:
                    continue

                thread_home = max((e.home_score for e in events), default=0)
                thread_away = max((e.away_score for e in events), default=0)

                ann_homeaway = {
                    "home": int(stored["home"]),
                    "away": int(stored["away"]),
                }
                source_seen = seen_thread.get(key)

                deltas, new_seen, new_ann = reconcile(
                    source_seen, ann_homeaway, thread_home, thread_away
                )

                # Always advance this source's seen baseline.
                seen_thread[key] = new_seen

                if not deltas:
                    # Lag catch-up may update new_ann (stays equal to ann in lag branch),
                    # so no live_scores change needed.
                    continue

                sorted_events = sorted(events, key=lambda e: e.minute_sort)

                goals_to_notify: list[dict] = []

                # Build per-goal notifications using intermediate target scores so each
                # notification shows the correct running score (e.g. 3-2, then 4-2).
                if new_ann["home"] > ann_homeaway["home"]:
                    for target in range(ann_homeaway["home"] + 1, new_ann["home"] + 1):
                        event = next(
                            (
                                e for e in sorted_events
                                if e.home_score == target
                                and _teams_match(e.scoring_team, match.home_name)
                            ),
                            None,
                        )
                        goals_to_notify.append({
                            "scoring_team": match.home_name,
                            "new_home": target,
                            "new_away": event.away_score if event else ann_homeaway["away"],
                            "scorer": event.scorer if event else None,
                            "minute": event.minute_text if event else None,
                            "minute_sort": event.minute_sort if event else float("inf"),
                        })

                if new_ann["away"] > ann_homeaway["away"]:
                    for target in range(ann_homeaway["away"] + 1, new_ann["away"] + 1):
                        event = next(
                            (
                                e for e in sorted_events
                                if e.away_score == target
                                and _teams_match(e.scoring_team, match.away_name)
                            ),
                            None,
                        )
                        goals_to_notify.append({
                            "scoring_team": match.away_name,
                            "new_home": event.home_score if event else ann_homeaway["home"],
                            "new_away": target,
                            "scorer": event.scorer if event else None,
                            "minute": event.minute_text if event else None,
                            "minute_sort": event.minute_sort if event else float("inf"),
                        })

                goals_to_notify.sort(key=lambda g: g["minute_sort"])

                for g in goals_to_notify:
                    try:
                        await _notify_goal(
                            match=match,
                            new_home=g["new_home"],
                            new_away=g["new_away"],
                            scoring_team=g["scoring_team"],
                            scorer=g["scorer"] or None,
                            minute=g["minute"],
                            settings=settings,
                            context=context,
                            silent=silent,
                        )
                    except Exception as exc:
                        log.error(
                            "poll_thread_goals_job: _notify_goal failed for match %d: %s",
                            match.id, exc,
                        )

                # Handle disallowed deltas (thread's own score dropped = real VAR).
                for delta in (d for d in deltas if d.kind == "disallowed"):
                    try:
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
                            "poll_thread_goals_job: thread-VAR disallowed for match %d (%s vs %s)",
                            match.id, match.home_name, match.away_name,
                        )
                    except Exception as exc:
                        log.error(
                            "poll_thread_goals_job: disallowed notification failed for match %d: %s",
                            match.id, exc,
                        )

                # Update shared announced score.
                scores[key]["home"] = new_ann["home"]
                scores[key]["away"] = new_ann["away"]
                changed = True

                log.info(
                    "poll_thread_goals_job: match %d (%s vs %s) thread score %d-%d "
                    "(was %d-%d), %d goal(s) + %d disallowed notified",
                    match.id, match.home_name, match.away_name,
                    thread_home, thread_away,
                    ann_homeaway["home"], ann_homeaway["away"],
                    len(goals_to_notify),
                    sum(1 for d in deltas if d.kind == "disallowed"),
                )

            except Exception as exc:
                log.exception(
                    "poll_thread_goals_job: error for match %s vs %s: %s",
                    result.home_tla, result.away_tla, exc,
                )

        if changed:
            save_scores(state_path, scores)

    except Exception as exc:
        log.exception("poll_thread_goals_job: unexpected error (will retry next tick): %s", exc)





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

    Dedup strategy (persistent + age-aware):
    - `finished_announced` (bot_data + disk): set of match ids already recapped or
      seeded as already-handled.  Loaded from `{state_dir}/finished_announced.json` at
      startup; persisted after every change so restarts are safe.
    - FIRST RUN (gate: `finished_seeded` flag): seed every match that is "definitely
      over already" — FINISHED status OR kickoff older than MATCH_OVER_AGE (4 h).
      This catches stale IN_PLAY/PAUSED matches whose football-data status lags.
      Persist immediately and return (no sends).
    - SUBSEQUENT RUNS: for each match newly showing FINISHED whose id is NOT in
      `finished_announced`, send the recap (Part A ESPN stats + Part B porra
      commentary), then add the id and persist (one save per match so a crash
      mid-batch doesn't replay).
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

        announced: set = context.bot_data["finished_announced"]
        finished_path = f"{settings.state_dir}/finished_announced.json"

        # ── seed on first run ─────────────────────────────────────────────────
        if not context.bot_data.get("finished_seeded", False):
            now_utc = datetime.utcnow()
            seeded: set[int] = set()
            for m in all_matches:
                if m.status == "FINISHED":
                    seeded.add(m.id)
                else:
                    try:
                        kickoff = datetime.strptime(m.utc_date, "%Y-%m-%dT%H:%M:%SZ")
                        if now_utc - kickoff > MATCH_OVER_AGE:
                            seeded.add(m.id)
                    except Exception:
                        pass
            announced.update(seeded)
            save_finished(finished_path, announced)
            context.bot_data["finished_seeded"] = True
            log.info(
                "poll_finished_matches_job: seeded %d already-handled matches (no sends)",
                len(seeded),
            )
            return

        finished_ids = {m.id for m in all_matches if m.status == "FINISHED"}
        new_ids = finished_ids - announced

        if not new_ids:
            return

        matches_by_id = {m.id: m for m in all_matches}
        live_path = f"{settings.state_dir}/porra_live.json"

        for match_id in new_ids:
            try:
                match = matches_by_id.get(match_id)
                if match is None:
                    announced.add(match_id)
                    save_finished(finished_path, announced)
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
                announced.add(match_id)
                save_finished(finished_path, announced)

    except Exception as exc:
        log.exception("poll_finished_matches_job: unexpected error: %s", exc)


# ── app builder ───────────────────────────────────────────────────────────────


def build_app(settings: Settings) -> Application:
    from worldcup_bot.bot import formatters
    formatters.set_beloved_teams(settings.beloved_teams)

    app = Application.builder().token(settings.telegram_bot_token).build()

    # Store settings in bot_data for handler access
    app.bot_data["settings"] = settings
    app.bot_data["reddit_scanner"] = None
    # Pre-load live score state so both poll_goals_job and poll_thread_goals_job
    # share the same in-memory dict for race-free deduplication.
    state_path = f"{settings.state_dir}/live_scores.json"
    app.bot_data["live_scores"] = load_scores(state_path)
    # Per-source "seen" baselines — in-memory only, rebuilt by re-seeding on restart.
    # {"api": {match_id: {home, away}}, "thread": {match_id: {home, away}}}
    app.bot_data["seen_scores"] = {"api": {}, "thread": {}}
    # Load persistent clip-store from disk (restart resilience: 'ready' entries
    # keep working, 'searching' entries resume in poll_goal_clips_job)
    clips_path = f"{settings.state_dir}/goal_clips.json"
    app.bot_data["clip_store"] = load_clips(clips_path)
    # In-flight lock set — tokens currently being processed by cmd_ver_gol_callback
    app.bot_data["vergol_inflight"] = set()
    # finished-match tracker: persisted set of match ids already recapped or seeded
    # as already-handled.  Loaded from disk so restarts never re-fire old recaps.
    finished_path = f"{settings.state_dir}/finished_announced.json"
    app.bot_data["finished_announced"] = load_finished(finished_path)
    # False until first poll_finished_matches_job run completes its seed pass.
    app.bot_data["finished_seeded"] = False
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
        CommandHandler("evolucion", cmd_evolucion),
        CommandHandler("tongo", cmd_tongo),
        # New approved improvements
        CommandHandler("mispredicciones", cmd_mis_predicciones),
        CommandHandler("participantes", cmd_participantes),
        CommandHandler("estadisticas", cmd_estadisticas),
        # "Ver gol" inline button handler
        CallbackQueryHandler(cmd_ver_gol_callback, pattern=r"^vergol:"),
        CallbackQueryHandler(cmd_endirecto_callback, pattern=r"^ed\|"),
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

    app.job_queue.run_repeating(
        poll_thread_goals_job,
        interval=25,
        first=25,
        name="poll_thread_goals",
    )
    log.info(
        "Thread-based early goal detector enabled — polling Reddit every 25s for group %s",
        settings.telegram_group_id,
    )

    # Porra history: backfill at startup + refresh daily at 09:05 local time
    tz = pytz.timezone(settings.timezone)
    app.job_queue.run_once(
        history_backfill_job,
        when=15,
        name="history_backfill_startup",
    )
    app.job_queue.run_daily(
        history_backfill_job,
        time=dtime(hour=9, minute=5, tzinfo=tz),
        name="history_backfill_daily",
    )
    log.info(
        "Porra history refresh enabled — startup (15s) + daily 09:05 %s",
        settings.timezone,
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

    if image_ai_enabled(settings):
        app.job_queue.run_daily(
            rich_image_job,
            time=dtime(hour=settings.rich_image_hour, minute=0, tzinfo=tz),
            name="rich_image",
        )
        log.info(
            "Rich image evolution enabled — running daily at %02d:00 %s",
            settings.rich_image_hour,
            settings.timezone,
        )
    else:
        log.info(
            "Rich image evolution DISABLED — set OPENAI_IMAGE_API_KEY/OPENAI_IMAGE_BASE_URL "
            "(or OPENAI_API_KEY/OPENAI_BASE_URL) + OPENAI_IMAGE_MODEL to enable."
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
