"""Tests for reddit.score_state — GoalDelta, diff_scores, load_scores, save_scores, reconcile."""

from __future__ import annotations

import json

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.reddit.score_state import GoalDelta, diff_scores, load_scores, reconcile, save_scores


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


# ══════════════════════════════════════════════════════════════════════════════
# reconcile — per-source deduplication (the flip-flop fix)
# ══════════════════════════════════════════════════════════════════════════════


def _s(home: int, away: int) -> dict:
    return {"home": home, "away": away}


class TestReconcile:
    # ── first-seen (seed) ──────────────────────────────────────────────────────

    def test_first_seen_no_announced_seeds_both(self):
        """reconcile(None, None, 2, 2) → no deltas, both seen and announced seeded to 2-2."""
        deltas, new_seen, new_ann = reconcile(None, None, 2, 2)
        assert deltas == []
        assert new_seen == _s(2, 2)
        assert new_ann == _s(2, 2)

    def test_first_seen_with_announced_same_score_no_delta(self):
        """Restart: source first tick equals announced → no delta, announced unchanged."""
        deltas, new_seen, new_ann = reconcile(None, _s(3, 2), 3, 2)
        assert deltas == []
        assert new_seen == _s(3, 2)
        assert new_ann == _s(3, 2)

    def test_first_seen_api_lagging_seeds_without_disallowed(self):
        """reconcile(None, {4,2}, 3, 2) — api first tick is below announced → seed, no disallowed."""
        deltas, new_seen, new_ann = reconcile(None, _s(4, 2), 3, 2)
        assert deltas == []
        assert new_seen == _s(3, 2)
        assert new_ann == _s(4, 2)  # announced unchanged

    # ── restart: missed goals ─────────────────────────────────────────────────

    def test_restart_new_ahead_of_announced_emits_home_delta(self):
        """Restart: source re-seeds with score ahead of announced → ONE catchup delta."""
        deltas, new_seen, new_ann = reconcile(None, _s(1, 1), 2, 1)
        assert len(deltas) == 1
        assert deltas[0].kind == "catchup"
        assert deltas[0].goals_missed == 1
        assert deltas[0].new_home == 2
        assert deltas[0].new_away == 1
        assert new_seen == _s(2, 1)
        assert new_ann == _s(2, 1)

    def test_restart_new_ahead_multiple_goals_emits_all(self):
        """Restart: score jumped 0-0 → 2-1 while down → ONE catchup delta with goals_missed=3."""
        deltas, new_seen, new_ann = reconcile(None, _s(0, 0), 2, 1)
        assert len(deltas) == 1
        assert deltas[0].kind == "catchup"
        assert deltas[0].goals_missed == 3
        assert deltas[0].new_home == 2
        assert deltas[0].new_away == 1
        assert new_seen == _s(2, 1)
        assert new_ann == _s(2, 1)

    def test_restart_new_equal_announced_no_delta(self):
        """Restart at same score as announced → no delta, no double-announce."""
        deltas, new_seen, new_ann = reconcile(None, _s(2, 1), 2, 1)
        assert deltas == []
        assert new_seen == _s(2, 1)
        assert new_ann == _s(2, 1)

    def test_restart_new_below_announced_no_delta_keeps_announced(self):
        """Restart: source lags behind announced → no delta, announced preserved."""
        deltas, new_seen, new_ann = reconcile(None, _s(4, 2), 3, 2)
        assert deltas == []
        assert new_seen == _s(3, 2)
        assert new_ann == _s(4, 2)

    def test_restart_away_goal_missed_emits_away_delta(self):
        """Restart: away goal missed → ONE catchup delta."""
        deltas, new_seen, new_ann = reconcile(None, _s(1, 0), 1, 1)
        assert len(deltas) == 1
        assert deltas[0].kind == "catchup"
        assert deltas[0].goals_missed == 1
        assert new_ann == _s(1, 1)

    def test_restart_catchup_delta_has_no_scoring_team(self):
        """Catchup delta from restart path has scoring_team='' — no team attribution."""
        deltas, _, _ = reconcile(None, _s(0, 0), 1, 0)
        assert len(deltas) == 1
        assert deltas[0].kind == "catchup"
        assert deltas[0].scoring_team == ""
        assert deltas[0].side == ""

    def test_restart_catchup_single_delta_no_token_collision(self):
        """Restart catch-up emits ONE delta regardless of how many goals were missed.

        The old multi-delta design caused token collisions for same-team goals.
        With a single catchup delta (kind='catchup') there is exactly one clip-store
        slot keyed by '{match_id}:catchup:{H}-{A}' — no collision possible.
        """
        # 0-0 → 2-1 missed while down: must produce exactly 1 catchup delta
        deltas, _, _ = reconcile(None, _s(0, 0), 2, 1)
        assert len(deltas) == 1
        assert deltas[0].kind == "catchup"
        assert deltas[0].goals_missed == 3
        assert deltas[0].new_home == 2
        assert deltas[0].new_away == 1

    # ── no change ─────────────────────────────────────────────────────────────

    def test_no_change_returns_empty(self):
        """Same score as seen → nothing to announce."""
        deltas, new_seen, new_ann = reconcile(_s(4, 2), _s(4, 2), 4, 2)
        assert deltas == []
        assert new_seen == _s(4, 2)
        assert new_ann == _s(4, 2)

    # ── thread path: step-by-step goals ───────────────────────────────────────

    def test_thread_home_goal_from_seeded_state(self):
        """seen=2-2, ann=2-2, new=3-2 → 1 home goal, announced→3-2."""
        deltas, new_seen, new_ann = reconcile(_s(2, 2), _s(2, 2), 3, 2)
        assert len(deltas) == 1
        assert deltas[0].kind == "goal"
        assert deltas[0].side == "home"
        assert deltas[0].new_home == 3
        assert deltas[0].new_away == 2
        assert new_seen == _s(3, 2)
        assert new_ann == _s(3, 2)

    def test_thread_second_goal(self):
        """seen=3-2, ann=3-2, new=4-2 → 1 home goal, announced→4-2."""
        deltas, new_seen, new_ann = reconcile(_s(3, 2), _s(3, 2), 4, 2)
        assert len(deltas) == 1
        assert deltas[0].kind == "goal"
        assert deltas[0].side == "home"
        assert new_ann == _s(4, 2)

    # ── multi-goal jump ────────────────────────────────────────────────────────

    def test_multi_goal_jump(self):
        """seen=2-2, ann=2-2, new=4-2 → 2 home goals, announced→4-2."""
        deltas, new_seen, new_ann = reconcile(_s(2, 2), _s(2, 2), 4, 2)
        goal_deltas = [d for d in deltas if d.kind == "goal" and d.side == "home"]
        assert len(goal_deltas) == 2
        assert new_ann == _s(4, 2)

    # ── API lag — THE BUG FIX ─────────────────────────────────────────────────

    def test_api_lag_does_not_produce_disallowed(self):
        """THE BUG: api seen=2-2, announced=4-2 (thread already told users 4-2), api reports 3-2.
        Must return [] — pure lag, NOT a disallowed. announced stays 4-2."""
        deltas, new_seen, new_ann = reconcile(_s(2, 2), _s(4, 2), 3, 2)
        assert deltas == []
        assert new_seen == _s(3, 2)
        assert new_ann == _s(4, 2)  # announced UNCHANGED — no false disallowed

    def test_api_lag_catchup_no_duplicate(self):
        """After lag-seed (seen=3-2, ann=4-2), api catches up to 4-2 → still no announcement."""
        deltas, new_seen, new_ann = reconcile(_s(3, 2), _s(4, 2), 4, 2)
        assert deltas == []
        assert new_seen == _s(4, 2)
        assert new_ann == _s(4, 2)  # already announced, no duplicate

    # ── real VAR on the same source ───────────────────────────────────────────

    def test_real_var_same_source(self):
        """seen=4-2, ann=4-2, new=3-2 → 1 home disallowed, announced→3-2."""
        deltas, new_seen, new_ann = reconcile(_s(4, 2), _s(4, 2), 3, 2)
        assert len(deltas) == 1
        assert deltas[0].kind == "disallowed"
        assert deltas[0].side == "home"
        assert deltas[0].new_home == 3
        assert deltas[0].new_away == 2
        assert new_seen == _s(3, 2)
        assert new_ann == _s(3, 2)

    def test_other_source_catching_up_after_var_no_double(self):
        """After VAR (ann=3-2), other source was at seen=4-2 and now reports 3-2 → no double disallowed."""
        # ann=3-2 (already corrected by first source), other source's seen still 4-2
        deltas, new_seen, new_ann = reconcile(_s(4, 2), _s(3, 2), 3, 2)
        assert deltas == []
        assert new_seen == _s(3, 2)
        assert new_ann == _s(3, 2)

    # ── away goal ─────────────────────────────────────────────────────────────

    def test_away_goal(self):
        """seen=1-0, ann=1-0, new=1-1 → 1 away goal."""
        deltas, _, new_ann = reconcile(_s(1, 0), _s(1, 0), 1, 1)
        assert len(deltas) == 1
        assert deltas[0].kind == "goal"
        assert deltas[0].side == "away"
        assert new_ann == _s(1, 1)

    # ── scoring_team placeholder ───────────────────────────────────────────────

    def test_goal_delta_scoring_team_empty_for_caller_to_fill(self):
        """GoalDelta.scoring_team from reconcile is '' — callers are responsible for filling it."""
        deltas, _, _ = reconcile(_s(0, 0), _s(0, 0), 1, 0)
        assert deltas[0].scoring_team == ""
