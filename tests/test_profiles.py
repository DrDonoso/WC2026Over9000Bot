"""Tests for the UserProfile store (profiles.py).

Covers:
- load_profiles: missing → {}; corrupt → {} + no raise; valid round-trip
- save_profiles: atomic write (no .tmp left), creates parent dirs
- get_profile: present / absent
- UserProfile dataclass: default fields, piques_recientes, pinned_fields
"""

from __future__ import annotations

import json
import os

import pytest

from worldcup_bot.chat.profiles import (
    UserProfile,
    get_profile,
    load_profiles,
    save_profiles,
)


# ── load_profiles ─────────────────────────────────────────────────────────────


class TestLoadProfiles:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = load_profiles(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_corrupt_file_returns_empty_dict_no_raise(self, tmp_path):
        path = tmp_path / "profiles.json"
        path.write_text("this is not valid json at all!!", encoding="utf-8")
        result = load_profiles(str(path))
        assert result == {}

    def test_json_array_root_returns_empty_dict_no_raise(self, tmp_path):
        path = tmp_path / "profiles.json"
        path.write_text("[]", encoding="utf-8")
        result = load_profiles(str(path))
        assert result == {}

    def test_empty_json_object_returns_empty_dict(self, tmp_path):
        path = tmp_path / "profiles.json"
        path.write_text("{}", encoding="utf-8")
        result = load_profiles(str(path))
        assert result == {}

    def test_loads_valid_profile_with_all_fields(self, tmp_path):
        path = tmp_path / "profiles.json"
        data = {
            "alice": {
                "username": "alice",
                "rasgos": "extrovertida y directa",
                "equipo": "España",
                "motes": ["Ali", "la voz"],
                "temas": ["futbol", "viajes"],
                "tono": "amigable y sin filtro",
                "piques_recientes": [{"ts": "2026-07-10T10:00:00+00:00", "texto": "¡Gol!"}],
                "pinned_fields": ["equipo"],
                "updated_at": "2026-07-10T04:00:00+00:00",
            }
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        profiles = load_profiles(str(path))

        assert "alice" in profiles
        p = profiles["alice"]
        assert p.username == "alice"
        assert p.rasgos == "extrovertida y directa"
        assert p.equipo == "España"
        assert p.motes == ["Ali", "la voz"]
        assert p.temas == ["futbol", "viajes"]
        assert p.tono == "amigable y sin filtro"
        assert len(p.piques_recientes) == 1
        assert p.piques_recientes[0]["texto"] == "¡Gol!"
        assert p.pinned_fields == ["equipo"]
        assert p.updated_at == "2026-07-10T04:00:00+00:00"

    def test_loads_multiple_profiles(self, tmp_path):
        path = tmp_path / "profiles.json"
        data = {
            "alice": {"username": "alice", "rasgos": "extrovertida"},
            "bob": {"username": "bob", "equipo": "Argentina"},
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        profiles = load_profiles(str(path))
        assert "alice" in profiles
        assert "bob" in profiles
        assert profiles["alice"].rasgos == "extrovertida"
        assert profiles["bob"].equipo == "Argentina"

    def test_non_dict_values_in_root_are_skipped(self, tmp_path):
        """Non-dict entries in the root object are silently skipped."""
        path = tmp_path / "profiles.json"
        data = {"alice": {"username": "alice"}, "bad": "not a dict", "also_bad": 42}
        path.write_text(json.dumps(data), encoding="utf-8")
        profiles = load_profiles(str(path))
        assert "alice" in profiles
        assert "bad" not in profiles
        assert "also_bad" not in profiles

    def test_missing_optional_fields_use_defaults(self, tmp_path):
        path = tmp_path / "profiles.json"
        path.write_text(json.dumps({"alice": {"username": "alice"}}), encoding="utf-8")
        profiles = load_profiles(str(path))
        p = profiles["alice"]
        assert p.rasgos is None
        assert p.equipo is None
        assert p.motes == []
        assert p.temas == []
        assert p.tono is None
        assert p.piques_recientes == []
        assert p.pinned_fields == []
        assert p.updated_at is None

    def test_null_optional_fields_use_defaults(self, tmp_path):
        """Explicit null values in JSON are treated as None/defaults."""
        path = tmp_path / "profiles.json"
        data = {
            "alice": {
                "username": "alice",
                "rasgos": None,
                "equipo": None,
                "motes": None,
                "temas": None,
                "tono": None,
            }
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        profiles = load_profiles(str(path))
        p = profiles["alice"]
        assert p.rasgos is None
        assert p.motes == []
        assert p.temas == []


# ── save_profiles ─────────────────────────────────────────────────────────────


class TestSaveProfiles:
    def test_atomic_no_tmp_file_left(self, tmp_path):
        path = str(tmp_path / "profiles.json")
        save_profiles(path, {"alice": UserProfile(username="alice")})
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")

    def test_roundtrip_all_fields(self, tmp_path):
        path = str(tmp_path / "profiles.json")
        original = {
            "bob": UserProfile(
                username="bob",
                rasgos="callado pero letal",
                equipo="Argentina",
                motes=["Bobiño", "el silencioso"],
                temas=["tenis", "chess"],
                tono="sarcástico a tope",
                piques_recientes=[{"ts": "2026-07-10T10:00:00+00:00", "texto": "jajaja"}],
                pinned_fields=["equipo"],
                updated_at="2026-07-10T04:00:00+00:00",
            )
        }
        save_profiles(path, original)
        loaded = load_profiles(path)

        p = loaded["bob"]
        assert p.username == "bob"
        assert p.rasgos == "callado pero letal"
        assert p.equipo == "Argentina"
        assert p.motes == ["Bobiño", "el silencioso"]
        assert p.temas == ["tenis", "chess"]
        assert p.tono == "sarcástico a tope"
        assert p.piques_recientes[0]["texto"] == "jajaja"
        assert p.pinned_fields == ["equipo"]
        assert p.updated_at == "2026-07-10T04:00:00+00:00"

    def test_creates_parent_directory(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "profiles.json")
        save_profiles(path, {"u": UserProfile(username="u")})
        assert os.path.exists(path)

    def test_empty_profiles_saves_empty_json_object(self, tmp_path):
        path = str(tmp_path / "profiles.json")
        save_profiles(path, {})
        loaded = load_profiles(path)
        assert loaded == {}

    def test_save_multiple_profiles(self, tmp_path):
        path = str(tmp_path / "profiles.json")
        profiles = {
            "alice": UserProfile(username="alice", equipo="España"),
            "bob": UserProfile(username="bob", equipo="Argentina"),
        }
        save_profiles(path, profiles)
        loaded = load_profiles(path)
        assert loaded["alice"].equipo == "España"
        assert loaded["bob"].equipo == "Argentina"

    def test_save_does_not_raise_on_write_failure(self, tmp_path):
        """save_profiles is best-effort — must not propagate PermissionError."""
        from unittest.mock import patch as _patch
        # Use a truly bad path so save will fail silently
        save_profiles("/nonexistent/deep/path/profiles.json", {"u": UserProfile(username="u")})
        # No exception → test passes


# ── get_profile ───────────────────────────────────────────────────────────────


class TestGetProfile:
    def test_returns_profile_when_present(self):
        profiles = {"alice": UserProfile(username="alice", rasgos="extrovertida")}
        result = get_profile(profiles, "alice")
        assert result is not None
        assert result.username == "alice"
        assert result.rasgos == "extrovertida"

    def test_returns_none_when_absent(self):
        profiles = {"alice": UserProfile(username="alice")}
        result = get_profile(profiles, "bob")
        assert result is None

    def test_returns_none_on_empty_dict(self):
        assert get_profile({}, "alice") is None

    def test_case_sensitive_lookup(self):
        """Username lookup is case-sensitive."""
        profiles = {"Alice": UserProfile(username="Alice")}
        assert get_profile(profiles, "alice") is None
        assert get_profile(profiles, "Alice") is not None


# ── UserProfile dataclass ─────────────────────────────────────────────────────


class TestUserProfileDataclass:
    def test_default_scalar_fields_are_none(self):
        p = UserProfile(username="test")
        assert p.rasgos is None
        assert p.equipo is None
        assert p.tono is None
        assert p.updated_at is None

    def test_default_list_fields_are_empty(self):
        p = UserProfile(username="test")
        assert p.motes == []
        assert p.temas == []
        assert p.piques_recientes == []
        assert p.pinned_fields == []

    def test_motes_list_is_independent_per_instance(self):
        """Each instance gets its own motes list (default_factory)."""
        p1 = UserProfile(username="a")
        p2 = UserProfile(username="b")
        p1.motes.append("mote1")
        assert p2.motes == []

    def test_piques_recientes_list_independent_per_instance(self):
        p1 = UserProfile(username="a")
        p2 = UserProfile(username="b")
        p1.piques_recientes.append({"ts": "x", "texto": "y"})
        assert p2.piques_recientes == []

    def test_piques_recientes_accepts_ts_texto_dicts(self):
        p = UserProfile(
            username="alice",
            piques_recientes=[
                {"ts": "2026-07-10T10:00:00+00:00", "texto": "¡Eso es trampa!"},
                {"ts": "2026-07-10T11:00:00+00:00", "texto": "Vaya jugada..."},
            ],
        )
        assert len(p.piques_recientes) == 2
        assert p.piques_recientes[0]["texto"] == "¡Eso es trampa!"

    def test_pinned_fields_can_include_any_field_name(self):
        p = UserProfile(
            username="alice",
            pinned_fields=["equipo", "rasgos", "tono"],
        )
        assert "equipo" in p.pinned_fields
        assert "rasgos" in p.pinned_fields

    def test_all_fields_settable_at_construction(self):
        p = UserProfile(
            username="charlie",
            rasgos="bromista",
            equipo="Panama",
            motes=["Charly"],
            temas=["rumba"],
            tono="festivo",
            piques_recientes=[{"ts": "t", "texto": "hola"}],
            pinned_fields=["equipo"],
            updated_at="2026-07-10T04:00:00+00:00",
        )
        assert p.username == "charlie"
        assert p.rasgos == "bromista"
        assert p.equipo == "Panama"
        assert p.motes == ["Charly"]
        assert p.temas == ["rumba"]
        assert p.tono == "festivo"
        assert len(p.piques_recientes) == 1
        assert p.pinned_fields == ["equipo"]
        assert p.updated_at == "2026-07-10T04:00:00+00:00"
