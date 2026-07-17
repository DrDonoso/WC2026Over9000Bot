"""Tests for the Final ceremony module and job.

Coverage:
- Pure builder functions (pre_final_text, campeon_text, podium_participants)
- State helpers (load/save round-trip, missing file, corrupt file)
- poll_final_ceremony_job: pre-final trigger, campeon trigger, idempotency,
  state persistence, edge cases (no match, API error, all done)
- cmd_granfinal: fires the right piece, handles missing match/group
- /granfinal absence from /start help
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.bot.final_ceremony import (
    COPY_CAMPEON_TEMPLATE,
    COPY_PRE_FINAL_HEADER,
    COPY_PRE_FINAL_RANKING_TITLE,
    build_campeon_text,
    build_podium_participants,
    build_pre_final_text,
    load_ceremony_state,
    save_ceremony_state,
)
from worldcup_bot.__main__ import cmd_granfinal, poll_final_ceremony_job
from worldcup_bot.config import Settings
from worldcup_bot.porra.engine import UserRankEntry


# ── helpers ───────────────────────────────────────────────────────────────────

_NOW_UTC = datetime.now(timezone.utc)
_PAST_STR = (_NOW_UTC - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
_FUTURE_STR = (_NOW_UTC + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_final_match(
    status: str = "SCHEDULED",
    utc_date: str | None = None,
    winner: str | None = None,
    home_tla: str = "ESP",
    away_tla: str = "ARG",
    home_name: str = "Spain",
    away_name: str = "Argentina",
) -> Match:
    return Match(
        id=999,
        utc_date=utc_date or _FUTURE_STR,
        status=status,
        stage="FINAL",
        group=None,
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=None,
        away_score=None,
        winner=winner,
    )


def _make_other_match() -> Match:
    return Match(
        id=1,
        utc_date=_PAST_STR,
        status="FINISHED",
        stage="SEMI_FINALS",
        group=None,
        home_tla="FRA",
        away_tla="ENG",
        home_name="France",
        away_name="England",
        home_score=2,
        away_score=1,
        winner="HOME_TEAM",
    )


def _make_settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567",
        state_dir=str(tmp_path),
        predictions_path=str(tmp_path / "predictions.yml"),
    )


def _make_context(settings: Settings, state: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "final_ceremony_state": state or {"pre_final_sent": False, "campeon_sent": False},
    }
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_photo = AsyncMock()
    return ctx


def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_ranking_rows() -> list[UserRankEntry]:
    return [
        UserRankEntry("alice", "Alice", 25.0, 0.0, 15.0, {}, 3),
        UserRankEntry("bob", "Bob", 20.0, 0.0, 10.0, {}, 2),
        UserRankEntry("carol", "Carol", 15.0, 0.0, 8.0, {}, 1),
        UserRankEntry("dave", "Dave", 10.0, 0.0, 5.0, {}, 0),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Pure builder tests
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPreFinalText:
    def test_includes_header_and_ranking(self):
        text = build_pre_final_text("RANKING_TEXT", "CAMPS_BLOCK")
        assert COPY_PRE_FINAL_HEADER in text
        assert "RANKING_TEXT" in text
        assert "CAMPS_BLOCK" in text

    def test_empty_camps_block_omitted(self):
        text = build_pre_final_text("RANKING_TEXT", "")
        assert "RANKING_TEXT" in text
        # No third section appended — "CAMPS_BLOCK" literal not present
        assert "CAMPS_BLOCK" not in text

    def test_sections_joined_with_blank_lines(self):
        text = build_pre_final_text("A", "B")
        assert "\n\n" in text
        # All three parts present
        assert COPY_PRE_FINAL_HEADER in text
        assert "A" in text
        assert "B" in text


class TestBuildCampeonText:
    def test_contains_winner_name(self):
        text = build_campeon_text("ESP", "Spain", "🇪🇸")
        assert "Spain" in text

    def test_contains_flag(self):
        text = build_campeon_text("ESP", "Spain", "🇪🇸")
        assert "🇪🇸" in text

    def test_contains_campeon_marker(self):
        text = build_campeon_text("ARG", "Argentina", "🇦🇷")
        assert "CAMPEÓN" in text

    def test_uses_provided_name_and_flag(self):
        text = build_campeon_text("ESP", "España", "🇪🇸")
        assert "España" in text
        assert "🇪🇸" in text


class TestBuildPodiumParticipants:
    def test_returns_top_3(self):
        rows = _make_ranking_rows()
        result = build_podium_participants(rows)
        assert len(result) == 3

    def test_correct_fields(self):
        rows = _make_ranking_rows()
        result = build_podium_participants(rows)
        assert result[0]["username"] == "alice"
        assert result[0]["display_name"] == "Alice"
        assert result[0]["position"] == 1

    def test_positions_1_2_3_no_ties(self):
        rows = _make_ranking_rows()
        result = build_podium_participants(rows)
        assert [r["position"] for r in result] == [1, 2, 3]

    def test_tied_positions(self):
        rows = [
            UserRankEntry("a", "A", 20.0, 0.0, 10.0, {}, 0),
            UserRankEntry("b", "B", 20.0, 0.0, 10.0, {}, 0),
            UserRankEntry("c", "C", 15.0, 0.0, 5.0, {}, 0),
        ]
        result = build_podium_participants(rows)
        assert result[0]["position"] == 1
        assert result[1]["position"] == 1
        assert result[2]["position"] == 3

    def test_empty_rows(self):
        assert build_podium_participants([]) == []

    def test_fewer_than_3_rows(self):
        rows = [UserRankEntry("a", "A", 10.0, 0.0, 5.0, {}, 0)]
        result = build_podium_participants(rows)
        assert len(result) == 1
        assert result[0]["position"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# State helper tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCeremonyState:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        state = load_ceremony_state(str(tmp_path / "nonexistent.json"))
        assert state == {"pre_final_sent": False, "campeon_sent": False}

    def test_save_and_load_round_trip(self, tmp_path):
        path = str(tmp_path / "state.json")
        save_ceremony_state(path, {"pre_final_sent": True, "campeon_sent": False})
        loaded = load_ceremony_state(path)
        assert loaded == {"pre_final_sent": True, "campeon_sent": False}

    def test_load_corrupt_file_returns_defaults(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("not json", encoding="utf-8")
        state = load_ceremony_state(str(p))
        assert state == {"pre_final_sent": False, "campeon_sent": False}

    def test_save_does_not_raise_on_bad_path(self):
        # Best-effort: must not raise even with a non-existent parent dir
        save_ceremony_state("/nonexistent/dir/state.json", {"pre_final_sent": True, "campeon_sent": False})

    def test_load_partial_state_defaults_missing_keys(self, tmp_path):
        p = tmp_path / "partial.json"
        p.write_text('{"pre_final_sent": true}', encoding="utf-8")
        state = load_ceremony_state(str(p))
        assert state["pre_final_sent"] is True
        assert state["campeon_sent"] is False

    def test_both_flags_true_round_trips(self, tmp_path):
        path = str(tmp_path / "done.json")
        save_ceremony_state(path, {"pre_final_sent": True, "campeon_sent": True})
        state = load_ceremony_state(path)
        assert state["pre_final_sent"] is True
        assert state["campeon_sent"] is True


# ══════════════════════════════════════════════════════════════════════════════
# poll_final_ceremony_job — PRE-FINAL piece
# ══════════════════════════════════════════════════════════════════════════════

class TestPollFinalCeremonyJobPreFinal:
    @pytest.mark.asyncio
    async def test_fires_pre_final_when_kickoff_reached(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_final_match(status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_awaited_once()
        assert ctx.bot_data["final_ceremony_state"]["pre_final_sent"] is True

    @pytest.mark.asyncio
    async def test_fires_pre_final_when_in_play(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        # status=IN_PLAY overrides future date
        match = _make_final_match(status="IN_PLAY", utc_date=_FUTURE_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fires_pre_final_when_paused(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_final_match(status="PAUSED", utc_date=_FUTURE_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_pre_final_when_future_scheduled(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_final_match(status="SCHEDULED", utc_date=_FUTURE_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_not_awaited()
        assert ctx.bot_data["final_ceremony_state"]["pre_final_sent"] is False

    @pytest.mark.asyncio
    async def test_pre_final_idempotent_already_sent(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": False})
        match = _make_final_match(status="IN_PLAY", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pre_final_persisted_to_disk(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_final_match(status="IN_PLAY", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock),
        ):
            await poll_final_ceremony_job(ctx)

        state_path = tmp_path / "final_ceremony_state.json"
        assert state_path.exists()
        saved = json.loads(state_path.read_text())
        assert saved["pre_final_sent"] is True

    @pytest.mark.asyncio
    async def test_pre_final_not_marked_on_send_failure(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_final_match(status="IN_PLAY", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        async def _fail(*a, **kw):
            raise RuntimeError("network error")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", side_effect=_fail),
        ):
            await poll_final_ceremony_job(ctx)  # must not raise

        assert ctx.bot_data["final_ceremony_state"]["pre_final_sent"] is False


# ══════════════════════════════════════════════════════════════════════════════
# poll_final_ceremony_job — CAMPEÓN piece
# ══════════════════════════════════════════════════════════════════════════════

class TestPollFinalCeremonyJobCampeon:
    @pytest.mark.asyncio
    async def test_fires_campeon_when_finished(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": False})
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner="HOME_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await poll_final_ceremony_job(ctx)

        mock_camp.assert_awaited_once()
        assert ctx.bot_data["final_ceremony_state"]["campeon_sent"] is True

    @pytest.mark.asyncio
    async def test_campeon_fires_with_away_winner(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": False})
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner="AWAY_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await poll_final_ceremony_job(ctx)

        mock_camp.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_campeon_not_fires_when_in_play(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": False})
        match = _make_final_match(status="IN_PLAY", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await poll_final_ceremony_job(ctx)

        mock_camp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_campeon_not_fires_when_no_winner(self, tmp_path):
        """FINISHED but winner=None (shouldn't happen in practice, but guard it)."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": False})
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner=None)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await poll_final_ceremony_job(ctx)

        mock_camp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_campeon_idempotent_already_sent(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": True})
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner="HOME_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await poll_final_ceremony_job(ctx)

        mock_camp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_campeon_persisted_to_disk(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": False})
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner="AWAY_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock),
        ):
            await poll_final_ceremony_job(ctx)

        state_path = tmp_path / "final_ceremony_state.json"
        assert state_path.exists()
        saved = json.loads(state_path.read_text())
        assert saved["campeon_sent"] is True


# ══════════════════════════════════════════════════════════════════════════════
# poll_final_ceremony_job — edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestPollFinalCeremonyJobMisc:
    @pytest.mark.asyncio
    async def test_all_done_no_api_call(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": True, "campeon_sent": True})
        mock_client = MagicMock()
        ctx.bot_data["football_client"] = mock_client

        await poll_final_ceremony_job(ctx)

        mock_client.get_all_matches.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_final_match_no_send(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_other_match()]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_api_error_is_handled_gracefully(self, tmp_path):
        from worldcup_bot.api.client import FootballAPIError

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        mock_client = MagicMock()
        mock_client.get_all_matches.side_effect = FootballAPIError(503, "timeout")

    @pytest.mark.asyncio
    async def test_both_pieces_fire_when_finished_and_neither_sent(self, tmp_path):
        """Pre-final never sent + match already FINISHED → both pieces fire in one tick."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state={"pre_final_sent": False, "campeon_sent": False})
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner="HOME_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await poll_final_ceremony_job(ctx)

        mock_pre.assert_awaited_once()
        mock_camp.assert_awaited_once()
        assert ctx.bot_data["final_ceremony_state"]["pre_final_sent"] is True
        assert ctx.bot_data["final_ceremony_state"]["campeon_sent"] is True

    @pytest.mark.asyncio
    async def test_restart_safety_loads_from_disk(self, tmp_path):
        """After restart, flags are loaded from disk and no pieces re-fire."""
        path = str(tmp_path / "final_ceremony_state.json")
        save_ceremony_state(path, {"pre_final_sent": True, "campeon_sent": True})

        # Simulate a fresh start: load from disk
        state = load_ceremony_state(path)
        assert state["pre_final_sent"] is True
        assert state["campeon_sent"] is True

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, state=state)
        mock_client = MagicMock()
        ctx.bot_data["football_client"] = mock_client

        await poll_final_ceremony_job(ctx)

        mock_client.get_all_matches.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_granfinal tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdGranfinal:
    @pytest.mark.asyncio
    async def test_fires_pre_final_when_scheduled(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        update = _make_update()
        match = _make_final_match(status="SCHEDULED", utc_date=_FUTURE_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_pre_final", new_callable=AsyncMock) as mock_pre,
        ):
            await cmd_granfinal(update, ctx)

        mock_pre.assert_awaited_once()
        assert ctx.bot_data["final_ceremony_state"]["pre_final_sent"] is True

    @pytest.mark.asyncio
    async def test_fires_campeon_and_podio_when_finished(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        update = _make_update()
        match = _make_final_match(status="FINISHED", utc_date=_PAST_STR, winner="AWAY_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._send_campeon_and_podio", new_callable=AsyncMock) as mock_camp,
        ):
            await cmd_granfinal(update, ctx)

        mock_camp.assert_awaited_once()
        assert ctx.bot_data["final_ceremony_state"]["campeon_sent"] is True

    @pytest.mark.asyncio
    async def test_no_final_match_sends_warning(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        update = _make_update()
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = []

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await cmd_granfinal(update, ctx)

        update.message.reply_text.assert_awaited()
        text = update.message.reply_text.call_args_list[-1].args[0]
        assert "Final" in text or "final" in text

    @pytest.mark.asyncio
    async def test_no_group_id_sends_warning(self, tmp_path):
        settings = Settings(
            telegram_bot_token="tok",
            football_data_api_key="key",
            telegram_group_id=None,
            state_dir=str(tmp_path),
            predictions_path=str(tmp_path / "predictions.yml"),
        )
        ctx = _make_context(settings)
        update = _make_update()

        await cmd_granfinal(update, ctx)

        update.message.reply_text.assert_awaited()
        ctx.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_api_error_sends_error_message(self, tmp_path):
        from worldcup_bot.api.client import FootballAPIError

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        update = _make_update()
        mock_client = MagicMock()
        mock_client.get_all_matches.side_effect = FootballAPIError(503, "timeout")

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await cmd_granfinal(update, ctx)  # must not raise

        update.message.reply_text.assert_awaited()
        text = update.message.reply_text.call_args_list[-1].args[0]
        assert "❌" in text or "error" in text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Absent from help
# ══════════════════════════════════════════════════════════════════════════════

def test_granfinal_absent_from_help_commands():
    """The /granfinal command must NOT appear in the public help listing."""
    from worldcup_bot.bot.handlers import _HELP_COMMANDS
    assert "granfinal" not in _HELP_COMMANDS
