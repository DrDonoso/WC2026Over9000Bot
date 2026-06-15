"""Message formatting helpers for Telegram output.

Depends only on data/tla_map — never imports api/ or porra/.
"""

from __future__ import annotations

from datetime import datetime, timezone

import flag as flag_lib
import pytz

from worldcup_bot.api.models import Match, Standing
from worldcup_bot.data.tla_map import tla_to_iso

# ── flag rendering ────────────────────────────────────────────────────────────


def team_flag(tla: str) -> str:
    """Return flag emoji for a TLA, empty string if unknown."""
    iso = tla_to_iso(tla)
    if not iso:
        return ""
    try:
        return flag_lib.flag(iso)
    except Exception:
        return ""


def team_label(tla: str, name: str | None = None) -> str:
    """Return '<flag> <name>' or '<flag> <TLA>' if name is None."""
    f = team_flag(tla)
    label = name or tla
    return f"{f} {label}".strip()


# ── match formatting ──────────────────────────────────────────────────────────


def format_match(match: Match, tz_name: str = "Europe/Madrid") -> str:
    """Format a single match for display."""
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
        return (
            f"{home_fl} {match.home_name} vs {match.away_name} {away_fl}"
            f" - ⌚ {local_time}"
        )


def format_match_with_date(match: Match, tz_name: str = "Europe/Madrid") -> str:
    """Format match with date prefix (dd-mm-YYYY)."""
    date_str = _format_date(match.utc_date, tz_name)
    return f"{date_str}: {format_match(match, tz_name)}"


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
    """Format a list of UserRankEntry into a message string."""
    if not rows:
        return "No hay datos de ranking aún."

    lines = [title, ""]
    for i, row in enumerate(rows, start=1):
        lines.append(f"{i}. {row.display_name}: {row.total_score:.1f} pts")

    top_score = rows[0].total_score
    leaders = [r for r in rows if r.total_score == top_score]

    if len(leaders) == 1:
        winner = leaders[0]
        lines.append(f"\n🏆 Líder: {winner.display_name} — {top_score:.1f} pts 🏆")
    else:
        names = ", ".join(r.display_name for r in leaders)
        lines.append(f"\n🏆 Empate en primer lugar: {names} — {top_score:.1f} pts 🏆")

    return "\n".join(lines)


def format_user_detail(detail: dict) -> str:
    """Format per-user scoring detail for /listaaciertos (official) or /listaaciertosactual (provisional)."""
    is_official = detail.get("official", False)
    display_name = detail["display_name"]
    if is_official:
        lines = [f"📊 Aciertos (oficial) de {display_name}:", ""]
    else:
        lines = [f"📊 Aciertos (provisional, a día de hoy) de {display_name}:", ""]

    lines.append("*Fase de Grupos:*")
    group_detail = sorted(detail.get("group_detail", []), key=lambda d: (d.get("group", ""), d.get("predicted_pos", 0)))
    for d in group_detail:
        if d.get("note") == "wildcard":
            continue
        team = d["team"]
        f = team_flag(team)
        pred = d.get("predicted_pos", "?")
        actual = d.get("actual_pos") or "?"
        pts = d.get("points", 0)
        note_map = {"exacto": "✅ +1", "clasifica": "🔶 +0.5", "fallo": "❌ 0", "no_data": "⏳ 0"}
        note = note_map.get(d.get("note", ""), "")
        lines.append(f"  Grupo {d['group']} {f}{team}: pred={pred} real={actual} {note} ({pts}pt)")

    lines.append(f"\n*Total grupos:* {detail['group_score']:.1f} pts")
    lines.append("")

    if detail.get("knockout_detail"):
        from worldcup_bot.data.stages import KNOCKOUT_STAGES, STAGE_YAML_KEYS

        lines.append("*Fases eliminatorias:*")
        current_stage = ""
        for d in detail.get("knockout_detail", []):
            stg = d.get("stage", "")
            if stg != current_stage:
                current_stage = stg
                display = d.get("display") or stg
                lines.append(f"  {display}:")
            team = d["team"]
            if team == "**":
                continue
            f = team_flag(team)
            note_map2 = {"acierto": "✅", "fallo": "❌", "wildcard": ""}
            note = note_map2.get(d.get("note", ""), "")
            pts = d.get("points", 0)
            lines.append(f"    {f}{team} {note} ({pts}pt)")

        lines.append(f"\n*Total eliminatorias:* {detail['knockout_score']:.1f} pts")
        lines.append("")

    lines.append(f"*TOTAL: {detail['total_score']:.1f} pts*")

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
