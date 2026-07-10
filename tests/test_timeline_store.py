"""Tests for the chronological group message timeline (timeline_store.py).

Covers:
- append_message: writes a JSONL line; no-op on empty username or store_text=False
- Trim-on-write: discards entries older than window_days (injectable _now)
- load_since: filters by ts; since_ts=None returns all; missing/corrupt → []
- last_run round-trip: save_last_run / load_last_run
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import worldcup_bot.chat.timeline_store as ts_mod
from worldcup_bot.chat.timeline_store import (
    append_message,
    load_last_run,
    load_since,
    save_last_run,
)

_UTC = timezone.utc
_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=_UTC)
_FRESH_TS = _NOW - timedelta(hours=1)   # clearly within any 2-day window
_OLD_TS = _NOW - timedelta(days=5)      # clearly outside 2-day window


# ── append_message ────────────────────────────────────────────────────────────


class TestAppendMessageWrites:
    def test_writes_one_jsonl_line(self, tmp_path):
        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(str(tmp_path), "alice", "hola mundo", _FRESH_TS)
        lines = (tmp_path / "picante_timeline.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["username"] == "alice"
        assert entry["text"] == "hola mundo"
        assert "2026-07-10T11:00:00" in entry["ts"]

    def test_multiple_appends_write_multiple_lines(self, tmp_path):
        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(str(tmp_path), "alice", "primero", _FRESH_TS)
            append_message(str(tmp_path), "bob", "segundo", _FRESH_TS)
        lines = (tmp_path / "picante_timeline.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["username"] == "alice"
        assert json.loads(lines[1])["username"] == "bob"

    def test_creates_state_dir_if_missing(self, tmp_path):
        state_dir = str(tmp_path / "nested" / "subdir")
        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(state_dir, "alice", "hola", _FRESH_TS)
        assert os.path.exists(os.path.join(state_dir, "picante_timeline.jsonl"))

    def test_entry_includes_ts_username_text_keys(self, tmp_path):
        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(str(tmp_path), "carlos", "prueba", _FRESH_TS)
        entry = json.loads(
            (tmp_path / "picante_timeline.jsonl").read_text(encoding="utf-8").strip()
        )
        assert set(entry.keys()) >= {"ts", "username", "text"}


class TestAppendMessageNoOp:
    def test_noop_when_username_empty_string(self, tmp_path):
        append_message(str(tmp_path), "", "texto importante", _FRESH_TS)
        assert not (tmp_path / "picante_timeline.jsonl").exists()

    def test_noop_when_store_text_false(self, tmp_path):
        append_message(str(tmp_path), "alice", "texto", _FRESH_TS, store_text=False)
        assert not (tmp_path / "picante_timeline.jsonl").exists()

    def test_noop_store_text_false_does_not_raise(self, tmp_path):
        # Must silently do nothing
        result = append_message(str(tmp_path), "alice", "texto", _FRESH_TS, store_text=False)
        assert result is None

    def test_best_effort_never_raises_on_write_failure(self, tmp_path):
        """Even if the underlying write fails, append_message must not propagate."""
        with patch("worldcup_bot.chat.timeline_store.open", side_effect=PermissionError("denied")):
            # Should not raise
            append_message(str(tmp_path), "alice", "texto", _FRESH_TS)


# ── trim-on-write ─────────────────────────────────────────────────────────────


class TestTrimOnWrite:
    def test_trim_discards_entries_older_than_window(self, tmp_path):
        """Old entries (> window_days old) must be dropped on the next append."""
        timeline_path = tmp_path / "picante_timeline.jsonl"
        old_entry = json.dumps({"ts": _OLD_TS.isoformat(), "username": "old_user", "text": "viejo"})
        timeline_path.write_text(old_entry + "\n", encoding="utf-8")

        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(str(tmp_path), "alice", "nuevo", _FRESH_TS, window_days=2)

        entries = [
            json.loads(l)
            for l in timeline_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        usernames = [e["username"] for e in entries]
        assert "old_user" not in usernames
        assert "alice" in usernames

    def test_trim_keeps_entries_within_window(self, tmp_path):
        """Entries clearly within the window are NOT discarded."""
        timeline_path = tmp_path / "picante_timeline.jsonl"
        recent_ts = _NOW - timedelta(hours=6)
        recent_entry = json.dumps({"ts": recent_ts.isoformat(), "username": "kept", "text": "ok"})
        timeline_path.write_text(recent_entry + "\n", encoding="utf-8")

        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(str(tmp_path), "alice", "nuevo", _FRESH_TS, window_days=2)

        entries = [
            json.loads(l)
            for l in timeline_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        usernames = [e["username"] for e in entries]
        assert "kept" in usernames
        assert "alice" in usernames

    def test_trim_at_exact_boundary_discards_entry(self, tmp_path):
        """Entries exactly at window_days old (ts < cutoff strictly) are removed."""
        timeline_path = tmp_path / "picante_timeline.jsonl"
        boundary_ts = _NOW - timedelta(days=2, seconds=1)  # just over 2 days
        entry = json.dumps({"ts": boundary_ts.isoformat(), "username": "boundary_user", "text": "x"})
        timeline_path.write_text(entry + "\n", encoding="utf-8")

        with patch("worldcup_bot.chat.timeline_store._now", new=lambda: _NOW):
            append_message(str(tmp_path), "alice", "nuevo", _FRESH_TS, window_days=2)

        entries = [
            json.loads(l)
            for l in timeline_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        usernames = [e["username"] for e in entries]
        assert "boundary_user" not in usernames


# ── load_since ────────────────────────────────────────────────────────────────


class TestLoadSince:
    def test_returns_empty_when_file_missing(self, tmp_path):
        result = load_since(str(tmp_path), None)
        assert result == []

    def test_returns_all_when_since_ts_is_none(self, tmp_path):
        t1 = datetime(2026, 7, 9, 10, 0, 0, tzinfo=_UTC)
        t2 = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            json.dumps({"ts": t1.isoformat(), "username": "a", "text": "msg1"}) + "\n"
            + json.dumps({"ts": t2.isoformat(), "username": "b", "text": "msg2"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), None)
        assert len(result) == 2

    def test_filters_entries_before_since_ts(self, tmp_path):
        t_old = datetime(2026, 7, 8, 10, 0, 0, tzinfo=_UTC)
        t_new = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        since = datetime(2026, 7, 9, 0, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            json.dumps({"ts": t_old.isoformat(), "username": "old_u", "text": "old"}) + "\n"
            + json.dumps({"ts": t_new.isoformat(), "username": "new_u", "text": "new"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), since)
        assert len(result) == 1
        assert result[0]["username"] == "new_u"

    def test_since_ts_boundary_is_exclusive(self, tmp_path):
        """Entries with ts == since_ts are NOT included (strict >)."""
        exact_ts = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            json.dumps({"ts": exact_ts.isoformat(), "username": "exact", "text": "boundary"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), exact_ts)
        assert result == []

    def test_one_second_after_since_ts_is_included(self, tmp_path):
        since = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        one_second_after = since + timedelta(seconds=1)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            json.dumps({"ts": one_second_after.isoformat(), "username": "after", "text": "ok"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), since)
        assert len(result) == 1
        assert result[0]["username"] == "after"

    def test_corrupt_lines_skipped_no_raise(self, tmp_path):
        t_valid = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            "NOT_VALID_JSON\n"
            + json.dumps({"ts": t_valid.isoformat(), "username": "ok", "text": "good"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), None)
        assert len(result) == 1
        assert result[0]["username"] == "ok"

    def test_fully_corrupt_file_returns_empty_no_raise(self, tmp_path):
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text("totally garbage content here\n", encoding="utf-8")
        result = load_since(str(tmp_path), None)
        # All lines are corrupt → empty result, no exception
        assert isinstance(result, list)

    def test_returned_dicts_have_ts_username_text_keys(self, tmp_path):
        ts = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            json.dumps({"ts": ts.isoformat(), "username": "alice", "text": "hola"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), None)
        assert len(result) == 1
        assert "ts" in result[0]
        assert "username" in result[0]
        assert "text" in result[0]

    def test_naive_ts_in_file_treated_as_utc(self, tmp_path):
        """Stored entries without tzinfo are treated as UTC."""
        naive_iso = "2026-07-10T10:00:00"  # no +00:00
        since = datetime(2026, 7, 9, 0, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            json.dumps({"ts": naive_iso, "username": "naive_u", "text": "msg"}) + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), since)
        assert len(result) == 1
        assert result[0]["username"] == "naive_u"

    def test_empty_lines_in_file_are_skipped(self, tmp_path):
        ts = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
        timeline_path = tmp_path / "picante_timeline.jsonl"
        timeline_path.write_text(
            "\n\n"
            + json.dumps({"ts": ts.isoformat(), "username": "alice", "text": "msg"}) + "\n"
            + "\n",
            encoding="utf-8",
        )
        result = load_since(str(tmp_path), None)
        assert len(result) == 1


# ── load_last_run / save_last_run ─────────────────────────────────────────────


class TestLastRunRoundTrip:
    def test_missing_file_returns_none(self, tmp_path):
        result = load_last_run(str(tmp_path))
        assert result is None

    def test_save_then_load_returns_same_timestamp(self, tmp_path):
        ts = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)
        save_last_run(str(tmp_path), ts)
        loaded = load_last_run(str(tmp_path))
        assert loaded is not None
        assert loaded.year == 2026
        assert loaded.month == 7
        assert loaded.day == 10
        assert loaded.hour == 4

    def test_save_is_atomic_no_tmp_file_left(self, tmp_path):
        ts = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)
        save_last_run(str(tmp_path), ts)
        assert (tmp_path / "picante_profiles_last_run.json").exists()
        assert not (tmp_path / "picante_profiles_last_run.json.tmp").exists()

    def test_corrupt_last_run_file_returns_none(self, tmp_path):
        (tmp_path / "picante_profiles_last_run.json").write_text("garbage", encoding="utf-8")
        result = load_last_run(str(tmp_path))
        assert result is None

    def test_loaded_timestamp_is_timezone_aware(self, tmp_path):
        ts = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)
        save_last_run(str(tmp_path), ts)
        loaded = load_last_run(str(tmp_path))
        assert loaded is not None
        assert loaded.tzinfo is not None

    def test_save_creates_state_dir_if_missing(self, tmp_path):
        state_dir = str(tmp_path / "new_dir")
        ts = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)
        save_last_run(state_dir, ts)
        assert os.path.exists(os.path.join(state_dir, "picante_profiles_last_run.json"))

    def test_save_last_run_best_effort_no_raise_on_failure(self, tmp_path):
        """save_last_run must swallow errors, never propagate."""
        ts = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)
        with patch("worldcup_bot.chat.timeline_store.open", side_effect=PermissionError("denied")):
            save_last_run(str(tmp_path), ts)  # must not raise

    def test_overwrite_saves_new_value(self, tmp_path):
        ts1 = datetime(2026, 7, 9, 4, 0, 0, tzinfo=_UTC)
        ts2 = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)
        save_last_run(str(tmp_path), ts1)
        save_last_run(str(tmp_path), ts2)
        loaded = load_last_run(str(tmp_path))
        assert loaded is not None
        assert loaded.day == 10
