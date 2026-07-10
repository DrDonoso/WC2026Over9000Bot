"""Tests for update_profiles_from_conversation (profile_updater.py).

Covers:
- Empty timeline → NO ai.complete call, returns current_profiles unchanged (same object)
- AIError → current profiles unchanged, no exception raised
- Malformed JSON / JSON array root → current profiles unchanged
- Markdown-fenced JSON → parsed correctly
- Profiles updated from a multi-user conversation
- updated_at set to the _now timestamp
- Existing fields preserved when AI returns null/empty
- piques_recientes NOT touched by updater
- pinned_fields NOT overwritten (rasgos, equipo, motes, temas, tono)
- Non-pinned fields updated even when others are pinned
- motes/temas accumulate (union, no duplicates)
- New user (absent from current_profiles) gets a new profile
- Prompt sent to ai contains [username] texto attributed conversation lines
- Prompt contains current profiles context
- System prompt is passed as first arg to ai.complete
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from worldcup_bot.ai.client import AIError
from worldcup_bot.chat.profile_updater import (
    MOTES_CAP,
    TEMAS_CAP,
    update_profiles_from_conversation,
)
from worldcup_bot.chat.profiles import UserProfile

_UTC = timezone.utc
_NOW = datetime(2026, 7, 10, 4, 0, 0, tzinfo=_UTC)


def _make_ai(response: str = "{}") -> MagicMock:
    ai = MagicMock()
    ai.complete = AsyncMock(return_value=response)
    return ai


def _msgs(*pairs: tuple[str, str]) -> list[dict]:
    """Build timeline message list from (username, text) pairs."""
    base_ts = datetime(2026, 7, 10, 10, 0, 0, tzinfo=_UTC)
    return [
        {"ts": base_ts.isoformat(), "username": u, "text": t}
        for u, t in pairs
    ]


# ── Empty timeline ────────────────────────────────────────────────────────────


class TestEmptyTimeline:
    async def test_no_ai_call_when_timeline_empty(self):
        ai = _make_ai()
        current = {"alice": UserProfile(username="alice", rasgos="extrovertida")}
        await update_profiles_from_conversation([], current, ai, _now=lambda: _NOW)
        ai.complete.assert_not_called()

    async def test_returns_current_profiles_object_unchanged(self):
        ai = _make_ai()
        current = {"alice": UserProfile(username="alice", rasgos="extrovertida")}
        result = await update_profiles_from_conversation([], current, ai, _now=lambda: _NOW)
        assert result is current

    async def test_empty_timeline_empty_current_returns_same(self):
        ai = _make_ai()
        current: dict = {}
        result = await update_profiles_from_conversation([], current, ai, _now=lambda: _NOW)
        assert result is current
        ai.complete.assert_not_called()


# ── AIError handling ──────────────────────────────────────────────────────────


class TestAIError:
    async def test_ai_error_returns_current_profiles_unchanged(self):
        ai = _make_ai()
        ai.complete = AsyncMock(side_effect=AIError("rate limit"))
        current = {"alice": UserProfile(username="alice", rasgos="extrovertida")}
        msgs = _msgs(("alice", "hola!"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result is current

    async def test_ai_error_does_not_raise(self):
        ai = _make_ai()
        ai.complete = AsyncMock(side_effect=AIError("timeout"))
        msgs = _msgs(("alice", "texto largo de prueba"))
        # Must not propagate
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert result == {}

    async def test_ai_error_profile_count_unchanged(self):
        ai = _make_ai()
        ai.complete = AsyncMock(side_effect=AIError("error"))
        current = {
            "alice": UserProfile(username="alice"),
            "bob": UserProfile(username="bob"),
        }
        msgs = _msgs(("alice", "hola"), ("bob", "qué tal"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert len(result) == 2


# ── Malformed JSON ────────────────────────────────────────────────────────────


class TestMalformedJSON:
    async def test_non_json_response_returns_current_unchanged(self):
        ai = _make_ai("esto no es JSON para nada, dígamelo como quiera")
        current = {"alice": UserProfile(username="alice", rasgos="original")}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result is current
        assert result["alice"].rasgos == "original"

    async def test_json_array_root_returns_current_unchanged(self):
        ai = _make_ai('["alice", "bob", "charlie"]')
        current = {"alice": UserProfile(username="alice")}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result is current

    async def test_malformed_json_does_not_raise(self):
        ai = _make_ai("{incomplete json")
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert result == {}

    async def test_markdown_fenced_json_is_parsed_correctly(self):
        """```json ... ``` code fence must be stripped before JSON parsing."""
        inner = json.dumps({
            "alice": {"rasgos": "cool", "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        fenced = f"```json\n{inner}\n```"
        ai = _make_ai(fenced)
        msgs = _msgs(("alice", "hola"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert "alice" in result
        assert result["alice"].rasgos == "cool"

    async def test_markdown_fence_without_language_tag_parsed(self):
        """Plain ``` without language tag is also stripped."""
        inner = json.dumps({
            "alice": {"rasgos": "ok", "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        fenced = f"```\n{inner}\n```"
        ai = _make_ai(fenced)
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert "alice" in result


# ── Profile merge correctness ─────────────────────────────────────────────────


class TestProfileMerge:
    async def test_profiles_updated_from_multi_user_conversation(self):
        response = json.dumps({
            "alice": {
                "rasgos": "extrovertida",
                "equipo": "España",
                "motes": ["Ali"],
                "temas": ["futbol"],
                "tono": "amigable",
            },
            "bob": {
                "rasgos": "callado",
                "equipo": "Argentina",
                "motes": [],
                "temas": ["tenis"],
                "tono": "sarcástico",
            },
        })
        ai = _make_ai(response)
        msgs = _msgs(("alice", "Hola!"), ("bob", "¿Qué tal?"), ("alice", "Todo bien"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        assert "alice" in result
        assert "bob" in result
        assert result["alice"].rasgos == "extrovertida"
        assert result["alice"].equipo == "España"
        assert result["bob"].equipo == "Argentina"
        assert result["bob"].tono == "sarcástico"

    async def test_updated_at_set_to_now_on_success(self):
        response = json.dumps({
            "alice": {"rasgos": "ok", "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        msgs = _msgs(("alice", "hola"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert result["alice"].updated_at is not None
        assert "2026-07-10" in result["alice"].updated_at

    async def test_null_ai_fields_fall_back_to_existing_values(self):
        """AI returning null/empty for a field preserves the existing value."""
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", rasgos="extrovertida", equipo="España")}
        msgs = _msgs(("alice", "hola"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].rasgos == "extrovertida"
        assert result["alice"].equipo == "España"

    async def test_piques_recientes_not_touched_by_updater(self):
        """piques_recientes is managed by maybe_reply only, not the updater."""
        response = json.dumps({
            "alice": {"rasgos": "nueva", "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        existing_pique = {"ts": "2026-07-10T10:00:00+00:00", "texto": "pique anterior"}
        current = {"alice": UserProfile(username="alice", piques_recientes=[existing_pique])}
        msgs = _msgs(("alice", "hola"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].piques_recientes == [existing_pique]

    async def test_new_user_absent_from_current_profiles_is_created(self):
        response = json.dumps({
            "charlie": {"rasgos": "nuevo", "equipo": "Panama", "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        msgs = _msgs(("charlie", "hola soy nuevo en el grupo"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert "charlie" in result
        assert result["charlie"].rasgos == "nuevo"
        assert result["charlie"].equipo == "Panama"

    async def test_non_dict_ai_field_value_skipped(self):
        """AI returning non-dict for a username entry → that entry is skipped."""
        response = json.dumps({
            "alice": "this should be a dict",
            "bob": {"rasgos": "ok", "equipo": None, "motes": [], "temas": [], "tono": None},
        })
        ai = _make_ai(response)
        msgs = _msgs(("alice", "texto"), ("bob", "texto"))
        result = await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)
        assert "bob" in result
        assert "alice" not in result


# ── Pinned fields ─────────────────────────────────────────────────────────────


class TestPinnedFields:
    async def test_pinned_rasgos_not_overwritten(self):
        response = json.dumps({
            "alice": {"rasgos": "nuevo valor AI", "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", rasgos="valor fijo", pinned_fields=["rasgos"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].rasgos == "valor fijo"

    async def test_pinned_equipo_not_overwritten(self):
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": "AI inventa equipo", "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", equipo="España fijo", pinned_fields=["equipo"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].equipo == "España fijo"

    async def test_pinned_motes_not_modified(self):
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": None, "motes": ["mote nuevo"], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=["mote fijo"], pinned_fields=["motes"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].motes == ["mote fijo"]

    async def test_pinned_temas_not_modified(self):
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": None, "motes": [], "temas": ["tema nuevo"], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", temas=["futbol fijo"], pinned_fields=["temas"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].temas == ["futbol fijo"]

    async def test_pinned_tono_not_overwritten(self):
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": None, "motes": [], "temas": [], "tono": "tono nuevo AI"}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", tono="tono fijo", pinned_fields=["tono"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].tono == "tono fijo"

    async def test_non_pinned_field_updated_when_another_is_pinned(self):
        """Pinning 'equipo' must NOT prevent 'rasgos' from being updated."""
        response = json.dumps({
            "alice": {
                "rasgos": "nuevo rasgos AI",
                "equipo": "Nuevo equipo AI",
                "motes": [],
                "temas": [],
                "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {
            "alice": UserProfile(
                username="alice",
                rasgos="viejo rasgos",
                equipo="España fijo",
                pinned_fields=["equipo"],
            )
        }
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert result["alice"].equipo == "España fijo"       # pinned — unchanged
        assert result["alice"].rasgos == "nuevo rasgos AI"   # not pinned — updated

    async def test_pinned_fields_list_preserved_after_update(self):
        """pinned_fields itself must survive the merge."""
        response = json.dumps({
            "alice": {"rasgos": "nuevo", "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", pinned_fields=["equipo", "tono"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert set(result["alice"].pinned_fields) == {"equipo", "tono"}


# ── Motes / temas accumulation ────────────────────────────────────────────────


class TestMotesTemasAccumulation:
    async def test_motes_union_no_duplicates(self):
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": ["Ali", "la voz nueva"],
                "temas": [], "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=["Ali", "existente"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        motes = result["alice"].motes
        assert "Ali" in motes
        assert "existente" in motes
        assert "la voz nueva" in motes
        assert motes.count("Ali") == 1  # no duplicate

    async def test_temas_union_no_duplicates(self):
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": [],
                "temas": ["futbol", "viajes_nuevo"],
                "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", temas=["futbol", "viajes_existente"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        temas = result["alice"].temas
        assert "futbol" in temas
        assert "viajes_existente" in temas
        assert "viajes_nuevo" in temas
        assert temas.count("futbol") == 1  # no duplicate

    async def test_empty_existing_motes_set_from_ai(self):
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": None, "motes": ["nuevomote"], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=[])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert "nuevomote" in result["alice"].motes

    async def test_existing_motes_preserved_when_ai_returns_empty(self):
        response = json.dumps({
            "alice": {"rasgos": None, "equipo": None, "motes": [], "temas": [], "tono": None}
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=["conservado"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)
        assert "conservado" in result["alice"].motes


# ── Prompt content assertions ─────────────────────────────────────────────────


class TestPromptContents:
    async def test_prompt_contains_attributed_conversation_lines(self):
        """[username] texto lines must appear in the user_prompt sent to ai.complete."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "primer mensaje"), ("bob", "segundo mensaje"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_args = ai.complete.call_args
        user_prompt = call_args[0][1]  # second positional arg
        assert "[alice] primer mensaje" in user_prompt
        assert "[bob] segundo mensaje" in user_prompt

    async def test_prompt_contains_current_profiles_context(self):
        """Current profiles JSON must appear in the user_prompt."""
        ai = _make_ai("{}")
        current = {"alice": UserProfile(username="alice", rasgos="extrovertida")}
        msgs = _msgs(("alice", "texto"))
        await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        call_args = ai.complete.call_args
        user_prompt = call_args[0][1]
        assert "alice" in user_prompt
        assert "extrovertida" in user_prompt

    async def test_system_prompt_is_first_arg_to_ai_complete(self):
        """The system prompt (not user prompt) is the first arg to ai.complete."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "texto"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_args = ai.complete.call_args
        system_prompt = call_args[0][0]  # first positional arg
        # The system prompt instructs about profile analysis
        assert any(kw in system_prompt.lower() for kw in ["perfil", "usuario", "conversaci"])

    async def test_prompt_conversation_lines_in_chrono_order(self):
        """Messages appear in the prompt in chronological order (index order)."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "primero"), ("bob", "segundo"), ("charlie", "tercero"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_args = ai.complete.call_args
        user_prompt = call_args[0][1]
        idx_primero = user_prompt.index("[alice] primero")
        idx_segundo = user_prompt.index("[bob] segundo")
        idx_tercero = user_prompt.index("[charlie] tercero")
        assert idx_primero < idx_segundo < idx_tercero

    async def test_ai_called_with_low_temperature(self):
        """Profile updates use temperature=0.3 (deterministic)."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "texto"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_kwargs = ai.complete.call_args[1]
        assert call_kwargs.get("temperature") == 0.3


# ── M3: Insertion-order preservation (dict.fromkeys) ─────────────────────────


class TestMotesTemasInsertionOrder:
    """M3: list(dict.fromkeys([*existing, *new])) — existing first, new appended, dedup by first occurrence."""

    async def test_motes_existing_items_precede_new_items(self):
        """New motes are appended AFTER all existing motes, never before."""
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": ["new1", "new2"],
                "temas": [], "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=["old1", "old2"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        motes = result["alice"].motes
        assert motes.index("old1") < motes.index("new1")
        assert motes.index("old1") < motes.index("new2")
        assert motes.index("old2") < motes.index("new1")
        assert motes.index("old2") < motes.index("new2")

    async def test_motes_duplicate_keeps_first_occurrence_at_existing_position(self):
        """Mote in both existing and new → kept at its existing position, not appended again."""
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": ["new1", "DUPE"],  # DUPE already exists
                "temas": [], "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=["DUPE", "old1"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        motes = result["alice"].motes
        assert motes.count("DUPE") == 1                    # deduped — exactly once
        assert motes.index("DUPE") < motes.index("new1")  # at existing position, before new

    async def test_motes_exact_order_existing_first_new_appended_deduped(self):
        """Full order assertion: [A, B] existing + [B, C_new] new → [A, B, C_new]."""
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": ["B", "C_new"],  # B is dup; C_new is genuinely new
                "temas": [], "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=["A", "B"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        assert result["alice"].motes == ["A", "B", "C_new"]

    async def test_temas_exact_order_existing_first_new_appended_deduped(self):
        """Temas follow same insertion-order rule: [P, Q] + [Q, R_new] → [P, Q, R_new]."""
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": [],
                "temas": ["Q", "R_new"],
                "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", temas=["P", "Q"])}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        assert result["alice"].temas == ["P", "Q", "R_new"]


# ── M4: MOTES_CAP = 8 — keep-most-recent ([-CAP:] drops oldest) ───────────────


class TestMotesCapKeepMostRecent:
    """M4: motes[-MOTES_CAP:] — oldest entries dropped when over cap."""

    async def test_motes_exactly_at_cap_all_kept(self):
        """Exactly MOTES_CAP unique motes → all kept, none dropped."""
        all_motes = [f"m{i}" for i in range(1, MOTES_CAP + 1)]  # exactly 8
        existing = all_motes[:4]
        new = all_motes[4:]
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": new,
                "temas": [], "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=existing)}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        assert len(result["alice"].motes) == MOTES_CAP

    async def test_motes_over_cap_drops_oldest(self):
        """existing(5) + new(6) = 11 unique → capped to 8; oldest 3 (old1,old2,old3) dropped."""
        existing_motes = [f"old{i}" for i in range(1, 6)]   # old1..old5
        new_motes = [f"new{i}" for i in range(1, 7)]         # new1..new6
        # union order: old1,old2,old3,old4,old5,new1,new2,new3,new4,new5,new6 → 11
        # [-8:] → old4,old5,new1,new2,new3,new4,new5,new6  (drops old1,old2,old3)
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": new_motes,
                "temas": [], "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", motes=existing_motes)}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        motes = result["alice"].motes
        assert len(motes) == MOTES_CAP
        # All newest entries (new motes) are present
        for m in new_motes:
            assert m in motes
        # Oldest existing entries are dropped
        assert "old1" not in motes
        assert "old2" not in motes
        assert "old3" not in motes
        # Mid-range existing entries survive (within the last 8)
        assert "old4" in motes
        assert "old5" in motes


# ── M4: TEMAS_CAP = 10 — keep-most-recent ([-CAP:] drops oldest) ──────────────


class TestTemasCapKeepMostRecent:
    """M4: temas[-TEMAS_CAP:] — oldest entries dropped when over cap."""

    async def test_temas_exactly_at_cap_all_kept(self):
        """Exactly TEMAS_CAP unique temas → all kept."""
        all_temas = [f"t{i}" for i in range(1, TEMAS_CAP + 1)]  # exactly 10
        existing = all_temas[:5]
        new = all_temas[5:]
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": [],
                "temas": new,
                "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", temas=existing)}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        assert len(result["alice"].temas) == TEMAS_CAP

    async def test_temas_over_cap_drops_oldest(self):
        """existing(7) + new(6) = 13 unique → capped to 10; oldest 3 (ex1,ex2,ex3) dropped."""
        existing_temas = [f"ex{i}" for i in range(1, 8)]   # ex1..ex7
        new_temas = [f"nw{i}" for i in range(1, 7)]         # nw1..nw6
        # union order: ex1,ex2,...,ex7,nw1,...,nw6 → 13
        # [-10:] → ex4,ex5,ex6,ex7,nw1,nw2,nw3,nw4,nw5,nw6  (drops ex1,ex2,ex3)
        response = json.dumps({
            "alice": {
                "rasgos": None, "equipo": None,
                "motes": [],
                "temas": new_temas,
                "tono": None,
            }
        })
        ai = _make_ai(response)
        current = {"alice": UserProfile(username="alice", temas=existing_temas)}
        msgs = _msgs(("alice", "texto"))
        result = await update_profiles_from_conversation(msgs, current, ai, _now=lambda: _NOW)

        temas = result["alice"].temas
        assert len(temas) == TEMAS_CAP
        # All newest entries (new temas) are present
        for t in new_temas:
            assert t in temas
        # Oldest existing entries are dropped
        assert "ex1" not in temas
        assert "ex2" not in temas
        assert "ex3" not in temas
        # Mid-range existing entries survive (within the last 10)
        for i in range(4, 8):
            assert f"ex{i}" in temas


# ── M5: max_completion_tokens = max(200, 200 * N) ─────────────────────────────


class TestMaxCompletionTokens:
    """M5: max_completion_tokens kwarg passed to ai.complete equals max(200, 200 * N)."""

    async def test_max_tokens_one_participant(self):
        """N=1 → max(200, 200*1) = 200."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "único participante"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_kwargs = ai.complete.call_args[1]
        assert call_kwargs.get("max_completion_tokens") == max(200, 200 * 1)

    async def test_max_tokens_two_participants(self):
        """N=2 → max(200, 200*2) = 400."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "hola"), ("bob", "qué tal"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_kwargs = ai.complete.call_args[1]
        assert call_kwargs.get("max_completion_tokens") == max(200, 200 * 2)

    async def test_max_tokens_five_participants(self):
        """N=5 → max(200, 200*5) = 1000."""
        ai = _make_ai("{}")
        msgs = _msgs(
            ("alice", "a"),
            ("bob", "b"),
            ("charlie", "c"),
            ("diana", "d"),
            ("eve", "e"),
        )
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_kwargs = ai.complete.call_args[1]
        assert call_kwargs.get("max_completion_tokens") == max(200, 200 * 5)

    async def test_max_tokens_same_user_multiple_msgs_counts_once(self):
        """Multiple messages from same user → N=1; tokens = max(200, 200*1) = 200."""
        ai = _make_ai("{}")
        msgs = _msgs(("alice", "msg1"), ("alice", "msg2"), ("alice", "msg3"))
        await update_profiles_from_conversation(msgs, {}, ai, _now=lambda: _NOW)

        call_kwargs = ai.complete.call_args[1]
        assert call_kwargs.get("max_completion_tokens") == max(200, 200 * 1)
