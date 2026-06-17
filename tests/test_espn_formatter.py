"""Tests for the ESPN stats formatter."""

from __future__ import annotations

import pytest

from worldcup_bot.espn.formatter import format_match_stats


# ── helpers ───────────────────────────────────────────────────────────────────


class FakeMatch:
    def __init__(
        self,
        home_tla: str = "ESP",
        away_tla: str = "FRA",
        home_name: str = "Spain",
        away_name: str = "France",
        home_score: int | None = 2,
        away_score: int | None = 1,
    ):
        self.home_tla = home_tla
        self.away_tla = away_tla
        self.home_name = home_name
        self.away_name = away_name
        self.home_score = home_score
        self.away_score = away_score


def _full_stats(home_overrides: dict | None = None, away_overrides: dict | None = None) -> dict:
    """Build a complete stats dict as returned by ESPNClient."""
    home = {
        "possessionPct": "54.2",
        "totalShots": "13",
        "shotsOnTarget": "5",
        "wonCorners": "3",
        "foulsCommitted": "6",
        "yellowCards": "2",
        "redCards": "0",
        "offsides": "1",
        "saves": "2",
        "passPct": "0.87",
    }
    away = {
        "possessionPct": "45.8",
        "totalShots": "8",
        "shotsOnTarget": "2",
        "wonCorners": "4",
        "foulsCommitted": "10",
        "yellowCards": "1",
        "redCards": "0",
        "offsides": "3",
        "saves": "4",
        "passPct": "0.83",
    }
    if home_overrides:
        home.update(home_overrides)
    if away_overrides:
        away.update(away_overrides)
    return {
        "home": {"name": "Spain", "stats": home},
        "away": {"name": "France", "stats": away},
    }


# ── tests ─────────────────────────────────────────────────────────────────────


class TestFormatMatchStats:
    def test_header_present(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "📊" in text
        assert "<b>" in text
        assert "Estadísticas" in text
        # Scoreline no longer in stats header (it lives in section 1 / final result)
        assert "2-1" not in text
        assert "Spain" not in text
        assert "France" not in text

    def test_possession_with_percent(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "Posesión" in text
        assert "54%" in text
        assert "46%" in text

    def test_possession_emoji(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "🔵" in text

    def test_shots_row(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "🎯" in text
        assert "Tiros" in text
        assert "13" in text
        assert "a puerta" in text

    def test_corners_row(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "🚩" in text
        assert "Córners" in text

    def test_fouls_row(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "⚠️" in text
        assert "Faltas" in text

    def test_yellow_cards_emoji(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "🟨" in text
        assert "Amarillas" in text

    def test_red_cards_omitted_when_both_zero(self):
        stats = _full_stats({"redCards": "0"}, {"redCards": "0"})
        text = format_match_stats(FakeMatch(), stats)
        assert "🟥" not in text
        assert "Rojas" not in text

    def test_red_cards_shown_when_nonzero(self):
        stats = _full_stats({"redCards": "1"}, {"redCards": "0"})
        text = format_match_stats(FakeMatch(), stats)
        assert "🟥" in text
        assert "Rojas" in text

    def test_offsides_row(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "Fueras de juego" in text

    def test_saves_row(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "🧤" in text
        assert "Paradas" in text

    def test_pass_accuracy_from_pct_fraction(self):
        stats = _full_stats({"passPct": "0.87"}, {"passPct": "0.83"})
        text = format_match_stats(FakeMatch(), stats)
        assert "Precisión de pase" in text
        assert "87%" in text
        assert "83%" in text

    def test_pass_accuracy_from_accurate_passes(self):
        # passPct absent, use accuratePasses/totalPasses
        home_stats = {k: v for k, v in _full_stats()["home"]["stats"].items() if k != "passPct"}
        home_stats["accuratePasses"] = "450"
        home_stats["totalPasses"] = "500"
        away_stats = {k: v for k, v in _full_stats()["away"]["stats"].items() if k != "passPct"}
        away_stats["accuratePasses"] = "400"
        away_stats["totalPasses"] = "500"
        stats = {
            "home": {"name": "Spain", "stats": home_stats},
            "away": {"name": "France", "stats": away_stats},
        }
        text = format_match_stats(FakeMatch(), stats)
        assert "90%" in text  # 450/500 * 100 = 90%

    def test_missing_stat_omits_row(self):
        # Remove possessionPct from both sides → Posesión row absent
        home_stats = {k: v for k, v in _full_stats()["home"]["stats"].items() if k != "possessionPct"}
        away_stats = {k: v for k, v in _full_stats()["away"]["stats"].items() if k != "possessionPct"}
        stats = {
            "home": {"name": "Spain", "stats": home_stats},
            "away": {"name": "France", "stats": away_stats},
        }
        text = format_match_stats(FakeMatch(), stats)
        assert "Posesión" not in text

    def test_none_score_still_renders(self):
        # Scores are no longer shown in the stats card — verify the card renders fine
        match = FakeMatch(home_score=None, away_score=None)
        text = format_match_stats(match, _full_stats())
        assert "📊" in text
        assert "Estadísticas" in text
        # Stat rows must still be present
        assert "Posesión" in text

    def test_special_chars_in_team_name_no_crash(self):
        # Team names are no longer rendered in the stats card header — verify no crash
        match = FakeMatch(home_name="<Spain&>", away_name="France")
        text = format_match_stats(match, _full_stats())
        assert "📊" in text
        assert "Estadísticas" in text
        # Team names should NOT appear in the stats card
        assert "Spain" not in text
        assert "France" not in text

    def test_spanish_labels(self):
        text = format_match_stats(FakeMatch(), _full_stats())
        assert "Posesión" in text
        assert "Tiros" in text
        assert "Córners" in text
        assert "Faltas" in text
        assert "Amarillas" in text
        assert "Fueras de juego" in text
        assert "Paradas" in text
        assert "Precisión de pase" in text
