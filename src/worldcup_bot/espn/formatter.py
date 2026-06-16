"""ESPN match stats formatter — builds an HTML card in Spanish with emojis."""

from __future__ import annotations

import html
import logging

from worldcup_bot.bot.formatters import team_flag

log = logging.getLogger(__name__)


def _float_val(stats: dict, key: str) -> float | None:
    v = stats.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int_val(stats: dict, key: str) -> int | None:
    f = _float_val(stats, key)
    return int(f) if f is not None else None


def _compute_pass_pct(stats: dict) -> float | None:
    """Derive pass-accuracy percentage.

    Tries passPct first (0-1 fraction → × 100).
    Falls back to accuratePasses / totalPasses × 100.
    """
    v = _float_val(stats, "passPct")
    if v is not None:
        return v * 100.0

    acc = _float_val(stats, "accuratePasses")
    total = _float_val(stats, "totalPasses")
    if acc is not None and total and total > 0:
        return (acc / total) * 100.0
    return None


def format_match_stats(match, stats: dict) -> str:
    """Build an HTML stats card for a finished match.

    ``match`` must have: home_tla, away_tla, home_name, away_name,
    home_score, away_score.
    ``stats`` is the dict returned by ESPNClient.get_match_stats().
    """
    hs_data = stats.get("home", {}).get("stats", {})
    as_data = stats.get("away", {}).get("stats", {})

    home_name = html.escape(match.home_name, quote=False)
    away_name = html.escape(match.away_name, quote=False)
    home_flag = team_flag(match.home_tla)
    away_flag = team_flag(match.away_tla)
    h_score = match.home_score if match.home_score is not None else 0
    a_score = match.away_score if match.away_score is not None else 0

    header = (
        f"📊 <b>Estadísticas — "
        f"{home_flag} {home_name} {h_score}-{a_score} {away_name} {away_flag}</b>"
    )

    rows = [header, ""]

    def add_row(emoji: str, label: str, h_val: str | None, a_val: str | None) -> None:
        if h_val is None and a_val is None:
            return
        rows.append(f"{emoji} {label}: {h_val or '—'} – {a_val or '—'}")

    # ── Posesión ──────────────────────────────────────────────────────────────
    h_poss = _float_val(hs_data, "possessionPct")
    a_poss = _float_val(as_data, "possessionPct")
    if h_poss is not None or a_poss is not None:
        add_row(
            "🔵",
            "Posesión",
            f"{round(h_poss)}%" if h_poss is not None else None,
            f"{round(a_poss)}%" if a_poss is not None else None,
        )

    # ── Tiros ─────────────────────────────────────────────────────────────────
    h_shots = _int_val(hs_data, "totalShots")
    a_shots = _int_val(as_data, "totalShots")
    h_sot = _int_val(hs_data, "shotsOnTarget")
    a_sot = _int_val(as_data, "shotsOnTarget")
    if h_shots is not None or a_shots is not None:
        h_str = f"{h_shots} ({h_sot} a puerta)" if h_shots is not None else None
        a_str = f"{a_shots} ({a_sot} a puerta)" if a_shots is not None else None
        add_row("🎯", "Tiros", h_str, a_str)

    # ── Córners ───────────────────────────────────────────────────────────────
    h_corn = _int_val(hs_data, "wonCorners")
    a_corn = _int_val(as_data, "wonCorners")
    add_row(
        "🚩",
        "Córners",
        str(h_corn) if h_corn is not None else None,
        str(a_corn) if a_corn is not None else None,
    )

    # ── Faltas ────────────────────────────────────────────────────────────────
    h_fouls = _int_val(hs_data, "foulsCommitted")
    a_fouls = _int_val(as_data, "foulsCommitted")
    add_row(
        "⚠️",
        "Faltas",
        str(h_fouls) if h_fouls is not None else None,
        str(a_fouls) if a_fouls is not None else None,
    )

    # ── Amarillas ─────────────────────────────────────────────────────────────
    h_yc = _int_val(hs_data, "yellowCards")
    a_yc = _int_val(as_data, "yellowCards")
    add_row(
        "🟨",
        "Amarillas",
        str(h_yc) if h_yc is not None else None,
        str(a_yc) if a_yc is not None else None,
    )

    # ── Rojas (omit if both 0) ────────────────────────────────────────────────
    h_rc = _int_val(hs_data, "redCards")
    a_rc = _int_val(as_data, "redCards")
    if not (h_rc == 0 and a_rc == 0):
        add_row(
            "🟥",
            "Rojas",
            str(h_rc) if h_rc is not None else None,
            str(a_rc) if a_rc is not None else None,
        )

    # ── Fueras de juego ───────────────────────────────────────────────────────
    h_off = _int_val(hs_data, "offsides")
    a_off = _int_val(as_data, "offsides")
    add_row(
        "🔰",
        "Fueras de juego",
        str(h_off) if h_off is not None else None,
        str(a_off) if a_off is not None else None,
    )

    # ── Paradas ───────────────────────────────────────────────────────────────
    h_saves = _int_val(hs_data, "saves")
    a_saves = _int_val(as_data, "saves")
    add_row(
        "🧤",
        "Paradas",
        str(h_saves) if h_saves is not None else None,
        str(a_saves) if a_saves is not None else None,
    )

    # ── Precisión de pase ─────────────────────────────────────────────────────
    h_pass = _compute_pass_pct(hs_data)
    a_pass = _compute_pass_pct(as_data)
    if h_pass is not None or a_pass is not None:
        add_row(
            "🅿️",
            "Precisión de pase",
            f"{round(h_pass)}%" if h_pass is not None else None,
            f"{round(a_pass)}%" if a_pass is not None else None,
        )

    return "\n".join(rows)
