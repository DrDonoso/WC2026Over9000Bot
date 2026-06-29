"""Tests for the porra face-off ("guerra de la porra")."""

from __future__ import annotations

from worldcup_bot.bot.formatters import format_match_camps
from worldcup_bot.porra.camps import MatchCamps, compute_match_camps


def _preds() -> dict:
    return {
        "participants": {
            "ann": {"display_name": "Ann", "groups": {"A": ["NED", "MAR", "RSA"]},
                    "knockout": {"round_of_32": ["NED"], "round_of_16": [], "quarter_finals": [],
                                 "semi_finals": [], "final": []}},
            "bob": {"display_name": "Bob", "groups": {"A": ["MAR", "NED", "RSA"]},
                    "knockout": {"round_of_32": ["MAR"], "round_of_16": [], "quarter_finals": [],
                                 "semi_finals": [], "final": []}},
            "cal": {"display_name": "Cal", "groups": {"A": ["CAN", "RSA", "MEX"]},
                    "knockout": {"round_of_32": ["CAN"], "round_of_16": [], "quarter_finals": [],
                                 "semi_finals": [], "final": []}},
        }
    }


# ── compute_match_camps ───────────────────────────────────────────────────────


class TestComputeMatchCamps:
    def test_knockout_splits_by_round_pick(self):
        camps = compute_match_camps("NED", "MAR", "LAST_32", None, _preds())
        assert camps.home_backers == ["Ann"]
        assert camps.away_backers == ["Bob"]

    def test_participant_with_neither_team_is_undecided(self):
        camps = compute_match_camps("NED", "MAR", "LAST_32", None, _preds())
        assert camps.undecided == ["Cal"]  # Cal picked CAN, neither NED nor MAR

    def test_total_backers_counts_both_camps(self):
        camps = compute_match_camps("NED", "MAR", "LAST_32", None, _preds())
        assert camps.total_backers == 2

    def test_group_stage_is_not_split(self):
        camps = compute_match_camps("NED", "MAR", "GROUP_STAGE", "GROUP_A", _preds())
        assert camps.home_backers == []
        assert camps.away_backers == []
        assert len(camps.undecided) == 3

    def test_uses_username_when_no_display_name(self):
        preds = {"participants": {"zoe": {"knockout": {"round_of_32": ["NED"]}}}}
        camps = compute_match_camps("NED", "MAR", "LAST_32", None, preds)
        assert camps.home_backers == ["@zoe"]

    def test_empty_predictions(self):
        camps = compute_match_camps("NED", "MAR", "LAST_32", None, {"participants": {}})
        assert camps.total_backers == 0


# ── format_match_camps (style B) ──────────────────────────────────────────────


class TestFormatMatchCamps:
    def _camps(self) -> MatchCamps:
        return MatchCamps(
            home_tla="NED", away_tla="MAR", home_name="Países Bajos", away_name="Marruecos",
            home_backers=["Patri", "Pilar"], away_backers=["David", "Miquel", "Víctor"],
            undecided=["Cristina"],
        )

    def test_has_title_bar_and_two_team_lines(self):
        text = format_match_camps(self._camps(), title="⚔️ ¿Con quién vas?")
        lines = text.splitlines()
        assert lines[0] == "⚔️ ¿Con quién vas?"
        assert "▓" in lines[1] and "░" in lines[1]
        assert "Países Bajos" in lines[2] and "Patri, Pilar" in lines[2]
        assert "Marruecos" in lines[3] and "David, Miquel, Víctor" in lines[3]

    def test_counts_reflect_backers(self):
        text = format_match_camps(self._camps())
        assert " 2  " in text and "  3 " in text  # 2 vs 3

    def test_undecided_never_shown(self):
        text = format_match_camps(self._camps())
        assert "Cristina" not in text
        assert "mojarse" not in text.lower()

    def test_empty_when_no_backers(self):
        camps = MatchCamps(home_tla="NED", away_tla="MAR")
        assert format_match_camps(camps) == ""

    def test_winner_side_home_marks_trophy_and_skull(self):
        text = format_match_camps(self._camps(), winner_side="home")
        home_line = next(l for l in text.splitlines() if "Países Bajos" in l)
        away_line = next(l for l in text.splitlines() if "Marruecos" in l)
        assert home_line.startswith("🏆")
        assert away_line.startswith("💀")

    def test_winner_side_away_marks_trophy_and_skull(self):
        text = format_match_camps(self._camps(), winner_side="away")
        home_line = next(l for l in text.splitlines() if "Países Bajos" in l)
        away_line = next(l for l in text.splitlines() if "Marruecos" in l)
        assert home_line.startswith("💀")
        assert away_line.startswith("🏆")

    def test_html_mode_bolds_team_and_escapes_names(self):
        camps = MatchCamps(
            home_tla="NED", away_tla="MAR", home_name="A&B", away_name="Marruecos",
            home_backers=["X<Y"], away_backers=["Z"],
        )
        text = format_match_camps(camps, use_html=True)
        assert "<b>A&amp;B</b>" in text
        assert "X&lt;Y" in text

    def test_plain_mode_no_html_tags(self):
        text = format_match_camps(self._camps(), use_html=False)
        assert "<b>" not in text

    def test_one_sided_still_shows_both_lines(self):
        camps = MatchCamps(
            home_tla="NED", away_tla="MAR", home_name="NED", away_name="MAR",
            home_backers=["A", "B"], away_backers=[],
        )
        text = format_match_camps(camps)
        away_line = next(l for l in text.splitlines() if l.endswith("MAR: —") or "MAR:" in l)
        assert "—" in away_line  # empty camp shown as dash
