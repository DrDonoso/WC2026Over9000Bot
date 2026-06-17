"""Tests for ai.goal_extractor — _parse_extractor_json and extract_scorer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from worldcup_bot.ai.goal_extractor import _parse_extractor_json, extract_scorer


# ══════════════════════════════════════════════════════════════════════════════
# _parse_extractor_json
# ══════════════════════════════════════════════════════════════════════════════


class TestParseExtractorJson:
    def test_clean_json_scorer_and_minute(self):
        raw = '{"scorer": "Kylian Mbappé", "minute": "66"}'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer == "Kylian Mbappé"
        assert minute == "66"

    def test_clean_json_nulls(self):
        raw = '{"scorer": null, "minute": null}'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer is None
        assert minute is None

    def test_fenced_json_with_language_tag(self):
        raw = '```json\n{"scorer": "Bradley Barcola", "minute": "82"}\n```'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer == "Bradley Barcola"
        assert minute == "82"

    def test_fenced_json_without_language_tag(self):
        raw = '```\n{"scorer": "Ibrahim Mbaye", "minute": "90+5"}\n```'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer == "Ibrahim Mbaye"
        assert minute == "90+5"

    def test_garbage_returns_none_none(self):
        raw = "I don't know, sorry, no se puede saber"
        scorer, minute = _parse_extractor_json(raw)
        assert scorer is None
        assert minute is None

    def test_stoppage_time_minute(self):
        raw = '{"scorer": "Ibrahim Mbaye", "minute": "90+5"}'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer == "Ibrahim Mbaye"
        assert minute == "90+5"

    def test_empty_string_scorer_normalized_to_none(self):
        raw = '{"scorer": "", "minute": "45"}'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer is None
        assert minute == "45"

    def test_empty_string_minute_normalized_to_none(self):
        raw = '{"scorer": "Messi", "minute": ""}'
        scorer, minute = _parse_extractor_json(raw)
        assert scorer == "Messi"
        assert minute is None

    def test_partial_json_returns_none_none(self):
        raw = '{"scorer": "Messi"'  # unclosed
        scorer, minute = _parse_extractor_json(raw)
        assert scorer is None
        assert minute is None

    def test_extra_whitespace_handled(self):
        raw = '  {"scorer": "Ronaldo", "minute": "45+2"}  '
        scorer, minute = _parse_extractor_json(raw)
        assert scorer == "Ronaldo"
        assert minute == "45+2"


# ══════════════════════════════════════════════════════════════════════════════
# extract_scorer
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractScorer:
    @pytest.mark.asyncio
    async def test_returns_scorer_and_minute_from_ai(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value='{"scorer": "Mbappé", "minute": "66"}')
        scorer, minute = await extract_scorer(
            ai=ai,
            thread_text="some thread content",
            scoring_team="France",
            home_team="France",
            away_team="Senegal",
            new_home=1,
            new_away=0,
        )
        assert scorer == "Mbappé"
        assert minute == "66"

    @pytest.mark.asyncio
    async def test_ai_failure_returns_none_none(self):
        from worldcup_bot.ai.client import AIError
        ai = MagicMock()
        ai.complete = AsyncMock(side_effect=AIError("boom"))
        scorer, minute = await extract_scorer(
            ai=ai,
            thread_text="some thread content",
            scoring_team="France",
            home_team="France",
            away_team="Senegal",
            new_home=1,
            new_away=0,
        )
        assert scorer is None
        assert minute is None

    @pytest.mark.asyncio
    async def test_ai_returns_garbage_gives_none_none(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value="No puedo encontrarlo, lo siento")
        scorer, minute = await extract_scorer(
            ai=ai,
            thread_text="some content",
            scoring_team="France",
            home_team="France",
            away_team="Senegal",
            new_home=1,
            new_away=0,
        )
        assert scorer is None
        assert minute is None

    @pytest.mark.asyncio
    async def test_long_thread_text_is_trimmed(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value='{"scorer": "X", "minute": "1"}')
        long_text = "a" * 10000

        await extract_scorer(
            ai=ai,
            thread_text=long_text,
            scoring_team="France",
            home_team="France",
            away_team="Senegal",
            new_home=1,
            new_away=0,
        )
        # The 'user' kwarg passed to ai.complete must be at most _MAX_THREAD_CHARS
        user_arg = ai.complete.call_args.kwargs["user"]
        assert len(user_arg) <= 8000

    @pytest.mark.asyncio
    async def test_ai_complete_called_with_zero_temperature(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value='{"scorer": null, "minute": null}')
        await extract_scorer(
            ai=ai,
            thread_text="content",
            scoring_team="Senegal",
            home_team="France",
            away_team="Senegal",
            new_home=1,
            new_away=1,
        )
        assert ai.complete.call_args.kwargs["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_system_prompt_mentions_scoring_team(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value='{"scorer": null, "minute": null}')
        await extract_scorer(
            ai=ai,
            thread_text="content",
            scoring_team="Brazil",
            home_team="Brazil",
            away_team="Argentina",
            new_home=2,
            new_away=1,
        )
        system_arg = ai.complete.call_args.kwargs["system"]
        assert "Brazil" in system_arg
        assert "2" in system_arg
        assert "1" in system_arg
