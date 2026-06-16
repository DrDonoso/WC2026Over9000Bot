"""Notification formatting for live goal events.

Builds Telegram message text and inline keyboard for new goals discovered in
Reddit match threads.
"""

from __future__ import annotations

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
