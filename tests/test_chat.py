"""Smoke tests for the chat package.

Tests cover the pure functions in buffer, state, picante, and revive so that
Buffon has clear, confirmed seams to build comprehensive tests on top of.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.state import ChatState, load_chat_state, save_chat_state
from worldcup_bot.chat.picante import (
    build_picante_user_message,
    cooldown_gate,
    daily_cap_gate,
    min_buffer_gate,
)
from worldcup_bot.chat.revive import (
    build_revive_user_message,
    compute_inactive_candidates,
    is_quiet_hours,
    next_revive_delay,
    select_candidate,
)


# ── RingBuffer ────────────────────────────────────────────────────────────────


class TestRingBuffer:
    _now = datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)

    def _item(self, username: str, text: str) -> dict:
        return dict(username=username, display_name=username.title(),
                    user_id=1, text=text, timestamp=self._now)

    def test_append_and_snapshot_preserves_order(self):
        buf = RingBuffer(maxlen=5)
        buf.append(**self._item("alice", "hola"))
        buf.append(**self._item("bob", "qué tal"))
        snap = buf.snapshot()
        assert len(snap) == 2
        assert snap[0]["username"] == "alice"
        assert snap[1]["text"] == "qué tal"

    def test_maxlen_evicts_oldest(self):
        buf = RingBuffer(maxlen=3)
        for i in range(5):
            buf.append(**self._item(f"u{i}", f"msg{i}"))
        snap = buf.snapshot()
        assert len(snap) == 3
        assert snap[0]["username"] == "u2"  # oldest kept after eviction

    def test_len_reflects_count(self):
        buf = RingBuffer(maxlen=10)
        assert len(buf) == 0
        buf.append(**self._item("x", "test!"))
        assert len(buf) == 1

    def test_snapshot_is_a_copy(self):
        buf = RingBuffer(maxlen=5)
        buf.append(**self._item("alice", "hola"))
        snap1 = buf.snapshot()
        buf.append(**self._item("bob", "hey"))
        snap2 = buf.snapshot()
        assert len(snap1) == 1
        assert len(snap2) == 2


# ── ChatState persistence ─────────────────────────────────────────────────────


class TestChatStatePersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "chat_state.json")
        state = ChatState(
            last_seen={"alice": "2026-06-30T10:00:00+00:00"},
            last_mentioned={"bob": "2026-06-28T08:00:00+00:00"},
            picante_last_ts=1234567.0,
            picante_daily_count=3,
            picante_last_date="2026-06-30",
            rotate_index=7,
        )
        save_chat_state(path, state)
        loaded = load_chat_state(path)
        assert loaded.last_seen == state.last_seen
        assert loaded.last_mentioned == state.last_mentioned
        assert loaded.picante_last_ts == 1234567.0
        assert loaded.picante_daily_count == 3
        assert loaded.picante_last_date == "2026-06-30"
        assert loaded.rotate_index == 7

    def test_load_missing_file_returns_empty_state(self, tmp_path):
        state = load_chat_state(str(tmp_path / "nonexistent.json"))
        assert state.last_seen == {}
        assert state.last_mentioned == {}
        assert state.picante_daily_count == 0
        assert state.rotate_index == 0

    def test_save_creates_parent_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "chat_state.json")
        save_chat_state(path, ChatState())
        assert os.path.exists(path)

    def test_load_corrupt_file_returns_empty_state(self, tmp_path):
        path = tmp_path / "chat_state.json"
        path.write_text("not json at all", encoding="utf-8")
        state = load_chat_state(str(path))
        assert state.last_seen == {}

    def test_atomic_write_uses_tmp_then_replace(self, tmp_path):
        path = str(tmp_path / "chat_state.json")
        save_chat_state(path, ChatState(rotate_index=42))
        # .tmp file should be cleaned up
        assert not os.path.exists(f"{path}.tmp")
        assert os.path.exists(path)


# ── Picante gate functions ────────────────────────────────────────────────────


class TestCooldownGate:
    def test_passes_when_enough_time_elapsed(self):
        assert cooldown_gate(last_ts=1000.0, cooldown_seconds=300, now_ts=1400.0) is True

    def test_blocks_when_too_soon(self):
        assert cooldown_gate(last_ts=1000.0, cooldown_seconds=300, now_ts=1200.0) is False

    def test_exact_boundary_is_allowed(self):
        assert cooldown_gate(last_ts=1000.0, cooldown_seconds=300, now_ts=1300.0) is True

    def test_zero_last_ts_with_large_now_always_passes(self):
        # Realistic scenario: picante_last_ts=0.0 on first run, now >> cooldown
        assert cooldown_gate(last_ts=0.0, cooldown_seconds=300, now_ts=1_000_000) is True


class TestDailyCapGate:
    def test_new_day_always_passes_regardless_of_count(self):
        assert daily_cap_gate(count=999, max_per_day=30, last_date="2026-06-29", today="2026-06-30") is True

    def test_same_day_under_cap(self):
        assert daily_cap_gate(count=5, max_per_day=30, last_date="2026-06-30", today="2026-06-30") is True

    def test_same_day_at_cap_blocks(self):
        assert daily_cap_gate(count=30, max_per_day=30, last_date="2026-06-30", today="2026-06-30") is False

    def test_same_day_over_cap_blocks(self):
        assert daily_cap_gate(count=31, max_per_day=30, last_date="2026-06-30", today="2026-06-30") is False

    def test_empty_last_date_treated_as_new_day(self):
        assert daily_cap_gate(count=30, max_per_day=30, last_date="", today="2026-06-30") is True


class TestMinBufferGate:
    def test_passes_when_at_or_above_min(self):
        assert min_buffer_gate(buffer_len=10, min_buffer=5) is True
        assert min_buffer_gate(buffer_len=5, min_buffer=5) is True  # exact boundary

    def test_blocks_when_below_min(self):
        assert min_buffer_gate(buffer_len=3, min_buffer=5) is False
        assert min_buffer_gate(buffer_len=0, min_buffer=5) is False


class TestPicanteUserMessage:
    def test_formats_messages_as_name_colon_text(self):
        msgs = [
            {"display_name": "Alice", "text": "Hola!"},
            {"display_name": "Bob", "text": "¿Qué tal?"},
        ]
        result = build_picante_user_message(msgs)
        assert "Alice: Hola!" in result
        assert "Bob: ¿Qué tal?" in result

    def test_empty_returns_placeholder(self):
        assert build_picante_user_message([]) == "(sin contexto)"

    def test_falls_back_to_username_when_no_display_name(self):
        msgs = [{"username": "alice", "text": "hola!"}]
        result = build_picante_user_message(msgs)
        assert "alice: hola!" in result


# ── Revive candidate selection ────────────────────────────────────────────────


class TestComputeInactiveCandidates:
    _now = datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)

    def _ts(self, days_ago: float) -> str:
        return (self._now - timedelta(days=days_ago)).isoformat()

    def test_inactive_user_is_candidate(self):
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(4)},
            last_mentioned={},
            porra_usernames=["alice"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_active_user_not_candidate(self):
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(1)},
            last_mentioned={},
            porra_usernames=["alice"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert "alice" not in candidates

    def test_recently_mentioned_excluded(self):
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(10)},
            last_mentioned={"alice": self._ts(1)},
            porra_usernames=["alice"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert "alice" not in candidates

    def test_mention_cooldown_expired_is_candidate(self):
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(10)},
            last_mentioned={"alice": self._ts(3)},  # 3 days ago, cooldown=2
            porra_usernames=["alice"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_non_porra_user_never_candidate(self):
        # "outsider" spoke and is inactive, but is NOT in porra_usernames → never a candidate.
        # "alice" is in porra_usernames but is recently active → not inactive.
        candidates = compute_inactive_candidates(
            last_seen={"outsider": self._ts(5), "alice": self._ts(1)},
            last_mentioned={},
            porra_usernames=["alice"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert "outsider" not in candidates
        assert candidates == []  # alice is active; outsider not in porra_usernames

    def test_result_is_sorted_alphabetically(self):
        candidates = compute_inactive_candidates(
            last_seen={u: self._ts(5) for u in ["charlie", "alice", "bob"]},
            last_mentioned={},
            porra_usernames=["charlie", "alice", "bob"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert candidates == ["alice", "bob", "charlie"]

    def test_blank_username_skipped(self):
        candidates = compute_inactive_candidates(
            last_seen={"": self._ts(10)},
            last_mentioned={},
            porra_usernames=[""],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert candidates == []

    def test_user_seeded_at_startup_not_immediately_inactive(self):
        # Seeded just now — should NOT be inactive yet (0 days < 3 days threshold)
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(0)},
            last_mentioned={},
            porra_usernames=["alice"],
            now=self._now,
            inactive_days=3,
            mention_cooldown_days=2,
        )
        assert "alice" not in candidates


class TestSelectCandidate:
    def test_selects_first_on_zero_index(self):
        username, new_idx = select_candidate(["alice", "bob", "charlie"], rotate_index=0)
        assert username == "alice"
        assert new_idx == 1

    def test_wraps_around_on_overflow(self):
        username, new_idx = select_candidate(["alice", "bob"], rotate_index=2)
        assert username == "alice"  # 2 % 2 == 0
        assert new_idx == 3

    def test_increments_index_each_call(self):
        _, idx1 = select_candidate(["alice"], rotate_index=5)
        assert idx1 == 6

    def test_single_candidate_always_selected(self):
        for i in range(5):
            username, _ = select_candidate(["only_one"], rotate_index=i)
            assert username == "only_one"


class TestReviveUserMessage:
    def test_includes_target_identity(self):
        msg = build_revive_user_message("alice", "Alice Foo", [])
        assert "@alice" in msg
        assert "Alice Foo" in msg

    def test_includes_context_messages(self):
        messages = [{"display_name": "Bob", "text": "¿Qué tal el partido?"}]
        msg = build_revive_user_message("alice", "Alice", messages)
        assert "Bob" in msg
        assert "¿Qué tal el partido?" in msg

    def test_empty_buffer_shows_placeholder(self):
        msg = build_revive_user_message("alice", "Alice", [])
        assert "sin mensajes" in msg


# ── is_quiet_hours ────────────────────────────────────────────────────────────


class TestIsQuietHours:
    def test_no_window_when_start_equals_end(self):
        assert is_quiet_hours(3, 6, 6) is False
        assert is_quiet_hours(23, 23, 23) is False

    def test_midnight_wrap_inside(self):
        # quiet 23->06: hours 23, 0, 5 are quiet
        assert is_quiet_hours(23, 23, 6) is True
        assert is_quiet_hours(0, 23, 6) is True
        assert is_quiet_hours(5, 23, 6) is True

    def test_midnight_wrap_outside(self):
        # hours 6..22 are NOT quiet for 23->06
        assert is_quiet_hours(6, 23, 6) is False
        assert is_quiet_hours(12, 23, 6) is False
        assert is_quiet_hours(22, 23, 6) is False

    def test_same_day_window(self):
        # quiet 01->06: hours 1..5 quiet, 0 and 6 not
        assert is_quiet_hours(1, 1, 6) is True
        assert is_quiet_hours(5, 1, 6) is True
        assert is_quiet_hours(0, 1, 6) is False
        assert is_quiet_hours(6, 1, 6) is False


# ── next_revive_delay ─────────────────────────────────────────────────────────


class TestNextReviveDelay:
    def _now(self, hour: int = 14) -> datetime:
        import pytz
        tz = pytz.timezone("Europe/Madrid")
        return tz.localize(datetime(2026, 6, 30, hour, 0, 0))

    def test_no_quiet_window_returns_base_plus_jitter(self):
        delay = next_revive_delay(
            base_seconds=14400,
            jitter_seconds=2700,
            now_local=self._now(14),
            quiet_start=6,
            quiet_end=6,   # no window
            rand=lambda a, b: 0.0,
        )
        assert delay == 14400.0

    def test_jitter_added(self):
        delay = next_revive_delay(
            base_seconds=14400,
            jitter_seconds=2700,
            now_local=self._now(14),
            quiet_start=6,
            quiet_end=6,
            rand=lambda a, b: 1234.0,
        )
        assert delay == 15634.0

    def test_minimum_delay_clamped_to_60(self):
        # negative jitter would normally make delay = 14400 - 14400 = 0
        delay = next_revive_delay(
            base_seconds=100,
            jitter_seconds=100,
            now_local=self._now(14),
            quiet_start=6,
            quiet_end=6,
            rand=lambda a, b: -100.0,
        )
        assert delay == 60.0

    def test_target_in_quiet_hours_pushed_to_wake_time(self):
        # base=3600, no jitter → target = 15:00; quiet window 14->17
        # should push to 17:00 + spread
        delay = next_revive_delay(
            base_seconds=3600,
            jitter_seconds=2700,
            now_local=self._now(14),
            quiet_start=14,
            quiet_end=17,
            rand=lambda a, b: 0.0,  # first call for jitter returns 0, second for spread returns 0
        )
        # target = 14:00 + 3600s = 15:00 which is in quiet(14->17)
        # pushed to 17:00 same day → delay from 14:00 = 3*3600 = 10800s
        assert delay == pytest.approx(10800.0, abs=1.0)


# ── ChatState eager persistence ───────────────────────────────────────────────


def _make_listener_update_ctx(state_path: str):
    """Minimal (update, context) for on_group_text listener tests."""
    from worldcup_bot.config import Settings

    msg = MagicMock()
    msg.text = "Hola equipo!"
    msg.chat_id = -1001234567890
    msg.photo = msg.video = msg.animation = msg.sticker = None
    msg.document = msg.voice = msg.video_note = msg.audio = None

    user = MagicMock()
    user.id = 42
    user.username = "testuser"
    user.full_name = "Test User"

    update = MagicMock()
    update.effective_message = msg
    update.message = msg
    update.effective_user = user

    settings = Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567890",
    )

    ctx = MagicMock()
    ctx.bot.id = 999
    ctx.bot_data = {
        "settings": settings,
        "chat_buffer": RingBuffer(maxlen=10),
        "chat_state": ChatState(),
        "chat_state_path": state_path,
        "ai_client": None,
    }
    return update, ctx


class TestChatStateEagerPersist:
    """Listener writes chat_state.json on every qualifying message."""

    @pytest.mark.asyncio
    async def test_qualifying_message_writes_state_file(self, tmp_path):
        """A qualifying message must write last_seen to chat_state.json."""
        from worldcup_bot.chat.listener import on_group_text

        state_file = str(tmp_path / "chat_state.json")
        update, ctx = _make_listener_update_ctx(state_file)

        await on_group_text(update, ctx)

        loaded = load_chat_state(state_file)
        assert "testuser" in loaded.last_seen
        assert loaded.last_seen["testuser"]  # non-empty ISO timestamp

    @pytest.mark.asyncio
    async def test_missing_state_path_key_does_not_raise(self, tmp_path):
        """If chat_state_path is absent from bot_data the save is skipped silently."""
        from worldcup_bot.chat.listener import on_group_text

        update, ctx = _make_listener_update_ctx(str(tmp_path / "chat_state.json"))
        del ctx.bot_data["chat_state_path"]

        await on_group_text(update, ctx)  # must not raise

        # last_seen still updated in memory
        assert "testuser" in ctx.bot_data["chat_state"].last_seen

    def test_startup_save_writes_seeded_participants(self, tmp_path):
        """Startup save_chat_state call persists seeded participants immediately."""
        state_file = str(tmp_path / "chat_state.json")
        state = ChatState()
        now_iso = datetime.now(timezone.utc).isoformat()
        state.last_seen["alice"] = now_iso
        state.last_seen["bob"] = now_iso

        save_chat_state(state_file, state)

        loaded = load_chat_state(state_file)
        assert "alice" in loaded.last_seen
        assert "bob" in loaded.last_seen

