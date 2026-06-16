"""Tests for reddit.notifier — goal notification formatting and silent-hour logic."""

from __future__ import annotations

from datetime import datetime

import pytest
import pytz

from worldcup_bot.reddit.models import GoalEvent
from worldcup_bot.reddit.notifier import (
    _is_silent_hour,
    _team_is_home,
    build_goal_keyboard,
    format_goal_notification,
)


# ── helpers ───────────────────────────────────────────────────────────────────

_MADRID_TZ = pytz.timezone("Europe/Madrid")


def _local_dt(hour: int, minute: int = 0) -> datetime:
    """Return a Europe/Madrid aware datetime at the given hour."""
    naive = datetime(2026, 6, 16, hour, minute, 0)
    return _MADRID_TZ.localize(naive)


def _goal(
    scorer: str = "Alexander Isak",
    scoring_team: str = "Sweden",
    home_team: str = "Sweden",
    away_team: str = "Tunisia",
    home_score: int = 2,
    away_score: int = 0,
    minute_text: str = "30",
) -> GoalEvent:
    from worldcup_bot.reddit.parser import _parse_minute_sort
    return GoalEvent(
        minute_text=minute_text,
        minute_sort=_parse_minute_sort(minute_text),
        scorer=scorer,
        scoring_team=scoring_team,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        raw="raw line",
        key=f"post1:{home_score}-{away_score}@{minute_text}:{scorer.lower()}",
    )


# ══════════════════════════════════════════════════════════════════════════════
# _is_silent_hour
# ══════════════════════════════════════════════════════════════════════════════


class TestIsSilentHour:
    def test_midnight_is_silent(self):
        assert _is_silent_hour(_local_dt(0, 0)) is True

    def test_02h_is_silent(self):
        assert _is_silent_hour(_local_dt(2, 30)) is True

    def test_07h59_is_silent(self):
        assert _is_silent_hour(_local_dt(7, 59)) is True

    def test_09h00_is_not_silent(self):
        assert _is_silent_hour(_local_dt(9, 0)) is False

    def test_15h00_is_not_silent(self):
        assert _is_silent_hour(_local_dt(15, 0)) is False

    def test_23h59_is_not_silent(self):
        assert _is_silent_hour(_local_dt(23, 59)) is False

    def test_08h59_is_still_silent(self):
        assert _is_silent_hour(_local_dt(8, 59)) is True


# ══════════════════════════════════════════════════════════════════════════════
# _team_is_home
# ══════════════════════════════════════════════════════════════════════════════


class TestTeamIsHome:
    def test_exact_match(self):
        assert _team_is_home("Sweden", "Sweden") is True

    def test_accent_insensitive(self):
        assert _team_is_home("México", "Mexico") is True

    def test_different_teams(self):
        assert _team_is_home("Tunisia", "Sweden") is False

    def test_substring_match(self):
        assert _team_is_home("United States", "United States of America") is True


# ══════════════════════════════════════════════════════════════════════════════
# format_goal_notification
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatGoalNotification:
    def test_home_scored_bracket_on_home_score(self):
        event = _goal(scoring_team="Sweden", home_team="Sweden", home_score=2, away_score=0)
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "[2]" in text
        # Away score should NOT have brackets
        assert "- 0" in text or "-0" in text

    def test_away_scored_bracket_on_away_score(self):
        event = _goal(
            scorer="Omar Rekik",
            scoring_team="Tunisia",
            home_team="Sweden",
            away_team="Tunisia",
            home_score=2,
            away_score=1,
            minute_text="43",
        )
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "[1]" in text
        assert "2" in text  # home score present without brackets

    def test_scorer_in_text(self):
        event = _goal()
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "Alexander Isak" in text

    def test_minute_in_text(self):
        event = _goal(minute_text="30")
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "30'" in text

    def test_goal_emoji_present(self):
        event = _goal()
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "⚽" in text

    def test_home_team_name_present(self):
        event = _goal()
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "Sweden" in text

    def test_away_team_name_present(self):
        event = _goal()
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "Tunisia" in text

    def test_flag_present_when_tla_known(self):
        """SWE → 🇸🇪 should appear when TLA is recognised."""
        event = _goal()
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        # flag emoji for Sweden is 🇸🇪 — just check a flag-like char is there
        # (avoid hardcoding the exact flag sequence for portability)
        assert "\U0001f1f8\U0001f1ea" in text or "🇸🇪" in text  # 🇸🇪

    def test_no_tla_works_without_flags(self):
        """When no TLA is provided the function should still return a valid string."""
        event = _goal()
        text = format_goal_notification(event)
        assert "Sweden" in text
        assert "30'" in text

    def test_stoppage_time_minute(self):
        event = _goal(minute_text="45+2")
        text = format_goal_notification(event, home_tla="SWE", away_tla="TUN")
        assert "45+2'" in text


# ══════════════════════════════════════════════════════════════════════════════
# build_goal_keyboard
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildGoalKeyboard:
    def test_returns_inline_markup(self):
        from telegram import InlineKeyboardMarkup
        kb = build_goal_keyboard("abc123def456")
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_single_button_labeled_ver_gol(self):
        kb = build_goal_keyboard("abc123def456")
        buttons = kb.inline_keyboard
        assert len(buttons) == 1
        assert len(buttons[0]) == 1
        assert buttons[0][0].text == "Ver gol"

    def test_callback_data_contains_token(self):
        kb = build_goal_keyboard("abc123def456")
        assert kb.inline_keyboard[0][0].callback_data == "vergol:abc123def456"

    def test_different_tokens_produce_different_callback_data(self):
        kb1 = build_goal_keyboard("token_aaa")
        kb2 = build_goal_keyboard("token_bbb")
        assert kb1.inline_keyboard[0][0].callback_data != kb2.inline_keyboard[0][0].callback_data
