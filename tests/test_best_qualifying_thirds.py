"""Tests for best_qualifying_thirds -- FIFA third-place ranking algorithm.

Pure function; no I/O, no network.
"""

from __future__ import annotations

import logging

import pytest

from worldcup_bot.porra.scoring import NUM_QUALIFYING_THIRDS, best_qualifying_thirds


# -- helpers -------------------------------------------------------------------


def _standings(group: str, thirds: tuple[str, int, int, int]) -> dict[str, list[dict]]:
    """Return a single-group full-standings dict where index 2 is the 3rd team.

    thirds: (tla, points, goal_difference, goals_for) for the 3rd-place entry.
    The 1st and 2nd entries have placeholder values far above the third's.
    """
    tla, pts, gd, gf = thirds
    return {
        group: [
            {"tla": f"{group}_1", "points": pts + 9, "goal_difference": 10, "goals_for": 10},
            {"tla": f"{group}_2", "points": pts + 3, "goal_difference": 5, "goals_for": 5},
            {"tla": tla, "points": pts, "goal_difference": gd, "goals_for": gf},
        ]
    }


def _twelve_groups(thirds: list[tuple[str, int, int, int]]) -> dict[str, list[dict]]:
    """Build full_group_standings for 12 groups from a list of 3rd-place tuples.

    Each tuple: (tla, points, goal_difference, goals_for).
    Groups are assigned letters A-L.
    """
    assert len(thirds) == 12
    result: dict[str, list[dict]] = {}
    for i, (tla, pts, gd, gf) in enumerate(thirds):
        group = f"GROUP_{chr(65 + i)}"
        result[group] = [
            {"tla": f"D1{i}", "points": pts + 9, "goal_difference": 10, "goals_for": 10},
            {"tla": f"D2{i}", "points": pts + 3, "goal_difference": 5, "goals_for": 5},
            {"tla": tla, "points": pts, "goal_difference": gd, "goals_for": gf},
            {"tla": f"D4{i}", "points": 0, "goal_difference": -10, "goals_for": 0},
        ]
    return result


# ==============================================================================
# empty / short inputs
# ==============================================================================


class TestBestQualifyingThirdsEmpty:
    def test_empty_standings_returns_empty(self):
        assert best_qualifying_thirds({}) == frozenset()

    def test_group_with_fewer_than_3_entries_skipped(self):
        standings = {
            "GROUP_A": [
                {"tla": "A1", "points": 9, "goal_difference": 5, "goals_for": 7},
                {"tla": "A2", "points": 6, "goal_difference": 2, "goals_for": 4},
            ]
        }
        assert best_qualifying_thirds(standings) == frozenset()

    def test_group_with_exactly_3_entries_yields_third(self):
        standings = _standings("GROUP_A", ("BRA", 3, 0, 1))
        result = best_qualifying_thirds(standings)
        assert "BRA" in result

    def test_fewer_than_8_thirds_all_qualify(self):
        combined: dict[str, list[dict]] = {}
        for letter in "ABCDE":
            combined.update(_standings(f"GROUP_{letter}", (f"T{letter}", 3, 0, 1)))
        result = best_qualifying_thirds(combined)
        assert len(result) == 5
        assert all(f"T{l}" in result for l in "ABCDE")


# ==============================================================================
# exactly 8 selected from 12 with clear ordering
# ==============================================================================


class TestBestQualifyingThirdsExactSelection:
    def test_exactly_8_selected_from_12(self):
        # Groups A-H have 3rd with 6 pts, I-L have 3rd with 3 pts
        thirds = [(f"T{chr(65+i)}", 6 if i < 8 else 3, 0, 0) for i in range(12)]
        standings = _twelve_groups(thirds)
        result = best_qualifying_thirds(standings)
        assert len(result) == NUM_QUALIFYING_THIRDS  # 8

    def test_top_8_qualify_bottom_4_do_not(self):
        # Clearly distinct points: 9,8,...,1 (descending)
        thirds = [(f"T{chr(65+i)}", 12 - i, 0, 0) for i in range(12)]
        standings = _twelve_groups(thirds)
        result = best_qualifying_thirds(standings)
        assert len(result) == 8
        for i in range(8):
            assert f"T{chr(65+i)}" in result, f"T{chr(65+i)} should qualify"
        for i in range(8, 12):
            assert f"T{chr(65+i)}" not in result, f"T{chr(65+i)} should NOT qualify"

    def test_returns_frozenset(self):
        thirds = [(f"T{chr(65+i)}", 12 - i, 0, 0) for i in range(12)]
        result = best_qualifying_thirds(_twelve_groups(thirds))
        assert isinstance(result, frozenset)


# ==============================================================================
# tiebreakers
# ==============================================================================


class TestBestQualifyingThirdsTiebreakers:
    def test_goal_difference_breaks_points_tie(self):
        # Groups A-K: thirds have 4 pts, 0 gd.  GROUP_L: third has 4 pts, +3 gd.
        # GROUP_L's third ranks first; one of the A-K thirds should be 9th.
        thirds = [(f"TK{i}", 4, 0, 0) for i in range(11)]  # 11 at 4pts/0gd
        thirds.append(("TBEST", 4, 3, 0))                    # 1 at 4pts/+3gd
        standings = _twelve_groups(thirds)
        result = best_qualifying_thirds(standings)
        assert "TBEST" in result  # highest gd always qualifies

    def test_goals_for_breaks_gd_tie(self):
        # 3 thirds with (4pts, 1gd, 2gf) and 9 with (4pts, 1gd, 0gf).
        # goals_for tiebreaker ensures all 3 high-gf teams outrank the low-gf teams.
        thirds = [(f"TH{i}", 4, 1, 2) for i in range(3)]
        thirds += [(f"TL{i}", 4, 1, 0) for i in range(9)]
        standings = _twelve_groups(thirds)
        result = best_qualifying_thirds(standings)
        # All 3 high-gf thirds rank above all low-gf thirds -> must qualify
        assert all(f"TH{i}" in result for i in range(3))
        # Exactly 8 qualify total; 4 of the 9 low-gf thirds do not qualify
        assert len(result) == 8
        assert sum(1 for i in range(9) if f"TL{i}" not in result) == 4

    def test_points_dominate_over_gd(self):
        # One third with 3pts/+10gd vs eleven thirds with 6pts/0gd.
        # The 6-pt thirds rank above the 3-pt one regardless of gd.
        thirds = [(f"T6_{i}", 6, 0, 0) for i in range(11)]
        thirds.append(("T3_HIGHGD", 3, 10, 5))
        standings = _twelve_groups(thirds)
        result = best_qualifying_thirds(standings)
        assert "T3_HIGHGD" not in result

    def test_points_dominate_over_goals_for(self):
        thirds = [(f"T6_{i}", 6, 0, 0) for i in range(11)]
        thirds.append(("T3_HIGHGF", 3, 0, 20))
        standings = _twelve_groups(thirds)
        result = best_qualifying_thirds(standings)
        assert "T3_HIGHGF" not in result


# ==============================================================================
# stable fallback (full tie)
# ==============================================================================


class TestBestQualifyingThirdsStableFallback:
    def test_full_tie_selects_deterministically(self):
        # All 12 thirds have identical (pts=3, gd=0, gf=0). The stable
        # fallback sorts by group letter then TLA -- same input always gives
        # the same 8.
        thirds = [(f"Z{chr(65+i)}", 3, 0, 0) for i in range(12)]
        standings = _twelve_groups(thirds)
        r1 = best_qualifying_thirds(standings)
        r2 = best_qualifying_thirds(standings)
        assert r1 == r2

    def test_full_tie_uses_group_letter_then_tla_order(self):
        # 12 thirds, all equal stats.  Stable sort: GROUP_A first, GROUP_L last.
        # So the 8 that qualify should be from the first 8 groups (A-H)
        # because their group keys sort lexicographically before I-L.
        thirds_data = []
        for i in range(12):
            group = f"GROUP_{chr(65+i)}"
            tla = f"T{chr(65+i)}"
            # equal stats for all
            thirds_data.append((group, tla, 3, 0, 0))

        standings: dict[str, list[dict]] = {}
        for group, tla, pts, gd, gf in thirds_data:
            standings[group] = [
                {"tla": f"{group}_1", "points": pts + 9, "goal_difference": 10, "goals_for": 10},
                {"tla": f"{group}_2", "points": pts + 3, "goal_difference": 5, "goals_for": 5},
                {"tla": tla, "points": pts, "goal_difference": gd, "goals_for": gf},
            ]

        result = best_qualifying_thirds(standings)
        # First 8 group letters (A-H) should qualify
        for letter in "ABCDEFGH":
            assert f"T{letter}" in result, f"T{letter} should qualify (stable fallback)"
        for letter in "IJKL":
            assert f"T{letter}" not in result, f"T{letter} should NOT qualify (stable fallback)"

    def test_full_tie_at_boundary_logs_warning(self, caplog):
        thirds = [(f"T{chr(65+i)}", 3, 0, 0) for i in range(12)]
        standings = _twelve_groups(thirds)
        with caplog.at_level(logging.WARNING, logger="worldcup_bot.porra.scoring"):
            best_qualifying_thirds(standings)
        assert any("tie at boundary" in r.message for r in caplog.records)

    def test_no_warning_when_no_tie(self, caplog):
        thirds = [(f"T{chr(65+i)}", 12 - i, 0, 0) for i in range(12)]
        with caplog.at_level(logging.WARNING, logger="worldcup_bot.porra.scoring"):
            best_qualifying_thirds(_twelve_groups(thirds))
        assert not any("tie at boundary" in r.message for r in caplog.records)
