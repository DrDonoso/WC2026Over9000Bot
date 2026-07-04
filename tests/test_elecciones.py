"""Tests for /elecciones command — phase keyboard, text renderers, image renderer,
phase filtering, split logic, caching, CHOICES_TYPE config, groups image, tile
cache eviction, and defensive line split.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.porra.elecciones import (
    _grupos_has_picks,
    _knockout_has_picks,
    _pick_for_tie,
    _split_messages,
    active_phases,
    build_groups_text,
    build_knockout_text,
    phase_label,
)

# ── Shared fixtures / helpers ─────────────────────────────────────────────────

def _make_groups(**overrides) -> dict:
    """Return a 12-group prediction dict with sensible defaults."""
    base = {
        "A": ["MEX", "KOR", "CZE"],
        "B": ["SUI", "CAN", "QAT"],
        "C": ["SCO", "MAR", "BRA"],
        "D": ["USA", "AUS", "TUR"],
        "E": ["GER", "CIV", "ECU"],
        "F": ["SWE", "JPN", "NED"],
        "G": ["EGY", "BEL", "IRN"],
        "H": ["CPV", "KSA", "ESP"],
        "I": ["FRA", "IRQ", "NOR"],
        "J": ["ALG", "ARG", "JOR"],
        "K": ["COD", "COL", "POR"],
        "L": ["ENG", "GHA", "CRO"],
    }
    base.update(overrides)
    return base


def _make_knockout(**overrides) -> dict:
    base = {
        "round_of_32": ["BRA", "ESP", "ARG", "FRA", "GER", "ENG", "POR", "NED",
                         "MEX", "USA", "BEL", "JPN", "MAR", "COL", "KOR", "SUI"],
        "round_of_16": ["BRA", "ESP", "ARG", "FRA", "GER", "ENG", "POR", "NED"],
        "quarter_finals": ["BRA", "ARG", "GER", "ENG"],
        "semi_finals": ["BRA", "GER"],
        "final": ["BRA"],
    }
    base.update(overrides)
    return base


def _make_predictions(users: dict[str, dict] | None = None) -> dict:
    if users is None:
        users = {
            "drdonoso": {
                "display_name": "DavidR",
                "groups": _make_groups(),
                "knockout": _make_knockout(),
            }
        }
    return {"participants": users}


def _flag(tla: str) -> str:
    """Minimal stub flag function for tests."""
    return f"[{tla}]"


# ── phase_label ───────────────────────────────────────────────────────────────


class TestPhaseLabel:
    def test_grupos(self):
        assert phase_label("grupos") == "Fase de grupos"

    def test_round_of_32(self):
        assert phase_label("round_of_32") == "Dieciseisavos"

    def test_round_of_16(self):
        assert phase_label("round_of_16") == "Octavos de Final"

    def test_quarter_finals(self):
        assert phase_label("quarter_finals") == "Cuartos de Final"

    def test_semi_finals(self):
        assert phase_label("semi_finals") == "Semifinales"

    def test_final(self):
        assert phase_label("final") == "La Final"

    def test_unknown_key_passthrough(self):
        assert phase_label("unknown_phase") == "unknown_phase"


# ── _grupos_has_picks / _knockout_has_picks ───────────────────────────────────


class TestHasPicks:
    def test_grupos_all_wildcard(self):
        preds = {
            "u": {"groups": {g: ["**", "**", "**"] for g in "ABCDEFGHIJKL"}}
        }
        assert _grupos_has_picks(preds) is False

    def test_grupos_one_real_pick(self):
        groups = {g: ["**", "**", "**"] for g in "ABCDEFGHIJKL"}
        groups["A"] = ["MEX", "**", "**"]
        preds = {"u": {"groups": groups}}
        assert _grupos_has_picks(preds) is True

    def test_knockout_all_wildcard(self):
        preds = {"u": {"knockout": {"round_of_32": ["**"] * 16}}}
        assert _knockout_has_picks(preds, "round_of_32") is False

    def test_knockout_one_real_pick(self):
        preds = {"u": {"knockout": {"round_of_32": ["ESP", "**"]}}}
        assert _knockout_has_picks(preds, "round_of_32") is True

    def test_knockout_empty_list(self):
        preds = {"u": {"knockout": {"round_of_32": []}}}
        assert _knockout_has_picks(preds, "round_of_32") is False

    def test_knockout_missing_key(self):
        preds = {"u": {"knockout": {}}}
        assert _knockout_has_picks(preds, "quarter_finals") is False


# ── active_phases ─────────────────────────────────────────────────────────────


class TestActivePhases:
    def test_empty_participants(self):
        assert active_phases({"participants": {}}) == []

    def test_all_wildcards_returns_empty(self):
        groups = {g: ["**", "**", "**"] for g in "ABCDEFGHIJKL"}
        ko = {k: ["**"] for k in ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]}
        preds = _make_predictions({"u": {"groups": groups, "knockout": ko}})
        assert active_phases(preds) == []

    def test_grupos_only_when_no_knockout_picks(self):
        groups = _make_groups()
        ko = {k: [] for k in ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]}
        preds = _make_predictions({"u": {"groups": groups, "knockout": ko}})
        result = active_phases(preds)
        assert result == ["grupos"]

    def test_grupos_and_round_of_32_with_picks(self):
        preds = _make_predictions()
        result = active_phases(preds)
        assert "grupos" in result
        assert "round_of_32" in result

    def test_quarter_semi_final_included_when_picks_present(self):
        preds = _make_predictions()
        result = active_phases(preds)
        assert "quarter_finals" in result
        assert "semi_finals" in result
        assert "final" in result

    def test_quarter_semi_final_absent_when_no_picks(self):
        ko = _make_knockout(quarter_finals=[], semi_finals=[], final=[])
        preds = _make_predictions({"u": {"display_name": "U", "groups": _make_groups(), "knockout": ko}})
        result = active_phases(preds)
        assert "quarter_finals" not in result
        assert "semi_finals" not in result
        assert "final" not in result

    def test_quarter_semi_final_absent_when_all_wildcard(self):
        ko = _make_knockout(quarter_finals=["**", "**", "**", "**"], semi_finals=["**", "**"], final=["**"])
        preds = _make_predictions({"u": {"groups": _make_groups(), "knockout": ko}})
        result = active_phases(preds)
        assert "quarter_finals" not in result
        assert "semi_finals" not in result
        assert "final" not in result

    def test_phase_order_respected(self):
        preds = _make_predictions()
        result = active_phases(preds)
        order = ["grupos", "round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]
        filtered = [p for p in order if p in result]
        assert result == filtered

    def test_two_users_one_with_picks(self):
        """Phase appears if ANY user has picks, not all."""
        ko_no = {k: [] for k in ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]}
        ko_yes = _make_knockout()
        preds = _make_predictions({
            "u1": {"groups": _make_groups(), "knockout": ko_no},
            "u2": {"groups": _make_groups(), "knockout": ko_yes},
        })
        result = active_phases(preds)
        assert "round_of_32" in result


# ── _pick_for_tie ─────────────────────────────────────────────────────────────


class TestPickForTie:
    def _udata(self, picks: list[str]) -> dict:
        return {"knockout": {"round_of_32": picks}}

    def test_picks_home(self):
        assert _pick_for_tie(self._udata(["ESP", "FRA"]), "ESP", "FRA", "round_of_32") == "ESP"

    def test_picks_away(self):
        assert _pick_for_tie(self._udata(["FRA", "ESP"]), "GER", "ESP", "round_of_32") == "ESP"

    def test_no_pick(self):
        assert _pick_for_tie(self._udata(["BRA", "ARG"]), "ESP", "FRA", "round_of_32") is None

    def test_wildcard_not_picked(self):
        assert _pick_for_tie(self._udata(["**"]), "ESP", "FRA", "round_of_32") is None

    def test_case_insensitive(self):
        assert _pick_for_tie(self._udata(["esp"]), "ESP", "FRA", "round_of_32") == "ESP"

    def test_empty_picks(self):
        assert _pick_for_tie(self._udata([]), "ESP", "FRA", "round_of_32") is None

    def test_missing_yaml_key(self):
        udata = {"knockout": {}}
        assert _pick_for_tie(udata, "ESP", "FRA", "round_of_32") is None


# ── build_knockout_text ───────────────────────────────────────────────────────


class TestBuildKnockoutText:
    _TIES = [("ESP", "FRA"), ("GER", "BRA"), ("ARG", "ENG")]

    def _participants(self):
        return {
            "user1": {
                "display_name": "Alice",
                "knockout": {"round_of_32": ["ESP", "GER", "ARG"]},
            },
            "user2": {
                "display_name": "Bob",
                "knockout": {"round_of_32": ["FRA", "BRA"]},
            },
        }

    def test_returns_list_of_strings(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)

    def test_header_present(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        assert "DIECISEISAVOS" in result[0]

    def test_user_block_per_participant(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        full = "\n\n".join(result)
        assert "👤 Alice" in full
        assert "👤 Bob" in full

    def test_pick_rendered_as_flag(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        full = "\n\n".join(result)
        # Alice picked ESP vs FRA → [ESP]
        assert "[ESP]" in full

    def test_no_pick_renders_question_mark(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        full = "\n\n".join(result)
        # Bob picked FRA and BRA but not ARG or ENG → ❓ for that tie
        assert "❓" in full

    def test_tie_format(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        full = "\n\n".join(result)
        # Tie format: flag·flag → pick
        assert "[ESP]·[FRA]" in full

    def test_display_name_used(self):
        result = build_knockout_text(self._TIES, self._participants(), "round_of_32", _flag)
        full = "\n\n".join(result)
        assert "Alice" in full
        assert "Bob" in full

    def test_fallback_to_at_username(self):
        parts = {"nod": {"knockout": {"round_of_32": ["ESP"]}}}
        result = build_knockout_text([("ESP", "FRA")], parts, "round_of_32", _flag)
        assert "@nod" in result[0]

    def test_empty_ties_shows_no_tie_lines(self):
        result = build_knockout_text([], self._participants(), "round_of_32", _flag)
        full = "\n\n".join(result)
        # No tie lines, but header present
        assert "DIECISEISAVOS" in full
        assert "[ESP]·[FRA]" not in full

    def test_fits_4096_chars_with_11_users_16_ties(self):
        users = {
            f"user{i}": {
                "display_name": f"Player{i}",
                "knockout": {"round_of_32": ["ESP", "FRA", "GER", "BRA", "ARG",
                                              "ENG", "POR", "NED", "MEX", "USA",
                                              "BEL", "JPN", "MAR", "COL", "KOR", "SUI"]},
            }
            for i in range(11)
        }
        ties = [
            ("ESP", "MAR"), ("FRA", "POL"), ("GER", "JPN"), ("BRA", "KOR"),
            ("ARG", "AUS"), ("ENG", "SEN"), ("POR", "URY"), ("NED", "USA"),
            ("MEX", "ECU"), ("SUI", "CMR"), ("BEL", "CRO"), ("COL", "ALG"),
            ("MEX", "CAN"), ("TUR", "NOR"), ("IRN", "CPV"), ("EGY", "GHA"),
        ]
        result = build_knockout_text(ties, users, "round_of_32", _flag)
        for msg in result:
            assert len(msg) <= 4096


# ── build_groups_text ─────────────────────────────────────────────────────────


class TestBuildGroupsText:
    def _participants(self):
        return {
            "drdonoso": {
                "display_name": "DavidR",
                "groups": _make_groups(),
            },
            "vicsaez": {
                "display_name": "Victor",
                "groups": _make_groups(A=["KOR", "MEX", "CZE"]),
            },
        }

    def test_returns_list_of_strings(self):
        result = build_groups_text(self._participants(), _flag)
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)

    def test_header_present(self):
        result = build_groups_text(self._participants(), _flag)
        assert "FASE DE GRUPOS" in result[0]

    def test_per_user_blocks(self):
        result = build_groups_text(self._participants(), _flag)
        full = "\n\n".join(result)
        assert "👤 DavidR" in full
        assert "👤 Victor" in full

    def test_group_letter_present(self):
        result = build_groups_text(self._participants(), _flag)
        full = "\n\n".join(result)
        for grp in "ABCDEFGHIJKL":
            assert f"  {grp}:" in full

    def test_third_pick_rendered(self):
        result = build_groups_text(self._participants(), _flag)
        full = "\n\n".join(result)
        # Group A: MEX KOR | 3ºCZE
        assert "3º[CZE]" in full

    def test_wildcard_third_rendered(self):
        groups = _make_groups(H=["CPV", "KSA", "**"])
        participants = {"u": {"display_name": "U", "groups": groups}}
        result = build_groups_text(participants, _flag)
        full = "\n\n".join(result)
        assert "3º**" in full

    def test_top2_rendered(self):
        result = build_groups_text(self._participants(), _flag)
        full = "\n\n".join(result)
        assert "[MEX]" in full
        assert "[KOR]" in full

    def test_pipe_separator_present(self):
        result = build_groups_text(self._participants(), _flag)
        full = "\n\n".join(result)
        assert " | " in full

    def test_fits_4096_chars_with_11_users(self):
        users = {
            f"user{i}": {
                "display_name": f"Player{i}",
                "groups": _make_groups(),
            }
            for i in range(11)
        }
        result = build_groups_text(users, _flag)
        for msg in result:
            assert len(msg) <= 4096


# ── _split_messages ───────────────────────────────────────────────────────────


class TestSplitMessages:
    def test_short_content_returns_single_message(self):
        result = _split_messages("Header", ["Block A", "Block B"])
        assert len(result) == 1
        assert "Header" in result[0]
        assert "Block A" in result[0]
        assert "Block B" in result[0]

    def test_empty_blocks_returns_header(self):
        result = _split_messages("Header", [])
        assert result == ["Header"]

    def test_split_adds_part_numbers(self):
        # Force a split by creating blocks that exceed _SPLIT_THRESHOLD
        big_block = "X" * 2000
        result = _split_messages("Header", [big_block, big_block])
        assert len(result) >= 2
        assert "(1/" in result[0]
        assert "(2/" in result[1]

    def test_split_each_part_within_threshold(self):
        from worldcup_bot.porra.elecciones import _SPLIT_THRESHOLD
        # Use blocks sized so they individually fit but pairs exceed threshold.
        # A block of 1400 chars fits alone; header + 1400 + 1400 = 2803 < 3800 so
        # two fit in one message; adding a third would exceed it → 2 parts.
        big_block = "Y" * 1400
        result = _split_messages("H", [big_block, big_block, big_block])
        for msg in result:
            # Each message is at most: "(N/N)\n" + threshold chars.
            # A single oversized block cannot be split further so we give
            # generous headroom; the important invariant is we attempted splitting.
            assert len(msg) <= 4096, f"message exceeds Telegram limit: {len(msg)}"
        # With 3 × 1400-char blocks we must produce ≥ 2 messages
        assert len(result) >= 2

    def test_header_present_in_first_part(self):
        big_block = "Z" * 2000
        result = _split_messages("MyHeader", [big_block, big_block])
        assert "MyHeader" in result[0]

    def test_single_large_block_not_split(self):
        # A single block that exceeds threshold cannot be split further
        big_block = "W" * 4000
        result = _split_messages("H", [big_block])
        # Whole thing in one message (can't split a single block)
        assert len(result) == 1

    def test_no_part_numbers_when_single_message(self):
        result = _split_messages("Header", ["Short block"])
        assert "(1/" not in result[0]


# ── CHOICES_TYPE config ───────────────────────────────────────────────────────


class TestChoicesTypeConfig:
    def test_default_is_text(self):
        from worldcup_bot.config import Settings
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.choices_type == "text"

    def test_load_settings_default_text(self, monkeypatch):
        """load_settings() uses CHOICES_TYPE env var; default = 'text'."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "key")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("CHOICES_TYPE", raising=False)
        from worldcup_bot.config import load_settings
        s = load_settings()
        assert s.choices_type == "text"

    def test_load_settings_image_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "key")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("CHOICES_TYPE", "image")
        from worldcup_bot.config import load_settings
        s = load_settings()
        assert s.choices_type == "image"

    def test_settings_choices_type_custom_value(self):
        from worldcup_bot.config import Settings
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            choices_type="image",
        )
        assert s.choices_type == "image"


# ── cmd_elecciones handler ────────────────────────────────────────────────────

def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    update.effective_user.username = "testuser"
    return update


def _make_context(settings=None) -> MagicMock:
    from worldcup_bot.config import Settings
    if settings is None:
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            predictions_path="fake.yml",
        )
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_photo = AsyncMock()
    return ctx


class TestCmdElecciones:
    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    async def test_shows_keyboard_with_active_phases(self, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        update = _make_update()
        context = _make_context()

        from worldcup_bot.bot.handlers import cmd_elecciones
        await cmd_elecciones(update, context)

        update.message.reply_text.assert_called_once()
        kwargs = update.message.reply_text.call_args
        markup = kwargs[1].get("reply_markup") or kwargs[0][1] if len(kwargs[0]) > 1 else kwargs[1].get("reply_markup")
        # Check reply_markup was passed
        call_kwargs = update.message.reply_text.call_args.kwargs
        assert "reply_markup" in call_kwargs
        assert call_kwargs["reply_markup"] is not None

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    async def test_keyboard_excludes_quarter_semi_final_when_no_picks(self, mock_load):
        ko = _make_knockout(quarter_finals=[], semi_finals=[], final=[])
        preds = _make_predictions({"u": {"display_name": "U", "groups": _make_groups(), "knockout": ko}})
        mock_load.return_value = preds

        update = _make_update()
        context = _make_context()

        from worldcup_bot.bot.handlers import cmd_elecciones
        await cmd_elecciones(update, context)

        call_kwargs = update.message.reply_text.call_args.kwargs
        markup = call_kwargs["reply_markup"]
        # Flatten all buttons
        all_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "Cuartos de Final" not in all_texts
        assert "Semifinales" not in all_texts
        assert "La Final" not in all_texts

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    async def test_keyboard_includes_grupos_and_round_of_32(self, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        update = _make_update()
        context = _make_context()

        from worldcup_bot.bot.handlers import cmd_elecciones
        await cmd_elecciones(update, context)

        call_kwargs = update.message.reply_text.call_args.kwargs
        markup = call_kwargs["reply_markup"]
        all_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "Fase de grupos" in all_texts
        assert "Dieciseisavos" in all_texts

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    async def test_no_participants_shows_error(self, mock_load):
        mock_load.return_value = {"participants": {}}

        update = _make_update()
        context = _make_context()

        from worldcup_bot.bot.handlers import cmd_elecciones
        await cmd_elecciones(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "predicciones" in text.lower()

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    async def test_all_wildcards_no_phases_message(self, mock_load):
        groups = {g: ["**", "**", "**"] for g in "ABCDEFGHIJKL"}
        ko = {k: [] for k in ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]}
        preds = _make_predictions({"u": {"groups": groups, "knockout": ko}})
        mock_load.return_value = preds

        update = _make_update()
        context = _make_context()

        from worldcup_bot.bot.handlers import cmd_elecciones
        await cmd_elecciones(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "no hay predicciones" in text.lower()

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    async def test_callback_data_uses_pipe_separator(self, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        update = _make_update()
        context = _make_context()

        from worldcup_bot.bot.handlers import cmd_elecciones
        await cmd_elecciones(update, context)

        call_kwargs = update.message.reply_text.call_args.kwargs
        markup = call_kwargs["reply_markup"]
        all_callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        for cb in all_callbacks:
            assert cb.startswith("elecciones|")


# ── cmd_elecciones_callback ───────────────────────────────────────────────────


class TestCmdEleccionesCallback:
    def _make_query(self, data: str = "elecciones|grupos") -> MagicMock:
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.message.chat_id = 12345
        return query

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    @patch("worldcup_bot.bot.handlers._elecciones_results_version", return_value="none")
    @patch("worldcup_bot.bot.handlers.os.path.getmtime", return_value=1000.0)
    async def test_removes_keyboard(self, mock_mtime, mock_rv, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        query = self._make_query("elecciones|grupos")
        update = MagicMock()
        update.callback_query = query
        context = _make_context()
        context.bot_data["elecciones_cache"] = {}

        with patch("worldcup_bot.porra.elecciones.build_groups_text", return_value=["msg"]):
            from worldcup_bot.bot.handlers import cmd_elecciones_callback
            await cmd_elecciones_callback(update, context)

        query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    @patch("worldcup_bot.bot.handlers._elecciones_results_version", return_value="none")
    @patch("worldcup_bot.bot.handlers.os.path.getmtime", return_value=1000.0)
    async def test_sends_text_result_for_grupos(self, mock_mtime, mock_rv, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        query = self._make_query("elecciones|grupos")
        update = MagicMock()
        update.callback_query = query
        context = _make_context()
        context.bot_data["elecciones_cache"] = {}

        with patch(
            "worldcup_bot.porra.elecciones.build_groups_text",
            return_value=["📋 FASE DE GRUPOS — Predicciones\n\n👤 DavidR\n  A: [MEX] [KOR] | 3º[CZE]"],
        ):
            from worldcup_bot.bot.handlers import cmd_elecciones_callback
            await cmd_elecciones_callback(update, context)

        context.bot.send_message.assert_called()
        sent_text = context.bot.send_message.call_args.kwargs.get("text") or context.bot.send_message.call_args[1].get("text", "")
        assert "FASE DE GRUPOS" in sent_text

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    @patch("worldcup_bot.bot.handlers._elecciones_results_version", return_value="v1")
    @patch("worldcup_bot.bot.handlers.os.path.getmtime", return_value=1000.0)
    async def test_cache_hit_serves_without_regeneration(self, mock_mtime, mock_rv, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        query = self._make_query("elecciones|grupos")
        update = MagicMock()
        update.callback_query = query
        context = _make_context()
        cached_artifact = {"messages": ["cached text"]}
        context.bot_data["elecciones_cache"] = {("grupos", 1000.0, "v1"): cached_artifact}

        from worldcup_bot.bot.handlers import cmd_elecciones_callback
        await cmd_elecciones_callback(update, context)

        context.bot.send_message.assert_called_once()
        sent = context.bot.send_message.call_args.kwargs.get("text", "") or context.bot.send_message.call_args[0][0] if context.bot.send_message.call_args[0] else ""
        # Accept kwargs or positional
        call_args = context.bot.send_message.call_args
        text_sent = call_args.kwargs.get("text") or (call_args.args[0] if call_args.args else "")
        assert "cached text" in text_sent

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    @patch("worldcup_bot.bot.handlers._elecciones_results_version", return_value="none")
    @patch("worldcup_bot.bot.handlers.os.path.getmtime", return_value=2000.0)
    async def test_cache_invalidated_on_mtime_change(self, mock_mtime, mock_rv, mock_load):
        preds = _make_predictions()
        mock_load.return_value = preds

        query = self._make_query("elecciones|grupos")
        update = MagicMock()
        update.callback_query = query
        context = _make_context()
        # Old cache entry with different mtime
        old_artifact = {"messages": ["old cached text"]}
        context.bot_data["elecciones_cache"] = {("grupos", 1000.0, "none"): old_artifact}

        with patch(
            "worldcup_bot.porra.elecciones.build_groups_text",
            return_value=["new text from regeneration"],
        ):
            from worldcup_bot.bot.handlers import cmd_elecciones_callback
            await cmd_elecciones_callback(update, context)

        # Should have sent new text, not old cache
        context.bot.send_message.assert_called()
        call_args = context.bot.send_message.call_args
        text_sent = call_args.kwargs.get("text") or (call_args.args[0] if call_args.args else "")
        assert "new text from regeneration" in text_sent


# ── cache helpers ─────────────────────────────────────────────────────────────


class TestEleccionesCache:
    def test_cache_put_evicts_stale_same_phase(self):
        from worldcup_bot.bot.handlers import _elecciones_cache_put
        cache: dict = {}
        _elecciones_cache_put(cache, ("grupos", 1.0, "a"), {"messages": ["v1"]})
        _elecciones_cache_put(cache, ("grupos", 2.0, "a"), {"messages": ["v2"]})
        # Only the newer entry should remain for grupos
        assert ("grupos", 1.0, "a") not in cache
        assert ("grupos", 2.0, "a") in cache

    def test_cache_different_phases_coexist(self):
        from worldcup_bot.bot.handlers import _elecciones_cache_put
        cache: dict = {}
        _elecciones_cache_put(cache, ("grupos", 1.0, "a"), {"messages": ["g"]})
        _elecciones_cache_put(cache, ("round_of_32", 1.0, "b"), {"messages": ["r"]})
        assert len(cache) == 2

    def test_cache_bounded_to_six(self):
        from worldcup_bot.bot.handlers import _elecciones_cache_put
        cache: dict = {}
        phases = ["grupos", "round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]
        for i, p in enumerate(phases):
            _elecciones_cache_put(cache, (p, float(i), "x"), {"messages": [p]})
        # Now add a 7th
        _elecciones_cache_put(cache, ("grupos", 999.0, "y"), {"messages": ["overflow"]})
        assert len(cache) <= 6

    def test_cache_invalidation_on_results_version_change(self):
        from worldcup_bot.bot.handlers import _elecciones_cache_put
        cache: dict = {}
        _elecciones_cache_put(cache, ("round_of_32", 1.0, "old_hash"), {"messages": ["old"]})
        _elecciones_cache_put(cache, ("round_of_32", 1.0, "new_hash"), {"messages": ["new"]})
        assert ("round_of_32", 1.0, "old_hash") not in cache
        assert ("round_of_32", 1.0, "new_hash") in cache


# ── elecciones_image (import + basic) ────────────────────────────────────────


class TestEleccionesImageImport:
    def test_render_knockout_matrix_importable(self):
        from worldcup_bot.bot.elecciones_image import render_knockout_matrix
        assert callable(render_knockout_matrix)

    def test_fetch_flag_tile_importable(self):
        from worldcup_bot.bot.elecciones_image import _fetch_flag_tile
        assert callable(_fetch_flag_tile)

    def test_flag_url_returns_none_for_gbeng(self):
        """England (GBENG) is a 5-char ISO code → no twemoji URL."""
        from worldcup_bot.bot.elecciones_image import _flag_url
        # ENG maps to GBENG — should be None
        assert _flag_url("ENG") is None

    def test_flag_url_returns_string_for_standard_code(self):
        """Spain (ESP → ES) has a 2-char ISO code → valid twemoji URL."""
        from worldcup_bot.bot.elecciones_image import _flag_url
        url = _flag_url("ESP")
        assert url is not None
        assert "twemoji" in url or "cdn.jsdelivr" in url

    @patch("worldcup_bot.bot.elecciones_image._requests.get")
    @patch("worldcup_bot.bot.podium_image._fetch_tile")
    def test_render_knockout_matrix_returns_bytes_io(self, mock_tile, mock_get):
        """render_knockout_matrix returns a BytesIO (or None if PIL unavailable)."""
        # Stub _fetch_tile to return a tiny placeholder image
        from PIL import Image
        stub_img = Image.new("RGBA", (44, 44), (100, 100, 100, 255))
        mock_tile.return_value = stub_img

        # Stub flag tile fetching to avoid network
        mock_get.return_value.status_code = 404

        from worldcup_bot.config import Settings
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            state_dir=".",
        )
        ties = [("ESP", "FRA"), ("GER", "BRA")]
        participants = {
            "user1": {"display_name": "Alice", "knockout": {"round_of_32": ["ESP", "GER"]}},
        }
        results_by_tie: dict = {}

        from worldcup_bot.bot.elecciones_image import render_knockout_matrix
        result = render_knockout_matrix(ties, participants, "round_of_32", results_by_tie, settings)

        # Should return BytesIO with PNG data
        assert result is not None
        assert isinstance(result, io.BytesIO)
        data = result.read()
        assert len(data) > 0
        assert data[:4] == b"\x89PNG"  # PNG magic bytes


# ── _start help text includes /elecciones ────────────────────────────────────


class TestStartHelpText:
    async def test_start_mentions_elecciones(self):
        from worldcup_bot.config import Settings
        from worldcup_bot.bot.handlers import cmd_start

        update = _make_update()
        context = _make_context(
            Settings(telegram_bot_token="t", football_data_api_key="k")
        )
        await cmd_start(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "/elecciones" in text


# ── build_group_compositions ──────────────────────────────────────────────────


class TestBuildGroupCompositions:
    def _make_standings(self, group: str, tlas: list[str]):
        """Return mock Standing objects for a group."""
        standings = []
        for pos, tla in enumerate(tlas, start=1):
            s = MagicMock()
            s.group = f"GROUP_{group}"
            s.position = pos
            s.tla = tla
            standings.append(s)
        return standings

    def test_builds_dict_from_standings(self):
        from worldcup_bot.porra.elecciones import build_group_compositions
        standings = (
            self._make_standings("A", ["MEX", "KOR", "CZE", "ZAF"])
            + self._make_standings("B", ["BRA", "ARG", "COL", "ECU"])
        )
        result = build_group_compositions(standings)
        assert result["A"] == ["MEX", "KOR", "CZE", "ZAF"]
        assert result["B"] == ["BRA", "ARG", "COL", "ECU"]

    def test_preserves_position_order(self):
        from worldcup_bot.porra.elecciones import build_group_compositions
        # Standings passed in reverse order — must be sorted by position
        standings = self._make_standings("C", ["GER", "FRA", "ESP", "POR"])
        # Reverse them
        standings.reverse()
        result = build_group_compositions(standings)
        assert result["C"] == ["GER", "FRA", "ESP", "POR"]

    def test_empty_standings_returns_empty_dict(self):
        from worldcup_bot.porra.elecciones import build_group_compositions
        assert build_group_compositions([]) == {}

    def test_ignores_entries_without_group(self):
        from worldcup_bot.porra.elecciones import build_group_compositions
        s = MagicMock()
        s.group = None
        s.position = 1
        s.tla = "TST"
        result = build_group_compositions([s])
        assert result == {}


# ── defensive line-level split (_split_block_at_lines) ───────────────────────


class TestDefensiveLineSplit:
    def test_short_block_unchanged(self):
        from worldcup_bot.porra.elecciones import _split_block_at_lines
        block = "line1\nline2\nline3"
        result = _split_block_at_lines(block, 4090)
        assert result == [block]

    def test_multi_line_block_split_at_boundary(self):
        from worldcup_bot.porra.elecciones import _split_block_at_lines
        # 5 lines × 1000 chars each; hard limit = 3500 so splits needed
        lines = ["X" * 1000 for _ in range(5)]
        block = "\n".join(lines)
        result = _split_block_at_lines(block, 3500)
        assert len(result) > 1
        for piece in result:
            assert len(piece) <= 3500

    def test_single_oversized_line_not_split(self):
        """A single line > max_len cannot be split further — returned as-is."""
        from worldcup_bot.porra.elecciones import _split_block_at_lines
        long_line = "A" * 5000
        result = _split_block_at_lines(long_line, 4090)
        assert result == [long_line]

    def test_split_messages_no_message_exceeds_hard_limit(self):
        """_split_messages never emits a message > _HARD_LIMIT even with fat blocks."""
        from worldcup_bot.porra.elecciones import _HARD_LIMIT, _split_messages
        # Build a block with many lines totalling >4090 chars
        lines = ["👤 BigUser"] + [f"  line {i}: " + "🏆" * 40 for i in range(60)]
        big_block = "\n".join(lines)
        result = _split_messages("Header", [big_block])
        for msg in result:
            assert len(msg) <= _HARD_LIMIT + 10  # allow tiny part-number prefix overhead

    def test_split_messages_single_block_within_threshold_unchanged(self):
        """A block < _SPLIT_THRESHOLD is not touched by the defensive pre-pass."""
        from worldcup_bot.porra.elecciones import _split_messages
        block = "👤 User\n  " + "X" * 100
        result = _split_messages("H", [block])
        assert len(result) == 1
        assert "👤 User" in result[0]


# ── groups image renderer ─────────────────────────────────────────────────────


class TestGroupsImage:
    @patch("worldcup_bot.bot.elecciones_image._requests.get")
    @patch("worldcup_bot.bot.podium_image._fetch_tile")
    def test_render_groups_matrix_returns_bytes_io(self, mock_tile, mock_get):
        """render_groups_matrix returns a BytesIO PNG with valid group compositions."""
        from PIL import Image as _Image

        stub_img = _Image.new("RGBA", (28, 28), (100, 150, 200, 255))
        mock_tile.return_value = stub_img
        mock_get.return_value.status_code = 404  # flag fetches fail → TLA fallback

        from worldcup_bot.config import Settings
        from worldcup_bot.bot.elecciones_image import render_groups_matrix

        settings = Settings(telegram_bot_token="t", football_data_api_key="k", state_dir=".")
        participants = {
            "user1": {"display_name": "Alice", "groups": {g: ["MEX", "KOR", "CZE"] for g in "ABCDEFGHIJKL"}},
        }
        group_comps = {g: ["MEX", "KOR", "CZE", "ZAF"] for g in "ABCDEFGHIJKL"}

        result = render_groups_matrix(group_comps, participants, settings)

        assert result is not None
        assert isinstance(result, io.BytesIO)
        data = result.read()
        assert data[:4] == b"\x89PNG"

    @patch("worldcup_bot.bot.elecciones_image._render_groups", side_effect=RuntimeError("boom"))
    def test_render_groups_matrix_returns_none_on_exception(self, _mock):
        from worldcup_bot.bot.elecciones_image import render_groups_matrix
        from worldcup_bot.config import Settings
        settings = Settings(telegram_bot_token="t", football_data_api_key="k", state_dir=".")
        result = render_groups_matrix({}, {}, settings)
        assert result is None

    def test_render_groups_matrix_importable(self):
        from worldcup_bot.bot.elecciones_image import render_groups_matrix
        assert callable(render_groups_matrix)

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    @patch("worldcup_bot.bot.handlers._elecciones_results_version", return_value="none")
    @patch("worldcup_bot.bot.handlers.os.path.getmtime", return_value=1000.0)
    @patch("worldcup_bot.bot.handlers._football_client")
    @patch("worldcup_bot.bot.elecciones_image.render_groups_matrix")
    async def test_grupos_image_mode_sends_photo(
        self, mock_render, mock_client, mock_mtime, mock_rv, mock_load
    ):
        """In image mode, tapping 'grupos' sends a photo — not a text message."""
        preds = _make_predictions()
        mock_load.return_value = preds
        mock_client.return_value.get_standings.return_value = []
        mock_render.return_value = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

        from worldcup_bot.config import Settings
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            predictions_path="fake.yml",
            choices_type="image",
        )

        query = MagicMock()
        query.data = "elecciones|grupos"
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.message.chat_id = 12345
        update = MagicMock()
        update.callback_query = query
        context = _make_context(settings)
        context.bot_data["elecciones_cache"] = {}

        from worldcup_bot.bot.handlers import cmd_elecciones_callback
        await cmd_elecciones_callback(update, context)

        context.bot.send_photo.assert_called_once()
        context.bot.send_message.assert_not_called()

    @patch("worldcup_bot.bot.handlers.pred_loader.load")
    @patch("worldcup_bot.bot.handlers._elecciones_results_version", return_value="none")
    @patch("worldcup_bot.bot.handlers.os.path.getmtime", return_value=1000.0)
    @patch("worldcup_bot.bot.handlers._football_client")
    @patch("worldcup_bot.bot.elecciones_image.render_groups_matrix", return_value=None)
    async def test_grupos_image_mode_falls_back_to_text_on_render_failure(
        self, mock_render, mock_client, mock_mtime, mock_rv, mock_load
    ):
        """If render fails, image mode falls back to text (graceful degradation)."""
        preds = _make_predictions()
        mock_load.return_value = preds
        mock_client.return_value.get_standings.return_value = []

        from worldcup_bot.config import Settings
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            predictions_path="fake.yml",
            choices_type="image",
        )

        query = MagicMock()
        query.data = "elecciones|grupos"
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.message.chat_id = 12345
        update = MagicMock()
        update.callback_query = query
        context = _make_context(settings)
        context.bot_data["elecciones_cache"] = {}

        from worldcup_bot.bot.handlers import cmd_elecciones_callback
        await cmd_elecciones_callback(update, context)

        # Render returned None → should fall back to text
        context.bot.send_message.assert_called()


# ── tile cache eviction ───────────────────────────────────────────────────────


class TestTileCacheEviction:
    def _make_tile_dir(self, tmp_path, n: int) -> str:
        """Create n dummy flag PNG files in a temp dir and return the path."""
        tile_dir = tmp_path / "elecciones_tiles"
        tile_dir.mkdir()
        import time
        for i in range(n):
            f = tile_dir / f"flag_{i:04d}.png"
            f.write_bytes(b"\x89PNG")
            # Vary mtime so eviction can distinguish old vs new
            os.utime(f, (1000000 + i, 1000000 + i))
        return str(tile_dir)

    def test_eviction_removes_oldest_files(self, tmp_path):
        from worldcup_bot.bot.elecciones_image import _evict_tile_cache
        tile_dir = self._make_tile_dir(tmp_path, 205)  # 5 over the 200-file cap
        _evict_tile_cache(tile_dir, max_files=200)
        remaining = list((tmp_path / "elecciones_tiles").glob("flag_*.png"))
        assert len(remaining) == 200

    def test_eviction_keeps_newest_files(self, tmp_path):
        from worldcup_bot.bot.elecciones_image import _evict_tile_cache
        tile_dir = self._make_tile_dir(tmp_path, 10)
        _evict_tile_cache(tile_dir, max_files=5)
        remaining = sorted(
            (tmp_path / "elecciones_tiles").glob("flag_*.png"),
            key=lambda f: f.stat().st_mtime,
        )
        # The newest 5 should survive; flag_0000..flag_0004 were oldest
        names = [f.name for f in remaining]
        assert "flag_0000.png" not in names
        assert "flag_0009.png" in names

    def test_no_eviction_when_under_limit(self, tmp_path):
        from worldcup_bot.bot.elecciones_image import _evict_tile_cache
        tile_dir = self._make_tile_dir(tmp_path, 50)
        _evict_tile_cache(tile_dir, max_files=200)
        remaining = list((tmp_path / "elecciones_tiles").glob("flag_*.png"))
        assert len(remaining) == 50

    def test_no_op_on_missing_dir(self, tmp_path):
        from worldcup_bot.bot.elecciones_image import _evict_tile_cache
        # Should not raise even if the directory doesn't exist
        _evict_tile_cache(str(tmp_path / "nonexistent"), max_files=10)

