"""Tests for worldcup_bot.bot.formatters — focusing on bold_person_names."""

from __future__ import annotations

import pytest

from worldcup_bot.bot.formatters import bold_person_names


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
