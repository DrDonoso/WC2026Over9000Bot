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


def _make_context(settings: Settings, scanner=None, seen_api: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "reddit_scanner": scanner,
        "seen_scores": {"api": seen_api or {}, "thread": {}},
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
    async def test_seed_at_zero_score_no_sends(self, tmp_path):
        """First time a match is seen at 0-0: store state, send nothing."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())

        match = _make_match(1, "IN_PLAY", home_score=0, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}) as _,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert "1" in saved
        assert saved["1"]["home"] == 0
        assert saved["1"]["away"] == 0

    @pytest.mark.asyncio
    async def test_seed_nonzero_first_sight_announces_catchup_goals(self, tmp_path):
        """API first reports IN_PLAY at 2-0 (status-flip delay) → ONE neutral catch-up notification."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 99
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # ONE catch-up notification (not 2 per-goal messages)
        assert ctx.bot.send_message.await_count == 1
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚠️" in text
        assert "perdí" in text
        assert "2" in text  # goals_missed count

    @pytest.mark.asyncio
    async def test_seed_nonzero_clips_store_entries_created(self, tmp_path):
        """Catch-up for first-seen non-zero score creates ONE clip-store entry."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 77
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        match = _make_match(1, "IN_PLAY", home_score=1, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # ONE catchup → ONE clip-store entry (keyed by {id}:catchup:{H}-{A})
        assert len(ctx.bot_data["clip_store"]) == 1

    @pytest.mark.asyncio
    async def test_restart_mid_match_missed_goal_announced(self, tmp_path):
        """Bot restarted with live_scores at 1-1, API returns 2-1 → neutral catch-up announced."""
        settings = _make_settings(tmp_path)
        # seen_api is empty (restart reset in-memory seen)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={})
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 55
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        # live_scores.json had 1-1 from before crash
        stored_state = {"1": {"home": 1, "away": 1, "status": "IN_PLAY"}}
        # API now reports 2-1
        match = _make_match(1, "IN_PLAY", home_score=2, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # The 1-1 → 2-1 goal must be announced even though seen was reset
        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        # Must be the neutral catch-up format, not a per-goal attribution
        assert "⚠️" in text
        assert "perdí" in text
        assert "⚽" not in text  # no per-goal goal emoji

    @pytest.mark.asyncio
    async def test_catchup_message_no_scorer_attribution_no_keyboard(self, tmp_path):
        """Neutral catch-up: message must not attribute scorer/team; initial send has no keyboard."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 11
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        match = _make_match(
            42, "IN_PLAY",
            home_name="Ecuador", away_name="Germany",
            home_tla="ECU", away_tla="GER",
            home_score=2, away_score=1,
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        call_kwargs = ctx.bot.send_message.call_args.kwargs
        text = call_kwargs["text"]

        # Must NOT attribute goals to a team (no "¡GOOOL!" style content)
        assert "GOOOL" not in text
        assert "⚽" not in text
        # Must NOT carry a keyboard on the initial send
        assert "reply_markup" not in call_kwargs
        # Must show the current score
        assert "2-1" in text or ("2" in text and "1" in text)

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 0, "away": 0}})

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 0, "away": 0}})

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 0, "away": 0}})

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 1, "away": 0}})

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 2, "away": 0}})

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 0, "away": 0}})
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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 1, "away": 0}})

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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 0, "away": 0}})
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
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 2, "away": 0}})
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


# ══════════════════════════════════════════════════════════════════════════════
# Shared state: poll_goals_job uses bot_data["live_scores"]
# ══════════════════════════════════════════════════════════════════════════════


class TestSharedState:
    @pytest.mark.asyncio
    async def test_poll_goals_uses_pre_populated_live_scores(self, tmp_path):
        """When bot_data['live_scores'] is pre-populated (build_app path), poll_goals uses it."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 0, "away": 0}})

        # Pre-populate as build_app would
        shared_scores = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        ctx.bot_data["live_scores"] = shared_scores

        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)
        fake_sent = MagicMock()
        fake_sent.message_id = 42
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # Goal sent and shared dict mutated in-place
        ctx.bot.send_message.assert_called_once()
        assert shared_scores["1"]["home"] == 1

    @pytest.mark.asyncio
    async def test_poll_goals_falls_back_to_load_scores_when_key_absent(self, tmp_path):
        """When bot_data has no 'live_scores' key, poll_goals_job falls back to load_scores."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        # Note: no "live_scores" key in bot_data

        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}) as mock_load,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # load_scores was called as fallback (setdefault)
        mock_load.assert_called_once()
        # Key now populated in bot_data
        assert "live_scores" in ctx.bot_data


# ══════════════════════════════════════════════════════════════════════════════
# _notify_goal helper
# ══════════════════════════════════════════════════════════════════════════════


class TestNotifyGoal:
    @pytest.mark.asyncio
    async def test_notify_goal_sends_message_and_registers_clip(self, tmp_path):
        """_notify_goal: sends goal message AND registers a clip-store entry."""
        from worldcup_bot.__main__ import _notify_goal

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 55
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        with patch("worldcup_bot.__main__.save_clips"):
            await _notify_goal(
                match=match,
                new_home=1,
                new_away=0,
                scoring_team="France",
                scorer="Mbappé",
                minute="35",
                settings=settings,
                context=ctx,
                silent=False,
            )

        ctx.bot.send_message.assert_called_once()
        call_kwargs = ctx.bot.send_message.call_args.kwargs
        assert "⚽" in call_kwargs["text"]
        assert call_kwargs["parse_mode"] == "HTML"

        clips = ctx.bot_data["clip_store"]
        assert len(clips) == 1
        entry = next(iter(clips.values()))
        assert entry["status"] == "searching"
        assert entry["message_id"] == 55
        assert entry["scorer"] == "Mbappé"
        assert entry["minute"] == "35"

    @pytest.mark.asyncio
    async def test_notify_goal_token_key_format(self, tmp_path):
        """_notify_goal token key is {match.id}:{scoring_team}:{new_home}-{new_away}."""
        from worldcup_bot.__main__ import _notify_goal
        from worldcup_bot.reddit.clip_store import goal_token

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner())
        ctx.bot_data["clip_store"] = {}

        fake_sent = MagicMock()
        fake_sent.message_id = 1
        ctx.bot.send_message = AsyncMock(return_value=fake_sent)

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal", home_score=2, away_score=1)

        expected_token = goal_token("1:France:2-1")

        with patch("worldcup_bot.__main__.save_clips"):
            await _notify_goal(
                match=match,
                new_home=2,
                new_away=1,
                scoring_team="France",
                scorer=None,
                minute=None,
                settings=settings,
                context=ctx,
                silent=False,
            )

        assert expected_token in ctx.bot_data["clip_store"]
