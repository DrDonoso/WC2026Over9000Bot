"""Tests for poll_goals_job — score-based detection, seeding, goal/disallowed messages,
and persistence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    utc_date: str | None = None,
) -> Match:
    if utc_date is None:
        # Default: kickoff 30 min ago so MATCH_OVER_AGE (4h) never triggers in standard tests.
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return Match(
        id=mid,
        utc_date=utc_date,
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


from worldcup_bot.__main__ import _match_is_over, poll_goals_job, poll_thread_goals_job


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


# ══════════════════════════════════════════════════════════════════════════════
# Over-match filter — the Egypt-Iran / stuck-IN_PLAY bug
# ══════════════════════════════════════════════════════════════════════════════


def _over_utc_date(hours: float = 5.0) -> str:
    """Return a UTC kickoff string that is `hours` hours in the past (default 5h > 4h ceiling)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _recent_utc_date(minutes: float = 30.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class TestMatchOverFilter:
    """Regression suite for the Egypt-Iran loop bug.

    Root cause: football-data.org stayed stuck at IN_PLAY long after FT, and
    the Reddit thread oscillated between N and N-1 goals → endless goal/disallowed
    spam.  The fix: hard-exclude any match whose kickoff is >4h ago regardless of
    API status, and prune stuck entries from live_scores + seen_scores.
    """

    @pytest.mark.asyncio
    async def test_stale_inplay_match_excluded_from_relevant(self, tmp_path):
        """IN_PLAY match whose kickoff was 5h ago is hard-excluded — no goal detection."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={})

        stored_state = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx.bot_data["live_scores"] = stored_state

        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0, utc_date=_over_utc_date())

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        # Pruned → save_scores called with match removed
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert "1" not in saved

    @pytest.mark.asyncio
    async def test_stale_match_pruned_from_live_scores_and_seen(self, tmp_path):
        """Over-match is evicted from scores, seen_api, and seen_thread in-memory dicts."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"1": {"home": 1, "away": 0}})
        ctx.bot_data["seen_scores"]["thread"]["1"] = {"home": 1, "away": 0}

        stored_state = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx.bot_data["live_scores"] = stored_state

        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0, utc_date=_over_utc_date())

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # Both in-memory dicts are cleared
        assert "1" not in ctx.bot_data["live_scores"]
        assert "1" not in ctx.bot_data["seen_scores"]["api"]
        assert "1" not in ctx.bot_data["seen_scores"]["thread"]

    @pytest.mark.asyncio
    async def test_egypt_iran_oscillation_produces_zero_sends(self, tmp_path):
        """Reproduce the exact Egypt-Iran loop: stuck IN_PLAY, thread flip-flops 1-0/0-0.

        With the fix, both ticks must produce zero sends (match excluded from relevant).
        """
        settings = _make_settings(tmp_path)
        ctx = _make_context(
            settings, _no_enrichment_scanner(),
            seen_api={"99": {"home": 0, "away": 1}},
        )
        ctx.bot_data["seen_scores"]["thread"]["99"] = {"home": 0, "away": 1}

        stored_state = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}
        ctx.bot_data["live_scores"] = stored_state

        stale_match = _make_match(
            99, "IN_PLAY",
            home_name="Egypt", away_name="Iran",
            home_tla="EGY", away_tla="IRN",
            home_score=0, away_score=1,
            utc_date=_over_utc_date(hours=20),  # kicked off 20h ago
        )

        for tick_score in [1, 0, 1, 0]:  # oscillating API/thread score
            stale_match.away_score = tick_score
            with (
                patch("worldcup_bot.__main__.make_client") as mock_client,
                patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
                patch("worldcup_bot.__main__.save_scores"),
            ):
                mock_client.return_value.get_all_matches.return_value = [stale_match]
                await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_recent_match_within_4h_goals_still_announced(self, tmp_path):
        """A genuinely live match (kickoff 30 min ago) still gets goal announcements."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"2": {"home": 0, "away": 0}})

        stored_state = {"2": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(
            2, "IN_PLAY",
            home_name="Brazil", away_name="Argentina",
            home_score=1, away_score=0,
            utc_date=_recent_utc_date(minutes=30),
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        assert "⚽" in ctx.bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_recently_finished_match_in_state_still_polled(self, tmp_path):
        """FINISHED match with kickoff 2h ago (within 4h ceiling) remains eligible
        for final-goal catch-up — existing behavior must not be broken."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"3": {"home": 1, "away": 0}})

        stored_state = {"3": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(
            3, "FINISHED",
            home_name="Germany", away_name="Japan",
            home_score=2, away_score=0,
            utc_date=_recent_utc_date(minutes=120),  # 2h ago → within 4h ceiling
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        # Final goal must still be announced
        ctx.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_over_match_finished_5h_ago_not_polled(self, tmp_path):
        """FINISHED match 5h past kickoff is excluded even though it's in scores."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"4": {"home": 2, "away": 1}})

        stored_state = {"4": {"home": 2, "away": 1, "status": "FINISHED"}}
        ctx.bot_data["live_scores"] = stored_state

        match = _make_match(
            4, "FINISHED",
            home_name="Spain", away_name="Portugal",
            home_score=3, away_score=1,
            utc_date=_over_utc_date(hours=5),
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_var_during_live_match_still_works(self, tmp_path):
        """A real VAR disallowed during a genuinely live match (recent kickoff) still fires."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"5": {"home": 2, "away": 0}})

        stored_state = {"5": {"home": 2, "away": 0, "status": "IN_PLAY"}}
        match = _make_match(
            5, "IN_PLAY",
            home_name="France", away_name="Belgium",
            home_score=1, away_score=0,
            utc_date=_recent_utc_date(minutes=45),
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "❌" in text or "VAR" in text


# ══════════════════════════════════════════════════════════════════════════════
# _match_is_over unit tests — boundary + safe defaults
# ══════════════════════════════════════════════════════════════════════════════


class TestMatchIsOverUnit:
    """Direct unit tests for the _match_is_over predicate.

    These guard the boundary behaviour and the safe fallback for bad utc_dates.
    """

    def test_invalid_utc_date_returns_false(self):
        """Unparseable utc_date → False (safe: keep match eligible rather than silence it).

        If the API sends a malformed date, the bot must not silently kill goal
        announcements for the match.  Exclusion requires a parseable kickoff.
        """
        match = _make_match(1, "IN_PLAY", utc_date="not-a-valid-date")
        assert not _match_is_over(match, datetime.now(timezone.utc))

    def test_empty_utc_date_returns_false(self):
        """Empty string utc_date → False (safe default via except Exception guard)."""
        match = _make_match(1, "IN_PLAY", utc_date="")
        assert not _match_is_over(match, datetime.now(timezone.utc))

    def test_3h59m_kickoff_is_not_over(self):
        """Match kicked off 3h59m ago is NOT over — comfortably inside the 4h ceiling.

        This covers the ET+penalties scenario: a match at 3h59m with PKs in
        progress must still be polled.  The ceiling is strictly >4h (not >=).
        """
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=239)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        match = _make_match(1, "IN_PLAY", utc_date=utc_date)
        assert not _match_is_over(match, datetime.now(timezone.utc))

    def test_4h2m_kickoff_is_over(self):
        """Match kicked off 4h2m ago IS over — clearly beyond the 4h wall-clock ceiling."""
        utc_date = (datetime.now(timezone.utc) - timedelta(hours=4, minutes=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        match = _make_match(1, "IN_PLAY", utc_date=utc_date)
        assert _match_is_over(match, datetime.now(timezone.utc))

    @pytest.mark.asyncio
    async def test_et_penalties_match_3h50m_still_announced(self, tmp_path):
        """Integration: match in ET+PKs 3h50m past kickoff still gets goals announced.

        A penalty shootout can start ~2h30m after kickoff; the decisive penalty
        might arrive at ~3h45m.  Must NOT be cut off by _match_is_over.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"10": {"home": 1, "away": 1}})

        stored_state = {"10": {"home": 1, "away": 1, "status": "IN_PLAY"}}
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=230)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        match = _make_match(
            10, "IN_PLAY",
            home_name="Argentina", away_name="Netherlands",
            home_score=2, away_score=1,
            utc_date=utc_date,
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value=stored_state),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        assert "⚽" in ctx.bot.send_message.call_args.kwargs["text"]


# ══════════════════════════════════════════════════════════════════════════════
# FINISHED two-tick eviction — B regression (Uruguay-Spain post-FT oscillation)
# ══════════════════════════════════════════════════════════════════════════════


class TestFinishedEviction:
    """Regression suite for the Uruguay-Spain post-FT oscillation bug.

    Root cause: football-data.org reports FINISHED, but the Reddit thread continued
    to flicker between goal/no-goal for ~4 minutes post-FT (within the <4h window
    that the Egypt-Iran fix did not catch).

    Fix: two-tick FINISHED eviction — keep match in live_scores for one FINISHED
    tick (catches late final goals), evict on the second tick with no new delta.
    """

    @pytest.mark.asyncio
    async def test_first_finished_tick_updates_status_no_eviction(self, tmp_path):
        """First FINISHED tick (was IN_PLAY): status updated, match stays in scores, no send."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"99": {"home": 0, "away": 1}})
        ctx.bot_data["seen_scores"]["thread"]["99"] = {"home": 0, "away": 1}
        ctx.bot_data["live_scores"] = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}

        match = _make_match(99, "FINISHED", home_name="Uruguay", away_name="Spain",
                            home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        assert "99" in ctx.bot_data["live_scores"]
        assert ctx.bot_data["live_scores"]["99"]["status"] == "FINISHED"
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_finished_tick_evicts_match(self, tmp_path):
        """Second FINISHED tick with no new delta -> match evicted from all live state."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"99": {"home": 0, "away": 1}})
        ctx.bot_data["seen_scores"]["thread"]["99"] = {"home": 0, "away": 1}
        ctx.bot_data["live_scores"] = {"99": {"home": 0, "away": 1, "status": "FINISHED"}}

        match = _make_match(99, "FINISHED", home_name="Uruguay", away_name="Spain",
                            home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        assert "99" not in ctx.bot_data["live_scores"]
        assert "99" not in ctx.bot_data["seen_scores"]["api"]
        assert "99" not in ctx.bot_data["seen_scores"]["thread"]
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_uruguay_spain_full_timeline_zero_post_ft_sends(self, tmp_path):
        """Full Uruguay-Spain B regression: two poll_goals ticks evict the match,
        then thread oscillation produces ZERO post-FT sends."""
        from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"99": {"home": 0, "away": 1}})
        ctx.bot_data["seen_scores"]["thread"]["99"] = {"home": 0, "away": 1}
        ctx.bot_data["live_scores"] = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}

        uru_match = _make_match(99, "FINISHED", home_name="Uruguay", away_name="Spain",
                                home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [uru_match]
            await poll_goals_job(ctx)

        assert ctx.bot_data["live_scores"]["99"]["status"] == "FINISHED"
        ctx.bot.send_message.assert_not_called()

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [uru_match]
            await poll_goals_job(ctx)

        assert "99" not in ctx.bot_data["live_scores"]
        ctx.bot.send_message.assert_not_called()

        def _osc_event(away_score: int) -> GoalEvent:
            return GoalEvent(
                minute_text="42", minute_sort=42.0, scorer="Baena", scoring_team="Spain",
                home_team="Uruguay", away_team="Spain",
                home_score=0, away_score=away_score,
                raw="Goal!", key=f"abc:0-{away_score}@42:baena",
            )

        thread_info = ThreadInfo(post_id="abc", title="URU vs ESP",
                                 permalink="/r/soccer/abc", created_utc=1.0)
        uru_live = _make_match(99, "IN_PLAY", home_name="Uruguay", away_name="Spain",
                               home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        for oscillating_events in ([], [_osc_event(1)]):
            result = MatchThreadResult(thread=thread_info, events=oscillating_events,
                                       home_tla="URU", away_tla="ESP")
            osc_scanner = MagicMock()
            osc_scanner.scan_live_matches = MagicMock(return_value=[result])
            ctx.bot_data["reddit_scanner"] = osc_scanner
            with (
                patch("worldcup_bot.__main__.make_client") as mock_client,
                patch("worldcup_bot.__main__.save_scores"),
                patch("worldcup_bot.__main__.save_clips"),
            ):
                mock_client.return_value.get_live_matches.return_value = [uru_live]
                await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_var_during_inplay_still_fires(self, tmp_path):
        """Real in-match VAR (IN_PLAY, was_already_finished=False) must still fire."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"99": {"home": 0, "away": 1}})
        ctx.bot_data["live_scores"] = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}

        match = _make_match(99, "IN_PLAY", home_name="Uruguay", away_name="Spain",
                            home_tla="URU", away_tla="ESP", home_score=0, away_score=0)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "VAR" in text or "anulado" in text

    @pytest.mark.asyncio
    async def test_final_goal_at_ft_still_notified(self, tmp_path):
        """Final goal on first FINISHED tick -> goal notified, match NOT evicted."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"99": {"home": 0, "away": 0}})
        ctx.bot_data["live_scores"] = {"99": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        match = _make_match(99, "FINISHED", home_name="Uruguay", away_name="Spain",
                            home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        assert "99" in ctx.bot_data["live_scores"]


# ══════════════════════════════════════════════════════════════════════════════
# Catch-up recovery from Reddit thread
# ══════════════════════════════════════════════════════════════════════════════


class TestCatchupRecovery:
    """Tests for _attempt_goal_recovery — proper per-goal sends vs neutral fallback."""

    def _make_recovery_scanner(self, permalink, selftext: str) -> MagicMock:
        scanner = MagicMock()
        scanner.find_thread_permalink = MagicMock(return_value=permalink)
        scanner.find_match_thread = MagicMock(return_value=None)
        scanner.get_thread_body = MagicMock(return_value=selftext)
        return scanner

    @pytest.mark.asyncio
    async def test_recovery_sends_proper_per_goal_not_neutral(self, tmp_path):
        """First seen at 0-2, thread has 2 matching events -> 2 goal sends (no neutral)."""
        from worldcup_bot.reddit.models import GoalEvent

        settings = _make_settings(tmp_path)
        scanner = self._make_recovery_scanner("/r/soccer/abc", "selftext")
        ctx = _make_context(settings, scanner)
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal",
                            home_tla="FRA", away_tla="SEN", home_score=0, away_score=2)
        events = [
            GoalEvent(minute_text="30", minute_sort=30.0, scorer="Mane",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=1, raw="Goal!", key="abc:0-1@30:mane"),
            GoalEvent(minute_text="65", minute_sort=65.0, scorer="Ndoye",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=2, raw="Goal!", key="abc:0-2@65:ndoye"),
        ]

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.parse_goal_events", return_value=events),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 2
        texts = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
        assert all("GOOOL" in t or "Gol" in t for t in texts)
        assert all("⚠️" not in t for t in texts)

    @pytest.mark.asyncio
    async def test_recovery_claims_seen_thread_for_dedup(self, tmp_path):
        """After recovery, seen_thread is updated to prevent poll_thread re-announcement."""
        from worldcup_bot.reddit.models import GoalEvent

        settings = _make_settings(tmp_path)
        scanner = self._make_recovery_scanner("/r/soccer/abc", "selftext")
        ctx = _make_context(settings, scanner)
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal",
                            home_tla="FRA", away_tla="SEN", home_score=0, away_score=2)
        events = [
            GoalEvent(minute_text="30", minute_sort=30.0, scorer="Mane",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=1, raw="Goal!", key="abc:0-1@30:mane"),
            GoalEvent(minute_text="65", minute_sort=65.0, scorer="Ndoye",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=2, raw="Goal!", key="abc:0-2@65:ndoye"),
        ]

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.parse_goal_events", return_value=events),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot_data["seen_scores"]["thread"]["1"] == {"home": 0, "away": 2}

    @pytest.mark.asyncio
    async def test_recovery_fallback_when_thread_unavailable(self, tmp_path):
        """No thread found -> falls back to neutral catch-up message."""
        settings = _make_settings(tmp_path)
        scanner = _no_enrichment_scanner()
        scanner.find_thread_permalink = MagicMock(return_value=None)
        scanner.find_match_thread = MagicMock(return_value=None)
        ctx = _make_context(settings, scanner)
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal",
                            home_tla="FRA", away_tla="SEN", home_score=0, away_score=2)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "perdí" in text

    @pytest.mark.asyncio
    async def test_recovery_fallback_when_event_cannot_be_matched(self, tmp_path):
        """Thread missing goal 2 event -> can't match target -> neutral fallback."""
        from worldcup_bot.reddit.models import GoalEvent

        settings = _make_settings(tmp_path)
        scanner = self._make_recovery_scanner("/r/soccer/abc", "selftext")
        ctx = _make_context(settings, scanner)
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal",
                            home_tla="FRA", away_tla="SEN", home_score=0, away_score=2)
        incomplete_events = [
            GoalEvent(minute_text="30", minute_sort=30.0, scorer="Mane",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=1, raw="Goal!", key="abc:0-1@30:mane"),
        ]

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.parse_goal_events", return_value=incomplete_events),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "perdí" in text


# ══════════════════════════════════════════════════════════════════════════════
# POSTPONED / SUSPENDED eviction
# ══════════════════════════════════════════════════════════════════════════════


class TestPostponedEviction:
    """Matches seeded at 0-0 that become POSTPONED/SUSPENDED must be evicted promptly."""

    @pytest.mark.asyncio
    async def test_postponed_match_seeded_is_evicted(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"20": {"home": 0, "away": 0}})
        ctx.bot_data["seen_scores"]["thread"]["20"] = {"home": 0, "away": 0}
        ctx.bot_data["live_scores"] = {"20": {"home": 0, "away": 0, "status": "IN_PLAY"}}

        match = _make_match(20, "POSTPONED", home_score=None, away_score=None)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert "20" not in ctx.bot_data["live_scores"]
        assert "20" not in ctx.bot_data["seen_scores"]["api"]
        assert "20" not in ctx.bot_data["seen_scores"]["thread"]
        ctx.bot.send_message.assert_not_called()
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_suspended_match_seeded_is_evicted(self, tmp_path):
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"21": {"home": 0, "away": 0}})
        ctx.bot_data["seen_scores"]["thread"]["21"] = {"home": 0, "away": 0}
        ctx.bot_data["live_scores"] = {"21": {"home": 0, "away": 0, "status": "IN_PLAY"}}

        match = _make_match(21, "SUSPENDED", home_score=None, away_score=None)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert "21" not in ctx.bot_data["live_scores"]
        assert "21" not in ctx.bot_data["seen_scores"]["api"]
        assert "21" not in ctx.bot_data["seen_scores"]["thread"]
        ctx.bot.send_message.assert_not_called()
        mock_save.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Eviction edge cases: coexistence with age-prune + dedup loop prevention
# ══════════════════════════════════════════════════════════════════════════════


class TestEvictionEdgeCases:
    """Edge-case coverage for eviction coexistence and post-send loop prevention."""

    @pytest.mark.asyncio
    async def test_var_flip_oscillation_post_ft_zero_sends(self, tmp_path):
        """Proper B regression: realistic VAR-flip (0-1→0-0→0-1) post-FT sends nothing.

        The existing test uses []→[0-1] oscillation which never fires regardless of eviction
        (reconcile(seen=0-1, ann=0-1, 0, 1) = step-2 no-change).  This test uses the real
        bug pattern: [0-0]→[0-1].  Without two-tick eviction:
          tick 3: reconcile(seen=0-1, ann=0-1, 0, 0) → disallowed → SENDS ❌
          tick 4: reconcile(seen=0-0, ann=0-0, 0, 1) → GOOOL → SENDS ⚽
        With the fix: match is evicted before thread ticks run → zero sends.
        """
        from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"99": {"home": 0, "away": 1}})
        ctx.bot_data["seen_scores"]["thread"]["99"] = {"home": 0, "away": 1}
        ctx.bot_data["live_scores"] = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}

        uru_match = _make_match(99, "FINISHED", home_name="Uruguay", away_name="Spain",
                                home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        # Tick 1: IN_PLAY → FINISHED, no delta → status updated, no eviction yet
        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [uru_match]
            await poll_goals_job(ctx)
        assert ctx.bot_data["live_scores"]["99"]["status"] == "FINISHED"

        # Tick 2: FINISHED, was_already_finished=True → evicted
        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [uru_match]
            await poll_goals_job(ctx)
        assert "99" not in ctx.bot_data["live_scores"]

        def _osc_event(away_score: int) -> GoalEvent:
            return GoalEvent(
                minute_text="42", minute_sort=42.0, scorer="Baena", scoring_team="Spain",
                home_team="Uruguay", away_team="Spain",
                home_score=0, away_score=away_score,
                raw="Goal!", key=f"abc:0-{away_score}@42:baena",
            )

        thread_info = ThreadInfo(post_id="abc", title="URU vs ESP",
                                 permalink="/r/soccer/abc", created_utc=1.0)
        uru_live = _make_match(99, "IN_PLAY", home_name="Uruguay", away_name="Spain",
                               home_tla="URU", away_tla="ESP", home_score=0, away_score=1)

        # Realistic VAR oscillation: [0-0] (VAR) then [0-1] (restored).
        # Without the fix, tick-3 reconcile(seen=0-1,ann=0-1,0,0) → disallowed;
        # tick-4 reconcile(seen=0-0,ann=0-0,0,1) → GOOOL.  With the fix: match is
        # evicted so scores.get("99") is None → both ticks skipped → zero sends.
        for oscillating_events in ([_osc_event(0)], [_osc_event(1)]):
            result = MatchThreadResult(thread=thread_info, events=oscillating_events,
                                       home_tla="URU", away_tla="ESP")
            osc_scanner = MagicMock()
            osc_scanner.scan_live_matches = MagicMock(return_value=[result])
            ctx.bot_data["reddit_scanner"] = osc_scanner
            with (
                patch("worldcup_bot.__main__.make_client") as mock_client,
                patch("worldcup_bot.__main__.save_scores"),
                patch("worldcup_bot.__main__.save_clips"),
            ):
                mock_client.return_value.get_live_matches.return_value = [uru_live]
                await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_age_prune_and_finished_eviction_no_crash(self, tmp_path):
        """Match >4h old AND FINISHED: age prune removes it first; two-tick logic never runs; no crash.

        The >4h prune fires before the relevant filter so the match is already gone from
        live_scores before the FINISHED two-tick logic could see it.  Both eviction paths
        coexist safely.
        """
        old_date = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, _no_enrichment_scanner(), seen_api={"50": {"home": 1, "away": 0}})
        ctx.bot_data["seen_scores"]["thread"]["50"] = {"home": 1, "away": 0}
        ctx.bot_data["live_scores"] = {"50": {"home": 1, "away": 0, "status": "FINISHED"}}

        match = _make_match(50, "FINISHED", home_score=1, away_score=0, utc_date=old_date)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)  # must not crash

        assert "50" not in ctx.bot_data["live_scores"]
        assert "50" not in ctx.bot_data["seen_scores"]["api"]
        assert "50" not in ctx.bot_data["seen_scores"]["thread"]
        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_dedup_no_resend_on_next_thread_tick(self, tmp_path):
        """After recovery claims seen_thread, next poll_thread_goals_job tick with same score emits nothing.

        reconcile(seen={0,2}, ann={0,2}, 0, 2) hits step-2 (new==seen) → ([], ...) → no send.
        """
        from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo

        settings = _make_settings(tmp_path)
        scanner = MagicMock()
        scanner.find_thread_permalink = MagicMock(return_value="/r/soccer/abc")
        scanner.find_match_thread = MagicMock(return_value=None)
        scanner.get_thread_body = MagicMock(return_value="selftext")
        ctx = _make_context(settings, scanner)
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal",
                            home_tla="FRA", away_tla="SEN", home_score=0, away_score=2)
        events = [
            GoalEvent(minute_text="30", minute_sort=30.0, scorer="Mane",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=1, raw="Goal!", key="abc:0-1@30:mane"),
            GoalEvent(minute_text="65", minute_sort=65.0, scorer="Ndoye",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=2, raw="Goal!", key="abc:0-2@65:ndoye"),
        ]

        # Step 1: recovery → 2 proper sends, seen_thread["1"] claimed at {home:0, away:2}
        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.parse_goal_events", return_value=events),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 2
        assert ctx.bot_data["seen_scores"]["thread"]["1"] == {"home": 0, "away": 2}
        ctx.bot.send_message.reset_mock()

        # Step 2: poll_thread_goals_job with same thread score → reconcile(seen=0-2, ann=0-2, 0, 2)
        # step-2 no-change → ([], ...) → zero sends
        thread_result = MatchThreadResult(
            thread=ThreadInfo(post_id="abc", title="FRA vs SEN",
                              permalink="/r/soccer/abc", created_utc=1.0),
            events=events,
            home_tla="FRA",
            away_tla="SEN",
        )
        thread_scanner = MagicMock()
        thread_scanner.scan_live_matches = MagicMock(return_value=[thread_result])
        ctx.bot_data["reddit_scanner"] = thread_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_neutral_fallback_no_loop_on_next_thread_tick(self, tmp_path):
        """Neutral fallback does not loop: next poll_thread tick with same score → zero sends.

        After neutral send, seen_thread is NOT claimed.  But reconcile(None, {0,2}, 0, 2)
        returns [] because _ahead(equal, equal) is False.  On subsequent ticks seen_thread
        is set to {0,2} and step-2 fires.  Never resends.
        """
        from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo

        settings = _make_settings(tmp_path)
        scanner = _no_enrichment_scanner()
        scanner.find_thread_permalink = MagicMock(return_value=None)
        scanner.find_match_thread = MagicMock(return_value=None)
        ctx = _make_context(settings, scanner)
        ctx.bot_data["clip_store"] = {}
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        match = _make_match(1, "IN_PLAY", home_name="France", away_name="Senegal",
                            home_tla="FRA", away_tla="SEN", home_score=0, away_score=2)

        # Step 1: poll_goals_job first-seen at 0-2 → no thread → 1 neutral send
        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        assert "perdí" in ctx.bot.send_message.call_args.kwargs["text"]
        assert "1" not in ctx.bot_data["seen_scores"]["thread"]  # neutral path never claims seen_thread
        ctx.bot.send_message.reset_mock()

        # Step 2: poll_thread_goals_job with same score → reconcile(seen=None, ann={0,2}, 0, 2)
        # _ahead({0,2}, {0,2}) is False → returns ([], ...) → zero sends
        thread_events = [
            GoalEvent(minute_text="30", minute_sort=30.0, scorer="Mane",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=1, raw="Goal!", key="abc:0-1@30:mane"),
            GoalEvent(minute_text="65", minute_sort=65.0, scorer="Ndoye",
                      scoring_team="Senegal", home_team="France", away_team="Senegal",
                      home_score=0, away_score=2, raw="Goal!", key="abc:0-2@65:ndoye"),
        ]
        thread_result = MatchThreadResult(
            thread=ThreadInfo(post_id="abc", title="FRA vs SEN",
                              permalink="/r/soccer/abc", created_utc=1.0),
            events=thread_events,
            home_tla="FRA",
            away_tla="SEN",
        )
        thread_scanner = MagicMock()
        thread_scanner.scan_live_matches = MagicMock(return_value=[thread_result])
        ctx.bot_data["reddit_scanner"] = thread_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
