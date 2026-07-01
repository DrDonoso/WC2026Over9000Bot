"""Edge-case / hardening tests for the schedule-based live-seeding fix.

Kanté's smoke tests (TestScheduleLivePredicate, TestGetLiveMatchesScheduleLive,
TestScheduleLiveSeeding, TestPollThreadGoalsJobScheduleLive) cover the happy path.
These tests harden:

1. match_is_schedule_live — sub-minute precision boundaries (elapsed=0, ±1s,
   exactly 4h, 4h+1s) and the AWARDED terminal status.
2. get_live_matches — mixed multi-status scenario (TIMED+FINISHED+TIMED-5h).
3. poll_goals_job — seeding at exactly the 4h window boundary vs. just over.
4. NO DOUBLE ANNOUNCE — thread-first-then-API and API-first-then-thread orderings.
5. NO FALSE DISALLOWED — 0-0 seed + thread 0→1 must never trigger a VAR message.
6. Double-goal thread catch-up — thread jumps 0→2 in one tick from seeded 0-0.
7. Real VAR on thread-first path — true disallowed is emitted after thread drops.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.client import MATCH_LIVE_WINDOW, match_is_schedule_live
from worldcup_bot.api.models import Match
from worldcup_bot.config import Settings
from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo

from worldcup_bot.__main__ import poll_goals_job, poll_thread_goals_job


# ── shared helpers ─────────────────────────────────────────────────────────────


def _make_match(
    mid: int = 42,
    status: str = "TIMED",
    home_name: str = "England",
    away_name: str = "Congo DR",
    home_tla: str = "ENG",
    away_tla: str = "COD",
    home_score: int | None = None,
    away_score: int | None = None,
    utc_date: str | None = None,
    minutes_ago: float = 30,
) -> Match:
    if utc_date is None:
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
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


def _no_enrichment_scanner() -> MagicMock:
    scanner = MagicMock()
    scanner.find_match_thread = MagicMock(return_value=None)
    scanner.get_thread_body = MagicMock(return_value="")
    return scanner


def _make_combined_context(settings: Settings, scanner=None) -> MagicMock:
    """Context that can be shared across poll_goals_job and poll_thread_goals_job.

    Initialises all keys that both jobs expect so neither job's setdefault()
    call ever shadows live state set by the other job.
    """
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "reddit_scanner": scanner or _no_enrichment_scanner(),
        "seen_scores": {"api": {}, "thread": {}},
        "clip_store": {},
        # goal_lock created explicitly so both jobs share the same lock object.
        "goal_lock": asyncio.Lock(),
    }
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
    return ctx


def _make_goal_event(
    scorer: str,
    scoring_team: str,
    home_score: int,
    away_score: int,
    minute_text: str = "15",
    minute_sort: float = 15.0,
    home_team: str = "England",
    away_team: str = "Congo DR",
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
        raw=f"**{minute_text}'** ⚽ Goal! {home_team} {home_score}-{away_score} {away_team}. {scorer}",
        key=f"post:{home_score}-{away_score}@{minute_text}:{scorer.lower().replace(' ', '')}",
    )


def _make_thread_result(
    home_tla: str,
    away_tla: str,
    events: list | None = None,
) -> MatchThreadResult:
    return MatchThreadResult(
        thread=ThreadInfo(
            post_id="matchpost",
            title=f"Match Thread: {home_tla} vs {away_tla}",
            permalink="/r/soccer/comments/matchpost",
            created_utc=1718640000.0,
        ),
        events=events or [],
        home_tla=home_tla,
        away_tla=away_tla,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. match_is_schedule_live — sub-minute precision boundaries
# ══════════════════════════════════════════════════════════════════════════════


class TestScheduleLivePredicatePrecision:
    """Second-level boundary tests that the minute-resolution smoke tests can't cover."""

    @staticmethod
    def _match_at_exact_elapsed(
        seconds: int,
        status: str = "TIMED",
    ) -> tuple[Match, datetime]:
        """Return (match, now_utc) such that now_utc - kickoff == exactly *seconds*.

        Uses microsecond=0 to avoid strftime truncation rounding the boundary.
        """
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        kickoff = now_utc - timedelta(seconds=seconds)
        utc_date = kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        m = Match(
            id=1,
            utc_date=utc_date,
            status=status,
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
        return m, now_utc

    def test_elapsed_exactly_zero_is_live(self):
        """Kickoff = now (elapsed 0 s) → at the inclusive lower bound → live."""
        m, now_utc = self._match_at_exact_elapsed(0)
        assert match_is_schedule_live(m, now_utc) is True

    def test_kickoff_1s_in_future_not_live(self):
        """Kickoff 1 second in the future → elapsed = -1 s → NOT live."""
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        kickoff = now_utc + timedelta(seconds=1)
        m = Match(
            id=2,
            utc_date=kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        assert match_is_schedule_live(m, now_utc) is False

    def test_elapsed_exactly_4h_is_live(self):
        """Elapsed = MATCH_LIVE_WINDOW exactly (4 h = 14 400 s) → at inclusive upper bound → live."""
        window_secs = int(MATCH_LIVE_WINDOW.total_seconds())  # 14400
        m, now_utc = self._match_at_exact_elapsed(window_secs)
        assert match_is_schedule_live(m, now_utc) is True

    def test_elapsed_4h_plus_1s_not_live(self):
        """Elapsed = 4 h + 1 s → one second past the window → NOT live."""
        window_secs = int(MATCH_LIVE_WINDOW.total_seconds()) + 1
        m, now_utc = self._match_at_exact_elapsed(window_secs)
        assert match_is_schedule_live(m, now_utc) is False

    def test_awarded_status_not_live(self):
        """AWARDED is a terminal status — must never be schedule-live even if within window."""
        m, now_utc = self._match_at_exact_elapsed(1800, status="AWARDED")
        assert match_is_schedule_live(m, now_utc) is False

    def test_timed_2h_elapsed_is_live(self):
        """2 h elapsed — well within 4 h window — is live (sanity mid-range check)."""
        m, now_utc = self._match_at_exact_elapsed(7200, status="TIMED")
        assert match_is_schedule_live(m, now_utc) is True

    def test_all_terminal_statuses_not_live(self):
        """Every known terminal status returns False, even at 30 min elapsed."""
        for status in ("FINISHED", "POSTPONED", "SUSPENDED", "CANCELLED", "AWARDED"):
            m, now_utc = self._match_at_exact_elapsed(1800, status=status)
            assert match_is_schedule_live(m, now_utc) is False, (
                f"{status} within window must not be live"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 2. get_live_matches — mixed-status scenario
# ══════════════════════════════════════════════════════════════════════════════


class TestGetLiveMatchesMixedScenario:
    """Mixed bag of statuses: only non-terminal, within-window matches are returned."""

    def _raw_match(
        self,
        mid: int,
        status: str,
        minutes_ago: float,
        home_score: int | None = None,
        away_score: int | None = None,
        winner: str | None = None,
    ) -> dict:
        utc_date = (
            datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "id": mid,
            "utcDate": utc_date,
            "status": status,
            "stage": "GROUP_STAGE",
            "group": "GROUP_A",
            "homeTeam": {"tla": "ENG", "name": "England"},
            "awayTeam": {"tla": "COD", "name": "Congo DR"},
            "score": {
                "fullTime": {"home": home_score, "away": away_score},
                "winner": winner,
            },
        }

    def test_mixed_returns_only_recent_timed(self):
        """3 matches: TIMED 30 min + FINISHED 90 min + TIMED 5 h → only TIMED 30 min returned."""
        import responses as resp_lib
        from worldcup_bot.api.cache import TTLCache
        from worldcup_bot.api.client import FootballDataClient

        matches = [
            self._raw_match(1, "TIMED", minutes_ago=30),         # schedule-live
            self._raw_match(2, "FINISHED", minutes_ago=90,
                            home_score=2, away_score=1, winner="HOME_TEAM"),  # terminal
            self._raw_match(3, "TIMED", minutes_ago=310),         # > 4 h → not live
        ]

        with resp_lib.RequestsMock() as rsps:
            rsps.add(
                resp_lib.GET,
                "https://api.football-data.org/v4/competitions/WC/matches",
                json={"matches": matches},
                status=200,
            )
            client = FootballDataClient(
                api_key="test-key",
                competition_code="WC",
                cache=TTLCache(ttl=60),
            )
            live = client.get_live_matches()

        ids = {m.id for m in live}
        assert 1 in ids, "TIMED 30 min ago must be schedule-live"
        assert 2 not in ids, "FINISHED must be excluded"
        assert 3 not in ids, "TIMED > 4 h ago must be excluded"
        assert len(live) == 1

    def test_paused_match_within_window_included(self):
        """PAUSED (half-time) match 45 min ago → non-terminal, within window → included."""
        import responses as resp_lib
        from worldcup_bot.api.cache import TTLCache
        from worldcup_bot.api.client import FootballDataClient

        match = self._raw_match(10, "PAUSED", minutes_ago=45)

        with resp_lib.RequestsMock() as rsps:
            rsps.add(
                resp_lib.GET,
                "https://api.football-data.org/v4/competitions/WC/matches",
                json={"matches": [match]},
                status=200,
            )
            client = FootballDataClient(
                api_key="test-key",
                competition_code="WC",
                cache=TTLCache(ttl=60),
            )
            live = client.get_live_matches()

        assert len(live) == 1
        assert live[0].id == 10


# ══════════════════════════════════════════════════════════════════════════════
# 3. poll_goals_job — 4 h window boundary for seeding
# ══════════════════════════════════════════════════════════════════════════════


class TestScheduleLiveSeedingWindowBoundary:
    """Verify seeding occurs at exactly the boundary but not one second past it."""

    @staticmethod
    def _timed_match_at_exact_elapsed(mid: int, seconds: int) -> Match:
        """TIMED match whose kickoff was exactly *seconds* ago (second-level precision)."""
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        kickoff = now_utc - timedelta(seconds=seconds)
        return Match(
            id=mid,
            utc_date=kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
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

    @pytest.mark.asyncio
    async def test_timed_well_within_window_is_seeded(self, tmp_path):
        """TIMED match kicked off 2 h ago — safely inside the 4 h window — is seeded.

        The exact 4 h boundary is tested as a pure function in
        TestScheduleLivePredicatePrecision.test_elapsed_exactly_4h_is_live.
        Here we verify the integration path (poll_goals_job `relevant` filter)
        without fighting sub-millisecond wall-clock jitter.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)

        # 120 min = 2 h — well within the 4 h window
        match = self._timed_match_at_exact_elapsed(mid=7, seconds=7200)

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mc.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert "7" in saved, "TIMED match 2 h ago must be seeded"
        assert saved["7"]["home"] == 0
        assert saved["7"]["away"] == 0

    @pytest.mark.asyncio
    async def test_timed_just_over_window_not_seeded(self, tmp_path):
        """TIMED match with elapsed = MATCH_LIVE_WINDOW + 30 s → past window → NOT seeded."""
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)

        over_secs = int(MATCH_LIVE_WINDOW.total_seconds()) + 30
        match = self._timed_match_at_exact_elapsed(mid=8, seconds=over_secs)

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mc.return_value.get_all_matches.return_value = [match]
            await poll_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()
        mock_save.assert_not_called()
        assert "live_scores" not in ctx.bot_data or "8" not in ctx.bot_data.get("live_scores", {})


# ══════════════════════════════════════════════════════════════════════════════
# 4. NO DOUBLE ANNOUNCE — the critical deduplication tests
# ══════════════════════════════════════════════════════════════════════════════


class TestNoDoubleAnnounce:
    """
    Invariant: regardless of which source (thread / API) announces a goal first,
    the total number of goal notifications sent to the group is exactly ONE.

    Mechanism: goal_lock + per-source seen dict + announced (live_scores) — the
    second job to run sees new == announced and reconcile returns no delta.
    """

    @staticmethod
    def _timed_match(mid: int = 42, minutes_ago: float = 30) -> Match:
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return Match(
            id=mid,
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

    @staticmethod
    def _in_play_match(mid: int = 42, minutes_ago: float = 30) -> Match:
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return Match(
            id=mid,
            utc_date=utc_date,
            status="IN_PLAY",
            stage="GROUP_STAGE",
            group="GROUP_A",
            home_tla="ENG",
            away_tla="COD",
            home_name="England",
            away_name="Congo DR",
            home_score=0,
            away_score=1,
            winner=None,
        )

    # ── Thread announces first, API catches up ─────────────────────────────

    @pytest.mark.asyncio
    async def test_thread_first_then_api_announces_exactly_once(self, tmp_path):
        """
        Flow:
        1. poll_goals_job (TIMED null scores) → seeds at 0-0, no send.
        2. poll_thread_goals_job (thread shows COD 0-1) → announces goal (send #1).
        3. poll_goals_job (API now reports IN_PLAY 0-1) → sees announced=0-1,
           reconcile returns no delta → NO additional send.

        Total: exactly 1 send.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = self._timed_match(mid=42)

        # ── Step 1: seed ──────────────────────────────────────────────────
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, "Seeding must produce no sends"
        assert ctx.bot_data["live_scores"]["42"]["home"] == 0
        assert ctx.bot_data["live_scores"]["42"]["away"] == 0

        # ── Step 2: thread announces COD 0-1 first ───────────────────────
        event = _make_goal_event(
            scorer="Banza",
            scoring_team="Congo DR",
            home_score=0,
            away_score=1,
            minute_text="12",
            minute_sort=12.0,
            home_team="England",
            away_team="Congo DR",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            # get_live_matches returns the TIMED match (schedule-live)
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1, "Thread must have announced the goal"
        goal_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in goal_text
        assert "anulado" not in goal_text.lower(), "No false disallowed on initial thread announce"

        # Verify live_scores was updated by the thread claim
        assert ctx.bot_data["live_scores"]["42"]["away"] == 1

        # ── Step 3: API catches up — same goal already announced ──────────
        ctx.bot.send_message.reset_mock()
        in_play_match = self._in_play_match(mid=42)

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_all_matches.return_value = [in_play_match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, (
            "API catch-up must NOT re-announce an already-announced goal"
        )

    # ── API announces first, thread catches up ─────────────────────────────

    @pytest.mark.asyncio
    async def test_api_first_then_thread_announces_exactly_once(self, tmp_path):
        """
        Flow:
        1. poll_goals_job (TIMED null scores) → seeds at 0-0, no send.
        2. poll_goals_job (API IN_PLAY 0-1) → announces goal (send #1).
        3. poll_thread_goals_job (thread shows same 0-1) → sees announced=0-1,
           reconcile(seen=None, announced=0-1, 0, 1): _ahead({0,1},{0,1}) is False
           → no delta → NO additional send.

        Total: exactly 1 send.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = self._timed_match(mid=43)

        # ── Step 1: seed ──────────────────────────────────────────────────
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0
        assert ctx.bot_data["live_scores"]["43"]["away"] == 0

        # ── Step 2: API announces 0-1 ─────────────────────────────────────
        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        in_play_0_1 = Match(
            id=43,
            utc_date=utc_date,
            status="IN_PLAY",
            stage="GROUP_STAGE",
            group="GROUP_A",
            home_tla="ENG",
            away_tla="COD",
            home_name="England",
            away_name="Congo DR",
            home_score=0,
            away_score=1,
            winner=None,
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_all_matches.return_value = [in_play_0_1]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1, "API must announce the goal"
        api_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in api_text
        assert ctx.bot_data["live_scores"]["43"]["away"] == 1

        # ── Step 3: thread catches up — same goal already announced ───────
        ctx.bot.send_message.reset_mock()
        event = _make_goal_event(
            scorer="Banza",
            scoring_team="Congo DR",
            home_score=0,
            away_score=1,
            minute_text="12",
            minute_sort=12.0,
            home_team="England",
            away_team="Congo DR",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [in_play_0_1]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, (
            "Thread catch-up must NOT re-announce an already-announced goal"
        )

    @pytest.mark.asyncio
    async def test_api_first_thread_second_seen_state_correct(self, tmp_path):
        """After API announces goal, seen_thread is updated to the announced score,
        so subsequent thread ticks at the same score produce zero deltas."""
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = self._timed_match(mid=44)

        # Seed + API announces 0-1
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        utc_date = timed_match.utc_date
        in_play = Match(
            id=44, utc_date=utc_date, status="IN_PLAY",
            stage="GROUP_STAGE", group="GROUP_A",
            home_tla="ENG", away_tla="COD",
            home_name="England", away_name="Congo DR",
            home_score=0, away_score=1, winner=None,
        )
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_all_matches.return_value = [in_play]
            await poll_goals_job(ctx)

        # API announced → send_count == 1
        first_send_count = ctx.bot.send_message.call_count
        assert first_send_count == 1

        ctx.bot.send_message.reset_mock()

        # Second poll_thread_goals_job tick with same score: no new send
        event = _make_goal_event(
            scorer="Banza", scoring_team="Congo DR",
            home_score=0, away_score=1, minute_text="12", minute_sort=12.0,
            home_team="England", away_team="Congo DR",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        # Run thread job twice to confirm idempotency
        for _ in range(2):
            with (
                patch("worldcup_bot.__main__.make_client") as mc,
                patch("worldcup_bot.__main__.save_scores"),
                patch("worldcup_bot.__main__.save_clips"),
            ):
                mc.return_value.get_live_matches.return_value = [in_play]
                await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, (
            "Thread at same score as announced must never re-send"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. NO FALSE DISALLOWED — 0-0 seed + thread 0→1 must not trigger VAR
# ══════════════════════════════════════════════════════════════════════════════


class TestNoFalseDisallowed:
    """
    When a match is seeded at 0-0 by the API path (TIMED null scores) and the
    thread then reports a goal, the reconcile restart-path returns a catchup
    delta.  The thread job must announce the goal but must NOT emit a disallowed
    (VAR) message — the score went UP, not down.
    """

    @pytest.mark.asyncio
    async def test_seed_then_thread_goal_no_disallowed(self, tmp_path):
        """Seed 0-0 → thread sees 0-1 → 1 goal message sent, 0 disallowed messages."""
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(42, "TIMED", minutes_ago=30)

        # Seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        assert ctx.bot_data["live_scores"]["42"]["away"] == 0

        # Thread sees 0-1 (first contact with this match from thread source)
        event = _make_goal_event(
            scorer="Banza", scoring_team="Congo DR",
            home_score=0, away_score=1, minute_text="17", minute_sort=17.0,
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1, "Exactly one goal notification expected"
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "⚽" in text, "Expected a goal emoji in the notification"
        assert "anulado" not in text.lower(), (
            "A VAR/disallowed message must NOT be sent when score only went up"
        )
        assert "❌" not in text, "No disallowed emoji expected"

    @pytest.mark.asyncio
    async def test_seed_then_thread_real_var_disallowed(self, tmp_path):
        """
        Seed 0-0 → thread 0-1 (goal) → thread drops to 0-0 (VAR).
        Expected: 2 sends total — 1 goal + 1 disallowed.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(45, "TIMED", minutes_ago=30)

        # Seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        # Thread tick 1: thread shows 0-1 → goal announced
        event_01 = _make_goal_event(
            scorer="Banza", scoring_team="Congo DR",
            home_score=0, away_score=1, minute_text="17",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event_01])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        assert "⚽" in ctx.bot.send_message.call_args.kwargs["text"]
        # Score claimed at 0-1, seen_thread["45"] = {home:0, away:1}
        assert ctx.bot_data["live_scores"]["45"]["away"] == 1

        # Thread tick 2: VAR — thread body now shows 0-0.
        # We simulate this with a single event showing the corrected score 0-0.
        # poll_thread_goals_job computes thread_away = max(e.away_score) = 0.
        # reconcile(seen={0,1}, announced={0,1}, 0, 0) → disallowed.
        # (Empty events would trigger `if not events: continue` and skip processing.)
        ctx.bot.send_message.reset_mock()
        var_event = GoalEvent(
            minute_text="17+1",
            minute_sort=17.1,
            scorer="",
            scoring_team="",
            home_team="England",
            away_team="Congo DR",
            home_score=0,
            away_score=0,
            raw="**17+1'** VAR: Goal disallowed. England 0-0 Congo DR.",
            key="matchpost:0-0@17v:var",
        )
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [var_event])]
        )

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        # Disallowed must be sent (thread's own prior value {0,1} dropped to {0,0})
        assert ctx.bot.send_message.call_count == 1, "Exactly one disallowed message expected"
        disallowed_text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "anulado" in disallowed_text.lower() or "❌" in disallowed_text, (
            "Disallowed message must contain VAR indicator"
        )

    @pytest.mark.asyncio
    async def test_false_disallowed_not_triggered_by_api_lag(self, tmp_path):
        """
        Thread first reports 0-1.  API is still showing null (TIMED/lag).
        A subsequent API tick at 0-0 must NOT trigger a disallowed message
        because the API source's own prior value was 0-0 (not above new score).

        reconcile(seen_api={0,0}, announced={0,1}, curr_home=0, curr_away=0):
        - _ahead(ann={0,1}, new={0,0}) → True (announced is ahead)
        - _ahead(seen={0,0}, new={0,0}) → False (source never went up) → LAG path
        → no disallowed emitted.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(46, "TIMED", minutes_ago=30)

        # Seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        # Thread announces 0-1 first
        event = _make_goal_event(
            scorer="Banza", scoring_team="Congo DR",
            home_score=0, away_score=1, minute_text="20",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        ctx.bot.send_message.reset_mock()

        # API still lagging — reports null scores (TIMED, no score yet)
        # poll_goals_job processes this; curr_home=0, curr_away=0
        # reconcile(seen_api={0,0}, announced={0,1}, 0, 0) → lag path → no disallowed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]  # still TIMED, null
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, (
            "API lagging at 0-0 while announced=0-1 must NOT trigger a false disallowed"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. Thread announces multiple goals from seeded 0-0 in one pass
# ══════════════════════════════════════════════════════════════════════════════


class TestThreadMultiGoalFromSeed:
    """Thread jumps multiple goals ahead of 0-0 seed in a single poll cycle."""

    @pytest.mark.asyncio
    async def test_thread_jumps_to_0_2_from_seed_announces_two_goals(self, tmp_path):
        """
        Seed 0-0; thread reports 0-2 in one tick.
        Reconcile (seen=None, announced={0,0}, 0, 2) → catchup delta.
        goals_to_notify is built from range(announced.away+1..new_ann.away+1)
        → 2 notifications sent.
        """
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(47, "TIMED", minutes_ago=30)

        # Seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        assert ctx.bot_data["live_scores"]["47"]["away"] == 0

        # Thread reports 0-2 (two goals, both away)
        events = [
            _make_goal_event(
                scorer="Banza", scoring_team="Congo DR",
                home_score=0, away_score=1, minute_text="18", minute_sort=18.0,
            ),
            _make_goal_event(
                scorer="Mbemba", scoring_team="Congo DR",
                home_score=0, away_score=2, minute_text="34", minute_sort=34.0,
            ),
        ]
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", events)]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 2, (
            "Two goals must each produce a notification"
        )
        for call in ctx.bot.send_message.call_args_list:
            assert "⚽" in call.kwargs["text"]

        assert ctx.bot_data["live_scores"]["47"]["away"] == 2

    @pytest.mark.asyncio
    async def test_api_does_not_re_announce_after_two_thread_goals(self, tmp_path):
        """After thread announces 0-2, API reporting IN_PLAY 0-2 must produce zero sends."""
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(48, "TIMED", minutes_ago=30)

        # Seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        # Thread reports 0-2
        events = [
            _make_goal_event(
                scorer="Banza", scoring_team="Congo DR",
                home_score=0, away_score=1, minute_text="18", minute_sort=18.0,
            ),
            _make_goal_event(
                scorer="Mbemba", scoring_team="Congo DR",
                home_score=0, away_score=2, minute_text="34", minute_sort=34.0,
            ),
        ]
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", events)]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 2
        ctx.bot.send_message.reset_mock()

        # API catches up — IN_PLAY 0-2
        utc_date = timed_match.utc_date
        in_play_0_2 = Match(
            id=48, utc_date=utc_date, status="IN_PLAY",
            stage="GROUP_STAGE", group="GROUP_A",
            home_tla="ENG", away_tla="COD",
            home_name="England", away_name="Congo DR",
            home_score=0, away_score=2, winner=None,
        )
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_all_matches.return_value = [in_play_0_2]
            await poll_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0, (
            "API catch-up at 0-2 (same as announced) must produce zero sends"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 7. Seeding idempotency — multiple poll_goals_job ticks at 0-0 must not re-seed
# ══════════════════════════════════════════════════════════════════════════════


class TestSeedingIdempotency:
    """Once a TIMED match is seeded at 0-0, subsequent ticks with null scores
    must not re-seed (save_scores called only once, no double sends)."""

    @pytest.mark.asyncio
    async def test_second_tick_with_null_scores_no_extra_save(self, tmp_path):
        """Two consecutive poll_goals_job ticks on a TIMED null-score match.
        Tick 1 → saves (seed).  Tick 2 → no new goals → no duplicate save."""
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(50, "TIMED", minutes_ago=30)

        # Tick 1: seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores") as mock_save,
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        assert mock_save.call_count == 1, "Seeding tick must save once"

        # Tick 2: already seeded at 0-0; API still null → reconcile no-delta → no save
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores") as mock_save2,
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        assert mock_save2.call_count == 0, (
            "Second tick with no score change must not re-save"
        )
        ctx.bot.send_message.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# 8. poll_thread_goals_job — schedule-seeded match ordering invariants
# ══════════════════════════════════════════════════════════════════════════════


class TestScheduleLiveSeedThreadOrdering:
    """Additional ordering invariants for the seeded-TIMED / thread interaction."""

    @pytest.mark.asyncio
    async def test_thread_before_seed_is_silently_skipped(self, tmp_path):
        """poll_thread_goals_job runs BEFORE poll_goals_job seeds the match.
        live_scores is empty → match not yet seeded → skipped silently → no send."""
        settings = _make_settings(tmp_path)
        # Context without live_scores being seeded (no poll_goals_job run)
        ctx = MagicMock()
        ctx.bot_data = {
            "settings": settings,
            "reddit_scanner": None,
            "live_scores": {},       # not yet seeded
            "seen_scores": {"api": {}, "thread": {}},
            "clip_store": {},
            "goal_lock": asyncio.Lock(),
        }
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))

        utc_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        timed_match = Match(
            id=51, utc_date=utc_date, status="TIMED",
            stage="GROUP_STAGE", group="GROUP_A",
            home_tla="ENG", away_tla="COD",
            home_name="England", away_name="Congo DR",
            home_score=None, away_score=None, winner=None,
        )

        event = _make_goal_event(
            scorer="Banza", scoring_team="Congo DR",
            home_score=0, away_score=1, minute_text="5",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        ctx.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_second_tick_same_goal_no_resend(self, tmp_path):
        """After thread announces a goal from seed, a second thread tick
        at the same score must produce no additional send."""
        settings = _make_settings(tmp_path)
        ctx = _make_combined_context(settings)
        timed_match = _make_match(52, "TIMED", minutes_ago=30)

        # Seed
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.load_scores", return_value={}),
            patch("worldcup_bot.__main__.save_scores"),
        ):
            mc.return_value.get_all_matches.return_value = [timed_match]
            await poll_goals_job(ctx)

        # Thread tick 1: announces goal
        event = _make_goal_event(
            scorer="Banza", scoring_team="Congo DR",
            home_score=0, away_score=1, minute_text="18",
        )
        scanner = MagicMock()
        scanner.scan_live_matches = MagicMock(
            return_value=[_make_thread_result("ENG", "COD", [event])]
        )
        ctx.bot_data["reddit_scanner"] = scanner

        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 1
        ctx.bot.send_message.reset_mock()

        # Thread tick 2: same event, same score — no re-send
        with (
            patch("worldcup_bot.__main__.make_client") as mc,
            patch("worldcup_bot.__main__.save_scores"),
            patch("worldcup_bot.__main__.save_clips"),
        ):
            mc.return_value.get_live_matches.return_value = [timed_match]
            await poll_thread_goals_job(ctx)

        assert ctx.bot.send_message.call_count == 0
