"""Tests for worldcup_bot.bot.formatters — focusing on bold_person_names."""

from __future__ import annotations

import pytest

from worldcup_bot.bot.formatters import bold_person_names, render_endirecto, team_flag


class TestTeamFlagBelovedTeams:
    """team_flag must append ❤️ for BELOVED_TEAMS (PAN, UZB) and only them."""

    def test_pan_uppercase_gets_heart(self):
        result = team_flag("PAN")
        assert "🇵🇦" in result
        assert result.endswith("❤️")

    def test_uzb_uppercase_gets_heart(self):
        result = team_flag("UZB")
        assert "🇺🇿" in result
        assert result.endswith("❤️")

    def test_pan_lowercase_gets_heart(self):
        result = team_flag("pan")
        assert "🇵🇦" in result
        assert result.endswith("❤️")

    def test_uzb_lowercase_gets_heart(self):
        result = team_flag("uzb")
        assert "🇺🇿" in result
        assert result.endswith("❤️")

    def test_esp_has_no_heart(self):
        result = team_flag("ESP")
        assert "❤️" not in result
        assert result != ""

    def test_unknown_tla_returns_empty_no_heart(self):
        result = team_flag("ZZZ")
        assert result == ""
        assert "❤️" not in result



class TestBoldPersonNames:
    # ── basic bolding ─────────────────────────────────────────────────────────

    def test_bolds_single_name(self):
        result = bold_person_names("Hello Alice!", ["Alice"])
        assert result == "Hello <b>Alice</b>!"

    def test_bolds_multiple_names(self):
        result = bold_person_names("Alice scored but Bob defended", ["Alice", "Bob"])
        assert "<b>Alice</b>" in result
        assert "<b>Bob</b>" in result

    def test_unknown_word_left_alone(self):
        result = bold_person_names("Carlos scored", ["Alice"])
        assert "<b>" not in result
        assert result == "Carlos scored"

    def test_empty_names_list_just_escapes(self):
        result = bold_person_names("Hello Alice!", [])
        assert result == "Hello Alice!"
        assert "<b>" not in result

    def test_none_stripped_names_ignored(self):
        result = bold_person_names("Hello Alice!", ["", "  ", "Alice"])
        assert result == "Hello <b>Alice</b>!"

    # ── longest-first / no partial overlap ───────────────────────────────────

    def test_longest_name_wins_over_shorter_prefix(self):
        """'Alice Smith' must be bolded as a whole, not 'Alice' and then ' Smith'."""
        result = bold_person_names("Alice Smith scored", ["Alice", "Alice Smith"])
        assert "<b>Alice Smith</b>" in result
        # Must NOT have nested bold from 'Alice' being re-processed
        assert "<b><b>" not in result

    def test_shorter_name_bolded_at_other_positions(self):
        """'Alice' alone still gets bolded when it appears separately from 'Alice Smith'."""
        result = bold_person_names("Alice scored but Alice Smith celebrated", ["Alice", "Alice Smith"])
        assert "<b>Alice Smith</b>" in result
        # The standalone 'Alice' should also be bolded
        assert "<b>Alice</b>" in result

    def test_substring_inside_longer_word_not_bolded(self):
        """'Ana' must NOT be bolded inside 'Banana'."""
        result = bold_person_names("Banana is tasty", ["Ana"])
        assert "<b>Ana</b>" not in result
        assert result == "Banana is tasty"

    # ── accented characters ───────────────────────────────────────────────────

    def test_accented_name_bolded(self):
        result = bold_person_names("Jugada de Peñalver fue clave", ["Peñalver"])
        assert "<b>Peñalver</b>" in result

    def test_accented_name_not_bolded_as_substring(self):
        """'Tarragó' must NOT be bolded inside 'Tarragón'."""
        result = bold_person_names("Tarragón es ciudad", ["Tarragó"])
        assert "<b>Tarragó</b>" not in result

    def test_accented_trailing_name(self):
        result = bold_person_names("Gol de Tarragó!", ["Tarragó"])
        assert "<b>Tarragó</b>" in result

    # ── multi-word names ──────────────────────────────────────────────────────

    def test_multi_word_name_bolded(self):
        result = bold_person_names("Felicidades Maria Tarrago!", ["Maria Tarrago"])
        assert "<b>Maria Tarrago</b>" in result

    def test_multi_word_name_with_accents_bolded(self):
        result = bold_person_names("Enhorabuena a Pilar Freixas", ["Pilar Freixas"])
        assert "<b>Pilar Freixas</b>" in result

    # ── HTML escaping ─────────────────────────────────────────────────────────

    def test_html_special_chars_escaped(self):
        result = bold_person_names("A & B < C > D", [])
        assert "&amp;" in result
        assert "&lt;" in result
        assert "&gt;" in result

    def test_name_bolded_and_surrounding_text_escaped(self):
        result = bold_person_names("Alice & Bob won", ["Alice", "Bob"])
        assert "<b>Alice</b>" in result
        assert "&amp;" in result
        assert "<b>Bob</b>" in result

    def test_ampersand_in_name_escaped_and_bolded(self):
        # Edge case: name contains HTML-special chars
        result = bold_person_names("A & B did great", ["A & B"])
        assert "<b>A &amp; B</b>" in result

    # ── no double-bold ────────────────────────────────────────────────────────

    def test_duplicate_names_in_list_bold_only_once(self):
        """Duplicate entries in names list must not cause double-wrapping."""
        result = bold_person_names("Alice scored", ["Alice", "Alice"])
        assert result.count("<b>Alice</b>") == 1
        assert "<b><b>" not in result

    def test_name_appears_twice_in_text_both_bolded(self):
        """A name appearing twice in text should be bolded in both places."""
        result = bold_person_names("Alice said to Alice: hello", ["Alice"])
        assert result.count("<b>Alice</b>") == 2

    # ── edge cases ────────────────────────────────────────────────────────────

    def test_empty_text_returns_empty(self):
        result = bold_person_names("", ["Alice"])
        assert result == ""

    def test_name_at_start_of_string(self):
        result = bold_person_names("Alice ganó", ["Alice"])
        assert result.startswith("<b>Alice</b>")

    def test_name_at_end_of_string(self):
        result = bold_person_names("Ganó Alice", ["Alice"])
        assert result.endswith("<b>Alice</b>")

    def test_name_is_entire_text(self):
        result = bold_person_names("Alice", ["Alice"])
        assert result == "<b>Alice</b>"

    def test_returns_html_safe_string(self):
        """Result must always be HTML-safe (no raw < > & from original text)."""
        result = bold_person_names("<script>alert('xss')</script>", ["Alice"])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ══════════════════════════════════════════════════════════════════════════════
# format_live_match_detail
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatLiveMatchDetail:
    def _make_match(self, home_tla="POR", away_tla="COD", home_score=1, away_score=1):
        from worldcup_bot.api.models import Match
        return Match(
            id=1,
            utc_date="2026-06-17T18:00:00Z",
            status="IN_PLAY",
            stage="GROUP_STAGE",
            group="GROUP_A",
            home_tla=home_tla,
            away_tla=away_tla,
            home_name="Portugal",
            away_name="Congo DR",
            home_score=home_score,
            away_score=away_score,
            winner=None,
        )

    def test_header_contains_en_directo(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {})
        assert "🔴 EN DIRECTO" in result

    def test_header_includes_minute_when_present(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {"minute": "74", "goals": [], "cards": [], "subs": []})
        assert "74'" in result

    def test_header_no_minute_when_null(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {"minute": None, "goals": [], "cards": [], "subs": []})
        # Should not have any minute marker after EN DIRECTO
        lines = result.splitlines()
        assert "·" not in lines[0]

    def test_score_line_shows_both_teams_and_score(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match(home_score=1, away_score=1)
        result = format_live_match_detail(m, {})
        assert "Portugal" in result
        assert "Congo DR" in result
        assert "1-1" in result

    def test_none_score_shows_zero(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match(home_score=None, away_score=None)
        result = format_live_match_detail(m, {})
        assert "0-0" in result

    def test_goals_section_shown_when_present(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        events = {
            "minute": "71",
            "goals": [{"minute": "6", "team": "Portugal", "scorer": "João Neves"}],
            "cards": [],
            "subs": [],
        }
        result = format_live_match_detail(m, events)
        assert "⚽ Goles" in result
        assert "João Neves" in result
        assert "6'" in result
        assert "(Portugal)" in result

    def test_goals_section_omitted_when_empty(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {"minute": None, "goals": [], "cards": [], "subs": []})
        assert "⚽ Goles" not in result

    def test_yellow_card_shown_with_yellow_emoji(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        events = {
            "minute": "13",
            "goals": [],
            "cards": [{"minute": "13", "team": "Portugal", "player": "Bernardo Silva", "type": "yellow"}],
            "subs": [],
        }
        result = format_live_match_detail(m, events)
        assert "🟨 Tarjetas" in result
        assert "🟨" in result
        assert "Bernardo Silva" in result

    def test_red_card_shown_with_red_emoji(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        events = {
            "minute": "55",
            "goals": [],
            "cards": [{"minute": "55", "team": "Congo DR", "player": "Mbemba", "type": "red"}],
            "subs": [],
        }
        result = format_live_match_detail(m, events)
        assert "🟥" in result
        assert "Mbemba" in result

    def test_cards_section_omitted_when_empty(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {"minute": None, "goals": [], "cards": [], "subs": []})
        assert "🟨 Tarjetas" not in result

    def test_subs_section_shown_with_arrow(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        events = {
            "minute": "71",
            "goals": [],
            "cards": [],
            "subs": [{"minute": "71", "team": "Portugal", "in": "Rafael Leão", "out": "Pedro Neto"}],
        }
        result = format_live_match_detail(m, events)
        assert "🔄 Cambios" in result
        assert "Rafael Leão" in result
        assert "Pedro Neto" in result
        assert "▶" in result

    def test_subs_section_omitted_when_empty(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {"minute": None, "goals": [], "cards": [], "subs": []})
        assert "🔄 Cambios" not in result

    def test_all_sections_present_when_all_events(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        events = {
            "minute": "71",
            "goals": [{"minute": "6", "team": "Portugal", "scorer": "João Neves"}],
            "cards": [{"minute": "13", "team": "Portugal", "player": "Bernardo Silva", "type": "yellow"}],
            "subs": [{"minute": "45", "team": "Portugal", "in": "Conceição", "out": "Bernardo Silva"}],
        }
        result = format_live_match_detail(m, events)
        assert "⚽ Goles" in result
        assert "🟨 Tarjetas" in result
        assert "🔄 Cambios" in result

    def test_resilient_to_empty_events_dict(self):
        from worldcup_bot.bot.formatters import format_live_match_detail
        m = self._make_match()
        result = format_live_match_detail(m, {})
        assert "🔴 EN DIRECTO" in result
        assert "Portugal" in result


_MINIMAL_SNAP = {
    "token": "abc12345",
    "match_id": 1,
    "minute": "71",
    "home_name": "Portugal",
    "away_name": "Congo DR",
    "home_tla": "POR",
    "away_tla": "COD",
    "home_score": 1,
    "away_score": 1,
    "goals": [
        {"minute": "6", "team": "Portugal", "scorer": "João Neves"},
        {"minute": "45+5", "team": "Congo DR", "scorer": "Yoane Wissa"},
    ],
    "cards": [{"minute": "13", "team": "Portugal", "player": "Bernardo Silva", "type": "yellow"}],
    "subs": [{"minute": "71", "team": "Portugal", "in": "Rafael Leão", "out": "Pedro Neto"}],
    "lineup": {"home": ["Diogo Costa", "Gonçalo Inácio"], "away": ["Masuaku", "Wissa"]},
    "revealed": [],
    "created": 0.0,
}


class TestRenderEndirecto:
    def test_revealed_empty_has_header_and_goals(self):
        text, _ = render_endirecto(dict(_MINIMAL_SNAP))
        assert "🔴 EN DIRECTO" in text
        assert "⚽ Goles" in text
        assert "João Neves" in text
        assert "🟨 Tarjetas" not in text
        assert "👥 Alineación" not in text
        assert "🔄 Cambios" not in text

    def test_revealed_empty_has_3_buttons(self):
        _, kb = render_endirecto(dict(_MINIMAL_SNAP))
        assert len(kb) == 1
        assert len(kb[0]) == 3

    def test_goals_always_shown_regardless_of_revealed(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["tarjetas"]
        text, _ = render_endirecto(snap)
        assert "⚽ Goles" in text

    def test_fixed_order_tarjetas_before_alineacion_before_cambios(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["tarjetas", "alineacion", "cambios"]
        text, _ = render_endirecto(snap)
        assert text.index("⚽ Goles") < text.index("🟨 Tarjetas") < text.index("👥 Alineación actual") < text.index("🔄 Cambios")

    def test_cambios_first_then_tarjetas_still_fixed_order(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["cambios", "tarjetas"]
        text, _ = render_endirecto(snap)
        assert text.index("🟨 Tarjetas") < text.index("🔄 Cambios")

    def test_all_revealed_no_keyboard(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["tarjetas", "alineacion", "cambios"]
        _, kb = render_endirecto(snap)
        assert kb == []

    def test_no_goals_shows_sin_goles(self):
        snap = dict(_MINIMAL_SNAP)
        snap["goals"] = []
        text, _ = render_endirecto(snap)
        assert "Sin goles todavía" in text

    def test_minute_in_header(self):
        text, _ = render_endirecto(dict(_MINIMAL_SNAP))
        assert "71'" in text

    def test_no_minute_no_prime(self):
        snap = dict(_MINIMAL_SNAP)
        snap["minute"] = None
        text, _ = render_endirecto(snap)
        assert "None'" not in text

    def test_flags_via_tla(self):
        text, _ = render_endirecto(dict(_MINIMAL_SNAP))
        assert "Portugal" in text
        assert "Congo DR" in text

    def test_score_shown(self):
        text, _ = render_endirecto(dict(_MINIMAL_SNAP))
        assert "1-1" in text

    def test_none_score_defaults_to_zero(self):
        snap = dict(_MINIMAL_SNAP)
        snap["home_score"] = None
        snap["away_score"] = None
        text, _ = render_endirecto(snap)
        assert "0-0" in text

    def test_callback_data_format(self):
        _, kb = render_endirecto(dict(_MINIMAL_SNAP))
        data = [button.callback_data for button in kb[0]]
        assert data == ["ed|abc12345|t", "ed|abc12345|l", "ed|abc12345|c"]

    def test_tarjetas_shown_when_revealed(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["tarjetas"]
        text, _ = render_endirecto(snap)
        assert "🟨 Tarjetas" in text
        assert "Bernardo Silva" in text

    def test_alineacion_shown_when_revealed(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["alineacion"]
        text, _ = render_endirecto(snap)
        assert "👥 Alineación actual" in text
        assert "Diogo Costa" in text

    def test_cambios_shown_when_revealed(self):
        snap = dict(_MINIMAL_SNAP)
        snap["revealed"] = ["cambios"]
        text, _ = render_endirecto(snap)
        assert "🔄 Cambios" in text
        assert "Rafael Leão" in text
