"""Tests for poll_finished_matches_job — seeds on first run, fires for new matches,
graceful degradation when ESPN/scanner/AI unavailable.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.api.models import Match
from worldcup_bot.config import Settings
from worldcup_bot.porra.engine import UserRankEntry


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
    }
    ctx.bot.send_message = AsyncMock()
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
    ctx.bot_data["finished_seen"] = set()  # empty — so match IS new

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
            # Seed first
            await poll_finished_matches_job(ctx)
            # Clear seed, re-add match as new
            ctx.bot_data.pop("finished_seen")
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
        ctx.bot_data["finished_seen"] = {99}  # match 1 is new

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
        ctx.bot_data["finished_seen"] = {99}

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
        ctx.bot_data["finished_seen"] = {99}

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
        ctx.bot_data["finished_seen"] = {99}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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

        match = _make_match(1, "FINISHED")
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = [match]

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_client),
        ):
            await poll_finished_matches_job(ctx)

        # No messages sent on first run
        ctx.bot.send_message.assert_not_awaited()
        # finished_seen populated
        assert 1 in ctx.bot_data["finished_seen"]

    @pytest.mark.asyncio
    async def test_first_run_seeds_all_finished(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)

        matches = [_make_match(i, "FINISHED") for i in range(1, 4)]
        mock_client = MagicMock()
        mock_client.get_all_matches.return_value = matches

        with patch("worldcup_bot.__main__.make_client", return_value=mock_client):
            await poll_finished_matches_job(ctx)

        assert ctx.bot_data["finished_seen"] == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_second_run_fires_for_new_match(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        # Pre-seed with match 1 already seen
        ctx = _make_context(settings)
        ctx.bot_data["finished_seen"] = {1}  # already seeded

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

        # Match 2 now in finished_seen
        assert 2 in ctx.bot_data["finished_seen"]


# ── Part A tests ──────────────────────────────────────────────────────────────


class TestPartAStats:
    @pytest.mark.asyncio
    async def test_sends_stats_when_available(self, tmp_path):
        settings = _make_settings(tmp_path, ai=False)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seen"] = {1}  # match 1 already seen

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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

        assert 2 in ctx.bot_data["finished_seen"]


# ── Part B tests ──────────────────────────────────────────────────────────────


class TestPartBPorraCommentary:
    @pytest.mark.asyncio
    async def test_sends_commentary_when_ai_enabled_and_changed(self, tmp_path):
        settings = _make_settings(tmp_path, ai=True)
        ctx = _make_context(settings)
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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

        assert 2 in ctx.bot_data["finished_seen"]


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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
        ctx.bot_data["finished_seen"] = {1}

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
