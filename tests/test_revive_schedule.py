"""Edge-case tests for quiet-hours + jitter scheduling in chat/revive.py.

Covers the three new pure helpers and the rescheduling behaviour of
revive_inactive_job:

  is_quiet_hours   — all 16 spec-document boundary vectors (parametrized)
  next_revive_delay — clamp, midnight-wrap push, same-day push, spread bounds,
                      cross-midnight date arithmetic, target-at-quiet_end
  schedule_next_revive — job_queue.run_once called with correct args/name
  revive_inactive_job  — quiet-skip (no send, always reschedules),
                         ALWAYS-RESCHEDULE on every exit path (success /
                         no-candidates / AIError / unexpected Exception),
                         exactly-one run_once per execution,
                         revive-disabled and settings-missing paths do NOT
                         reschedule.
"""

from __future__ import annotations

import datetime as _dt
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytz
import pytest

from worldcup_bot.ai.client import AIError
from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.revive import (
    is_quiet_hours,
    next_revive_delay,
    revive_inactive_job,
    schedule_next_revive,
)
from worldcup_bot.chat.state import ChatState
from worldcup_bot.config import Settings


# ── helpers ───────────────────────────────────────────────────────────────────

_GROUP_ID = "-1001234567"
_TZ_MADRID = pytz.timezone("Europe/Madrid")


def _ai_settings(**overrides) -> Settings:
    base: dict = dict(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id=_GROUP_ID,
        openai_api_key="sk-test",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt-test",
        chat_revive_enabled=True,
        revive_inactive_days=3,
        revive_mention_cooldown_days=2,
        # quiet window defaults from Settings: 23→6
    )
    base.update(overrides)
    return Settings(**base)


def _make_ctx(
    settings: Settings | None = None,
    porra_usernames: list[str] | None = None,
    last_seen: dict[str, str] | None = None,
    state_path: str = "",
    ai_reply: str = "¡Vuelve, te echamos de menos!",
) -> MagicMock:
    """Build a context mock suitable for revive_inactive_job tests."""
    if settings is None:
        settings = _ai_settings()
    state = ChatState(last_seen=last_seen or {})
    buf = RingBuffer(maxlen=10)

    ai_client = MagicMock()
    ai_client.complete = AsyncMock(return_value=ai_reply)

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot_data = {
        "settings": settings,
        "chat_state": state,
        "chat_state_path": state_path,
        "chat_buffer": buf,
        "porra_usernames": porra_usernames or [],
        "porra_display_names": {},
        "ai_client": ai_client,
    }
    return ctx


def _inactive_ts(days: float = 5.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _local(hour: int, minute: int = 0, day: int = 30) -> datetime:
    """Return a Madrid-localised datetime on 2026-06-day at hour:minute."""
    return _TZ_MADRID.localize(_dt.datetime(2026, 6, day, hour, minute, 0))


def _frozen_datetime_cls(hour: int, minute: int = 0) -> type:
    """Return a datetime subclass whose .now() always returns 2026-06-30 HH:MM Madrid."""
    frozen = _local(hour, minute)

    class _FrozenDt(_dt.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return frozen.astimezone(tz)
            return frozen

    return _FrozenDt


# ── is_quiet_hours — all boundary vectors ─────────────────────────────────────


class TestIsQuietHoursBoundaries:
    @pytest.mark.parametrize("hour, qs, qe, expected", [
        # ── Wrap window 23→6 (start inclusive, end exclusive) ──────────────
        (23, 23, 6, True),   # start boundary → inside
        (0,  23, 6, True),   # midnight → inside wrap
        (3,  23, 6, True),   # 3 am → inside wrap
        (5,  23, 6, True),   # just before end → inside
        (6,  23, 6, False),  # end boundary → exclusive, outside
        (7,  23, 6, False),  # one past end → outside
        (12, 23, 6, False),  # midday → outside
        (22, 23, 6, False),  # just before start → outside
        # ── Non-wrap / same-day window 1→5 ─────────────────────────────────
        (1,  1,  5, True),   # start boundary → inside
        (4,  1,  5, True),   # middle → inside
        (0,  1,  5, False),  # before start → outside
        (5,  1,  5, False),  # end boundary → exclusive, outside
        (6,  1,  5, False),  # past end → outside
        # ── No quiet window (start == end) — always False ──────────────────
        (0,  0,  0, False),
        (3,  6,  6, False),  # spec example
        (12, 12, 12, False),
    ])
    def test_spec_vectors(self, hour, qs, qe, expected):
        assert is_quiet_hours(hour, qs, qe) is expected

    def test_wrap_window_all_outside_hours_not_quiet(self):
        """Hours 6-22 are all outside the 23→6 wrap window."""
        for h in range(6, 23):
            assert is_quiet_hours(h, 23, 6) is False, f"hour {h} should be outside 23→6"

    def test_wrap_window_inside_hours_are_quiet(self):
        """Hours 23,0,1,2,3,4,5 are all inside the 23→6 wrap window."""
        inside = [23] + list(range(0, 6))
        for h in inside:
            assert is_quiet_hours(h, 23, 6) is True, f"hour {h} should be inside 23→6"

    def test_same_day_window_exact_boundaries(self):
        """Same-day window 2→8: hours 2-7 quiet, 1 and 8 not."""
        assert is_quiet_hours(2, 2, 8) is True
        assert is_quiet_hours(7, 2, 8) is True
        assert is_quiet_hours(1, 2, 8) is False
        assert is_quiet_hours(8, 2, 8) is False  # exclusive end


# ── next_revive_delay — edge cases ────────────────────────────────────────────


class TestNextReviveDelayEdgeCases:
    """
    All tests inject a deterministic `rand` so results are exact.

    The function calls rand TWICE when quiet-push applies:
      1. rand(-jitter, +jitter)  → initial delay jitter
      2. rand(0, jitter)         → spread past quiet_end

    Using lambda a, b: 0.0  → zero jitter, zero spread (minimum path)
    Using lambda a, b: b    → max jitter, max spread
    Using lambda a, b: (a+b)/2 → mid values
    """

    def test_no_quiet_window_zero_jitter_returns_exact_base(self):
        delay = next_revive_delay(
            base_seconds=14400, jitter_seconds=0,
            now_local=_local(14), quiet_start=6, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        assert delay == 14400.0

    def test_positive_jitter_increases_delay(self):
        delay = next_revive_delay(
            base_seconds=14400, jitter_seconds=2700,
            now_local=_local(14), quiet_start=6, quiet_end=6,
            rand=lambda a, b: 1000.0,
        )
        assert delay == pytest.approx(15400.0)

    def test_large_negative_jitter_clamped_to_60(self):
        """base - max_jitter = 100 - 200 = -100 → clamped to 60."""
        delay = next_revive_delay(
            base_seconds=100, jitter_seconds=200,
            now_local=_local(14), quiet_start=6, quiet_end=6,
            rand=lambda a, b: -200.0,
        )
        assert delay == 60.0

    def test_zero_jitter_always_returns_exact_base_no_push_needed(self):
        """jitter=0, target at 18:00 (not quiet) → exactly base."""
        delay = next_revive_delay(
            base_seconds=14400, jitter_seconds=0,
            now_local=_local(14), quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        assert delay == 14400.0

    def test_daytime_target_not_pushed(self):
        """now=10:00, base=4h → target 14:00, quiet=23→6: 14:00 not quiet → no push."""
        delay = next_revive_delay(
            base_seconds=14400, jitter_seconds=0,
            now_local=_local(10), quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        assert delay == 14400.0

    def test_midnight_wrap_push_target_at_midnight(self):
        """now=23:30, base=1800s → target=00:00 next day → inside 23→6 → pushed to 06:00.

        Expected delay = 6.5h = 23400s.
        """
        delay = next_revive_delay(
            base_seconds=1800, jitter_seconds=0,
            now_local=_local(23, 30), quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        assert delay == pytest.approx(23400.0, abs=1.0)

    def test_midnight_wrap_push_from_evening_target(self):
        """now=22:00, base=3600s → target=23:00 → inside wrap → pushed to 06:00 NEXT day.

        wake=today 06:00 <= target 23:00 → add one day → wake=next 06:00.
        Delay = 8h = 28800s.
        """
        delay = next_revive_delay(
            base_seconds=3600, jitter_seconds=0,
            now_local=_local(22), quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        assert delay == pytest.approx(28800.0, abs=1.0)

    def test_same_day_window_push(self):
        """now=10:00, base=3600s, quiet=11→14 → target=11:00 → pushed to 14:00.

        Delay = 4h = 14400s.
        """
        delay = next_revive_delay(
            base_seconds=3600, jitter_seconds=0,
            now_local=_local(10), quiet_start=11, quiet_end=14,
            rand=lambda a, b: 0.0,
        )
        assert delay == pytest.approx(14400.0, abs=1.0)

    def test_target_exactly_at_quiet_end_not_pushed(self):
        """now=00:00, base=6h, quiet=23→6 → target=06:00 → is_quiet(6,23,6)=False → no push."""
        delay = next_revive_delay(
            base_seconds=21600, jitter_seconds=0,
            now_local=_local(0), quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        assert delay == pytest.approx(21600.0, abs=1.0)
        # Verify no push: target=06:00 is NOT in quiet window
        assert not is_quiet_hours(6, 23, 6)

    @pytest.mark.parametrize("rand_fn, label", [
        (lambda a, b: 0.0,       "min"),
        (lambda a, b: b,         "max"),
        (lambda a, b: (a + b)/2, "mid"),
    ])
    def test_pushed_target_always_outside_quiet_window(self, rand_fn, label):
        """For any rand value in [min, max], the pushed target must not be in quiet hours."""
        now = _local(23, 30)
        delay = next_revive_delay(
            base_seconds=3600, jitter_seconds=2700,
            now_local=now, quiet_start=23, quiet_end=6,
            rand=rand_fn,
        )
        target = now + timedelta(seconds=delay)
        assert not is_quiet_hours(target.hour, 23, 6), (
            f"Pushed target (rand={label}) landed in quiet hours: {target}"
        )

    @pytest.mark.parametrize("rand_fn", [
        lambda a, b: 0.0,    # zero spread
        lambda a, b: b,      # max spread
    ])
    def test_spread_additive_never_before_quiet_end(self, rand_fn):
        """Pushed target is at quiet_end:00 or later — never back in the night."""
        now = _local(23, 30)
        delay = next_revive_delay(
            base_seconds=3600, jitter_seconds=2700,
            now_local=now, quiet_start=23, quiet_end=6,
            rand=rand_fn,
        )
        target = now + timedelta(seconds=delay)
        # target must be at or after 06:00 (on its date)
        wake_floor = target.replace(hour=6, minute=0, second=0, microsecond=0)
        assert target >= wake_floor, (
            f"Pushed target {target} falls before quiet_end 06:00"
        )

    def test_cross_midnight_next_day_date_correct(self):
        """now=23:30, pushed target must be on the NEXT calendar day at 06:xx."""
        now = _local(23, 30)
        delay = next_revive_delay(
            base_seconds=3600, jitter_seconds=0,
            now_local=now, quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        target = now + timedelta(seconds=delay)
        # Should be 2026-07-01 06:00
        assert target.day == 1
        assert target.month == 7
        assert target.hour == 6

    def test_large_base_no_push_when_target_outside_window(self):
        """base=86400s (1 day), now=10:00, target=10:00 next day → not quiet → no push."""
        delay = next_revive_delay(
            base_seconds=86400, jitter_seconds=0,
            now_local=_local(10), quiet_start=23, quiet_end=6,
            rand=lambda a, b: 0.0,
        )
        # target = 10:00 next day → not in 23→6 quiet window → no push
        assert delay == pytest.approx(86400.0, abs=1.0)


# ── schedule_next_revive ──────────────────────────────────────────────────────


class TestScheduleNextRevive:
    def test_calls_run_once_with_revive_inactive_job(self):
        jq = MagicMock()
        settings = _ai_settings()
        with patch("worldcup_bot.chat.revive.next_revive_delay", return_value=99.0):
            schedule_next_revive(jq, settings)
        jq.run_once.assert_called_once()
        assert jq.run_once.call_args.args[0] is revive_inactive_job

    def test_calls_run_once_with_name_revive_inactive(self):
        jq = MagicMock()
        settings = _ai_settings()
        with patch("worldcup_bot.chat.revive.next_revive_delay", return_value=99.0):
            schedule_next_revive(jq, settings)
        assert jq.run_once.call_args.kwargs["name"] == "revive_inactive"

    def test_when_kwarg_matches_computed_delay(self):
        jq = MagicMock()
        settings = _ai_settings()
        with patch("worldcup_bot.chat.revive.next_revive_delay", return_value=12345.0):
            schedule_next_revive(jq, settings)
        assert jq.run_once.call_args.kwargs["when"] == pytest.approx(12345.0)

    def test_called_exactly_once(self):
        jq = MagicMock()
        settings = _ai_settings()
        with patch("worldcup_bot.chat.revive.next_revive_delay", return_value=500.0):
            schedule_next_revive(jq, settings)
        assert jq.run_once.call_count == 1

    def test_without_patching_delay_is_at_least_60_seconds(self):
        """Smoke: even without patching, the returned delay is clamped to >= 60s."""
        jq = MagicMock()
        settings = _ai_settings()
        schedule_next_revive(jq, settings)
        when = jq.run_once.call_args.kwargs["when"]
        assert when >= 60.0


# ── revive_inactive_job — rescheduling on every exit path ────────────────────


class TestReviveInactiveJobReschedule:
    """Every exit path through revive_inactive_job must trigger exactly one
    job_queue.run_once (ALWAYS-RESCHEDULE contract) — unless revive is disabled
    or settings are unavailable.
    """

    # ── quiet-hours skip ──────────────────────────────────────────────────────

    async def test_quiet_skip_no_send_but_reschedules(self, tmp_path):
        """When inside quiet hours: no send_message, but run_once IS called once."""
        # Freeze datetime.now to 23:30 Madrid (inside 23→6 quiet window)
        _QuietDt = _frozen_datetime_cls(23, 30)
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        with patch("worldcup_bot.chat.revive.datetime", _QuietDt):
            await revive_inactive_job(ctx)

        ctx.bot.send_message.assert_not_called()
        ctx.job_queue.run_once.assert_called_once()

    async def test_quiet_skip_reschedules_with_correct_job_name(self, tmp_path):
        """The reschedule spawned during quiet skip uses the canonical job name."""
        _QuietDt = _frozen_datetime_cls(23, 30)
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        with patch("worldcup_bot.chat.revive.datetime", _QuietDt):
            await revive_inactive_job(ctx)

        name = ctx.job_queue.run_once.call_args.kwargs.get("name")
        assert name == "revive_inactive"

    # ── ALWAYS-RESCHEDULE on every non-disabled exit path ────────────────────

    async def test_success_path_reschedules(self, tmp_path):
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_called_once()   # confirm it was a real run
        ctx.job_queue.run_once.assert_called_once()

    async def test_no_candidates_reschedules(self, tmp_path):
        """No inactive candidates → no send, but still reschedules."""
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": datetime.now(timezone.utc).isoformat()},  # just seen
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()
        ctx.job_queue.run_once.assert_called_once()

    async def test_ai_error_reschedules(self, tmp_path):
        """AIError during AI call must not prevent rescheduling."""
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"].complete = AsyncMock(side_effect=AIError("rate limit"))
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()
        ctx.job_queue.run_once.assert_called_once()

    async def test_unexpected_exception_reschedules(self, tmp_path):
        """A generic Exception must not prevent rescheduling."""
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"].complete = AsyncMock(
            side_effect=RuntimeError("chaos")
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()
        ctx.job_queue.run_once.assert_called_once()

    # ── NO DOUBLE-SCHEDULE ────────────────────────────────────────────────────

    async def test_exactly_one_run_once_per_execution_on_success(self, tmp_path):
        """The finally block must not schedule twice even on a clean success run."""
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        assert ctx.job_queue.run_once.call_count == 1

    async def test_exactly_one_run_once_on_ai_error(self, tmp_path):
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"].complete = AsyncMock(side_effect=AIError("oops"))
        await revive_inactive_job(ctx)
        assert ctx.job_queue.run_once.call_count == 1

    # ── conditions that PREVENT rescheduling ──────────────────────────────────

    async def test_revive_disabled_no_reschedule(self, tmp_path):
        """revive_enabled() is False → early return AND finally skips scheduling."""
        settings = Settings(
            telegram_bot_token="tok", football_data_api_key="key",
            telegram_group_id=_GROUP_ID,
            chat_revive_enabled=True,
            # No openai fields → ai_enabled() = False → revive_enabled() = False
        )
        ctx = _make_ctx(
            settings=settings,
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.job_queue.run_once.assert_not_called()

    async def test_chat_revive_flag_false_no_reschedule(self, tmp_path):
        """chat_revive_enabled=False: even with AI configured, no scheduling."""
        settings = _ai_settings(chat_revive_enabled=False)
        ctx = _make_ctx(
            settings=settings,
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.job_queue.run_once.assert_not_called()

    async def test_settings_key_missing_no_reschedule(self):
        """If bot_data has no 'settings' key, settings stays None and finally skips."""
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        ctx.bot_data = {}   # KeyError on ["settings"]
        await revive_inactive_job(ctx)
        ctx.job_queue.run_once.assert_not_called()

    # ── ai_client is None but revive IS enabled → still reschedules ──────────

    async def test_ai_client_none_but_revive_enabled_reschedules(self, tmp_path):
        """When ai_client is None in bot_data, the job returns early BUT
        settings is not None and revive_enabled() is True, so the finally
        block DOES reschedule (the loop continues so it can pick up the client
        once it's available again).
        """
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"] = None  # override
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()
        ctx.job_queue.run_once.assert_called_once()

    # ── reschedule job passes correct first arg ───────────────────────────────

    async def test_reschedule_passes_revive_inactive_job_as_callable(self, tmp_path):
        """The run_once first argument must be the revive_inactive_job coroutine."""
        ctx = _make_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": _inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        callable_arg = ctx.job_queue.run_once.call_args.args[0]
        assert callable_arg is revive_inactive_job
