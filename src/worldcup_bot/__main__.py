"""Entry point: python -m worldcup_bot

Builds the Telegram Application, registers all handlers, starts polling.
"""

from __future__ import annotations

import asyncio
import html
import logging
import shutil
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import pytz
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.commentators import generate_porra_commentary, pick_commentator
from worldcup_bot.ai.daily_update import generate_daily_update
from worldcup_bot.ai.goal_extractor import extract_scorer
from worldcup_bot.ai.rich_image import run_rich_iteration
from worldcup_bot.api.client import FootballAPIError
from worldcup_bot.bot.formatters import (
    bold_person_names,
    format_match_camps,
    format_match_start,
    team_flag,
)
from worldcup_bot.bot.handlers import (
    cmd_actual,
    cmd_ayer,
    cmd_clasificacion,
    cmd_endirecto_callback,
    cmd_endirecto_goal_callback,
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
    cmd_recalcular,
    cmd_tongocheck,
    cmd_ver_gol_callback,
    make_client,
)
from worldcup_bot.config import Settings, ai_enabled, image_ai_enabled, load_settings
from worldcup_bot.espn.client import ESPNClient
from worldcup_bot.espn.formatter import format_match_stats
from worldcup_bot.porra import predictions as pred_loader
from worldcup_bot.porra.camps import compute_match_camps
from worldcup_bot.porra.engine import compute_general_ranking
from worldcup_bot.porra.history import ensure_history
from worldcup_bot.porra.live import build_state, diff_live, load_live, render_porra_context, save_live
from worldcup_bot.reddit.notifier import (
    _is_silent_hour,
    build_goal_keyboard,
    format_catchup_message,
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


def _match_is_over(match, now_utc: datetime) -> bool:
    """True when the match kickoff was >MATCH_OVER_AGE (4 h) ago.

    Pure wall-clock guard: API status is deliberately ignored because
    football-data.org can stay stuck at IN_PLAY/PAUSED long after FT.
    ET + penalties comfortably fit inside 4 h, so this never cuts off a
    legitimately live match.  FINISHED matches within 4 h are NOT over by
    this predicate — they remain eligible for final-goal catch-up in the
    goal-polling jobs.
    """
    try:
        kickoff = datetime.strptime(match.utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        return now_utc - kickoff > MATCH_OVER_AGE
    except Exception:
        return False


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


async def _notify_catchup(
    match,
    new_home: int,
    new_away: int,
    goals_missed: int,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    silent: bool,
) -> None:
    """Send a neutral catch-up notification for goals missed during status-flip delay or restart.

    Sends ONE message that shows the current score and the number of missed goals,
    without attributing any goal to a specific team or showing fabricated scorelines.
    Registers a single clip-store entry keyed on the final score so the clip finder
    can locate any recent goal from this match and attach a "Ver gol" button later.
    """
    text = format_catchup_message(
        home_name=match.home_name,
        away_name=match.away_name,
        home_score=new_home,
        away_score=new_away,
        home_tla=match.home_tla,
        away_tla=match.away_tla,
        goals_missed=goals_missed,
    )
    sent = await context.bot.send_message(
        chat_id=settings.telegram_group_id,
        text=text,
        parse_mode="HTML",
        disable_notification=silent,
    )
    log.info(
        "Catch-up notification sent: %s vs %s (%d-%d) missed=%d",
        match.home_name, match.away_name, new_home, new_away, goals_missed,
    )

    clips_path = f"{settings.state_dir}/goal_clips.json"
    clip_data: dict = context.bot_data.setdefault("clip_store", {})
    token_key = f"{match.id}:catchup:{new_home}-{new_away}"
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
        scoring_team="",
        scorer=None,
        minute=None,
    )
    save_clips(clips_path, clip_data)
    log.debug("Clip-store catchup entry created: token=%s key=%s", tok, token_key)


async def _attempt_goal_recovery(
    match,
    curr_home: int,
    curr_away: int,
    prev_home: int,
    prev_away: int,
    goals_missed: int,
    scanner: RedditMatchScanner,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    silent: bool,
    seen_thread: dict,
    match_key: str,
) -> bool:
    """Attempt to recover per-goal events from the Reddit match thread.

    Called when the bot missed goals (first-seen at non-zero score OR restart-ahead).
    Looks up the match thread, parses goal events, and emits proper _notify_goal
    notifications (scorer + "Ver gol" keyboard) for each missed goal.

    Returns True if all missed goals were recovered and proper notifications sent.
    Returns False (fallback to neutral catch-up) when:
    - No thread found
    - Thread body empty or unparseable
    - Recovered event count != goals_missed
    - Any individual goal cannot be matched to a thread event
    """
    try:
        # Try cached /new/ listing first (no extra HTTP), then search fallback.
        permalink = await asyncio.to_thread(
            scanner.find_thread_permalink, match.home_name, match.away_name
        )
        if permalink is None:
            permalink = await asyncio.to_thread(
                scanner.find_match_thread, match.home_name, match.away_name
            )
        if permalink is None:
            log.info(
                "_attempt_goal_recovery: no thread for %s vs %s → neutral fallback",
                match.home_name, match.away_name,
            )
            return False

        selftext = await asyncio.to_thread(scanner.get_thread_body, permalink)
        if not selftext:
            log.info(
                "_attempt_goal_recovery: empty thread body for %s vs %s → neutral fallback",
                match.home_name, match.away_name,
            )
            return False

        events = parse_goal_events(selftext)
        if not events:
            log.info(
                "_attempt_goal_recovery: no events parsed for %s vs %s → neutral fallback",
                match.home_name, match.away_name,
            )
            return False

        sorted_events = sorted(events, key=lambda e: e.minute_sort)
        goals_to_notify: list[dict] = []

        for target in range(prev_home + 1, curr_home + 1):
            event = next(
                (
                    e for e in sorted_events
                    if e.home_score == target
                    and _teams_match(e.scoring_team, match.home_name)
                ),
                None,
            )
            if event is None:
                log.info(
                    "_attempt_goal_recovery: cannot match home goal %d for %s → neutral fallback",
                    target, match.home_name,
                )
                return False
            goals_to_notify.append({
                "scoring_team": match.home_name,
                "new_home": target,
                "new_away": event.away_score,
                "scorer": event.scorer or None,
                "minute": event.minute_text or None,
                "minute_sort": event.minute_sort,
            })

        for target in range(prev_away + 1, curr_away + 1):
            event = next(
                (
                    e for e in sorted_events
                    if e.away_score == target
                    and _teams_match(e.scoring_team, match.away_name)
                ),
                None,
            )
            if event is None:
                log.info(
                    "_attempt_goal_recovery: cannot match away goal %d for %s → neutral fallback",
                    target, match.away_name,
                )
                return False
            goals_to_notify.append({
                "scoring_team": match.away_name,
                "new_home": event.home_score,
                "new_away": target,
                "scorer": event.scorer or None,
                "minute": event.minute_text or None,
                "minute_sort": event.minute_sort,
            })

        if len(goals_to_notify) != goals_missed:
            log.info(
                "_attempt_goal_recovery: recovered %d goals but expected %d for %s vs %s → neutral fallback",
                len(goals_to_notify), goals_missed, match.home_name, match.away_name,
            )
            return False

        goals_to_notify.sort(key=lambda g: g["minute_sort"])

        for g in goals_to_notify:
            await _notify_goal(
                match=match,
                new_home=g["new_home"],
                new_away=g["new_away"],
                scoring_team=g["scoring_team"],
                scorer=g["scorer"],
                minute=g["minute"],
                settings=settings,
                context=context,
                silent=silent,
            )

        # Claim in seen_thread so poll_thread_goals_job won't re-announce these goals.
        seen_thread[match_key] = {"home": curr_home, "away": curr_away}
        log.info(
            "_attempt_goal_recovery: recovered %d goal(s) for %s vs %s via thread",
            goals_missed, match.home_name, match.away_name,
        )
        return True

    except Exception as exc:
        log.warning(
            "_attempt_goal_recovery: error for %s vs %s: %s → neutral fallback",
            match.home_name, match.away_name, exc,
        )
        return False



async def _backfill_scorer_in_clip_store(
    match,
    events: list,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Bug 2 fix: back-fill scorer onto an already-announced goal whose clip-store entry
    has scorer=None (happens when the API detected the goal before the thread reported
    the scorer — e.g. enrichment returned (None, None) due to 429 / thread lag).

    For each thread event that has a known scorer:
      1. Locate the clip-store entry by token key ``{match.id}:{team}:{h}-{w}``.
      2. If the entry exists and its scorer is None, update it and edit the original
         Telegram goal message to add the ``🎯 scorer (min')`` line.
      3. Save the updated clip-store so poll_goal_clips_job picks up the scorer
         and can find the clip.

    Idempotent: entry["scorer"] is only filled once (checked before every edit).
    Never raises — all failures are caught and logged.
    """
    try:
        clips_path = f"{settings.state_dir}/goal_clips.json"
        clip_data: dict = context.bot_data.setdefault("clip_store", load_clips(clips_path))

        filled: list[str] = []

        for event in events:
            if not event.scorer:
                continue

            # Use the canonical team name (same value _notify_goal stored in the token key).
            if _teams_match(event.scoring_team, match.home_name):
                scoring_team = match.home_name
            else:
                scoring_team = match.away_name

            token_key = f"{match.id}:{scoring_team}:{event.home_score}-{event.away_score}"
            tok = _cs_goal_token(token_key)
            entry = clip_data.get(tok)

            if entry is None or entry.get("scorer") is not None:
                continue  # no entry, or scorer already known — nothing to do

            # Update scorer (and minute if still unknown) so the clip search can proceed.
            entry["scorer"] = event.scorer
            if entry.get("minute") is None and event.minute_text:
                entry["minute"] = event.minute_text

            # Rebuild the goal message text with the now-known scorer and edit it.
            new_text = format_new_goal_message(
                scoring_team=scoring_team,
                home_name=match.home_name,
                away_name=match.away_name,
                home_score=entry["home_score"],
                away_score=entry["away_score"],
                home_tla=entry.get("home_tla", ""),
                away_tla=entry.get("away_tla", ""),
                scorer=event.scorer,
                minute=entry["minute"],
            )
            # Re-attach the "Ver gol" keyboard when the clip is already ready.
            # IMPORTANT: omit reply_markup entirely when not ready — passing None would
            # send reply_markup=null to Telegram which removes any existing keyboard.
            edit_kwargs: dict = {
                "chat_id": entry["chat_id"],
                "message_id": entry["message_id"],
                "text": new_text,
                "parse_mode": "HTML",
            }
            if entry.get("status") == "ready":
                edit_kwargs["reply_markup"] = build_goal_keyboard(tok)
            try:
                await context.bot.edit_message_text(**edit_kwargs)
                log.info(
                    "_backfill_scorer: edited message %d for %s vs %s (%d-%d) → scorer=%s%s",
                    entry["message_id"],
                    match.home_name, match.away_name,
                    entry["home_score"], entry["away_score"],
                    event.scorer,
                    " (keyboard preserved)" if entry.get("status") == "ready" else "",
                )
            except Exception as exc:
                log.warning(
                    "_backfill_scorer: could not edit message %d: %s",
                    entry.get("message_id"), exc,
                )
                # Scorer is still updated in the entry so the clip search can proceed.

            filled.append(tok)

        if filled:
            save_clips(clips_path, clip_data)
            log.info(
                "_backfill_scorer: filled scorer for %d goal(s) in %s vs %s",
                len(filled), match.home_name, match.away_name,
            )

    except Exception as exc:
        log.exception(
            "_backfill_scorer: unexpected error for %s vs %s: %s",
            match.home_name, match.away_name, exc,
        )


async def _process_goal_delta(
    delta: GoalDelta,
    match,
    scanner: RedditMatchScanner,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    silent: bool,
    seen_thread: dict | None = None,
    match_key: str | None = None,
) -> None:
    """Send a goal or disallowed notification for a single score-change delta."""
    if delta.kind == "catchup":
        if seen_thread is not None and match_key is not None:
            recovered = await _attempt_goal_recovery(
                match=match,
                curr_home=delta.new_home,
                curr_away=delta.new_away,
                prev_home=delta.prev_home,
                prev_away=delta.prev_away,
                goals_missed=delta.goals_missed,
                scanner=scanner,
                settings=settings,
                context=context,
                silent=silent,
                seen_thread=seen_thread,
                match_key=match_key,
            )
            if recovered:
                return
        await _notify_catchup(
            match=match,
            new_home=delta.new_home,
            new_away=delta.new_away,
            goals_missed=delta.goals_missed,
            settings=settings,
            context=context,
            silent=silent,
        )
        return
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

    Bug 1 fix: the "read announced → reconcile → claim new_ann" step is performed
    inside goal_lock so it is atomic across both poll jobs.  The slow enrichment
    + Telegram send happen OUTSIDE the lock; a concurrent job that acquires the
    lock afterwards sees the already-updated announced and reconcile returns no
    delta → no duplicate announcement.
    """
    try:
        settings: Settings = context.bot_data["settings"]
        state_path = f"{settings.state_dir}/live_scores.json"

        # Shared announced state — persisted across restarts.
        scores: dict = context.bot_data.setdefault("live_scores", load_scores(state_path))

        # Per-source seen — in-memory only (rebuilt by re-seeding on restart).
        seen_scores = context.bot_data.setdefault("seen_scores", {"api": {}, "thread": {}})
        seen_api: dict = seen_scores["api"]

        # Shared lock: both poll jobs use this to atomically claim score changes.
        goal_lock: asyncio.Lock = context.bot_data.setdefault("goal_lock", asyncio.Lock())

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

        now_utc = datetime.now(timezone.utc)

        # Evict over-matches (kickoff >MATCH_OVER_AGE ago) from shared state.
        # This self-heals stuck IN_PLAY entries (e.g. Egypt-Iran) so they can
        # never keep generating goal/disallowed spam on subsequent ticks.
        over_ids = {str(m.id) for m in all_matches if _match_is_over(m, now_utc)}
        pruned = [k for k in over_ids if k in scores]
        for k in pruned:
            log.info("poll_goals_job: pruning over-match key=%s from live state", k)
            scores.pop(k, None)
            seen_api.pop(k, None)
            seen_scores["thread"].pop(k, None)
        if pruned:
            save_scores(state_path, scores)

        # Evict POSTPONED/SUSPENDED matches that were seeded (e.g. by poll_kickoff_job
        # 0-0 seed).  The 4h wall-clock prune is backup; this handles status changes
        # within the 4h window so stale 0-0 entries don't persist indefinitely.
        postponed_evicted = [
            str(m.id) for m in all_matches
            if m.status in ("POSTPONED", "SUSPENDED") and str(m.id) in scores
        ]
        for k in postponed_evicted:
            m = next((x for x in all_matches if str(x.id) == k), None)
            log.warning(
                "poll_goals_job: match %s became %s — evicting seeded entry from live state",
                k, m.status if m else "POSTPONED/SUSPENDED",
            )
            scores.pop(k, None)
            seen_api.pop(k, None)
            seen_scores["thread"].pop(k, None)
        if postponed_evicted:
            save_scores(state_path, scores)

        # IN_PLAY/PAUSED are live; FINISHED matches already in state catch final goals + FT.
        # Hard-exclude any match whose kickoff was >MATCH_OVER_AGE ago.
        relevant = [
            m for m in all_matches
            if not _match_is_over(m, now_utc)
            and (
                m.status in ("IN_PLAY", "PAUSED")
                or (m.status == "FINISHED" and str(m.id) in scores)
            )
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

            # Deltas to process after the lock is released (slow sends must not hold it).
            deltas_to_process: list = []

            async with goal_lock:
                stored = scores.get(match_key)
                ann_homeaway = (
                    {"home": int(stored["home"]), "away": int(stored["away"])}
                    if stored is not None else None
                )

                source_seen = seen_api.get(match_key)
                deltas, new_seen, new_ann = reconcile(
                    source_seen, ann_homeaway, curr_home, curr_away
                )

                # Always advance this source's seen baseline.
                seen_api[match_key] = new_seen

                # Track whether this is already a FINISHED tick (for two-tick eviction).
                was_already_finished = (
                    stored is not None and stored.get("status") == "FINISHED"
                )

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
                    # If the API first reported IN_PLAY/PAUSED with a non-zero score
                    # (status-flip delay), earlier goals were never seen.  Attempt to
                    # recover proper per-goal notifications from the Reddit thread;
                    # fall back to a neutral catch-up if the thread is unavailable.
                    if curr_home > 0 or curr_away > 0:
                        log.info(
                            "poll_goals_job: match %d first seen at %d-%d — "
                            "will attempt recovery for %d missed goal(s)",
                            match.id, curr_home, curr_away, curr_home + curr_away,
                        )
                        deltas_to_process.append(GoalDelta(
                            side="",
                            scoring_team="",
                            new_home=curr_home,
                            new_away=curr_away,
                            kind="catchup",
                            goals_missed=curr_home + curr_away,
                            prev_home=0,
                            prev_away=0,
                        ))

                elif deltas:
                    for delta in deltas:
                        delta.scoring_team = (
                            match.home_name if delta.side == "home" else match.away_name
                        )
                    # CLAIM the announced score immediately so a concurrent job that
                    # acquires the lock next sees new_ann and produces no delta.
                    scores[match_key] = {
                        "home": new_ann["home"],
                        "away": new_ann["away"],
                        "status": match.status,
                    }
                    changed = True
                    deltas_to_process = list(deltas)

                else:
                    # No goals/disallowed to announce.
                    if was_already_finished:
                        # Second+ FINISHED tick with no new delta → evict from live state.
                        # Stops post-FT thread oscillations (e.g. Uruguay-Spain) from
                        # re-announcing after the match ends.  The FT recap job uses its
                        # own finished_announced set and is unaffected.
                        log.info(
                            "poll_goals_job: match %d (%s vs %s) already FINISHED, "
                            "no new delta → evicting from live state",
                            match.id, match.home_name, match.away_name,
                        )
                        scores.pop(match_key, None)
                        seen_api.pop(match_key, None)
                        seen_scores["thread"].pop(match_key, None)
                        changed = True
                    else:
                        # Normal no-delta path: update status/score if changed.
                        announced_changed = (
                            new_ann["home"] != stored["home"] or new_ann["away"] != stored["away"]
                        )
                        status_changed = stored.get("status") != match.status
                        if announced_changed or status_changed:
                            scores[match_key]["home"] = new_ann["home"]
                            scores[match_key]["away"] = new_ann["away"]
                            scores[match_key]["status"] = match.status
                            changed = True

            # ── Outside the lock: slow enrichment + Telegram sends ────────────────
            for delta in deltas_to_process:
                try:
                    await _process_goal_delta(
                        delta, match, scanner, settings, context, silent,
                        seen_thread=seen_scores["thread"],
                        match_key=match_key,
                    )
                except Exception as exc:
                    # Score already claimed; log only — do not re-announce.
                    log.error(
                        "poll_goals_job: error processing delta for match %d: %s",
                        match.id, exc,
                    )

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

    Bug 1 fix: goal_lock makes the "read announced → reconcile → claim" step atomic
    with poll_goals_job — prevents concurrent jobs from announcing the same goal twice.

    Bug 2 fix: _backfill_scorer_in_clip_store edits already-sent scorer-less messages
    once the thread provides the scorer.

    Bug 3 fix: thread disallowed score is clamped to announced−1 per dropped side so
    a momentary thread under-read never shows a score below the authoritative post-VAR
    value (e.g. shows 4-0 instead of 3-0 when only goal 5 was VAR'd, not goal 4).
    """
    try:
        settings: Settings = context.bot_data["settings"]
        state_path = f"{settings.state_dir}/live_scores.json"

        # Shared announced state.
        scores: dict = context.bot_data["live_scores"]

        # Per-source thread seen — in-memory only.
        seen_scores = context.bot_data.setdefault("seen_scores", {"api": {}, "thread": {}})
        seen_thread: dict = seen_scores["thread"]

        # Shared lock (created by poll_goals_job on its first run, or here if thread runs first).
        goal_lock: asyncio.Lock = context.bot_data.setdefault("goal_lock", asyncio.Lock())

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

        # Hard-exclude matches whose kickoff was >MATCH_OVER_AGE ago so a stuck
        # IN_PLAY entry (e.g. Egypt-Iran) can never keep generating spam from
        # an oscillating Reddit thread.
        now_utc = datetime.now(timezone.utc)
        live_matches = [m for m in live_matches if not _match_is_over(m, now_utc)]

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

                # Sort once; used for both goals_to_notify expansion and backfill.
                sorted_events = sorted(events, key=lambda e: e.minute_sort)

                # Variables set inside the lock and used outside it.
                deltas: list = []
                ann_homeaway: dict = {}
                new_ann: dict = {}
                goals_to_notify: list[dict] = []
                disallowed_deltas: list = []

                async with goal_lock:
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

                    if deltas:
                        # Bug 3: clamp disallowed score to announced−1 per dropped side.
                        # The thread can momentarily under-read (e.g. read 3-0 when 4-0 stands
                        # after a VAR on the 5th goal).  Using announced−1 instead of the raw
                        # thread read ensures the disallowed message and the new announced value
                        # are always authoritative and never go below the truly-confirmed score.
                        for d in deltas:
                            if d.kind == "disallowed":
                                if d.side == "home":
                                    clamped = max(d.new_home, ann_homeaway["home"] - 1)
                                    d.new_home = clamped
                                    new_ann["home"] = clamped
                                else:
                                    clamped = max(d.new_away, ann_homeaway["away"] - 1)
                                    d.new_away = clamped
                                    new_ann["away"] = clamped

                        # CLAIM the announced score before slow Telegram sends.
                        # Persist immediately — closes the save-window race where a
                        # crash between claim and a deferred save could lose the
                        # claimed score and trigger re-announcement on restart.
                        scores[key]["home"] = new_ann["home"]
                        scores[key]["away"] = new_ann["away"]
                        save_scores(state_path, scores)
                        changed = True

                # ── Outside the lock: build notifications ─────────────────────

                if deltas:
                    goal_deltas = [d for d in deltas if d.kind == "goal"]
                    disallowed_deltas = [d for d in deltas if d.kind == "disallowed"]

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
                    for delta in disallowed_deltas:
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

                    log.info(
                        "poll_thread_goals_job: match %d (%s vs %s) thread score %d-%d "
                        "(was %d-%d), %d goal(s) + %d disallowed notified",
                        match.id, match.home_name, match.away_name,
                        thread_home, thread_away,
                        ann_homeaway["home"], ann_homeaway["away"],
                        len(goals_to_notify),
                        len(disallowed_deltas),
                    )

                # Bug 2 fix: back-fill scorer onto scorer-less announced goals.
                # Runs regardless of whether there were new deltas this tick —
                # the API may have beaten the thread to the announcement.
                await _backfill_scorer_in_clip_store(match, sorted_events, settings, context)

            except Exception as exc:
                log.exception(
                    "poll_thread_goals_job: error for match %s vs %s: %s",
                    result.home_tla, result.away_tla, exc,
                )

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

                    # Mark ready BEFORE the Telegram edit so that any concurrent
                    # _backfill_scorer_in_clip_store call sees status="ready" and
                    # preserves the keyboard when editing the message text.
                    entry["status"] = "ready"
                    entry["clip_path"] = str(persistent_path)

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


# Grace window: never announce a kickoff that was >30 minutes ago.  Protects
# against the rare case where the seed pass missed a match somehow.
_KICKOFF_GRACE = timedelta(minutes=30)


async def poll_kickoff_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeating job: post a 'match starting' notice at each scheduled kickoff time.

    Dedup strategy (persistent, restart-safe):
    - `kickoff_announced` (bot_data + disk): set of match ids whose kick-off
      notice has already been sent (or seeded as already-handled).  Persisted to
      `{state_dir}/kickoff_announced.json` after every change.
    - SEED on first run (gate: `kickoff_seeded`): mark every match whose kickoff
      is already in the past OR whose status is IN_PLAY / PAUSED / FINISHED as
      announced.  Persist and return — no sends on the seed pass.
    - NORMAL pass: for each SCHEDULED/TIMED match not in `announced`, announce
      when `kickoff <= now_utc` AND `now_utc - kickoff <= 30 min` (grace window).
    """
    try:
        settings: Settings = context.bot_data["settings"]
        announced: set = context.bot_data["kickoff_announced"]
        path = f"{settings.state_dir}/kickoff_announced.json"

        client = make_client(settings)
        try:
            all_matches = client.get_all_matches()
        except FootballAPIError as exc:
            log.warning("poll_kickoff_job: could not get matches: %s", exc)
            return

        now_utc = datetime.now(timezone.utc)
        silent = _is_silent_hour(datetime.now(pytz.timezone(settings.timezone)))

        # ── seed on first run ─────────────────────────────────────────────────
        if not context.bot_data.get("kickoff_seeded", False):
            seeded: set[int] = set()
            for m in all_matches:
                if m.status in ("IN_PLAY", "PAUSED", "FINISHED"):
                    seeded.add(int(m.id))
                else:
                    try:
                        kickoff = datetime.strptime(
                            m.utc_date, "%Y-%m-%dT%H:%M:%SZ"
                        ).replace(tzinfo=timezone.utc)
                        if kickoff <= now_utc:
                            seeded.add(int(m.id))
                    except Exception:
                        pass
            announced.update(seeded)
            save_finished(path, announced)
            context.bot_data["kickoff_seeded"] = True
            log.info(
                "poll_kickoff_job: seeded %d already-kicked-off matches (no sends)",
                len(seeded),
            )
            return

        # ── normal pass ───────────────────────────────────────────────────────
        for m in all_matches:
            mid = int(m.id)
            if mid in announced:
                continue

            # FINISHED matches: mark quietly without sending
            if m.status == "FINISHED":
                announced.add(mid)
                save_finished(path, announced)
                continue

            # Only consider matches that haven't definitely started yet
            # (SCHEDULED / TIMED) — IN_PLAY/PAUSED are handled by seed normally
            # but may appear between seed and first normal tick; announce them.
            try:
                kickoff = datetime.strptime(
                    m.utc_date, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
            except Exception:
                continue

            elapsed = now_utc - kickoff
            if kickoff > now_utc:
                continue  # not yet
            if elapsed > _KICKOFF_GRACE:
                # Escaped the seed somehow; mark and skip silently.
                announced.add(mid)
                save_finished(path, announced)
                continue

            # Announce
            try:
                text = format_match_start(m)
                try:
                    kickoff_preds = pred_loader.load(settings.predictions_path)
                    camps = compute_match_camps(
                        m.home_tla, m.away_tla, m.stage, m.group, kickoff_preds,
                        home_name=m.home_name, away_name=m.away_name,
                    )
                    camps_block = format_match_camps(
                        camps, use_html=True, title="⚔️ ¿Con quién va la porra?"
                    )
                    if camps_block:
                        text = f"{text}\n\n{camps_block}"
                except Exception as exc:
                    log.warning(
                        "poll_kickoff_job: camps block failed for match %d: %s", mid, exc
                    )
                await context.bot.send_message(
                    chat_id=settings.telegram_group_id,
                    text=text,
                    parse_mode="HTML",
                    disable_notification=silent,
                )
                log.info(
                    "poll_kickoff_job: sent kickoff notice for match %d (%s vs %s)",
                    mid,
                    m.home_name,
                    m.away_name,
                )
            except Exception as exc:
                log.error(
                    "poll_kickoff_job: failed to send for match %d: %s", mid, exc
                )
            finally:
                announced.add(mid)
                save_finished(path, announced)
                # Seed live_scores at 0-0 so the first IN_PLAY API tick sees a proper
                # 0→1 goal delta rather than triggering the first-seen catch-up path.
                scores_dict: dict = context.bot_data.setdefault("live_scores", {})
                match_key_str = str(mid)
                if match_key_str not in scores_dict:
                    scores_dict[match_key_str] = {"home": 0, "away": 0, "status": "IN_PLAY"}
                    save_scores(f"{settings.state_dir}/live_scores.json", scores_dict)
                    log.info("poll_kickoff_job: seeded match %d at 0-0 in live_scores", mid)

    except Exception as exc:
        log.exception("poll_kickoff_job: unexpected error: %s", exc)


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

                # ── Section 2: porra face-off ("guerra de la porra") ─────────
                camps_section: str | None = None
                try:
                    camps_preds = pred_loader.load(settings.predictions_path)
                    camps = compute_match_camps(
                        match.home_tla, match.away_tla, match.stage, match.group,
                        camps_preds, home_name=match.home_name, away_name=match.away_name,
                    )
                    winner_side = (
                        "home" if match.winner == "HOME_TEAM"
                        else "away" if match.winner == "AWAY_TEAM"
                        else None
                    )
                    camps_section = format_match_camps(
                        camps, use_html=True, title="⚔️ La guerra de la porra",
                        winner_side=winner_side,
                    ) or None
                except Exception as exc:
                    log.error("Face-off failed for match %d: %s", match_id, exc)

                # ── Assemble sections and always send ─────────────────────────
                sections: list[str] = [result_section]
                if camps_section:
                    sections.append(camps_section)
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
    # kickoff-start tracker: persisted set of match ids already announced or seeded.
    kickoff_path = f"{settings.state_dir}/kickoff_announced.json"
    app.bot_data["kickoff_announced"] = load_finished(kickoff_path)
    # False until first poll_kickoff_job run completes its seed pass.
    app.bot_data["kickoff_seeded"] = False

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
        CallbackQueryHandler(cmd_endirecto_goal_callback, pattern=r"^edgol\|"),
        CallbackQueryHandler(cmd_endirecto_callback, pattern=r"^ed\|"),
        # Test / utility
        CommandHandler("simulagol", cmd_simula_gol),
        CommandHandler("updatediario", cmd_update_diario),
        CommandHandler("recalcular", cmd_recalcular),
        CommandHandler("tongocheck", cmd_tongocheck),
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

        app.job_queue.run_repeating(
            poll_kickoff_job,
            interval=30,
            first=20,
            name="poll_kickoff",
        )
        log.info(
            "Kickoff-start notifier enabled — polling every 30s for group %s",
            settings.telegram_group_id,
        )

    app.run_polling()


if __name__ == "__main__":
    main()
