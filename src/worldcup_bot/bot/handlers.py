"""Telegram command handlers.

All commands are async (python-telegram-bot v21+ pattern).
Handlers import from porra/engine (never from api/ directly).
Spanish user-facing strings throughout.
"""

from __future__ import annotations

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
from worldcup_bot.data.tongo import FRASES
from worldcup_bot.porra import engine, predictions as pred_loader

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
    await update.message.reply_text(random.choice(FRASES))


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
