"""Tests for the new score-based goal message formatters in reddit.notifier.

Covers format_new_goal_message (scorer present/absent, flags, bold team, escaping)
and format_disallowed_message.
"""

from __future__ import annotations

import pytest

from worldcup_bot.reddit.notifier import format_disallowed_message, format_new_goal_message


# ══════════════════════════════════════════════════════════════════════════════
# format_new_goal_message
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatNewGoalMessage:
    def test_goal_emoji_present(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "⚽" in text

    def test_scoring_team_bold(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "<b>France</b>" in text

    def test_score_in_message(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=2,
            away_score=1,
        )
        assert "2-1" in text

    def test_both_team_names_present(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "France" in text
        assert "Senegal" in text

    def test_scorer_present_when_provided(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
            scorer="Kylian Mbappé",
            minute="66",
        )
        assert "Kylian Mbappé" in text
        assert "66" in text
        assert "🎯" in text

    def test_scorer_absent_when_not_provided(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "🎯" not in text

    def test_scorer_without_minute(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
            scorer="Mbappé",
            minute=None,
        )
        assert "Mbappé" in text
        # No parenthesised minute should appear
        assert "('" not in text

    def test_flag_present_when_tla_known(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
            home_tla="FRA",
            away_tla="SEN",
        )
        # France flag 🇫🇷
        assert "\U0001f1eb\U0001f1f7" in text or "🇫🇷" in text

    def test_no_tla_no_crash(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "France" in text
        assert "1-0" in text

    def test_html_escaping_of_team_names(self):
        text = format_new_goal_message(
            scoring_team="Team & Co.",
            home_name="Team & Co.",
            away_name="Rival <Club>",
            home_score=1,
            away_score=0,
        )
        assert "&amp;" in text
        assert "&lt;" in text
        # Raw < > & must not appear unescaped
        assert "<Club>" not in text

    def test_html_escaping_of_scorer(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
            scorer="O'Brien & Smith",
        )
        assert "&amp;" in text

    def test_stoppage_time_minute(self):
        text = format_new_goal_message(
            scoring_team="France",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
            scorer="Mbappé",
            minute="90+5",
        )
        assert "90+5" in text

    def test_away_team_scored(self):
        text = format_new_goal_message(
            scoring_team="Senegal",
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=1,
            home_tla="FRA",
            away_tla="SEN",
        )
        assert "<b>Senegal</b>" in text
        assert "1-1" in text


# ══════════════════════════════════════════════════════════════════════════════
# format_disallowed_message
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatDisallowedMessage:
    def test_var_emoji_and_text(self):
        text = format_disallowed_message(
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "❌" in text
        assert "VAR" in text

    def test_score_in_message(self):
        text = format_disallowed_message(
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "1-0" in text

    def test_team_names_present(self):
        text = format_disallowed_message(
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "France" in text
        assert "Senegal" in text

    def test_flag_present_when_tla_known(self):
        text = format_disallowed_message(
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
            home_tla="FRA",
            away_tla="SEN",
        )
        assert "\U0001f1eb\U0001f1f7" in text or "🇫🇷" in text

    def test_no_tla_no_crash(self):
        text = format_disallowed_message(
            home_name="France",
            away_name="Senegal",
            home_score=1,
            away_score=0,
        )
        assert "France" in text

    def test_html_escaping(self):
        text = format_disallowed_message(
            home_name="Team & Co.",
            away_name="Rival <FC>",
            home_score=0,
            away_score=0,
        )
        assert "&amp;" in text
        assert "&lt;" in text
        assert "<FC>" not in text
