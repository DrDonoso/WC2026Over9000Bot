"""Tests for worldcup_bot.reddit.clip_store — load/save/add/update/prune."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from worldcup_bot.reddit.clip_store import (
    add_entry,
    goal_token,
    load_clips,
    prune_old_entries,
    save_clips,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _old_iso(days: int = 8) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _sample_entry(status: str = "searching", created_at: str | None = None) -> dict:
    return {
        "chat_id": -100123,
        "message_id": 42,
        "home_name": "France",
        "away_name": "Senegal",
        "home_tla": "FRA",
        "away_tla": "SEN",
        "home_score": 1,
        "away_score": 0,
        "scoring_team": "France",
        "scorer": "Mbappé",
        "minute": "66",
        "status": status,
        "clip_path": None,
        "file_id": None,
        "attempts": 0,
        "created_at": created_at or _now_iso(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# goal_token
# ══════════════════════════════════════════════════════════════════════════════


class TestGoalToken:
    def test_returns_12_hex_chars(self):
        tok = goal_token("some:key:here")
        assert len(tok) == 12
        assert all(c in "0123456789abcdef" for c in tok)

    def test_stable(self):
        assert goal_token("a:b") == goal_token("a:b")

    def test_different_keys_differ(self):
        assert goal_token("key1") != goal_token("key2")


# ══════════════════════════════════════════════════════════════════════════════
# load_clips
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadClips:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        path = str(tmp_path / "nope.json")
        assert load_clips(path) == {}

    def test_returns_data_from_valid_file(self, tmp_path):
        path = tmp_path / "clips.json"
        data = {"abc123": _sample_entry()}
        path.write_text(json.dumps(data), encoding="utf-8")
        assert load_clips(str(path)) == data

    def test_returns_empty_on_corrupt_json(self, tmp_path):
        path = tmp_path / "clips.json"
        path.write_text("not valid json{{}", encoding="utf-8")
        assert load_clips(str(path)) == {}

    def test_does_not_raise_on_corrupt(self, tmp_path):
        path = tmp_path / "clips.json"
        path.write_text("null", encoding="utf-8")
        # json.loads("null") == None, not a dict — should be handled
        result = load_clips(str(path))
        # Either an empty dict or the raw None converted gracefully
        assert isinstance(result, dict) or result is None


# ══════════════════════════════════════════════════════════════════════════════
# save_clips
# ══════════════════════════════════════════════════════════════════════════════


class TestSaveClips:
    def test_creates_file_with_data(self, tmp_path):
        path = tmp_path / "clips.json"
        data = {"tok1": _sample_entry()}
        save_clips(str(path), data)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert "tok1" in loaded

    def test_unwritable_path_does_not_raise(self, tmp_path):
        # Deliberately bad path — should swallow error silently
        save_clips("/nonexistent_dir_xyz/clips.json", {"x": 1})

    def test_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "clips.json"
        path.write_text(json.dumps({"old": _sample_entry()}), encoding="utf-8")
        save_clips(str(path), {"new": _sample_entry()})
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert "new" in loaded
        assert "old" not in loaded


# ══════════════════════════════════════════════════════════════════════════════
# add_entry
# ══════════════════════════════════════════════════════════════════════════════


class TestAddEntry:
    def test_adds_entry_with_searching_status(self):
        data: dict = {}
        add_entry(
            data,
            "abc123",
            chat_id=-100123,
            message_id=42,
            home_name="France",
            away_name="Senegal",
            home_tla="FRA",
            away_tla="SEN",
            home_score=1,
            away_score=0,
            scoring_team="France",
            scorer="Mbappé",
            minute="66",
        )
        assert "abc123" in data
        assert data["abc123"]["status"] == "searching"

    def test_required_fields_present(self):
        data: dict = {}
        add_entry(
            data,
            "tok",
            chat_id=99,
            message_id=7,
            home_name="A",
            away_name="B",
            home_tla="AAA",
            away_tla="BBB",
            home_score=2,
            away_score=1,
            scoring_team="A",
            scorer=None,
            minute=None,
        )
        entry = data["tok"]
        for field in (
            "chat_id", "message_id", "home_name", "away_name",
            "home_tla", "away_tla", "home_score", "away_score",
            "scoring_team", "scorer", "minute",
            "status", "clip_path", "file_id", "attempts", "created_at",
        ):
            assert field in entry, f"missing field: {field}"

    def test_attempts_starts_at_zero(self):
        data: dict = {}
        add_entry(
            data, "t", chat_id=1, message_id=1, home_name="X", away_name="Y",
            home_tla="X", away_tla="Y", home_score=0, away_score=0,
            scoring_team="X", scorer=None, minute=None,
        )
        assert data["t"]["attempts"] == 0

    def test_clip_path_and_file_id_start_null(self):
        data: dict = {}
        add_entry(
            data, "t2", chat_id=1, message_id=1, home_name="X", away_name="Y",
            home_tla="X", away_tla="Y", home_score=0, away_score=0,
            scoring_team="X", scorer="Bob", minute="30",
        )
        assert data["t2"]["clip_path"] is None
        assert data["t2"]["file_id"] is None

    def test_overwrites_existing_entry(self):
        data: dict = {"tok": {"status": "ready", "clip_path": "/old"}}
        add_entry(
            data, "tok", chat_id=1, message_id=2, home_name="A", away_name="B",
            home_tla="A", away_tla="B", home_score=1, away_score=0,
            scoring_team="A", scorer=None, minute=None,
        )
        assert data["tok"]["status"] == "searching"
        assert data["tok"]["clip_path"] is None

    def test_created_at_is_recent_utc(self):
        data: dict = {}
        before = datetime.now(timezone.utc)
        add_entry(
            data, "t3", chat_id=1, message_id=1, home_name="X", away_name="Y",
            home_tla="X", away_tla="Y", home_score=0, away_score=0,
            scoring_team="X", scorer=None, minute=None,
        )
        after = datetime.now(timezone.utc)
        created = datetime.fromisoformat(data["t3"]["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        assert before <= created <= after


# ══════════════════════════════════════════════════════════════════════════════
# prune_old_entries
# ══════════════════════════════════════════════════════════════════════════════


class TestPruneOldEntries:
    def test_removes_old_entry(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        data = {"old": _sample_entry(created_at=_old_iso(8))}
        prune_old_entries(data, clips_dir, max_age_days=7)
        assert "old" not in data

    def test_keeps_recent_entry(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        data = {"recent": _sample_entry(created_at=_now_iso())}
        prune_old_entries(data, clips_dir, max_age_days=7)
        assert "recent" in data

    def test_deletes_clip_file_when_pruning(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        clip_file = clips_dir / "old.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_entry(created_at=_old_iso(10))
        entry["clip_path"] = str(clip_file)
        data = {"old": entry}
        prune_old_entries(data, clips_dir, max_age_days=7)
        assert not clip_file.exists()

    def test_no_crash_if_clip_file_missing(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        entry = _sample_entry(created_at=_old_iso(10))
        entry["clip_path"] = str(clips_dir / "ghost.mp4")  # doesn't exist
        data = {"old": entry}
        prune_old_entries(data, clips_dir, max_age_days=7)  # must not raise
        assert "old" not in data

    def test_entry_without_created_at_retained(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        entry = _sample_entry()
        entry.pop("created_at")
        data = {"nodate": entry}
        prune_old_entries(data, clips_dir, max_age_days=7)
        assert "nodate" in data  # retained (safe default)

    def test_entry_with_bad_created_at_retained(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        entry = _sample_entry(created_at="not-a-date")
        data = {"baddate": entry}
        prune_old_entries(data, clips_dir, max_age_days=7)
        assert "baddate" in data

    def test_mixes_old_and_recent(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        data = {
            "old1": _sample_entry(created_at=_old_iso(10)),
            "recent": _sample_entry(created_at=_now_iso()),
            "old2": _sample_entry(created_at=_old_iso(8)),
        }
        prune_old_entries(data, clips_dir, max_age_days=7)
        assert "old1" not in data
        assert "old2" not in data
        assert "recent" in data


# ══════════════════════════════════════════════════════════════════════════════
# Round-trip: load → modify → save → reload
# ══════════════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    def test_load_save_load_preserves_all_fields(self, tmp_path):
        path = str(tmp_path / "clips.json")
        data: dict = {}
        add_entry(
            data,
            "roundtrip",
            chat_id=-100999,
            message_id=777,
            home_name="Spain",
            away_name="Morocco",
            home_tla="ESP",
            away_tla="MAR",
            home_score=2,
            away_score=0,
            scoring_team="Spain",
            scorer="Morata",
            minute="55",
        )
        save_clips(path, data)

        reloaded = load_clips(path)
        assert "roundtrip" in reloaded
        entry = reloaded["roundtrip"]
        assert entry["chat_id"] == -100999
        assert entry["message_id"] == 777
        assert entry["home_name"] == "Spain"
        assert entry["scorer"] == "Morata"
        assert entry["minute"] == "55"
        assert entry["status"] == "searching"
        assert entry["attempts"] == 0

    def test_status_update_persists(self, tmp_path):
        path = str(tmp_path / "clips.json")
        data: dict = {}
        add_entry(
            data, "t", chat_id=1, message_id=1, home_name="A", away_name="B",
            home_tla="A", away_tla="B", home_score=1, away_score=0,
            scoring_team="A", scorer=None, minute=None,
        )
        data["t"]["status"] = "ready"
        data["t"]["clip_path"] = "/app/state/clips/t.mp4"
        save_clips(path, data)

        reloaded = load_clips(path)
        assert reloaded["t"]["status"] == "ready"
        assert reloaded["t"]["clip_path"] == "/app/state/clips/t.mp4"
