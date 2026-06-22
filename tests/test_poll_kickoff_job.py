"""Tests for poll_kickoff_job — seeds on first run, fires at scheduled kickoff,
restart-safe dedup, 30-min grace window, silent-hour flag.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.bot.formatters import format_match_start
from worldcup_bot.config import Settings


# ── helpers ───────────────────────────────────────────────────────────────────

# Time fixtures computed relative to *now* so no datetime mocking is needed.
# The test suite is fast enough that these offsets stay valid throughout the run.
_NOW_UTC = datetime.now(timezone.utc)
# 5 minutes ago — within the 30-min grace window → should be announced
_PAST_STR = (_NOW_UTC - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
# 60 minutes ago — beyond the 30-min grace window → should NOT be announced
_OLD_STR = (_NOW_UTC - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
# 30 minutes from now — future → should NOT be announced yet
_FUTURE_STR = (_NOW_UTC + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_match(
    mid: int,
    status: str = "SCHEDULED",
    utc_date: str | None = None,
    home_name: str = "Argentina",
    away_name: str = "Austria",
    home_tla: str = "ARG",
    away_tla: str = "AUT",
) -> Match:
    return Match(
        id=mid,
        utc_date=utc_date or _FUTURE_STR,
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=None,
        away_score=None,
        winner=None,
    )


def _make_settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567",
        state_dir=str(tmp_path),
        predictions_path=str(tmp_path / "predictions.yml"),
    )


def _make_context(settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "kickoff_announced": set(),
        "kickoff_seeded": False,
    }
    ctx.bot.send_message = AsyncMock()
    return ctx


# ── import job under test ─────────────────────────────────────────────────────

from worldcup_bot.__main__ import poll_kickoff_job


# ── seed pass tests ───────────────────────────────────────────────────────────


class TestSeedPass:
    @pytest.mark.asyncio
    async def test_seeds_past_kickoff_sends_nothing(self, tmp_path):
        """On first run, a match whose kickoff already passed is seeded — no send."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_match(1, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 1 in ctx.bot_data["kickoff_announced"]
        assert ctx.bot_data["kickoff_seeded"] is True

    @pytest.mark.asyncio
    async def test_seeds_in_play_sends_nothing(self, tmp_path):
        """On first run, an IN_PLAY match is seeded — no send."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_match(2, status="IN_PLAY", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 2 in ctx.bot_data["kickoff_announced"]

    @pytest.mark.asyncio
    async def test_seeds_finished_sends_nothing(self, tmp_path):
        """On first run, a FINISHED match is seeded — no send."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_match(3, status="FINISHED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 3 in ctx.bot_data["kickoff_announced"]

    @pytest.mark.asyncio
    async def test_future_match_not_seeded(self, tmp_path):
        """On first run, a future SCHEDULED match is NOT seeded (will be announced later)."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_match(4, status="SCHEDULED", utc_date=_FUTURE_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 4 not in ctx.bot_data["kickoff_announced"]
        assert ctx.bot_data["kickoff_seeded"] is True

    @pytest.mark.asyncio
    async def test_seeds_persisted_to_disk(self, tmp_path):
        """Seed pass writes kickoff_announced.json to disk."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        match = _make_match(5, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        json_path = tmp_path / "kickoff_announced.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert 5 in data


# ── normal pass tests ─────────────────────────────────────────────────────────


class TestNormalPass:
    def _ctx_seeded(self, settings, announced=None) -> MagicMock:
        ctx = _make_context(settings)
        ctx.bot_data["kickoff_seeded"] = True
        ctx.bot_data["kickoff_announced"] = set(announced or [])
        return ctx

    @pytest.mark.asyncio
    async def test_announces_match_just_kicked_off(self, tmp_path):
        """A SCHEDULED match whose kickoff was 5 min ago → exactly one send."""
        settings = _make_settings(tmp_path)
        ctx = self._ctx_seeded(settings)
        match = _make_match(10, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_awaited_once()
        assert 10 in ctx.bot_data["kickoff_announced"]

    @pytest.mark.asyncio
    async def test_does_not_announce_future_match(self, tmp_path):
        """A SCHEDULED match with kickoff in the future → no send."""
        settings = _make_settings(tmp_path)
        ctx = self._ctx_seeded(settings)
        match = _make_match(11, status="SCHEDULED", utc_date=_FUTURE_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 11 not in ctx.bot_data["kickoff_announced"]

    @pytest.mark.asyncio
    async def test_idempotent_already_announced(self, tmp_path):
        """A match already in kickoff_announced → no re-send."""
        settings = _make_settings(tmp_path)
        ctx = self._ctx_seeded(settings, announced={12})
        match = _make_match(12, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finished_match_marked_not_announced(self, tmp_path):
        """A FINISHED match (not yet in announced) → marked but not sent."""
        settings = _make_settings(tmp_path)
        ctx = self._ctx_seeded(settings)
        match = _make_match(13, status="FINISHED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 13 in ctx.bot_data["kickoff_announced"]

    @pytest.mark.asyncio
    async def test_grace_window_exceeded_not_announced(self, tmp_path):
        """A match with kickoff >30 min ago and not in announced → silently skipped."""
        settings = _make_settings(tmp_path)
        ctx = self._ctx_seeded(settings)
        match = _make_match(14, status="SCHEDULED", utc_date=_OLD_STR)  # 60 min ago
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        # Marked to prevent repeated skip-checks on every tick
        assert 14 in ctx.bot_data["kickoff_announced"]

    @pytest.mark.asyncio
    async def test_persists_after_announce(self, tmp_path):
        """After announcing, kickoff_announced.json is updated on disk."""
        settings = _make_settings(tmp_path)
        ctx = self._ctx_seeded(settings)
        match = _make_match(15, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        json_path = tmp_path / "kickoff_announced.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert 15 in data


# ── restart safety ────────────────────────────────────────────────────────────


class TestRestartSafety:
    @pytest.mark.asyncio
    async def test_restart_does_not_reannounce_seeded_matches(self, tmp_path):
        """Simulate a restart: seed, then run a normal pass — no re-announce."""
        settings = _make_settings(tmp_path)

        # --- first run (seed) ---
        ctx1 = _make_context(settings)
        match = _make_match(20, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx1)

        assert 20 in ctx1.bot_data["kickoff_announced"]
        ctx1.bot.send_message.assert_not_awaited()

        # --- simulate restart: reload state from disk ---
        from worldcup_bot.reddit.finished_state import load_finished
        disk_state = load_finished(str(tmp_path / "kickoff_announced.json"))

        ctx2 = _make_context(settings)
        ctx2.bot_data["kickoff_announced"] = disk_state
        ctx2.bot_data["kickoff_seeded"] = True  # seed pass already ran
        mock_client2 = MagicMock()
        mock_client2.get_all_matches.return_value = [match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client2):
            await poll_kickoff_job(ctx2)

        ctx2.bot.send_message.assert_not_awaited()


# ── silent-hour tests ─────────────────────────────────────────────────────────


class TestSilentHour:
    @pytest.mark.asyncio
    async def test_silent_hour_sets_disable_notification(self, tmp_path):
        """When _is_silent_hour returns True, send_message uses disable_notification=True."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        ctx.bot_data["kickoff_seeded"] = True
        match = _make_match(30, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._is_silent_hour", return_value=True),
        ):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_awaited_once()
        kwargs = ctx.bot.send_message.call_args[1]
        assert kwargs["disable_notification"] is True

    @pytest.mark.asyncio
    async def test_non_silent_hour_notification_enabled(self, tmp_path):
        """During normal hours, disable_notification is False."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        ctx.bot_data["kickoff_seeded"] = True
        match = _make_match(31, status="SCHEDULED", utc_date=_PAST_STR)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__._is_silent_hour", return_value=False),
        ):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_awaited_once()
        kwargs = ctx.bot.send_message.call_args[1]
        assert kwargs["disable_notification"] is False


# ── football API error ────────────────────────────────────────────────────────


class TestAPIError:
    @pytest.mark.asyncio
    async def test_api_error_logs_and_returns(self, tmp_path):
        """FootballAPIError → log warning + return (no crash, no send)."""
        from worldcup_bot.api.client import FootballAPIError

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)
        ctx.bot_data["kickoff_seeded"] = True
        mock_client = MagicMock()
        mock_client.get_all_matches.side_effect = FootballAPIError(503, "timeout")

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_kickoff_job(ctx)

        ctx.bot.send_message.assert_not_awaited()


# ── format_match_start tests ──────────────────────────────────────────────────


class TestFormatMatchStart:
    def _make_match_for_format(
        self,
        home_name: str = "Argentina",
        away_name: str = "Austria",
        home_tla: str = "ARG",
        away_tla: str = "AUT",
    ) -> Match:
        return Match(
            id=1,
            utc_date="2026-06-22T18:00:00Z",
            status="SCHEDULED",
            stage="GROUP_STAGE",
            group="GROUP_A",
            home_tla=home_tla,
            away_tla=away_tla,
            home_name=home_name,
            away_name=away_name,
            home_score=None,
            away_score=None,
            winner=None,
        )

    def test_contains_green_circle(self):
        m = self._make_match_for_format()
        assert "🟢" in format_match_start(m)

    def test_contains_spanish_text(self):
        m = self._make_match_for_format()
        text = format_match_start(m)
        assert "¡Empieza el partido!" in text

    def test_contains_team_names(self):
        m = self._make_match_for_format()
        text = format_match_start(m)
        assert "Argentina" in text
        assert "Austria" in text

    def test_html_bold_team_names(self):
        m = self._make_match_for_format()
        text = format_match_start(m)
        assert "<b>Argentina</b>" in text
        assert "<b>Austria</b>" in text

    def test_html_escapes_special_chars(self):
        m = self._make_match_for_format(
            home_name="Team <A>",
            away_name="Team & B",
            home_tla="AAA",
            away_tla="BBB",
        )
        text = format_match_start(m)
        assert "<A>" not in text
        assert "&amp;" in text or "Team & B" not in text
        assert "Team &lt;A&gt;" in text

    def test_parse_mode_html_tag_structure(self):
        """Text contains parse_mode=HTML-safe bold tags."""
        m = self._make_match_for_format()
        text = format_match_start(m)
        assert "<b>" in text and "</b>" in text
