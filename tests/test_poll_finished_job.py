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
        winner="HOME_TEAM",
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


# ── seeding tests ─────────────────────────────────────────────────────────────


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
    async def test_no_send_when_game_id_none(self, tmp_path):
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

        # No stats send
        for call in ctx.bot.send_message.call_args_list:
            text = call[1].get("text", "")
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
    """Tests for the ONE combined message (stats + ---- + commentary) contract."""

    def _make_fake_stats(self) -> dict:
        return {
            "home": {"name": "Spain", "stats": {"possessionPct": "60"}},
            "away": {"name": "France", "stats": {"possessionPct": "40"}},
        }

    @pytest.mark.asyncio
    async def test_combined_message_with_separator_when_both_parts_present(self, tmp_path):
        """When BOTH stats and commentary are available, ONE message with '----' separator."""
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
        assert "----" in text
        # Both parts must be present
        assert "📊" in text or "Estadísticas" in text
        assert "¡Qué partidazo!" in text
        # Persona name must NOT appear
        assert "Andrés Montes" not in text
        assert "🎙️" not in text

    @pytest.mark.asyncio
    async def test_only_stats_when_no_porra_change(self, tmp_path):
        """When no porra change (live_diff.changed=False), only stats are sent (no separator)."""
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
        ):
            await poll_finished_matches_job(ctx)

        calls = ctx.bot.send_message.call_args_list
        assert len(calls) == 1
        text = calls[0][1]["text"]
        assert "----" not in text
        assert "📊" in text or "Estadísticas" in text

    @pytest.mark.asyncio
    async def test_only_commentary_when_no_stats(self, tmp_path):
        """When ESPN returns no stats but AI generates commentary, send ONLY commentary."""
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
        assert "----" not in text
        assert "¡La porra arde!" in text
        assert "Julio Maldini" not in text
        assert "🎙️" not in text

    @pytest.mark.asyncio
    async def test_no_send_when_neither_stats_nor_commentary(self, tmp_path):
        """When both ESPN and porra produce nothing, NO message is sent."""
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

        ctx.bot.send_message.assert_not_awaited()

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
