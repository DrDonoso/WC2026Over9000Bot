"""Tests for worldcup_bot.data.gender — infer_gender helper."""

from __future__ import annotations

import pytest

from worldcup_bot.data.gender import infer_gender


class TestInferGender:
    def test_female_laura(self):
        assert infer_gender("Laura") == "f"

    def test_female_maria(self):
        assert infer_gender("Maria") == "f"

    def test_male_david(self):
        assert infer_gender("David") == "m"

    def test_male_juan(self):
        assert infer_gender("Juan") == "m"

    def test_empty_string_defaults_to_male(self):
        assert infer_gender("") == "m"

    def test_none_defaults_to_male(self):
        assert infer_gender(None) == "m"

    def test_unknown_name_defaults_to_male(self):
        assert infer_gender("Xkqlzpr") == "m"

    def test_name_with_emoji_prefix_uses_first_alpha_token(self):
        """Leading emoji should be ignored; the real name token is used."""
        assert infer_gender("Laura") == infer_gender("🌟 Laura")
