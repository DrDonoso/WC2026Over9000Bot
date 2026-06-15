"""Tests for the YAML predictions loader: parsing, validation, hot-reload, lookups.

All file I/O uses pytest's tmp_path fixture (OS-managed temp dir).
Module-level hot-reload cache is reset via the conftest autouse fixture.
"""

from __future__ import annotations

import os
import time

import pytest

from worldcup_bot.porra.predictions import (
    display_name_for,
    find_by_display_name,
    get_participant,
    list_usernames,
    load,
)

# ── YAML constants ─────────────────────────────────────────────────────────────

# A fully-valid YAML with one participant ("user1").
VALID_YAML_1 = """\
participants:
  user1:
    display_name: "Player One"
    base_score: 2.5
    groups:
      A: [ESP, FRA, GER]
      B: [ARG, BRA, ENG]
      C: [POR, NED, URU]
      D: [BEL, CRO, ITA]
      E: [COL, MEX, DEN]
      F: [USA, POL, AUT]
      G: [TUR, MAR, SUI]
      H: [ECU, NGA, CHI]
      I: [JPN, KOR, CIV]
      J: [VEN, PAR, CAN]
      K: [EGY, ALG, AUS]
      L: [PER, GHA, SRB]
    knockout:
      round_of_32: [ESP, FRA, ARG, BRA, GER, ENG, POR, NED, COL, MEX, USA, JPN, MAR, BEL, CRO, ITA]
      round_of_16: [ESP, FRA, ARG, BRA, GER, ENG, POR, NED]
      quarter_finals: [ESP, FRA, ARG, BRA]
      semi_finals: [ESP, FRA]
      final: [ESP]
"""

# A second valid YAML with a *different* user ("user2") — for hot-reload tests.
VALID_YAML_2 = """\
participants:
  user2:
    display_name: "Player Two"
    base_score: 0
    groups:
      A: [GER, ESP, BRA]
      B: [ENG, ARG, FRA]
      C: [URU, NED, POR]
      D: [ITA, CRO, BEL]
      E: [DEN, MEX, COL]
      F: [AUT, POL, USA]
      G: [SUI, MAR, TUR]
      H: [CHI, NGA, ECU]
      I: [CIV, KOR, JPN]
      J: [CAN, PAR, VEN]
      K: [AUS, ALG, EGY]
      L: [SRB, GHA, PER]
    knockout:
      round_of_32: [GER, ESP, BRA, ARG, ENG, FRA, NED, POR, MEX, COL, JPN, USA, BEL, MAR, CRO, ITA]
      round_of_16: [GER, ESP, BRA, ARG, ENG, FRA, NED, POR]
      quarter_finals: [GER, ESP, BRA, ARG]
      semi_finals: [GER, ESP]
      final: [GER]
"""

# ── helpers to build invalid YAML blobs ──────────────────────────────────────

_GROUPS_BLOCK = """\
      A: [ESP, FRA, GER]
      B: [ARG, BRA, ENG]
      C: [POR, NED, URU]
      D: [BEL, CRO, ITA]
      E: [COL, MEX, DEN]
      F: [USA, POL, AUT]
      G: [TUR, MAR, SUI]
      H: [ECU, NGA, CHI]
      I: [JPN, KOR, CIV]
      J: [VEN, PAR, CAN]
      K: [EGY, ALG, AUS]
      L: [PER, GHA, SRB]"""

_KO_BLOCK = """\
      round_of_32: [ESP, FRA, ARG, BRA, GER, ENG, POR, NED, COL, MEX, USA, JPN, MAR, BEL, CRO, ITA]
      round_of_16: [ESP, FRA, ARG, BRA, GER, ENG, POR, NED]
      quarter_finals: [ESP, FRA, ARG, BRA]
      semi_finals: [ESP, FRA]
      final: [ESP]"""


def _user_block(name: str, groups_block: str, ko_block: str) -> str:
    return (
        f"participants:\n"
        f"  {name}:\n"
        f"    display_name: null\n"
        f"    base_score: 0\n"
        f"    groups:\n{groups_block}\n"
        f"    knockout:\n{ko_block}\n"
    )


# 11 groups only — group L is absent
_GROUPS_MISSING_L = "\n".join(
    ln for ln in _GROUPS_BLOCK.splitlines() if "L:" not in ln
)

# Group A has 4 picks (should be 3)
_GROUPS_WRONG_PICKS = _GROUPS_BLOCK.replace(
    "A: [ESP, FRA, GER]", "A: [ESP, FRA, GER, ARG]"
)

# Group A has an unknown TLA
_GROUPS_INVALID_TLA = _GROUPS_BLOCK.replace(
    "A: [ESP, FRA, GER]", "A: [ZZZ, FRA, GER]"
)

# knockout key "round_of_64" instead of "round_of_32"
_KO_BAD_KEY = _KO_BLOCK.replace("round_of_32", "round_of_64")


# ══════════════════════════════════════════════════════════════════════════════
# load() — file loading, validation, hot-reload
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadValidYaml:
    def test_valid_yaml_returns_participants_key(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        result = load(str(p))
        assert "participants" in result
        assert "user1" in result["participants"]

    def test_valid_yaml_base_score_parsed_as_float(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        result = load(str(p))
        assert result["participants"]["user1"]["base_score"] == 2.5

    def test_valid_yaml_display_name(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        result = load(str(p))
        assert result["participants"]["user1"]["display_name"] == "Player One"

    def test_valid_yaml_groups_structure(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        result = load(str(p))
        groups = result["participants"]["user1"]["groups"]
        assert set(groups.keys()) == set("ABCDEFGHIJKL")
        assert groups["A"] == ["ESP", "FRA", "GER"]

    def test_valid_yaml_knockout_structure(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        result = load(str(p))
        ko = result["participants"]["user1"]["knockout"]
        assert set(ko.keys()) == {"round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"}
        assert ko["final"] == ["ESP"]

    def test_tlas_uppercased_on_load(self, tmp_path):
        yaml_with_lower = VALID_YAML_1.replace("A: [ESP, FRA, GER]", "A: [esp, fra, ger]")
        p = tmp_path / "preds.yml"
        p.write_text(yaml_with_lower)
        result = load(str(p))
        assert result["participants"]["user1"]["groups"]["A"] == ["ESP", "FRA", "GER"]


class TestLoadInvalidCases:
    def test_nonexistent_file_returns_empty_participants(self):
        result = load("/no/such/file/predictions.yml")
        assert result == {"participants": {}}

    def test_wrong_number_of_groups_user_skipped(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(_user_block("baduser", _GROUPS_MISSING_L, _KO_BLOCK))
        result = load(str(p))
        assert "baduser" not in result["participants"]

    def test_wrong_picks_per_group_user_skipped(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(_user_block("baduser", _GROUPS_WRONG_PICKS, _KO_BLOCK))
        result = load(str(p))
        assert "baduser" not in result["participants"]

    def test_invalid_tla_user_skipped(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(_user_block("baduser", _GROUPS_INVALID_TLA, _KO_BLOCK))
        result = load(str(p))
        assert "baduser" not in result["participants"]

    def test_bad_knockout_key_user_skipped(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(_user_block("baduser", _GROUPS_BLOCK, _KO_BAD_KEY))
        result = load(str(p))
        assert "baduser" not in result["participants"]

    def test_invalid_user_does_not_crash_valid_user_still_loaded(self, tmp_path):
        """A bad user is skipped; a valid user in the same file is kept."""
        yaml = (
            _user_block("baduser", _GROUPS_INVALID_TLA, _KO_BLOCK)
            + "\n"
            + "  user1:\n"
            + "    display_name: null\n"
            + "    base_score: 0\n"
            + "    groups:\n" + _GROUPS_BLOCK + "\n"
            + "    knockout:\n" + _KO_BLOCK + "\n"
        )
        p = tmp_path / "preds.yml"
        p.write_text(yaml)
        result = load(str(p))
        assert "baduser" not in result["participants"]
        assert "user1" in result["participants"]

    def test_empty_yaml_returns_empty_participants(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text("")
        result = load(str(p))
        assert result == {"participants": {}}

    def test_malformed_yaml_returns_empty_participants(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text("key: [unclosed bracket")
        result = load(str(p))
        assert result == {"participants": {}}


class TestLoadHotReload:
    def test_same_mtime_returns_cached_object(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)

        first = load(str(p))
        second = load(str(p))

        assert first is second  # exact same Python object → cache was used

    def test_changed_mtime_triggers_reload(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        first = load(str(p))

        # Ensure a strictly different mtime by sleeping past filesystem resolution
        time.sleep(0.05)
        p.write_text(VALID_YAML_2)

        second = load(str(p))

        assert first is not second
        assert "user1" in first["participants"]
        assert "user2" in second["participants"]

    def test_reload_does_not_include_old_users(self, tmp_path):
        p = tmp_path / "preds.yml"
        p.write_text(VALID_YAML_1)
        load(str(p))

        time.sleep(0.05)
        p.write_text(VALID_YAML_2)

        result = load(str(p))
        assert "user1" not in result["participants"]
        assert "user2" in result["participants"]


# ══════════════════════════════════════════════════════════════════════════════
# get_participant, find_by_display_name, display_name_for, list_usernames
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def predictions_dict():
    """Inline predictions dict (no file I/O needed for lookup tests)."""
    return {
        "participants": {
            "alice": {
                "display_name": "Alice Wonderland",
                "base_score": 0.0,
                "groups": {},
                "knockout": {},
            },
            "bob": {
                "display_name": None,
                "base_score": 0.0,
                "groups": {},
                "knockout": {},
            },
        }
    }


class TestGetParticipant:
    def test_exact_lowercase_key(self, predictions_dict):
        result = get_participant(predictions_dict, "alice")
        assert result is not None
        assert result["display_name"] == "Alice Wonderland"

    def test_mixed_case_input_normalised(self, predictions_dict):
        result = get_participant(predictions_dict, "Alice")
        assert result is not None

    def test_all_caps_input_normalised(self, predictions_dict):
        result = get_participant(predictions_dict, "ALICE")
        assert result is not None

    def test_nonexistent_user_returns_none(self, predictions_dict):
        assert get_participant(predictions_dict, "charlie") is None

    def test_empty_predictions_returns_none(self):
        assert get_participant({"participants": {}}, "alice") is None

    def test_empty_dict_returns_none(self):
        assert get_participant({}, "alice") is None


class TestFindByDisplayName:
    def test_exact_display_name_match(self, predictions_dict):
        result = find_by_display_name(predictions_dict, "Alice Wonderland")
        assert result is not None
        username, udata = result
        assert username == "alice"

    def test_case_insensitive_match(self, predictions_dict):
        result = find_by_display_name(predictions_dict, "alice wonderland")
        assert result is not None

    def test_not_found_returns_none(self, predictions_dict):
        assert find_by_display_name(predictions_dict, "Nobody") is None

    def test_none_display_name_not_matched(self, predictions_dict):
        # bob has display_name=None — searching for None string shouldn't match
        assert find_by_display_name(predictions_dict, "None") is None

    def test_returns_username_and_data_tuple(self, predictions_dict):
        result = find_by_display_name(predictions_dict, "Alice Wonderland")
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestDisplayNameFor:
    def test_returns_display_name_when_set(self, predictions_dict):
        udata = predictions_dict["participants"]["alice"]
        assert display_name_for("alice", udata) == "Alice Wonderland"

    def test_returns_at_username_when_display_name_none(self, predictions_dict):
        udata = predictions_dict["participants"]["bob"]
        assert display_name_for("bob", udata) == "@bob"

    def test_returns_at_username_when_display_name_empty_string(self):
        udata = {"display_name": ""}
        assert display_name_for("charlie", udata) == "@charlie"


class TestListUsernames:
    def test_returns_all_keys(self, predictions_dict):
        names = list_usernames(predictions_dict)
        assert set(names) == {"alice", "bob"}

    def test_empty_predictions_returns_empty_list(self):
        assert list_usernames({"participants": {}}) == []

    def test_empty_dict_returns_empty_list(self):
        assert list_usernames({}) == []
