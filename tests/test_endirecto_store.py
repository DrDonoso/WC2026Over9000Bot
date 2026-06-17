"""Tests for bot.endirecto_store — snapshot store for /endirecto reveal buttons."""

from __future__ import annotations

import json
import time

import pytest

from worldcup_bot.bot.endirecto_store import (
    load_snapshot,
    new_token,
    prune,
    save_snapshot,
    set_revealed,
)


def _sample_snap(token: str = "abc12345", created: float | None = None) -> dict:
    return {
        "token": token,
        "match_id": 1,
        "minute": "71",
        "home_name": "Portugal",
        "away_name": "Congo DR",
        "home_tla": "POR",
        "away_tla": "COD",
        "home_score": 1,
        "away_score": 1,
        "goals": [],
        "cards": [],
        "subs": [],
        "lineup": {"home": [], "away": []},
        "revealed": [],
        "created": time.time() if created is None else created,
    }


class TestNewToken:
    def test_returns_8_hex_chars(self):
        token = new_token()
        assert len(token) == 8
        assert all(char in "0123456789abcdef" for char in token)

    def test_unique(self):
        assert new_token() != new_token()


class TestSaveLoadRoundTrip:
    def test_save_and_load_returns_snap(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap()
        save_snapshot(str(path), snap)
        assert load_snapshot(str(path), snap["token"]) == snap

    def test_load_missing_token_returns_none(self, tmp_path):
        path = tmp_path / "endirecto.json"
        save_snapshot(str(path), _sample_snap())
        assert load_snapshot(str(path), "deadbeef") is None

    def test_load_missing_file_returns_none(self, tmp_path):
        path = tmp_path / "missing.json"
        assert load_snapshot(str(path), "deadbeef") is None

    def test_corrupt_file_returns_none(self, tmp_path):
        path = tmp_path / "endirecto.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_snapshot(str(path), "deadbeef") is None


class TestSetRevealed:
    def test_appends_section(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap()
        save_snapshot(str(path), snap)
        updated = set_revealed(str(path), snap["token"], "tarjetas")
        assert updated["revealed"] == ["tarjetas"]

    def test_idempotent(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap()
        save_snapshot(str(path), snap)
        set_revealed(str(path), snap["token"], "tarjetas")
        updated = set_revealed(str(path), snap["token"], "tarjetas")
        assert updated["revealed"] == ["tarjetas"]

    def test_multiple_sections(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap()
        save_snapshot(str(path), snap)
        set_revealed(str(path), snap["token"], "tarjetas")
        updated = set_revealed(str(path), snap["token"], "cambios")
        assert updated["revealed"] == ["tarjetas", "cambios"]

    def test_persists_to_disk(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap()
        save_snapshot(str(path), snap)
        set_revealed(str(path), snap["token"], "tarjetas")
        assert load_snapshot(str(path), snap["token"])["revealed"] == ["tarjetas"]

    def test_missing_token_returns_none(self, tmp_path):
        path = tmp_path / "endirecto.json"
        save_snapshot(str(path), _sample_snap())
        assert set_revealed(str(path), "deadbeef", "tarjetas") is None


class TestPrune:
    def test_drops_old_entries(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap(created=time.time() - 7 * 3600)
        save_snapshot(str(path), snap)
        prune(str(path), max_age_secs=3600)
        assert load_snapshot(str(path), snap["token"]) is None

    def test_keeps_fresh_entries(self, tmp_path):
        path = tmp_path / "endirecto.json"
        snap = _sample_snap()
        save_snapshot(str(path), snap)
        prune(str(path), max_age_secs=3600)
        assert load_snapshot(str(path), snap["token"]) == snap

    def test_missing_file_is_safe(self, tmp_path):
        path = tmp_path / "missing.json"
        prune(str(path), max_age_secs=3600)
        assert not path.exists()
