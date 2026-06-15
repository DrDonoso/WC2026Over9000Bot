"""Shared pytest fixtures for the worldcup_bot test suite."""

from __future__ import annotations

import sys
import os

# Ensure src/ is on the path in case the package is not pip-installed.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import worldcup_bot.porra.predictions as pred_module
from worldcup_bot.config import Settings


# ── cache isolation ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_predictions_cache():
    """Reset the module-level hot-reload state before *and* after every test."""
    pred_module._cached_path = None
    pred_module._cached_mtime = 0.0
    pred_module._cached_data = {}
    yield
    pred_module._cached_path = None
    pred_module._cached_mtime = 0.0
    pred_module._cached_data = {}


@pytest.fixture(autouse=True)
def reset_api_default_cache():
    """Reset the process-wide shared API cache before and after every test."""
    from worldcup_bot.api.cache import reset_default_cache
    reset_default_cache()
    yield
    reset_default_cache()


# ── settings ───────────────────────────────────────────────────────────────────


@pytest.fixture
def settings():
    return Settings(
        telegram_bot_token="test-telegram-token",
        football_data_api_key="test-api-key",
    )


# ── minimal scoring fixtures (for pure-function unit tests) ───────────────────


@pytest.fixture
def sample_user_groups():
    """Three-group user prediction dict (no need for all 12 in unit tests)."""
    return {
        "A": ["GER", "ESP", "BRA"],
        "B": ["FRA", "ARG", "ENG"],
        "C": ["POR", "NED", "URU"],
    }


@pytest.fixture
def sample_actual_standings():
    """Three-group actual standings in football-data.org API key format."""
    return {
        "GROUP_A": ["GER", "ESP", "BRA", "USA"],
        "GROUP_B": ["FRA", "ARG", "ENG", "MEX"],
        "GROUP_C": ["POR", "NED", "URU", "CAN"],
    }


# ── full predictions fixture (all 12 groups, two users) ───────────────────────


@pytest.fixture
def sample_predictions():
    """
    Pre-validated predictions dict mirroring the structure produced by
    predictions.load().  Two users, all 12 WC2026 groups, all 5 KO stages.
    """
    groups1 = {
        "A": ["GER", "ESP", "BRA"],
        "B": ["FRA", "ARG", "ENG"],
        "C": ["POR", "NED", "URU"],
        "D": ["BEL", "CRO", "ITA"],
        "E": ["COL", "MEX", "DEN"],
        "F": ["USA", "POL", "AUT"],
        "G": ["TUR", "MAR", "SUI"],
        "H": ["ECU", "NGA", "CHI"],
        "I": ["JPN", "KOR", "CIV"],
        "J": ["VEN", "PAR", "CAN"],
        "K": ["EGY", "ALG", "AUS"],
        "L": ["PER", "GHA", "SRB"],
    }
    ko1 = {
        "round_of_32": [
            "ESP", "FRA", "ARG", "BRA", "GER", "ENG", "POR", "NED",
            "COL", "MEX", "USA", "JPN", "MAR", "BEL", "CRO", "ITA",
        ],
        "round_of_16": ["ESP", "FRA", "ARG", "BRA", "GER", "ENG", "POR", "NED"],
        "quarter_finals": ["ESP", "FRA", "ARG", "BRA"],
        "semi_finals": ["ESP", "FRA"],
        "final": ["ESP"],
    }
    # user2 reverses every group (tests off-by-one / fallo)
    groups2 = {k: list(reversed(v)) for k, v in groups1.items()}
    ko2 = {
        "round_of_32": [
            "FRA", "ESP", "ARG", "BRA", "ENG", "GER", "NED", "POR",
            "MEX", "COL", "JPN", "USA", "BEL", "MAR", "ITA", "CRO",
        ],
        "round_of_16": ["FRA", "ESP", "ARG", "BRA", "ENG", "GER", "NED", "POR"],
        "quarter_finals": ["FRA", "ESP", "ARG", "BRA"],
        "semi_finals": ["FRA", "ESP"],
        "final": ["FRA"],
    }
    return {
        "participants": {
            "user1": {
                "display_name": "Player One",
                "base_score": 0.0,
                "groups": groups1,
                "knockout": ko1,
            },
            "user2": {
                "display_name": "Player Two",
                "base_score": 5.0,
                "groups": groups2,
                "knockout": ko2,
            },
        }
    }


# ── API response fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def sample_standings_json():
    """Minimal football-data.org /standings API response (one group)."""
    return {
        "standings": [
            {
                "group": "GROUP_A",
                "table": [
                    {
                        "position": 1,
                        "team": {"tla": "GER", "name": "Germany"},
                        "points": 6,
                        "playedGames": 3,
                    },
                    {
                        "position": 2,
                        "team": {"tla": "ESP", "name": "Spain"},
                        "points": 4,
                        "playedGames": 3,
                    },
                    {
                        "position": 3,
                        "team": {"tla": "BRA", "name": "Brazil"},
                        "points": 3,
                        "playedGames": 3,
                    },
                    {
                        "position": 4,
                        "team": {"tla": "USA", "name": "USA"},
                        "points": 0,
                        "playedGames": 3,
                    },
                ],
            }
        ]
    }


@pytest.fixture
def sample_matches_json():
    """Three matches: one finished GROUP_STAGE, one scheduled LAST_16, one finished LAST_16."""
    return {
        "matches": [
            {
                "id": 1,
                "utcDate": "2026-06-15T18:00:00Z",
                "status": "FINISHED",
                "stage": "GROUP_STAGE",
                "group": "GROUP_A",
                "homeTeam": {"tla": "GER", "name": "Germany"},
                "awayTeam": {"tla": "ESP", "name": "Spain"},
                "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
            },
            {
                "id": 2,
                "utcDate": "2026-06-28T15:00:00Z",
                "status": "SCHEDULED",
                "stage": "LAST_16",
                "group": None,
                "homeTeam": {"tla": "ESP", "name": "Spain"},
                "awayTeam": {"tla": "FRA", "name": "France"},
                "score": {"fullTime": {"home": None, "away": None}, "winner": None},
            },
            {
                "id": 3,
                "utcDate": "2026-06-29T18:00:00Z",
                "status": "FINISHED",
                "stage": "LAST_16",
                "group": None,
                "homeTeam": {"tla": "BRA", "name": "Brazil"},
                "awayTeam": {"tla": "ARG", "name": "Argentina"},
                "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
            },
        ]
    }
