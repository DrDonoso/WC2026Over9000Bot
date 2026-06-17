"""Tests for poll_goals_job — score-based detection, seeding, goal/disallowed messages,
and persistence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.config import Settings


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_match(
    mid: int = 1,
    status: str = "IN_PLAY",
    home_name: str = "France",
    away_name: str = "Senegal",
    home_tla: str = "FRA",
    away_tla: str = "SEN",
    home_score: int | None = 1,
    away_score: int | None = 0,
) -> Match:
    return Match(
        id=mid,
        utc_date="2026-06-17T18:00:00Z",
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=home_score,
        away_score=away_score,
        winner=None,
    )


def _make_settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567",
        state_dir=str(tmp_path),
    )


def _make_context(settings: Settings, scanner=None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "reddit_scanner": scanner,
    }
    ctx.bot.send_message = AsyncMock()
    return ctx


def _no_enrichment_scanner() -> MagicMock:
    """Return a mock scanner that finds no Reddit thread (enrichment skipped)."""
    scanner = MagicMock()
    scanner.find_match_thread = MagicMock(return_value=None)
    scanner.get_thread_body = MagicMock(return_value="")
    return scanner


from worldcup_bot.__main__ import poll_goals_job


# ══════════════════════════════════════════════════════════════════════════════
# Seeding behaviour
# ══════════════════════════════════════════════════════════════════════════════


class TestSeedingBehaviour:
    @pytest.mark.asyncio
    async def test_seed_on_first_sight_no_sends(self, tmp_path):
        """First time a match is seen: store state, send nothing."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}) as _,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # No notification sent for first-seen match
        ctx.bot.send_message.assert_not_called()
        # State persisted with seeded score
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert "1" in saved
        assert saved["1"]["home"] == 1
        assert saved["1"]["away"] == 0

    @pytest.mark.asyncio
    async def test_no_relevant_matches_returns_early(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        # TIMED matches are not relevant
        match = _make_match(1, "SCHEDULED")

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}) as _,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Goal detection
# ══════════════════════════════════════════════════════════════════════════════


class TestGoalDetection:
    @pytest.mark.asyncio
    async def test_score_increase_sends_goal_message(self, tmp_path):
        """Stored 0-0, current 1-0 → one goal notification sent."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        stored_state = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        call_kwargs = ctx.bot.send_message.call_args.kwargs
        assert call_kwargs["parse_mode"] == "HTML"
        text = call_kwargs["text"]
        assert "⚽" in text
        assert "France" in text

    @pytest.mark.asyncio
    async def test_goal_message_has_no_keyboard(self, tmp_path):
        """Block 1: goal messages must NOT include a reply_markup."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        stored_state = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        call_kwargs = ctx.bot.send_message.call_args.kwargs
        assert "reply_markup" not in call_kwargs

    @pytest.mark.asyncio
    async def test_state_updated_after_goal(self, tmp_path):
        """After a goal, stored state updated to new score."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        stored_state = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        saved = mock_save.call_args[0][1]
        assert saved["1"]["home"] == 1
        assert saved["1"]["away"] == 0

    @pytest.mark.asyncio
    async def test_finished_match_in_state_catches_final_goal(self, tmp_path):
        """FINISHED match already in state should trigger goal detection."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        stored_state = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "FINISHED", home_score=2, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_finished_match_not_in_state_not_processed(self, tmp_path):
        """FINISHED match NOT in stored state should be ignored (avoid spamming old goals)."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        match = _make_match(1, "FINISHED", home_score=2, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Disallowed path
# ══════════════════════════════════════════════════════════════════════════════


class TestDisallowedGoal:
    @pytest.mark.asyncio
    async def test_score_decrease_sends_disallowed_message(self, tmp_path):
        """Stored 2-0, current 1-0 → disallowed (VAR) message sent."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        stored_state = {"1": {"home": 2, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "❌" in text
        assert "VAR" in text
        assert "France" in text


# ══════════════════════════════════════════════════════════════════════════════
# Persistence
# ══════════════════════════════════════════════════════════════════════════════


class TestPersistence:
    @pytest.mark.asyncio
    async def test_save_scores_called_on_seed(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        match = _make_match(1, "IN_PLAY", home_score=0, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_scores_called_on_goal(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        stored_state = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert saved["1"]["home"] == 1

    @pytest.mark.asyncio
    async def test_no_changes_save_not_called(self, tmp_path):
        """No state changes → save_scores should NOT be called."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        stored_state = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_error_does_not_call_save(self, tmp_path):
        from worldcup_bot.api.client import FootballAPIError
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.side_effect = FootballAPIError(
                429, "rate limit"
            )
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Clip-store integration
# ══════════════════════════════════════════════════════════════════════════════


class TestClipStoreIntegration:
    @pytest.mark.asyncio
    async def test_goal_detection_creates_searching_entry(self, tmp_path):
        """After detecting a goal, a clip-store entry with status='searching' is written."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 42
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        stored_state = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        clips = ctx.bot_data["clip_store"]
        assert len(clips) == 1
        token, entry = next(iter(clips.items()))
        assert len(token) == 12
        assert entry["status"] == "searching"
        assert entry["message_id"] == 42
        assert entry["attempts"] == 0

    @pytest.mark.asyncio
    async def test_disallowed_goal_does_not_create_clip_entry(self, tmp_path):
        """A VAR disallowed goal (score decrease) must NOT write a clip-store entry."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        stored_state = {"1": {"home": 2, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot_data["clip_store"] == {}
