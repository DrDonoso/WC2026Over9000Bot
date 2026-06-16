"""Telegram command handlers.

All commands are async (python-telegram-bot v21+ pattern).
Handlers import from porra/engine (never from api/ directly).
Spanish user-facing strings throughout.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random

import requests as _requests

from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes

from worldcup_bot.api.cache import get_default_cache
from worldcup_bot.api.client import FootballDataClient, FootballAPIError
from worldcup_bot.bot.formatters import (
    format_general_ranking,
    format_match,
    format_standings,
    format_user_detail,
    participant_photo_url,
    team_flag,
)
from worldcup_bot.config import Settings
from worldcup_bot.data.stages import GROUPS, KNOCKOUT_STAGES, STAGE_YAML_KEYS
from worldcup_bot.data.tongo import FRASES, SANCHEZ_ENS_ROBA, frase_argentino
from worldcup_bot.data.gender import infer_gender
from worldcup_bot.porra import engine, predictions as pred_loader
from worldcup_bot.reddit.clip_finder import find_goal_clip
from worldcup_bot.reddit.downloader import MediaDownloader
from worldcup_bot.reddit.models import GoalEvent
from worldcup_bot.reddit.notifier import build_goal_keyboard, format_goal_notification
from worldcup_bot.reddit.parser import parse_goal_events
from worldcup_bot.reddit.scanner import RedditMatchScanner, _teams_match
from worldcup_bot.reddit.video import VideoTooLargeError, compress_if_needed, probe_video

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
        await update.message.reply_text(text)
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
        await update.message.reply_text(text)
        return

    caption = text[:1024]
    media = [InputMediaPhoto(media=valid_urls[0], caption=caption)]
    for url in valid_urls[1:]:
        media.append(InputMediaPhoto(media=url))

    try:
        await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media)
        if len(text) > 1024:
            await update.message.reply_text(text)
    except Exception:
        log.warning("send_media_group failed, falling back to text.")
        await update.message.reply_text(text)


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

    await update.message.reply_text(format_user_detail(detail), parse_mode="Markdown")


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

    lines = [format_match(m, settings.timezone) for m in live]
    await update.message.reply_text("\n".join(lines))


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    client = make_client(settings)
    h = settings.football_day_start_hour

    try:
        matches = client.get_football_day_matches(
            settings.timezone, 0, h
        )
    except FootballAPIError as exc:
        await update.message.reply_text(_api_error_msg(exc))
        return

    if not matches:
        await update.message.reply_text("No hay partidos programados para hoy.")
        return

    header = f"⚽️ Partidos de hoy ({h:02d}:00–{h:02d}:00):"
    lines = [header, ""] + [format_match(m, settings.timezone) for m in matches]
    await update.message.reply_text("\n".join(lines))


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
    await update.message.reply_text(text)


async def cmd_tongo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if random.random() < 1 / 3:
        frase = SANCHEZ_ENS_ROBA
    else:
        user = update.effective_user
        first_name = user.first_name if user else None
        gender = infer_gender(first_name)
        candidatas = FRASES + [frase_argentino(gender)]
        frase = random.choice(candidatas)
    await update.message.reply_text(frase)


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
        display = f"@{uname}" + (f" ({dname})" if dname else "")
        lines.append(f"• {display}")

    await update.message.reply_text("\n".join(lines))


# ── "Ver gol" callback handler ────────────────────────────────────────────────


def _goal_token(key: str) -> str:
    """Derive a short stable token from a goal event key (sha1[:12])."""
    return hashlib.sha1(key.encode()).hexdigest()[:12]


async def cmd_ver_gol_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle 'Ver gol' inline button — find, download and send the goal clip."""
    query = update.callback_query
    token = query.data.split(":", 1)[1] if ":" in query.data else ""

    goal_clips: dict = context.bot_data.get("goal_clips", {})
    info: dict | None = goal_clips.get(token)

    if info is None:
        await query.answer("No tengo los datos de ese gol.", show_alert=True)
        return

    # Status guards (belt)
    if info["status"] == "sending":
        await query.answer("Ya estoy enviando el vídeo…")
        return
    if info["status"] == "sent":
        await query.answer("El vídeo ya se envió.")
        return

    # Explicit non-blocking in-flight lock (suspenders) — atomic check-and-add
    # (no await between check and add, so safe on the single-threaded event loop)
    inflight: set = context.bot_data.setdefault("vergol_inflight", set())
    if token in inflight:
        await query.answer("Ya estoy enviando el vídeo…")
        return
    inflight.add(token)
    info["status"] = "sending"

    await query.answer("⏳ Buscando el vídeo del gol…")

    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    clip_file_ids: dict = context.bot_data.setdefault("clip_file_ids", {})

    downloaded_path = None
    compressed_path = None
    media_url: str | None = None

    try:
        # ── Fast path A: cached file_id on this specific goal ──────────────────
        cached_fid = info.get("file_id")
        if cached_fid:
            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=cached_fid,
                    reply_to_message_id=msg_id,
                    supports_streaming=True,
                )
                info["status"] = "sent"
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as exc:
                    log.debug("Could not remove keyboard from goal message: %s", exc)
                return
            except Exception as exc:
                log.warning(
                    "cmd_ver_gol_callback: cached file_id %s is stale, evicting: %s",
                    cached_fid,
                    exc,
                )
                info.pop("file_id", None)
                # Also evict from global map if present
                for url, fid in list(clip_file_ids.items()):
                    if fid == cached_fid:
                        clip_file_ids.pop(url, None)
                        break
                info["status"] = "pending"
                raise

        # Reuse shared scanner instance if available
        scanner: RedditMatchScanner | None = context.bot_data.get("reddit_scanner")
        if scanner is None:
            settings: Settings = context.bot_data["settings"]
            scanner = RedditMatchScanner(user_agent=settings.reddit_user_agent)
            context.bot_data["reddit_scanner"] = scanner

        # Parse minute (strip stoppage-time suffix, e.g. "45+2" → 45)
        minute_raw = info.get("minute_text", "0")
        try:
            minute = int(minute_raw.split("+")[0].rstrip("'"))
        except (ValueError, IndexError):
            minute = 0

        media_url = await asyncio.to_thread(
            find_goal_clip,
            scanner,
            info["home_team"],
            info["away_team"],
            info["home_score"],
            info["away_score"],
            info["scorer"],
            minute,
        )

        if media_url is None:
            info["status"] = "pending"  # allow retry
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ El clip aún no está disponible en r/soccer, inténtalo en un minuto.",
                reply_to_message_id=msg_id,
            )
            return

        # ── Fast path B: cached file_id for this media URL ────────────────────
        if media_url in clip_file_ids:
            cached_url_fid = clip_file_ids[media_url]
            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=cached_url_fid,
                    reply_to_message_id=msg_id,
                    supports_streaming=True,
                )
                info["file_id"] = cached_url_fid
                info["status"] = "sent"
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as exc:
                    log.debug("Could not remove keyboard from goal message: %s", exc)
                return
            except Exception as exc:
                log.warning(
                    "cmd_ver_gol_callback: cached url file_id %s is stale, evicting: %s",
                    cached_url_fid,
                    exc,
                )
                clip_file_ids.pop(media_url, None)
                info.pop("file_id", None)
                info["status"] = "pending"
                raise

        # Download
        downloader = MediaDownloader()
        downloaded_path = await downloader.download(media_url)
        if downloaded_path is None:
            info["status"] = "pending"
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ No pude descargar el vídeo del gol.",
                reply_to_message_id=msg_id,
            )
            return

        # Compress if needed
        try:
            send_path = await compress_if_needed(downloaded_path)
            if send_path != downloaded_path:
                compressed_path = send_path
        except VideoTooLargeError as exc:
            log.warning("Video too large / uncompressible: %s", exc)
            info["status"] = "pending"
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ El vídeo es demasiado grande para Telegram.",
                reply_to_message_id=msg_id,
            )
            return

        # Probe dimensions and send; capture returned message to store file_id
        meta = await probe_video(send_path)
        with open(send_path, "rb") as f:
            sent_msg = await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                reply_to_message_id=msg_id,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
                **meta,
            )

        # Cache the Telegram file_id for future instant re-sends
        if sent_msg and sent_msg.video:
            fid = sent_msg.video.file_id
            info["file_id"] = fid
            if media_url:
                clip_file_ids[media_url] = fid

        info["status"] = "sent"
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("Could not remove keyboard from goal message: %s", exc)

    except Exception as exc:
        log.exception("cmd_ver_gol_callback: unexpected error: %s", exc)
        info["status"] = "pending"
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Error inesperado al obtener el vídeo. Inténtalo de nuevo.",
                reply_to_message_id=msg_id,
            )
        except Exception:
            pass

    finally:
        inflight.discard(token)
        if downloaded_path is not None:
            try:
                downloaded_path.unlink(missing_ok=True)
            except Exception:
                pass
        if compressed_path is not None:
            try:
                compressed_path.unlink(missing_ok=True)
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

    Stores goal context in bot_data["goal_clips"] so the 'Ver gol' inline button
    works exactly as it does for real goals from poll_goals_job.
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

    context.bot_data.setdefault("goal_clips", {})[token] = {
        "home_team": goal.home_team,
        "away_team": goal.away_team,
        "home_score": goal.home_score,
        "away_score": goal.away_score,
        "scorer": goal.scorer,
        "minute_text": goal.minute_text,
        "scoring_team": goal.scoring_team,
        "home_tla": home_tla,
        "away_tla": away_tla,
        "status": "pending",
    }

    text = format_goal_notification(goal, home_tla, away_tla)
    keyboard = build_goal_keyboard(token)

    log.info("Simulated goal fired (token=%s): %s", token, goal.key)

    await update.message.reply_text(
        f"🧪 [SIMULACIÓN]\n{text}",
        reply_markup=keyboard,
    )
