"""Tests for engine evolution functions: compute_general_ranking_from."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from worldcup_bot.api.models import Match, Standing
from worldcup_bot.data.stages import KNOCKOUT_STAGES
from worldcup_bot.porra.engine import (
    compute_general_ranking,
    compute_general_ranking_from,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_standing(group: str, position: int, tla: str, played: int = 3) -> Standing:
    return Standing(group=group, position=position, tla=tla, team_name=tla, points=0, played=played)


def _ko_empty() -> dict[str, list[str]]:
    return {api_stage: [] for api_stage, _, _ in KNOCKOUT_STAGES}


def _make_match(
    match_id: int,
    utc_date: str,
    status: str,
    stage: str,
    home_tla: str,
    away_tla: str,
    winner: str | None = None,
    group: str | None = None,
) -> Match:
    return Match(
        id=match_id,
        utc_date=utc_date,
        status=status,
        stage=stage,
        group=group,
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_tla,
        away_name=away_tla,
        home_score=1 if winner == "HOME_TEAM" else 0,
        away_score=1 if winner == "AWAY_TEAM" else 0,
        winner=winner,
    )


_ONE_USER_PREDICTIONS = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {"A": ["GER", "ESP", "BRA"]},
            "knockout": {k: [] for k, _, _ in KNOCKOUT_STAGES},
        }
    }
}

_GROUP_A_STANDINGS_DICT = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}


# ══════════════════════════════════════════════════════════════════════════════
# compute_general_ranking_from
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeGeneralRankingFrom:
    def test_returns_one_entry_per_participant(self):
        rows = compute_general_ranking_from(_ONE_USER_PREDICTIONS, _GROUP_A_STANDINGS_DICT, _ko_empty())
        assert len(rows) == 1
        assert rows[0].username == "alice"

    def test_exact_predictions_score_3_0(self):
        """User1 predicted GROUP_A top-3 exactly → 3.0 group pts."""
        rows = compute_general_ranking_from(_ONE_USER_PREDICTIONS, _GROUP_A_STANDINGS_DICT, _ko_empty())
        assert rows[0].group_score == 3.0
        assert rows[0].total_score == 3.0

    def test_empty_standings_scores_zero(self):
        """No standings data → score_groups returns no_data → 0 pts."""
        rows = compute_general_ranking_from(_ONE_USER_PREDICTIONS, {}, _ko_empty())
        assert rows[0].group_score == 0.0

    def test_knockout_points_added(self):
        """Correct FINAL pick adds 5 pts."""
        from worldcup_bot.data.stages import STAGE_YAML_KEYS
        ko_actual = _ko_empty()
        ko_actual["FINAL"] = ["ESP"]
        preds = {
            "participants": {
                "alice": {
                    "display_name": "Alice",
                    "base_score": 0.0,
                    "groups": {},
                    "knockout": {**{k: [] for k, _, _ in KNOCKOUT_STAGES}, "final": ["ESP"]},
                }
            }
        }
        rows = compute_general_ranking_from(preds, {}, ko_actual)
        assert rows[0].total_score == 5.0

    def test_base_score_included(self):
        preds = {
            "participants": {
                "bob": {
                    "display_name": "Bob",
                    "base_score": 10.0,
                    "groups": {},
                    "knockout": {k: [] for k, _, _ in KNOCKOUT_STAGES},
                }
            }
        }
        rows = compute_general_ranking_from(preds, {}, _ko_empty())
        assert rows[0].base_score == 10.0
        assert rows[0].total_score == 10.0

    def test_sorted_by_total_descending(self):
        preds = {
            "participants": {
                "alice": {"display_name": "Alice", "base_score": 0.0, "groups": {"A": ["GER", "ESP", "BRA"]}, "knockout": _ko_empty()},
                "bob":   {"display_name": "Bob",   "base_score": 5.0, "groups": {},                           "knockout": _ko_empty()},
            }
        }
        rows = compute_general_ranking_from(preds, _GROUP_A_STANDINGS_DICT, _ko_empty())
        # bob has 5.0, alice has 3.0 — bob should be first
        assert rows[0].username == "bob"
        assert rows[1].username == "alice"

    def test_does_not_call_client(self):
        """compute_general_ranking_from takes plain dicts — no client involved."""
        rows = compute_general_ranking_from(_ONE_USER_PREDICTIONS, _GROUP_A_STANDINGS_DICT, _ko_empty())
        assert rows is not None  # just verifies it runs without a client

    def test_existing_compute_general_ranking_behaviour_unchanged(self):
        """Ensure compute_general_ranking still works with mock client."""
        standings_list = [
            _make_standing("GROUP_A", 1, "GER"),
            _make_standing("GROUP_A", 2, "ESP"),
            _make_standing("GROUP_A", 3, "BRA"),
            _make_standing("GROUP_A", 4, "USA"),
        ]
        client = MagicMock()
        client.get_standings.return_value = standings_list
        client.get_started_groups.return_value = {"GROUP_A"}
        client.get_knockout_results.return_value = _ko_empty()
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        assert rows[0].group_score == 3.0
