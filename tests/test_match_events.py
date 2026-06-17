"""Tests for ai.match_events — extract_match_events and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from worldcup_bot.ai.match_events import (
    _parse_events_json,
    _trim_events_region,
    extract_match_events,
)

# ── real sample from the Portugal vs Congo DR thread ─────────────────────────

_REAL_THREAD_SAMPLE = """\
**MATCH EVENTS** | via ESPN
**6'** ⚽ **Goal! Portugal 1, Congo DR 0. João Neves (Portugal) header ... Assisted by Pedro Neto with a cross.**
**13'** 🟨 Bernardo Silva (Portugal) is shown the yellow card for a bad foul.
**32'** 🟨 Chancel Mbemba (Congo DR) is shown the yellow card for a bad foul.
**45'** 🔄 Substitution, Portugal. Francisco Conceição replaces Bernardo Silva.
**45'+5'** ⚽ **Goal! Portugal 1, Congo DR 1. Yoane Wissa (Congo DR) header ... Assisted by Arthur Masuaku ...**
**57'** 🔄 Substitution, Congo DR. Noah Sadiki replaces Ngal'ayel Mukau.
**71'** 🔄 Substitution, Portugal. Rafael Leão replaces Pedro Neto.

**MATCH STATS** | via ESPN
Possession: Portugal 58%, Congo DR 42%
Shots: Portugal 14, Congo DR 4
"""

_REAL_THREAD_SAMPLE_WITH_LINEUP = """\
Starting XI

Portugal: Diogo Costa / Gonçalo Inácio / João Neves / Nuno Mendes 🔄 off 72' / Vitinha 🔄 off 83'
Congo DR: Masuaku / Wissa

**MATCH EVENTS** | via ESPN
**6'** ⚽ **Goal! Portugal 1, Congo DR 0. João Neves...**
**45'** 🔄 Substitution, Portugal. Francisco Conceição replaces Bernardo Silva.

**MATCH STATS** | via ESPN
Possession: Portugal 58%, Congo DR 42%
"""

_SAMPLE_EVENTS_JSON = """\
{
  "minute": "71",
  "goals": [
    {"minute": "6", "team": "Portugal", "scorer": "João Neves"},
    {"minute": "45+5", "team": "Congo DR", "scorer": "Yoane Wissa"}
  ],
  "cards": [
    {"minute": "13", "team": "Portugal", "player": "Bernardo Silva", "type": "yellow"},
    {"minute": "32", "team": "Congo DR", "player": "Chancel Mbemba", "type": "yellow"}
  ],
  "subs": [
    {"minute": "45", "team": "Portugal", "in": "Francisco Conceição", "out": "Bernardo Silva"},
    {"minute": "57", "team": "Congo DR", "in": "Noah Sadiki", "out": "Ngal'ayel Mukau"},
    {"minute": "71", "team": "Portugal", "in": "Rafael Leão", "out": "Pedro Neto"}
  ]
}
"""

_SAMPLE_EVENTS_WITH_LINEUP_JSON = """\
{
  "minute": "45",
  "goals": [{"minute": "6", "team": "Portugal", "scorer": "João Neves"}],
  "cards": [],
  "subs": [{"minute": "45", "team": "Portugal", "in": "Francisco Conceição", "out": "Bernardo Silva"}],
  "lineup": {
    "home": ["Diogo Costa", "Gonçalo Inácio", "João Neves", "Francisco Conceição"],
    "away": ["Masuaku", "Wissa"]
  }
}
"""


# ══════════════════════════════════════════════════════════════════════════════
# _trim_events_region
# ══════════════════════════════════════════════════════════════════════════════


class TestTrimEventsRegion:
    def test_keeps_match_events_section(self):
        trimmed = _trim_events_region(_REAL_THREAD_SAMPLE)
        assert "João Neves" in trimmed
        assert "Yoane Wissa" in trimmed

    def test_drops_match_stats_section(self):
        trimmed = _trim_events_region(_REAL_THREAD_SAMPLE)
        assert "MATCH STATS" not in trimmed
        assert "Possession" not in trimmed

    def test_no_marker_returns_head(self):
        text = "a" * 10000
        trimmed = _trim_events_region(text)
        assert len(trimmed) <= 8000

    def test_capped_at_8000(self):
        events_section = "MATCH EVENTS\n" + ("x" * 10000)
        trimmed = _trim_events_region(events_section)
        assert len(trimmed) <= 8000

    def test_includes_context_before_marker(self):
        prefix = "preamble text " * 5
        text = prefix + "MATCH EVENTS\n**6'** ⚽ Goal!"
        trimmed = _trim_events_region(text)
        assert "MATCH EVENTS" in trimmed
        assert "⚽ Goal!" in trimmed

    def test_includes_starting_xi_section(self):
        trimmed = _trim_events_region(_REAL_THREAD_SAMPLE_WITH_LINEUP)
        assert "Starting XI" in trimmed
        assert "Diogo Costa" in trimmed

    def test_anchors_on_earlier_of_starting_xi_and_match_events(self):
        trimmed = _trim_events_region(_REAL_THREAD_SAMPLE_WITH_LINEUP)
        assert "Starting XI" in trimmed
        assert "MATCH EVENTS" in trimmed
        assert "MATCH STATS" not in trimmed


# ══════════════════════════════════════════════════════════════════════════════
# _parse_events_json
# ══════════════════════════════════════════════════════════════════════════════


class TestParseEventsJson:
    def test_clean_json_parsed(self):
        result = _parse_events_json(_SAMPLE_EVENTS_JSON)
        assert result["minute"] == "71"
        assert len(result["goals"]) == 2

    def test_fenced_json_parsed(self):
        fenced = f"```json\n{_SAMPLE_EVENTS_JSON}\n```"
        result = _parse_events_json(fenced)
        assert result["minute"] == "71"

    def test_fenced_no_language_tag(self):
        fenced = f"```\n{_SAMPLE_EVENTS_JSON}\n```"
        result = _parse_events_json(fenced)
        assert isinstance(result, dict)
        assert "goals" in result

    def test_garbage_returns_empty_dict(self):
        result = _parse_events_json("No tengo esa información, lo siento.")
        assert result == {}

    def test_non_dict_returns_empty_dict(self):
        result = _parse_events_json("[1, 2, 3]")
        assert result == {}

    def test_partial_json_returns_empty_dict(self):
        result = _parse_events_json('{"minute": "71"')
        assert result == {}


# ══════════════════════════════════════════════════════════════════════════════
# extract_match_events
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractMatchEvents:
    @pytest.mark.asyncio
    async def test_returns_parsed_events(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_JSON)
        result = await extract_match_events(ai, _REAL_THREAD_SAMPLE, "Portugal", "Congo DR")
        assert result["minute"] == "71"
        assert len(result["goals"]) == 2
        assert result["goals"][0]["scorer"] == "João Neves"
        assert len(result["cards"]) == 2
        assert len(result["subs"]) == 3

    @pytest.mark.asyncio
    async def test_fenced_json_parsed_correctly(self):
        ai = MagicMock()
        fenced = f"```json\n{_SAMPLE_EVENTS_JSON}\n```"
        ai.complete = AsyncMock(return_value=fenced)
        result = await extract_match_events(ai, "some thread", "Portugal", "Congo DR")
        assert result["minute"] == "71"
        assert len(result["goals"]) == 2

    @pytest.mark.asyncio
    async def test_garbage_response_returns_empty_structure(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value="No sé nada de este partido, perdona.")
        result = await extract_match_events(ai, "thread", "Portugal", "Congo DR")
        assert result == {
            "minute": None,
            "goals": [],
            "cards": [],
            "subs": [],
            "lineup": {"home": [], "away": []},
        }

    @pytest.mark.asyncio
    async def test_ai_raises_returns_empty_structure(self):
        from worldcup_bot.ai.client import AIError
        ai = MagicMock()
        ai.complete = AsyncMock(side_effect=AIError("api failure"))
        result = await extract_match_events(ai, "thread", "Portugal", "Congo DR")
        assert result == {
            "minute": None,
            "goals": [],
            "cards": [],
            "subs": [],
            "lineup": {"home": [], "away": []},
        }

    @pytest.mark.asyncio
    async def test_never_raises_on_any_exception(self):
        ai = MagicMock()
        ai.complete = AsyncMock(side_effect=RuntimeError("unexpected crash"))
        # Must not raise
        result = await extract_match_events(ai, "thread", "X", "Y")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_called_with_zero_temperature(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_JSON)
        await extract_match_events(ai, "thread", "Portugal", "Congo DR")
        assert ai.complete.call_args.kwargs["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_system_prompt_contains_team_names(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_JSON)
        await extract_match_events(ai, "thread", "Portugal", "Congo DR")
        system = ai.complete.call_args.kwargs["system"]
        assert "Portugal" in system
        assert "Congo DR" in system

    @pytest.mark.asyncio
    async def test_real_sample_trims_stats_from_user_arg(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_JSON)
        await extract_match_events(ai, _REAL_THREAD_SAMPLE, "Portugal", "Congo DR")
        user_arg = ai.complete.call_args.kwargs["user"]
        assert "MATCH STATS" not in user_arg
        assert "João Neves" in user_arg

    @pytest.mark.asyncio
    async def test_malformed_entries_dropped(self):
        bad_json = '{"minute": "50", "goals": [{"minute": "10"}], "cards": [], "subs": []}'
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=bad_json)
        result = await extract_match_events(ai, "thread", "X", "Y")
        # goals entry missing 'team' and 'scorer' → dropped
        assert result["goals"] == []

    @pytest.mark.asyncio
    async def test_minute_null_preserved(self):
        json_str = '{"minute": null, "goals": [], "cards": [], "subs": []}'
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=json_str)
        result = await extract_match_events(ai, "thread", "X", "Y")
        assert result["minute"] is None

    @pytest.mark.asyncio
    async def test_max_completion_tokens_is_1200(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_JSON)
        await extract_match_events(ai, "thread", "Portugal", "Congo DR")
        assert ai.complete.call_args.kwargs["max_completion_tokens"] == 1200

    @pytest.mark.asyncio
    async def test_lineup_returned_in_result(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_WITH_LINEUP_JSON)
        result = await extract_match_events(ai, _REAL_THREAD_SAMPLE_WITH_LINEUP, "Portugal", "Congo DR")
        assert result["lineup"] == {
            "home": ["Diogo Costa", "Gonçalo Inácio", "João Neves", "Francisco Conceição"],
            "away": ["Masuaku", "Wissa"],
        }

    @pytest.mark.asyncio
    async def test_lineup_empty_fallback(self):
        ai = MagicMock()
        ai.complete = AsyncMock(return_value=_SAMPLE_EVENTS_JSON)
        result = await extract_match_events(ai, _REAL_THREAD_SAMPLE_WITH_LINEUP, "Portugal", "Congo DR")
        assert result["lineup"] == {"home": [], "away": []}

    @pytest.mark.asyncio
    async def test_never_raises_always_has_lineup_key(self):
        ai = MagicMock()
        ai.complete = AsyncMock(side_effect=RuntimeError("boom"))
        result = await extract_match_events(ai, "thread", "X", "Y")
        assert "lineup" in result
        assert result["lineup"] == {"home": [], "away": []}
