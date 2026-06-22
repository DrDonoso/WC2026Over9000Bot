"""Message formatting helpers for Telegram output.

Depends only on data/tla_map — never imports api/ or porra/.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Iterable

import flag as flag_lib
import pytz
from telegram import InlineKeyboardButton

from worldcup_bot.api.models import Match, Standing
from worldcup_bot.data.tla_map import tla_to_iso

# ── person-name bolding ───────────────────────────────────────────────────────


def bold_person_names(text: str, names: Iterable[str]) -> str:
    """HTML-escape *text* and wrap each known participant name in <b>…</b>.

    Matching rules:
    - Names are tried longest-first to prevent shorter names from shadowing
      multi-word names (e.g. "Alice" won't eat into "Alice Smith").
    - Unicode word boundaries (``(?<!\\w)`` / ``(?!\\w)``) so accented names
      like Peñalver or Tarragó and multi-word names like "Maria Tarrago" match
      correctly, while substrings inside other words are NOT bolded.
    - A single regex pass prevents double-wrapping within one call.
    - Input *text* is HTML-escaped before matching; the returned string is
      HTML-safe and ready for ``parse_mode="HTML"``.
    """
    escaped = html.escape(text, quote=False)
    clean = sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)
    if not clean:
        return escaped
    esc_names = [html.escape(n, quote=False) for n in clean]
    alt = "|".join(re.escape(n) for n in esc_names)
    pattern = re.compile(rf"(?<!\w)({alt})(?!\w)", re.UNICODE)
    return pattern.sub(r"<b>\1</b>", escaped)


# ── flag rendering ────────────────────────────────────────────────────────────

BELOVED_TEAMS: set[str] = {"PAN", "UZB", "CUW"}  # Panamá, Uzbekistán, Curaçao — el cariño del bot
_LOVE = "❤️"


def set_beloved_teams(tlas) -> None:
    """Set the global BELOVED_TEAMS from an iterable of TLA strings.

    Called once at startup (from build_app) so the env-configured list takes
    effect across all renderers.  Safe to call multiple times (e.g. in tests).
    """
    global BELOVED_TEAMS
    BELOVED_TEAMS = {t.strip().upper() for t in tlas if t and t.strip()}


def team_flag(tla: str) -> str:
    """Return flag emoji for a TLA, empty string if unknown.

    For beloved teams (BELOVED_TEAMS) the heart emoji is appended to the flag.
    """
    iso = tla_to_iso(tla)
    if not iso:
        return ""
    try:
        f = flag_lib.flag(iso)
    except Exception:
        return ""
    if f and tla.strip().upper() in BELOVED_TEAMS:
        return f + _LOVE
    return f


def team_label(tla: str, name: str | None = None) -> str:
    """Return '<flag> <name>' or '<flag> <TLA>' if name is None."""
    f = team_flag(tla)
    label = name or tla
    return f"{f} {label}".strip()


# ── match formatting ──────────────────────────────────────────────────────────


def format_match(match: Match, tz_name: str = "Europe/Madrid", *, tve_label: str | None = None) -> str:
    """Format a single match for display.

    tve_label: when provided and the match is SCHEDULED, appends '📺 {tve_label}'.
    """
    home_fl = team_flag(match.home_tla)
    away_fl = team_flag(match.away_tla)

    if match.status == "FINISHED":
        h = match.home_score if match.home_score is not None else 0
        a = match.away_score if match.away_score is not None else 0
        return (
            f"{home_fl} {match.home_name} {h} - {a} {match.away_name} {away_fl} 🏁"
        )
    elif match.status in ("IN_PLAY", "PAUSED"):
        h = match.home_score if match.home_score is not None else "-"
        a = match.away_score if match.away_score is not None else "-"
        return (
            f"{home_fl} {match.home_name} {h} - {a} {match.away_name} {away_fl} ⚽️"
        )
    else:
        # Scheduled — show local time
        local_time = _format_local_time(match.utc_date, tz_name)
        base = (
            f"{home_fl} {match.home_name} vs {match.away_name} {away_fl}"
            f" - ⌚ {local_time}"
        )
        if tve_label:
            return f"{base} 📺 {tve_label}"
        return base


def format_match_with_date(match: Match, tz_name: str = "Europe/Madrid", *, tve_label: str | None = None) -> str:
    """Format match with date prefix (dd-mm-YYYY)."""
    date_str = _format_date(match.utc_date, tz_name)
    return f"{date_str}: {format_match(match, tz_name, tve_label=tve_label)}"


# ── standings formatting ──────────────────────────────────────────────────────


def format_standings(standings: list[Standing], live_tlas: set[str] | None = None) -> str:
    """Format all group standings as a multi-line string."""
    if not standings:
        return "No hay clasificaciones disponibles."

    by_group: dict[str, list[Standing]] = {}
    for s in standings:
        by_group.setdefault(s.group, []).append(s)

    lines: list[str] = []
    for group in sorted(by_group):
        group_label = group.replace("GROUP_", "Grupo ") if group.startswith("GROUP_") else group
        lines.append(f"Clasificación del {group_label}:")
        for team in sorted(by_group[group], key=lambda x: x.position):
            live_icon = " ⚽️" if (live_tlas and team.tla in live_tlas) else ""
            lines.append(
                f"{team.position}. {team_flag(team.tla)} {team.team_name}"
                f" - {team.points} puntos{live_icon}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


# ── ranking formatting ────────────────────────────────────────────────────────


def participant_photo_url(username: str, base_url: str) -> str:
    """Build the photo URL for a participant from their username (the predictions.yml key)."""
    return f"{base_url.rstrip('/')}/{username}.png"


def format_general_ranking(rows: list, title: str = "🏆 Ranking General:") -> str:
    """Format a list of UserRankEntry into an HTML message string."""
    if not rows:
        return "No hay datos de ranking aún."

    lines = [title, ""]
    for i, row in enumerate(rows, start=1):
        dname_esc = html.escape(row.display_name, quote=False)
        lines.append(f"{i}. <b>{dname_esc}</b>: {row.total_score:.1f} pts")

    top_score = rows[0].total_score
    leaders = [r for r in rows if r.total_score == top_score]

    if len(leaders) == 1:
        winner = leaders[0]
        dname_esc = html.escape(winner.display_name, quote=False)
        lines.append(f"\n🏆 Líder: <b>{dname_esc}</b> — {top_score:.1f} pts 🏆")
    else:
        names = ", ".join(f"<b>{html.escape(r.display_name, quote=False)}</b>" for r in leaders)
        lines.append(f"\n🏆 Empate en primer lugar: {names} — {top_score:.1f} pts 🏆")

    return "\n".join(lines)


def format_user_detail(detail: dict) -> str:
    """Format per-user scoring detail for /listaaciertos (official) or /listaaciertosactual (provisional).

    Returns HTML-safe text (ready for parse_mode="HTML").
    """
    is_official = detail.get("official", False)
    display_name = html.escape(detail["display_name"], quote=False)
    if is_official:
        lines = [f"📊 Aciertos (oficial) de <b>{display_name}</b>:", ""]
    else:
        lines = [f"📊 Aciertos (provisional, a día de hoy) de <b>{display_name}</b>:", ""]

    lines.append("<b>Fase de Grupos:</b>")
    group_detail = sorted(detail.get("group_detail", []), key=lambda d: (d.get("group", ""), d.get("predicted_pos", 0)))
    for d in group_detail:
        if d.get("note") == "wildcard":
            continue
        team = html.escape(str(d["team"]), quote=False)
        f = team_flag(team)
        pred = d.get("predicted_pos", "?")
        actual = d.get("actual_pos") or "?"
        pts = d.get("points", 0)
        note_map = {"exacto": "✅ +1", "clasifica": "🔶 +0.5", "fallo": "❌ 0", "no_data": "⏳ 0"}
        note = note_map.get(d.get("note", ""), "")
        lines.append(f"  Grupo {html.escape(str(d['group']), quote=False)} {f}{team}: pred={pred} real={actual} {note} ({pts}pt)")

    lines.append(f"\n<b>Total grupos:</b> {detail['group_score']:.1f} pts")
    lines.append("")

    if detail.get("knockout_detail"):
        from worldcup_bot.data.stages import KNOCKOUT_STAGES, STAGE_YAML_KEYS

        lines.append("<b>Fases eliminatorias:</b>")
        current_stage = ""
        for d in detail.get("knockout_detail", []):
            stg = d.get("stage", "")
            if stg != current_stage:
                current_stage = stg
                display = html.escape(str(d.get("display") or stg), quote=False)
                lines.append(f"  {display}:")
            team = d["team"]
            if team == "**":
                continue
            f = team_flag(team)
            note_map2 = {"acierto": "✅", "fallo": "❌", "wildcard": ""}
            note = note_map2.get(d.get("note", ""), "")
            pts = d.get("points", 0)
            lines.append(f"    {f}{html.escape(str(team), quote=False)} {note} ({pts}pt)")

        lines.append(f"\n<b>Total eliminatorias:</b> {detail['knockout_score']:.1f} pts")
        lines.append("")

    lines.append(f"<b>TOTAL: {detail['total_score']:.1f} pts</b>")

    # Mode-specific footer
    finished_groups = detail.get("finished_groups")
    total_groups = detail.get("total_groups")
    if is_official:
        if finished_groups is not None and total_groups is not None and finished_groups < total_groups:
            lines.append(f"\n📋 Grupos cerrados: {finished_groups}/{total_groups} — solo cuentan los ya cerrados.")
            lines.append("ℹ️ Usa /listaaciertosactual para ver la provisional.")
    else:
        started_groups = detail.get("started_groups")
        if started_groups is not None and started_groups < detail["total_groups"]:
            lines.append(f"\n📋 Grupos en juego: {started_groups}/{detail['total_groups']} — los grupos sin empezar aún no puntúan.")
        lines.append("\nℹ️ Provisional: posiciones en vivo, pueden cambiar. /listaaciertos = oficial (solo cerrados).")

    return "\n".join(lines)


# ── live match detail formatting ─────────────────────────────────────────────


def format_live_match_detail(
    match: Match,
    events: dict,
    tz_name: str = "Europe/Madrid",
) -> str:
    """Format a live match with enriched event details (goals, cards, subs).

    Produces a plain-text (no HTML) message block for /endirecto.
    Resilient to missing or malformed keys in events dict.
    """
    home_fl = team_flag(match.home_tla)
    away_fl = team_flag(match.away_tla)
    hs = match.home_score if match.home_score is not None else 0
    as_ = match.away_score if match.away_score is not None else 0

    evt = events if isinstance(events, dict) else {}
    minute = evt.get("minute")

    lines: list[str] = []
    header = "🔴 EN DIRECTO"
    if minute:
        header += f" · {minute}'"
    lines.append(header)
    lines.append(f"{home_fl} {match.home_name} {hs}-{as_} {match.away_name} {away_fl}")

    goals = evt.get("goals", [])
    if isinstance(goals, list) and goals:
        lines.append("")
        lines.append("⚽ Goles")
        for g in goals:
            if not isinstance(g, dict):
                continue
            lines.append(
                f"  {g.get('minute', '?')}' {g.get('scorer', '?')} ({g.get('team', '?')})"
            )

    cards = evt.get("cards", [])
    if isinstance(cards, list) and cards:
        lines.append("")
        lines.append("🟨 Tarjetas")
        for c in cards:
            if not isinstance(c, dict):
                continue
            card_emoji = "🟥" if c.get("type", "").lower() == "red" else "🟨"
            lines.append(
                f"  {c.get('minute', '?')}' {card_emoji} {c.get('player', '?')} ({c.get('team', '?')})"
            )

    subs = evt.get("subs", [])
    if isinstance(subs, list) and subs:
        lines.append("")
        lines.append("🔄 Cambios")
        for s in subs:
            if not isinstance(s, dict):
                continue
            lines.append(
                f"  {s.get('minute', '?')}' {s.get('in', '?')} ▶ {s.get('out', '?')} ({s.get('team', '?')})"
            )

    return "\n".join(lines)


_ED_SECTION_ORDER = ["tarjetas", "alineacion", "cambios"]
_ED_SECTION_LABELS = {
    "tarjetas": "🟨 Tarjetas",
    "alineacion": "👥 Alineación",
    "cambios": "🔄 Cambios",
}
_ED_SECTION_CODES = {"tarjetas": "t", "alineacion": "l", "cambios": "c"}


def render_endirecto(snap: dict) -> tuple[str, list]:
    token = snap.get("token", "")
    minute = snap.get("minute")
    home_name = snap.get("home_name", "")
    away_name = snap.get("away_name", "")
    home_tla = snap.get("home_tla", "")
    away_tla = snap.get("away_tla", "")
    home_flag = team_flag(home_tla)
    away_flag = team_flag(away_tla)
    hs = snap.get("home_score")
    as_ = snap.get("away_score")
    hs = 0 if hs is None else hs
    as_ = 0 if as_ is None else as_
    revealed = set(snap.get("revealed", []))

    lines = ["🔴 EN DIRECTO" + (f" · {minute}'" if minute else "")]
    lines.append(f"{home_flag} {home_name} {hs}-{as_} {away_name} {away_flag}")

    lines.append("")
    lines.append("⚽ Goles")
    goals = snap.get("goals", [])
    if isinstance(goals, list) and goals:
        for g in goals:
            if not isinstance(g, dict):
                continue
            lines.append(f"  {g['minute']}' {g['scorer']} ({g['team']})")
    else:
        lines.append("  Sin goles todavía")

    if "tarjetas" in revealed:
        lines.append("")
        lines.append("🟨 Tarjetas")
        cards = snap.get("cards", [])
        if isinstance(cards, list):
            for c in cards:
                if not isinstance(c, dict):
                    continue
                emoji = "🟥" if c.get("type") == "red" else "🟨"
                lines.append(f"  {c['minute']}' {emoji} {c['player']} ({c['team']})")

    if "alineacion" in revealed:
        lines.append("")
        lines.append("👥 Alineación actual")
        lineup = snap.get("lineup", {})
        home_xi = lineup.get("home", []) if isinstance(lineup, dict) else []
        away_xi = lineup.get("away", []) if isinstance(lineup, dict) else []
        lines.append(f"{home_flag} {home_name}: {', '.join(home_xi)}")
        lines.append(f"{away_flag} {away_name}: {', '.join(away_xi)}")

    if "cambios" in revealed:
        lines.append("")
        lines.append("🔄 Cambios")
        subs = snap.get("subs", [])
        if isinstance(subs, list):
            for s in subs:
                if not isinstance(s, dict):
                    continue
                lines.append(f"  {s['minute']}' {s['in']} ▶ {s['out']} ({s['team']})")

    text = "\n".join(lines)
    not_revealed = [section for section in _ED_SECTION_ORDER if section not in revealed]
    if not not_revealed:
        return text, []
    return (
        text,
        [[
            InlineKeyboardButton(
                _ED_SECTION_LABELS[section],
                callback_data=f"ed|{token}|{_ED_SECTION_CODES[section]}",
            )
            for section in not_revealed
        ]],
    )


# ── private helpers ───────────────────────────────────────────────────────────


def _format_local_time(utc_date: str, tz_name: str) -> str:
    try:
        utc_dt = datetime.strptime(utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        local_tz = pytz.timezone(tz_name)
        local_dt = utc_dt.astimezone(local_tz)
        return local_dt.strftime("%H:%M")
    except (ValueError, Exception):
        return "?"


def _format_date(utc_date: str, tz_name: str = "Europe/Madrid") -> str:
    try:
        utc_dt = datetime.strptime(utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        local_tz = pytz.timezone(tz_name)
        local_dt = utc_dt.astimezone(local_tz)
        return local_dt.strftime("%d-%m-%Y")
    except (ValueError, Exception):
        return "?"
