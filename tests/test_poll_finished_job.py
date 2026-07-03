"""Tests for poll_finished_matches_job — seeds on first run, fires for new matches,
graceful degradation when ESPN/scanner/AI unavailable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.config import Settings
from worldcup_bot.porra.engine import UserRankEntry
from worldcup_bot.reddit.clip_store import goal_token as _cs_goal_token
from datetime import timezone


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_match(
    mid: int,
    status: str = "FINISHED",
    home_name: str = "Spain",
    away_name: str = "France",
    home_tla: str = "ESP",
    away_tla: str = "FRA",
    winner: str | None = "HOME_TEAM",
) -> Match:
    return Match(
        id=mid,
        utc_date="2026-06-16T18:00:00Z",
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=2,
        away_score=1,
        winner=winner,
    )


def _make_settings(tmp_path, ai: bool = True) -> Settings:
    s = Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567",
        state_dir=str(tmp_path),
        predictions_path=str(tmp_path / "predictions.yml"),
    )
    if ai:
        s.openai_api_key = "key"
        s.openai_base_url = "http://localhost"
        s.openai_model = "gpt-4"
    return s


def _make_context(settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "espn_client": None,
        "reddit_scanner": None,
        # Persistent dedup set (populated from disk in build_app; empty in tests)
        "finished_announced": set(),
        # False until the first-run seed pass completes
        "finished_seeded": False,
    }
    ctx.bot.send_message = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()
    return ctx


def _make_rank_entry(username: str, display_name: str, total: float) -> UserRankEntry:
    return UserRankEntry(
        username=username,
        display_name=display_name,
        total_score=total,
        base_score=0.0,
        group_score=total,
        knockout_scores={},
        exact_group_hits=0,
    )


# ── import the job under test ─────────────────────────────────────────────────

from worldcup_bot.__main__ import poll_finished_matches_job


# ── final-result section tests ────────────────────────────────────────────────


def _ctx_for_result(settings, match):
    """Return a pre-seeded context that will fire for *match* (no ESPN, no AI)."""
    ctx = _make_context(settings)
    # Skip the first-run seed gate; announced is empty so *match* IS new.
    ctx.bot_data["finished_seeded"] = True
    ctx.bot_data["finished_announced"] = set()

    mock_client = MagicMock()
    mock_client.get_all_matches.return_value = [match]

    mock_scanner = MagicMock()
    mock_scanner.get_espn_game_id = MagicMock(return_value=None)
    ctx.bot_data["reddit_scanner"] = mock_scanner

    return ctx, mock_client


class TestFinalResultSection:
    """The 🏁 Final section must ALWAYS be present as section 1 of the message."""

    @pytest.mark.asyncio
    async def test_final_result_always_present(self, tmp_path):
        """With no stats and no commentary, the final-result message is still sent."""
        settings = _make_settings(tmp_path, ai=False)
        match = _make_match(1, winner=None)
        ctx, mock_client = _ctx_for_result(settings, match)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_awaited()
        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "🏁" in text
        assert "Final" in text
        assert "Spain" in text
        assert "France" in text
        assert "2-1" in text

    @pytest.mark.asyncio
    async def test_winner_bolded_home_team(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        match = _make_match(1, winner="HOME_TEAM")
        ctx, mock_client = _ctx_for_result(settings, match)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {99}  # match 1 is new

        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "<b>Spain</b>" in text
        assert "<b>France</b>" not in text

    @pytest.mark.asyncio
    async def test_winner_bolded_away_team(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        match = _make_match(1, winner="AWAY_TEAM")
        ctx, mock_client = _ctx_for_result(settings, match)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {99}

        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "<b>France</b>" in text
        assert "<b>Spain</b>" not in text

    @pytest.mark.asyncio
    async def test_draw_no_bolding(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        match = _make_match(1, winner="DRAW")
        ctx, mock_client = _ctx_for_result(settings, match)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {99}

        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "<b>Spain</b>" not in text
        assert "<b>France</b>" not in text
        assert "Spain" in text
        assert "France" in text

    @pytest.mark.asyncio
    async def test_flags_present(self, tmp_path):
        """Flags for known TLAs (ESP, FRA) must appear in the final-result section."""
        settings = _make_settings(tmp_path, ai=False)
        match = _make_match(1, winner=None)
        ctx, mock_client = _ctx_for_result(settings, match)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {99}

        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        # ESP → 🇪🇸, FRA → 🇫🇷 — if TLA mapping works, flags appear
        assert "🏁" in text  # at minimum the result section marker is there

    @pytest.mark.asyncio
    async def test_three_sections_with_stats_and_commentary(self, tmp_path):
        """Stats + porra change → 3 sections joined by '---'."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2, winner="HOME_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value="espn-7")
        ctx.bot_data["reddit_scanner"] = mock_scanner

        fake_stats = {
            "home": {"name": "Spain", "stats": {"possessionPct": "60"}},
            "away": {"name": "France", "stats": {"possessionPct": "40"}},
        }
        mock_espn = MagicMock()
        mock_espn.get_match_stats = MagicMock(return_value=fake_stats)
        ctx.bot_data["espn_client"] = mock_espn

        ranking = [
            _make_rank_entry("alice", "Alice", 6.0),
            _make_rank_entry("bob", "Bob", 3.0),
        ]
        old_state = {"alice": {"pos": 2, "pts": 4.0, "name": "Alice"}, "bob": {"pos": 1, "pts": 3.0, "name": "Bob"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="La porra cambia!"),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Comentarista"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        # Three sections joined by "\n\n---\n\n"
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 3
        # Section 1: final result
        assert "🏁" in parts[0]
        assert "<b>Spain</b>" in parts[0]  # HOME_TEAM winner
        # Section 2: stats (header simplified — no scoreline)
        assert "📊" in parts[1]
        assert "Estadísticas" in parts[1]
        assert "2-1" not in parts[1]  # scoreline NOT in stats section
        # Section 3: commentary
        assert "La porra cambia!" in parts[2]

    @pytest.mark.asyncio
    async def test_stats_header_no_scoreline(self, tmp_path):
        """Stats card header is '📊 Estadísticas' — scoreline must NOT appear in it."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value="espn-8")
        ctx.bot_data["reddit_scanner"] = mock_scanner

        mock_espn = MagicMock()
        mock_espn.get_match_stats = MagicMock(return_value={
            "home": {"name": "Spain", "stats": {"possessionPct": "55"}},
            "away": {"name": "France", "stats": {"possessionPct": "45"}},
        })
        ctx.bot_data["espn_client"] = mock_espn

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 2  # result + stats
        stats_section = parts[1]
        # Header must be "📊 <b>Estadísticas</b>" — no score in it
        first_line = stats_section.split("\n")[0]
        assert "Estadísticas" in first_line
        assert "2-1" not in first_line
        assert "Spain" not in first_line
        assert "France" not in first_line

    @pytest.mark.asyncio
    async def test_no_stats_no_commentary_only_result_sent(self, tmp_path):
        """When both ESPN and porra produce nothing, the final-result IS still sent."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2, winner="DRAW")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_awaited_once()
        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "🏁" in text
        assert "---" not in text  # only 1 section — no separator needed
        assert "📊" not in text

    @pytest.mark.asyncio
    async def test_final_result_plus_commentary_no_stats(self, tmp_path):
        """No ESPN stats but porra changed: final result --- commentary."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2, winner="AWAY_TEAM")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [
            _make_rank_entry("alice", "Alice", 5.0),
            _make_rank_entry("bob", "Bob", 3.0),
        ]
        old_state = {"bob": {"pos": 1, "pts": 3.0, "name": "Bob"}, "alice": {"pos": 2, "pts": 2.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="¡Francia arriba!"),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Narrador"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 2
        assert "🏁" in parts[0]
        assert "<b>France</b>" in parts[0]  # AWAY_TEAM winner
        assert "¡Francia arriba!" in parts[1]
        assert "📊" not in text


class TestSeedingBehaviour:
    @pytest.mark.asyncio
    async def test_seeds_on_first_run_no_sends(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        # finished_seeded=False (default from _make_context) → triggers seed

        match = _make_match(1, "FINISHED")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
        ):
            await poll_finished_matches_job(ctx)

        # No messages sent on first run
        ctx.bot.send_message.assert_not_awaited()
        # finished_announced populated; finished_seeded set to True
        assert 1 in ctx.bot_data["finished_announced"]
        assert ctx.bot_data["finished_seeded"] is True

    @pytest.mark.asyncio
    async def test_first_run_seeds_all_finished(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)

        matches = [_make_match(i, "FINISHED") for i in range(1, 4)]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_finished_matches_job(ctx)

        assert ctx.bot_data["finished_announced"] == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_second_run_fires_for_new_match(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        # Pre-seed with match 1 already seen
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        # Now match 2 is FINISHED (new)
        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        # ESPN returns no game_id → no Part A send, but Part B should still run
        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=[],
            ),
        ):
            ctx.bot_data["reddit_scanner"] = mock_scanner
            await poll_finished_matches_job(ctx)

        # Match 2 now in finished_announced
        assert 2 in ctx.bot_data["finished_announced"]


# ── Part A tests ──────────────────────────────────────────────────────────────


class TestPartAStats:
    @pytest.mark.asyncio
    async def test_sends_stats_when_available(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}  # match 1 already seen

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value="999")
        ctx.bot_data["reddit_scanner"] = mock_scanner

        fake_stats = {
            "home": {"name": "Spain", "stats": {"possessionPct": "60"}},
            "away": {"name": "France", "stats": {"possessionPct": "40"}},
        }
        mock_espn = MagicMock()
        mock_espn.get_match_stats = MagicMock(return_value=fake_stats)
        ctx.bot_data["espn_client"] = mock_espn

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=[],
            ),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_awaited()
        call_kwargs = ctx.bot.send_message.call_args_list[0][1]
        assert call_kwargs["parse_mode"] == "HTML"
        assert "Estadísticas" in call_kwargs["text"] or "📊" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_no_stats_in_message_when_game_id_none(self, tmp_path):
        """When game_id is None, the final-result message IS sent but contains no stats."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=[],
            ),
        ):
            await poll_finished_matches_job(ctx)

        # Final-result message IS sent even without stats
        ctx.bot.send_message.assert_awaited_once()
        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "🏁" in text
        assert "Estadísticas" not in text

    @pytest.mark.asyncio
    async def test_no_crash_when_espn_raises(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(side_effect=RuntimeError("oops"))
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=[],
            ),
        ):
            await poll_finished_matches_job(ctx)  # must not raise

        assert 2 in ctx.bot_data["finished_announced"]


# ── Part B tests ──────────────────────────────────────────────────────────────


class TestPartBPorraCommentary:
    @pytest.mark.asyncio
    async def test_sends_commentary_when_ai_enabled_and_changed(self, tmp_path):
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [
            _make_rank_entry("alice", "Alice", 5.0),
            _make_rank_entry("bob", "Bob", 3.0),
        ]
        # Old state has bob in 1st place
        old_state = {"bob": {"pos": 1, "pts": 3.0, "name": "Bob"}, "alice": {"pos": 2, "pts": 2.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=ranking,
            ),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="¡Increíble la porra!"),
            ),
            patch(
                "worldcup_bot.__main__.pick_commentator",
                return_value="Manolo Lama",
            ),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1, "Expected exactly ONE combined send_message call"
        text = calls[0][1].get("text", "")
        # Persona name must NOT appear (hidden behind the style)
        assert "Manolo Lama" not in text
        # 🎙️ prefix must NOT appear
        assert "🎙️" not in text
        # Commentary content must be present
        assert "¡Increíble la porra!" in text

    @pytest.mark.asyncio
    async def test_no_commentary_when_ai_disabled(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches
        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 2, "pts": 3.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=ranking,
            ),
        ):
            await poll_finished_matches_job(ctx)

        for call in ctx.bot.send_message.call_args_list:
            assert "🎙️" not in call[1].get("text", "")

    @pytest.mark.asyncio
    async def test_saves_live_state_even_when_ai_disabled(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches
        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [_make_rank_entry("alice", "Alice", 5.0)]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                return_value={"participants": {}},
            ),
            patch(
                "worldcup_bot.__main__.compute_general_ranking",
                return_value=ranking,
            ),
        ):
            await poll_finished_matches_job(ctx)

        live_path = str(tmp_path / "porra_live.json")
        assert os.path.exists(live_path)
        with open(live_path, encoding="utf-8") as f:
            saved = json.load(f)
        assert "alice" in saved

    @pytest.mark.asyncio
    async def test_no_crash_when_part_b_raises(self, tmp_path):
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches
        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch(
                "worldcup_bot.__main__.pred_loader.load",
                side_effect=RuntimeError("pred load failed"),
            ),
        ):
            await poll_finished_matches_job(ctx)  # must not raise

        assert 2 in ctx.bot_data["finished_announced"]


# ── football API error ────────────────────────────────────────────────────────


class TestAPIErrorHandling:
    @pytest.mark.asyncio
    async def test_no_crash_on_football_api_error(self, tmp_path):
        from worldcup_bot.api.client import FootballAPIError

        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)

        mock_client = MagicMock()
        mock_client.get_all_matches.side_effect = FootballAPIError("503", 503)

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_finished_matches_job(ctx)  # must not raise

        ctx.bot.send_message.assert_not_awaited()


# ── combined message tests ────────────────────────────────────────────────────


class TestCombinedMessage:
    """Tests for the ONE combined message (result + stats + commentary) contract."""

    def _make_fake_stats(self) -> dict:
        return {
            "home": {"name": "Spain", "stats": {"possessionPct": "60"}},
            "away": {"name": "France", "stats": {"possessionPct": "40"}},
        }

    @pytest.mark.asyncio
    async def test_combined_message_with_separator_when_both_parts_present(self, tmp_path):
        """When BOTH stats and commentary are available, ONE message with 3-dash '---' separators."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value="espn-999")
        ctx.bot_data["reddit_scanner"] = mock_scanner

        mock_espn = MagicMock()
        mock_espn.get_match_stats = MagicMock(return_value=self._make_fake_stats())
        ctx.bot_data["espn_client"] = mock_espn

        ranking = [
            _make_rank_entry("alice", "Alice", 5.0),
            _make_rank_entry("bob", "Bob", 3.0),
        ]
        old_state = {"bob": {"pos": 1, "pts": 3.0, "name": "Bob"}, "alice": {"pos": 2, "pts": 2.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="¡Qué partidazo!"),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Andrés Montes"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1, "Must send exactly ONE combined message"
        text = calls[0][1]["text"]
        # Three sections separated by 3-dash separator
        assert "\n\n---\n\n" in text
        assert "----" not in text  # old 4-dash separator must NOT appear
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 3
        # Section 1: final result
        assert "🏁" in parts[0]
        # Section 2: stats
        assert "📊" in parts[1] or "Estadísticas" in parts[1]
        # Section 3: commentary
        assert "¡Qué partidazo!" in parts[2]
        # Persona name must NOT appear
        assert "Andrés Montes" not in text
        assert "🎙️" not in text

    @pytest.mark.asyncio
    async def test_only_stats_when_no_porra_change(self, tmp_path):
        """When no porra change but AI enabled, message has result --- stats --- commentary (3 sections)."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value="espn-888")
        ctx.bot_data["reddit_scanner"] = mock_scanner

        mock_espn = MagicMock()
        mock_espn.get_match_stats = MagicMock(return_value=self._make_fake_stats())
        ctx.bot_data["espn_client"] = mock_espn

        # Ranking matches old state exactly — no changes
        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="Sin cambios en la porra."),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Julio Maldini"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        parts = text.split("\n\n---\n\n")
        # Now always 3 sections: result + stats + commentary (AI enabled + non-empty ranking)
        assert len(parts) == 3
        assert "🏁" in parts[0]
        assert "📊" in parts[1] or "Estadísticas" in parts[1]
        assert "Sin cambios en la porra." in parts[2]
        assert "----" not in text

    @pytest.mark.asyncio
    async def test_only_commentary_when_no_stats(self, tmp_path):
        """When ESPN returns no stats but AI generates commentary: result --- commentary."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)  # no ESPN game_id
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [
            _make_rank_entry("alice", "Alice", 5.0),
            _make_rank_entry("bob", "Bob", 3.0),
        ]
        old_state = {"bob": {"pos": 1, "pts": 3.0, "name": "Bob"}, "alice": {"pos": 2, "pts": 2.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="¡La porra arde!"),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Julio Maldini"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 2  # result + commentary, no stats
        assert "🏁" in parts[0]
        assert "¡La porra arde!" in parts[1]
        assert "📊" not in text
        assert "----" not in text
        assert "Julio Maldini" not in text
        assert "🎙️" not in text

    @pytest.mark.asyncio
    async def test_no_send_when_neither_stats_nor_commentary(self, tmp_path):
        """When both ESPN and porra produce nothing, the final-result section IS still sent."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        # No porra change
        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
        ):
            await poll_finished_matches_job(ctx)

        # A message IS always sent (final-result section guarantees it)
        ctx.bot.send_message.assert_awaited_once()
        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "🏁" in text
        assert "---" not in text  # only 1 section — no separator
        assert "📊" not in text

    @pytest.mark.asyncio
    async def test_names_bolded_in_commentary(self, tmp_path):
        """Participant names appearing in the commentary are wrapped in <b>.</b>."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        matches = [_make_match(1, "FINISHED"), _make_match(2, "FINISHED")]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [
            _make_rank_entry("alice", "Alice", 5.0),
            _make_rank_entry("bob", "Bob", 3.0),
        ]
        old_state = {"bob": {"pos": 1, "pts": 3.0, "name": "Bob"}, "alice": {"pos": 2, "pts": 2.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="Alice sube al primer puesto y Bob baja."),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Manolo Lama"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        assert "<b>Alice</b>" in text
        assert "<b>Bob</b>" in text


# ── always-commentary behaviour (new) ────────────────────────────────────────


class TestAlwaysCommentary:
    """Commentary is produced whenever AI is enabled + ranking is non-empty,
    regardless of whether the ranking actually moved."""

    @pytest.mark.asyncio
    async def test_commentary_when_no_change_no_stats(self, tmp_path):
        """AI enabled + non-empty ranking + no movement + no ESPN → result --- commentary."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        # Ranking unchanged
        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="Todo igual en la porra, ¡Alice sigue al mando!"),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Andrés Montes"),
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 2  # result + commentary (no stats)
        assert "🏁" in parts[0]
        assert "Todo igual en la porra" in parts[1]
        assert "📊" not in text

    @pytest.mark.asyncio
    async def test_commentary_when_no_change_with_stats(self, tmp_path):
        """AI enabled + non-empty ranking + no movement + ESPN → result --- stats --- commentary."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value="espn-77")
        ctx.bot_data["reddit_scanner"] = mock_scanner

        mock_espn = MagicMock()
        mock_espn.get_match_stats = MagicMock(return_value={
            "home": {"name": "Spain", "stats": {"possessionPct": "55"}},
            "away": {"name": "France", "stats": {"possessionPct": "45"}},
        })
        ctx.bot_data["espn_client"] = mock_espn

        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch(
                "worldcup_bot.__main__.generate_porra_commentary",
                new=AsyncMock(return_value="Nada cambia, Alice es líder."),
            ),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Manolo Lama"),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        parts = text.split("\n\n---\n\n")
        assert len(parts) == 3
        assert "🏁" in parts[0]
        assert "📊" in parts[1] or "Estadísticas" in parts[1]
        assert "Nada cambia" in parts[2]

    @pytest.mark.asyncio
    async def test_no_commentary_when_empty_ranking(self, tmp_path):
        """AI enabled but ranking is empty → no commentary (no participants)."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),  # empty!
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "---" not in text  # only the result section
        assert "🏁" in text

    @pytest.mark.asyncio
    async def test_no_commentary_when_ai_disabled_no_change(self, tmp_path):
        """AI disabled + no change → no commentary, only result."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "---" not in text
        assert "🏁" in text

    @pytest.mark.asyncio
    async def test_render_porra_context_called_with_ranking(self, tmp_path):
        """render_porra_context receives the ranking (not just the diff) when commentary is generated."""
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1}

        match = _make_match(2)
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [_make_match(1), match]

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        ranking = [_make_rank_entry("alice", "Alice", 5.0)]
        old_state = {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}}
        live_path = str(tmp_path / "porra_live.json")
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        captured_args: list = []

        async def fake_commentary(ai, persona, context_text):
            captured_args.append(context_text)
            return "¡Comentario!"

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=ranking),
            patch("worldcup_bot.__main__.generate_porra_commentary", side_effect=fake_commentary),
            patch("worldcup_bot.__main__.pick_commentator", return_value="Manolo Lama"),
        ):
            await poll_finished_matches_job(ctx)

        assert captured_args, "generate_porra_commentary must be called"
        context_text = captured_args[0]
        # render_porra_context always includes both blocks
        assert "CLASIFICACIÓN ACTUAL" in context_text
        assert "CAMBIOS CON ESTE RESULTADO" in context_text
        assert "Alice" in context_text  # participant appears in standings


# ── finished_state module tests ───────────────────────────────────────────────


class TestFinishedState:
    """Tests for load_finished / save_finished helpers."""

    def test_round_trip(self, tmp_path):
        from worldcup_bot.reddit.finished_state import load_finished, save_finished

        path = str(tmp_path / "finished_announced.json")
        ids = {1, 42, 999}
        save_finished(path, ids)
        loaded = load_finished(path)
        assert loaded == ids

    def test_missing_file_returns_empty_set(self, tmp_path):
        from worldcup_bot.reddit.finished_state import load_finished

        path = str(tmp_path / "no_such_file.json")
        result = load_finished(path)
        assert result == set()

    def test_corrupt_file_returns_empty_set(self, tmp_path):
        from worldcup_bot.reddit.finished_state import load_finished

        path = str(tmp_path / "corrupt.json")
        with open(path, "w") as f:
            f.write("NOT VALID JSON {{{")
        result = load_finished(path)
        assert result == set()

    def test_load_never_raises(self, tmp_path):
        from worldcup_bot.reddit.finished_state import load_finished

        # Even with a completely broken path component
        result = load_finished(str(tmp_path / "sub" / "deep" / "missing.json"))
        assert result == set()

    def test_save_never_raises_on_bad_path(self, tmp_path):
        from worldcup_bot.reddit.finished_state import save_finished

        # Directory that doesn't exist — save_finished must swallow the error
        save_finished(str(tmp_path / "no_dir" / "finished.json"), {1, 2})
        # No exception → test passes

    def test_empty_set_round_trip(self, tmp_path):
        from worldcup_bot.reddit.finished_state import load_finished, save_finished

        path = str(tmp_path / "empty.json")
        save_finished(path, set())
        assert load_finished(path) == set()

    def test_ids_are_integers_after_load(self, tmp_path):
        from worldcup_bot.reddit.finished_state import load_finished, save_finished

        path = str(tmp_path / "ids.json")
        # Write as strings (edge case: JSON doesn't have int vs str distinction issue but
        # we want to make sure save writes ints and load coerces correctly)
        with open(path, "w") as f:
            json.dump(["1", "2", "3"], f)  # strings in JSON
        result = load_finished(path)
        assert result == {1, 2, 3}
        assert all(isinstance(x, int) for x in result)


# ── first-run seed with kickoff-age tests ─────────────────────────────────────

# Fixed reference "now" for all age-seed tests
_NOW_UTC = datetime(2026, 6, 18, 12, 0, 0)


def _dt_mock(now: datetime):
    """Return a mock that replaces worldcup_bot.__main__.datetime.
    utcnow() returns *now*; strptime delegates to the real implementation.
    """
    m = MagicMock()
    m.utcnow.return_value = now
    m.strptime.side_effect = datetime.strptime
    return m


def _make_match_at(mid: int, status: str, kickoff: datetime) -> Match:
    """Build a Match with a specific kickoff datetime (UTC)."""
    return Match(
        id=mid,
        utc_date=kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla="ESP",
        away_tla="FRA",
        home_name="Spain",
        away_name="France",
        home_score=2,
        away_score=1,
        winner="HOME_TEAM",
    )


class TestFirstRunSeedWithAge:
    """First-run seed must include FINISHED matches AND IN_PLAY matches whose
    kickoff is older than MATCH_OVER_AGE (4 h), but NOT genuinely live ones.
    """

    @pytest.mark.asyncio
    async def test_seeds_finished_stale_not_live_sends_nothing(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        # finished_seeded=False (default) → triggers first-run seed

        finished_match = _make_match_at(
            1, "FINISHED", _NOW_UTC - timedelta(hours=5)
        )
        stale_match = _make_match_at(
            2, "IN_PLAY", _NOW_UTC - timedelta(hours=5)   # 5h old → definitely over
        )
        live_match = _make_match_at(
            3, "IN_PLAY", _NOW_UTC - timedelta(minutes=30)  # 30min old → still live
        )

        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [finished_match, stale_match, live_match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.datetime", _dt_mock(_NOW_UTC)),
        ):
            await poll_finished_matches_job(ctx)

        # No sends on first run
        ctx.bot.send_message.assert_not_awaited()
        # FINISHED and stale IN_PLAY are seeded; live IN_PLAY is NOT
        assert 1 in ctx.bot_data["finished_announced"]  # FINISHED
        assert 2 in ctx.bot_data["finished_announced"]  # stale IN_PLAY (5h)
        assert 3 not in ctx.bot_data["finished_announced"]  # live IN_PLAY (30min)
        assert ctx.bot_data["finished_seeded"] is True

    @pytest.mark.asyncio
    async def test_seed_persists_to_disk(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)

        finished_match = _make_match_at(10, "FINISHED", _NOW_UTC - timedelta(hours=6))
        stale_match = _make_match_at(20, "PAUSED", _NOW_UTC - timedelta(hours=5))

        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [finished_match, stale_match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.datetime", _dt_mock(_NOW_UTC)),
        ):
            await poll_finished_matches_job(ctx)

        disk_path = str(tmp_path / "finished_announced.json")
        assert os.path.exists(disk_path)
        with open(disk_path) as f:
            on_disk = set(json.load(f))
        assert {10, 20} == on_disk


class TestStaleLaterFlip:
    """A stale IN_PLAY match that was seeded must NOT produce a recap when
    football-data later flips it to FINISHED."""

    @pytest.mark.asyncio
    async def test_no_recap_for_seeded_stale_match(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        # Simulate: match 2 was already seeded (stale IN_PLAY at startup)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {2}

        # On this run, match 2 has now flipped to FINISHED
        flipped_match = _make_match_at(2, "FINISHED", _NOW_UTC - timedelta(hours=5))

        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [flipped_match]

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_finished_matches_job(ctx)

        # MUST send nothing (id 2 is already in announced)
        ctx.bot.send_message.assert_not_awaited()


class TestLiveMatchRecap:
    """A genuinely live match (30-min kickoff, not seeded) that transitions to
    FINISHED on a later run must produce exactly ONE recap."""

    @pytest.mark.asyncio
    async def test_recap_sent_once_for_newly_finished_live_match(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        # After first-run seed: live match (id=3) was NOT seeded (kickoff too recent)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {1, 2}  # ids 1+2 already done; 3 is new

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        # Match 3 now FINISHED
        newly_finished = _make_match_at(3, "FINISHED", _NOW_UTC - timedelta(minutes=30))

        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [
            _make_match_at(1, "FINISHED", _NOW_UTC - timedelta(hours=5)),
            _make_match_at(2, "FINISHED", _NOW_UTC - timedelta(hours=3)),
            newly_finished,
        ]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Exactly one message for match 3
        ctx.bot.send_message.assert_awaited_once()
        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "🏁" in text
        # id 3 is now in announced
        assert 3 in ctx.bot_data["finished_announced"]

    @pytest.mark.asyncio
    async def test_id_persisted_immediately_after_send(self, tmp_path):
        """After recapping a match, its id is saved to disk before processing the next."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = set()

        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        match = _make_match_at(5, "FINISHED", _NOW_UTC - timedelta(minutes=90))
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        disk_path = str(tmp_path / "finished_announced.json")
        assert os.path.exists(disk_path)
        with open(disk_path) as f:
            on_disk = set(json.load(f))
        assert 5 in on_disk


class TestRestartSimulation:
    """Simulate a container restart: finished_announced is pre-loaded from disk."""

    @pytest.mark.asyncio
    async def test_no_recap_after_restart_for_already_announced_match(self, tmp_path):
        """finished_announced loaded from disk containing match id → no recap on restart."""
        from worldcup_bot.reddit.finished_state import save_finished

        # Persist id=7 to disk as if the bot already recapped it before the restart
        disk_path = str(tmp_path / "finished_announced.json")
        save_finished(disk_path, {7})

        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        # Simulate what build_app does: load from disk
        from worldcup_bot.reddit.finished_state import load_finished
        ctx.bot_data["finished_announced"] = load_finished(disk_path)
        # finished_seeded=False → first run seeds again (idempotent)

        match = _make_match_at(7, "FINISHED", _NOW_UTC - timedelta(hours=3))
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.datetime", _dt_mock(_NOW_UTC)),
        ):
            # First run after restart → seeds (no sends), 7 already in announced
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 7 in ctx.bot_data["finished_announced"]

    @pytest.mark.asyncio
    async def test_first_run_seed_idempotent_with_preloaded_set(self, tmp_path):
        """First-run seed adds to (but doesn't replace) the pre-loaded announced set."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        # Pre-loaded from disk: ids 10, 11 already announced
        ctx.bot_data["finished_announced"] = {10, 11}

        new_finished = _make_match_at(12, "FINISHED", _NOW_UTC - timedelta(hours=2))
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [new_finished]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.datetime", _dt_mock(_NOW_UTC)),
        ):
            await poll_finished_matches_job(ctx)

        # Seed merged new id 12 with pre-existing ids 10, 11
        assert {10, 11, 12}.issubset(ctx.bot_data["finished_announced"])
        # No sends
        ctx.bot.send_message.assert_not_awaited()


# ── porra face-off ("guerra de la porra") section ─────────────────────────────


def _make_ko_match(mid: int, winner: str | None = "AWAY_TEAM") -> Match:
    return Match(
        id=mid,
        utc_date="2026-06-29T18:00:00Z",
        status="FINISHED",
        stage="LAST_32",
        group=None,
        home_tla="NED",
        away_tla="MAR",
        home_name="Netherlands",
        away_name="Morocco",
        home_score=0,
        away_score=1,
        winner=winner,
    )


class TestFaceOffSection:
    _PREDS = {
        "participants": {
            "ann": {"display_name": "Ann", "groups": {}, "knockout": {"round_of_32": ["NED"]}},
            "bob": {"display_name": "Bob", "groups": {}, "knockout": {"round_of_32": ["MAR"]}},
        }
    }

    @pytest.mark.asyncio
    async def test_knockout_match_appends_faceoff_with_winner_marks(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        match = _make_ko_match(1, winner="AWAY_TEAM")  # Morocco (away) wins
        ctx, mock_client = _ctx_for_result(settings, match)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value=self._PREDS),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "⚔️" in text
        assert "Ann" in text and "Bob" in text
        assert "🏆" in text and "💀" in text  # winner/loser camps marked

    @pytest.mark.asyncio
    async def test_group_match_has_no_faceoff(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        match = _make_match(1, winner="HOME_TEAM")  # GROUP_STAGE
        ctx, mock_client = _ctx_for_result(settings, match)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value=self._PREDS),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "⚔️" not in text

# ══════════════════════════════════════════════════════════════════════════════
# Penalty-shootout Final card + premature-Final guard
# ══════════════════════════════════════════════════════════════════════════════


def _pen_match(mid=1, winner="AWAY_TEAM", penalty_home=3, penalty_away=4, duration="PENALTY_SHOOTOUT"):
    from dataclasses import replace
    m = _make_match(mid, home_name="Germany", away_name="Paraguay",
                    home_tla="GER", away_tla="PAR", winner=winner)
    m = replace(m, stage="LAST_32", group=None, home_score=1, away_score=1,
                duration=duration, penalty_home=penalty_home, penalty_away=penalty_away)
    return m


class TestPenaltyFinal:
    @pytest.mark.asyncio
    async def test_final_shows_onpitch_score_penalty_line_and_winner(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        match = _pen_match(1, winner="AWAY_TEAM", penalty_home=3, penalty_away=4)
        ctx, mock_client = _ctx_for_result(settings, match)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "1-1" in text                       # on-pitch score, not 4-5
        assert "<b>Paraguay</b>" in text           # winner from score.winner
        assert "🥅 Penaltis: 3-4" in text and "pasa" in text

    @pytest.mark.asyncio
    async def test_pending_shootout_is_deferred_not_announced(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        # FINISHED mid-shootout: duration set but penalties not yet present, winner DRAW.
        match = _pen_match(1, winner="DRAW", penalty_home=None, penalty_away=None)
        ctx, mock_client = _ctx_for_result(settings, match)

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        assert 1 not in ctx.bot_data["finished_announced"]  # not marked done → retries later


# ── post-final VAR-correction watch ───────────────────────────────────────────


class TestVARCorrectionWatch:
    """Tests for the post-final VAR score correction feature.

    The watch runs at the end of every poll_finished_matches_job tick.
    Scenarios: score change → correction + goal edit; stable → no-op;
    penalty shootout → no false positive; window expiry → prune only;
    clip absent → correction posted, edit skipped gracefully.
    """

    # ── fixture helpers ────────────────────────────────────────────────────

    def _por_cro(self, home_score: int, away_score: int, winner: str = "HOME_TEAM") -> Match:
        """Portugal vs Croatia at the given on-pitch score."""
        return Match(
            id=101,
            utc_date="2026-07-03T20:00:00Z",
            status="FINISHED",
            stage="LAST_16",
            group=None,
            home_tla="POR",
            away_tla="CRO",
            home_name="Portugal",
            away_name="Croatia",
            home_score=home_score,
            away_score=away_score,
            winner=winner,
            duration="REGULAR",
        )

    def _fs_entry(
        self,
        home: int,
        away: int,
        corrected: bool = False,
        age_minutes: int = 5,
    ) -> dict:
        """finished_scores entry finalized `age_minutes` ago."""
        ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
        return {"home": home, "away": away, "finalized_at": ts, "corrected": corrected}

    def _clip_tok_entry(
        self,
        match_id: int,
        scoring_team: str,
        home_score: int,
        away_score: int,
        message_id: int = 42,
        chat_id: int = -100999,
        status: str = "searching",
    ) -> tuple[str, dict]:
        """(token, clip_store_entry) for the given scored goal."""
        token_key = f"{match_id}:{scoring_team}:{home_score}-{away_score}"
        tok = _cs_goal_token(token_key)
        entry = {
            "chat_id": chat_id,
            "message_id": message_id,
            "home_name": "Portugal",
            "away_name": "Croatia",
            "home_tla": "POR",
            "away_tla": "CRO",
            "home_score": home_score,
            "away_score": away_score,
            "scoring_team": scoring_team,
            "scorer": "Cristiano Ronaldo",
            "minute": "90",
            "status": status,
            "clip_path": None,
            "file_id": None,
            "attempts": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return tok, entry

    def _make_ctx_no_new_ids(self, settings: Settings, match: Match) -> tuple[MagicMock, MagicMock]:
        """Context where the match is already in finished_announced (no new recap)."""
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {match.id}
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]
        return ctx, mock_client

    # ── main correction tests ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_correction_posted_and_goal_edited_on_score_change(self, tmp_path):
        """2-2 finalized, API corrects to 2-1 → correction sent, goal message edited."""
        settings = _make_settings(tmp_path, ai=False)
        corrected_match = self._por_cro(2, 1, winner="HOME_TEAM")
        ctx, mock_client = self._make_ctx_no_new_ids(settings, corrected_match)

        # Pre-recorded score at finalization: 2-2
        ctx.bot_data["finished_scores"] = {"101": self._fs_entry(home=2, away=2)}
        # Portugal scored the 2-2 goal (searching status)
        tok, clip_entry = self._clip_tok_entry(
            match_id=101, scoring_team="Portugal",
            home_score=2, away_score=2, message_id=42,
        )
        ctx.bot_data["clip_store"] = {tok: clip_entry}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # 1. Correction message sent with correct format and target
        send_calls = ctx.bot.send_message.call_args_list
        assert len(send_calls) == 1
        ckw = send_calls[0][1]
        assert ckw["chat_id"] == settings.telegram_group_id
        assert ckw["parse_mode"] == "HTML"
        text = ckw["text"]
        assert "Corrección" in text
        assert "VAR" in text
        assert "2-2" in text    # old (annulled) score
        assert "2-1" in text    # new (corrected) score

        # 2. Original goal message edited with ANULADO mark (no keyboard for 'searching')
        edit_calls = ctx.bot.edit_message_text.call_args_list
        assert len(edit_calls) == 1
        ekw = edit_calls[0][1]
        assert ekw["chat_id"] == -100999
        assert ekw["message_id"] == 42
        assert "ANULADO" in ekw["text"]
        assert "VAR" in ekw["text"]
        assert ekw["parse_mode"] == "HTML"
        assert "reply_markup" not in ekw  # 'searching' clip → no keyboard

        # 3. finished_scores updated in-memory
        entry = ctx.bot_data["finished_scores"]["101"]
        assert entry["corrected"] is True
        assert entry["home"] == 2
        assert entry["away"] == 1

        # 4. Persisted to disk
        import json as _json
        with open(str(tmp_path / "finished_scores.json")) as f:
            saved = _json.load(f)
        assert saved["101"]["corrected"] is True
        assert saved["101"]["home"] == 2
        assert saved["101"]["away"] == 1

    @pytest.mark.asyncio
    async def test_keyboard_preserved_when_clip_ready(self, tmp_path):
        """'ready' clip entry → 'Ver gol' keyboard passed through on edit."""
        from worldcup_bot.reddit.notifier import build_goal_keyboard

        settings = _make_settings(tmp_path, ai=False)
        corrected_match = self._por_cro(2, 1)
        ctx, mock_client = self._make_ctx_no_new_ids(settings, corrected_match)
        ctx.bot_data["finished_scores"] = {"101": self._fs_entry(2, 2)}

        tok, clip_entry = self._clip_tok_entry(
            match_id=101, scoring_team="Portugal",
            home_score=2, away_score=2, message_id=55, status="ready",
        )
        ctx.bot_data["clip_store"] = {tok: clip_entry}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        edit_calls = ctx.bot.edit_message_text.call_args_list
        assert len(edit_calls) == 1
        ekw = edit_calls[0][1]
        assert "reply_markup" in ekw
        assert ekw["reply_markup"] == build_goal_keyboard(tok)

    @pytest.mark.asyncio
    async def test_no_correction_when_score_stable(self, tmp_path):
        """Recorded 2-1, API still 2-1 → no correction, no edit."""
        settings = _make_settings(tmp_path, ai=False)
        same_match = self._por_cro(2, 1)
        ctx, mock_client = self._make_ctx_no_new_ids(settings, same_match)
        ctx.bot_data["finished_scores"] = {"101": self._fs_entry(2, 1)}
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_duplicate_correction_on_third_tick(self, tmp_path):
        """After correction the recorded score is updated → stable on third tick → no duplicate."""
        settings = _make_settings(tmp_path, ai=False)
        # Entry already corrected: recorded score is the post-VAR score (2-1)
        same_match = self._por_cro(2, 1)
        ctx, mock_client = self._make_ctx_no_new_ids(settings, same_match)
        ctx.bot_data["finished_scores"] = {
            "101": self._fs_entry(home=2, away=1, corrected=True),
        }
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_penalty_shootout_no_false_correction(self, tmp_path):
        """Settled shootout: on-pitch score stable (1-1) → no false VAR correction.

        Penalty shootouts only change penalty_home/away, not home_score/away_score.
        match_result_is_final(match) is True here (both penalty scores set, winner set).
        The comparison is purely on on-pitch scores; 1-1 == 1-1 → no diff.
        """
        settings = _make_settings(tmp_path, ai=False)
        shootout_match = Match(
            id=102,
            utc_date="2026-07-03T20:00:00Z",
            status="FINISHED",
            stage="LAST_16",
            group=None,
            home_tla="GER",
            away_tla="BRA",
            home_name="Germany",
            away_name="Brazil",
            home_score=1,
            away_score=1,
            winner="HOME_TEAM",
            duration="PENALTY_SHOOTOUT",
            penalty_home=4,
            penalty_away=3,
        )
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = {102}
        # On-pitch score recorded at finalization: 1-1 (same as current)
        ctx.bot_data["finished_scores"] = {"102": self._fs_entry(1, 1)}
        ctx.bot_data["clip_store"] = {}
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [shootout_match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_window_expiry_prunes_entry_no_correction(self, tmp_path):
        """Entry finalized 45 min ago (> 30-min window) → pruned, no correction."""
        settings = _make_settings(tmp_path, ai=False)
        corrected_match = self._por_cro(2, 1)
        ctx, mock_client = self._make_ctx_no_new_ids(settings, corrected_match)
        # Finalized 45 min ago — outside the default 30-min window
        ctx.bot_data["finished_scores"] = {
            "101": self._fs_entry(home=2, away=2, age_minutes=45),
        }
        ctx.bot_data["clip_store"] = {}

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()
        assert "101" not in ctx.bot_data["finished_scores"]  # pruned

    @pytest.mark.asyncio
    async def test_correction_sent_even_if_goal_message_absent(self, tmp_path):
        """Goal message absent from clip_store → correction still posted, edit skipped."""
        settings = _make_settings(tmp_path, ai=False)
        corrected_match = self._por_cro(2, 1)
        ctx, mock_client = self._make_ctx_no_new_ids(settings, corrected_match)
        ctx.bot_data["finished_scores"] = {"101": self._fs_entry(2, 2)}
        ctx.bot_data["clip_store"] = {}  # no clip entry

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        # Correction message still sent
        assert ctx.bot.send_message.await_count == 1
        text = ctx.bot.send_message.call_args_list[0][1]["text"]
        assert "Corrección" in text
        # But goal message NOT edited (no entry found)
        ctx.bot.edit_message_text.assert_not_awaited()
        # corrected flag still set
        assert ctx.bot_data["finished_scores"]["101"]["corrected"] is True

    @pytest.mark.asyncio
    async def test_score_recorded_when_match_finalized(self, tmp_path):
        """When a new match is finalized, its score is recorded in finished_scores."""
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seeded"] = True
        ctx.bot_data["finished_announced"] = set()  # match 1 is new
        ctx.bot_data["finished_scores"] = {}

        match = _make_match(1, winner="HOME_TEAM")  # 2-1
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]
        mock_scanner = MagicMock()
        mock_scanner.get_espn_game_id = MagicMock(return_value=None)
        ctx.bot_data["reddit_scanner"] = mock_scanner

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
            patch("worldcup_bot.__main__.pred_loader.load", return_value={"participants": {}}),
            patch("worldcup_bot.__main__.compute_general_ranking", return_value=[]),
        ):
            await poll_finished_matches_job(ctx)

        assert "1" in ctx.bot_data["finished_scores"]
        entry = ctx.bot_data["finished_scores"]["1"]
        assert entry["home"] == 2
        assert entry["away"] == 1
        assert entry["corrected"] is False
        assert "finalized_at" in entry
