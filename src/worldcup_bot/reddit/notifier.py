"""Notification formatting for live goal events.

Builds Telegram message text and inline keyboard for goal notifications.
format_new_goal_message / format_disallowed_message are used by the score-based
detector (block 1).  format_goal_notification / build_goal_keyboard are kept for
cmd_simula_gol and the block-2 "Ver gol" callback.
"""

from __future__ import annotations

import html
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from worldcup_bot.reddit.models import GoalEvent


# ── silent-hour helper ────────────────────────────────────────────────────────


def _is_silent_hour(now_local: datetime) -> bool:
    """Return True if the local hour falls in [00:00, 09:00) — send silently.

    Covers early-morning US-time World Cup matches so sleeping Madrid users
    are not woken up by goal notifications.
    """
    return 0 <= now_local.hour < 9


# ── team-match helper ─────────────────────────────────────────────────────────


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _team_is_home(scoring_team: str, home_team: str) -> bool:
    """Return True if *scoring_team* fuzzy-matches *home_team*."""
    na = _strip_accents(scoring_team).lower()
    nb = _strip_accents(home_team).lower()
    return (
        na == nb
        or na in nb
        or nb in na
        or SequenceMatcher(None, na, nb).ratio() >= 0.80
    )


# ── message formatting ────────────────────────────────────────────────────────


def format_goal_notification(
    event: GoalEvent,
    home_tla: str = "",
    away_tla: str = "",
) -> str:
    """Build the Telegram goal notification text for a GoalEvent.

    Uses r/soccer bracket convention: the scoring team's score is wrapped
    in ``[N]``.  Flag emojis are included when a TLA is available.

    Example (home scored):
        ⚽️ ¡GOL!  🇸🇪 Sweden [2] - 0 Tunisia 🇹🇳
           Alexander Isak  30'
    """
    from worldcup_bot.bot.formatters import team_flag  # avoid circular import at module level

    home_flag = team_flag(home_tla) if home_tla else ""
    away_flag = team_flag(away_tla) if away_tla else ""

    home_scored = _team_is_home(event.scoring_team, event.home_team)

    if home_scored:
        score_str = f"[{event.home_score}] - {event.away_score}"
    else:
        score_str = f"{event.home_score} - [{event.away_score}]"

    home_label = f"{home_flag} {event.home_team}".strip()
    away_label = f"{event.away_team} {away_flag}".strip()

    line1 = f"⚽️ ¡GOL!  {home_label} {score_str} {away_label}"
    line2 = f"   {event.scorer}  {event.minute_text}'"
    return f"{line1}\n{line2}"


def build_goal_keyboard(token: str) -> InlineKeyboardMarkup:
    """Return the inline keyboard shown with every goal notification.

    *token* is a short stable id (``hashlib.sha1(key)[:12]``) stored in
    ``bot_data["goal_clips"]`` so the callback handler can look up the goal.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Ver gol", callback_data=f"vergol:{token}")]]
    )


# ── score-based detection formatters (block 1) ───────────────────────────────


def format_new_goal_message(
    scoring_team: str,
    home_name: str,
    away_name: str,
    home_score: int,
    away_score: int,
    home_tla: str = "",
    away_tla: str = "",
    scorer: str | None = None,
    minute: str | None = None,
) -> str:
    """Build the HTML goal notification for the score-based detector.

    Format::

        ⚽ <b>¡GOOOL!</b> 🇫🇷 <b>France</b>
        🇫🇷 France 1-0 Senegal 🇸🇳
        🎯 Kylian Mbappé (66')   ← only when scorer is known

    All variable text is html.escaped.  The scoring team's name is bold.
    """
    from worldcup_bot.bot.formatters import team_flag  # avoid circular import

    scoring_is_home = _team_is_home(scoring_team, home_name)
    scoring_tla = home_tla if scoring_is_home else away_tla
    scoring_flag = team_flag(scoring_tla) if scoring_tla else ""
    home_flag = team_flag(home_tla) if home_tla else ""
    away_flag = team_flag(away_tla) if away_tla else ""

    team_esc = html.escape(scoring_team, quote=False)
    home_esc = html.escape(home_name, quote=False)
    away_esc = html.escape(away_name, quote=False)

    line1_parts = ["⚽ <b>¡GOOOL!</b>"]
    if scoring_flag:
        line1_parts.append(scoring_flag)
    line1_parts.append(f"<b>{team_esc}</b>")
    line1 = " ".join(line1_parts)

    line2_parts = []
    if home_flag:
        line2_parts.append(home_flag)
    line2_parts.append(f"{home_esc} {home_score}-{away_score} {away_esc}")
    if away_flag:
        line2_parts.append(away_flag)
    line2 = " ".join(line2_parts)

    lines = [line1, line2]

    if scorer:
        scorer_esc = html.escape(scorer, quote=False)
        scorer_line = f"🎯 {scorer_esc}"
        if minute:
            minute_esc = html.escape(minute, quote=False)
            scorer_line += f" ({minute_esc}')"
        lines.append(scorer_line)

    return "\n".join(lines)


def format_disallowed_message(
    home_name: str,
    away_name: str,
    home_score: int,
    away_score: int,
    home_tla: str = "",
    away_tla: str = "",
) -> str:
    """Build the HTML VAR-disallowed goal notification.

    Format::

        ❌ Gol anulado (VAR) — 🇫🇷 France 1-0 Senegal 🇸🇳
    """
    from worldcup_bot.bot.formatters import team_flag  # avoid circular import

    home_flag = team_flag(home_tla) if home_tla else ""
    away_flag = team_flag(away_tla) if away_tla else ""

    home_esc = html.escape(home_name, quote=False)
    away_esc = html.escape(away_name, quote=False)

    parts = ["❌ Gol anulado (VAR) —"]
    if home_flag:
        parts.append(home_flag)
    parts.append(f"{home_esc} {home_score}-{away_score} {away_esc}")
    if away_flag:
        parts.append(away_flag)
    return " ".join(parts)
