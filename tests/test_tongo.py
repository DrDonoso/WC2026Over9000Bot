"""Tests for worldcup_bot.data.tongo — data integrity and probability model."""

from __future__ import annotations

import pytest

from worldcup_bot.data.tongo import FRASES, SANCHEZ_ENS_ROBA

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
        """Each of the 13 new phrases must be in FRASES verbatim."""
        assert phrase in FRASES

    def test_frases_count_at_least_28(self):
        """15 original non-Sanchez phrases + 13 new = 28 minimum."""
        assert len(FRASES) >= 28
