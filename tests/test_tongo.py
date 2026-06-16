"""Tests for worldcup_bot.data.tongo — data integrity and probability model."""

from __future__ import annotations

from pathlib import Path

import pytest

from worldcup_bot.data.gifs import list_tongo_gifs
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


class TestListTongoGifs:
    def test_returns_gif_and_mp4(self, tmp_path):
        """Supported suffixes are returned; txt is excluded."""
        (tmp_path / "a.gif").write_bytes(b"GIF89a")
        (tmp_path / "b.mp4").write_bytes(b"\x00")
        (tmp_path / "c.txt").write_text("skip me")
        result = list_tongo_gifs(tmp_path)
        names = [p.name for p in result]
        assert "a.gif" in names
        assert "b.mp4" in names
        assert "c.txt" not in names

    def test_result_is_sorted(self, tmp_path):
        """Files come back in sorted order."""
        (tmp_path / "z.gif").write_bytes(b"GIF89a")
        (tmp_path / "a.mp4").write_bytes(b"\x00")
        result = list_tongo_gifs(tmp_path)
        assert result == sorted(result)

    def test_nonexistent_dir_returns_empty(self):
        """Missing directory is tolerated — returns []."""
        result = list_tongo_gifs(Path("/nonexistent/dir/tongo_gifs_xyz"))
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        """Empty directory returns []."""
        result = list_tongo_gifs(tmp_path)
        assert result == []

    def test_webp_included(self, tmp_path):
        """.webp files are included in the pool."""
        (tmp_path / "anim.webp").write_bytes(b"\x52\x49\x46\x46")
        result = list_tongo_gifs(tmp_path)
        assert len(result) == 1
        assert result[0].suffix == ".webp"

    def test_uppercase_suffix_included(self, tmp_path):
        """Suffix check is case-insensitive (.GIF → included)."""
        (tmp_path / "BIG.GIF").write_bytes(b"GIF89a")
        result = list_tongo_gifs(tmp_path)
        assert len(result) == 1

