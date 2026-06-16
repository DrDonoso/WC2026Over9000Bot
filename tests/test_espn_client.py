"""Tests for the ESPN Stats API client (ESPNClient)."""

from __future__ import annotations

import json

import pytest
import requests

from worldcup_bot.espn.client import ESPNClient


# ── helpers ───────────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body

    @property
    def text(self) -> str:
        return json.dumps(self._body) if not isinstance(self._body, str) else self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self._resp = response
        self.headers = {}

    def update(self, h: dict) -> None:
        self.headers.update(h)

    def get(self, url: str, **kwargs) -> FakeResponse:
        self._last_url = url
        self._last_kwargs = kwargs
        return self._resp


def _make_espn_summary(
    home_name: str = "Spain",
    away_name: str = "France",
    home_stats: dict | None = None,
    away_stats: dict | None = None,
) -> dict:
    """Build a minimal ESPN summary API response."""
    def _stats_list(d: dict) -> list:
        return [{"name": k, "displayValue": v} for k, v in d.items()]

    hs = home_stats or {
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
    as_ = away_stats or {
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
    return {
        "boxscore": {
            "teams": [
                {
                    "homeAway": "home",
                    "team": {"displayName": home_name},
                    "statistics": _stats_list(hs),
                },
                {
                    "homeAway": "away",
                    "team": {"displayName": away_name},
                    "statistics": _stats_list(as_),
                },
            ]
        }
    }


# ── tests ─────────────────────────────────────────────────────────────────────


class TestESPNClientParse:
    def test_returns_home_and_away(self):
        session = FakeSession(FakeResponse(200, _make_espn_summary()))
        client = ESPNClient(session=session)
        result = client.get_match_stats("12345")
        assert result is not None
        assert "home" in result
        assert "away" in result

    def test_home_name_parsed(self):
        session = FakeSession(FakeResponse(200, _make_espn_summary("Germany", "Brazil")))
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result["home"]["name"] == "Germany"
        assert result["away"]["name"] == "Brazil"

    def test_stat_values_parsed(self):
        session = FakeSession(FakeResponse(200, _make_espn_summary()))
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result["home"]["stats"]["possessionPct"] == "54.2"
        assert result["home"]["stats"]["totalShots"] == "13"
        assert result["away"]["stats"]["yellowCards"] == "1"

    def test_http_error_returns_none(self):
        session = FakeSession(FakeResponse(404, {}))
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result is None

    def test_empty_boxscore_returns_none(self):
        session = FakeSession(FakeResponse(200, {"boxscore": {"teams": []}}))
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result is None

    def test_missing_boxscore_returns_none(self):
        session = FakeSession(FakeResponse(200, {}))
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result is None

    def test_missing_side_returns_none(self):
        # Only one side present
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "boxscore": {
                        "teams": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Spain"},
                                "statistics": [],
                            }
                        ]
                    }
                },
            )
        )
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result is None

    def test_unknown_side_skipped(self):
        # Both teams have homeAway = "unknown" → neither side fills → returns None
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "boxscore": {
                        "teams": [
                            {"homeAway": "unknown", "team": {"displayName": "X"}, "statistics": []},
                            {"homeAway": "unknown", "team": {"displayName": "Y"}, "statistics": []},
                        ]
                    }
                },
            )
        )
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result is None

    def test_missing_stat_name_skipped(self):
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "boxscore": {
                        "teams": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "A"},
                                "statistics": [{"name": "", "displayValue": "5"}, {"name": "totalShots", "displayValue": "10"}],
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "B"},
                                "statistics": [],
                            },
                        ]
                    }
                },
            )
        )
        client = ESPNClient(session=session)
        result = client.get_match_stats("1")
        assert result is not None
        # empty-name stat skipped
        assert "" not in result["home"]["stats"]
        assert result["home"]["stats"]["totalShots"] == "10"

    def test_league_slug_default(self):
        client = ESPNClient()
        assert client._league == "fifa.world"

    def test_custom_league_slug(self):
        client = ESPNClient(league_slug="eng.1")
        assert client._league == "eng.1"
