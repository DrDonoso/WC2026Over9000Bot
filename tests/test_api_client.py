"""Tests for FootballDataClient and TTLCache.

All HTTP is mocked with the `responses` library — no real network calls.
"""

from __future__ import annotations

import time

import pytest
import responses as resp_lib

from worldcup_bot.api.cache import TTLCache
from worldcup_bot.api.client import FootballAPIError, FootballDataClient

BASE = "https://api.football-data.org/v4"
WC_STANDINGS = f"{BASE}/competitions/WC/standings"
WC_MATCHES = f"{BASE}/competitions/WC/matches"


# ── helpers ────────────────────────────────────────────────────────────────────


def _fresh_client() -> FootballDataClient:
    """Return a client with an empty TTLCache (avoids cross-test cache pollution)."""
    return FootballDataClient(api_key="test-key", competition_code="WC", cache=TTLCache(ttl=60))


# ══════════════════════════════════════════════════════════════════════════════
# TTLCache
# ══════════════════════════════════════════════════════════════════════════════


class TestTTLCache:
    def test_get_returns_none_for_missing_key(self):
        cache = TTLCache(ttl=60)
        assert cache.get("missing") is None

    def test_set_then_get_returns_value(self):
        cache = TTLCache(ttl=60)
        cache.set("key", {"data": 42})
        assert cache.get("key") == {"data": 42}

    def test_expired_entry_returns_none(self):
        cache = TTLCache(ttl=0.01)  # 10 ms TTL
        cache.set("k", "value")
        time.sleep(0.05)
        assert cache.get("k") is None

    def test_not_yet_expired_returns_value(self):
        cache = TTLCache(ttl=60)
        cache.set("k", "value")
        time.sleep(0.01)
        assert cache.get("k") == "value"

    def test_invalidate_removes_key(self):
        cache = TTLCache(ttl=60)
        cache.set("k", 1)
        cache.invalidate("k")
        assert cache.get("k") is None

    def test_invalidate_missing_key_is_noop(self):
        cache = TTLCache(ttl=60)
        cache.invalidate("no-such-key")  # must not raise

    def test_clear_removes_all_entries(self):
        cache = TTLCache(ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — standings
# ══════════════════════════════════════════════════════════════════════════════


class TestGetStandings:
    @resp_lib.activate
    def test_parse_standing_fields(self):
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={
                "standings": [
                    {
                        "group": "GROUP_A",
                        "table": [
                            {
                                "position": 1,
                                "team": {"tla": "GER", "name": "Germany"},
                                "points": 6,
                                "playedGames": 3,
                            }
                        ],
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        standings = client.get_standings()
        assert len(standings) == 1
        s = standings[0]
        assert s.group == "GROUP_A"
        assert s.position == 1
        assert s.tla == "GER"
        assert s.team_name == "Germany"
        assert s.points == 6
        assert s.played == 3

    @resp_lib.activate
    def test_parse_goal_difference_and_goals_for(self):
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={
                "standings": [
                    {
                        "group": "GROUP_A",
                        "table": [
                            {
                                "position": 1,
                                "team": {"tla": "GER", "name": "Germany"},
                                "points": 6,
                                "playedGames": 3,
                                "goalDifference": 4,
                                "goalsFor": 7,
                            }
                        ],
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        s = client.get_standings()[0]
        assert s.goal_difference == 4
        assert s.goals_for == 7

    @resp_lib.activate
    def test_goal_difference_goals_for_default_zero_when_absent(self):
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={
                "standings": [
                    {
                        "group": "GROUP_A",
                        "table": [
                            {
                                "position": 1,
                                "team": {"tla": "GER", "name": "Germany"},
                                "points": 6,
                                "playedGames": 3,
                                # goalDifference and goalsFor absent
                            }
                        ],
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        s = client.get_standings()[0]
        assert s.goal_difference == 0
        assert s.goals_for == 0

    @resp_lib.activate
    def test_multiple_groups_and_teams(self):
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={
                "standings": [
                    {
                        "group": "GROUP_A",
                        "table": [
                            {"position": 1, "team": {"tla": "GER", "name": "Germany"}, "points": 6, "playedGames": 3},
                            {"position": 2, "team": {"tla": "ESP", "name": "Spain"}, "points": 4, "playedGames": 3},
                        ],
                    },
                    {
                        "group": "GROUP_B",
                        "table": [
                            {"position": 1, "team": {"tla": "FRA", "name": "France"}, "points": 6, "playedGames": 3},
                        ],
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        standings = client.get_standings()
        assert len(standings) == 3
        groups = {s.group for s in standings}
        assert groups == {"GROUP_A", "GROUP_B"}

    @resp_lib.activate
    def test_real_api_format_group_a_normalized(self):
        """Regression: football-data.org returns 'Group A' (title case + space).
        Ensure get_standings() normalises it to 'GROUP_A'."""
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={
                "standings": [
                    {
                        "group": "Group A",
                        "table": [
                            {
                                "position": 1,
                                "team": {"tla": "MEX", "name": "Mexico"},
                                "points": 9,
                                "playedGames": 3,
                            }
                        ],
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        standings = client.get_standings()
        assert len(standings) == 1
        assert standings[0].group == "GROUP_A"

    @resp_lib.activate
    def test_real_api_format_multiple_groups_normalized(self):
        """Regression: 'Group A', 'Group B' both normalize to GROUP_X form."""
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={
                "standings": [
                    {
                        "group": "Group A",
                        "table": [
                            {"position": 1, "team": {"tla": "MEX", "name": "Mexico"}, "points": 9, "playedGames": 3},
                        ],
                    },
                    {
                        "group": "Group B",
                        "table": [
                            {"position": 1, "team": {"tla": "BRA", "name": "Brazil"}, "points": 7, "playedGames": 3},
                        ],
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        standings = client.get_standings()
        groups = {s.group for s in standings}
        assert groups == {"GROUP_A", "GROUP_B"}


        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"standings": []}, status=200)
        client = _fresh_client()
        assert client.get_standings() == []


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — matches
# ══════════════════════════════════════════════════════════════════════════════


class TestGetAllMatches:
    @resp_lib.activate
    def test_parse_match_fields(self):
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 99,
                        "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED",
                        "stage": "GROUP_STAGE",
                        "group": "GROUP_A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {
                            "fullTime": {"home": 2, "away": 1},
                            "winner": "HOME_TEAM",
                        },
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        matches = client.get_all_matches()
        assert len(matches) == 1
        m = matches[0]
        assert m.id == 99
        assert m.utc_date == "2026-06-15T18:00:00Z"
        assert m.status == "FINISHED"
        assert m.stage == "GROUP_STAGE"
        assert m.group == "GROUP_A"
        assert m.home_tla == "GER"
        assert m.away_tla == "ESP"
        assert m.home_score == 2
        assert m.away_score == 1
        assert m.winner == "HOME_TEAM"

    @resp_lib.activate
    def test_null_scores_parse_as_none(self):
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1,
                        "utcDate": "2026-06-28T15:00:00Z",
                        "status": "SCHEDULED",
                        "stage": "LAST_16",
                        "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        m = client.get_all_matches()[0]
        assert m.home_score is None
        assert m.away_score is None
        assert m.winner is None
        assert m.group is None


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — stage results
# ══════════════════════════════════════════════════════════════════════════════


class TestGetStageResults:
    @resp_lib.activate
    def test_returns_only_finished_matches_for_stage(self, sample_matches_json):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json=sample_matches_json, status=200)
        client = _fresh_client()
        results = client.get_stage_results("LAST_16")
        # Only the FINISHED LAST_16 match (id=3) qualifies
        assert len(results) == 1
        assert results[0].home_tla == "BRA"
        assert results[0].away_tla == "ARG"
        assert results[0].winner_tla == "BRA"  # HOME_TEAM won

    @resp_lib.activate
    def test_home_team_win_sets_winner_tla(self, sample_matches_json):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json=sample_matches_json, status=200)
        client = _fresh_client()
        results = client.get_stage_results("LAST_16")
        assert results[0].winner_tla == "BRA"

    @resp_lib.activate
    def test_away_team_win_sets_winner_tla(self):
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 10,
                        "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED",
                        "stage": "QUARTER_FINALS",
                        "group": None,
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "BRA", "name": "Brazil"},
                        "score": {
                            "fullTime": {"home": 0, "away": 1},
                            "winner": "AWAY_TEAM",
                        },
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        results = client.get_stage_results("QUARTER_FINALS")
        assert results[0].winner_tla == "BRA"  # AWAY_TEAM → away_tla

    @resp_lib.activate
    def test_scheduled_match_excluded(self, sample_matches_json):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json=sample_matches_json, status=200)
        client = _fresh_client()
        # Match id=2 is SCHEDULED LAST_16 — should be excluded
        results = client.get_stage_results("LAST_16")
        ids = [r.home_tla for r in results]
        assert "ESP" not in ids  # scheduled match not included

    @resp_lib.activate
    def test_different_stage_excluded(self, sample_matches_json):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json=sample_matches_json, status=200)
        client = _fresh_client()
        results = client.get_stage_results("QUARTER_FINALS")
        assert results == []  # no QUARTER_FINALS in sample


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    @resp_lib.activate
    def test_429_raises_football_api_error(self):
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={"message": "Rate limit exceeded"},
            status=429,
        )
        client = _fresh_client()
        with pytest.raises(FootballAPIError) as exc_info:
            client.get_standings()
        assert exc_info.value.status_code == 429

    @resp_lib.activate
    def test_non_200_raises_football_api_error(self):
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"message": "Server error"}, status=500)
        client = _fresh_client()
        with pytest.raises(FootballAPIError) as exc_info:
            client.get_standings()
        assert exc_info.value.status_code == 500

    @resp_lib.activate
    def test_401_raises_football_api_error(self):
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"message": "Unauthorized"}, status=401)
        client = _fresh_client()
        with pytest.raises(FootballAPIError) as exc_info:
            client.get_standings()
        assert exc_info.value.status_code == 401

    @resp_lib.activate
    def test_404_raises_football_api_error(self):
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"message": "Not found"}, status=404)
        client = _fresh_client()
        with pytest.raises(FootballAPIError) as exc_info:
            client.get_standings()
        assert exc_info.value.status_code == 404

    def test_football_api_error_stores_status_code(self):
        exc = FootballAPIError(429, "rate limited")
        assert exc.status_code == 429
        assert isinstance(exc, Exception)


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — TTL caching
# ══════════════════════════════════════════════════════════════════════════════


class TestCaching:
    @resp_lib.activate
    def test_two_calls_within_ttl_make_one_http_request(self):
        resp_lib.add(
            resp_lib.GET,
            WC_STANDINGS,
            json={"standings": []},
            status=200,
        )
        client = _fresh_client()

        client.get_standings()
        client.get_standings()

        # Only one real HTTP call was made
        assert len(resp_lib.calls) == 1

    @resp_lib.activate
    def test_second_call_returns_same_data(self):
        standings_json = {
            "standings": [
                {
                    "group": "GROUP_A",
                    "table": [
                        {"position": 1, "team": {"tla": "GER", "name": "Germany"}, "points": 6, "playedGames": 3}
                    ],
                }
            ]
        }
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json=standings_json, status=200)
        client = _fresh_client()

        first = client.get_standings()
        second = client.get_standings()

        assert first == second

    @resp_lib.activate
    def test_different_endpoint_cached_separately(self):
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"standings": []}, status=200)
        resp_lib.add(resp_lib.GET, WC_MATCHES, json={"matches": []}, status=200)

        client = _fresh_client()
        client.get_standings()
        client.get_all_matches()

        # One call for standings, one for matches
        assert len(resp_lib.calls) == 2

    @resp_lib.activate
    def test_expired_cache_makes_new_request(self):
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"standings": []}, status=200)
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"standings": []}, status=200)

        cache = TTLCache(ttl=0.01)  # 10 ms TTL
        client = FootballDataClient(api_key="test-key", competition_code="WC", cache=cache)

        client.get_standings()
        time.sleep(0.05)  # Let TTL expire
        client.get_standings()

        assert len(resp_lib.calls) == 2

    @resp_lib.activate
    def test_get_knockout_results_uses_single_cached_matches_call(self):
        """get_knockout_results calls get_stage_results for all 5 stages,
        but because get_all_matches is cached, only one HTTP call is made."""
        resp_lib.add(resp_lib.GET, WC_MATCHES, json={"matches": []}, status=200)
        client = _fresh_client()

        result = client.get_knockout_results()

        assert len(resp_lib.calls) == 1
        assert isinstance(result, dict)
        # All 5 stages should be present as keys
        from worldcup_bot.data.stages import KNOCKOUT_STAGES
        for api_stage, _, _ in KNOCKOUT_STAGES:
            assert api_stage in result


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — get_finished_groups
# ══════════════════════════════════════════════════════════════════════════════


class TestGetFinishedGroups:
    @resp_lib.activate
    def test_empty_matches_returns_empty_set(self):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json={"matches": []}, status=200)
        client = _fresh_client()
        assert client.get_finished_groups() == set()

    @resp_lib.activate
    def test_all_finished_group_returned(self):
        """A group whose every match is FINISHED appears in the result."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-06-16T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "USA", "name": "USA"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        finished = client.get_finished_groups()
        assert "GROUP_A" in finished

    @resp_lib.activate
    def test_any_non_finished_match_excludes_group(self):
        """A group with at least one non-FINISHED match is NOT in the result."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-06-20T18:00:00Z",
                        "status": "SCHEDULED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "USA", "name": "USA"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        finished = client.get_finished_groups()
        assert "GROUP_A" not in finished

    @resp_lib.activate
    def test_knockout_matches_group_none_ignored(self):
        """Knockout matches (group=None) are ignored and do not appear in the result."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert client.get_finished_groups() == set()

    @resp_lib.activate
    def test_only_finished_group_in_mixed_scenario(self):
        """Group A all FINISHED; Group B has a SCHEDULED match → only GROUP_A returned."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-06-16T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group B",
                        "homeTeam": {"tla": "FRA", "name": "France"},
                        "awayTeam": {"tla": "ARG", "name": "Argentina"},
                        "score": {"fullTime": {"home": 1, "away": 2}, "winner": "AWAY_TEAM"},
                    },
                    {
                        "id": 3, "utcDate": "2026-06-20T18:00:00Z",
                        "status": "SCHEDULED", "stage": "GROUP_STAGE", "group": "Group B",
                        "homeTeam": {"tla": "ENG", "name": "England"},
                        "awayTeam": {"tla": "MEX", "name": "Mexico"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        finished = client.get_finished_groups()
        assert finished == {"GROUP_A"}

    @resp_lib.activate
    def test_group_identifiers_normalized_to_group_x(self):
        """Real API returns 'Group A' (title case); result must contain 'GROUP_A'."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group L",
                        "homeTeam": {"tla": "PER", "name": "Peru"},
                        "awayTeam": {"tla": "GHA", "name": "Ghana"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        finished = client.get_finished_groups()
        assert "GROUP_L" in finished
        assert "Group L" not in finished


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — get_started_groups
# ══════════════════════════════════════════════════════════════════════════════


class TestGetStartedGroups:
    @resp_lib.activate
    def test_empty_matches_returns_empty_set(self):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json={"matches": []}, status=200)
        client = _fresh_client()
        assert client.get_started_groups() == set()

    @resp_lib.activate
    def test_group_with_at_least_one_finished_match_is_included(self):
        """A group with ≥1 FINISHED match is returned even if others are SCHEDULED."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-06-20T18:00:00Z",
                        "status": "SCHEDULED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "USA", "name": "USA"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert "GROUP_A" in client.get_started_groups()

    @resp_lib.activate
    def test_group_with_only_scheduled_matches_excluded(self):
        """A group with only SCHEDULED/TIMED matches (no FINISHED) is NOT returned."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-20T18:00:00Z",
                        "status": "SCHEDULED", "stage": "GROUP_STAGE", "group": "Group B",
                        "homeTeam": {"tla": "FRA", "name": "France"},
                        "awayTeam": {"tla": "ARG", "name": "Argentina"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                    {
                        "id": 2, "utcDate": "2026-06-21T18:00:00Z",
                        "status": "TIMED", "stage": "GROUP_STAGE", "group": "Group B",
                        "homeTeam": {"tla": "ENG", "name": "England"},
                        "awayTeam": {"tla": "MEX", "name": "Mexico"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert "GROUP_B" not in client.get_started_groups()

    @resp_lib.activate
    def test_group_with_only_in_play_matches_excluded(self):
        """A group with only IN_PLAY matches (no FINISHED) is NOT returned."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-20T18:00:00Z",
                        "status": "IN_PLAY", "stage": "GROUP_STAGE", "group": "Group C",
                        "homeTeam": {"tla": "POR", "name": "Portugal"},
                        "awayTeam": {"tla": "NED", "name": "Netherlands"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert "GROUP_C" not in client.get_started_groups()

    @resp_lib.activate
    def test_mixed_scenario_only_started_groups_returned(self):
        """Group A has 1 FINISHED match (started); Group B has only SCHEDULED (not started)."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-06-20T18:00:00Z",
                        "status": "SCHEDULED", "stage": "GROUP_STAGE", "group": "Group B",
                        "homeTeam": {"tla": "FRA", "name": "France"},
                        "awayTeam": {"tla": "ARG", "name": "Argentina"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        started = client.get_started_groups()
        assert started == {"GROUP_A"}

    @resp_lib.activate
    def test_knockout_matches_ignored(self):
        """Knockout matches (group=None) are not counted and never appear in the result."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert client.get_started_groups() == set()

    @resp_lib.activate
    def test_group_identifiers_normalized_to_group_x(self):
        """API returns 'Group L' (title case); result must contain 'GROUP_L'."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "Group L",
                        "homeTeam": {"tla": "PER", "name": "Peru"},
                        "awayTeam": {"tla": "GHA", "name": "Ghana"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        started = client.get_started_groups()
        assert "GROUP_L" in started
        assert "Group L" not in started


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — get_finished_stages
# ══════════════════════════════════════════════════════════════════════════════


class TestGetFinishedStages:
    @resp_lib.activate
    def test_empty_matches_returns_empty_set(self):
        resp_lib.add(resp_lib.GET, WC_MATCHES, json={"matches": []}, status=200)
        client = _fresh_client()
        assert client.get_finished_stages() == set()

    @resp_lib.activate
    def test_all_finished_ko_stage_returned(self):
        """A knockout stage whose every match is FINISHED appears in the result."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-07-02T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "ARG", "name": "Argentina"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert "LAST_16" in client.get_finished_stages()

    @resp_lib.activate
    def test_any_non_finished_match_excludes_stage(self):
        """A stage with at least one non-FINISHED match is NOT in the result."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-07-03T18:00:00Z",
                        "status": "SCHEDULED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "ARG", "name": "Argentina"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert "LAST_16" not in client.get_finished_stages()

    @resp_lib.activate
    def test_group_stage_matches_ignored(self):
        """GROUP_STAGE matches are not in KNOCKOUT_STAGES and must be ignored."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-06-15T18:00:00Z",
                        "status": "FINISHED", "stage": "GROUP_STAGE", "group": "GROUP_A",
                        "homeTeam": {"tla": "GER", "name": "Germany"},
                        "awayTeam": {"tla": "ESP", "name": "Spain"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    }
                ]
            },
            status=200,
        )
        client = _fresh_client()
        assert client.get_finished_stages() == set()

    @resp_lib.activate
    def test_only_finished_stage_in_mixed_scenario(self):
        """LAST_16 all FINISHED; QUARTER_FINALS has a SCHEDULED match → only LAST_16 returned."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-07-05T18:00:00Z",
                        "status": "SCHEDULED", "stage": "QUARTER_FINALS", "group": None,
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "GER", "name": "Germany"},
                        "score": {"fullTime": {"home": None, "away": None}, "winner": None},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        finished = client.get_finished_stages()
        assert finished == {"LAST_16"}

    @resp_lib.activate
    def test_multiple_finished_stages_all_returned(self):
        """Both LAST_16 and QUARTER_FINALS all FINISHED → both returned."""
        resp_lib.add(
            resp_lib.GET,
            WC_MATCHES,
            json={
                "matches": [
                    {
                        "id": 1, "utcDate": "2026-07-01T18:00:00Z",
                        "status": "FINISHED", "stage": "LAST_16", "group": None,
                        "homeTeam": {"tla": "ESP", "name": "Spain"},
                        "awayTeam": {"tla": "FRA", "name": "France"},
                        "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
                    },
                    {
                        "id": 2, "utcDate": "2026-07-05T18:00:00Z",
                        "status": "FINISHED", "stage": "QUARTER_FINALS", "group": None,
                        "homeTeam": {"tla": "BRA", "name": "Brazil"},
                        "awayTeam": {"tla": "GER", "name": "Germany"},
                        "score": {"fullTime": {"home": 1, "away": 0}, "winner": "HOME_TEAM"},
                    },
                ]
            },
            status=200,
        )
        client = _fresh_client()
        finished = client.get_finished_stages()
        assert "LAST_16" in finished
        assert "QUARTER_FINALS" in finished


# ══════════════════════════════════════════════════════════════════════════════
# Shared default cache
# ══════════════════════════════════════════════════════════════════════════════


class TestSharedDefaultCache:
    """Prove that the process-wide shared TTLCache singleton works correctly."""

    def test_get_default_cache_returns_same_instance_on_repeated_calls(self):
        """get_default_cache() must return the identical TTLCache object every time."""
        from worldcup_bot.api.cache import get_default_cache
        assert get_default_cache() is get_default_cache()

    def test_reset_default_cache_produces_new_instance(self):
        """After reset_default_cache(), get_default_cache() returns a fresh instance."""
        from worldcup_bot.api.cache import get_default_cache, reset_default_cache
        c_before = get_default_cache()
        reset_default_cache()
        c_after = get_default_cache()
        assert c_before is not c_after

    def test_reset_default_cache_entries_are_gone(self):
        """Entries written before reset are not visible after reset."""
        from worldcup_bot.api.cache import get_default_cache, reset_default_cache
        get_default_cache().set("url", {"data": 1})
        reset_default_cache()
        assert get_default_cache().get("url") is None

    @resp_lib.activate
    def test_two_clients_sharing_cache_make_one_http_request(self):
        """Two FootballDataClient instances sharing a TTLCache make only one HTTP call."""
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"standings": []}, status=200)
        shared = TTLCache(ttl=60)
        c1 = FootballDataClient(api_key="k", competition_code="WC", cache=shared)
        c2 = FootballDataClient(api_key="k", competition_code="WC", cache=shared)
        c1.get_standings()
        c2.get_standings()
        assert len(resp_lib.calls) == 1

    @resp_lib.activate
    def test_make_client_uses_shared_default_cache(self):
        """Two clients built via make_client share the singleton — only one HTTP call."""
        from worldcup_bot.api.cache import reset_default_cache
        from worldcup_bot.bot.handlers import make_client
        from worldcup_bot.config import Settings
        reset_default_cache()
        resp_lib.add(resp_lib.GET, WC_STANDINGS, json={"standings": []}, status=200)
        settings = Settings(telegram_bot_token="t", football_data_api_key="k")
        c1 = make_client(settings)
        c2 = make_client(settings)
        c1.get_standings()
        c2.get_standings()
        assert len(resp_lib.calls) == 1


# ══════════════════════════════════════════════════════════════════════════════
# FootballDataClient — get_football_day_matches (09:00→09:00 rolling window)
# ══════════════════════════════════════════════════════════════════════════════


class TestGetFootballDayMatches:
    """Tests for the rolling 24h football-day window.

    Europe/Madrid in summer = CEST = UTC+2.
    Offset shorthand: CEST = UTC+2 → e.g. 09:00 CEST = 07:00 UTC.
    """

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _match(utc_date: str, match_id: int = 1) -> "Match":
        from worldcup_bot.api.models import Match

        return Match(
            id=match_id,
            utc_date=utc_date,
            status="SCHEDULED",
            stage="GROUP_STAGE",
            group="GROUP_A",
            home_tla="GER",
            away_tla="ESP",
            home_name="Germany",
            away_name="Spain",
            home_score=None,
            away_score=None,
            winner=None,
        )

    @staticmethod
    def _fixed_now(year, month, day, hour, minute=0):
        """Return a CEST-aware datetime (Europe/Madrid, UTC+2 in summer)."""
        import pytz
        from datetime import datetime as real_dt

        tz = pytz.timezone("Europe/Madrid")
        return tz.localize(real_dt(year, month, day, hour, minute, 0))

    # ── core window tests (afternoon now, offset=0) ───────────────────────────

    def test_match_at_23h_local_included(self):
        """now=14:00 CEST Jun15; window=[07:00Z Jun15, 07:00Z Jun16).
        Match at 21:00Z (=23:00 CEST Jun15) is inside the window."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [self._match("2026-06-15T21:00:00Z", 1)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert len(result) == 1
        assert result[0].id == 1

    def test_match_at_02h_next_calendar_day_local_included(self):
        """now=14:00 CEST Jun15; match at 00:00Z Jun16 (=02:00 CEST Jun16) is inside window."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [self._match("2026-06-16T00:00:00Z", 2)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert len(result) == 1
        assert result[0].id == 2

    def test_match_before_anchor_excluded(self):
        """now=14:00 CEST Jun15; match at 06:30Z (=08:30 CEST Jun15) is before 07:00Z anchor → excluded."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [self._match("2026-06-15T06:30:00Z", 3)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert result == []

    def test_match_at_window_end_excluded(self):
        """now=14:00 CEST Jun15; match at 07:30Z Jun16 (=09:30 CEST Jun16) equals/exceeds end → excluded."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [self._match("2026-06-16T07:30:00Z", 4)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert result == []

    def test_window_includes_both_evening_and_early_morning_excludes_outside(self):
        """Comprehensive: 4 matches, 2 inside window, 2 outside."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [
            self._match("2026-06-15T21:00:00Z", 1),  # 23:00 CEST Jun15 → included
            self._match("2026-06-16T00:00:00Z", 2),  # 02:00 CEST Jun16 → included
            self._match("2026-06-15T06:30:00Z", 3),  # 08:30 CEST Jun15 → excluded
            self._match("2026-06-16T07:30:00Z", 4),  # 09:30 CEST Jun16 → excluded
        ]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        ids = [m.id for m in result]
        assert 1 in ids
        assert 2 in ids
        assert 3 not in ids
        assert 4 not in ids

    # ── rolling rule: now before anchor ───────────────────────────────────────

    def test_rolling_rule_now_before_anchor_uses_previous_day_start(self):
        """now=02:00 CEST Jun16 (before 09:00 anchor) → window started Jun15 09:00 CEST.
        A match at 23:00Z Jun15 (=Jun16 01:00 CEST) is inside the window."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 16, 2)
        # 23:00 UTC Jun15 = 01:00 CEST Jun16 — well within [Jun15 07:00Z, Jun16 07:00Z)
        matches = [self._match("2026-06-15T23:00:00Z", 10)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert len(result) == 1
        assert result[0].id == 10

    def test_rolling_rule_match_from_yesterday_morning_excluded(self):
        """now=02:00 CEST Jun16; match at 06:00Z Jun15 (=08:00 CEST Jun15) is before the window start."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 16, 2)
        matches = [self._match("2026-06-15T06:00:00Z", 11)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert result == []

    # ── day_offset=-1 (/ayer) ─────────────────────────────────────────────────

    def test_day_offset_minus1_returns_previous_block(self):
        """now=14:00 CEST Jun15, offset=-1 → window=[Jun14 07:00Z, Jun15 07:00Z).
        Match at 18:00Z Jun14 (=20:00 CEST Jun14) is included."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [self._match("2026-06-14T18:00:00Z", 20)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", -1, 9)

        assert len(result) == 1
        assert result[0].id == 20

    def test_day_offset_minus1_excludes_todays_matches(self):
        """offset=-1 must NOT return today's matches."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [
            self._match("2026-06-15T21:00:00Z", 30),  # today evening → outside ayer window
            self._match("2026-06-14T18:00:00Z", 31),  # yesterday → inside ayer window
        ]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", -1, 9)

        ids = [m.id for m in result]
        assert 30 not in ids
        assert 31 in ids

    # ── sorting ───────────────────────────────────────────────────────────────

    def test_results_sorted_ascending_by_kickoff(self):
        """Matches are returned in ascending UTC kickoff order."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        matches = [
            self._match("2026-06-15T21:00:00Z", 1),
            self._match("2026-06-15T19:00:00Z", 2),
            self._match("2026-06-15T17:00:00Z", 3),
        ]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert [m.id for m in result] == [3, 2, 1]

    # ── empty ─────────────────────────────────────────────────────────────────

    def test_empty_when_no_matches_in_range(self):
        """Returns [] when no matches fall in the window."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)
        # Only a match from a month ago
        matches = [self._match("2026-05-01T18:00:00Z", 99)]

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=matches):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert result == []

    def test_empty_when_no_matches_at_all(self):
        """Returns [] when the match list is empty."""
        from datetime import datetime as real_dt
        from unittest.mock import patch

        fixed_now = self._fixed_now(2026, 6, 15, 14)

        client = _fresh_client()
        with patch("worldcup_bot.api.client.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.strptime.side_effect = real_dt.strptime
            with patch.object(client, "get_all_matches", return_value=[]):
                result = client.get_football_day_matches("Europe/Madrid", 0, 9)

        assert result == []
