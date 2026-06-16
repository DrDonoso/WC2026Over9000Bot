"""Tests for the commentators module."""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from worldcup_bot.ai.commentators import (
    COMMENTATORS,
    _STYLE_HINTS,
    build_commentary_messages,
    generate_porra_commentary,
    pick_commentator,
)
from worldcup_bot.ai.client import AIClient


# ── pick_commentator ──────────────────────────────────────────────────────────


class TestPickCommentator:
    def test_returns_value_from_pool(self):
        result = pick_commentator()
        assert result in COMMENTATORS

    def test_with_seeded_rng(self):
        rng = random.Random(42)
        result = pick_commentator(rng=rng)
        assert result in COMMENTATORS

    def test_pool_not_empty(self):
        assert len(COMMENTATORS) >= 3

    def test_known_commentators_in_pool(self):
        assert "Manolo Lama" in COMMENTATORS
        assert "Julio Maldini" in COMMENTATORS
        assert "Andrés Montes" in COMMENTATORS

    def test_deterministic_with_fixed_rng(self):
        rng1 = random.Random(999)
        rng2 = random.Random(999)
        assert pick_commentator(rng=rng1) == pick_commentator(rng=rng2)


# ── build_commentary_messages ─────────────────────────────────────────────────


class TestBuildCommentaryMessages:
    def test_returns_tuple_of_two_strings(self):
        system, user = build_commentary_messages("Manolo Lama", "David sube al 1º")
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_persona_name_in_system(self):
        for persona in COMMENTATORS:
            system, _ = build_commentary_messages(persona, "test")
            assert persona in system

    def test_max_4_lines_instruction_in_system(self):
        system, _ = build_commentary_messages("Manolo Lama", "test")
        assert "4" in system
        assert "líneas" in system.lower() or "lines" in system.lower() or "líneas" in system

    def test_spanish_instruction_in_system(self):
        system, _ = build_commentary_messages("Manolo Lama", "test")
        assert "español" in system.lower() or "Spanish" in system

    def test_changes_text_is_user_message(self):
        changes = "Pilar sube del 3º al 1º (+2.0 pts)"
        _, user = build_commentary_messages("Andrés Montes", changes)
        assert user == changes

    def test_style_hints_used(self):
        system, _ = build_commentary_messages("Andrés Montes", "test")
        # Andrés Montes style hint mentions "lírico" or similar
        assert any(
            word in system.lower()
            for word in ["lírico", "ocurrente", "maravillosa", "andrés montes"]
        )

    def test_unknown_persona_uses_fallback_style(self):
        system, _ = build_commentary_messages("Unknown Commentator", "test")
        assert "Unknown Commentator" in system
        # Should still produce valid system prompt
        assert len(system) > 20

    def test_porra_mentioned_in_system(self):
        system, _ = build_commentary_messages("Manolo Lama", "test")
        assert "porra" in system.lower()

    def test_no_firmes_instruction_in_system(self):
        """System prompt must instruct the model not to sign or mention its own name."""
        for persona in COMMENTATORS:
            system, _ = build_commentary_messages(persona, "test")
            assert "No firmes" in system or "no firmes" in system.lower()


# ── generate_porra_commentary ─────────────────────────────────────────────────


class TestGeneratePorraCommentary:
    @pytest.mark.asyncio
    async def test_calls_ai_complete(self):
        mock_ai = MagicMock(spec=AIClient)
        mock_ai.complete = AsyncMock(return_value="¡Brutal remontada!")

        result = await generate_porra_commentary(
            mock_ai,
            "Manolo Lama",
            "David sube del 3º al 1º",
        )
        assert result == "¡Brutal remontada!"
        mock_ai.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_max_completion_tokens_400(self):
        mock_ai = MagicMock(spec=AIClient)
        mock_ai.complete = AsyncMock(return_value="La vida puede ser maravillosa")

        await generate_porra_commentary(mock_ai, "Andrés Montes", "test changes")

        _, kwargs = mock_ai.complete.call_args
        assert kwargs.get("max_completion_tokens") == 400

    @pytest.mark.asyncio
    async def test_passes_persona_in_system(self):
        captured = {}

        async def fake_complete(system, user, **kwargs):
            captured["system"] = system
            return "respuesta"

        mock_ai = MagicMock(spec=AIClient)
        mock_ai.complete = fake_complete

        await generate_porra_commentary(mock_ai, "Julio Maldini", "some changes")
        assert "Julio Maldini" in captured["system"]
