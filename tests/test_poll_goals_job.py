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


from worldcup_bot.__main__ import _match_is_over, poll_goals_job


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
