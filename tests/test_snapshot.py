"""Tests for worldcup_bot.ai.snapshot.

Covers: load_snapshots, save_snapshots (including degradation on unwritable path),
compute_movements, and update_and_diff (round-trip, pruning, missing file, first run).
All filesystem ops use pytest's tmp_path for isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldcup_bot.ai.snapshot import (
    Movement,
    compute_movements,
    load_snapshots,
    save_snapshots,
    update_and_diff,
)


# ── load_snapshots ────────────────────────────────────────────────────────────


class TestLoadSnapshots:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        path = str(tmp_path / "no_such_file.json")
        assert load_snapshots(path) == {}

    def test_returns_data_from_valid_json(self, tmp_path):
        data = {"2026-06-15": {"user1": 1, "user2": 2}}
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        assert load_snapshots(str(p)) == data

    def test_returns_empty_dict_on_malformed_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {{{", encoding="utf-8")
        assert load_snapshots(str(p)) == {}

    def test_does_not_raise_on_missing_file(self, tmp_path):
        # Verify it genuinely doesn't raise (test is redundant but explicit)
        result = load_snapshots(str(tmp_path / "ghost.json"))
        assert isinstance(result, dict)


# ── save_snapshots ────────────────────────────────────────────────────────────


class TestSaveSnapshots:
    def test_round_trip(self, tmp_path):
        data = {"2026-06-15": {"alice": 1, "bob": 2}}
        path = str(tmp_path / "state.json")
        save_snapshots(path, data)
        assert load_snapshots(path) == data

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "snap.json"
        save_snapshots(str(nested), {"x": {}})
        assert nested.exists()

    def test_overwrites_existing_file(self, tmp_path):
        p = tmp_path / "snap.json"
        save_snapshots(str(p), {"old": {}})
        save_snapshots(str(p), {"new": {}})
        assert load_snapshots(str(p)) == {"new": {}}

    def test_no_crash_on_unwritable_path(self, tmp_path):
        """Saving to an invalid path must NOT raise; it just logs a warning."""
        # Use a path whose parent is a file (can't create a dir on top of a file)
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file", encoding="utf-8")
        bad_path = str(blocker / "snap.json")
        save_snapshots(bad_path, {"data": {}})  # must not raise


# ── compute_movements ─────────────────────────────────────────────────────────


class TestComputeMovements:
    def test_climbed_user(self):
        baseline = {"u1": 3, "u2": 1}
        current = {"u1": 1, "u2": 2}
        names = {"u1": "Alice", "u2": "Bob"}
        movements = compute_movements(baseline, current, names)
        alice = next(m for m in movements if m.username == "u1")
        assert alice.old_pos == 3
        assert alice.new_pos == 1
        assert alice.delta == 2  # climbed

    def test_dropped_user(self):
        baseline = {"u1": 1}
        current = {"u1": 3}
        names = {"u1": "Alice"}
        movements = compute_movements(baseline, current, names)
        assert len(movements) == 1
        assert movements[0].delta == -2  # dropped

    def test_no_change_excluded(self):
        baseline = {"u1": 1}
        current = {"u1": 1}
        names = {"u1": "Alice"}
        assert compute_movements(baseline, current, names) == []

    def test_user_absent_from_baseline_skipped(self):
        baseline = {"u1": 1}
        current = {"u1": 1, "u2": 2}  # u2 not in baseline
        names = {"u1": "Alice", "u2": "Bob"}
        movements = compute_movements(baseline, current, names)
        assert not any(m.username == "u2" for m in movements)

    def test_sorted_by_new_pos(self):
        baseline = {"u1": 5, "u2": 4, "u3": 3}
        current = {"u1": 1, "u2": 2, "u3": 5}
        names = {"u1": "A", "u2": "B", "u3": "C"}
        movements = compute_movements(baseline, current, names)
        positions = [m.new_pos for m in movements]
        assert positions == sorted(positions)

    def test_empty_baseline_returns_empty(self):
        current = {"u1": 1}
        names = {"u1": "Alice"}
        assert compute_movements({}, current, names) == []

    def test_display_name_falls_back_to_at_username(self):
        baseline = {"u1": 2}
        current = {"u1": 1}
        movements = compute_movements(baseline, current, {})  # no names dict
        assert movements[0].display_name == "@u1"

    def test_movement_dataclass_fields(self):
        baseline = {"u1": 3}
        current = {"u1": 1}
        names = {"u1": "Alice"}
        mv = compute_movements(baseline, current, names)[0]
        assert isinstance(mv, Movement)
        assert mv.username == "u1"
        assert mv.display_name == "Alice"
        assert mv.old_pos == 3
        assert mv.new_pos == 1
        assert mv.delta == 2


# ── update_and_diff ───────────────────────────────────────────────────────────


class TestUpdateAndDiff:
    def test_first_run_baseline_is_none(self, tmp_path):
        path = str(tmp_path / "snap.json")
        baseline, snaps = update_and_diff(path, "2026-06-16", {"u1": 1})
        assert baseline is None
        assert snaps["2026-06-16"] == {"u1": 1}

    def test_second_run_returns_yesterday_as_baseline(self, tmp_path):
        path = str(tmp_path / "snap.json")
        update_and_diff(path, "2026-06-15", {"u1": 2})
        baseline, _ = update_and_diff(path, "2026-06-16", {"u1": 1})
        assert baseline == {"u1": 2}

    def test_today_entry_overwrites_existing(self, tmp_path):
        path = str(tmp_path / "snap.json")
        update_and_diff(path, "2026-06-16", {"u1": 3})
        _, snaps = update_and_diff(path, "2026-06-16", {"u1": 1})
        assert snaps["2026-06-16"] == {"u1": 1}

    def test_most_recent_date_before_today_is_baseline(self, tmp_path):
        path = str(tmp_path / "snap.json")
        # Seed three dates
        update_and_diff(path, "2026-06-13", {"u1": 3})
        update_and_diff(path, "2026-06-14", {"u1": 2})
        update_and_diff(path, "2026-06-15", {"u1": 1})
        # Today = 2026-06-16; baseline must be 2026-06-15 (most recent < today)
        baseline, _ = update_and_diff(path, "2026-06-16", {"u1": 1})
        assert baseline == {"u1": 1}

    def test_prune_keeps_only_last_7_dates(self, tmp_path):
        path = str(tmp_path / "snap.json")
        # Insert 8 dates
        for day in range(8, 0, -1):
            update_and_diff(path, f"2026-06-{day:02d}", {"u": day})
        # After the last call (day=1 is earliest inserted but we went 8→1)
        # Actually let's add one more day to trigger pruning
        _, snaps = update_and_diff(path, "2026-06-16", {"u": 0})
        assert len(snaps) <= 7

    def test_data_persisted_to_file(self, tmp_path):
        path = str(tmp_path / "snap.json")
        update_and_diff(path, "2026-06-16", {"u1": 1})
        loaded = load_snapshots(path)
        assert "2026-06-16" in loaded
        assert loaded["2026-06-16"] == {"u1": 1}

    def test_missing_file_does_not_raise(self, tmp_path):
        path = str(tmp_path / "nonexistent" / "snap.json")
        baseline, _ = update_and_diff(path, "2026-06-16", {"u1": 1})
        assert baseline is None

    def test_future_date_not_used_as_baseline(self, tmp_path):
        """A stored date AFTER today_date must NOT be selected as baseline."""
        path = str(tmp_path / "snap.json")
        update_and_diff(path, "2026-06-18", {"u1": 5})  # future date
        baseline, _ = update_and_diff(path, "2026-06-16", {"u1": 1})
        assert baseline is None  # 2026-06-18 > 2026-06-16, must be ignored
