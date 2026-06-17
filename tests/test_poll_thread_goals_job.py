"""Tests for poll_thread_goals_job — Reddit-thread-based early goal detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.config import Settings
from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_match(
    mid: int = 1,
    status: str = "IN_PLAY",
    home_name: str = "England",
    away_name: str = "Senegal",
    home_tla: str = "ENG",
    away_tla: str = "SEN",
    home_score: int | None = 2,
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


def _make_goal_event(
    scorer: str = "Harry Kane",
    scoring_team: str = "England",
    home_score: int = 2,
    away_score: int = 0,
    minute_text: str = "60",
    minute_sort: float = 60.0,
    home_team: str = "England",
    away_team: str = "Senegal",
    post_id: str = "abc123",
) -> GoalEvent:
    return GoalEvent(
        minute_text=minute_text,
        minute_sort=minute_sort,
        scorer=scorer,
        scoring_team=scoring_team,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        raw=f"**{minute_text}'** ⚽ Goal! {home_team} {home_score}, {away_team} {away_score}. {scorer}",
        key=f"{post_id}:{home_score}-{away_score}@{minute_text}:{scorer.lower()}",
    )


def _make_thread_result(
    home_tla: str = "ENG",
    away_tla: str = "SEN",
    events: list | None = None,
) -> MatchThreadResult:
    thread = ThreadInfo(
        post_id="abc123",
        title=f"Match Thread: {home_tla} vs {away_tla}",
        permalink="/r/soccer/comments/abc123",
        created_utc=1718640000.0,
    )
    return MatchThreadResult(
        thread=thread,
        events=events or [],
        home_tla=home_tla,
        away_tla=away_tla,
    )


def _make_context(settings: Settings, live_scores: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "reddit_scanner": None,
        "live_scores": live_scores if live_scores is not None else {},
        "clip_store": {},
    }
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
    return ctx


from worldcup_bot.__main__ import poll_thread_goals_job


# ══════════════════════════════════════════════════════════════════════════════
# Core notification logic
# ══════════════════════════════════════════════════════════════════════════════


class TestPollThreadGoalsJob:
    @pytest.mark.asyncio
    async def test_seeded_match_with_new_goal_notified(self, tmp_path):
        """Match seeded at 1-0; thread shows home 2 → one goal notified with event scorer."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0)

        live_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)

        event = _make_goal_event(
            scorer="Harry Kane", scoring_team="England",
            home_score=2, away_score=0, minute_text="60", minute_sort=60.0,
        )
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in text

        # Shared score updated to thread score
        assert live_scores["1"]["home"] == 2
        mock_save.assert_called_once()

        # Clip-store entry registered
        clips = ctx.bot_data.get("clip_store", {})
        assert len(clips) == 1
        entry = next(iter(clips.values()))
        assert entry["status"] == "searching"
        assert entry["scorer"] == "Harry Kane"

    @pytest.mark.asyncio
    async def test_scorer_from_thread_event_not_openai(self, tmp_path):
        """Thread path uses event.scorer directly — no enrichment/OpenAI call."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        live_scores = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)

        event = _make_goal_event(
            scorer="Bellingham", scoring_team="England",
            home_score=1, away_score=0, minute_text="23",
        )
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__._enrich_scorer") as mock_enrich,
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        # The thread path must NOT call _enrich_scorer
        mock_enrich.assert_not_called()
        ctx.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_unseeded_match_skipped(self, tmp_path):
        """Match not yet in shared scores → skip (let football-data seed first)."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        live_scores = {}  # not seeded
        ctx = _make_context(settings, live_scores=live_scores)

        event = _make_goal_event(scorer="Kane", scoring_team="England", home_score=1, away_score=0)
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_same_score_as_stored_no_notify(self, tmp_path):
        """Thread score == stored → no notification."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        live_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)

        event = _make_goal_event(scorer="Kane", scoring_team="England", home_score=1, away_score=0)
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_live_matches_returns_early(self, tmp_path):
        """No IN_PLAY/PAUSED matches → returns immediately without scanning."""
        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, live_scores={})

        mock_scanner = MagicMock()
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with patch("worldcup_bot.__main__.make_client") as mock_client:
            mock_client.return_value.get_live_matches.return_value = []
            await poll_thread_goals_job(ctx)

        mock_scanner.scan_live_matches.assert_not_called()
        ctx.bot.send_message.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Deduplication with football-data poll
# ══════════════════════════════════════════════════════════════════════════════


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_dedup_football_data_after_thread_notify(self, tmp_path):
        """After thread notifies 2-0, diff_scores at 2-0 returns [] (no second message)."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0)

        live_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)

        event = _make_goal_event(scorer="Kane", scoring_team="England", home_score=2, away_score=0)
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1

        # Now simulate football-data also reporting 2-0 — diff_scores should return []
        from worldcup_bot.reddit.score_state import diff_scores
        stored_after_thread = live_scores["1"]
        assert stored_after_thread["home"] == 2
        assert stored_after_thread["away"] == 0
        result_diff = diff_scores(stored_after_thread, match)
        assert result_diff == []

    @pytest.mark.asyncio
    async def test_shared_dict_mutation_prevents_double_notify(self, tmp_path):
        """Both jobs mutate the SAME dict — football-data poll sees updated score."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0)

        # Shared scores starts at 1-0
        shared_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=shared_scores)

        event = _make_goal_event(scorer="Kane", scoring_team="England", home_score=2, away_score=0)
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        # Thread updated shared_scores to 2-0
        assert shared_scores["1"]["home"] == 2

        # poll_goals_job would now see stored == 2-0 == current → no delta → no message
        from worldcup_bot.reddit.score_state import diff_scores
        deltas = diff_scores(shared_scores["1"], match)
        assert deltas == []


# ══════════════════════════════════════════════════════════════════════════════
# Error handling / resilience
# ══════════════════════════════════════════════════════════════════════════════


class TestResilience:
    @pytest.mark.asyncio
    async def test_scanner_error_never_raises(self, tmp_path):
        """scan_live_matches exception → job swallows and does not re-raise."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY")

        live_scores = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)

        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(side_effect=RuntimeError("Reddit 503"))
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with patch("worldcup_bot.__main__.make_client") as mock_client:
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)  # must not raise

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_error_does_not_raise(self, tmp_path):
        """Football-data API error → job returns early without crashing."""
        from worldcup_bot.api.client import FootballAPIError

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings, live_scores={})

        with patch("worldcup_bot.__main__.make_client") as mock_client:
            mock_client.return_value.get_live_matches.side_effect = FootballAPIError(
                429, "rate limit"
            )
            await poll_thread_goals_job(ctx)  # must not raise

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_thread_events_no_notify(self, tmp_path):
        """Thread result with no events → nothing to notify."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=1, away_score=0)

        live_scores = {"1": {"home": 0, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)

        result = _make_thread_result("ENG", "SEN", events=[])  # no events
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Job registration
# ══════════════════════════════════════════════════════════════════════════════


class TestJobRegistration:
    def test_poll_thread_goals_registered_in_main(self, tmp_path):
        """main() registers poll_thread_goals_job with interval=25."""
        import inspect
        import worldcup_bot.__main__ as main_mod

        source = inspect.getsource(main_mod.main)
        assert "poll_thread_goals" in source
        assert "poll_thread_goals_job" in source
