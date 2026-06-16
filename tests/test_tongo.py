"""Tests for worldcup_bot.data.tongo — data integrity and probability model."""

from __future__ import annotations

import pytest

from worldcup_bot.data.tongo import FRASES, SANCHEZ_ENS_ROBA, frase_argentino

_NEW_PHRASES = [
    "Per robos el de Javi a Raona",
    "Que si quiere la bolsa",
    "La culpa es de Suñé",
    "Ara envio a la buuuhhhambulancia",
    "si, si, però vas palmant",
    "Si, y Amalia y Suñé son mejores amigos ahora también",
    "Y Rosamar para cuando?",
    "Y Santvi para cuando?",
    "Y Sant Celoni para cuando?",
    "Aguacate?",
    "Si, y Arbeloa es el jugador favorito de Laura. CAP17ÁN.",
    "Tongo es que Joan García no fue convocado con el Espanyol y vaya con el Barça, asi que a callar.",
    "Como va a ser tongo, si no te interesa ni el futbol.",
    "Un conoooooo!! un cono!!!",
    "Por lo menos no somos italia.",
    "Ah, pero ChatGPT decia que si.",
]


class TestTongoData:
    def test_sanchez_constant_value(self):
        assert SANCHEZ_ENS_ROBA == "Sanchez ens roba"

    def test_frases_contains_no_sanchez(self):
        """SANCHEZ_ENS_ROBA must NOT appear in FRASES (probability contract)."""
        assert SANCHEZ_ENS_ROBA not in FRASES

    def test_frases_contains_no_sanchez_by_value(self):
        """No string equal to 'Sanchez ens roba' anywhere in FRASES."""
        assert all(phrase != "Sanchez ens roba" for phrase in FRASES)

    @pytest.mark.parametrize("phrase", _NEW_PHRASES)
    def test_new_phrase_present(self, phrase: str):
        """Each expected phrase must be in FRASES verbatim."""
        assert phrase in FRASES

    def test_frases_count_at_least_16(self):
        """13 pre-existing phrases + 3 new simple phrases = 16 minimum."""
        assert len(FRASES) >= 16


class TestFraseArgentino:
    def test_female_variant(self):
        assert frase_argentino("f") == "Que tongo ni que tongo, eres mas pesada que una argentina."

    def test_male_variant(self):
        assert frase_argentino("m") == "Que tongo ni que tongo, eres mas pesado que un argentino."

    def test_unknown_defaults_to_male(self):
        assert frase_argentino("x") == "Que tongo ni que tongo, eres mas pesado que un argentino."

    def test_empty_defaults_to_male(self):
        assert frase_argentino("") == "Que tongo ni que tongo, eres mas pesado que un argentino."
