"""Exhaustive pure-function tests for score_groups and score_knockout.

No I/O, no network — pure logic.
"""

from __future__ import annotations

import pytest

from worldcup_bot.data.stages import GROUP_SCORING, KNOCKOUT_STAGES, STAGE_YAML_KEYS
from worldcup_bot.porra.scoring import (
    NON_QUALIFYING_THIRD_SCORE,
    score_groups,
    score_knockout,
    score_user_groups_detail,
)


# ══════════════════════════════════════════════════════════════════════════════
# score_groups
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreGroupsExact:
    def test_all_exact_scores_3(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        assert pts == 3.0
        assert all(d["note"] == "exacto" for d in detail)
        assert all(d["points"] == 1.0 for d in detail)

    def test_one_exact_two_others_present(self):
        # GER exact, USA wrong (pred=2, actual=4), BRA exact (pred=3, actual=3)
        user = {"A": ["GER", "USA", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        assert pts == 2.0  # GER(+1.0) + USA(fallo 0) + BRA(+1.0)

    def test_exact_position_constant_is_1(self):
        assert GROUP_SCORING["exact_position"] == 1.0

    def test_detail_predicted_pos_matches_index(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        assert detail[0]["predicted_pos"] == 1
        assert detail[1]["predicted_pos"] == 2
        assert detail[2]["predicted_pos"] == 3

    def test_detail_actual_pos_populated(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        assert detail[0]["actual_pos"] == 1
        assert detail[1]["actual_pos"] == 2
        assert detail[2]["actual_pos"] == 3


class TestScoreGroupsOffByOne:
    def test_upward_shift(self):
        # GER pred=1, actual=2; ESP pred=2, actual=1; BRA pred=3, actual=3
        # Corrected rule: both GER and ESP are in the top-2 zone → each earns 1.0
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["ESP", "GER", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        assert pts == 3.0
        notes = [d["note"] for d in detail]
        assert notes == ["exacto", "exacto", "exacto"]

    def test_downward_shift(self):
        # GER exact (pred=1/actual=1), BRA pred=2/actual=3 (boundary), ESP pred=3/actual=2 (boundary)
        user = {"A": ["GER", "BRA", "ESP"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        assert pts == 2.0
        notes = {d["team"]: d["note"] for d in detail}
        assert notes["GER"] == "exacto"
        assert notes["BRA"] == "clasifica"
        assert notes["ESP"] == "clasifica"

    def test_qualified_wrong_position_value_is_0_5(self):
        assert GROUP_SCORING["qualified_wrong_position"] == 0.5

    def test_top2_swap_earns_full_point_not_half(self):
        # GER pred=1, actual=2 — both in top-2 zone → 1.0 (not 0.5 under the old rule)
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["ESP", "GER", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["points"] == 1.0
        assert ger["note"] == "exacto"


class TestScoreGroupsFallo:
    def test_qualifies_wrong_position_not_fallo(self):
        # GER pred=1, actual=3 (clasifica); ESP pred=2, actual=4 (fallo); BRA pred=3, actual=1 (clasifica)
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["BRA", "USA", "GER", "ESP"]}
        pts, detail = score_groups(user, actual)
        assert pts == 1.0
        notes = {d["team"]: d["note"] for d in detail}
        assert notes["GER"] == "clasifica"
        assert notes["ESP"] == "fallo"
        assert notes["BRA"] == "clasifica"

    def test_mixed_clasifica_and_fallo(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["BRA", "USA", "GER", "ESP"]}
        pts, detail = score_groups(user, actual)
        assert pts == 1.0
        notes = {d["team"]: d["note"] for d in detail}
        assert notes["GER"] == "clasifica"
        assert notes["ESP"] == "fallo"
        assert notes["BRA"] == "clasifica"

    def test_diff_3_is_also_fallo(self):
        # GER pred=1, actual=4
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["USA", "MEX", "CAN", "GER"]}
        pts, detail = score_groups(user, actual)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["note"] == "fallo"
        assert ger["points"] == 0


class TestScoreGroupsWildcard:
    def test_single_wildcard_scores_0(self):
        user = {"A": ["**", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        # ** → 0; ESP exact → +1.0; BRA exact → +1.0
        assert pts == 2.0
        wc = next(d for d in detail if d["team"] == "**")
        assert wc["note"] == "wildcard"
        assert wc["points"] == 0

    def test_wildcard_actual_pos_is_none(self):
        user = {"A": ["**", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        wc = next(d for d in detail if d["team"] == "**")
        assert wc["actual_pos"] is None

    def test_all_wildcards_score_0(self):
        user = {"A": ["**", "**", "**"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        assert pts == 0.0
        assert all(d["note"] == "wildcard" for d in detail)

    def test_empty_string_treated_as_wildcard(self):
        user = {"A": ["", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual)
        # "" → wildcard; ESP pred=2 actual=2 → +1.0; BRA pred=3 actual=3 → +1.0
        assert pts == 2.0
        empty = next(d for d in detail if d["team"] == "")
        assert empty["note"] == "wildcard"


class TestScoreGroupsNoData:
    def test_team_not_in_actual_standings(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["USA", "MEX", "KOR", "CAN"]}
        pts, detail = score_groups(user, actual)
        assert pts == 0.0
        assert all(d["note"] == "no_data" for d in detail)
        assert all(d["actual_pos"] is None for d in detail)

    def test_group_key_missing_from_standings(self):
        user = {"Z": ["GER", "ESP", "BRA"]}
        actual = {}
        pts, detail = score_groups(user, actual)
        assert pts == 0.0
        assert all(d["note"] == "no_data" for d in detail)
        assert all(d["group"] == "Z" for d in detail)

    def test_partial_standings_unplayed_team(self):
        # BRA not in the (partial) GROUP_A list
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP"]}
        pts, detail = score_groups(user, actual)
        # GER exact (+1.0), ESP exact (+1.0), BRA no_data (0)
        assert pts == 2.0
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["note"] == "no_data"


class TestScoreGroupsEmptyInputs:
    def test_empty_user_groups_returns_zero_and_empty_list(self):
        pts, detail = score_groups({}, {"GROUP_A": ["GER", "ESP", "BRA", "USA"]})
        assert pts == 0.0
        assert detail == []

    def test_empty_actual_standings_all_no_data(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        pts, detail = score_groups(user, {})
        assert pts == 0.0
        assert all(d["note"] == "no_data" for d in detail)

    def test_both_empty(self):
        pts, detail = score_groups({}, {})
        assert pts == 0.0
        assert detail == []


class TestScoreGroupsMultipleGroups:
    def test_two_groups_independent_scoring(self):
        user = {
            "A": ["GER", "ESP", "BRA"],  # all exact → +3.0
            "B": ["ARG", "FRA", "ENG"],  # ARG↔FRA swapped (both top-2) → exacto,exacto; ENG exact
        }
        actual = {
            "GROUP_A": ["GER", "ESP", "BRA", "USA"],
            "GROUP_B": ["FRA", "ARG", "ENG", "MEX"],
        }
        pts, detail = score_groups(user, actual)
        # A: 1+1+1 = 3; B: ARG pred=1/actual=2 (+1.0) + FRA pred=2/actual=1 (+1.0) + ENG exact (+1.0)
        assert pts == 6.0

    def test_detail_has_group_key(self):
        user = {"A": ["GER", "ESP", "BRA"], "B": ["FRA", "ARG", "ENG"]}
        actual = {
            "GROUP_A": ["GER", "ESP", "BRA", "USA"],
            "GROUP_B": ["FRA", "ARG", "ENG", "MEX"],
        }
        _, detail = score_groups(user, actual)
        groups_in_detail = {d["group"] for d in detail}
        assert groups_in_detail == {"A", "B"}

    def test_detail_entry_has_all_required_keys(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        required = {"group", "team", "predicted_pos", "actual_pos", "points", "note"}
        for entry in detail:
            assert required <= entry.keys()


class TestScoreUserGroupsDetailIsAlias:
    def test_returns_same_as_score_groups(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        assert score_groups(user, actual) == score_user_groups_detail(user, actual)

    def test_alias_works_with_multiple_groups(self):
        user = {"A": ["GER", "ESP", "BRA"], "B": ["FRA", "ARG", "ENG"]}
        actual = {
            "GROUP_A": ["GER", "ESP", "BRA", "USA"],
            "GROUP_B": ["ARG", "FRA", "ENG", "MEX"],
        }
        assert score_groups(user, actual) == score_user_groups_detail(user, actual)


class TestScoreGroupsQualifiesWrongPosition:
    """Explicit edge cases for the 'clasifica' branch (qualifies but wrong position)."""

    def test_predicted_3rd_actual_1st(self):
        # User's exact example: pred=3, actual=1 → 0.5, "clasifica"
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["BRA", "ESP", "GER", "USA"]}
        _, detail = score_groups(user, actual)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == 0.5
        assert bra["note"] == "clasifica"

    def test_predicted_1st_actual_3rd(self):
        # "Al revés": pred=1, actual=3 → 0.5, "clasifica"
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["ESP", "USA", "GER", "BRA"]}
        _, detail = score_groups(user, actual)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["points"] == 0.5
        assert ger["note"] == "clasifica"

    def test_predicted_1st_actual_2nd(self):
        # pred=1, actual=2 — BOTH in the direct top-2 qualifying zone → 1.0 (corrected rule)
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["ESP", "GER", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["points"] == 1.0
        assert ger["note"] == "exacto"

    def test_predicted_1st_actual_4th(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["ESP", "BRA", "USA", "GER"]}
        _, detail = score_groups(user, actual)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["points"] == 0.0
        assert ger["note"] == "fallo"

    def test_exact_position_scores_1_0(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        _, detail = score_groups(user, actual)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["points"] == 1.0
        assert ger["note"] == "exacto"


# ══════════════════════════════════════════════════════════════════════════════
# score_knockout
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreKnockoutRoundOf32:
    """LAST_32 awards 1 point per correct qualifier."""

    def test_one_correct_qualifer_scores_1(self):
        user = {"round_of_32": ["ESP"]}
        actual = {"LAST_32": ["ESP", "FRA", "GER"]}
        pts, detail = score_knockout(user, actual, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert pts == 1.0
        assert detail[0]["note"] == "acierto"
        assert detail[0]["points"] == 1

    def test_wrong_qualifier_scores_0(self):
        user = {"round_of_32": ["GER"]}
        actual = {"LAST_32": ["ESP", "FRA"]}
        pts, detail = score_knockout(user, actual, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert pts == 0.0
        assert detail[0]["note"] == "fallo"
        assert detail[0]["points"] == 0

    def test_multiple_correct_accumulate(self):
        user = {"round_of_32": ["ESP", "FRA", "GER"]}
        actual = {"LAST_32": ["ESP", "FRA", "BRA"]}
        pts, detail = score_knockout(user, actual, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert pts == 2.0  # ESP + FRA correct; GER fallo


class TestScoreKnockoutLast16:
    """LAST_16 awards 1 point per correct qualifier."""

    def test_point_value_is_1(self):
        user = {"round_of_16": ["ESP"]}
        actual = {"LAST_16": ["ESP"]}
        pts, _ = score_knockout(user, actual, [("LAST_16", "Octavos", 1)])
        assert pts == 1.0

    def test_yaml_key_is_round_of_16(self):
        assert STAGE_YAML_KEYS["LAST_16"] == "round_of_16"

    def test_all_eight_correct_scores_8(self):
        teams = ["ESP", "FRA", "ARG", "BRA", "GER", "ENG", "POR", "NED"]
        user = {"round_of_16": teams}
        actual = {"LAST_16": teams}
        pts, _ = score_knockout(user, actual, [("LAST_16", "Octavos", 1)])
        assert pts == 8.0


class TestScoreKnockoutQuarterFinals:
    """QUARTER_FINALS awards 2 points per correct qualifier."""

    def test_point_value_is_2(self):
        user = {"quarter_finals": ["ESP"]}
        actual = {"QUARTER_FINALS": ["ESP"]}
        pts, detail = score_knockout(user, actual, [("QUARTER_FINALS", "Cuartos", 2)])
        assert pts == 2.0
        assert detail[0]["points"] == 2

    def test_two_correct_scores_4(self):
        user = {"quarter_finals": ["ESP", "BRA"]}
        actual = {"QUARTER_FINALS": ["ESP", "BRA", "FRA", "GER"]}
        pts, _ = score_knockout(user, actual, [("QUARTER_FINALS", "Cuartos", 2)])
        assert pts == 4.0

    def test_yaml_key_mapping(self):
        assert STAGE_YAML_KEYS["QUARTER_FINALS"] == "quarter_finals"


class TestScoreKnockoutSemiFinals:
    """SEMI_FINALS awards 3 points per correct qualifier."""

    def test_point_value_is_3(self):
        user = {"semi_finals": ["ESP"]}
        actual = {"SEMI_FINALS": ["ESP"]}
        pts, detail = score_knockout(user, actual, [("SEMI_FINALS", "Semis", 3)])
        assert pts == 3.0
        assert detail[0]["points"] == 3

    def test_both_semifinalists_correct(self):
        user = {"semi_finals": ["ESP", "BRA"]}
        actual = {"SEMI_FINALS": ["ESP", "BRA"]}
        pts, _ = score_knockout(user, actual, [("SEMI_FINALS", "Semis", 3)])
        assert pts == 6.0

    def test_yaml_key_mapping(self):
        assert STAGE_YAML_KEYS["SEMI_FINALS"] == "semi_finals"


class TestScoreKnockoutFinal:
    """FINAL awards 5 points for correct champion."""

    def test_point_value_is_5(self):
        user = {"final": ["ESP"]}
        actual = {"FINAL": ["ESP"]}
        pts, detail = score_knockout(user, actual, [("FINAL", "Final", 5)])
        assert pts == 5.0
        assert detail[0]["points"] == 5

    def test_wrong_champion_scores_0(self):
        user = {"final": ["GER"]}
        actual = {"FINAL": ["ESP"]}
        pts, detail = score_knockout(user, actual, [("FINAL", "Final", 5)])
        assert pts == 0.0
        assert detail[0]["note"] == "fallo"

    def test_yaml_key_mapping(self):
        assert STAGE_YAML_KEYS["FINAL"] == "final"


class TestScoreKnockoutWildcard:
    def test_wildcard_scores_0(self):
        user = {"round_of_32": ["**"]}
        actual = {"LAST_32": ["ESP", "FRA"]}
        pts, detail = score_knockout(user, actual, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert pts == 0.0
        assert detail[0]["note"] == "wildcard"
        assert detail[0]["points"] == 0

    def test_wildcard_mixed_with_correct(self):
        user = {"round_of_16": ["**", "ESP"]}
        actual = {"LAST_16": ["ESP", "FRA"]}
        pts, detail = score_knockout(user, actual, [("LAST_16", "Octavos", 1)])
        assert pts == 1.0  # only ESP correct, ** is 0
        notes = {d["team"]: d["note"] for d in detail}
        assert notes["**"] == "wildcard"
        assert notes["ESP"] == "acierto"

    def test_empty_string_treated_as_wildcard(self):
        user = {"round_of_32": [""]}
        actual = {"LAST_32": ["ESP"]}
        pts, detail = score_knockout(user, actual, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert pts == 0.0
        assert detail[0]["note"] == "wildcard"


class TestScoreKnockoutPending:
    """decided_teams distinguishes a not-yet-played pick (pending) from a loss."""

    _STAGE = [("LAST_32", "Dieciseisavos de Final", 1)]

    def test_unplayed_pick_is_pending_not_fallo(self):
        user = {"round_of_32": ["BRA"]}
        actual = {"LAST_32": ["CAN"]}  # BRA's match not finished
        decided = {"LAST_32": {"CAN", "RSA"}}
        pts, detail = score_knockout(user, actual, self._STAGE, decided_teams=decided)
        assert pts == 0.0
        assert detail[0]["note"] == "pending"
        assert detail[0]["points"] == 0

    def test_eliminated_pick_is_fallo(self):
        user = {"round_of_32": ["RSA"]}  # RSA played and lost
        actual = {"LAST_32": ["CAN"]}
        decided = {"LAST_32": {"CAN", "RSA"}}
        pts, detail = score_knockout(user, actual, self._STAGE, decided_teams=decided)
        assert pts == 0.0
        assert detail[0]["note"] == "fallo"

    def test_winner_pick_is_acierto(self):
        user = {"round_of_32": ["CAN"]}
        actual = {"LAST_32": ["CAN"]}
        decided = {"LAST_32": {"CAN", "RSA"}}
        pts, detail = score_knockout(user, actual, self._STAGE, decided_teams=decided)
        assert pts == 1.0
        assert detail[0]["note"] == "acierto"

    def test_mixed_winner_pending_and_fallo(self):
        user = {"round_of_32": ["CAN", "BRA", "RSA"]}
        actual = {"LAST_32": ["CAN"]}
        decided = {"LAST_32": {"CAN", "RSA"}}
        pts, detail = score_knockout(user, actual, self._STAGE, decided_teams=decided)
        notes = {d["team"]: d["note"] for d in detail}
        assert notes == {"CAN": "acierto", "BRA": "pending", "RSA": "fallo"}
        assert pts == 1.0

    def test_none_decided_is_backward_compatible_fallo(self):
        """Without decided_teams, a non-winner stays 'fallo' (legacy behavior)."""
        user = {"round_of_32": ["BRA"]}
        actual = {"LAST_32": ["CAN"]}
        pts, detail = score_knockout(user, actual, self._STAGE)
        assert detail[0]["note"] == "fallo"


class TestScoreKnockoutEmptyInputs:
    def test_empty_user_knockout_no_teams_no_detail(self):
        pts, detail = score_knockout({}, {"LAST_32": ["ESP"]})
        assert pts == 0.0
        assert detail == []

    def test_empty_actual_winners_all_fallo(self):
        user = {"round_of_32": ["ESP", "FRA"]}
        pts, detail = score_knockout(user, {}, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert pts == 0.0
        assert all(d["note"] == "fallo" for d in detail)

    def test_stage_absent_from_actual_is_all_fallo(self):
        user = {"final": ["ESP"]}
        pts, detail = score_knockout(user, {}, [("FINAL", "Final", 5)])
        assert pts == 0.0
        assert detail[0]["note"] == "fallo"

    def test_both_empty_returns_zero_empty_list(self):
        pts, detail = score_knockout({}, {})
        assert pts == 0.0
        assert detail == []


class TestScoreKnockoutAllStagesIntegration:
    """Test using the default KNOCKOUT_STAGES config (all 5 stages)."""

    def test_all_stages_correct_sums_correctly(self):
        user = {
            "round_of_32": ["ESP"],
            "round_of_16": ["ESP"],
            "quarter_finals": ["ESP"],
            "semi_finals": ["ESP"],
            "final": ["ESP"],
        }
        actual = {
            "LAST_32": ["ESP"],
            "LAST_16": ["ESP"],
            "QUARTER_FINALS": ["ESP"],
            "SEMI_FINALS": ["ESP"],
            "FINAL": ["ESP"],
        }
        pts, _ = score_knockout(user, actual)
        # 1 + 1 + 2 + 3 + 5 = 12
        assert pts == 12.0

    def test_knockout_stages_config_point_values(self):
        """Canonical check: each stage has the documented point value."""
        expected = {
            "LAST_32": 1,
            "LAST_16": 1,
            "QUARTER_FINALS": 2,
            "SEMI_FINALS": 3,
            "FINAL": 5,
        }
        for api_name, _display, pts in KNOCKOUT_STAGES:
            assert pts == expected[api_name], (
                f"{api_name}: expected {expected[api_name]} pts, got {pts}"
            )

    def test_detail_has_all_required_keys(self):
        user = {"round_of_32": ["ESP"]}
        actual = {"LAST_32": ["ESP"]}
        _, detail = score_knockout(user, actual, [("LAST_32", "Dieciseisavos de Final", 1)])
        assert {"stage", "display", "team", "points", "note"} <= detail[0].keys()

    def test_stage_display_name_in_detail(self):
        user = {"quarter_finals": ["ESP"]}
        actual = {"QUARTER_FINALS": ["ESP"]}
        _, detail = score_knockout(user, actual, [("QUARTER_FINALS", "Cuartos de Final", 2)])
        assert detail[0]["display"] == "Cuartos de Final"

    def test_missing_user_stage_yields_no_entries(self):
        """If a stage key is missing from user_knockout, that stage has 0 entries."""
        user = {"final": ["ESP"]}  # only final; other stages absent
        actual = {
            "LAST_32": ["ESP"],
            "LAST_16": ["ESP"],
            "QUARTER_FINALS": ["ESP"],
            "SEMI_FINALS": ["ESP"],
            "FINAL": ["ESP"],
        }
        pts, detail = score_knockout(user, actual)
        # Only final stage has a team entry
        stages_in_detail = {d["stage"] for d in detail}
        assert stages_in_detail == {"FINAL"}
        assert pts == 5.0


# ══════════════════════════════════════════════════════════════════════════════
# score_groups — corrected rule truth table (2026-06-22)
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreGroupsTruthTable:
    """Full truth table for the corrected group-scoring rule.

    pred_pos→actual_pos → expected points:
      1→1:1.0  1→2:1.0  1→3:0.5  1→4+:0
      2→1:1.0  2→2:1.0  2→3:0.5  2→4+:0
      3→1:0.5  3→2:0.5  3→3:1.0  3→4+:0
    """

    def _pts(self, pred_pos: int, actual_pos: int) -> tuple[float, str]:
        """Score a single team at pred_pos against actual_pos."""
        teams = ["GER", "ESP", "BRA", "ITA"]
        user = {"A": teams[:3]}  # 3 predictions
        # build standings with desired team at actual_pos
        ordered = ["POR", "NED", "MEX", "POL"]
        ordered[actual_pos - 1] = teams[pred_pos - 1]
        actual = {"GROUP_A": ordered}
        _, detail = score_groups(user, actual)
        team = teams[pred_pos - 1]
        entry = next(d for d in detail if d["team"] == team)
        return entry["points"], entry["note"]

    # pred=1
    def test_1_to_1(self):
        assert self._pts(1, 1) == (1.0, "exacto")

    def test_1_to_2(self):
        assert self._pts(1, 2) == (1.0, "exacto")

    def test_1_to_3(self):
        assert self._pts(1, 3) == (0.5, "clasifica")

    def test_1_to_4(self):
        assert self._pts(1, 4) == (0.0, "fallo")

    # pred=2
    def test_2_to_1(self):
        assert self._pts(2, 1) == (1.0, "exacto")

    def test_2_to_2(self):
        assert self._pts(2, 2) == (1.0, "exacto")

    def test_2_to_3(self):
        assert self._pts(2, 3) == (0.5, "clasifica")

    def test_2_to_4(self):
        assert self._pts(2, 4) == (0.0, "fallo")

    # pred=3
    def test_3_to_1(self):
        assert self._pts(3, 1) == (0.5, "clasifica")

    def test_3_to_2(self):
        assert self._pts(3, 2) == (0.5, "clasifica")

    def test_3_to_3(self):
        assert self._pts(3, 3) == (1.0, "exacto")

    def test_3_to_4(self):
        assert self._pts(3, 4) == (0.0, "fallo")


class TestScoreGroupsRegressionDrDonoso:
    """Regression test based on DrDonoso's real data.

    Five teams were predicted as 1st or 2nd and finished in the top-2 (swapped
    order).  Each must score 1.0 (not 0.5 under the old rule).
    Prediction: MEX1/CZE2/KOR3, etc.
    Swap teams: SUI(pred1,real2), EGY(pred2,real1), FRA(pred1,real2),
                COL(pred2,real1), ENG(pred2,real1).
    """

    def _swap_group(self, pred_first: str, pred_second: str) -> tuple[float, str, str]:
        """pred_first finishes 2nd, pred_second finishes 1st."""
        user = {"X": [pred_first, pred_second, "PAD"]}
        actual = {"GROUP_X": [pred_second, pred_first, "PAD", "OTH"]}
        _, detail = score_groups(user, actual)
        e1 = next(d for d in detail if d["team"] == pred_first)
        e2 = next(d for d in detail if d["team"] == pred_second)
        return e1["points"], e1["note"], e2["note"]

    def test_sui_pred1_real2_earns_full(self):
        pts, note, _ = self._swap_group("SUI", "MEX")
        assert pts == 1.0
        assert note == "exacto"

    def test_egy_pred2_real1_earns_full(self):
        _, _, note = self._swap_group("GRP", "EGY")
        assert note == "exacto"

    def test_fra_pred1_real2_earns_full(self):
        pts, note, _ = self._swap_group("FRA", "GER")
        assert pts == 1.0
        assert note == "exacto"

    def test_col_pred2_real1_earns_full(self):
        _, _, note = self._swap_group("ARG", "COL")
        assert note == "exacto"

    def test_eng_pred2_real1_earns_full(self):
        _, _, note = self._swap_group("URY", "ENG")
        assert note == "exacto"

    def test_five_swapped_pairs_yield_10_not_5(self):
        """Five top-2 swaps should produce 10 pts total (5×1.0 each pair), not 5×0.5 each."""
        swaps = [
            ("SUI", "MEX"),
            ("EGY", "ALG"),
            ("FRA", "GER"),
            ("COL", "ARG"),
            ("ENG", "URY"),
        ]
        total = 0.0
        for pred1, pred2 in swaps:
            user = {"X": [pred1, pred2, "**"]}  # wildcard 3rd slot → 0
            actual = {"GROUP_X": [pred2, pred1, "OTHER", "OTH2"]}
            pts, _ = score_groups(user, actual)
            # pred1 earns 1.0, pred2 earns 1.0, "**" wildcard → 0
            total += pts
        assert total == 10.0


# ==============================================================================
# score_groups — qualifying-thirds aware (2026-06-26)
# ==============================================================================


class TestScoreGroupsQualifyingThirds:
    """Tests for the new qualifying_thirds parameter in score_groups."""

    # -- exact 3rd with qualifying set ------------------------------------------

    def test_qualifying_3rd_exact_match_scores_1(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset({"BRA"})
        pts, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(1.0)
        assert bra["note"] == "exacto"

    def test_non_qualifying_exact_3rd_scores_0(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset()  # BRA not in qualifying
        pts, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(NON_QUALIFYING_THIRD_SCORE)
        assert bra["note"] == "fallo"

    def test_non_qualifying_exact_3rd_score_constant_is_zero(self):
        assert NON_QUALIFYING_THIRD_SCORE == 0.0

    # -- boundary cases (one top-2, one 3rd) ------------------------------------

    def test_boundary_pred1_actual3_qualifying_scores_0_5(self):
        # pred=1, actual=3 (BRA qualifies) -> 0.5
        user = {"A": ["BRA", "ESP", "GER"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset({"BRA"})
        pts, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(0.5)
        assert bra["note"] == "clasifica"

    def test_boundary_pred1_actual3_non_qualifying_scores_0(self):
        # pred=1, actual=3 (BRA does NOT qualify) -> 0.0
        user = {"A": ["BRA", "ESP", "GER"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset()  # empty
        pts, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(NON_QUALIFYING_THIRD_SCORE)
        assert bra["note"] == "fallo"

    def test_boundary_pred2_actual3_non_qualifying_scores_0(self):
        user = {"A": ["GER", "BRA", "ESP"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset()  # BRA not qualifying
        _, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(0.0)
        assert bra["note"] == "fallo"

    def test_boundary_pred3_actual1_always_scores_0_5(self):
        # pred=3, actual=1 -- team is top-2, definitely advances, qualifying set irrelevant
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["BRA", "ESP", "GER", "USA"]}  # BRA is 1st
        qualifying = frozenset()  # empty set but BRA is actual 1st -> always advances
        _, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(0.5)
        assert bra["note"] == "clasifica"

    def test_boundary_pred3_actual2_always_scores_0_5(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "BRA", "USA", "FRA"]}  # BRA is 2nd
        qualifying = frozenset()  # empty, but BRA actual 2nd -> always advances
        _, detail = score_groups(user, actual, qualifying)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(0.5)
        assert bra["note"] == "clasifica"

    # -- top-2 zone unaffected by qualifying set ---------------------------------

    def test_top2_swap_unaffected_by_qualifying_set(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["ESP", "GER", "BRA", "USA"]}  # GER/ESP swapped
        qualifying = frozenset({"BRA"})
        _, detail = score_groups(user, actual, qualifying)
        ger = next(d for d in detail if d["team"] == "GER")
        esp = next(d for d in detail if d["team"] == "ESP")
        assert ger["points"] == pytest.approx(1.0)
        assert ger["note"] == "exacto"
        assert esp["points"] == pytest.approx(1.0)
        assert esp["note"] == "exacto"

    def test_top2_exact_unaffected_by_empty_qualifying_set(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "USA", "BRA"]}  # GER/ESP exact top-2
        qualifying = frozenset()
        _, detail = score_groups(user, actual, qualifying)
        ger = next(d for d in detail if d["team"] == "GER")
        assert ger["points"] == pytest.approx(1.0)
        assert ger["note"] == "exacto"

    # -- backward compat (qualifying_thirds=None) --------------------------------

    def test_backward_compat_none_all_3rds_qualify(self):
        # qualifying_thirds=None -> treat all 3rds as qualifying (original behavior)
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts, detail = score_groups(user, actual, None)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(1.0)
        assert bra["note"] == "exacto"

    def test_backward_compat_boundary_none_all_3rds_qualify(self):
        # pred=1, actual=3; qualifying=None -> clasifica (unchanged from old behavior)
        user = {"A": ["BRA", "ESP", "GER"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        _, detail = score_groups(user, actual, None)
        bra = next(d for d in detail if d["team"] == "BRA")
        assert bra["points"] == pytest.approx(0.5)
        assert bra["note"] == "clasifica"

    def test_default_call_no_qualifying_set_is_same_as_none(self):
        # Calling score_groups without qualifying_thirds == passing None
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        pts_default, _ = score_groups(user, actual)
        pts_none, _ = score_groups(user, actual, None)
        assert pts_default == pts_none

    # -- total points computation ------------------------------------------------

    def test_total_with_non_qualifying_3rd(self):
        # GER exact 1st (1.0) + ESP exact 2nd (1.0) + BRA exact 3rd not qualifying (0.0)
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset()  # BRA not qualifying
        pts, _ = score_groups(user, actual, qualifying)
        assert pts == pytest.approx(2.0)

    def test_total_with_qualifying_3rd(self):
        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset({"BRA"})
        pts, _ = score_groups(user, actual, qualifying)
        assert pts == pytest.approx(3.0)

    # -- alias passes qualifying_thirds through ----------------------------------

    def test_alias_passes_qualifying_thirds(self):
        from worldcup_bot.porra.scoring import score_user_groups_detail

        user = {"A": ["GER", "ESP", "BRA"]}
        actual = {"GROUP_A": ["GER", "ESP", "BRA", "USA"]}
        qualifying = frozenset()  # BRA not qualifying
        r1 = score_groups(user, actual, qualifying)
        r2 = score_user_groups_detail(user, actual, qualifying)
        assert r1 == r2

