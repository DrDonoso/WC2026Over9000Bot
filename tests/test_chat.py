"""Smoke tests for the chat package.

Tests cover the pure functions in buffer, state, picante, and revive so that
Buffon has clear, confirmed seams to build comprehensive tests on top of.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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
