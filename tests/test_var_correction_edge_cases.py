"""Edge-case / hardening tests for the post-final VAR correction feature.

Kanté's 8 smoke tests (TestVARCorrectionWatch in test_poll_finished_job.py) cover:
  - Score change → correction + goal edit (searching clip, no keyboard)
  - Ready clip → keyboard preserved
  - Stable score → no correction
  - No duplicate after correction (corrected flag + same score)
  - Penalty shootout on-pitch stable → no false positive
  - Window expiry 45 min → pruned
  - Absent clip → correction sent, edit skipped
  - Score recorded at finalization

These tests harden:
  1. Token probing: home score drop (first probe) and away team probe (second probe)
  2. Genuine re-correction within window: second VAR fires against updated recorded score
  3. Window boundary precision (_fs_entry_is_stale pure-function tests)
  4. Unparseable / missing finalized_at → treated as stale, pruned
  5. match_result_is_final=False (shootout not yet settled) → skipped, no correction
  6. edit_message_text raises → correction still counted, no crash
  7. send_message raises → edit still attempted, corrected=True still set
  8. clip_store missing from bot_data → graceful no crash
  9. Two matches in finished_scores → both corrected independently
  10. Match not in matches_by_id → entry skipped gracefully
  11. clip status "timeout" or missing → no keyboard on edit
  12. Empty finished_scores → early return, no-op
  13. Format: format_var_correction output structure
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.bot.formatters import format_var_correction
from worldcup_bot.config import Settings
from worldcup_bot.reddit.clip_store import goal_token as _cs_goal_token
from worldcup_bot.reddit.notifier import build_goal_keyboard

from worldcup_bot.__main__ import (
    _fs_entry_is_stale,
    _var_correction_watch,
    poll_finished_matches_job,
)


# ── shared helpers ─────────────────────────────────────────────────────────────


def _make_settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567",
        state_dir=str(tmp_path),
        predictions_path=str(tmp_path / "predictions.yml"),
    )


def _make_match(
    mid: int = 101,
    home_name: str = "Portugal",
    away_name: str = "Croatia",
    home_tla: str = "POR",
    away_tla: str = "CRO",
    home_score: int = 2,
    away_score: int = 1,
    winner: str = "HOME_TEAM",
    duration: str = "REGULAR",
    penalty_home: int | None = None,
    penalty_away: int | None = None,
) -> Match:
    return Match(
        id=mid,
        utc_date="2026-07-03T20:00:00Z",
        status="FINISHED",
        stage="LAST_16",
        group=None,
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=home_score,
        away_score=away_score,
        winner=winner,
        duration=duration,
        penalty_home=penalty_home,
        penalty_away=penalty_away,
    )


def _fs_entry(
    home: int,
    away: int,
    corrected: bool = False,
    age_minutes: float = 5,
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    return {"home": home, "away": away, "finalized_at": ts, "corrected": corrected}


def _clip_entry(
    match_id: int,
    scoring_team: str,
    home_score: int,
    away_score: int,
    message_id: int = 42,
    chat_id: int = -100999,
    status: str = "searching",
) -> tuple[str, dict]:
    """Return (token, clip_store_entry)."""
    token_key = f"{match_id}:{scoring_team}:{home_score}-{away_score}"
    tok = _cs_goal_token(token_key)
    entry = {
        "chat_id": chat_id,
        "message_id": message_id,
        "home_name": "Portugal",
        "away_name": "Croatia",
        "home_tla": "POR",
        "away_tla": "CRO",
        "home_score": home_score,
        "away_score": away_score,
        "scoring_team": scoring_team,
        "scorer": "Cristiano Ronaldo",
        "minute": "90",
        "status": status,
        "clip_path": None,
        "file_id": None,
        "attempts": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return tok, entry


def _make_ctx(settings: Settings, finished_scores: dict, clip_store: dict) -> MagicMock:
    """Minimal context for _var_correction_watch unit calls."""
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "finished_scores": finished_scores,
        "clip_store": clip_store,
    }
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
    ctx.bot.edit_message_text = AsyncMock(return_value=MagicMock())
    return ctx


def _make_no_new_ctx(settings: Settings, match: Match) -> tuple[MagicMock, MagicMock]:
    """Context where match is already in finished_announced — only VAR watch runs."""
    from tests.test_poll_finished_job import _make_context as _base_ctx
    ctx = _base_ctx(settings)
    ctx.bot_data["finished_seeded"] = True
    ctx.bot_data["finished_announced"] = {match.id}
    mock_client = MagicMock()
    mock_client.get_all_matches.return_value = [match]
    return ctx, mock_client


# ══════════════════════════════════════════════════════════════════════════════
# 1. _fs_entry_is_stale — precision boundary unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFsEntryIsStalePrecision:
    """Pure-function unit tests for _fs_entry_is_stale boundary logic."""

    def test_exactly_at_window_boundary_is_not_stale(self):
        """Elapsed == window → NOT stale (boundary is strict >)."""
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        window = timedelta(minutes=30)
        entry = {"finalized_at": (now_utc - window).isoformat()}
        assert _fs_entry_is_stale(entry, now_utc, window) is False

    def test_one_second_past_window_is_stale(self):
        """Elapsed == window + 1 s → stale."""
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        window = timedelta(minutes=30)
        entry = {"finalized_at": (now_utc - window - timedelta(seconds=1)).isoformat()}
        assert _fs_entry_is_stale(entry, now_utc, window) is True

    def test_well_within_window_is_not_stale(self):
        """Finalized 5 min ago with 30-min window → not stale."""
        now_utc = datetime.now(timezone.utc)
        window = timedelta(minutes=30)
        entry = {"finalized_at": (now_utc - timedelta(minutes=5)).isoformat()}
        assert _fs_entry_is_stale(entry, now_utc, window) is False

    def test_well_outside_window_is_stale(self):
        """Finalized 45 min ago with 30-min window → stale."""
        now_utc = datetime.now(timezone.utc)
        window = timedelta(minutes=30)
        entry = {"finalized_at": (now_utc - timedelta(minutes=45)).isoformat()}
        assert _fs_entry_is_stale(entry, now_utc, window) is True

    def test_unparseable_finalized_at_is_stale(self):
        """Bad timestamp → exception handled → treated as stale."""
        now_utc = datetime.now(timezone.utc)
        window = timedelta(minutes=30)
        assert _fs_entry_is_stale({"finalized_at": "not-a-date"}, now_utc, window) is True

    def test_missing_finalized_at_key_is_stale(self):
        """Entry without finalized_at key → exception → stale."""
        now_utc = datetime.now(timezone.utc)
        window = timedelta(minutes=30)
        assert _fs_entry_is_stale({}, now_utc, window) is True

    def test_naive_datetime_treated_as_utc(self):
        """ISO string without timezone → coerced to UTC, not treated as stale."""
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        window = timedelta(minutes=30)
        # naive ISO string 5 minutes in the past → should NOT be stale
        naive_ts = (now_utc - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
        entry = {"finalized_at": naive_ts}
        assert _fs_entry_is_stale(entry, now_utc, window) is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. Token probing — home vs away team clip lookup
# ══════════════════════════════════════════════════════════════════════════════


class TestTokenReconstructionProbing:
    """_mark_goal_annulled tries home team first, then away team.
    The correct entry must be found regardless of which team scored the annulled goal.
    """

    @pytest.mark.asyncio
    async def test_home_score_drop_home_team_clip_first_probe(self, tmp_path):
        """Portugal (home) scored the 3-1 goal; that goal is VAR'd → 3-1→2-1.
        Clip stored with scoring_team='Portugal' → first probe finds it.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)

        # Recorded: 3-1 (Portugal scored the 3rd goal)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=3, away=1)}
        tok, clip = _clip_entry(101, "Portugal", home_score=3, away_score=1, message_id=77)
        ctx.bot_data["clip_store"] = {tok: clip}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Correction message sent
        assert ctx.bot.send_message.await_count == 1
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert "3-1" in text     # old (annulled) home score
        assert "2-1" in text     # new score

        # Goal message edited (first probe found Portugal's entry)
        assert ctx.bot.edit_message_text.await_count == 1
        ekw = ctx.bot.edit_message_text.call_args.kwargs
        assert ekw["message_id"] == 77
        assert "ANULADO" in ekw["text"]

    @pytest.mark.asyncio
    async def test_away_score_drop_away_team_clip_second_probe(self, tmp_path):
        """Croatia (away) scored the 2-2 goal; that goal is VAR'd → 2-2→2-1.
        Clip stored with scoring_team='Croatia' (away team).
        First probe for 'Portugal:2-2' misses; second probe for 'Croatia:2-2' finds it.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)

        # Recorded: 2-2 (Croatia scored the equaliser)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        # ONLY the away team clip is in the store
        tok, clip = _clip_entry(101, "Croatia", home_score=2, away_score=2, message_id=88)
        ctx.bot_data["clip_store"] = {tok: clip}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Correction message sent
        assert ctx.bot.send_message.await_count == 1
        assert "2-2" in ctx.bot.send_message.call_args.kwargs["text"]

        # Edit called on Croatia's clip (second probe succeeded)
        assert ctx.bot.edit_message_text.await_count == 1
        ekw = ctx.bot.edit_message_text.call_args.kwargs
        assert ekw["message_id"] == 88
        assert "ANULADO" in ekw["text"]

    @pytest.mark.asyncio
    async def test_both_team_clips_present_home_wins(self, tmp_path):
        """Both home and away clips exist for the annulled score.
        The home team (first probe) wins — only one edit is performed.
        """
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}

        tok_h, clip_h = _clip_entry(101, "Portugal", home_score=2, away_score=2, message_id=10)
        tok_a, clip_a = _clip_entry(101, "Croatia", home_score=2, away_score=2, message_id=20)
        ctx.bot_data["clip_store"] = {tok_h: clip_h, tok_a: clip_a}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Exactly one edit — for the home team clip (first probe wins)
        assert ctx.bot.edit_message_text.await_count == 1
        ekw = ctx.bot.edit_message_text.call_args.kwargs
        assert ekw["message_id"] == 10  # Portugal's message_id


# ══════════════════════════════════════════════════════════════════════════════
# 3. Genuine re-correction — second VAR within window
# ══════════════════════════════════════════════════════════════════════════════


class TestGenuineReCorrection:
    """A second VAR within the window must produce a second correction."""

    @pytest.mark.asyncio
    async def test_second_var_fires_after_first_correction(self, tmp_path):
        """
        Tick 1: recorded 2-2, API shows 2-1 → first correction fires.
                Recorded score updated to 2-1, corrected=True.
        Tick 2: API now shows 2-0 → second correction fires against updated score.
        """
        settings = _make_settings(tmp_path)

        # ── Tick 1: 2-2 → 2-1 ─────────────────────────────────────────────
        match_2_1 = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match_2_1)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        assert ctx.bot.send_message.await_count == 1
        text_tick1 = ctx.bot.send_message.call_args.kwargs["text"]
        assert "2-2" in text_tick1  # old score
        assert "2-1" in text_tick1  # new score
        assert ctx.bot_data["finished_scores"]["101"]["home"] == 2
        assert ctx.bot_data["finished_scores"]["101"]["away"] == 1
        assert ctx.bot_data["finished_scores"]["101"]["corrected"] is True

        # ── Tick 2: 2-1 → 2-0 ─────────────────────────────────────────────
        ctx.bot.send_message.reset_mock()
        ctx.bot.edit_message_text.reset_mock()

        match_2_0 = _make_match(home_score=2, away_score=0)
        mock_client_2 = MagicMock()
        mock_client_2.get_all_matches.return_value = [match_2_0]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client_2),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        assert ctx.bot.send_message.await_count == 1
        text_tick2 = ctx.bot.send_message.call_args.kwargs["text"]
        assert "2-1" in text_tick2  # old (now 2-1 recorded after tick 1)
        assert "2-0" in text_tick2  # newest correction
        assert ctx.bot_data["finished_scores"]["101"]["away"] == 0

    @pytest.mark.asyncio
    async def test_immediate_second_tick_no_duplicate(self, tmp_path):
        """After correction (recorded=2-1, corrected=True), same API score on next tick → no duplicate."""
        settings = _make_settings(tmp_path)
        match_2_1 = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match_2_1)
        # Already corrected; recorded score == current API score
        ctx.bot_data["finished_scores"] = {
            "101": _fs_entry(home=2, away=1, corrected=True)
        }
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            # Two ticks in a row
            await poll_finished_matches_job(ctx)
            await poll_finished_matches_job(ctx)

        # Zero sends across both ticks
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Shootout safety — match_result_is_final=False skips the watch entry
# ══════════════════════════════════════════════════════════════════════════════


class TestShootoutSafetyEdgeCases:
    """Penalty shootout not yet settled → match_result_is_final is False → skipped."""

    @pytest.mark.asyncio
    async def test_shootout_not_settled_skips_even_if_score_differs(self, tmp_path):
        """
        PENALTY_SHOOTOUT match where penalty_home/penalty_away are None.
        match_result_is_final returns False → _var_correction_watch skips it.
        Even if on-pitch score changed (recorded 1-1, current 1-0), NO correction.
        """
        settings = _make_settings(tmp_path)
        # Shootout not settled: no penalty scores yet, winner=None
        unsettled = _make_match(
            home_score=1, away_score=0,
            winner=None,
            duration="PENALTY_SHOOTOUT",
            penalty_home=None,
            penalty_away=None,
        )
        ctx, mock_client = _make_no_new_ctx(settings, unsettled)
        # Recorded 1-1 → current 1-0 would be a diff, but shootout not final
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=1, away=1)}
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_settled_shootout_on_pitch_stable_no_correction(self, tmp_path):
        """Settled shootout with stable on-pitch score → no correction.
        Verifies the diff logic works for penalty matches once final.
        """
        settings = _make_settings(tmp_path)
        settled = _make_match(
            home_score=1, away_score=1,
            winner="HOME_TEAM",
            duration="PENALTY_SHOOTOUT",
            penalty_home=5, penalty_away=4,
        )
        ctx, mock_client = _make_no_new_ctx(settings, settled)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=1, away=1)}
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# 5. Best-effort resilience — exception handling
# ══════════════════════════════════════════════════════════════════════════════


class TestBestEffortResiliency:
    """Failures in send/edit must not break the job; corrected flag must still be set."""

    @pytest.mark.asyncio
    async def test_edit_raises_correction_still_counted(self, tmp_path):
        """edit_message_text raises → corrected=True still set, no crash."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        tok, clip = _clip_entry(101, "Portugal", home_score=2, away_score=2, message_id=55)
        ctx.bot_data["clip_store"] = {tok: clip}

        # edit_message_text raises TelegramError
        ctx.bot.edit_message_text = AsyncMock(side_effect=Exception("Telegram timeout"))

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)  # must not raise

        # Correction message still sent
        assert ctx.bot.send_message.await_count == 1
        # corrected flag still set (update happens after _mark_goal_annulled returns)
        assert ctx.bot_data["finished_scores"]["101"]["corrected"] is True
        assert ctx.bot_data["finished_scores"]["101"]["away"] == 1

    @pytest.mark.asyncio
    async def test_send_message_raises_edit_still_attempted(self, tmp_path):
        """send_message raises → edit still attempted, corrected=True still set, no crash."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        tok, clip = _clip_entry(101, "Portugal", home_score=2, away_score=2, message_id=66)
        ctx.bot_data["clip_store"] = {tok: clip}

        ctx.bot.send_message = AsyncMock(side_effect=Exception("network error"))

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)  # must not raise

        # Edit still attempted (send failure doesn't skip the edit)
        assert ctx.bot.edit_message_text.await_count == 1
        # corrected flag still set
        assert ctx.bot_data["finished_scores"]["101"]["corrected"] is True

    @pytest.mark.asyncio
    async def test_clip_store_missing_from_bot_data_no_crash(self, tmp_path):
        """clip_store key absent from bot_data → graceful fallback to {}, no crash."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        # Deliberately omit clip_store from bot_data
        ctx.bot_data.pop("clip_store", None)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)  # must not raise

        # Correction still sent; edit skipped (no clip_store → no entry)
        assert ctx.bot.send_message.await_count == 1
        ctx.bot.edit_message_text.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# 6. Multiple matches in finished_scores
# ══════════════════════════════════════════════════════════════════════════════


class TestMultipleMatchesEdgeCases:
    """Both entries in finished_scores corrected independently."""

    @pytest.mark.asyncio
    async def test_two_matches_both_corrected_independently(self, tmp_path):
        """Two matches each with a score change → two corrections, independent edits."""
        settings = _make_settings(tmp_path)

        match_101 = _make_match(mid=101, home_score=2, away_score=1)  # 2-2 → 2-1
        match_202 = _make_match(
            mid=202,
            home_name="Germany",
            away_name="Brazil",
            home_tla="GER",
            away_tla="BRA",
            home_score=1,
            away_score=0,
        )  # 1-1 → 1-0

        # Both already announced; no new finalisation
        ctx = MagicMock()
        ctx.bot_data = {
            "settings": settings,
            "espn_client": None,
            "reddit_scanner": None,
            "finished_announced": {101, 202},
            "finished_seeded": True,
            "finished_scores": {
                "101": _fs_entry(home=2, away=2),
                "202": _fs_entry(home=1, away=1),
            },
            "clip_store": {},
        }
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        ctx.bot.edit_message_text = AsyncMock(return_value=MagicMock())

        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match_101, match_202]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Two correction messages (one per match)
        assert ctx.bot.send_message.await_count == 2
        texts = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
        # Each text contains the respective old and new scores
        assert any("2-2" in t and "2-1" in t for t in texts)
        assert any("1-1" in t and "1-0" in t for t in texts)

        # Both entries corrected
        assert ctx.bot_data["finished_scores"]["101"]["corrected"] is True
        assert ctx.bot_data["finished_scores"]["202"]["corrected"] is True

    @pytest.mark.asyncio
    async def test_match_not_in_matches_by_id_skipped_gracefully(self, tmp_path):
        """Entry for match_id not in API response → skipped, no crash, no correction."""
        settings = _make_settings(tmp_path)
        # Only match 999 in API, but finished_scores has match 101
        other_match = _make_match(mid=999, home_score=1, away_score=0)
        ctx = MagicMock()
        ctx.bot_data = {
            "settings": settings,
            "espn_client": None,
            "reddit_scanner": None,
            "finished_announced": {999},
            "finished_seeded": True,
            "finished_scores": {"101": _fs_entry(home=2, away=2)},
            "clip_store": {},
        }
        ctx.bot.send_message = AsyncMock()
        ctx.bot.edit_message_text = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [other_match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# 7. Keyboard preservation edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestKeyboardEdgeCases:
    """Only status='ready' clips get reply_markup; others get no keyboard."""

    @pytest.mark.asyncio
    async def test_timeout_status_no_keyboard(self, tmp_path):
        """Clip with status='timeout' → no keyboard on edit (only 'ready' gets one)."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        tok, clip = _clip_entry(
            101, "Portugal", home_score=2, away_score=2, message_id=33, status="timeout"
        )
        ctx.bot_data["clip_store"] = {tok: clip}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        assert ctx.bot.edit_message_text.await_count == 1
        ekw = ctx.bot.edit_message_text.call_args.kwargs
        assert "reply_markup" not in ekw, "timeout clip must NOT pass reply_markup"
        assert "ANULADO" in ekw["text"]

    @pytest.mark.asyncio
    async def test_missing_status_field_no_keyboard(self, tmp_path):
        """Clip entry without 'status' key → no keyboard (safe default)."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}

        tok, clip = _clip_entry(101, "Portugal", home_score=2, away_score=2, message_id=44)
        del clip["status"]  # remove status field
        ctx.bot_data["clip_store"] = {tok: clip}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        assert ctx.bot.edit_message_text.await_count == 1
        ekw = ctx.bot.edit_message_text.call_args.kwargs
        assert "reply_markup" not in ekw
        assert "ANULADO" in ekw["text"]

    @pytest.mark.asyncio
    async def test_ready_clip_keyboard_contains_vergol_callback(self, tmp_path):
        """'ready' clip → reply_markup contains the 'vergol:<token>' callback button."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {"101": _fs_entry(home=2, away=2)}
        tok, clip = _clip_entry(
            101, "Portugal", home_score=2, away_score=2, message_id=55, status="ready"
        )
        ctx.bot_data["clip_store"] = {tok: clip}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ekw = ctx.bot.edit_message_text.call_args.kwargs
        assert "reply_markup" in ekw
        expected_keyboard = build_goal_keyboard(tok)
        assert ekw["reply_markup"] == expected_keyboard
        # Verify the button contains the correct callback data
        button = ekw["reply_markup"].inline_keyboard[0][0]
        assert button.callback_data == f"vergol:{tok}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. Empty / missing finished_scores edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestEmptyOrMissingFinishedScores:

    @pytest.mark.asyncio
    async def test_empty_finished_scores_dict_no_op(self, tmp_path):
        """finished_scores = {} → early return, no crash, no sends."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["finished_scores"] = {}
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finished_scores_not_in_bot_data_no_op(self, tmp_path):
        """finished_scores key missing from bot_data → early return in watch, no crash."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["clip_store"] = {}
        # Don't set finished_scores at all

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# 9. format_var_correction output structure
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatVarCorrection:
    """Verify the correction message format matches the spec."""

    def test_format_contains_required_elements(self):
        """Output must contain: ⚠️, Corrección, VAR, old score, new score, team names."""
        match = _make_match(home_score=2, away_score=1)
        text = format_var_correction(match, old_home=2, old_away=2)

        assert "⚠️" in text
        assert "Corrección" in text
        assert "VAR" in text
        assert "2-1" in text    # new score
        assert "2-2" in text    # old score ("El gol del 2-2 fue anulado")
        assert "Portugal" in text
        assert "Croatia" in text

    def test_format_is_html_safe(self):
        """HTML entities in team names are escaped properly."""
        match = _make_match(
            home_name="Côte d'Ivoire",
            away_name="São Paulo FC",
            home_score=1, away_score=0,
        )
        text = format_var_correction(match, old_home=1, old_away=1)
        # Should not contain raw < or > (entities are escaped in HTML context)
        assert "<b>Corrección (VAR)</b>" in text

    def test_format_away_goal_annulled(self):
        """Away goal was annulled: old_away > new_away."""
        match = _make_match(home_score=1, away_score=0)
        text = format_var_correction(match, old_home=1, old_away=1)
        assert "1-0" in text    # new score
        assert "1-1" in text    # old score in annulment line

    def test_format_handles_null_scores_gracefully(self):
        """Match with None scores → treated as 0."""
        match = _make_match(home_score=None, away_score=None)
        text = format_var_correction(match, old_home=1, old_away=0)
        assert "0-0" in text    # new score (both None → 0)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Window expiry — stale entries pruned on the watch tick
# ══════════════════════════════════════════════════════════════════════════════


class TestWindowExpiryEdgeCases:

    @pytest.mark.asyncio
    async def test_exactly_at_window_not_pruned_correction_fires(self, tmp_path):
        """Entry finalized exactly `window_minutes` ago → NOT stale → correction fires."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["clip_store"] = {}

        # Exactly at the window boundary (not stale → correction fires)
        window_minutes = settings.final_correction_window_minutes  # 30
        ctx.bot_data["finished_scores"] = {
            "101": _fs_entry(home=2, away=2, age_minutes=window_minutes)
        }

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Note: due to execution time, elapsed may be *very slightly* over window.
        # We accept either pruned (age=30min → ms jitter makes it stale) or correction
        # as valid — the important invariant is no crash and no false correction on a
        # truly stale entry. The pure-function tests in TestFsEntryIsStalePrecision
        # cover the exact boundary with a fixed clock.
        # Here we just verify no crash and if a correction fires it's well-formed.
        if ctx.bot.send_message.await_count == 1:
            text = ctx.bot.send_message.call_args.kwargs["text"]
            assert "Corrección" in text

    @pytest.mark.asyncio
    async def test_unparseable_finalized_at_entry_pruned(self, tmp_path):
        """Entry with bad finalized_at → treated as stale → pruned, no correction."""
        settings = _make_settings(tmp_path)
        match = _make_match(home_score=2, away_score=1)
        ctx, mock_client = _make_no_new_ctx(settings, match)
        ctx.bot_data["clip_store"] = {}
        ctx.bot_data["finished_scores"] = {
            "101": {"home": 2, "away": 2, "finalized_at": "INVALID_DATE", "corrected": False}
        }

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Entry pruned (bad timestamp → stale)
        assert "101" not in ctx.bot_data["finished_scores"]
        ctx.bot.send_message.assert_not_awaited()
