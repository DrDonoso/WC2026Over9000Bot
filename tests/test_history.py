"""Tests for porra/history.py — football_day_of, build_jornadas,
reconstruct_group_standings, compute_ranking_at_jornada, load/save, ensure_history."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest

from worldcup_bot.api.models import Match, Standing
from worldcup_bot.config import Settings
from worldcup_bot.data.stages import KNOCKOUT_STAGES
from worldcup_bot.porra.history import (
    build_jornadas,
    compute_ranking_at_jornada,
    ensure_history,
    football_day_of,
    load_history,
    reconstruct_group_standings,
    save_history,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_match(
    utc_date: str,
    status: str,
    stage: str = "GROUP_STAGE",
    group: str | None = "GROUP_A",
    home_tla: str = "GER",
    away_tla: str = "ESP",
    home_score: int | None = 1,
    away_score: int | None = 0,
    winner: str | None = "HOME_TEAM",
) -> Match:
    return Match(
        id=1,
        utc_date=utc_date,
        status=status,
        stage=stage,
        group=group,
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_tla,
        away_name=away_tla,
        home_score=home_score,
        away_score=away_score,
        winner=winner,
    )


def _fake_settings(tz: str = "Europe/Madrid") -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        timezone=tz,
        football_day_start_hour=9,
    )


def _ko_empty():
    return {api: [] for api, _, _ in KNOCKOUT_STAGES}


# ══════════════════════════════════════════════════════════════════════════════
# football_day_of
# ══════════════════════════════════════════════════════════════════════════════


class TestFootballDayOf:
    """Test the 9am→9am football-day windowing logic."""

    # Europe/Madrid is UTC+2 in summer (CEST).

    def test_hour_at_anchor_is_same_day(self):
        """Match at exactly anchor_hour local → belongs to that calendar date."""
        # 2026-06-13T07:00:00Z = 2026-06-13 09:00 CEST → hour=9 >= 9 → "2026-06-13"
        m = _make_match("2026-06-13T07:00:00Z", "FINISHED")
        assert football_day_of(m, "Europe/Madrid", 9) == "2026-06-13"

    def test_hour_above_anchor_is_same_day(self):
        """Match well after anchor → same calendar date."""
        # 2026-06-13T18:00:00Z = 2026-06-13 20:00 CEST → hour=20 >= 9 → "2026-06-13"
        m = _make_match("2026-06-13T18:00:00Z", "FINISHED")
        assert football_day_of(m, "Europe/Madrid", 9) == "2026-06-13"

    def test_hour_below_anchor_is_previous_day(self):
        """Match before anchor hour local → belongs to previous jornada."""
        # 2026-06-14T06:00:00Z = 2026-06-14 08:00 CEST → hour=8 < 9 → "2026-06-13"
        m = _make_match("2026-06-14T06:00:00Z", "FINISHED")
        assert football_day_of(m, "Europe/Madrid", 9) == "2026-06-13"

    def test_tz_conversion_us_eastern(self):
        """Check correct local-time conversion for US/Eastern (UTC-5 in June)."""
        # America/New_York is UTC-4 in summer (EDT).
        # 2026-06-13T10:00:00Z = 2026-06-13 06:00 EDT → hour=6 < 9 → "2026-06-12"
        m = _make_match("2026-06-13T10:00:00Z", "FINISHED")
        assert football_day_of(m, "America/New_York", 9) == "2026-06-12"

    def test_midnight_utc_early_morning_groups_into_previous_jornada(self):
        """A match at 00:30 local (UTC~22:30 prev day) belongs to previous jornada."""
        # 2026-06-14T22:30:00Z = 2026-06-15 00:30 CEST → hour=0 < 9 → "2026-06-14"
        m = _make_match("2026-06-14T22:30:00Z", "FINISHED")
        assert football_day_of(m, "Europe/Madrid", 9) == "2026-06-14"


# ══════════════════════════════════════════════════════════════════════════════
# build_jornadas
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildJornadas:
    def test_empty_list_returns_empty(self):
        assert build_jornadas([], "Europe/Madrid", 9) == []

    def test_no_finished_returns_empty(self):
        matches = [
            _make_match("2026-06-13T15:00:00Z", "SCHEDULED"),
            _make_match("2026-06-13T18:00:00Z", "TIMED"),
        ]
        assert build_jornadas(matches, "Europe/Madrid", 9) == []

    def test_single_finished_match(self):
        matches = [_make_match("2026-06-13T18:00:00Z", "FINISHED")]
        assert build_jornadas(matches, "Europe/Madrid", 9) == ["2026-06-13"]

    def test_multiple_matches_same_jornada_return_one_label(self):
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED"),
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
        ]
        assert build_jornadas(matches, "Europe/Madrid", 9) == ["2026-06-13"]

    def test_early_morning_match_groups_into_previous_day(self):
        """A match at 08:00 local (< 9am anchor) belongs to previous jornada."""
        # 2026-06-14T06:00:00Z = 2026-06-14 08:00 CEST → hour=8 < 9 → "2026-06-13"
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED"),  # → "2026-06-13"
            _make_match("2026-06-14T06:00:00Z", "FINISHED"),  # → "2026-06-13" too
        ]
        assert build_jornadas(matches, "Europe/Madrid", 9) == ["2026-06-13"]

    def test_sorted_distinct_jornadas(self):
        matches = [
            _make_match("2026-06-15T18:00:00Z", "FINISHED"),
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T15:00:00Z", "FINISHED"),
        ]
        assert build_jornadas(matches, "Europe/Madrid", 9) == [
            "2026-06-13",
            "2026-06-14",
            "2026-06-15",
        ]

    def test_mixed_status_only_finished_included(self):
        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "SCHEDULED"),
            _make_match("2026-06-15T18:00:00Z", "IN_PLAY"),
        ]
        assert build_jornadas(matches, "Europe/Madrid", 9) == ["2026-06-13"]


# ══════════════════════════════════════════════════════════════════════════════
# reconstruct_group_standings
# ══════════════════════════════════════════════════════════════════════════════


class TestReconstructGroupStandings:
    def test_empty_list_returns_empty(self):
        assert reconstruct_group_standings([]) == {}

    def test_single_win_home(self):
        """Home team wins 2-0 → home=3pts/+2/2gf, away=0pts/-2/0gf."""
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="GER", away_tla="ESP", home_score=2, away_score=0, winner="HOME_TEAM",
        )
        result = reconstruct_group_standings([m])
        assert result["GROUP_A"] == ["GER", "ESP"]

    def test_draw_gives_one_point_each(self):
        """A draw gives 1pt to each team; order by TLA when all other stats equal."""
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="BRA", away_tla="ARG", home_score=1, away_score=1, winner="DRAW",
        )
        result = reconstruct_group_standings([m])
        # Equal pts=1, gd=0, gf=1 → TLA asc → ARG before BRA
        assert result["GROUP_A"] == ["ARG", "BRA"]

    def test_points_ordering(self):
        """Team with more points should be ranked higher."""
        # GER beats ESP 2-0: GER=3pts, ESP=0pts
        # GER draws BRA 1-1: GER=4pts, BRA=1pt
        # ESP beats BRA 1-0: ESP=3pts, BRA=1pt
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="ESP", home_score=2, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-14T15:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="BRA", home_score=1, away_score=1, winner="DRAW"),
            _make_match("2026-06-15T15:00:00Z", "FINISHED",
                        home_tla="ESP", away_tla="BRA", home_score=1, away_score=0, winner="HOME_TEAM"),
        ]
        result = reconstruct_group_standings(matches)
        # GER=4pts, ESP=3pts, BRA=1pt
        assert result["GROUP_A"] == ["GER", "ESP", "BRA"]

    def test_gd_tiebreak(self):
        """When points equal, team with better GD ranked higher."""
        # A beats C 3-0: A=3pts, +3gd
        # B beats C 1-0: B=3pts, +1gd
        # A vs B: 0-0 draw → A=4pts/+3gd, B=4pts/+1gd
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED",
                        home_tla="AAA", away_tla="CCC", home_score=3, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-14T15:00:00Z", "FINISHED",
                        home_tla="BBB", away_tla="CCC", home_score=1, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-15T15:00:00Z", "FINISHED",
                        home_tla="AAA", away_tla="BBB", home_score=0, away_score=0, winner="DRAW"),
        ]
        result = reconstruct_group_standings(matches)
        assert result["GROUP_A"][0] == "AAA"  # better GD
        assert result["GROUP_A"][1] == "BBB"

    def test_gf_tiebreak(self):
        """When pts and GD equal, team with more GF ranked higher."""
        # A beats C 2-1 (+1gd, 2gf), B beats C 1-0 (+1gd, 1gf)
        # A vs B draw 1-1
        # A: 4pts, +1gd, 3gf ; B: 4pts, +1gd, 2gf
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED",
                        home_tla="AAA", away_tla="CCC", home_score=2, away_score=1, winner="HOME_TEAM"),
            _make_match("2026-06-14T15:00:00Z", "FINISHED",
                        home_tla="BBB", away_tla="CCC", home_score=1, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-15T15:00:00Z", "FINISHED",
                        home_tla="AAA", away_tla="BBB", home_score=1, away_score=1, winner="DRAW"),
        ]
        result = reconstruct_group_standings(matches)
        assert result["GROUP_A"][0] == "AAA"  # more GF

    def test_tla_alphabetical_tiebreak(self):
        """When pts, GD, GF all equal → TLA alphabetical order."""
        # Two teams draw 0-0 → equal everything
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="ZZZ", away_tla="AAA", home_score=0, away_score=0, winner="DRAW",
        )
        result = reconstruct_group_standings([m])
        assert result["GROUP_A"] == ["AAA", "ZZZ"]

    def test_multiple_groups(self):
        """Matches from different groups produce separate group entries."""
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED",
                        group="GROUP_A", home_tla="GER", away_tla="ESP",
                        home_score=1, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-13T18:00:00Z", "FINISHED",
                        group="GROUP_B", home_tla="FRA", away_tla="BRA",
                        home_score=2, away_score=1, winner="HOME_TEAM"),
        ]
        result = reconstruct_group_standings(matches)
        assert "GROUP_A" in result
        assert "GROUP_B" in result
        assert result["GROUP_A"][0] == "GER"
        assert result["GROUP_B"][0] == "FRA"

    def test_non_finished_matches_ignored(self):
        """SCHEDULED and IN_PLAY matches must not affect standings."""
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="ESP", home_score=1, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-14T15:00:00Z", "SCHEDULED",
                        home_tla="ESP", away_tla="GER", home_score=None, away_score=None, winner=None),
        ]
        result = reconstruct_group_standings(matches)
        # Only the first match counts
        assert result["GROUP_A"] == ["GER", "ESP"]


# ══════════════════════════════════════════════════════════════════════════════
# compute_ranking_at_jornada
# ══════════════════════════════════════════════════════════════════════════════

_SIMPLE_PREDICTIONS = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {"A": ["GER", "ESP", "BRA"]},
            "knockout": {k: [] for k, _, _ in KNOCKOUT_STAGES},
        }
    }
}


class TestComputeRankingAtJornada:
    def test_returns_entry_for_each_participant(self):
        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="ESP", home_score=1, away_score=0, winner="HOME_TEAM"),
        ]
        rows = compute_ranking_at_jornada(
            _SIMPLE_PREDICTIONS, matches, "2026-06-13", "Europe/Madrid", 9
        )
        assert len(rows) == 1
        assert rows[0].username == "alice"

    def test_later_matches_excluded_from_cutoff(self):
        """Matches after the jornada date must NOT affect the ranking."""
        # All on the same football-day "2026-06-13", scores make GER top
        matches_jornada_13 = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="ESP", home_score=3, away_score=0, winner="HOME_TEAM"),
        ]
        rows_13 = compute_ranking_at_jornada(
            _SIMPLE_PREDICTIONS, matches_jornada_13, "2026-06-13", "Europe/Madrid", 9
        )
        # Alice predicted GER top → should score
        assert rows_13[0].group_score > 0

        # Add a future match that changes GROUP_A order
        matches_future = matches_jornada_13 + [
            _make_match("2026-06-14T18:00:00Z", "FINISHED",
                        home_tla="ESP", away_tla="GER", home_score=5, away_score=0, winner="HOME_TEAM"),
        ]
        rows_13_with_future = compute_ranking_at_jornada(
            _SIMPLE_PREDICTIONS, matches_future, "2026-06-13", "Europe/Madrid", 9
        )
        # Same score as without future match — cutoff stops at 2026-06-13
        assert rows_13_with_future[0].group_score == rows_13[0].group_score

    def test_knockout_winners_included_in_ranking(self):
        """Finished knockout matches within cutoff contribute their winner."""
        from worldcup_bot.data.stages import STAGE_YAML_KEYS

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
        matches = [
            _make_match(
                "2026-07-19T18:00:00Z", "FINISHED",
                stage="FINAL", group=None,
                home_tla="ESP", away_tla="FRA",
                home_score=1, away_score=0, winner="HOME_TEAM",
            ),
        ]
        rows = compute_ranking_at_jornada(
            preds, matches, "2026-07-19", "Europe/Madrid", 9
        )
        assert rows[0].total_score == 5.0  # FINAL = 5 pts

    def test_no_api_calls_needed(self):
        """compute_ranking_at_jornada must not call any client — it takes plain matches."""
        # Just verify it runs without a client argument (only predictions + match list)
        rows = compute_ranking_at_jornada(
            _SIMPLE_PREDICTIONS, [], "2026-06-13", "Europe/Madrid", 9
        )
        assert isinstance(rows, list)


# ══════════════════════════════════════════════════════════════════════════════
# load_history / save_history
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadSaveHistory:
    def test_load_missing_file_returns_empty(self):
        assert load_history("nonexistent_path_xyz.json") == {}

    def test_save_then_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "history.json")
        data = {
            "2026-06-13": {"alice": {"pos": 1, "pts": 3.0, "name": "Alice"}},
            "2026-06-14": {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}},
        }
        save_history(path, data)
        loaded = load_history(path)
        assert loaded == data

    def test_save_creates_file(self, tmp_path):
        path = str(tmp_path / "history.json")
        save_history(path, {"2026-06-13": {}})
        assert os.path.exists(path)

    def test_load_invalid_json_returns_empty(self, tmp_path):
        path = str(tmp_path / "broken.json")
        with open(path, "w") as f:
            f.write("not json !!!")
        result = load_history(path)
        assert result == {}

    def test_save_invalid_path_does_not_raise(self):
        """save_history to an invalid path must not raise."""
        save_history("/no/such/dir/history.json", {"x": 1})  # best-effort


# ══════════════════════════════════════════════════════════════════════════════
# ensure_history
# ══════════════════════════════════════════════════════════════════════════════


def _make_ranking_entry(username: str, display_name: str, total: float) -> MagicMock:
    e = MagicMock()
    e.username = username
    e.display_name = display_name
    e.total_score = total
    return e


class TestEnsureHistory:
    def _make_client(self, matches: list[Match]) -> MagicMock:
        client = MagicMock()
        client.get_all_matches.return_value = matches
        client.get_standings.return_value = []  # used by sanity check only
        return client

    def test_no_finished_matches_returns_empty(self, tmp_path):
        path = str(tmp_path / "h.json")
        settings = _fake_settings()
        client = self._make_client([_make_match("2026-06-13T18:00:00Z", "SCHEDULED")])
        result = ensure_history(client, {"participants": {}}, settings, path)
        assert result == {}

    def test_computes_missing_jornada(self, tmp_path):
        path = str(tmp_path / "h.json")
        settings = _fake_settings()
        matches = [_make_match("2026-06-13T18:00:00Z", "FINISHED")]
        client = self._make_client(matches)

        rank_entry = _make_ranking_entry("alice", "Alice", 3.0)
        with pytest.MonkeyPatch().context() as mp:
            # 2026-06-13 is the only (hence latest) jornada → must use live ranking
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [rank_entry],
            )
            result = ensure_history(client, {"participants": {}}, settings, path)

        assert "2026-06-13" in result
        assert "alice" in result["2026-06-13"]
        assert result["2026-06-13"]["alice"]["pos"] == 1
        assert result["2026-06-13"]["alice"]["pts"] == 3.0

    def test_already_stored_jornada_not_recomputed(self, tmp_path):
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        # Pre-fill history with 2026-06-13
        pre_data = {"2026-06-13": {"alice": {"pos": 1, "pts": 2.0, "name": "Alice"}}}
        save_history(path, pre_data)

        # Two finished matches: 2026-06-13 (already stored), 2026-06-14 (latest)
        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),
        ]
        client = self._make_client(matches)
        reconstruct_call_log: list[str] = []
        live_call_count: list[int] = [0]

        def fake_reconstruct(preds, mlist, jornada, tz, ah):
            reconstruct_call_log.append(jornada)
            return [_make_ranking_entry("alice", "Alice", 4.0)]

        def fake_live(preds, cli, official=False):
            live_call_count[0] += 1
            return [_make_ranking_entry("alice", "Alice", 4.0)]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("worldcup_bot.porra.history.compute_ranking_at_jornada", fake_reconstruct)
            mp.setattr("worldcup_bot.porra.engine.compute_general_ranking", fake_live)
            ensure_history(client, {"participants": {}}, settings, path)

        # 2026-06-13 was stored and is NOT the latest → never touched
        assert "2026-06-13" not in reconstruct_call_log
        # Latest (2026-06-14) uses live ranking, NOT reconstruction
        assert "2026-06-14" not in reconstruct_call_log
        assert live_call_count[0] == 1

    def test_latest_jornada_always_refreshed(self, tmp_path):
        """The most recent jornada is always re-computed with the exact live ranking."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        pre_data = {
            "2026-06-13": {"alice": {"pos": 1, "pts": 2.0, "name": "Alice"}},
            "2026-06-14": {"alice": {"pos": 1, "pts": 3.0, "name": "Alice"}},
        }
        save_history(path, pre_data)

        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),
        ]
        client = self._make_client(matches)

        # Live ranking returns updated pts=5.0 for alice
        live_entry = _make_ranking_entry("alice", "Alice", 5.0)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [live_entry],
            )
            result = ensure_history(client, {"participants": {}}, settings, path)

        # Latest date (2026-06-14) must be re-computed using live ranking
        assert result["2026-06-14"]["alice"]["pts"] == 5.0

    def test_api_error_returns_existing_history(self, tmp_path):
        path = str(tmp_path / "h.json")
        settings = _fake_settings()
        pre_data = {"2026-06-13": {"alice": {"pos": 1, "pts": 2.0, "name": "Alice"}}}
        save_history(path, pre_data)

        client = MagicMock()
        client.get_all_matches.side_effect = Exception("API down")

        result = ensure_history(client, {"participants": {}}, settings, path)
        assert result == pre_data

    def test_result_is_persisted_to_file(self, tmp_path):
        path = str(tmp_path / "h.json")
        settings = _fake_settings()
        matches = [_make_match("2026-06-13T18:00:00Z", "FINISHED")]
        client = self._make_client(matches)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [
                    _make_ranking_entry("alice", "Alice", 3.0)
                ],
            )
            ensure_history(client, {"participants": {}}, settings, path)

        loaded = load_history(path)
        assert "2026-06-13" in loaded

    def test_get_standings_not_called_from_ensure_history(self, tmp_path):
        """ensure_history must NOT call client.get_standings() directly.
        The latest jornada uses engine.compute_general_ranking (mocked here);
        since we mock it directly, no standings call is made from that path.
        """
        path = str(tmp_path / "h.json")
        settings = _fake_settings()
        matches = [_make_match("2026-06-13T18:00:00Z", "FINISHED")]
        client = self._make_client(matches)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [
                    _make_ranking_entry("alice", "Alice", 3.0)
                ],
            )
            ensure_history(client, {"participants": {}}, settings, path)

        client.get_standings.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# ensure_history — latest jornada uses exact live ranking
# ══════════════════════════════════════════════════════════════════════════════


class TestEnsureHistoryLatestUsesLiveRanking:
    """Latest jornada must use compute_general_ranking; past ones use reconstruction."""

    def _make_client(self, matches):
        client = MagicMock()
        client.get_all_matches.return_value = matches
        return client

    def test_latest_jornada_uses_live_ranking_not_reconstruction(self, tmp_path):
        """For multi-jornada history, the latest uses live ranking; past uses reconstruction."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),  # past jornada
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),  # latest jornada
        ]
        client = self._make_client(matches)
        reconstruct_calls: list[str] = []
        live_calls: list[int] = [0]

        def fake_reconstruct(preds, mlist, jornada, tz, ah):
            reconstruct_calls.append(jornada)
            return [_make_ranking_entry("alice", "Alice", 2.0)]

        def fake_live(preds, cli, official=False):
            live_calls[0] += 1
            return [_make_ranking_entry("alice", "Alice", 5.0)]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("worldcup_bot.porra.history.compute_ranking_at_jornada", fake_reconstruct)
            mp.setattr("worldcup_bot.porra.engine.compute_general_ranking", fake_live)
            result = ensure_history(client, {"participants": {}}, settings, path)

        # Past jornada uses reconstruction
        assert "2026-06-13" in reconstruct_calls
        assert result["2026-06-13"]["alice"]["pts"] == 2.0
        # Latest uses live ranking, not reconstruction
        assert "2026-06-14" not in reconstruct_calls
        assert live_calls[0] == 1
        assert result["2026-06-14"]["alice"]["pts"] == 5.0

    def test_live_ranking_entry_equals_latest_history_entry(self, tmp_path):
        """Entry stored for latest jornada is exactly what compute_general_ranking returns."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        matches = [_make_match("2026-06-17T18:00:00Z", "FINISHED")]
        client = self._make_client(matches)

        live_rank = [
            _make_ranking_entry("alice", "Alice", 7.5),
            _make_ranking_entry("bob", "Bob", 4.0),
        ]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: live_rank,
            )
            result = ensure_history(client, {"participants": {}}, settings, path)

        jornada = "2026-06-17"
        assert result[jornada]["alice"]["pos"] == 1
        assert result[jornada]["alice"]["pts"] == 7.5
        assert result[jornada]["bob"]["pos"] == 2
        assert result[jornada]["bob"]["pts"] == 4.0

    def test_past_already_stored_not_recomputed_with_live_or_reconstruct(self, tmp_path):
        """A past stored jornada triggers neither reconstruction nor live ranking."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        # Pre-store both jornadas; 06-14 is latest
        pre = {
            "2026-06-13": {"alice": {"pos": 1, "pts": 1.0, "name": "Alice"}},
        }
        save_history(path, pre)

        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),
        ]
        client = self._make_client(matches)
        reconstruct_calls: list[str] = []

        def fake_reconstruct(preds, mlist, jornada, tz, ah):
            reconstruct_calls.append(jornada)
            return [_make_ranking_entry("alice", "Alice", 99.0)]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("worldcup_bot.porra.history.compute_ranking_at_jornada", fake_reconstruct)
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [_make_ranking_entry("alice", "Alice", 3.0)],
            )
            result = ensure_history(client, {"participants": {}}, settings, path)

        # 06-13 stored and not latest → never reconstructed or live-computed
        assert "2026-06-13" not in reconstruct_calls
        # Original stored value preserved
        assert result["2026-06-13"]["alice"]["pts"] == 1.0
        # 06-14 is latest → live ranking used
        assert result["2026-06-14"]["alice"]["pts"] == 3.0


# ══════════════════════════════════════════════════════════════════════════════
# ensure_history — force=True recomputes all jornadas from scratch
# ══════════════════════════════════════════════════════════════════════════════


class TestEnsureHistoryForce:
    """ensure_history(force=True) discards the cache and recomputes every jornada."""

    def _make_client(self, matches: list) -> MagicMock:
        client = MagicMock()
        client.get_all_matches.return_value = matches
        return client

    def test_force_true_ignores_cached_past_jornadas(self, tmp_path):
        """With force=True, stale cached points for past jornadas are overwritten."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        # Pre-fill with stale data (old incorrect points)
        stale = {
            "2026-06-13": {"alice": {"pos": 1, "pts": 2.0, "name": "Alice"}},
        }
        save_history(path, stale)

        # Two matches: 06-13 (past), 06-14 (latest)
        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),
        ]
        client = self._make_client(matches)
        reconstruct_calls: list[str] = []

        def fake_reconstruct(preds, mlist, jornada, tz, ah):
            reconstruct_calls.append(jornada)
            return [_make_ranking_entry("alice", "Alice", 9.0)]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("worldcup_bot.porra.history.compute_ranking_at_jornada", fake_reconstruct)
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [_make_ranking_entry("alice", "Alice", 10.0)],
            )
            result = ensure_history(client, {"participants": {}}, settings, path, force=True)

        # Past jornada must have been recomputed (stale 2.0 replaced with 9.0)
        assert "2026-06-13" in reconstruct_calls
        assert result["2026-06-13"]["alice"]["pts"] == 9.0
        # Latest uses live ranking
        assert result["2026-06-14"]["alice"]["pts"] == 10.0

    def test_force_false_preserves_cached_past_jornadas(self, tmp_path):
        """With force=False (default), cached past jornadas are NOT recomputed."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        stale = {
            "2026-06-13": {"alice": {"pos": 1, "pts": 2.0, "name": "Alice"}},
        }
        save_history(path, stale)

        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),
        ]
        client = self._make_client(matches)
        reconstruct_calls: list[str] = []

        def fake_reconstruct(preds, mlist, jornada, tz, ah):
            reconstruct_calls.append(jornada)
            return [_make_ranking_entry("alice", "Alice", 99.0)]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("worldcup_bot.porra.history.compute_ranking_at_jornada", fake_reconstruct)
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [_make_ranking_entry("alice", "Alice", 3.0)],
            )
            result = ensure_history(client, {"participants": {}}, settings, path, force=False)

        # Past jornada (06-13) cached → NOT recomputed
        assert "2026-06-13" not in reconstruct_calls
        assert result["2026-06-13"]["alice"]["pts"] == 2.0  # original stale value preserved
        # Latest always refreshed
        assert result["2026-06-14"]["alice"]["pts"] == 3.0

    def test_force_true_empty_history_when_no_existing_file(self, tmp_path):
        """force=True starts from {} even when the file does not exist."""
        path = str(tmp_path / "nonexistent.json")
        settings = _fake_settings()
        matches = [_make_match("2026-06-13T18:00:00Z", "FINISHED")]
        client = self._make_client(matches)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [_make_ranking_entry("alice", "Alice", 5.0)],
            )
            result = ensure_history(client, {"participants": {}}, settings, path, force=True)

        assert "2026-06-13" in result
        assert result["2026-06-13"]["alice"]["pts"] == 5.0

    def test_force_true_rewrites_all_jornadas(self, tmp_path):
        """force=True recomputes every jornada; the result count matches the match days."""
        path = str(tmp_path / "h.json")
        settings = _fake_settings()

        # Pre-fill with stale pts
        save_history(path, {
            "2026-06-13": {"alice": {"pos": 1, "pts": 0.5, "name": "Alice"}},
            "2026-06-14": {"alice": {"pos": 1, "pts": 1.0, "name": "Alice"}},
        })

        matches = [
            _make_match("2026-06-13T18:00:00Z", "FINISHED"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED"),
        ]
        client = self._make_client(matches)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "worldcup_bot.porra.history.compute_ranking_at_jornada",
                lambda preds, mlist, jornada, tz, ah: [_make_ranking_entry("alice", "Alice", 7.0)],
            )
            mp.setattr(
                "worldcup_bot.porra.engine.compute_general_ranking",
                lambda preds, cli, official=False: [_make_ranking_entry("alice", "Alice", 8.0)],
            )
            result = ensure_history(client, {"participants": {}}, settings, path, force=True)

        # Both jornadas recomputed; old stale values gone
        assert result["2026-06-13"]["alice"]["pts"] == 7.0
        assert result["2026-06-14"]["alice"]["pts"] == 8.0  # latest uses live


# ==============================================================================
# reconstruct_full_group_standings
# ==============================================================================

from worldcup_bot.porra.history import reconstruct_full_group_standings  # noqa: E402


class TestReconstructFullGroupStandings:
    def test_returns_dicts_with_required_keys(self):
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="GER", away_tla="ESP", home_score=2, away_score=1, winner="HOME_TEAM",
        )
        result = reconstruct_full_group_standings([m])
        entries = result["GROUP_A"]
        assert len(entries) == 2
        for e in entries:
            assert {"tla", "points", "goal_difference", "goals_for"} <= e.keys()

    def test_winner_has_3_points(self):
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="GER", away_tla="ESP", home_score=2, away_score=0, winner="HOME_TEAM",
        )
        result = reconstruct_full_group_standings([m])
        ger = result["GROUP_A"][0]
        assert ger["tla"] == "GER"
        assert ger["points"] == 3
        assert ger["goal_difference"] == 2
        assert ger["goals_for"] == 2

    def test_loser_has_0_points_negative_gd(self):
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="GER", away_tla="ESP", home_score=2, away_score=0, winner="HOME_TEAM",
        )
        result = reconstruct_full_group_standings([m])
        esp = result["GROUP_A"][1]
        assert esp["tla"] == "ESP"
        assert esp["points"] == 0
        assert esp["goal_difference"] == -2
        assert esp["goals_for"] == 0

    def test_draw_each_team_gets_1_point(self):
        m = _make_match(
            "2026-06-13T18:00:00Z", "FINISHED",
            home_tla="GER", away_tla="ESP", home_score=1, away_score=1, winner="DRAW",
        )
        result = reconstruct_full_group_standings([m])
        for e in result["GROUP_A"]:
            assert e["points"] == 1
            assert e["goal_difference"] == 0
            assert e["goals_for"] == 1

    def test_order_matches_reconstruct_group_standings(self):
        """The TLA order in full standings must equal the TLA order in plain standings."""
        matches = [
            _make_match("2026-06-13T15:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="ESP", home_score=3, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-13T18:00:00Z", "FINISHED",
                        home_tla="BRA", away_tla="USA", home_score=2, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-14T15:00:00Z", "FINISHED",
                        home_tla="GER", away_tla="BRA", home_score=1, away_score=0, winner="HOME_TEAM"),
            _make_match("2026-06-14T18:00:00Z", "FINISHED",
                        home_tla="ESP", away_tla="USA", home_score=1, away_score=0, winner="HOME_TEAM"),
        ]
        plain = reconstruct_group_standings(matches)
        full = reconstruct_full_group_standings(matches)
        assert plain["GROUP_A"] == [e["tla"] for e in full["GROUP_A"]]

    def test_empty_matches_returns_empty(self):
        assert reconstruct_full_group_standings([]) == {}


# ==============================================================================
# compute_ranking_at_jornada — qualifying thirds integration
# ==============================================================================


def _build_group_matches(
    group: str, first: str, second: str, third: str, utc_date: str
) -> list[Match]:
    """Three matches giving first 6pts, second 3pts, third 0pts."""
    return [
        _make_match(utc_date, "FINISHED", group=group, home_tla=first, away_tla=second,
                    home_score=2, away_score=0, winner="HOME_TEAM"),
        _make_match(utc_date, "FINISHED", group=group, home_tla=first, away_tla=third,
                    home_score=2, away_score=0, winner="HOME_TEAM"),
        _make_match(utc_date, "FINISHED", group=group, home_tla=second, away_tla=third,
                    home_score=1, away_score=0, winner="HOME_TEAM"),
    ]


def _build_group_matches_draw_third(
    group: str, first: str, second: str, third: str, utc_date: str
) -> list[Match]:
    """Three matches giving third 1pt via a draw (so third ranks above 0-pt teams)."""
    return [
        _make_match(utc_date, "FINISHED", group=group, home_tla=first, away_tla=second,
                    home_score=2, away_score=0, winner="HOME_TEAM"),
        _make_match(utc_date, "FINISHED", group=group, home_tla=first, away_tla=third,
                    home_score=2, away_score=0, winner="HOME_TEAM"),
        _make_match(utc_date, "FINISHED", group=group, home_tla=second, away_tla=third,
                    home_score=1, away_score=1, winner="DRAW"),
    ]


_PREDICTIONS_ALICE_GROUP_A = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {"A": ["ESP", "GER", "BRA"]},  # exact pred: ESP 1st, GER 2nd, BRA 3rd
            "knockout": {k: [] for k, _, _ in KNOCKOUT_STAGES},
        }
    }
}


class TestComputeRankingAtJornadaQualifyingThirds:
    """Verify that qualifying thirds are propagated through the history path."""

    def test_provisional_third_qualifies_when_fewer_than_8_groups(self):
        """With only 1 group (< 8 thirds), all thirds qualify provisionally -> BRA scores 1.0."""
        date = "2026-06-14T12:00:00Z"
        matches = _build_group_matches("GROUP_A", "ESP", "GER", "BRA", date)
        rows = compute_ranking_at_jornada(
            _PREDICTIONS_ALICE_GROUP_A, matches, "2026-06-14", "Europe/Madrid", 9
        )
        alice = rows[0]
        # ESP exact 1st (+1.0), GER exact 2nd (+1.0), BRA exact 3rd -> qualifies provisionally (+1.0)
        assert alice.group_score == pytest.approx(3.0)

    def test_non_qualifying_3rd_scores_zero_in_history_path(self):
        """With 9 groups: BRA (0pts) is 9th third and does NOT qualify -> scores 0 not 1."""
        date = "2026-06-14T12:00:00Z"
        jornada = "2026-06-14"

        # GROUP_A: ESP wins all, GER beats BRA, BRA loses all -> BRA=0pts (worst third)
        matches = _build_group_matches("GROUP_A", "ESP", "GER", "BRA", date)

        # GROUP_B to GROUP_I: each 3rd gets 1pt via a draw (better than BRA's 0pts)
        for letter in "BCDEFGHI":
            matches += _build_group_matches_draw_third(
                f"GROUP_{letter}",
                f"{letter}1", f"{letter}2", f"{letter}3",
                date,
            )

        # 9 thirds total: BRA(0pts) ranks 9th; the 8 with 1pt qualify
        rows = compute_ranking_at_jornada(
            _PREDICTIONS_ALICE_GROUP_A, matches, jornada, "Europe/Madrid", 9
        )
        alice = rows[0]
        # ESP exact 1st (+1.0), GER exact 2nd (+1.0), BRA exact 3rd NOT qualifying (+0.0)
        assert alice.group_score == pytest.approx(2.0)

    def test_qualifying_3rd_scores_one_in_history_path(self):
        """When BRA ranks in the top 8 thirds, exact 3rd prediction scores 1.0."""
        date = "2026-06-14T12:00:00Z"
        jornada = "2026-06-14"

        # GROUP_A: ESP 4pts (W+D), GER 3pts (W), BRA 1pt (D) -> BRA is 3rd with 1pt.
        # This gives BRA 1pt, better than all other groups' thirds (0pts).
        matches = [
            _make_match(date, "FINISHED", group="GROUP_A",
                        home_tla="ESP", away_tla="GER", home_score=2, away_score=0, winner="HOME_TEAM"),
            _make_match(date, "FINISHED", group="GROUP_A",
                        home_tla="GER", away_tla="BRA", home_score=1, away_score=0, winner="HOME_TEAM"),
            _make_match(date, "FINISHED", group="GROUP_A",
                        home_tla="ESP", away_tla="BRA", home_score=0, away_score=0, winner="DRAW"),
        ]
        # Groups B-I: each 3rd gets 0pts -> BRA (1pt) outranks all 8 other thirds
        for letter in "BCDEFGHI":
            matches += _build_group_matches(
                f"GROUP_{letter}", f"{letter}1", f"{letter}2", f"{letter}3", date
            )

        rows = compute_ranking_at_jornada(
            _PREDICTIONS_ALICE_GROUP_A, matches, jornada, "Europe/Madrid", 9
        )
        alice = rows[0]
        # ESP exact 1st (+1.0), GER exact 2nd (+1.0), BRA exact 3rd qualifies (+1.0)
        assert alice.group_score == pytest.approx(3.0)

