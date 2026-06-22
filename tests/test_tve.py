"""Tests for worldcup_bot.tve — RTVE schedule integration.

All network calls are mocked; no real HTTP in any test.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from worldcup_bot.tve import (
    ES_NAME_TO_TLA,
    TveBroadcast,
    _norm,
    fetch_rtve_schedule,
    load_tve_broadcasts,
    parse_wc_broadcasts,
    tve_channel_for,
)
from worldcup_bot.api.models import Match

_UTC = timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_match(
    home_tla: str,
    away_tla: str,
    utc_date: str = "2026-06-22T17:00:00Z",
    status: str = "SCHEDULED",
) -> Match:
    return Match(
        id=1,
        utc_date=utc_date,
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_tla,
        away_name=away_tla,
        home_score=None,
        away_score=None,
        winner=None,
    )


def _bcast(
    kickoff_utc: datetime,
    home_tla: str | None,
    away_tla: str | None,
    channel: str = "La 1",
) -> TveBroadcast:
    return TveBroadcast(kickoff_utc=kickoff_utc, home_tla=home_tla, away_tla=away_tla, channel=channel)


def _dt(utc_str: str) -> datetime:
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)


# ── RTVE sample items ─────────────────────────────────────────────────────────

_ITEM_LA1_ARG_AUT = {
    "name": "COPA DEL MUNDO FIFA 2026 ",
    "description": "Incluye:Nº12 Previo\r(19:00) ARGENTINA / AUSTRIA\rNº12 Post\r",
    "begintime": "20260622184500",
    "duration": "007800",
    "original_episode_name": "Futbol Copa Mundo Fifa Argentina - Austria",
    "idPrograma": 1030562,
}

_ITEM_LA1_ESP_KSA = {
    "original_episode_name": "Futbol Copa Mundo Fifa España - Arabia Saudi",
    "description": "Incluye:(18:00) ESPAÑA / ARABIA SAUDI",
    "begintime": "20260621174500",
    "idPrograma": 1030562,
}

_ITEM_DEP_GER_CUW = {
    "name": "FUTBOL COPA MUNDO FIFA ALEMANIA - CURAZA",
    "original_event_name": "Futbol Copa Mundo Fifa Alemania - Curazao",
    "description": "FUTBOL COPA DEL MUNDO FIFA 2026",
    "begintime": "20260615080000",
    "idPrograma": 1030562,
}

_ITEM_RESUMEN = {
    "name": "FUTBOL COPA MUNDIAL SUECIA - TUNEZ RESUM",
    "original_event_name": "Futbol Copa Mundial Suecia - Tunez Resumen",
    "begintime": "20260615120000",
    "idPrograma": 1030562,
}

_ITEM_NON_WC = {
    "name": "BALONCESTO NBA",
    "original_episode_name": "Lakers vs Warriors",
    "begintime": "20260622200000",
    "idPrograma": 9999999,
}

_ITEM_UNPARSEABLE_TEAMS = {
    "name": "COPA DEL MUNDO FIFA 2026",
    "description": "(21:00) Partido sin equipos reconocidos",
    "begintime": "20260622190000",
    "original_episode_name": "Futbol Copa Mundo Fifa MarcianoCFC - GalaxiaFC",
    "idPrograma": 1030562,
}


# ══════════════════════════════════════════════════════════════════════════════
# parse_wc_broadcasts
# ══════════════════════════════════════════════════════════════════════════════


class TestParseWcBroadcasts:
    """parse_wc_broadcasts correctly filters and parses WC items."""

    def test_la1_argentina_austria_tlas(self):
        result = parse_wc_broadcasts({"items": [_ITEM_LA1_ARG_AUT]}, "La 1")
        assert len(result) == 1
        b = result[0]
        assert b.home_tla == "ARG"
        assert b.away_tla == "AUT"
        assert b.channel == "La 1"

    def test_la1_argentina_austria_kickoff_utc(self):
        """La 1 description says (19:00) Madrid = 17:00 UTC (CEST = +2)."""
        result = parse_wc_broadcasts({"items": [_ITEM_LA1_ARG_AUT]}, "La 1")
        b = result[0]
        assert b.kickoff_utc == datetime(2026, 6, 22, 17, 0, tzinfo=_UTC)

    def test_la1_espana_arabia_saudi(self):
        result = parse_wc_broadcasts({"items": [_ITEM_LA1_ESP_KSA]}, "La 1")
        assert len(result) == 1
        b = result[0]
        assert b.home_tla == "ESP"
        assert b.away_tla == "KSA"

    def test_la1_espana_arabia_saudi_kickoff_utc(self):
        """La 1 description (18:00) Madrid = 16:00 UTC."""
        result = parse_wc_broadcasts({"items": [_ITEM_LA1_ESP_KSA]}, "La 1")
        b = result[0]
        assert b.kickoff_utc == datetime(2026, 6, 21, 16, 0, tzinfo=_UTC)

    def test_teledeporte_alemania_curazao_tlas(self):
        result = parse_wc_broadcasts({"items": [_ITEM_DEP_GER_CUW]}, "Teledeporte")
        assert len(result) == 1
        b = result[0]
        assert b.home_tla == "GER"
        assert b.away_tla == "CUW"
        assert b.channel == "Teledeporte"

    def test_teledeporte_alemania_curazao_kickoff_utc(self):
        """Teledeporte begintime 08:00 Madrid = 06:00 UTC."""
        result = parse_wc_broadcasts({"items": [_ITEM_DEP_GER_CUW]}, "Teledeporte")
        b = result[0]
        assert b.kickoff_utc == datetime(2026, 6, 15, 6, 0, tzinfo=_UTC)

    def test_resumen_item_excluded(self):
        result = parse_wc_broadcasts({"items": [_ITEM_RESUMEN]}, "Teledeporte")
        assert result == []

    def test_non_wc_programa_excluded(self):
        result = parse_wc_broadcasts({"items": [_ITEM_NON_WC]}, "La 1")
        assert result == []

    def test_unparseable_teams_skipped_gracefully(self):
        """When teams can't be mapped to TLAs the item is still included (TLAs=None)."""
        result = parse_wc_broadcasts({"items": [_ITEM_UNPARSEABLE_TEAMS]}, "La 1")
        # Item has a valid kickoff and idPrograma — it's kept but with None TLAs
        assert len(result) == 1
        assert result[0].home_tla is None
        assert result[0].away_tla is None

    def test_multiple_items_filtered_correctly(self):
        items = [
            _ITEM_LA1_ARG_AUT,
            _ITEM_RESUMEN,
            _ITEM_NON_WC,
            _ITEM_LA1_ESP_KSA,
        ]
        result = parse_wc_broadcasts({"items": items}, "La 1")
        assert len(result) == 2

    def test_empty_items_returns_empty(self):
        result = parse_wc_broadcasts({"items": []}, "La 1")
        assert result == []

    def test_missing_items_key_returns_empty(self):
        result = parse_wc_broadcasts({}, "La 1")
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# ES_NAME_TO_TLA: accent and case-insensitive lookup
# ══════════════════════════════════════════════════════════════════════════════


class TestEsNameToTla:
    """ES_NAME_TO_TLA lookup is accent-stripped and case-insensitive via _norm."""

    def test_tunez_with_accent(self):
        assert ES_NAME_TO_TLA.get(_norm("Túnez")) == "TUN"

    def test_tunez_without_accent(self):
        assert ES_NAME_TO_TLA.get(_norm("Tunez")) == "TUN"

    def test_tunez_uppercase(self):
        assert ES_NAME_TO_TLA.get(_norm("TUNEZ")) == "TUN"

    def test_espana_with_accent(self):
        assert ES_NAME_TO_TLA.get(_norm("España")) == "ESP"

    def test_espana_without_accent(self):
        assert ES_NAME_TO_TLA.get(_norm("Espana")) == "ESP"

    def test_arabia_saudi_no_accent(self):
        assert ES_NAME_TO_TLA.get(_norm("Arabia Saudi")) == "KSA"

    def test_curazao_variant(self):
        assert ES_NAME_TO_TLA.get(_norm("Curazao")) == "CUW"

    def test_curacao_variant(self):
        assert ES_NAME_TO_TLA.get(_norm("Curacao")) == "CUW"

    def test_alemania(self):
        assert ES_NAME_TO_TLA.get(_norm("Alemania")) == "GER"

    def test_argentina(self):
        assert ES_NAME_TO_TLA.get(_norm("Argentina")) == "ARG"

    def test_austria(self):
        assert ES_NAME_TO_TLA.get(_norm("Austria")) == "AUT"

    def test_unknown_returns_none(self):
        assert ES_NAME_TO_TLA.get(_norm("Wonderland FC")) is None


# ══════════════════════════════════════════════════════════════════════════════
# DST-correct Madrid → UTC conversion
# ══════════════════════════════════════════════════════════════════════════════


class TestMadridUtcDstCorrect:
    """June is CEST (UTC+2). Kickoff times must shift by exactly 2 hours."""

    def test_june_offset_is_2_hours(self):
        """Argentina vs Austria: 19:00 Madrid (CEST) = 17:00 UTC."""
        result = parse_wc_broadcasts({"items": [_ITEM_LA1_ARG_AUT]}, "La 1")
        b = result[0]
        # Madrid 19:00 on 2026-06-22 → UTC 17:00
        assert b.kickoff_utc.hour == 17
        assert b.kickoff_utc.minute == 0
        assert b.kickoff_utc.tzinfo == _UTC


# ══════════════════════════════════════════════════════════════════════════════
# tve_channel_for
# ══════════════════════════════════════════════════════════════════════════════


class TestTveChannelFor:
    """tve_channel_for correlates matches to broadcasts."""

    def test_exact_match_returns_channel(self):
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        broadcasts = [_bcast(_dt("2026-06-22T17:00:00Z"), "ARG", "AUT", "La 1")]
        assert tve_channel_for(match, broadcasts) == "La 1"

    def test_within_20_min_offset_matches(self):
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        # Broadcast is 10 minutes off — within ±20 min window
        broadcasts = [_bcast(_dt("2026-06-22T17:10:00Z"), "ARG", "AUT", "Teledeporte")]
        assert tve_channel_for(match, broadcasts) == "Teledeporte"

    def test_wrong_teams_same_time_returns_none(self):
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        broadcasts = [_bcast(_dt("2026-06-22T17:00:00Z"), "ESP", "FRA", "La 1")]
        assert tve_channel_for(match, broadcasts) is None

    def test_outside_window_returns_none(self):
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        # Broadcast is 25 min off — outside ±20 min window
        broadcasts = [_bcast(_dt("2026-06-22T17:25:00Z"), "ARG", "AUT", "La 1")]
        assert tve_channel_for(match, broadcasts) is None

    def test_both_channels_returns_la1(self):
        """When La 1 and Teledeporte both match, return La 1."""
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        broadcasts = [
            _bcast(_dt("2026-06-22T17:00:00Z"), "ARG", "AUT", "Teledeporte"),
            _bcast(_dt("2026-06-22T17:00:00Z"), "ARG", "AUT", "La 1"),
        ]
        assert tve_channel_for(match, broadcasts) == "La 1"

    def test_time_only_fallback_single_broadcast(self):
        """TLAs are None + only one broadcast in window → time-only match allowed."""
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        broadcasts = [_bcast(_dt("2026-06-22T17:00:00Z"), None, None, "La 1")]
        assert tve_channel_for(match, broadcasts) == "La 1"

    def test_time_only_fallback_multiple_broadcasts_no_match(self):
        """TLAs are None + two broadcasts at same kickoff → no time-only match (ambiguous)."""
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        broadcasts = [
            _bcast(_dt("2026-06-22T17:00:00Z"), None, None, "La 1"),
            _bcast(_dt("2026-06-22T17:00:00Z"), None, None, "Teledeporte"),
        ]
        assert tve_channel_for(match, broadcasts) is None

    def test_no_broadcasts_returns_none(self):
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z")
        assert tve_channel_for(match, []) is None

    def test_finished_match_can_still_match(self):
        match = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z", status="FINISHED")
        broadcasts = [_bcast(_dt("2026-06-22T17:00:00Z"), "ARG", "AUT", "La 1")]
        assert tve_channel_for(match, broadcasts) == "La 1"

    def test_reversed_home_away_tlas_match(self):
        """TLA set match is unordered — swapping home/away still matches."""
        match = _make_match("AUT", "ARG", "2026-06-22T17:00:00Z")
        broadcasts = [_bcast(_dt("2026-06-22T17:00:00Z"), "ARG", "AUT", "La 1")]
        assert tve_channel_for(match, broadcasts) == "La 1"


# ══════════════════════════════════════════════════════════════════════════════
# load_tve_broadcasts: TTL cache + error handling + disabled flag
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadTveBroadcasts:
    """load_tve_broadcasts respects TTL, handles fetch errors, and checks tve_enabled."""

    def test_disabled_returns_empty_without_fetching(self):
        """When tve_enabled=False, returns [] and never calls fetch."""
        with patch("worldcup_bot.tve.fetch_rtve_schedule") as mock_fetch:
            result = load_tve_broadcasts(tve_enabled=False)
        assert result == []
        mock_fetch.assert_not_called()

    def test_fetch_error_returns_empty_list(self):
        """If all fetches return None, load_tve_broadcasts returns []."""
        with patch("worldcup_bot.tve.fetch_rtve_schedule", return_value=None):
            result = load_tve_broadcasts()
        assert result == []

    def test_fetches_both_channels(self):
        """Both tv1 and dep slugs are fetched once."""
        with patch("worldcup_bot.tve.fetch_rtve_schedule", return_value={"items": []}) as mock_fetch:
            load_tve_broadcasts()
        slugs = {c[0][0] for c in mock_fetch.call_args_list}
        assert "tv1" in slugs
        assert "dep" in slugs

    def test_ttl_cache_second_call_no_refetch(self):
        """A second call within the TTL window must not refetch."""
        schedule = {"items": [_ITEM_LA1_ARG_AUT]}
        with patch("worldcup_bot.tve.fetch_rtve_schedule", return_value=schedule) as mock_fetch:
            result1 = load_tve_broadcasts(ttl_seconds=3600)
            result2 = load_tve_broadcasts(ttl_seconds=3600)
        # tv1 + dep = 2 calls on first invocation; 0 on second
        assert mock_fetch.call_count == 2
        assert result1 == result2

    def test_ttl_expired_refetches(self):
        """After TTL expires the next call must refetch."""
        schedule = {"items": []}
        with patch("worldcup_bot.tve.fetch_rtve_schedule", return_value=schedule) as mock_fetch:
            load_tve_broadcasts(ttl_seconds=0)  # TTL=0 → always expired
            load_tve_broadcasts(ttl_seconds=0)
        assert mock_fetch.call_count == 4  # 2 channels × 2 calls

    def test_returns_parsed_broadcasts(self):
        """Returns actual TveBroadcast objects when fetch succeeds."""
        schedule = {"items": [_ITEM_LA1_ARG_AUT]}
        with patch("worldcup_bot.tve.fetch_rtve_schedule") as mock_fetch:
            mock_fetch.side_effect = lambda slug, **_: schedule if slug == "tv1" else {"items": []}
            result = load_tve_broadcasts()
        assert len(result) == 1
        assert result[0].home_tla == "ARG"


# ══════════════════════════════════════════════════════════════════════════════
# fetch_rtve_schedule
# ══════════════════════════════════════════════════════════════════════════════


class TestFetchRtveSchedule:
    def test_returns_json_on_success(self):
        fake_json = {"nombreCanal": "La 1", "items": []}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = fake_json
        with patch("worldcup_bot.tve.requests.get", return_value=mock_resp):
            result = fetch_rtve_schedule("tv1")
        assert result == fake_json

    def test_returns_none_on_http_error(self):
        with patch("worldcup_bot.tve.requests.get", side_effect=Exception("timeout")):
            result = fetch_rtve_schedule("tv1")
        assert result is None

    def test_returns_none_on_bad_json(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        with patch("worldcup_bot.tve.requests.get", return_value=mock_resp):
            result = fetch_rtve_schedule("tv1")
        assert result is None

    def test_uses_browser_user_agent(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {}
        with patch("worldcup_bot.tve.requests.get", return_value=mock_resp) as mock_get:
            fetch_rtve_schedule("tv1")
        headers = mock_get.call_args.kwargs.get("headers", {})
        ua = headers.get("User-Agent", "")
        assert "Mozilla" in ua


# ══════════════════════════════════════════════════════════════════════════════
# format_match TVE label integration
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatMatchTveLabel:
    """format_match appends 📺 on SCHEDULED but not on FINISHED/IN_PLAY."""

    def test_scheduled_appends_tve_label(self):
        from worldcup_bot.bot.formatters import format_match
        m = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "SCHEDULED")
        result = format_match(m, tve_label="La 1")
        assert "📺 La 1" in result

    def test_scheduled_no_label_no_emoji(self):
        from worldcup_bot.bot.formatters import format_match
        m = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "SCHEDULED")
        result = format_match(m)
        assert "📺" not in result

    def test_finished_ignores_tve_label(self):
        from worldcup_bot.bot.formatters import format_match
        m = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "FINISHED")
        result = format_match(m, tve_label="La 1")
        assert "📺" not in result

    def test_in_play_ignores_tve_label(self):
        from worldcup_bot.bot.formatters import format_match
        m = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "IN_PLAY")
        result = format_match(m, tve_label="La 1")
        assert "📺" not in result

    def test_format_match_with_date_forwards_tve_label(self):
        from worldcup_bot.bot.formatters import format_match_with_date
        m = _make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "SCHEDULED")
        result = format_match_with_date(m, tve_label="Teledeporte")
        assert "📺 Teledeporte" in result


# ══════════════════════════════════════════════════════════════════════════════
# build_ai_user_message TVE integration
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildAiUserMessageTve:
    """build_ai_user_message annotates today fixtures with 📺 when tve_by_key is set."""

    def test_today_fixture_on_tve_carries_emoji(self):
        from worldcup_bot.ai.daily_update import build_ai_user_message
        today = [_make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "SCHEDULED")]
        tve_by_key = {"ARG-AUT": "La 1"}
        msg = build_ai_user_message([], today, [], [], "Europe/Madrid", tve_by_key=tve_by_key)
        assert "📺 La 1" in msg

    def test_today_fixture_not_on_tve_no_emoji(self):
        from worldcup_bot.ai.daily_update import build_ai_user_message
        today = [_make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "SCHEDULED")]
        msg = build_ai_user_message([], today, [], [], "Europe/Madrid")
        assert "📺" not in msg

    def test_tve_by_key_none_no_emoji(self):
        from worldcup_bot.ai.daily_update import build_ai_user_message
        today = [_make_match("ARG", "AUT", "2026-06-22T17:00:00Z", "SCHEDULED")]
        msg = build_ai_user_message([], today, [], [], "Europe/Madrid", tve_by_key=None)
        assert "📺" not in msg

    def test_only_matching_fixture_gets_emoji(self):
        """Only the fixture in tve_by_key is annotated; others are untouched."""
        from worldcup_bot.ai.daily_update import build_ai_user_message
        today = [
            _make_match("ARG", "AUT", "2026-06-22T17:00:00Z"),
            _make_match("ESP", "KSA", "2026-06-22T20:00:00Z"),
        ]
        tve_by_key = {"ESP-KSA": "La 1"}
        msg = build_ai_user_message([], today, [], [], "Europe/Madrid", tve_by_key=tve_by_key)
        lines = msg.splitlines()
        tve_lines = [l for l in lines if "📺" in l]
        assert len(tve_lines) == 1
        assert "ESP-KSA" in tve_lines[0]
