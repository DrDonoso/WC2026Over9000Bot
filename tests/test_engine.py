"""Tests for porra engine — provisional vs official compute_general_ranking.

Uses lightweight MagicMock clients; no network, no I/O.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from worldcup_bot.api.models import Standing
from worldcup_bot.data.stages import KNOCKOUT_STAGES
from worldcup_bot.porra.engine import compute_general_ranking, compute_user_detail


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
) -> MagicMock:
    client = MagicMock()
    client.get_standings.return_value = standings or []
    client.get_finished_groups.return_value = finished_groups if finished_groups is not None else set()
    client.get_knockout_results.return_value = ko_results if ko_results is not None else _ko_empty()
    client.get_finished_stages.return_value = finished_stages if finished_stages is not None else set()
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

    def test_live_standings_counted_regardless_of_finished_groups(self):
        """official=False: group A scores even if finished_groups is empty."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        rows = compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        # All 3 exact → 3.0 group pts
        assert rows[0].group_score == 3.0
        assert rows[0].total_score == 3.0

    def test_get_finished_groups_not_called_in_unofficial_mode(self):
        """get_finished_groups is not needed for official=False."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        compute_general_ranking(_ONE_USER_PREDICTIONS, client, official=False)
        client.get_finished_groups.assert_not_called()

    def test_official_false_is_default(self):
        """Default call (no official kwarg) == explicit official=False."""
        client1 = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        client2 = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        rows_default = compute_general_ranking(_ONE_USER_PREDICTIONS, client1)
        rows_explicit = compute_general_ranking(_ONE_USER_PREDICTIONS, client2, official=False)
        assert rows_default[0].group_score == rows_explicit[0].group_score
        assert rows_default[0].total_score == rows_explicit[0].total_score


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

    def test_group_score_uses_live_standings(self):
        """official=False: group A scores from live standings regardless of finished_groups."""
        client = _make_client(standings=_GROUP_A_STANDINGS, finished_groups=set())
        result = compute_user_detail("alice", _DETAIL_PREDICTIONS, client)
        # Alice predicted GER/ESP/BRA exactly → 3.0 pts
        assert result["group_score"] == 3.0

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

    def test_unfinished_ko_stage_produces_no_detail_entries(self):
        """official=True: a KO stage not yet finished has no entries in knockout_detail."""
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
        ko_results["QUARTER_FINALS"] = ["ESP"]
        # QUARTER_FINALS is NOT in finished_stages
        client = _make_client(
            standings=_GROUP_A_STANDINGS,
            finished_groups={"GROUP_A"},
            finished_stages=set(),
            ko_results=ko_results,
        )
        result = compute_user_detail("carol", predictions, client, official=True)
        assert result["knockout_detail"] == []
        assert result["knockout_score"] == 0.0
