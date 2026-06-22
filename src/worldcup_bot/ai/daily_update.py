"""AI-powered daily update: Spanish recap of yesterday + today's fixtures + porra.

Key design points:
- render_message() is a pure, deterministic HTML builder — easy to unit-test.
- parse_ai_json() parses the AI JSON response with graceful degradation.
- build_ai_user_message() is a pure function — builds the AI prompt.
- generate_daily_update() is the orchestrator: fetches data, calls AI, returns HTML or None.

Message is sent with parse_mode="HTML".  All AI-provided strings are escaped with
html.escape() before insertion.

Scenarios
---------
"normal"      - matches yesterday AND today  → full recap + preview.
"pausa"       - matches yesterday, none today → recap + standings-frozen notice.
"reanudacion" - no matches yesterday, today yes → competition resumes framing.
None return   - no matches either day → generate_daily_update returns None (caller skips post).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime, timezone

import pytz

from worldcup_bot.ai import snapshot as _snapshot
from worldcup_bot.ai.client import AIClient
from worldcup_bot.ai.snapshot import Movement
from worldcup_bot.api.client import FootballDataClient
from worldcup_bot.api.models import Match
from worldcup_bot.bot.formatters import bold_person_names, team_flag
from worldcup_bot.config import Settings
from worldcup_bot.porra import engine, predictions as pred_loader
from worldcup_bot.porra.engine import UserRankEntry

log = logging.getLogger(__name__)

_DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_SYSTEM = (
    "Eres el comentarista del grupo de Telegram de una porra del Mundial 2026 entre amigos.\n\n"
    # ── TODAY_NOTES — regla principal, aplica SIEMPRE que haya partidos hoy ──
    "REGLA today_notes (obligatoria cuando hay partidos de hoy, independientemente del escenario):\n"
    "Para CADA partido de hoy, evalúa en este orden de prioridad:\n"
    "  1. CONFLICTO ARMADO: ¿comparten los dos países un conflicto armado actual o histórico, "
    "guerra, confrontación militar o tensión militar-política grave? (ejemplos: Israel–Palestina; "
    "Argentina–Inglaterra → Guerra de las Malvinas/Falklands 1982; "
    "India–Pakistán → múltiples guerras desde 1947; Irak–Irán → guerra 1980-1988). "
    "Si es así, ESTA INFORMACIÓN TIENE PRIORIDAD: nómbrala de forma concisa y factual "
    "(ej. 'se enfrentaron en la Guerra de las Malvinas (1982)'; "
    "'llevan décadas de conflicto armado en la franja de Gaza'). "
    "Sé informativo y concreto, no eufemístico ni vago, pero con tacto: sin imágenes violentas.\n"
    "  2. OTRA CURIOSIDAD GENUINA: si no hay conflicto armado, ¿existe otro dato históricamente "
    "relevante? (historia colonial —ej. Francia–Senegal—; disputa territorial notable; "
    "un encuentro WC memorable —ej. Senegal 1–0 Francia, Korea 2002—). Cítalo con precisión.\n"
  "3. CURIOSIDADES: Si no hay nada relevante de los dos puntos anteriores, devuelve una curiosidad de cada pais a poder ser relacionada con el mundo del futbol. Como por ejemplo de participaciones anteriores, como la última ronda alcanzada, curiosidades de algun jugador en particular, de algun equipo de la liga del país. Deberian ser anecdotas curiosas, interesantes o cómicas."
"4. CADENA VACÍA: si no hay nada genuino, devuelve \"\" para ese partido. "
    "NUNCA inventes, nunca estires una conexión débil, nunca pongas relleno genérico "
    "('es un partido bonito', 'gran rivalidad futbolera' sin sustancia).\n"
    "Notas: una frase corta, en español, tono informativo con tacto.\n\n"
    # ── STANDINGS_COMMENT — depende del escenario ──
    "REGLA standings_comment: adapta el comentario al ESCENARIO indicado en el mensaje del usuario:\n"
    "  - 'normal': repasa ayer y presenta hoy; narra el movimiento de la porra desde ayer "
    "y qué puede pasar hoy (los partidos de hoy pueden cerrar grupos y agitar la tabla).\n"
    "  - 'pausa': hubo partidos ayer pero hoy no; comenta el resultado/movimiento y deja "
    "claro que la clasificación queda CONGELADA/intacta hasta que se reanude la competición "
    "(la fecha la pone el sistema, no la inventes).\n"
    "  - 'reanudacion': ayer no hubo partidos y hoy SÍ; comenta que VUELVE la competición "
    "y cómo PODRÍA moverse la porra hoy — menciona rivales que están cerca en la tabla y que "
    "los resultados de los grupos de hoy pueden cambiar posiciones "
    "(NO inventes las predicciones concretas de cada usuario; háblalo en términos de cercanía en puntos).\n"
    "Emojis moderados, conciso. Máximo 4-5 frases cortas. Nunca inventes resultados.\n"
    "IMPORTANTE — nombres de participantes: cuando menciones a un participante de la porra, "
    "escribe SIEMPRE su nombre COMPLETO (nombre y apellidos) EXACTAMENTE como aparece en la "
    "clasificación que te paso (por ejemplo 'Miquel Apellido', nunca solo 'Miquel'). "
    "No uses solo el nombre de pila, no abrevies y no inventes apellidos: "
    "copia el nombre tal cual aparece.\n\n"
    "Devuelve ÚNICAMENTE el objeto JSON, sin marcas de código ni nada más. "
    'Formato exacto: {"today_notes": {"TLA1-TLA2": "nota o cadena vacía"}, '
    '"standings_comment": "narrativa corta"}\n\n'
    "Cariño especial: Panamá 🇵🇦, Uzbekistán 🇺🇿 y Curaçao 🇨🇼 son las selecciones favoritas de esta porra. "
    "Siempre que las menciones, muéstrales un poco de amor y ánimo (con naturalidad, sin pasarte "
    "ni romper el formato): un emoji de corazón, una palabra de apoyo o un guiño cariñoso."
)


def format_spanish_date(utc_date: str, tz_name: str) -> str | None:
    """Return a Spanish-formatted local date, e.g. 'el sábado 20 de junio', or None on error."""
    try:
        utc_dt = datetime.strptime(utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        local_dt = utc_dt.astimezone(pytz.timezone(tz_name))
        day_name = _DIAS_ES[local_dt.weekday()]
        month_name = _MESES_ES[local_dt.month - 1]
        return f"el {day_name} {local_dt.day} de {month_name}"
    except Exception:
        return None


def _format_kickoff(utc_date: str, tz_name: str) -> str:
    """Return local HH:MM for a UTC ISO-8601 kickoff timestamp."""
    try:
        utc_dt = datetime.strptime(utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        local_tz = pytz.timezone(tz_name)
        return utc_dt.astimezone(local_tz).strftime("%H:%M")
    except Exception:
        return "?"


# ── pure helpers ──────────────────────────────────────────────────────────────


def build_ai_user_message(
    yesterday: list[Match],
    today: list[Match],
    ranking: list[UserRankEntry],
    movements: list[Movement],
    tz_name: str,
    first_snapshot: bool = False,
    scenario: str = "normal",
    next_match: Match | None = None,
    next_date_str: str | None = None,
) -> str:
    """Build the user message string sent to the AI model. Pure function — no I/O."""
    # Yesterday's results
    if yesterday:
        results_lines = [
            f"- {m.home_name} {m.home_score}-{m.away_score} {m.away_name}"
            for m in yesterday
        ]
        results_block = "\n".join(results_lines)
    else:
        results_block = "Sin partidos ayer."

    # Today's fixtures — include TLA key so the model uses the right key
    if today:
        today_lines: list[str] = []
        for m in today:
            line = (
                f"- [{m.home_tla}-{m.away_tla}] {m.home_name} vs {m.away_name}"
                f" ({_format_kickoff(m.utc_date, tz_name)})"
            )
            today_lines.append(line)
        today_block = "\n".join(today_lines)
    else:
        today_block = "Sin partidos hoy."

    # Current ranking
    if ranking:
        ranking_lines = [
            f"{i + 1}. {r.display_name} — {r.total_score:.1f} pts"
            for i, r in enumerate(ranking)
        ]
        ranking_block = "\n".join(ranking_lines) + "\n(usa el nombre completo tal cual al mencionarlos)"
    else:
        ranking_block = "Sin datos de porra."

    # Position changes
    if first_snapshot or not movements:
        if first_snapshot:
            movements_block = "(Primera instantánea — sin datos previos de posiciones)"
        else:
            movements_block = "Sin cambios de posición respecto a ayer."
    else:
        mov_lines: list[str] = []
        for mv in movements:
            if mv.delta > 0:
                mov_lines.append(
                    f"- {mv.display_name}: {mv.old_pos}º → {mv.new_pos}º"
                    f" (subió {mv.delta})"
                )
            else:
                mov_lines.append(
                    f"- {mv.display_name}: {mv.old_pos}º → {mv.new_pos}º"
                    f" (bajó {abs(mv.delta)})"
                )
        movements_block = "\n".join(mov_lines)

    proximos_block = ""
    if scenario == "pausa" and next_match is not None and next_date_str:
        proximos_block = (
            f"\n\nPROXIMOS PARTIDOS: {next_date_str}"
            f" ({next_match.home_name} vs {next_match.away_name})"
        )

    return (
        f"ESCENARIO: {scenario}\n\n"
        f"RESULTADOS DE AYER:\n{results_block}\n\n"
        f"PARTIDOS DE HOY:\n{today_block}\n\n"
        f"CLASIFICACIÓN ACTUAL:\n{ranking_block}\n\n"
        f"CAMBIOS DESDE AYER:\n{movements_block}"
        f"{proximos_block}"
    )


def parse_ai_json(raw: str) -> tuple[dict, str]:
    """Parse the AI JSON response into (today_notes, standings_comment).

    Strips ```json ... ``` fences.  On any failure: returns ({}, "") and logs a warning.
    The rendered message will still show all match lines — AI content is optional.
    """
    try:
        text = raw.strip()
        # Strip ```json...``` or ```...``` code fences
        if text.startswith("```"):
            text = text.lstrip("`")
            if text.startswith("json"):
                text = text[4:]
            last_fence = text.rfind("```")
            if last_fence != -1:
                text = text[:last_fence]
            text = text.strip()
        data = json.loads(text)
        today_notes = data.get("today_notes", {})
        if not isinstance(today_notes, dict):
            today_notes = {}
        standings_comment = str(data.get("standings_comment", ""))
        return today_notes, standings_comment
    except Exception as exc:
        log.warning("parse_ai_json failed (%s) | raw=%r", exc, raw[:300])
        return {}, ""


def render_message(
    yesterday: list[Match],
    today: list[Match],
    tz_name: str,
    today_notes: dict[str, str],
    standings_comment: str,
    scenario: str = "normal",
    next_date_str: str | None = None,
    participant_names: list[str] | None = None,
    tve_by_key: dict[str, str] | None = None,
) -> str:
    """Assemble the final HTML Telegram message. Pure function — no I/O.

    Uses html.escape() on all variable content; own <b>/<i> tags are literal.
    Person names in standings_comment are bolded via bold_person_names().

    Section rules:
    - "Resultados de ayer": only included when yesterday is non-empty.
    - "Partidos de hoy": shown when today is non-empty; if empty and scenario=="pausa"
      a pause notice is shown instead.
    - "La porra": always present.
    """
    _participant_names: list[str] = participant_names or []
    sections: list[str] = []

    # ── Section 1: yesterday (omit entirely when empty) ───────────────────────
    if yesterday:
        lines: list[str] = ["📅 <b>Resultados de ayer</b>"]
        for m in yesterday:
            hf = team_flag(m.home_tla)
            af = team_flag(m.away_tla)
            hs = m.home_score if m.home_score is not None else 0
            as_ = m.away_score if m.away_score is not None else 0
            home_esc = html.escape(m.home_name, quote=False)
            away_esc = html.escape(m.away_name, quote=False)
            if m.winner == "HOME_TEAM":
                home_str = f"<b>{home_esc}</b>"
                away_str = away_esc
            elif m.winner == "AWAY_TEAM":
                home_str = home_esc
                away_str = f"<b>{away_esc}</b>"
            else:  # DRAW or None
                home_str = home_esc
                away_str = away_esc
            lines.append(f"{hf} {home_str} {hs}-{as_} {away_str} {af}")
        sections.append("\n".join(lines))

    # ── Section 2: today ──────────────────────────────────────────────────────
    if today:
        lines = ["⚽ <b>Partidos de hoy</b>"]
        for m in today:
            hf = team_flag(m.home_tla)
            af = team_flag(m.away_tla)
            home_esc = html.escape(m.home_name, quote=False)
            away_esc = html.escape(m.away_name, quote=False)
            kickoff = _format_kickoff(m.utc_date, tz_name)
            key = f"{m.home_tla}-{m.away_tla}"
            match_line = f"{hf} <b>{home_esc}</b> vs <b>{away_esc}</b> {af} — {kickoff}"
            if tve_by_key:
                label = tve_by_key.get(key)
                if label:
                    match_line += f" 📺 {label}"
            lines.append(match_line)
            note = today_notes.get(key, "").strip()
            if note:
                lines.append(f"   <i>{html.escape(note, quote=False)}</i>")
        sections.append("\n".join(lines))
    elif scenario == "pausa":
        body = (
            "La clasificación de la porra se mantiene intacta hasta que "
            "se reanude la competición"
        )
        if next_date_str:
            body += f" {next_date_str}."
        else:
            body += "."
        sections.append(f"⏸️ <b>Hoy no hay partidos</b>\n{body}")

    # ── Section 3: porra ──────────────────────────────────────────────────────
    lines = ["📊 <b>La porra</b>"]
    if standings_comment:
        lines.append(bold_person_names(standings_comment, _participant_names))
    sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ── orchestrator ──────────────────────────────────────────────────────────────


async def generate_daily_update(
    client: FootballDataClient,
    ai: AIClient,
    settings: Settings,
) -> str | None:
    """Fetch football data + porra, call AI, return HTML message string or None.

    Returns None when there are no matches yesterday or today — caller should skip posting.
    """
    # 1. Football data
    yesterday_raw = client.get_football_day_matches(
        settings.timezone,
        day_offset=-1,
        anchor_hour=settings.football_day_start_hour,
    )
    yesterday = [m for m in yesterday_raw if m.status == "FINISHED"]

    today = client.get_football_day_matches(
        settings.timezone,
        day_offset=0,
        anchor_hour=settings.football_day_start_hour,
    )

    has_y = bool(yesterday)
    has_t = bool(today)

    if not has_y and not has_t:
        return None

    # Determine scenario and optional next-match info
    if has_y and has_t:
        scenario = "normal"
        next_match = None
        next_date_str = None
    elif has_y and not has_t:
        scenario = "pausa"
        next_match = client.get_next_match(settings.timezone)
        next_date_str = (
            format_spanish_date(next_match.utc_date, settings.timezone)
            if next_match
            else None
        )
    else:  # not has_y and has_t → "reanudacion"
        scenario = "reanudacion"
        next_match = None
        next_date_str = None

    # 2. Porra ranking (degrade gracefully on error)
    try:
        predictions = pred_loader.load(settings.predictions_path)
        ranking = engine.compute_general_ranking(predictions, client, official=False)
    except Exception as exc:
        log.warning("generate_daily_update: porra ranking failed: %s", exc)
        ranking = []

    current_positions = {r.username: i + 1 for i, r in enumerate(ranking)}
    names = {r.username: r.display_name for r in ranking}

    # 3. Snapshot / movements
    today_local_date = datetime.now(pytz.timezone(settings.timezone)).strftime(
        "%Y-%m-%d"
    )
    snapshot_path = f"{settings.state_dir}/porra_snapshot.json"
    baseline, _ = _snapshot.update_and_diff(
        snapshot_path, today_local_date, current_positions
    )
    movements = _snapshot.compute_movements(baseline or {}, current_positions, names)
    first_snapshot = baseline is None

    # 4. TVE broadcasts (degrade gracefully — a RTVE failure must never break the update)
    tve_by_key: dict[str, str] = {}
    try:
        from worldcup_bot.tve import load_tve_broadcasts, tve_channel_for
        broadcasts = await asyncio.to_thread(
            load_tve_broadcasts, tve_enabled=getattr(settings, "tve_enabled", True)
        )
        for m in today:
            label = tve_channel_for(m, broadcasts)
            if label:
                tve_by_key[f"{m.home_tla}-{m.away_tla}"] = label
    except Exception as exc:
        log.warning("generate_daily_update: TVE fetch failed: %s", exc)

    # 5. AI call
    user_msg = build_ai_user_message(
        yesterday,
        today,
        ranking,
        movements,
        settings.timezone,
        first_snapshot,
        scenario=scenario,
        next_match=next_match,
        next_date_str=next_date_str,
    )
    try:
        raw = await ai.complete(_SYSTEM, user_msg, max_completion_tokens=1500)
        today_notes, standings_comment = parse_ai_json(raw)
    except Exception as exc:
        log.warning(
            "generate_daily_update: AI call failed: %s — rendering without AI content",
            exc,
        )
        today_notes, standings_comment = {}, ""

    # 6. Render HTML
    participant_names = [r.display_name for r in ranking]
    return render_message(
        yesterday,
        today,
        settings.timezone,
        today_notes,
        standings_comment,
        scenario=scenario,
        next_date_str=next_date_str,
        participant_names=participant_names,
        tve_by_key=tve_by_key or None,
    )
