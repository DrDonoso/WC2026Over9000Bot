"""Tests for poll_thread_goals_job — Reddit-thread-based early goal detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _make_context(settings: Settings, live_scores: dict | None = None, seen_thread: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "reddit_scanner": None,
        "live_scores": live_scores if live_scores is not None else {},
        "clip_store": {},
        "seen_scores": {"api": {}, "thread": seen_thread or {}},
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
        # Thread was last tracking at 1-0; now sees 2-0 → should notify
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 1, "away": 0}})

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
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 0, "away": 0}})

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
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 1, "away": 0}})

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
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 1, "away": 0}})

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
        ctx = _make_context(settings, live_scores=shared_scores, seen_thread={"1": {"home": 1, "away": 0}})

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


# ══════════════════════════════════════════════════════════════════════════════
# Screenshot scenario & reconcile integration (the flip-flop bug)
# ══════════════════════════════════════════════════════════════════════════════


class TestFlipFlopFix:
    """Regression tests for the England 4-2 Croatia flip-flop screenshot bug.

    Setup mirrors production reality:
      - Both sources seeded earlier. api_seen=thread_seen=2-2, announced=2-2.
      - api detected England's 3rd goal → announced updated to 3-2, api_seen=3-2.
      - thread_seen still at 2-2 (thread was behind when api moved).
      - thread now sees 4-2 (Rashford 85') → ONE goal notification.
      - api keeps reporting 3-2 (lagging) → ZERO disallowed.
      - api eventually catches up to 4-2 → ZERO duplicate goal.
    """

    @pytest.mark.asyncio
    async def test_screenshot_scenario_one_goal_zero_disallowed(self, tmp_path):
        """THE BUG: thread 4-2 while api lags at 3-2 must NOT produce flip-flop."""
        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="England", away_name="Croatia",
            home_tla="ENG", away_tla="CRO",
            home_score=4, away_score=2,
        )

        # announced=3-2 (api already moved here); thread_seen still at 2-2
        live_scores = {"1": {"home": 3, "away": 2, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 2, "away": 2}})
        # Also put api_seen at 3-2 so that the api job leg works in isolation
        ctx.bot_data["seen_scores"]["api"]["1"] = {"home": 3, "away": 2}

        rashford = _make_goal_event(
            scorer="Rashford", scoring_team="England",
            home_score=4, away_score=2, minute_text="85", minute_sort=85.0,
        )
        thread_result = _make_thread_result("ENG", "CRO", [rashford])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[thread_result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            # Step 1: thread reports 4-2 (Rashford)
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1, "Exactly ONE goal notification"
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in text
        assert "Rashford" in text
        assert live_scores["1"]["home"] == 4, "Announced updated to 4-2"

        # Step 2: api repeatedly reports 3-2 — must produce ZERO disallowed
        from worldcup_bot.__main__ import poll_goals_job

        api_match_32 = _make_match(
            1, "IN_PLAY",
            home_name="England", away_name="Croatia",
            home_tla="ENG", away_tla="CRO",
            home_score=3, away_score=2,
        )

        ctx.bot.send_message.reset_mock()

        for _ in range(3):
            with (
                patch("worldcup_bot.__main__.make_client") as mock_client,
                patch("worldcup_bot.__main__.save_scores"),
                patch("worldcup_bot.__main__.save_clips"),
            ):
                mock_client.return_value.get_all_matches.return_value = [api_match_32]
                await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, "ZERO disallowed — api lag must not flip-flop"

        # Step 3: api catches up to 4-2 — must produce ZERO duplicate goal
        api_match_42 = _make_match(
            1, "IN_PLAY",
            home_name="England", away_name="Croatia",
            home_tla="ENG", away_tla="CRO",
            home_score=4, away_score=2,
        )
        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [api_match_42]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, "ZERO duplicate goal on api catch-up"

    @pytest.mark.asyncio
    async def test_real_var_thread_goal_then_disallowed(self, tmp_path):
        """Thread sees 4-2 then 3-2 (VAR) → one goal + one disallowed. Api catch-up adds nothing."""
        settings = _make_settings(tmp_path)

        # Initial state: all at 3-2
        live_scores = {"1": {"home": 3, "away": 2, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 3, "away": 2}})
        ctx.bot_data["seen_scores"]["api"]["1"] = {"home": 3, "away": 2}

        # Tick 1: thread sees 4-2 (Rashford goal)
        goal_event = _make_goal_event(
            scorer="Rashford", scoring_team="England",
            home_score=4, away_score=2, minute_text="85",
        )
        match_42 = _make_match(1, "IN_PLAY", home_name="England", away_name="Croatia",
                               home_tla="ENG", away_tla="CRO", home_score=4, away_score=2)
        result_42 = _make_thread_result("ENG", "CRO", [goal_event])

        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result_42])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match_42]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        goal_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in goal_text
        assert live_scores["1"]["home"] == 4

        ctx.bot.send_message.reset_mock()

        # Tick 2: thread sees 3-2 (VAR disallowed — thread's own score dropped)
        match_32 = _make_match(1, "IN_PLAY", home_name="England", away_name="Croatia",
                               home_tla="ENG", away_tla="CRO", home_score=3, away_score=2)
        result_32 = _make_thread_result("ENG", "CRO", [
            _make_goal_event(scorer="Kane", scoring_team="England",
                             home_score=3, away_score=2, minute_text="60"),
        ])
        mock_scanner.scan_live_matches = MagicMock(return_value=[result_32])

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match_32]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1, "One disallowed notification"
        disallowed_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "VAR" in disallowed_text or "❌" in disallowed_text
        assert live_scores["1"]["home"] == 3, "Announced corrected to 3-2"

        ctx.bot.send_message.reset_mock()

        # Tick 3: api catches up to 3-2 — must add nothing
        from worldcup_bot.__main__ import poll_goals_job
        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match_32]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, "Api catch-up to 3-2 adds nothing"

    @pytest.mark.asyncio
    async def test_restart_safety_no_replay(self, tmp_path):
        """After restart (seen=None), first tick at current score announces nothing."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=4, away_score=2)

        # On restart: announced loaded from disk at 4-2, thread_seen is None (in-memory cleared)
        live_scores = {"1": {"home": 4, "away": 2, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread=None)
        # No seen_thread entry at all → simulates restart

        event = _make_goal_event(scorer="Rashford", scoring_team="England",
                                 home_score=4, away_score=2, minute_text="85")
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


# ══════════════════════════════════════════════════════════════════════════════
# Bug 1 regression — cross-job race: goal announced exactly once
# ══════════════════════════════════════════════════════════════════════════════


class TestCrossJobRace:
    """Regression tests for Bug 1: poll_goals_job and poll_thread_goals_job both see
    the same new score while the announced is still the old value.  Without the
    goal_lock the slow enrichment/send await yields control and the other job
    re-reconciles from the stale announced → duplicate.  With the lock only the
    first claimer updates announced; the second finds no delta.
    """

    @pytest.mark.asyncio
    async def test_concurrent_goal_announced_exactly_once(self, tmp_path):
        """Both jobs see Spain 5-0 while announced=4-0, run concurrently via gather.
        The lock must ensure only ONE send_message call despite the race.
        """
        import asyncio as _asyncio

        from worldcup_bot.__main__ import poll_goals_job, poll_thread_goals_job

        settings = _make_settings(tmp_path)
        match = _make_match(
            5, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=5, away_score=0,
        )

        # Both jobs share the same bot_data dict (same lock, same live_scores).
        shared_scores = {"5": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        shared_bot_data = {
            "settings": settings,
            "live_scores": shared_scores,
            "clip_store": {},
            "seen_scores": {
                "api": {"5": {"home": 4, "away": 0}},
                "thread": {"5": {"home": 4, "away": 0}},
            },
        }

        goal_event = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=5, away_score=0, minute_text="78",
            home_team="Spain", away_team="Saudi Arabia",
        )
        thread_result = _make_thread_result("ESP", "SAU", [goal_event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[thread_result])
        mock_scanner.find_match_thread = MagicMock(return_value=None)
        shared_bot_data["reddit_scanner"] = mock_scanner

        send_count = 0

        async def counting_send(**kwargs):
            nonlocal send_count
            await _asyncio.sleep(0)  # yield — lets the other coroutine interleave
            send_count += 1
            return MagicMock(message_id=99)

        ctx_api = MagicMock()
        ctx_api.bot_data = shared_bot_data
        ctx_api.bot.send_message = counting_send
        ctx_api.bot.edit_message_text = AsyncMock()

        ctx_thread = MagicMock()
        ctx_thread.bot_data = shared_bot_data
        ctx_thread.bot.send_message = counting_send
        ctx_thread.bot.edit_message_text = AsyncMock()

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            mock_client.return_value.get_live_matches.return_value = [match]

            await _asyncio.gather(
                poll_goals_job(ctx_api),
                poll_thread_goals_job(ctx_thread),
            )

        assert send_count == 1, (
            f"Expected exactly 1 goal notification, got {send_count} — "
            "Bug 1: concurrent jobs must not duplicate the same goal"
        )

    @pytest.mark.asyncio
    async def test_sequential_api_then_thread_no_duplicate(self, tmp_path):
        """API job claims 5-0 first; thread job then sees announced=5-0 → no second send."""
        from worldcup_bot.__main__ import poll_goals_job, poll_thread_goals_job

        settings = _make_settings(tmp_path)
        match = _make_match(
            5, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=5, away_score=0,
        )

        shared_scores = {"5": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        shared_bot_data = {
            "settings": settings,
            "live_scores": shared_scores,
            "clip_store": {},
            "seen_scores": {
                "api": {"5": {"home": 4, "away": 0}},
                "thread": {"5": {"home": 4, "away": 0}},
            },
        }

        goal_event = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=5, away_score=0, minute_text="78",
            home_team="Spain", away_team="Saudi Arabia",
        )
        thread_result = _make_thread_result("ESP", "SAU", [goal_event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[thread_result])
        mock_scanner.find_match_thread = MagicMock(return_value=None)
        shared_bot_data["reddit_scanner"] = mock_scanner

        ctx_api = MagicMock()
        ctx_api.bot_data = shared_bot_data
        ctx_api.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        ctx_api.bot.edit_message_text = AsyncMock()

        ctx_thread = MagicMock()
        ctx_thread.bot_data = shared_bot_data
        ctx_thread.bot.send_message = AsyncMock(return_value=MagicMock(message_id=2))
        ctx_thread.bot.edit_message_text = AsyncMock()

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_all_matches.return_value = [match]
            mock_client.return_value.get_live_matches.return_value = [match]

            # API runs first and claims 5-0
            await poll_goals_job(ctx_api)
            # Thread then sees announced=5-0 → no delta
            await poll_thread_goals_job(ctx_thread)

        total_sends = (
            ctx_api.bot.send_message.call_count
            + ctx_thread.bot.send_message.call_count
        )
        assert total_sends == 1, (
            f"Expected 1 total notification, got {total_sends}"
        )
        # Shared announced score must be 5-0
        assert shared_scores["5"]["home"] == 5


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2 regression — scorer back-fill on already-announced scorer-less goal
# ══════════════════════════════════════════════════════════════════════════════


class TestScorerBackfill:
    """Regression tests for Bug 2: API announces a goal with scorer=None (enrichment
    failed or thread not ready).  When the thread later reports the scorer, the job
    must edit the original message and update the clip-store entry so the clip search
    can proceed.
    """

    def _make_scorer_less_entry(self, match_id, scoring_team, home_score, away_score,
                                message_id, home_name, away_name, home_tla, away_tla):
        from worldcup_bot.reddit.clip_store import goal_token, add_entry
        data = {}
        key = f"{match_id}:{scoring_team}:{home_score}-{away_score}"
        tok = goal_token(key)
        add_entry(
            data,
            token=tok,
            chat_id="-100999",
            message_id=message_id,
            home_name=home_name,
            away_name=away_name,
            home_tla=home_tla,
            away_tla=away_tla,
            home_score=home_score,
            away_score=away_score,
            scoring_team=scoring_team,
            scorer=None,
            minute=None,
        )
        return data, tok

    @pytest.mark.asyncio
    async def test_backfill_edits_message_and_sets_scorer(self, tmp_path):
        """Thread provides scorer for a 4-0 goal that API announced with scorer=None.
        Message must be edited with scorer line; clip-store entry scorer must be set.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
        )

        clip_data, tok = self._make_scorer_less_entry(
            match_id=1, scoring_team="Spain",
            home_score=4, away_score=0,
            message_id=42,
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
        )

        # announced=4-0, thread_seen=4-0 → no new deltas, but backfill should run
        live_scores = {"1": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 4, "away": 0}})
        ctx.bot_data["clip_store"] = clip_data
        ctx.bot.edit_message_text = AsyncMock()

        event = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=4, away_score=0, minute_text="67",
        )
        result = _make_thread_result("ESP", "SAU", [event])
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

        # No new goal message (score already announced)
        ctx.bot.send_message.assert_not_called()

        # edit_message_text must have been called to add the scorer line
        ctx.bot.edit_message_text.assert_called_once()
        edit_kwargs = ctx.bot.edit_message_text.call_args.kwargs
        assert edit_kwargs["message_id"] == 42
        assert "Morata" in edit_kwargs["text"]
        assert "🎯" in edit_kwargs["text"]

        # Clip-store entry scorer updated
        assert clip_data[tok]["scorer"] == "Morata"

    @pytest.mark.asyncio
    async def test_backfill_idempotent_no_double_edit(self, tmp_path):
        """Running the job twice after backfill: edit_message_text called only once."""
        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
        )

        clip_data, tok = self._make_scorer_less_entry(
            match_id=1, scoring_team="Spain",
            home_score=4, away_score=0,
            message_id=42,
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
        )

        live_scores = {"1": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 4, "away": 0}})
        ctx.bot_data["clip_store"] = clip_data
        ctx.bot.edit_message_text = AsyncMock()

        event = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=4, away_score=0, minute_text="67",
        )
        result = _make_thread_result("ESP", "SAU", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            # First run: backfills scorer, edits message
            await poll_thread_goals_job(ctx)
            # Second run: scorer already set → no second edit
            await poll_thread_goals_job(ctx)

        assert ctx.bot.edit_message_text.call_count == 1, (
            "edit_message_text must be called exactly once — backfill must be idempotent"
        )

    @pytest.mark.asyncio
    async def test_no_backfill_when_scorer_already_known(self, tmp_path):
        """If clip-store entry already has a scorer, backfill must not edit the message."""
        from worldcup_bot.reddit.clip_store import goal_token, add_entry
        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
        )

        clip_data: dict = {}
        tok = goal_token("1:Spain:4-0")
        add_entry(
            clip_data, token=tok,
            chat_id="-100999", message_id=42,
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
            scoring_team="Spain",
            scorer="Morata",  # already known
            minute="67",
        )

        live_scores = {"1": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 4, "away": 0}})
        ctx.bot_data["clip_store"] = clip_data
        ctx.bot.edit_message_text = AsyncMock()

        event = _make_goal_event(scorer="Morata", scoring_team="Spain", home_score=4, away_score=0)
        result = _make_thread_result("ESP", "SAU", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfill_preserves_keyboard_when_clip_ready(self, tmp_path):
        """When the clip-store entry is already 'ready' (Ver gol keyboard attached),
        the backfill must pass reply_markup=build_goal_keyboard(tok) so the keyboard
        is preserved after editMessageText — not silently cleared by Telegram.
        """
        from worldcup_bot.reddit.clip_store import goal_token, add_entry
        from worldcup_bot.reddit.notifier import build_goal_keyboard

        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
        )

        clip_data: dict = {}
        tok = goal_token("1:Spain:4-0")
        add_entry(
            clip_data, token=tok,
            chat_id="-100999", message_id=77,
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
            scoring_team="Spain",
            scorer=None,
            minute=None,
        )
        # Simulate clip already found and keyboard attached
        clip_data[tok]["status"] = "ready"
        clip_data[tok]["clip_path"] = "/data/clips/abc.mp4"

        live_scores = {"1": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 4, "away": 0}})
        ctx.bot_data["clip_store"] = clip_data
        ctx.bot.edit_message_text = AsyncMock()

        event = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=4, away_score=0, minute_text="67",
        )
        result = _make_thread_result("ESP", "SAU", [event])
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

        ctx.bot.edit_message_text.assert_called_once()
        edit_kwargs = ctx.bot.edit_message_text.call_args.kwargs
        assert edit_kwargs["message_id"] == 77
        # reply_markup must be the Ver gol keyboard (not None)
        expected_markup = build_goal_keyboard(tok)
        assert edit_kwargs.get("reply_markup") == expected_markup, (
            "Backfill must re-attach the Ver gol keyboard when clip status is 'ready'"
        )

    @pytest.mark.asyncio
    async def test_backfill_no_keyboard_when_clip_not_ready(self, tmp_path):
        """When the clip-store entry is still 'searching' (no clip yet, no keyboard),
        the backfill must NOT include reply_markup in the edit kwargs — omitting the key
        entirely preserves any existing Telegram markup and avoids accidentally clearing it
        with reply_markup=null.
        """
        from worldcup_bot.reddit.clip_store import goal_token, add_entry

        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
        )

        clip_data: dict = {}
        tok = goal_token("1:Spain:4-0")
        add_entry(
            clip_data, token=tok,
            chat_id="-100999", message_id=88,
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
            scoring_team="Spain",
            scorer=None,
            minute=None,
        )
        # Entry still searching — no clip, no keyboard yet
        assert clip_data[tok]["status"] == "searching"

        live_scores = {"1": {"home": 4, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 4, "away": 0}})
        ctx.bot_data["clip_store"] = clip_data
        ctx.bot.edit_message_text = AsyncMock()

        event = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=4, away_score=0, minute_text="67",
        )
        result = _make_thread_result("ESP", "SAU", [event])
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

        ctx.bot.edit_message_text.assert_called_once()
        edit_kwargs = ctx.bot.edit_message_text.call_args.kwargs
        assert edit_kwargs["message_id"] == 88
        # reply_markup must be ABSENT (not passed at all) — passing None would send
        # reply_markup=null to Telegram which removes any existing keyboard.
        assert "reply_markup" not in edit_kwargs, (
            "Backfill must NOT include reply_markup when clip is not yet ready "
            "(omitting the key preserves existing Telegram markup)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Bug 3 regression — disallowed must show authoritative post-VAR score
# ══════════════════════════════════════════════════════════════════════════════


class TestDisallowedAuthoritativeScore:
    """Regression tests for Bug 3: thread momentarily under-reads after a VAR.

    Scenario: thread had announced goal 5 (announced=5-0, thread_seen=5-0).
    VAR reverses goal 5.  Thread mis-parses and reads 3-0 (under-reads goal 4 too).
    Without the clamp the disallowed message would say "3-0" — wrong.
    With the clamp (announced−1 per side) the message says "4-0" — correct.
    """

    @pytest.mark.asyncio
    async def test_under_read_disallowed_shows_announced_minus_1(self, tmp_path):
        """Thread under-reads 3-0 when announced=5-0 (VAR on goal 5).
        Disallowed message must show 4-0; announced must be updated to 4-0.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(
            5, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=3, away_score=0,
        )

        # State: thread previously announced goal 5 → both announced and thread_seen at 5-0
        live_scores = {"5": {"home": 5, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(
            settings,
            live_scores=live_scores,
            seen_thread={"5": {"home": 5, "away": 0}},
        )
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        ctx.bot.edit_message_text = AsyncMock()

        # Thread under-reads: only event at 3-0 visible (missed event 4)
        event_at_3 = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=3, away_score=0, minute_text="55",
            home_team="Spain", away_team="Saudi Arabia",
        )
        result = _make_thread_result("ESP", "SAU", [event_at_3])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        # One disallowed notification
        ctx.bot.send_message.assert_called_once()
        disallowed_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "❌" in disallowed_text or "VAR" in disallowed_text

        # Message must show 4-0 (announced-1), NOT the under-read 3-0
        assert "4-0" in disallowed_text, (
            f"Disallowed message should say 4-0 (announced-1), got: {disallowed_text!r}"
        )
        assert "3-0" not in disallowed_text, (
            f"Disallowed message must not contain under-read score 3-0: {disallowed_text!r}"
        )

        # Announced updated to 4-0 (not 3-0)
        assert live_scores["5"]["home"] == 4, (
            f"Announced must be updated to 4-0, got {live_scores['5']['home']}"
        )

    @pytest.mark.asyncio
    async def test_correct_read_disallowed_unchanged(self, tmp_path):
        """Thread correctly reads 4-0 after VAR on goal 5 (announced=5-0).
        Clamp must not change anything: max(4, 5-1)=4, message shows 4-0 as expected.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(
            5, "IN_PLAY",
            home_name="Spain", away_name="Saudi Arabia",
            home_tla="ESP", away_tla="SAU",
            home_score=4, away_score=0,
        )

        live_scores = {"5": {"home": 5, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(
            settings,
            live_scores=live_scores,
            seen_thread={"5": {"home": 5, "away": 0}},
        )
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        ctx.bot.edit_message_text = AsyncMock()

        event_at_4 = _make_goal_event(
            scorer="Morata", scoring_team="Spain",
            home_score=4, away_score=0, minute_text="60",
            home_team="Spain", away_team="Saudi Arabia",
        )
        result = _make_thread_result("ESP", "SAU", [event_at_4])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_called_once()
        disallowed_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "4-0" in disallowed_text
        assert live_scores["5"]["home"] == 4


# ══════════════════════════════════════════════════════════════════════════════
# Bug 4 regression — multi-goal jump announces all intermediate goals
# ══════════════════════════════════════════════════════════════════════════════


class TestMultiGoalExpansion:
    """Regression tests for Bug 4: when the thread sees a score jump >1 in one tick,
    every intermediate goal must be announced with the correct running score.
    Also verifies no goal is dropped when the two sources update around the same time
    (covered by Bug 1's lock fix; confirmed here via the per-target expansion).
    """

    @pytest.mark.asyncio
    async def test_three_away_goals_in_one_tick_sends_three_messages(self, tmp_path):
        """Thread sees NZ 1-3 EGY when announced was 1-0.
        Must send 3 notifications with scores 1-1, 1-2, 1-3.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(
            7, "IN_PLAY",
            home_name="New Zealand", away_name="Egypt",
            home_tla="NZL", away_tla="EGY",
            home_score=1, away_score=3,
        )

        live_scores = {"7": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(
            settings,
            live_scores=live_scores,
            seen_thread={"7": {"home": 1, "away": 0}},
        )
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        ctx.bot.edit_message_text = AsyncMock()

        events = [
            _make_goal_event(
                scorer="Salah", scoring_team="Egypt",
                home_score=1, away_score=1, minute_text="67", minute_sort=67.0,
                home_team="New Zealand", away_team="Egypt",
            ),
            _make_goal_event(
                scorer="Trezeguet", scoring_team="Egypt",
                home_score=1, away_score=2, minute_text="82", minute_sort=82.0,
                home_team="New Zealand", away_team="Egypt",
            ),
            _make_goal_event(
                scorer="Zizo", scoring_team="Egypt",
                home_score=1, away_score=3, minute_text="88", minute_sort=88.0,
                home_team="New Zealand", away_team="Egypt",
            ),
        ]
        result = _make_thread_result("NZL", "EGY", events)
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

        assert ctx.bot.send_message.call_count == 3, (
            f"Expected 3 goal notifications for 3-goal jump, got {ctx.bot.send_message.call_count}"
        )

        # Verify intermediate scores are shown correctly (not all showing 1-3)
        texts = [call.kwargs["text"] for call in ctx.bot.send_message.call_args_list]
        scores_in_messages = set()
        for text in texts:
            for score in ["1-1", "1-2", "1-3"]:
                if score in text:
                    scores_in_messages.add(score)
        assert scores_in_messages == {"1-1", "1-2", "1-3"}, (
            f"Expected intermediate scores 1-1, 1-2, 1-3 in messages, got {scores_in_messages}"
        )

        # All goals announced; announced updated to 1-3
        assert live_scores["7"]["away"] == 3

    @pytest.mark.asyncio
    async def test_multi_goal_no_goals_dropped_after_lock_claim(self, tmp_path):
        """After thread claims 1-3, a second call (simulating API catchup) produces no extra sends.
        Verifies Bug 4 is covered by Bug 1's lock fix.
        """
        from worldcup_bot.__main__ import poll_goals_job, poll_thread_goals_job

        settings = _make_settings(tmp_path)
        match = _make_match(
            7, "IN_PLAY",
            home_name="New Zealand", away_name="Egypt",
            home_tla="NZL", away_tla="EGY",
            home_score=1, away_score=3,
        )

        # Shared state: announced at 1-0
        shared_scores = {"7": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        shared_bot_data = {
            "settings": settings,
            "live_scores": shared_scores,
            "clip_store": {},
            "seen_scores": {
                "api": {"7": {"home": 1, "away": 0}},
                "thread": {"7": {"home": 1, "away": 0}},
            },
        }

        events = [
            _make_goal_event(scorer="Salah", scoring_team="Egypt",
                             home_score=1, away_score=1, minute_text="67", minute_sort=67.0,
                             home_team="New Zealand", away_team="Egypt"),
            _make_goal_event(scorer="Trezeguet", scoring_team="Egypt",
                             home_score=1, away_score=2, minute_text="82", minute_sort=82.0,
                             home_team="New Zealand", away_team="Egypt"),
            _make_goal_event(scorer="Zizo", scoring_team="Egypt",
                             home_score=1, away_score=3, minute_text="88", minute_sort=88.0,
                             home_team="New Zealand", away_team="Egypt"),
        ]
        thread_result = _make_thread_result("NZL", "EGY", events)
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[thread_result])
        mock_scanner.find_match_thread = MagicMock(return_value=None)
        shared_bot_data["reddit_scanner"] = mock_scanner

        ctx_thread = MagicMock()
        ctx_thread.bot_data = shared_bot_data
        ctx_thread.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        ctx_thread.bot.edit_message_text = AsyncMock()

        ctx_api = MagicMock()
        ctx_api.bot_data = shared_bot_data
        ctx_api.bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
        ctx_api.bot.edit_message_text = AsyncMock()

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            mock_client.return_value.get_all_matches.return_value = [match]

            # Thread announces all 3 goals
            await poll_thread_goals_job(ctx_thread)
            # API catchup at 1-3: announced already 1-3 → no new sends
            await poll_goals_job(ctx_api)

        thread_sends = ctx_thread.bot.send_message.call_count
        api_sends = ctx_api.bot.send_message.call_count
        assert thread_sends == 3, f"Thread should send 3 goals, sent {thread_sends}"
        assert api_sends == 0, f"API catchup must send 0 (all claimed), sent {api_sends}"


# ══════════════════════════════════════════════════════════════════════════════
# Over-match filter — thread job must not scan/announce for finished matches
# ══════════════════════════════════════════════════════════════════════════════


def _over_utc_date(hours: float = 5.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _recent_utc_date(minutes: float = 30.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class TestMatchOverFilterThread:
    """Regression suite for the Egypt-Iran loop bug — thread job side.

    The thread job must never scan/reconcile for a match whose kickoff is >4h ago,
    regardless of what get_live_matches() returns (the API can lag at IN_PLAY).
    """

    @pytest.mark.asyncio
    async def test_stale_inplay_match_filtered_thread_job_no_announce(self, tmp_path):
        """Live-match list contains a match with kickoff 5h ago → filtered out,
        scan_live_matches not called for it, no goal/disallowed sent."""
        settings = _make_settings(tmp_path)
        stale_match = _make_match(
            99, "IN_PLAY",
            home_name="Egypt", away_name="Iran",
            home_tla="EGY", away_tla="IRN",
            home_score=0, away_score=1,
            utc_date=_over_utc_date(hours=20),
        )

        live_scores = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores)
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with patch("worldcup_bot.__main__.make_client") as mock_client:
            mock_client.return_value.get_live_matches.return_value = [stale_match]
            await poll_thread_goals_job(ctx)

        # scan_live_matches must have been called with an empty list (stale match filtered)
        # OR not called at all (empty → early return).
        # Either way, no goal/disallowed notification should be sent.
        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_match_oscillation_zero_sends_thread_job(self, tmp_path):
        """Exact Egypt-Iran scenario via thread job: oscillating thread score on a
        >4h-old match produces zero sends across multiple ticks."""
        settings = _make_settings(tmp_path)
        stale_match = _make_match(
            99, "IN_PLAY",
            home_name="Egypt", away_name="Iran",
            home_tla="EGY", away_tla="IRN",
            home_score=0, away_score=1,
            utc_date=_over_utc_date(hours=20),
        )

        live_scores = {"99": {"home": 0, "away": 1, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"99": {"home": 0, "away": 1}})

        for away_score in [1, 0, 1, 0]:
            stale_match.away_score = away_score
            event = _make_goal_event(
                scorer="Mehdi", scoring_team="Iran",
                home_score=0, away_score=away_score,
                home_team="Egypt", away_team="Iran",
            )
            result = _make_thread_result("EGY", "IRN", [event])
            mock_scanner = MagicMock()
            mock_scanner.scan_live_matches = MagicMock(return_value=[result])
            ctx.bot_data["reddit_scanner"] = mock_scanner

            with patch("worldcup_bot.__main__.make_client") as mock_client:
                mock_client.return_value.get_live_matches.return_value = [stale_match]
                await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_recent_match_still_processed_by_thread_job(self, tmp_path):
        """A genuinely live match (kickoff 30 min ago) is not filtered — goals announced."""
        settings = _make_settings(tmp_path)
        match = _make_match(
            1, "IN_PLAY",
            home_name="England", away_name="Senegal",
            home_tla="ENG", away_tla="SEN",
            home_score=2, away_score=0,
            utc_date=_recent_utc_date(minutes=30),
        )

        live_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"1": {"home": 1, "away": 0}})

        event = _make_goal_event(
            scorer="Bellingham", scoring_team="England",
            home_score=2, away_score=0, minute_text="72",
        )
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

        ctx.bot.send_message.assert_called_once()
        assert "⚽" in ctx.bot.send_message.call_args.kwargs["text"]


# ══════════════════════════════════════════════════════════════════════════════
# Immediate save after goal claim (Part 4 — save-window race fix)
# ══════════════════════════════════════════════════════════════════════════════


class TestImmediateSave:
    """save_scores must be called INSIDE the goal_lock (immediately after claiming
    the score), not deferred to the end of the loop — prevents losing the claim
    if the process crashes between the in-memory update and the deferred save."""

    @pytest.mark.asyncio
    async def test_save_called_immediately_after_goal_claim(self, tmp_path):
        """Goal claimed -> save_scores called once with the new score right away."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0)
        live_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores,
                            seen_thread={"1": {"home": 1, "away": 0}})

        event = _make_goal_event(scorer="Harry Kane", scoring_team="England",
                                 home_score=2, away_score=0, minute_text="60")
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

        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][1]
        assert saved_state["1"]["home"] == 2

    @pytest.mark.asyncio
    async def test_save_persists_claim_even_when_notify_fails(self, tmp_path):
        """Even if send_message raises, the score was already saved inside the lock."""
        settings = _make_settings(tmp_path)
        match = _make_match(1, "IN_PLAY", home_score=2, away_score=0)
        live_scores = {"1": {"home": 1, "away": 0, "status": "IN_PLAY"}}
        ctx = _make_context(settings, live_scores=live_scores,
                            seen_thread={"1": {"home": 1, "away": 0}})

        event = _make_goal_event(scorer="Harry Kane", scoring_team="England",
                                 home_score=2, away_score=0, minute_text="60")
        result = _make_thread_result("ENG", "SEN", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner
        ctx.bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)  # must not raise

        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][1]
        assert saved_state["1"]["home"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Post-FT eviction dedup — evicted match skipped by thread job
# ══════════════════════════════════════════════════════════════════════════════


class TestPostFTEvictionDedup:
    """Once poll_goals_job evicts a match from live_scores (two-tick FINISHED eviction),
    poll_thread_goals_job must skip it entirely — no post-FT goal/disallowed sends."""

    @pytest.mark.asyncio
    async def test_evicted_match_skipped_by_thread_job(self, tmp_path):
        """live_scores has no entry for match -> thread job skips -> zero sends."""
        settings = _make_settings(tmp_path)
        live_scores = {}  # match already evicted
        ctx = _make_context(settings, live_scores=live_scores)

        event = _make_goal_event(scorer="Baena", scoring_team="Spain",
                                 home_score=0, away_score=1, minute_text="42",
                                 home_team="Uruguay", away_team="Spain")
        result = _make_thread_result("URU", "ESP", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        match = _make_match(99, "IN_PLAY", home_name="Uruguay", away_name="Spain",
                            home_tla="URU", away_tla="ESP",
                            home_score=0, away_score=1)

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Schedule-live matches: thread poller processes seeded TIMED match
# ══════════════════════════════════════════════════════════════════════════════


class TestPollThreadGoalsJobScheduleLive:
    """poll_thread_goals_job must handle seeded schedule-live (TIMED) matches."""

    @pytest.mark.asyncio
    async def test_seeded_timed_match_processes_goal_from_thread(self, tmp_path):
        """
        A TIMED schedule-live match that was already seeded at 0-0 (by poll_goals_job)
        should be processed by poll_thread_goals_job when the Reddit thread shows 1-0.

        This is the core real-time flow:
        1. poll_goals_job seeds the TIMED match at 0-0 (new schedule-live path).
        2. get_live_matches() now includes the TIMED match (fixed).
        3. poll_thread_goals_job finds the seeded entry and announces the goal.
        """
        settings = _make_settings(tmp_path)
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        match = Match(
            id=99,
            utc_date=utc_date,
            status="TIMED",
            stage="GROUP_STAGE",
            group="GROUP_A",
            home_tla="ENG",
            away_tla="COD",
            home_name="England",
            away_name="Congo DR",
            home_score=None,
            away_score=None,
            winner=None,
        )

        # Match is seeded at 0-0 (done by poll_goals_job on the schedule-live path)
        live_scores = {"99": {"home": 0, "away": 0, "status": "TIMED"}}
        ctx = _make_context(settings, live_scores=live_scores, seen_thread={"99": {"home": 0, "away": 0}})

        event = _make_goal_event(
            scorer="Harry Kane", scoring_team="England",
            home_score=1, away_score=0, minute_text="12",
            minute_sort=12.0,
            home_team="England", away_team="Congo DR",
        )
        result = _make_thread_result("ENG", "COD", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            # get_live_matches returns the TIMED schedule-live match (fixed behaviour)
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        # Goal announced in real time
        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in text

        # Shared state updated
        assert live_scores["99"]["home"] == 1

    @pytest.mark.asyncio
    async def test_unseeded_timed_match_still_skipped(self, tmp_path):
        """A TIMED schedule-live match that is NOT yet seeded should be skipped."""
        settings = _make_settings(tmp_path)
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        match = Match(
            id=77,
            utc_date=utc_date,
            status="TIMED",
            stage="GROUP_STAGE",
            group="GROUP_B",
            home_tla="FRA",
            away_tla="ARG",
            home_name="France",
            away_name="Argentina",
            home_score=None,
            away_score=None,
            winner=None,
        )

        # live_scores is empty → match not seeded
        ctx = _make_context(settings, live_scores={})

        event = _make_goal_event(
            scorer="Mbappe", scoring_team="France",
            home_score=1, away_score=0, minute_text="5",
            home_team="France", away_team="Argentina",
        )
        result = _make_thread_result("FRA", "ARG", [event])
        mock_scanner = MagicMock()
        mock_scanner.scan_live_matches = MagicMock(return_value=[result])
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mock_client,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mock_client.return_value.get_live_matches.return_value = [match]
            await poll_thread_goals_job(ctx)

        # Not seeded → skipped → no announcement
        ctx.bot.send_message.assert_not_called()
