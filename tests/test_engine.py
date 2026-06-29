"""Tests for porra engine — provisional vs official compute_general_ranking.

Uses lightweight MagicMock clients; no network, no I/O.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from worldcup_bot.api.models import Standing
from worldcup_bot.data.stages import KNOCKOUT_STAGES
import pytest

from worldcup_bot.porra.engine import compute_general_ranking, compute_group_ranking, compute_user_detail


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_standing(group: str, position: int, tla: str) -> Standing:
    return Standing(group=group, position=position, tla=tla, team_name=tla, points=0, played=3)


def _ko_empty() -> dict[str, list[str]]:
    return {api_stage: [] for api_stage, _, _ in KNOCKOUT_STAGES}


def _make_client(
    standings: list[Standing] | None = None,
    finished_groups: set[str] | None = None,
    ko_results: dict[str, list[str]] | None = None,
    finished_stages: set[str] | None = None,
    started_groups: set[str] | None = None,
    decided_teams: dict[str, set[str]] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.get_standings.return_value = standings or []
    client.get_finished_groups.return_value = finished_groups if finished_groups is not None else set()
    client.get_knockout_results.return_value = ko_results if ko_results is not None else _ko_empty()
    client.get_finished_stages.return_value = finished_stages if finished_stages is not None else set()
    client.get_started_groups.return_value = started_groups if started_groups is not None else set()
    if decided_teams is not None:
        client.get_knockout_decided.return_value = decided_teams
    else:
        # Not a dict → engine disables the pending/fallo distinction (legacy behavior).
        client.get_knockout_decided.return_value = MagicMock()
    return client


# Group A standings where user1 predicted perfectly
_GROUP_A_STANDINGS = [
    _make_standing("GROUP_A", 1, "GER"),
    _make_standing("GROUP_A", 2, "ESP"),
    _make_standing("GROUP_A", 3, "BRA"),
    _make_standing("GROUP_A", 4, "USA"),
]

_ONE_USER_PREDICTIONS = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {"A": ["GER", "ESP", "BRA"]},
            "knockout": {
                "round_of_32": [], "round_of_16": [],
                "quarter_finals": [], "semi_finals": [], "final": [],
            },
        }
    }
}


# ══════════════════════════════════════════════════════════════════════════════
# compute_general_ranking — provisional (official=False)
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeGeneralRankingProvisional:
    def test_returns_one_row_per_participant(self):
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        assert len(rows) == 1
        assert rows[0].username == "alice"

    def test_live_standings_counted_for_started_groups(self):
        """official=False: group A scores from live standings when it IS in started_groups."""
        client = _make_client(standings=_GROUP_A_STANDINGS, started_groups={"GROUP_A"})
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        # All 3 exact → 3.0 group pts
        assert rows[0].group_score == 3.0
        assert rows[0].total_score == 3.0

    def test_not_started_group_scores_zero(self):
        """official=False: group A NOT in started_groups → group score = 0."""
        client = _make_client(standings=_GROUP_A_STANDINGS, started_groups=set())
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        assert rows[0].group_score == 0.0
        assert rows[0].total_score == 0.0

    def test_get_started_groups_is_called_in_provisional_mode(self):
        """get_started_groups is called for official=False."""
        client = _make_client(standings=_GROUP_A_STANDINGS, started_groups={"GROUP_A"})
        compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        client.get_started_groups.assert_called_once()

    def test_get_finished_groups_not_called_in_unofficial_mode(self):
        """get_finished_groups is not needed for official=False."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        client.get_finished_groups.assert_not_called()

    def test_official_false_is_default(self):
        """Default call (no official kwarg) == explicit official=False."""
        client1 = _make_client(standings=_GROUP_A_STANDINGS, started_groups={"GROUP_A"})
        client2 = _make_client(standings=_GROUP_A_STANDINGS, started_groups={"GROUP_A"})
        rows_default = compute_general_ranking(_ONE_USER_PREDICTIONS, client1)
        rows_explicit = compute_general_ranking(_ONE_USER_PREDICTIONS, client2, official=False)
        assert rows_default[0].group_score == rows_explicit[0].group_score
        assert rows_default[0].total_score == rows_explicit[0].total_score

    def test_partial_started_only_started_group_scores(self):
        """Two groups: A started (scores), B not started (0)."""
        standings = _GROUP_A_STANDINGS + [
            _make_standing("GROUP_B", 1, "FRA"),
            _make_standing("GROUP_B", 2, "ARG"),
            _make_standing("GROUP_B", 3, "ENG"),
            _make_standing("GROUP_B", 4, "MEX"),
        ]
        predictions = {
            "participants": {
                "bob": {
                    "display_name": "Bob",
                    "base_score": 0.0,
                    "groups": {"A": ["GER", "ESP", "BRA"], "B": ["FRA", "ARG", "ENG"]},
                    "knockout": {
                        "round_of_32": [], "round_of_16": [],
                        "quarter_finals": [], "semi_finals": [], "final": [],
                    },
                }
            }
        }
        # Only Group A has started
        client = _make_client(standings=standings, started_groups={"GROUP_A"})
        rows = compute_general_ranking(predictions, client, official=False)
        # Group A (3 exact → 3.0), Group B (not started → 0)
        assert rows[0].group_score == 3.0


# ══════════════════════════════════════════════════════════════════════════════
# compute_general_ranking — official (official=True)
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeGeneralRankingOfficial:
    def test_unfinished_group_scores_zero(self):
        """official=True: Group A not in finished_groups → group score = 0."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=True)
        assert rows[0].group_score == 0.0
        assert rows[0].total_score == 0.0

    def test_finished_group_scores_normally(self):
        """official=True: Group A in finished_groups → full group score counts."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"})
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=True)
        assert rows[0].group_score == 3.0
        assert rows[0].total_score == 3.0

    def test_partially_finished_only_finished_group_scores(self):
        """Two groups: A finished (scores), B not finished (scores 0)."""
        standings = _GROUP_A_STANDINGS + [
            _make_standing("GROUP_B", 1, "FRA"),
            _make_standing("GROUP_B", 2, "ARG"),
            _make_standing("GROUP_B", 3, "ENG"),
            _make_standing("GROUP_B", 4, "MEX"),
        ]
        predictions = {
            "participants": {
                "bob": {
                    "display_name": "Bob",
                    "base_score": 0.0,
                    # Group A: exact prediction
                    "groups": {"A": ["GER", "ESP", "BRA"], "B": ["FRA", "ARG", "ENG"]},
                    "knockout": {
                        "round_of_32": [], "round_of_16": [],
                        "quarter_finals": [], "semi_finals": [], "final": [],
                    },
                }
            }
        }
        # Only Group A is finished
        client = _make_client(standings=standings, finished_groups={"GROUP_A"})
        rows = compute_general_ranking(predictions, client, official=True)
        # Group A (3 exact → 3.0), Group B (not finished → 0)
        assert rows[0].group_score == 3.0

    def test_no_groups_finished_all_group_scores_zero(self):
        """official=True, no finished groups → all group scores are 0."""
        standings = _GROUP_A_STANDINGS
        client = _make_client(standings=standings, finished_groups=set())
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=True)
        assert rows[0].group_score == 0.0

    def test_get_finished_groups_is_called_in_official_mode(self):
        """get_finished_groups is called exactly once for official=True."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"})
        compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=True)
        client.get_finished_groups.assert_called_once()

    def test_knockout_score_unchanged_between_modes(self):
        """Knockout scoring is identical in official=True and official=False."""
        ko_results = _ko_empty()
        ko_results["ROUND_OF_32"] = ["GER"]  # GER advances, user predicted GER → +1pt

        predictions = {
            "participants": {
                "charlie": {
                    "display_name": "Charlie",
                    "base_score": 0.0,
                    "groups": {"A": ["GER", "ESP", "BRA"]},
                    "knockout": {
                        "round_of_32": ["GER"],
                        "round_of_16": [], "quarter_finals": [], "semi_finals": [], "final": [],
                    },
                }
            }
        }
        client_off = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set(), ko_results=ko_results)
        client_on = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"}, ko_results=ko_results)

        rows_unofficial = compute_general_ranking(predictions, client_off, official=False)
        rows_official = compute_general_ranking(predictions, client_on, official=True)

        assert rows_unofficial[0].knockout_scores == rows_official[0].knockout_scores

    def test_base_score_unchanged_between_modes(self):
        """base_score is included in total regardless of official mode."""
        predictions = {
            "participants": {
                "diana": {
                    "display_name": "Diana",
                    "base_score": 5.0,
                    "groups": {"A": ["GER", "ESP", "BRA"]},
                    "knockout": {
                        "round_of_32": [], "round_of_16": [],
                        "quarter_finals": [], "semi_finals": [], "final": [],
                    },
                }
            }
        }
        client_off = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        client_on = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())

        rows_unofficial = compute_general_ranking(predictions, client_off, official=False)
        rows_official = compute_general_ranking(predictions, client_on, official=True)

        assert rows_unofficial[0].base_score == 5.0
        assert rows_official[0].base_score == 5.0


# ══════════════════════════════════════════════════════════════════════════════
# compute_user_detail — provisional (official=False, default)
# ══════════════════════════════════════════════════════════════════════════════

_DETAIL_PREDICTIONS = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {"A": ["GER", "ESP", "BRA"]},
            "knockout": {
                "round_of_32": [], "round_of_16": [],
                "quarter_finals": [], "semi_finals": [], "final": [],
            },
        }
    }
}


class TestComputeUserDetailProvisional:
    def test_returns_none_for_unknown_user(self):
        client = _make_client(standings=_GROUP_A_STANDINGS)
        result = compute_user_detail("nobody", _DETAIL_PREDICTIONS, client)
        assert result is None

    def test_returns_dict_for_known_user(self):
        client = _make_client(standings=_GROUP_A_STANDINGS)
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result is not None
        assert result["username"] == "alice"

    def test_group_score_uses_live_standings_for_started_groups(self):
        """official=False: group A scores from live standings when it IS in started_groups."""
        client = _make_client(standings=_GROUP_A_STANDINGS, started_groups={"GROUP_A"})
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        # Alice predicted GER/ESP/BRA exactly → 3.0 pts
        assert result["group_score"] == 3.0

    def test_not_started_group_scores_zero_with_no_data(self):
        """official=False, group NOT in started_groups → group_score=0, entries have note 'no_data'."""
        client = _make_client(standings=_GROUP_A_STANDINGS, started_groups=set())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result["group_score"] == 0.0
        for entry in result["group_detail"]:
            if entry.get("note") != "wildcard":
                assert entry["note"] == "no_data", f"Expected no_data, got {entry['note']}"

    def test_started_groups_key_reflects_started_count(self):
        """started_groups key = len(get_started_groups()) in provisional mode."""
        client = _make_client(standings=_GROUP_A_STANDINGS, started_groups={"GROUP_A", "GROUP_B"})
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result["started_groups"] == 2

    def test_started_groups_key_is_none_in_official_mode(self):
        """started_groups key is None when official=True."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"}, finished_stages=set())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result["started_groups"] is None

    def test_official_key_is_false(self):
        client = _make_client(standings=_GROUP_A_STANDINGS)
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result["official"] is False

    def test_finished_groups_key_is_none_in_provisional(self):
        client = _make_client(standings=_GROUP_A_STANDINGS)
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result["finished_groups"] is None

    def test_total_groups_key_present(self):
        client = _make_client(standings=_GROUP_A_STANDINGS)
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result["total_groups"] == 12

    def test_default_is_provisional(self):
        """No official kwarg → same as official=False."""
        client1 = _make_client(standings=_GROUP_A_STANDINGS)
        client2 = _make_client(standings=_GROUP_A_STANDINGS)
        default = compute_user_detail("alice", _DETAIL_PREDICTIONS, client1)
        explicit = compute_user_detail("alice", _DETAIL_PREDICTIONS, client2, official=False)
        assert default["group_score"] == explicit["group_score"]
        assert default["official"] is False

    def test_knockout_detail_empty_when_no_ko_results(self):
        client = _make_client(standings=_GROUP_A_STANDINGS, ko_results=_ko_empty())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        assert result["knockout_detail"] == []
        assert result["knockout_score"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# compute_user_detail — official (official=True)
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeUserDetailOfficial:
    def test_unclosed_group_has_no_data_entries(self):
        """official=True, group not finished → predicted teams get note 'no_data'."""
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups=set(),   # Group A NOT finished
            finished_stages=set(),
        )
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result is not None
        # All group detail entries for group A should be 'no_data' (standings excluded)
        for entry in result["group_detail"]:
            if entry.get("note") != "wildcard":
                assert entry["note"] == "no_data", f"Expected no_data, got {entry['note']}"

    def test_unclosed_group_scores_zero(self):
        """official=True, group not finished → group_score = 0."""
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups=set(),
            finished_stages=set(),
        )
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result["group_score"] == 0.0

    def test_finished_group_scores_normally(self):
        """official=True, group finished → full group score counts."""
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups={"GROUP_A"},
            finished_stages=set(),
        )
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        # Alice predicted GER/ESP/BRA exactly → 3.0 pts
        assert result["group_score"] == 3.0

    def test_official_key_is_true(self):
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"}, finished_stages=set())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result["official"] is True

    def test_finished_groups_count_in_result(self):
        """finished_groups key reflects how many groups are closed."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"}, finished_stages=set())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result["finished_groups"] == 1

    def test_total_groups_is_twelve(self):
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups={"GROUP_A"}, finished_stages=set())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result["total_groups"] == 12

    def test_empty_knockout_no_raise_and_empty_detail(self):
        """official=True with no finished KO stages → ko_detail=[], ko_pts=0, no exception."""
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups={"GROUP_A"},
            finished_stages=set(),
            ko_results=_ko_empty(),
        )
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client, official=True)
        assert result["knockout_detail"] == []
        assert result["knockout_score"] == 0.0

    def test_finished_ko_stage_scores_when_hit(self):
        """official=True: a finished KO stage produces a scored entry for a correct pick."""
        predictions = {
            "participants": {
                "bob": {
                    "display_name": "Bob",
                    "base_score": 0.0,
                    "groups": {"A": ["GER", "ESP", "BRA"]},
                    "knockout": {
                        "round_of_32": [], "round_of_16": ["ESP"],
                        "quarter_finals": [], "semi_finals": [], "final": [],
                    },
                }
            }
        }
        ko_results = _ko_empty()
        ko_results["LAST_16"] = ["ESP"]
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups={"GROUP_A"},
            finished_stages={"LAST_16"},
            ko_results=ko_results,
        )
        result = compute_user_detail("bob", predictions, client, official=True)
        assert result["knockout_score"] == 1.0  # LAST_16 awards 1 pt per correct pick

    def test_finished_ko_match_counts_even_if_stage_unfinished(self):
        """official=True: a FINISHED KO match scores immediately, even if the rest
        of its stage is still pending (a result is definitive once played)."""
        predictions = {
            "participants": {
                "carol": {
                    "display_name": "Carol",
                    "base_score": 0.0,
                    "groups": {"A": ["GER", "ESP", "BRA"]},
                    "knockout": {
                        "round_of_32": [], "round_of_16": [],
                        "quarter_finals": ["ESP"], "semi_finals": [], "final": [],
                    },
                }
            }
        }
        ko_results = _ko_empty()
        ko_results["QUARTER_FINALS"] = ["ESP"]  # ESP already won its QF match
        # QUARTER_FINALS is NOT fully finished, but ESP's match is.
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups={"GROUP_A"},
            finished_stages=set(),
            ko_results=ko_results,
        )
        result = compute_user_detail("carol", predictions, client, official=True)
        assert result["knockout_score"] == 2.0  # QF awards 2 pts per correct pick
        assert [d["note"] for d in result["knockout_detail"]] == ["acierto"]


# ══════════════════════════════════════════════════════════════════════════════
# compute_user_detail — round-of-32 partially played (pending vs fallo)
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeUserDetailKnockoutPending:
    """A round_of_32 with only one finished match: the winner scores, every
    not-yet-played pick is 'pending' (⏳), and an eliminated pick is 'fallo'."""

    _PREDS = {
        "participants": {
            "dave": {
                "display_name": "Dave",
                "base_score": 0.0,
                "groups": {"A": ["GER", "ESP", "BRA"]},
                "knockout": {
                    "round_of_32": ["CAN", "BRA", "RSA"],  # CAN won, BRA pending, RSA lost
                    "round_of_16": [], "quarter_finals": [],
                    "semi_finals": [], "final": [],
                },
            }
        }
    }

    def _client(self, official_groups: bool):
        ko_results = _ko_empty()
        ko_results["ROUND_OF_32"] = ["CAN"]  # only the CAN vs RSA match is finished
        return _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups={"GROUP_A"} if official_groups else None,
            started_groups={"GROUP_A"} if not official_groups else None,
            ko_results=ko_results,
            decided_teams={"ROUND_OF_32": {"CAN", "RSA"}},
        )

    def _notes(self, detail):
        return {d["team"]: d["note"] for d in detail}

    def test_provisional_marks_pending_and_scores_winner(self):
        result = compute_user_detail("dave", self._PREDS, self._client(False), official=False)
        notes = self._notes(result["knockout_detail"])
        assert notes == {"CAN": "acierto", "BRA": "pending", "RSA": "fallo"}
        assert result["knockout_score"] == 1.0

    def test_official_counts_finished_match_same_as_provisional(self):
        result = compute_user_detail("dave", self._PREDS, self._client(True), official=True)
        notes = self._notes(result["knockout_detail"])
        assert notes == {"CAN": "acierto", "BRA": "pending", "RSA": "fallo"}
        assert result["knockout_score"] == 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Regression guard: engine callers must pass qualifying_thirds
# ══════════════════════════════════════════════════════════════════════════════
#
# These tests would FAIL if any of compute_general_ranking, compute_group_ranking,
# or compute_user_detail dropped the qualifying_thirds argument to score_groups.
# The backward-compat default (None → all 3rds qualify) would give BRA 1.0
# instead of 0.0, producing group_score=3.0 instead of 2.0.
#
# Setup: 9 groups (A-I) in started/finished_groups.
#   - GROUP_A 3rd = BRA with 0 pts  (worst third, does NOT qualify)
#   - GROUP_B..I 3rds each have 1 pt (outrank BRA → all 8 of them qualify)
# Alice's prediction: ESP 1st, GER 2nd, BRA 3rd (exact for all three).
# Expected group_score = 2.0 (ESP+GER exact @ 1.0 each; BRA non-qualifying @ 0.0).


def _make_standing_pts(
    group: str, pos: int, tla: str, pts: int = 0
) -> Standing:
    return Standing(
        group=group, position=pos, tla=tla, team_name=tla,
        points=pts, played=3, goal_difference=0, goals_for=0,
    )


def _nine_groups_standings() -> list[Standing]:
    s = [
        _make_standing_pts("GROUP_A", 1, "ESP", 9),
        _make_standing_pts("GROUP_A", 2, "GER", 6),
        _make_standing_pts("GROUP_A", 3, "BRA", 0),  # worst third
    ]
    for letter in "BCDEFGHI":
        s += [
            _make_standing_pts(f"GROUP_{letter}", 1, f"{letter}1", 9),
            _make_standing_pts(f"GROUP_{letter}", 2, f"{letter}2", 6),
            _make_standing_pts(f"GROUP_{letter}", 3, f"{letter}3", 1),  # qualifies
        ]
    return s


_NINE_GROUPS_STARTED: set[str] = {f"GROUP_{c}" for c in "ABCDEFGHI"}

_ALICE_PREDS_9_GROUPS = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {"A": ["ESP", "GER", "BRA"]},
            "knockout": {k: [] for k, _, _ in KNOCKOUT_STAGES},
        }
    }
}


class TestQualifyingThirdsCallerRegression:
    """Regression guards: engine callers must propagate qualifying_thirds to score_groups.

    With qualifying_thirds=None (backward-compat), BRA would score 1.0 → group_score
    would be 3.0.  With the fix, BRA (9th best third, 0pts) scores 0.0 → 2.0.
    """

    def test_compute_general_ranking_provisional_non_qualifying_3rd_scores_zero(self):
        client = _make_client(
            standings=_nine_groups_standings(),
            started_groups=_NINE_GROUPS_STARTED,
        )
        rows = compute_general_ranking(_ALICE_PREDS_9_GROUPS, client, official=False)
        assert rows[0].group_score == pytest.approx(2.0)

    def test_compute_general_ranking_official_non_qualifying_3rd_scores_zero(self):
        client = _make_client(
            standings=_nine_groups_standings(),
            finished_groups=_NINE_GROUPS_STARTED,
        )
        rows = compute_general_ranking(_ALICE_PREDS_9_GROUPS, client, official=True)
        assert rows[0].group_score == pytest.approx(2.0)

    def test_compute_user_detail_provisional_non_qualifying_3rd_scores_zero(self):
        client = _make_client(
            standings=_nine_groups_standings(),
            started_groups=_NINE_GROUPS_STARTED,
        )
        result = compute_user_detail("alice", _ALICE_PREDS_9_GROUPS, client, official=False)
        assert result["group_score"] == pytest.approx(2.0)
        bra = next(d for d in result["group_detail"] if d["team"] == "BRA")
        assert bra["note"] == "fallo"
        assert bra["points"] == pytest.approx(0.0)

    def test_compute_user_detail_official_non_qualifying_3rd_scores_zero(self):
        client = _make_client(
            standings=_nine_groups_standings(),
            finished_groups=_NINE_GROUPS_STARTED,
            finished_stages=set(),
        )
        result = compute_user_detail("alice", _ALICE_PREDS_9_GROUPS, client, official=True)
        assert result["group_score"] == pytest.approx(2.0)

    def test_compute_group_ranking_non_qualifying_3rd_scores_zero(self):
        """compute_group_ranking (no only_groups filter) must also pass qualifying_thirds."""
        client = _make_client(standings=_nine_groups_standings())
        rows = compute_group_ranking(_ALICE_PREDS_9_GROUPS, client)
        assert rows[0].group_score == pytest.approx(2.0)
