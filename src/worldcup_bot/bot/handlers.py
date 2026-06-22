"""Telegram command handlers.

All commands are async (python-telegram-bot v21+ pattern).
Handlers import from porra/engine (never from api/ directly).
Spanish user-facing strings throughout.
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
import time
from pathlib import Path

import requests as _requests

from telegram import InputMediaPhoto, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from worldcup_bot.api.cache import get_default_cache
from worldcup_bot.api.client import FootballDataClient, FootballAPIError
from worldcup_bot.bot.formatters import (
    format_general_ranking,
    format_live_match_detail,
    format_match,
    format_match_with_date,
    render_endirecto,
    format_standings,
    format_user_detail,
    participant_photo_url,
    team_flag,
)
from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.daily_update import generate_daily_update
from worldcup_bot.ai.match_events import extract_match_events
from worldcup_bot.config import Settings, ai_enabled
from worldcup_bot.data.stages import GROUPS, KNOCKOUT_STAGES, STAGE_YAML_KEYS
from worldcup_bot.data.tongo import (
    FRASES,
    build_tongo_context,
    choose_tongo_response,
    load_tongo_config,
    phrase_uses_reply,
    render_tongo,
)
from worldcup_bot.data.gender import infer_gender
from worldcup_bot.data.gifs import list_tongo_gifs
from worldcup_bot.porra import engine, predictions as pred_loader
from worldcup_bot.porra.history import ensure_history
from worldcup_bot.porra.chart import render_evolution_png
from worldcup_bot.reddit.clip_finder import find_goal_clip
from worldcup_bot.reddit.clip_store import (
    add_entry as _cs_add_entry,
    goal_token as _goal_token,
    save_clips as _cs_save_clips,
)
from worldcup_bot.bot.endirecto_store import (
    load_snapshot as _ed_load_snapshot,
    new_token as _ed_new_token,
    save_snapshot as _ed_save_snapshot,
    set_revealed as _ed_set_revealed,
)
from worldcup_bot.reddit.downloader import MediaDownloader
from worldcup_bot.reddit.models import GoalEvent
from worldcup_bot.reddit.notifier import build_goal_keyboard, format_goal_notification
from worldcup_bot.reddit.parser import parse_goal_events
from worldcup_bot.reddit.scanner import RedditMatchScanner, _teams_match
from worldcup_bot.reddit.vergol_stats import leaderboard as _vs_leaderboard
from worldcup_bot.reddit.vergol_stats import load_stats as _vs_load_stats
from worldcup_bot.reddit.vergol_stats import record_view as _vs_record_view
from worldcup_bot.reddit.vergol_stats import save_stats as _vs_save_stats
from worldcup_bot.reddit.video import VideoTooLargeError, compress_if_needed, probe_video
from worldcup_bot.tve import load_tve_broadcasts, tve_channel_for

log = logging.getLogger(__name__)

# ── Spanish error messages ────────────────────────────────────────────────────

_MSG_NO_USERNAME = (
    "No tienes @username configurado en Telegram. "
    "Configura tu username en Telegram o pide a un admin que te ayude."
)
_MSG_USER_NOT_FOUND = "No encontré a '{name}' en la porra. Comprueba el nombre."
_MSG_RATE_LIMIT = "⚠️ Rate limit de la API. Intenta en 1 minuto."
_MSG_API_ERROR = "❌ Error de API ({code}). Intenta más tarde."


def _msg_no_predictions(path: str) -> str:
    return (
        f"⚠️ No se han podido cargar predicciones desde `{path}`. "
        "Revisa que el fichero existe y es válido (mira los logs para errores de validación)."
    )


# ── factory ───────────────────────────────────────────────────────────────────


def make_client(settings: Settings) -> FootballDataClient:
    return FootballDataClient(
        api_key=settings.football_data_api_key,
        competition_code=settings.competition_code,
        cache=get_default_cache(ttl=settings.football_cache_ttl),
    )


# ── error translation ─────────────────────────────────────────────────────────


def _api_error_msg(exc: FootballAPIError) -> str:
    if exc.status_code == 429:
        return _MSG_RATE_LIMIT
    return _MSG_API_ERROR.format(code=exc.status_code)


# ── user resolution helpers ───────────────────────────────────────────────────


def _caller_username(update: Update) -> str | None:
    user = update.effective_user
    if user and user.username:
        return user.username.lower()
    return None


def _resolve_target(
    arg: str | None,
    caller: str | None,
    predictions: dict,
) -> tuple[str | None, dict | None]:
    """Resolve a /listaaciertos argument to (username, user_data).

    Precedence:
    1. No arg → caller.
    2. @user or user → direct username lookup.
    3. Not found by username → try display_name.
    """
    if arg is None:
        if caller is None:
            return None, None
        udata = pred_loader.get_participant(predictions, caller)
        return caller, udata

    target = arg.lstrip("@").lower()
    udata = pred_loader.get_participant(predictions, target)
    if udata is not None:
        return target, udata

    # Try display_name fallback
    result = pred_loader.find_by_display_name(predictions, arg)
    if result:
        return result

    return target, None


# ── handlers ──────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "¡Hola! Soy el bot de la porra del Mundial 2026 ⚽️🌍\n\n"
        "Comandos disponibles:\n"
        "/actual — clasificación provisional (a día de hoy)\n"
        "/general — clasificación general (oficial, solo grupos cerrados)\n"
        "/evolucion — gráfico de evolución de la porra 📈\n"
        "/porra — alias de /actual\n"
        "/listaaciertos — tus aciertos (oficial, solo cerrados)\n"
        "/listaaciertosactual — tus aciertos provisionales (a día de hoy)\n"
        "/clasificacion [grupo] — clasificación de grupos (ej: /clasificacion L)\n"
        "/hoy — partidos de la jornada (09:00–09:00)\n"
        "/ayer — resultados de la jornada anterior\n"
        "/siguiente — próximo partido\n"
        "/endirecto — partidos en directo\n"
        "/mispredicciones — ver tus predicciones\n"
        "/participantes — lista de participantes\n"
        "/estadisticas — quién ve más goles 🏆\n"
        "/tongo — revelar la verdad 👀"
    )


async def _send_ranking_with_top3_photos(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    rows: list,
    settings: Settings,
) -> None:
    """Send a ranking text as a top-3 photo album, or fall back to plain text."""
    if not rows:
        await update.message.reply_text(text, parse_mode="HTML")
        return

    top3 = rows[:3]
    candidate_urls = [participant_photo_url(r.username, settings.photo_base_url) for r in top3]

    valid_urls: list[str] = []
    for url in candidate_urls:
        try:
            resp = _requests.get(url, timeout=4, stream=True)
            resp.close()
            if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
                valid_urls.append(url)
        except Exception:
            pass

    if not valid_urls:
        await update.message.reply_text(text, parse_mode="HTML")
        return

    caption = text[:1024]
    media = [InputMediaPhoto(media=valid_urls[0], caption=caption, parse_mode="HTML")]
    for url in valid_urls[1:]:
        media.append(InputMediaPhoto(media=url))

    try:
        await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media)
        if len(text) > 1024:
            await update.message.reply_text(text, parse_mode="HTML")
    except Exception:
        log.warning("send_media_group failed, falling back to text.")
        await update.message.reply_text(text, parse_mode="HTML")


async def cmd_clasificacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)

    # Parse optional group letter: first token (any position) that is a single A–L letter.
    letter: str | None = None
    if context.args:
        for token in context.args:
            t = token.strip().upper()
            if len(t) == 1 and t in GROUPS:
                letter = t
                break
        if letter is None:
            await update.message.reply_text(
                "Grupo no válido. Indica una letra de la A a la L, por ejemplo: /clasificacion L"
            )
            return

    try:
        standings = client.get_standings()
        live_matches = client.get_live_matches()
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    live_tlas = {m.home_tla for m in live_matches} | {m.away_tla for m in live_matches}

    if letter is not None:
        target = f"GROUP_{letter}"
        standings = [s for s in standings if s.group == target]
        if not standings:
            await update.message.reply_text(
                f"No hay clasificación disponible para el Grupo {letter} todavía."
            )
            return

    text = format_standings(standings, live_tlas=live_tlas or None)
    await update.message.reply_text(text)


async def cmd_actual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clasificación provisional (a día de hoy) — /actual and /porra alias."""
    settings: Settings = context.bot_data["settings"]
    predictions = pred_loader.load(settings.predictions_path)

    if not predictions.get("participants"):
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    client = make_client(settings)
    try:
        rows = engine.compute_general_ranking(predictions, client, official=False)
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    text = format_general_ranking(rows, title="🏆 Clasificación provisional (a día de hoy):")
    await _send_ranking_with_top3_photos(update, context, text, rows, settings)


async def cmd_general(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clasificación general oficial — solo grupos cerrados puntúan."""
    settings: Settings = context.bot_data["settings"]
    predictions = pred_loader.load(settings.predictions_path)

    if not predictions.get("participants"):
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    client = make_client(settings)
    try:
        rows = engine.compute_general_ranking(predictions, client, official=True)
        finished = client.get_finished_groups()
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    footer = f"\n\n📋 Grupos cerrados: {len(finished)}/{len(GROUPS)}"
    if len(finished) < len(GROUPS):
        footer += "\nℹ️ Solo puntúan los grupos ya terminados. Usa /actual para ver la provisional."

    text = format_general_ranking(rows, title="🏆 Clasificación general (oficial):")
    text = text + footer
    await _send_ranking_with_top3_photos(update, context, text, rows, settings)


async def _send_user_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    official: bool,
) -> None:
    """Shared body for /listaaciertos (official) and /listaaciertosactual (provisional)."""
    settings: Settings = context.bot_data["settings"]
    caller = _caller_username(update)

    arg = " ".join(context.args).strip() if context.args else None

    if arg is None and caller is None:
        await update.message.reply_text(_MSG_NO_USERNAME)
        return

    predictions = pred_loader.load(settings.predictions_path)

    if not predictions.get("participants"):
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    target_username, udata = _resolve_target(arg, caller, predictions)

    if udata is None:
        name = arg or f"@{caller}"
        await update.message.reply_text(_MSG_USER_NOT_FOUND.format(name=name))
        return

    client = make_client(settings)
    try:
        detail = engine.compute_user_detail(target_username, predictions, client, official=official)
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    if detail is None:
        await update.message.reply_text(_MSG_USER_NOT_FOUND.format(name=target_username))
        return

    await update.message.reply_text(format_user_detail(detail), parse_mode="HTML")


async def cmd_lista_aciertos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show official scoring detail — only closed groups and finished KO rounds count."""
    await _send_user_detail(update, context, official=True)


async def cmd_lista_aciertos_actual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show provisional scoring detail — live standings, a día de hoy."""
    await _send_user_detail(update, context, official=False)


async def cmd_en_directo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)

    try:
        live = client.get_live_matches()
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    if not live:
        await update.message.reply_text("No hay partidos en directo en este momento.")
        return

    # Reuse the shared scanner (same instance used by goal/clip jobs so their
    # recent TTL-cached fetches benefit /endirecto too — avoids duplicate Reddit hits).
    scanner: RedditMatchScanner = context.bot_data.get("reddit_scanner")  # type: ignore[assignment]
    if scanner is None:
        scanner = RedditMatchScanner(user_agent=settings.reddit_user_agent)
        context.bot_data["reddit_scanner"] = scanner

    ai = (
        AIClient(settings.openai_api_key, settings.openai_base_url, settings.openai_model)
        if ai_enabled(settings)
        else None
    )
    store_path = f"{settings.state_dir}/endirecto.json"
    for m in live[:4]:
        try:
            if ai is not None:
                # Try the cached /new/ listing first (avoids the 429-prone search endpoint).
                permalink = await asyncio.to_thread(
                    scanner.find_thread_permalink, m.home_name, m.away_name
                )
                if permalink is None:
                    # Fall back to the search endpoint for matches not yet in /new/.
                    permalink = await asyncio.to_thread(
                        scanner.find_match_thread, m.home_name, m.away_name
                    )
                if permalink:
                    body = await asyncio.to_thread(scanner.get_thread_body, permalink)
                    events = await extract_match_events(ai, body, m.home_name, m.away_name)
                    snap = {
                        "token": _ed_new_token(),
                        "match_id": m.id,
                        "minute": events.get("minute"),
                        "home_name": m.home_name,
                        "away_name": m.away_name,
                        "home_tla": m.home_tla,
                        "away_tla": m.away_tla,
                        "home_score": m.home_score,
                        "away_score": m.away_score,
                        "goals": events.get("goals", []),
                        "cards": events.get("cards", []),
                        "subs": events.get("subs", []),
                        "lineup": events.get("lineup", {"home": [], "away": []}),
                        "revealed": [],
                        "created": time.time(),
                    }
                    _ed_save_snapshot(store_path, snap)
                    text, kb = render_endirecto(snap)
                    await update.message.reply_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
                    )
                    continue
            await update.message.reply_text(format_match(m, settings.timezone))
        except Exception as exc:
            log.warning(
                "cmd_en_directo enrichment failed for %s vs %s: %s",
                m.home_name, m.away_name, exc,
            )
            await update.message.reply_text(format_match(m, settings.timezone))


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)
    h = settings.football_day_start_hour

    # Walk forward up to 15 windows (today .. +14 days) to find the first window
    # that still has at least one non-finished match.
    selected: list | None = None
    selected_offset: int = 0
    for offset in range(0, 15):
        try:
            ms = client.get_football_day_matches(settings.timezone, offset, h)
        except FootballAPIError as exc:
            await update.message.reply_text(_api_error_msg(exc))
            return
        if ms and any(m.status != "FINISHED" for m in ms):
            selected = ms
            selected_offset = offset
            break

    if selected is None:
        # All windows were empty or fully finished — fall back to today's results.
        try:
            today = client.get_football_day_matches(settings.timezone, 0, h)
        except FootballAPIError as exc:
            await update.message.reply_text(_api_error_msg(exc))
            return
        if today:
            selected = today
            selected_offset = 0
        else:
            await update.message.reply_text("No hay partidos programados.")
            return

    if selected_offset == 0:
        header = f"⚽️ Partidos de hoy ({h:02d}:00–{h:02d}:00):"
        try:
            broadcasts = await asyncio.to_thread(
                load_tve_broadcasts, tve_enabled=settings.tve_enabled
            )
        except Exception:
            broadcasts = []
        lines = [
            format_match(m, settings.timezone, tve_label=tve_channel_for(m, broadcasts))
            for m in selected
        ]
    else:
        header = "⚽️ Ya han acabado los partidos de hoy. Estos son los próximos:"
        try:
            broadcasts = await asyncio.to_thread(
                load_tve_broadcasts, tve_enabled=settings.tve_enabled
            )
        except Exception:
            broadcasts = []
        lines = [
            format_match_with_date(
                m, settings.timezone, tve_label=tve_channel_for(m, broadcasts)
            )
            for m in selected
        ]

    await update.message.reply_text("\n".join([header, ""] + lines))


async def cmd_ayer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)
    h = settings.football_day_start_hour

    try:
        matches = client.get_football_day_matches(
            settings.timezone, -1, h
        )
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    if not matches:
        await update.message.reply_text("No hubo partidos en ese periodo.")
        return

    header = f"📅 Resultados de ayer ({h:02d}:00–{h:02d}:00):"
    lines = [header, ""] + [format_match(m, settings.timezone) for m in matches]
    await update.message.reply_text("\n".join(lines))


async def cmd_siguiente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)

    try:
        nxt = client.get_next_match(settings.timezone)
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    if nxt is None:
        await update.message.reply_text("No se encontró información sobre el próximo partido.")
        return

    import pytz
    from datetime import datetime, timezone as dt_tz

    local_tz = pytz.timezone(settings.timezone)
    try:
        utc_dt = datetime.strptime(nxt.utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt_tz.utc)
        local_dt = utc_dt.astimezone(local_tz)
        date_str = local_dt.strftime("%d-%m-%Y %H:%M")
    except ValueError:
        date_str = nxt.utc_date

    hf = team_flag(nxt.home_tla)
    af = team_flag(nxt.away_tla)
    text = (
        f"Próximo partido:\n"
        f"{hf} {nxt.home_name} vs {nxt.away_name} {af}\n"
        f" ⌚: {date_str}"
    )
    try:
        broadcasts = await asyncio.to_thread(
            load_tve_broadcasts, tve_enabled=settings.tve_enabled
        )
        label = tve_channel_for(nxt, broadcasts)
        if label:
            text += f" 📺 {label}"
    except Exception:
        pass
    await update.message.reply_text(text)


async def cmd_tongo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    predictions_parent = Path(settings.predictions_path).parent

    if settings.tongo_users_path:
        path = Path(settings.tongo_users_path)
    else:
        path = predictions_parent / "TongoUsers.yml"

    if settings.tongo_gifs_dir:
        gifs_dir = Path(settings.tongo_gifs_dir)
    else:
        gifs_dir = predictions_parent / "tongo_gifs"

    gifs = list_tongo_gifs(gifs_dir)
    user = update.effective_user
    gender = infer_gender(user.first_name if user else None)
    ctx = build_tongo_context(update)

    cfg = load_tongo_config(str(path))
    global_phrases = cfg.phrases if cfg.phrases else FRASES
    users = cfg.users

    username = _caller_username(update)
    user_cfg = users.get(username) if username else None

    sanchez_ratio = (
        user_cfg.sanchez_ratio if (user_cfg and user_cfg.sanchez_ratio is not None) else 1 / 3
    )

    per_user_phrases = list(user_cfg.phrases) if user_cfg else []
    mode = user_cfg.phrases_mode if user_cfg else "append"

    if mode == "replace" and per_user_phrases:
        effective_phrases = per_user_phrases
    else:
        # "append" OR "replace" with empty per-user pool — guard: never serve an empty pool
        effective_phrases = global_phrases + per_user_phrases

    choice = choose_tongo_response(ctx, effective_phrases, sanchez_ratio, gender, gifs, rng=random)

    if isinstance(choice, Path):
        try:
            with open(choice, "rb") as f:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id, animation=f
                )
        except Exception as exc:
            log.warning("Could not send tongo GIF %s: %s", choice, exc)
            fb_pool = [render_tongo(p, ctx) for p in global_phrases if not phrase_uses_reply(p)]
            if not fb_pool:
                fb_pool = [render_tongo(p, ctx) for p in FRASES]
            await update.message.reply_text(random.choice(fb_pool))
    else:
        await update.message.reply_text(choice)


async def cmd_mis_predicciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the caller's own predictions from the YAML."""
    settings: Settings = context.bot_data["settings"]
    caller = _caller_username(update)

    if caller is None:
        await update.message.reply_text(_MSG_NO_USERNAME)
        return

    predictions = pred_loader.load(settings.predictions_path)

    if not predictions.get("participants"):
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    udata = pred_loader.get_participant(predictions, caller)

    if udata is None:
        await update.message.reply_text(
            f"No encontré predicciones para @{caller}. "
            "Comprueba que tu username está en el fichero."
        )
        return

    dname = pred_loader.display_name_for(caller, udata)
    lines = [f"📋 Predicciones de {dname}:", ""]

    lines.append("*Grupos:*")
    for grp, picks in sorted(udata.get("groups", {}).items()):
        formatted = " | ".join(
            f"{team_flag(t)}{t}" if t != "**" else "**" for t in picks
        )
        lines.append(f"  Grupo {grp}: {formatted}")

    lines.append("\n*Eliminatorias:*")
    for api_stage, display_es, _ in KNOCKOUT_STAGES:
        yaml_key = STAGE_YAML_KEYS.get(api_stage, api_stage.lower())
        picks = udata.get("knockout", {}).get(yaml_key, [])
        formatted = " | ".join(
            f"{team_flag(t)}{t}" if t != "**" else "**" for t in picks
        )
        lines.append(f"  {display_es}: {formatted}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_participantes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all registered participants."""
    settings: Settings = context.bot_data["settings"]
    predictions = pred_loader.load(settings.predictions_path)
    participants = predictions.get("participants", {})

    if not participants:
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    lines = ["👥 Participantes registrados:", ""]
    for uname, udata in sorted(participants.items()):
        dname = udata.get("display_name") or ""
        uname_esc = html.escape(uname, quote=False)
        dname_esc = html.escape(dname, quote=False)
        display = f"@{uname_esc}" + (f" (<b>{dname_esc}</b>)" if dname else "")
        lines.append(f"• {display}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_estadisticas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show who has watched the most goal clips (/estadisticas)."""
    settings: Settings = context.bot_data["settings"]
    path = f"{settings.state_dir}/vergol_stats.json"

    try:
        data = _vs_load_stats(path)
        board = _vs_leaderboard(data)
    except Exception:
        log.exception("cmd_estadisticas: failed to load stats")
        board = []

    if not board:
        await update.message.reply_text(
            "Aún no hay estadísticas de 'Ver gol'.",
            parse_mode="HTML",
        )
        return

    lines = ["🏆 <b>Quién ve más goles</b>", ""]
    for i, (name, count) in enumerate(board, 1):
        lines.append(f"{i}. <b>{html.escape(name)}</b> — {count}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── "Ver gol" callback handler ────────────────────────────────────────────────


def _record_vergol_view(settings: Settings, query, token: str) -> None:
    """Best-effort: record a vergol view in the persistent stats file.

    Never raises — a stats failure must never break video delivery.
    """
    try:
        user = query.from_user
        if not user:
            return
        user_id = user.id
        name = (
            (user.full_name or "").strip()
            or (user.username or "").strip()
            or f"id:{user_id}"
        )
        path = f"{settings.state_dir}/vergol_stats.json"
        data = _vs_load_stats(path)
        _vs_record_view(data, user_id, name, token)
        _vs_save_stats(path, data)
    except Exception:
        log.warning("vergol stats: failed to record view for token %s", token)


async def cmd_ver_gol_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle 'Ver gol' inline button — send the downloaded goal clip as a reply.

    Flow (Block 2):
    - The button only appears once poll_goal_clips_job has set status='ready'
      and edited the goal message to add the keyboard.
    - On tap: read the clip-store entry, send the clip file as a reply to the
      original goal message.
    - File_id is cached in the entry after the first upload so subsequent taps
      skip the file I/O.
    - In-flight set prevents a double-send if the user taps twice quickly.

    TODO [Block 4]: increment per-goal click counter here.
    """
    query = update.callback_query
    token = query.data.split(":", 1)[1] if ":" in query.data else ""

    clip_store: dict = context.bot_data.get("clip_store", {})
    entry: dict | None = clip_store.get(token)

    if entry is None:
        await query.answer("No tengo los datos de ese gol.", show_alert=True)
        return

    # Button should not appear unless status='ready', but guard gracefully
    if entry.get("status") != "ready" or not entry.get("clip_path"):
        await query.answer("⏳ El vídeo aún no está listo, espera un momento.")
        return

    # Non-blocking in-flight guard — atomic check-and-add (no await between)
    inflight: set = context.bot_data.setdefault("vergol_inflight", set())
    if token in inflight:
        await query.answer("Ya estoy enviando el vídeo…")
        return
    inflight.add(token)

    await query.answer()

    settings: Settings = context.bot_data["settings"]
    chat_id = entry["chat_id"]
    message_id = entry["message_id"]

    try:
        # Fast path: file_id already cached in the clip-store entry
        cached_fid = entry.get("file_id")
        if cached_fid:
            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=cached_fid,
                    reply_to_message_id=message_id,
                    supports_streaming=True,
                )
                _record_vergol_view(settings, query, token)
                return
            except Exception as exc:
                log.warning(
                    "cmd_ver_gol_callback: stale file_id %s evicted: %s",
                    cached_fid,
                    exc,
                )
                entry.pop("file_id", None)
                # Fall through to fresh send

        # Fresh send: open clip from the persistent volume
        clip_path = Path(entry["clip_path"])
        if not clip_path.exists():
            log.error(
                "cmd_ver_gol_callback: clip_path %s missing for token %s",
                clip_path,
                token,
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ No encuentro el archivo del vídeo. El clip fue limpiado del disco.",
                reply_to_message_id=message_id,
            )
            return

        meta = await probe_video(clip_path)
        with open(clip_path, "rb") as f:
            sent_msg = await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                reply_to_message_id=message_id,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
                **meta,
            )

        _record_vergol_view(settings, query, token)

        # Cache the Telegram file_id so the next tap is instant
        if sent_msg and sent_msg.video:
            entry["file_id"] = sent_msg.video.file_id
            clips_path = f"{settings.state_dir}/goal_clips.json"
            _cs_save_clips(clips_path, clip_store)

    except Exception as exc:
        log.exception("cmd_ver_gol_callback: unexpected error: %s", exc)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Error inesperado al enviar el vídeo. Inténtalo de nuevo.",
                reply_to_message_id=message_id,
            )
        except Exception:
            pass

    finally:
        inflight.discard(token)


async def cmd_endirecto_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /endirecto inline reveal buttons (tarjetas / alineacion / cambios)."""
    query = update.callback_query
    try:
        parts = query.data.split("|", 2)
        if len(parts) != 3:
            await query.answer("Datos inválidos.", show_alert=True)
            return
        _, token, code = parts
        _code_map = {"t": "tarjetas", "l": "alineacion", "c": "cambios"}
        section = _code_map.get(code)
        if not section:
            await query.answer("Sección desconocida.", show_alert=True)
            return
        settings: Settings = context.bot_data["settings"]
        store_path = f"{settings.state_dir}/endirecto.json"
        snap = _ed_set_revealed(store_path, token, section)
        if snap is None:
            await query.answer("Datos no disponibles.", show_alert=True)
            return
        text, kb = render_endirecto(snap)
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb) if kb else None,
        )
        await query.answer()
    except Exception as exc:
        log.warning("cmd_endirecto_callback: error: %s", exc)
        try:
            await query.answer("Error al procesar.", show_alert=True)
        except Exception:
            pass


# ── /simulagol — test command ─────────────────────────────────────────────────

_FALLBACK_GOAL = GoalEvent(
    minute_text="60",
    minute_sort=60.0,
    scorer="Viktor Gyökeres",
    scoring_team="Sweden",
    home_team="Sweden",
    away_team="Tunisia",
    home_score=3,
    away_score=1,
    raw="(simulado)",
    key="SIM:sweden-tunisia-3-1-60-gyokeres",
)
_FALLBACK_HOME_TLA = "SWE"
_FALLBACK_AWAY_TLA = "TUN"


def _pick_random_goal(
    client: FootballDataClient,
    scanner: RedditMatchScanner,
    max_candidates: int = 6,
) -> tuple[GoalEvent, str, str] | None:
    """Sync helper: pick a random goal from a finished WC fixture via Reddit.

    Tries up to *max_candidates* shuffled finished matches.  Returns
    ``(goal, home_tla, away_tla)`` on success or ``None`` if no goal found.
    """
    try:
        matches = client.get_all_matches()
    except Exception as exc:
        log.warning("_pick_random_goal: get_all_matches failed: %s", exc)
        return None

    finished = [m for m in matches if m.status == "FINISHED"]
    if not finished:
        log.info("_pick_random_goal: no finished matches available")
        return None

    random.shuffle(finished)

    for m in finished[:max_candidates]:
        try:
            permalink = scanner.find_match_thread(m.home_name, m.away_name)
            if permalink is None:
                log.debug(
                    "_pick_random_goal: no thread for %s vs %s", m.home_name, m.away_name
                )
                continue

            parts = permalink.strip("/").split("/")
            post_id = parts[3] if len(parts) > 3 else ""

            body = scanner.get_thread_body(permalink)
            goals = parse_goal_events(body, post_id=post_id)
            if not goals:
                log.debug(
                    "_pick_random_goal: no goals in thread for %s vs %s",
                    m.home_name,
                    m.away_name,
                )
                continue

            goal = random.choice(goals)

            # Align TLAs to the fixture (Reddit title home/away may differ from API)
            if _teams_match(goal.home_team, m.home_name):
                home_tla, away_tla = m.home_tla, m.away_tla
            elif _teams_match(goal.home_team, m.away_name):
                home_tla, away_tla = m.away_tla, m.home_tla
            else:
                home_tla, away_tla = m.home_tla, m.away_tla

            return goal, home_tla, away_tla

        except Exception as exc:
            log.warning(
                "_pick_random_goal: error processing %s vs %s: %s",
                m.home_name,
                m.away_name,
                exc,
            )
            continue

    return None


async def cmd_simula_gol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fire a simulated goal notification with a random WC goal.

    Picks a random goal from any finished WC fixture (via Reddit match thread).
    Falls back to the fixed Sweden 3-1 Tunisia, Gyökeres 60' goal if no random
    goal can be found, so the command never fully fails.

    Stores a clip-store entry with status='searching' so poll_goal_clips_job
    will search for the clip and edit the message to add the 'Ver gol' button.
    The goal notification is sent WITHOUT a keyboard (same flow as real goals).
    """
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)

    scanner: RedditMatchScanner | None = context.bot_data.get("reddit_scanner")
    if scanner is None:
        scanner = RedditMatchScanner(user_agent=settings.reddit_user_agent)
        context.bot_data["reddit_scanner"] = scanner

    await update.message.reply_text("⏳ Eligiendo un gol al azar del Mundial…")

    picked = await asyncio.to_thread(_pick_random_goal, client, scanner)

    if picked is not None:
        goal, home_tla, away_tla = picked
    else:
        log.warning(
            "cmd_simula_gol: dynamic pick failed, falling back to fixed Sweden-Tunisia goal"
        )
        goal = _FALLBACK_GOAL
        home_tla = _FALLBACK_HOME_TLA
        away_tla = _FALLBACK_AWAY_TLA

    token = _goal_token(goal.key)

    text = format_goal_notification(goal, home_tla, away_tla)

    # Send WITHOUT keyboard — poll_goal_clips_job will edit the message once ready
    sent = await update.message.reply_text(f"🧪 [SIMULACIÓN]\n{text}")

    # Record clip-store entry for background clip search
    clip_store: dict = context.bot_data.setdefault("clip_store", {})
    _cs_add_entry(
        clip_store,
        token=token,
        chat_id=update.effective_chat.id,
        message_id=sent.message_id,
        home_name=goal.home_team,
        away_name=goal.away_team,
        home_tla=home_tla,
        away_tla=away_tla,
        home_score=goal.home_score,
        away_score=goal.away_score,
        scoring_team=goal.scoring_team,
        scorer=goal.scorer,
        minute=goal.minute_text,
    )
    clips_path = f"{settings.state_dir}/goal_clips.json"
    _cs_save_clips(clips_path, clip_store)

    log.info("Simulated goal fired (token=%s): %s", token, goal.key)


# ── /updatediario — hidden AI daily update trigger ────────────────────────────


async def cmd_update_diario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hidden manual trigger for the AI daily update. /updatediario

    Sends the AI-generated Spanish recap to the current chat so it can be
    tested before the 9 AM scheduled job fires.  Not listed in /start help.
    """
    settings: Settings = context.bot_data["settings"]

    if not ai_enabled(settings):
        await update.message.reply_text(
            "⚠️ La integración de IA no está configurada (faltan OPENAI_*)."
        )
        return

    await update.message.reply_text("⏳ Generando el resumen del día…")

    client = make_client(settings)
    ai = AIClient(
        settings.openai_api_key,
        settings.openai_base_url,
        settings.openai_model,
    )

    try:
        text = await generate_daily_update(client, ai, settings)
        if text is None:
            await update.message.reply_text(
                "🤷 No hay partidos ni ayer ni hoy, no hay nada que comentar."
            )
            return
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode="HTML",
        )
    except Exception:
        log.exception("cmd_update_diario: error generating update")
        await update.message.reply_text(
            "❌ Error al generar el resumen. Revisa los logs."
        )



# ── /recalcular — hidden admin: rebuild history with current scoring ──────────


async def cmd_recalcular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hidden admin trigger: recomputes ALL jornadas from scratch. /recalcular

    Useful after a scoring-rule fix to correct stale cached points so
    /evolucion reflects the corrected history.  Not listed in /start help.
    """
    settings: Settings = context.bot_data["settings"]
    predictions = pred_loader.load(settings.predictions_path)

    if not predictions.get("participants"):
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    client = make_client(settings)
    history_path = f"{settings.state_dir}/porra_history.json"

    await update.message.reply_text("⏳ Recalculando histórico desde cero…")

    try:
        history = await asyncio.to_thread(
            ensure_history, client, predictions, settings, history_path, True
        )
    except Exception:
        log.exception("cmd_recalcular: error rebuilding history")
        await update.message.reply_text("❌ Error al recalcular el histórico. Revisa los logs.")
        return

    n = len(history)
    await update.message.reply_text(
        f"✅ Histórico recalculado: {n} jornadas. /evolucion ya refleja la nueva puntuación."
    )


# ── /evolucion — ranking evolution chart ─────────────────────────────────────


async def cmd_evolucion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post a bump-chart image of porra ranking evolution since the first match."""
    settings: Settings = context.bot_data["settings"]
    predictions = pred_loader.load(settings.predictions_path)

    if not predictions.get("participants"):
        await update.message.reply_text(_msg_no_predictions(settings.predictions_path))
        return

    client = make_client(settings)
    history_path = f"{settings.state_dir}/porra_history.json"

    try:
        history = await asyncio.to_thread(
            ensure_history, client, predictions, settings, history_path
        )
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return
    except Exception:
        log.exception("cmd_evolucion: error building history")
        await update.message.reply_text("❌ Error al generar la evolución. Intenta más tarde.")
        return

    if not history:
        await update.message.reply_text("Aún no hay partidos para dibujar la evolución.")
        return

    out_path = f"{settings.state_dir}/evolucion.png"
    try:
        await asyncio.to_thread(render_evolution_png, history, out_path)
        with open(out_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption="📈 Evolución de la porra",
            )
    except Exception:
        log.exception("cmd_evolucion: error rendering or sending chart")
        await update.message.reply_text("❌ Error al generar el gráfico. Intenta más tarde.")
