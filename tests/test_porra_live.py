"""Tests for porra.live — load/save, build_state, diff_live, render_changes_text."""

from __future__ import annotations

import json
import os

import pytest

from worldcup_bot.porra.live import (
    LiveDiff,
    build_state,
    diff_live,
    load_live,
    render_changes_text,
    save_live,
)
from worldcup_bot.porra.engine import UserRankEntry


# ── helpers ───────────────────────────────────────────────────────────────────


def _entry(username: str, display_name: str, total: float) -> UserRankEntry:
    return UserRankEntry(
        username=username,
        display_name=display_name,
        total_score=total,
        base_score=0.0,
        group_score=total,
        knockout_scores={},
        exact_group_hits=0,
    )


def _ranking(*args) -> list[UserRankEntry]:
    """Pass (username, display_name, total_score) tuples."""
    return [_entry(*a) for a in args]


# ── load_live / save_live ─────────────────────────────────────────────────────


class TestLoadSaveLive:
    def test_load_returns_empty_dict_when_missing(self, tmp_path):
        result = load_live(str(tmp_path / "missing.json"))
        assert result == {}

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "state.json")
        data = {"user1": {"pos": 1, "pts": 5.0, "name": "Player One"}}
        save_live(path, data)
        loaded = load_live(path)
        assert loaded == data

    def test_save_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "state.json")
        data = {"u": {"pos": 1, "pts": 0.0, "name": "U"}}
        save_live(path, data)
        assert os.path.exists(path)

    def test_load_returns_empty_on_corrupt_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("NOT JSON", encoding="utf-8")
        result = load_live(str(path))
        assert result == {}

    def test_save_swallows_error_on_readonly_dir(self, tmp_path):
        # Provide a path that will fail (non-existent drive letter)
        # Instead, test that no exception is raised
        import stat

        path = str(tmp_path / "state.json")
        save_live(path, {"u": {"pos": 1, "pts": 0.0, "name": "U"}})
        # Make file read-only so overwrite might fail on some OSes — just ensure no crash
        os.chmod(path, stat.S_IREAD)
        save_live(path, {"u": {"pos": 2, "pts": 1.0, "name": "U"}})  # should not raise
        os.chmod(path, stat.S_IWRITE)  # restore


# ── build_state ───────────────────────────────────────────────────────────────


class TestBuildState:
    def test_positions_are_1_indexed(self):
        ranking = _ranking(("alice", "Alice", 10.0), ("bob", "Bob", 8.0))
        state = build_state(ranking)
        assert state["alice"]["pos"] == 1
        assert state["bob"]["pos"] == 2

    def test_pts_captured(self):
        ranking = _ranking(("alice", "Alice", 7.5))
        state = build_state(ranking)
        assert state["alice"]["pts"] == 7.5

    def test_name_captured(self):
        ranking = _ranking(("alice", "Alice García", 5.0))
        state = build_state(ranking)
        assert state["alice"]["name"] == "Alice García"

    def test_empty_ranking_returns_empty_dict(self):
        assert build_state([]) == {}


# ── diff_live ─────────────────────────────────────────────────────────────────


class TestDiffLive:
    def test_no_change_returns_changed_false(self):
        old = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        new = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        diff = diff_live(old, new)
        assert not diff.changed
        assert diff.movements == []
        assert diff.new_entries == []

    def test_position_change_detected(self):
        old = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}, "bob": {"pos": 2, "pts": 4.0, "name": "Bob"}}
        new = {"alice": {"pos": 2, "pts": 5.0, "name": "Alice"}, "bob": {"pos": 1, "pts": 5.5, "name": "Bob"}}
        diff = diff_live(old, new)
        assert diff.changed
        assert len(diff.movements) == 2

    def test_points_change_detected(self):
        old = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        new = {"alice": {"pos": 1, "pts": 6.0, "name": "Alice"}}
        diff = diff_live(old, new)
        assert diff.changed
        assert len(diff.movements) == 1
        assert diff.movements[0]["old_pts"] == pytest.approx(5.0)
        assert diff.movements[0]["new_pts"] == pytest.approx(6.0)

    def test_new_user_noted_as_new_entry(self):
        old = {}
        new = {"alice": {"pos": 1, "pts": 3.0, "name": "Alice"}}
        diff = diff_live(old, new)
        assert diff.changed
        assert len(diff.new_entries) == 1
        assert diff.new_entries[0]["username"] == "alice"

    def test_new_user_not_in_movements(self):
        old = {}
        new = {"alice": {"pos": 1, "pts": 3.0, "name": "Alice"}}
        diff = diff_live(old, new)
        assert diff.movements == []

    def test_small_pts_delta_ignored(self):
        old = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        new = {"alice": {"pos": 1, "pts": 5.0000001, "name": "Alice"}}
        diff = diff_live(old, new)
        assert not diff.changed

    def test_movement_contains_correct_fields(self):
        old = {"alice": {"pos": 2, "pts": 4.0, "name": "Alice"}}
        new = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        diff = diff_live(old, new)
        m = diff.movements[0]
        assert m["username"] == "alice"
        assert m["name"] == "Alice"
        assert m["old_pos"] == 2
        assert m["new_pos"] == 1
        assert m["old_pts"] == pytest.approx(4.0)
        assert m["new_pts"] == pytest.approx(5.0)


# ── render_changes_text ───────────────────────────────────────────────────────


class TestRenderChangesText:
    def test_empty_when_not_changed(self):
        diff = LiveDiff(changed=False, movements=[], new_entries=[])
        assert render_changes_text(diff) == ""

    def test_rise_described_as_sube(self):
        diff = LiveDiff(
            changed=True,
            movements=[{"username": "alice", "name": "Alice", "old_pos": 3, "new_pos": 1, "old_pts": 3.0, "new_pts": 5.0}],
            new_entries=[],
        )
        text = render_changes_text(diff)
        assert "sube" in text
        assert "3º" in text
        assert "1º" in text
        assert "+2.0" in text

    def test_drop_described_as_baja(self):
        diff = LiveDiff(
            changed=True,
            movements=[{"username": "bob", "name": "Bob", "old_pos": 1, "new_pos": 3, "old_pts": 5.0, "new_pts": 5.0}],
            new_entries=[],
        )
        text = render_changes_text(diff)
        assert "baja" in text

    def test_new_entry_described(self):
        diff = LiveDiff(
            changed=True,
            movements=[],
            new_entries=[{"username": "carol", "name": "Carol", "pos": 2, "pts": 4.5}],
        )
        text = render_changes_text(diff)
        assert "Carol" in text
        assert "2º" in text
        assert "4.5" in text

    def test_multiple_movements_sorted_by_new_pos(self):
        diff = LiveDiff(
            changed=True,
            movements=[
                {"username": "b", "name": "Bob", "old_pos": 1, "new_pos": 3, "old_pts": 5.0, "new_pts": 5.0},
                {"username": "a", "name": "Alice", "old_pos": 3, "new_pos": 1, "old_pts": 3.0, "new_pts": 5.0},
            ],
            new_entries=[],
        )
        text = render_changes_text(diff)
        lines = text.strip().split("\n")
        # Alice (new_pos=1) should come before Bob (new_pos=3)
        assert lines[0].startswith("Alice")
        assert lines[1].startswith("Bob")

    def test_no_pts_delta_shows_no_pts_annotation(self):
        diff = LiveDiff(
            changed=True,
            movements=[{"username": "x", "name": "X", "old_pos": 2, "new_pos": 1, "old_pts": 5.0, "new_pts": 5.0}],
            new_entries=[],
        )
        text = render_changes_text(diff)
        assert "pts" not in text or "+0.0" not in text
