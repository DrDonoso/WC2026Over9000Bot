"""Tests for the vergol_stats module (persistent per-user view counter)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from worldcup_bot.reddit.vergol_stats import (
    leaderboard,
    load_stats,
    record_view,
    save_stats,
)


# ══════════════════════════════════════════════════════════════════════════════
# load_stats / save_stats
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadSaveRoundTrip:
    def test_missing_file_returns_empty(self, tmp_path):
        data = load_stats(str(tmp_path / "nonexistent.json"))
        assert data == {}

    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "stats.json")
        original = {"123": {"name": "Alice", "tokens": ["abc", "def"]}}
        save_stats(path, original)
        loaded = load_stats(path)
        assert loaded == original

    def test_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("NOT { valid json !!!")
        data = load_stats(str(path))
        assert data == {}

    def test_save_unwritable_does_not_raise(self, tmp_path):
        """save_stats to an unwritable path must swallow the error silently."""
        path = str(tmp_path / "no" / "such" / "dir" / "stats.json")
        # should not raise
        save_stats(path, {"1": {"name": "Bob", "tokens": ["tok1"]}})

    def test_load_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("")
        data = load_stats(str(path))
        assert data == {}


# ══════════════════════════════════════════════════════════════════════════════
# record_view
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordView:
    def test_new_user_new_token_returns_true(self):
        data = {}
        result = record_view(data, 42, "Alice", "tok1")
        assert result is True

    def test_new_user_creates_entry(self):
        data = {}
        record_view(data, 42, "Alice", "tok1")
        assert "42" in data
        assert data["42"]["name"] == "Alice"
        assert "tok1" in data["42"]["tokens"]

    def test_duplicate_token_returns_false(self):
        data = {}
        record_view(data, 42, "Alice", "tok1")
        result = record_view(data, 42, "Alice", "tok1")
        assert result is False

    def test_duplicate_token_not_added_twice(self):
        data = {}
        record_view(data, 42, "Alice", "tok1")
        record_view(data, 42, "Alice", "tok1")
        assert data["42"]["tokens"].count("tok1") == 1

    def test_different_token_same_user_returns_true(self):
        data = {}
        record_view(data, 42, "Alice", "tok1")
        result = record_view(data, 42, "Alice", "tok2")
        assert result is True

    def test_different_token_appended(self):
        data = {}
        record_view(data, 42, "Alice", "tok1")
        record_view(data, 42, "Alice", "tok2")
        assert set(data["42"]["tokens"]) == {"tok1", "tok2"}

    def test_name_updated_on_each_view(self):
        data = {}
        record_view(data, 42, "Old Name", "tok1")
        record_view(data, 42, "New Name", "tok2")
        assert data["42"]["name"] == "New Name"

    def test_name_updated_even_on_duplicate_token(self):
        """Name should update even if the token is a duplicate."""
        data = {}
        record_view(data, 42, "Old Name", "tok1")
        record_view(data, 42, "Latest Name", "tok1")
        assert data["42"]["name"] == "Latest Name"

    def test_user_id_stored_as_string(self):
        data = {}
        record_view(data, 999, "Bob", "tokX")
        assert "999" in data

    def test_two_users_independent(self):
        data = {}
        record_view(data, 1, "Alice", "tok1")
        record_view(data, 2, "Bob", "tok1")
        # same token, but different users → both count it
        assert data["1"]["tokens"] == ["tok1"]
        assert data["2"]["tokens"] == ["tok1"]

    def test_count_is_distinct_tokens(self):
        data = {}
        record_view(data, 1, "Alice", "tok1")
        record_view(data, 1, "Alice", "tok1")  # duplicate
        record_view(data, 1, "Alice", "tok2")
        assert len(data["1"]["tokens"]) == 2  # distinct: tok1, tok2


# ══════════════════════════════════════════════════════════════════════════════
# leaderboard
# ══════════════════════════════════════════════════════════════════════════════


class TestLeaderboard:
    def test_empty_data_returns_empty(self):
        assert leaderboard({}) == []

    def test_single_user(self):
        data = {"1": {"name": "Alice", "tokens": ["a", "b"]}}
        board = leaderboard(data)
        assert board == [("Alice", 2)]

    def test_sorted_by_count_desc(self):
        data = {
            "1": {"name": "Alice", "tokens": ["a"]},
            "2": {"name": "Bob", "tokens": ["a", "b", "c"]},
            "3": {"name": "Carol", "tokens": ["a", "b"]},
        }
        board = leaderboard(data)
        assert board[0] == ("Bob", 3)
        assert board[1] == ("Carol", 2)
        assert board[2] == ("Alice", 1)

    def test_tie_broken_by_name_asc(self):
        data = {
            "1": {"name": "Zara", "tokens": ["a", "b"]},
            "2": {"name": "Anna", "tokens": ["c", "d"]},
        }
        board = leaderboard(data)
        assert board[0][0] == "Anna"
        assert board[1][0] == "Zara"

    def test_users_with_no_tokens_excluded(self):
        data = {
            "1": {"name": "Alice", "tokens": ["tok1"]},
            "2": {"name": "Ghost", "tokens": []},
        }
        board = leaderboard(data)
        names = [name for name, _ in board]
        assert "Ghost" not in names
        assert "Alice" in names

    def test_count_equals_len_of_distinct_tokens(self):
        data = {"1": {"name": "X", "tokens": ["a", "b", "c"]}}
        board = leaderboard(data)
        assert board[0][1] == 3
