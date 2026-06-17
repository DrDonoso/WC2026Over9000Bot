"""Tests for reddit.score_state — GoalDelta, diff_scores, load_scores, save_scores."""

from __future__ import annotations

import json

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.reddit.score_state import GoalDelta, diff_scores, load_scores, save_scores


# ── helpers ───────────────────────────────────────────────────────────────────


def _match(
    mid: int = 1,
    home_name: str = "France",
    away_name: str = "Senegal",
    home_score: int | None = 1,
    away_score: int | None = 0,
    status: str = "IN_PLAY",
    home_tla: str = "FRA",
    away_tla: str = "SEN",
) -> Match:
    return Match(
        id=mid,
        utc_date="2026-06-17T18:00:00Z",
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=home_score,
        away_score=away_score,
        winner=None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# diff_scores
# ══════════════════════════════════════════════════════════════════════════════


class TestDiffScores:
    def test_seed_first_seen_returns_empty(self):
        match = _match(home_score=1, away_score=0)
        result = diff_scores(None, match)
        assert result == []

    def test_home_goal(self):
        stored = {"home": 0, "away": 0, "status": "IN_PLAY"}
        match = _match(home_score=1, away_score=0)
        deltas = diff_scores(stored, match)
        assert len(deltas) == 1
        assert deltas[0].side == "home"
        assert deltas[0].scoring_team == "France"
        assert deltas[0].new_home == 1
        assert deltas[0].new_away == 0
        assert deltas[0].kind == "goal"

    def test_away_goal(self):
        stored = {"home": 1, "away": 0, "status": "IN_PLAY"}
        match = _match(home_score=1, away_score=1)
        deltas = diff_scores(stored, match)
        assert len(deltas) == 1
        assert deltas[0].side == "away"
        assert deltas[0].scoring_team == "Senegal"
        assert deltas[0].new_home == 1
        assert deltas[0].new_away == 1
        assert deltas[0].kind == "goal"

    def test_double_increase_produces_two_deltas(self):
        stored = {"home": 0, "away": 0, "status": "IN_PLAY"}
        match = _match(home_score=2, away_score=0)
        deltas = diff_scores(stored, match)
        goal_deltas = [d for d in deltas if d.kind == "goal" and d.side == "home"]
        assert len(goal_deltas) == 2

    def test_decrease_produces_disallowed(self):
        stored = {"home": 2, "away": 0, "status": "IN_PLAY"}
        match = _match(home_score=1, away_score=0)
        deltas = diff_scores(stored, match)
        assert len(deltas) == 1
        assert deltas[0].kind == "disallowed"
        assert deltas[0].side == "home"

    def test_no_change_returns_empty(self):
        stored = {"home": 1, "away": 1, "status": "IN_PLAY"}
        match = _match(home_score=1, away_score=1)
        assert diff_scores(stored, match) == []

    def test_none_scores_treated_as_zero(self):
        stored = {"home": 0, "away": 0, "status": "IN_PLAY"}
        match = _match(home_score=None, away_score=None)
        assert diff_scores(stored, match) == []

    def test_both_sides_score_gives_two_deltas(self):
        stored = {"home": 0, "away": 0, "status": "IN_PLAY"}
        match = _match(home_score=1, away_score=1)
        deltas = diff_scores(stored, match)
        kinds = {d.side: d.kind for d in deltas}
        assert kinds == {"home": "goal", "away": "goal"}

    def test_away_disallowed(self):
        stored = {"home": 0, "away": 1, "status": "IN_PLAY"}
        match = _match(home_score=0, away_score=0)
        deltas = diff_scores(stored, match)
        assert len(deltas) == 1
        assert deltas[0].side == "away"
        assert deltas[0].kind == "disallowed"
        assert deltas[0].scoring_team == "Senegal"


# ══════════════════════════════════════════════════════════════════════════════
# load_scores / save_scores
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadSaveScores:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "live_scores.json")
        data = {"1": {"home": 2, "away": 1, "status": "FINISHED"}}
        save_scores(path, data)
        loaded = load_scores(path)
        assert loaded == data

    def test_missing_file_returns_empty(self, tmp_path):
        path = str(tmp_path / "does_not_exist.json")
        assert load_scores(path) == {}

    def test_unwritable_path_does_not_raise(self):
        # Must not raise even for a totally invalid path
        save_scores("/nonexistent/deeply/nested/live_scores.json", {"x": 1})

    def test_corrupt_file_returns_empty(self, tmp_path):
        path_obj = tmp_path / "bad.json"
        path_obj.write_text("not-json{{{", encoding="utf-8")
        assert load_scores(str(path_obj)) == {}

    def test_empty_dict_round_trip(self, tmp_path):
        path = str(tmp_path / "empty.json")
        save_scores(path, {})
        assert load_scores(path) == {}

    def test_multiple_matches_round_trip(self, tmp_path):
        path = str(tmp_path / "scores.json")
        data = {
            "42": {"home": 3, "away": 1, "status": "FINISHED"},
            "99": {"home": 0, "away": 0, "status": "IN_PLAY"},
        }
        save_scores(path, data)
        assert load_scores(path) == data
