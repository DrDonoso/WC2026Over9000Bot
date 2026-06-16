"""Tests for reddit.parser — goal event extraction from match thread selftexts."""

from __future__ import annotations

import pytest

from worldcup_bot.reddit.models import GoalEvent
from worldcup_bot.reddit.parser import compute_new_goals, parse_goal_events

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


# ══════════════════════════════════════════════════════════════════════════════
# compute_new_goals
# ══════════════════════════════════════════════════════════════════════════════


def _make_event(key_suffix: str) -> GoalEvent:
    return GoalEvent(
        minute_text="1",
        minute_sort=1.0,
        scorer="Scorer",
        scoring_team="TeamA",
        home_team="TeamA",
        away_team="TeamB",
        home_score=1,
        away_score=0,
        raw="raw",
        key=f"thread1:{key_suffix}",
    )


class TestComputeNewGoals:
    def test_first_poll_returns_no_goals(self):
        events = [_make_event("g1"), _make_event("g2")]
        new_goals, notified, seeded = compute_new_goals("thread1", events, set(), set())
        assert new_goals == []

    def test_first_poll_seeds_all_keys(self):
        events = [_make_event("g1"), _make_event("g2")]
        _, notified, seeded = compute_new_goals("thread1", events, set(), set())
        assert "thread1:g1" in notified
        assert "thread1:g2" in notified
        assert "thread1" in seeded

    def test_second_poll_notifies_new_goal(self):
        events_first = [_make_event("g1"), _make_event("g2")]
        _, notified, seeded = compute_new_goals("thread1", events_first, set(), set())
        # New goal appears
        events_second = events_first + [_make_event("g3")]
        new_goals, notified2, _ = compute_new_goals("thread1", events_second, notified, seeded)
        assert len(new_goals) == 1
        assert new_goals[0].key == "thread1:g3"
        assert "thread1:g3" in notified2

    def test_preexisting_goals_never_re_notified(self):
        events = [_make_event("g1")]
        _, notified, seeded = compute_new_goals("thread1", events, set(), set())
        # Second poll: same events, no new ones
        new_goals, _, _ = compute_new_goals("thread1", events, notified, seeded)
        assert new_goals == []

    def test_different_threads_seeded_independently(self):
        e1 = [_make_event("g1")]
        e2 = [_make_event("g2")]
        # Seed thread1
        _, notified, seeded = compute_new_goals("thread1", e1, set(), set())
        # thread2 has not been seen — first poll for thread2 also seeds
        new_goals2, notified2, seeded2 = compute_new_goals("thread2", e2, notified, seeded)
        assert new_goals2 == []
        assert "thread2" in seeded2
        # Now a new goal in thread2
        e2_new = e2 + [_make_event("g3")]
        new_goals3, _, _ = compute_new_goals("thread2", e2_new, notified2, seeded2)
        assert len(new_goals3) == 1

    def test_immutability_of_input_sets(self):
        events = [_make_event("g1")]
        orig_notified: set[str] = set()
        orig_seeded: set[str] = set()
        compute_new_goals("thread1", events, orig_notified, orig_seeded)
        assert orig_notified == set()
        assert orig_seeded == set()
