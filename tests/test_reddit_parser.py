"""Tests for reddit.parser — goal event extraction from match thread selftexts."""

from __future__ import annotations

import pytest

from worldcup_bot.reddit.models import GoalEvent
from worldcup_bot.reddit.parser import parse_goal_events

# ── fixture: Sweden vs Tunisia sample selftext ────────────────────────────────

SWEDEN_TUNISIA_SELFTEXT = """\
**MATCH EVENTS** | via ESPN

**7'** ⚽ **Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) right footed shot from outside the box...**
**30'** ⚽ **Goal! Sweden 2, Tunisia 0. Alexander Isak (Sweden) ... Assisted by Viktor Gyökeres...**
**43'** ⚽ **Goal! Sweden 2, Tunisia 1. Omar Rekik (Tunisia) header ...**
**54'** 🟨 Rani Khedira (Tunisia) is shown the yellow card...
**59'** ⚽ **Goal! Sweden 3, Tunisia 1. Viktor Gyökeres (Sweden) ...**
"""

# Stoppage-time goal
STOPPAGE_SELFTEXT = """\
**45+2'** ⚽ **Goal! Brazil 1, Argentina 0. Gabriel Jesus (Brazil) header...**
**90+3'** ⚽ **Goal! Brazil 2, Argentina 0. Rodrygo (Brazil) right foot...**
"""

# Disallowed / VAR lines — should NOT produce goal events
DISALLOWED_SELFTEXT = """\
**23'** ⚽ **Goal disallowed! Sweden 1, Tunisia 0. Scorer (Sweden)**
**31'** 🚫 VAR — No goal: Sweden 1, Tunisia 0.
**40'** ⚽ **Goal! Sweden 1, Tunisia 0. Scorer (Sweden) Penalty missed after VAR...**
"""

# Own goal
OWN_GOAL_SELFTEXT = """\
**45+1'** ⚽ **Goal! Sweden 2, Tunisia 1. Marcus Danielson (Sweden) Own Goal, header...**
"""

# Missed penalty (no ⚽ — should not match)
PENALTY_MISSED_SELFTEXT = """\
**71'** Penalty missed! Marcus Berg (Sweden) right footed shot saved...
"""


# ══════════════════════════════════════════════════════════════════════════════
# parse_goal_events
# ══════════════════════════════════════════════════════════════════════════════


class TestParseGoalEvents:
    def test_extracts_four_goals_from_sweden_tunisia(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        assert len(events) == 4

    def test_first_goal_minute(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        assert events[0].minute_text == "7"
        assert events[0].minute_sort == 7.0

    def test_first_goal_scorer_and_team(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        assert events[0].scorer == "Yasin Ayari"
        assert events[0].scoring_team == "Sweden"

    def test_first_goal_scoreline(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        e = events[0]
        assert e.home_score == 1
        assert e.away_score == 0
        assert e.home_team == "Sweden"
        assert e.away_team == "Tunisia"

    def test_away_goal_scoring_team(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        # 43' — Omar Rekik (Tunisia)
        e = events[2]
        assert e.minute_text == "43"
        assert e.scorer == "Omar Rekik"
        assert e.scoring_team == "Tunisia"
        assert e.home_score == 2
        assert e.away_score == 1

    def test_fourth_goal_viktor_gokeres(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        e = events[3]
        assert e.minute_text == "59"
        assert "Gyökeres" in e.scorer or "Gokeres" in e.scorer or "Viktor" in e.scorer

    def test_card_line_ignored(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        # 54' yellow card should not appear
        assert all(e.minute_text != "54" for e in events)

    def test_events_in_document_order(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="swetun")
        minute_sorts = [e.minute_sort for e in events]
        assert minute_sorts == sorted(minute_sorts)

    def test_stoppage_time_minute_sort(self):
        events = parse_goal_events(STOPPAGE_SELFTEXT, post_id="braarg")
        assert len(events) == 2
        assert events[0].minute_text == "45+2"
        assert events[0].minute_sort == pytest.approx(45.02)
        assert events[1].minute_text == "90+3"
        assert events[1].minute_sort == pytest.approx(90.03)

    def test_disallowed_line_not_counted(self):
        events = parse_goal_events(DISALLOWED_SELFTEXT, post_id="test")
        assert len(events) == 0

    def test_var_no_goal_not_counted(self):
        text = "**50'** 🚫 VAR — No goal: Sweden 1, Tunisia 0. Scorer (Sweden)"
        events = parse_goal_events(text, post_id="test")
        assert len(events) == 0

    def test_own_goal_handled_without_crash(self):
        events = parse_goal_events(OWN_GOAL_SELFTEXT, post_id="own")
        assert len(events) == 1
        e = events[0]
        assert e.minute_text == "45+1"
        # Own goal — credited to Tunisia (the opponent of Sweden/Marcus Danielson)
        assert e.scoring_team == "Tunisia"
        assert "en propia" in e.scorer

    def test_penalty_missed_no_goal(self):
        events = parse_goal_events(PENALTY_MISSED_SELFTEXT, post_id="test")
        assert len(events) == 0

    def test_key_contains_post_id(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="mypost")
        for e in events:
            assert e.key.startswith("mypost:")

    def test_key_is_stable_and_unique(self):
        events = parse_goal_events(SWEDEN_TUNISIA_SELFTEXT, post_id="p1")
        keys = {e.key for e in events}
        assert len(keys) == len(events)

    def test_empty_selftext_returns_empty_list(self):
        assert parse_goal_events("", post_id="x") == []

    def test_no_match_events_section_returns_empty(self):
        assert parse_goal_events("No goals here, just chat", post_id="x") == []
