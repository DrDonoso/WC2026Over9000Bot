"""Lightweight integration tests for Telegram command handlers.

All external dependencies (engine, predictions loader, API client) are mocked
so no network calls or real files are needed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.bot.handlers import (
    _MSG_NO_USERNAME,
    _MSG_USER_NOT_FOUND,
    _goal_token,
    _pick_random_goal,
    _send_ranking_with_top3_photos,
    cmd_actual,
    cmd_clasificacion,
    cmd_endirecto_callback,
    cmd_endirecto_goal_callback,
    cmd_en_directo,
    cmd_estadisticas,
    cmd_general,
    cmd_hoy,
    cmd_lista_aciertos,
    cmd_lista_aciertos_actual,
    cmd_mis_predicciones,
    cmd_participantes,
    cmd_simula_gol,
    cmd_start,
    cmd_tongo,
    cmd_ver_gol_callback,
)
from worldcup_bot.api.client import FootballAPIError
from worldcup_bot.api.models import Match, Standing
from worldcup_bot.bot.formatters import format_user_detail, participant_photo_url
from worldcup_bot.config import Settings
from worldcup_bot.data.tongo import TongoConfig, TongoConfigError
from worldcup_bot.porra.engine import UserRankEntry


# ── fake data ──────────────────────────────────────────────────────────────────

_FAKE_DETAIL = {
    "username": "testuser",
    "display_name": "Test User",
    "base_score": 0.0,
    "group_score": 3.0,
    "knockout_score": 1.0,
    "total_score": 4.0,
    "group_detail": [],
    "knockout_detail": [],
    "official": False,
    "finished_groups": None,
    "started_groups": 12,
    "total_groups": 12,
}

_FAKE_DETAIL_OFFICIAL = {
    "username": "testuser",
    "display_name": "Test User",
    "base_score": 0.0,
    "group_score": 3.0,
    "knockout_score": 0.0,
    "total_score": 3.0,
    "group_detail": [],
    "knockout_detail": [],
    "official": True,
    "finished_groups": 1,
    "started_groups": None,
    "total_groups": 12,
}

_FAKE_PREDICTIONS = {
    "participants": {
        "testuser": {
            "display_name": "Test User",
            "base_score": 0.0,
            "groups": {
                "A": ["GER", "ESP", "BRA"],
                "B": ["FRA", "ARG", "ENG"],
                "C": ["POR", "NED", "URU"],
                "D": ["BEL", "CRO", "ITA"],
                "E": ["COL", "MEX", "DEN"],
                "F": ["USA", "POL", "AUT"],
                "G": ["TUR", "MAR", "SUI"],
                "H": ["ECU", "NGA", "CHI"],
                "I": ["JPN", "KOR", "CIV"],
                "J": ["VEN", "PAR", "CAN"],
                "K": ["EGY", "ALG", "AUS"],
                "L": ["PER", "GHA", "SRB"],
            },
            "knockout": {
                "round_of_32": ["ESP", "FRA", "ARG", "BRA", "GER", "ENG", "POR", "NED",
                                 "COL", "MEX", "USA", "JPN", "MAR", "BEL", "CRO", "ITA"],
                "round_of_16": ["ESP", "FRA", "ARG", "BRA", "GER", "ENG", "POR", "NED"],
                "quarter_finals": ["ESP", "FRA", "ARG", "BRA"],
                "semi_finals": ["ESP", "FRA"],
                "final": ["ESP"],
            },
        }
    }
}

_EMPTY_PREDICTIONS = {"participants": {}}


# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_update(username: str | None = "testuser") -> MagicMock:
    """Create a minimal fake Update object."""
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    if username:
        update.effective_user.username = username
    else:
        update.effective_user.username = None
    return update


def _make_context(settings: Settings, args: list[str] | None = None) -> MagicMock:
    """Create a minimal fake Context object."""
    context = MagicMock()
    context.bot_data = {"settings": settings}
    context.args = args or []
    context.bot.send_photo = AsyncMock()
    context.bot.send_media_group = AsyncMock()
    context.bot.send_animation = AsyncMock()
    return context


@pytest.fixture
def fake_settings():
    return Settings(
        telegram_bot_token="fake-token",
        football_data_api_key="fake-api-key",
        predictions_path="fake_predictions.yml",
    )


# ══════════════════════════════════════════════════════════════════════════════
# cmd_start
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdStart:
    async def test_sends_help_text(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "/porra" in text
        assert "/listaaciertos" in text
        assert "/general" in text

    async def test_mentions_mispredicciones_command(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "/mispredicciones" in text

    async def test_does_not_mention_simulagol(self, fake_settings):
        """/start help must NOT expose /simulagol (hidden test command)."""
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "simulagol" not in text

    async def test_mentions_tongo_and_hoy(self, fake_settings):
        """/start help still lists /tongo and /hoy."""
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "/tongo" in text
        assert "/hoy" in text


# ══════════════════════════════════════════════════════════════════════════════
# cmd_lista_aciertos
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdListaAciertos:
    async def test_no_username_sends_no_username_message(self, fake_settings):
        """When the caller has no @username, _MSG_NO_USERNAME is sent."""
        update = _make_update(username=None)
        context = _make_context(fake_settings, args=[])

        await cmd_lista_aciertos(update, context)

        update.message.reply_text.assert_called_once_with(_MSG_NO_USERNAME)

    async def test_no_username_none_effective_user(self, fake_settings):
        """Works even if effective_user is None."""
        update = _make_update()
        update.effective_user = None
        context = _make_context(fake_settings, args=[])

        await cmd_lista_aciertos(update, context)

        update.message.reply_text.assert_called_once_with(_MSG_NO_USERNAME)

    async def test_no_arg_uses_caller_username_lowercased(self, fake_settings):
        """No arg → caller's username is lowercased for the lookup."""
        update = _make_update(username="MixedCase")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_lista_aciertos(update, context)

        # User not found → error message must include lowercased "@mixedcase"
        text = update.message.reply_text.call_args[0][0]
        assert "@mixedcase" in text
        assert "MixedCase" not in text  # original case must NOT appear

    async def test_no_arg_caller_found_reply_sent(self, fake_settings):
        """No arg, caller found in predictions → engine called, reply sent."""
        update = _make_update(username="testuser")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail", return_value=_FAKE_DETAIL):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos(update, context)

        update.message.reply_text.assert_called_once()

    async def test_no_arg_caller_found_engine_receives_lowercased_username(self, fake_settings):
        """Engine is called with the lowercased caller username."""
        update = _make_update(username="TestUser")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail",
                       return_value=_FAKE_DETAIL) as mock_engine:
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos(update, context)

        # First positional arg must be the lowercased username
        called_username = mock_engine.call_args[0][0]
        assert called_username == "testuser"

    async def test_user_not_found_sends_not_found_message(self, fake_settings):
        """User not in predictions → _MSG_USER_NOT_FOUND sent."""
        update = _make_update(username="nobody")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_lista_aciertos(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "nobody" in text.lower() or "No encontré" in text

    async def test_arg_at_prefix_stripped(self, fake_settings):
        """@user arg → '@' is stripped before lookup."""
        update = _make_update(username="admin")
        context = _make_context(fake_settings, args=["@testuser"])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail",
                       return_value=_FAKE_DETAIL):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos(update, context)

        update.message.reply_text.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_mis_predicciones
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdMisPredicciones:
    async def test_no_username_sends_no_username_message(self, fake_settings):
        update = _make_update(username=None)
        context = _make_context(fake_settings)

        await cmd_mis_predicciones(update, context)

        update.message.reply_text.assert_called_once_with(_MSG_NO_USERNAME)

    async def test_caller_identity_lowercased(self, fake_settings):
        """Caller's username is lowercased when used for lookup."""
        update = _make_update(username="UPPERUSER")
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_mis_predicciones(update, context)

        text = update.message.reply_text.call_args[0][0]
        # Error message mentions lowercase "@upperuser"
        assert "upperuser" in text.lower()

    async def test_caller_found_reply_contains_display_name(self, fake_settings):
        """When caller is found, their display_name appears in the reply."""
        update = _make_update(username="testuser")
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_mis_predicciones(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Test User" in text

    async def test_caller_not_in_predictions_sends_informative_message(self, fake_settings):
        """When caller not in predictions, an informative message is sent (not a crash)."""
        update = _make_update(username="ghost")
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_mis_predicciones(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "ghost" in text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_participantes
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdParticipantes:
    async def test_empty_predictions_sends_no_participants_message(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_EMPTY_PREDICTIONS):
            await cmd_participantes(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "predicciones" in text.lower()
        assert "fake_predictions.yml" in text

    async def test_participants_listed(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_participantes(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "testuser" in text

    async def test_display_name_shown_when_available(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_participantes(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Test User" in text


# ══════════════════════════════════════════════════════════════════════════════
# build_app — command registrations
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildAppRegistrations:
    def test_actual_porra_general_all_registered(self, fake_settings):
        """/actual, /porra, and /general are all registered in the app."""
        from worldcup_bot.__main__ import build_app

        app = build_app(fake_settings)

        commands: set[str] = set()
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if hasattr(h, "commands"):
                    commands.update(h.commands)

        assert "actual" in commands
        assert "porra" in commands
        assert "general" in commands

    async def test_start_help_text_contains_actual_and_general(self, fake_settings):
        """cmd_start help text lists /actual, /general, and /porra (alias)."""
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "/actual" in text
        assert "/general" in text
        assert "/porra" in text
        assert "alias" in text.lower()

    def test_listaaciertos_and_listaaciertosactual_both_registered(self, fake_settings):
        """/listaaciertos (official) and /listaaciertosactual (provisional) are both registered."""
        from worldcup_bot.__main__ import build_app

        app = build_app(fake_settings)

        commands: set[str] = set()
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if hasattr(h, "commands"):
                    commands.update(h.commands)

        assert "listaaciertos" in commands
        assert "listaaciertosactual" in commands

    def test_endirecto_callback_registered(self, fake_settings):
        r"""A CallbackQueryHandler with pattern ^ed\| must be registered in build_app."""
        from telegram.ext import CallbackQueryHandler
        from worldcup_bot.__main__ import build_app

        app = build_app(fake_settings)
        patterns = []
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if isinstance(h, CallbackQueryHandler):
                    patterns.append(getattr(h, "pattern", None))
        pattern_strs = [str(p.pattern) if hasattr(p, "pattern") else str(p) for p in patterns]
        assert any("ed" in s and "|" in s for s in pattern_strs)

    def test_build_app_applies_beloved_teams_from_settings(self, monkeypatch):
        """build_app must call formatters.set_beloved_teams with settings.beloved_teams."""
        from worldcup_bot.__main__ import build_app
        from worldcup_bot.bot import formatters

        calls = []
        monkeypatch.setattr(formatters, "set_beloved_teams", lambda tlas: calls.append(tuple(tlas)))

        custom = Settings(
            telegram_bot_token="fake-token",
            football_data_api_key="fake-api-key",
            beloved_teams=("CUW", "PAN"),
        )
        build_app(custom)

        assert len(calls) == 1
        assert set(calls[0]) == {"CUW", "PAN"}


# ══════════════════════════════════════════════════════════════════════════════
# cmd_clasificacion — group standings with optional letter filter
# ══════════════════════════════════════════════════════════════════════════════

_FAKE_STANDINGS = [
    Standing(group="GROUP_A", position=1, tla="GER", team_name="Germany", points=9, played=3),
    Standing(group="GROUP_A", position=2, tla="ESP", team_name="Spain", points=6, played=3),
    Standing(group="GROUP_A", position=3, tla="BRA", team_name="Brazil", points=3, played=3),
    Standing(group="GROUP_A", position=4, tla="USA", team_name="USA", points=0, played=3),
    Standing(group="GROUP_L", position=1, tla="PER", team_name="Peru", points=6, played=3),
    Standing(group="GROUP_L", position=2, tla="GHA", team_name="Ghana", points=3, played=3),
    Standing(group="GROUP_L", position=3, tla="SRB", team_name="Serbia", points=1, played=3),
    Standing(group="GROUP_L", position=4, tla="NZL", team_name="New Zealand", points=0, played=3),
]


class TestCmdClasificacion:
    async def test_no_arg_returns_all_groups(self, fake_settings):
        """No argument → format_standings receives full standings, output has multiple groups."""
        update = _make_update()
        context = _make_context(fake_settings, args=[])

        mock_client = MagicMock()
        mock_client.get_standings.return_value = _FAKE_STANDINGS
        mock_client.get_live_matches.return_value = []

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            await cmd_clasificacion(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Grupo A" in text
        assert "Grupo L" in text

    async def test_letter_uppercase_filters_to_single_group(self, fake_settings):
        """/clasificacion L → only Group L standings returned."""
        update = _make_update()
        context = _make_context(fake_settings, args=["L"])

        mock_client = MagicMock()
        mock_client.get_standings.return_value = _FAKE_STANDINGS
        mock_client.get_live_matches.return_value = []

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            await cmd_clasificacion(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Grupo L" in text
        assert "Grupo A" not in text

    async def test_letter_lowercase_filters_to_single_group(self, fake_settings):
        """/clasificacion l (lowercase) is treated the same as /clasificacion L."""
        update = _make_update()
        context = _make_context(fake_settings, args=["l"])

        mock_client = MagicMock()
        mock_client.get_standings.return_value = _FAKE_STANDINGS
        mock_client.get_live_matches.return_value = []

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            await cmd_clasificacion(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Grupo L" in text
        assert "Grupo A" not in text

    async def test_invalid_arg_sends_friendly_error(self, fake_settings):
        """/clasificacion Z or /clasificacion foo → friendly error, no crash."""
        for bad_arg in (["Z"], ["foo"], ["12"]):
            update = _make_update()
            context = _make_context(fake_settings, args=bad_arg)

            mock_client = MagicMock()

            with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
                await cmd_clasificacion(update, context)

            text = update.message.reply_text.call_args[0][0]
            assert "Grupo no válido" in text
            assert "/clasificacion L" in text
            mock_client.get_standings.assert_not_called()

    async def test_requested_group_empty_sends_not_available_message(self, fake_settings):
        """If the requested group has no standings data, a 'not available yet' message is sent."""
        update = _make_update()
        context = _make_context(fake_settings, args=["K"])

        # Standings only have GROUP_A and GROUP_L — GROUP_K is absent
        mock_client = MagicMock()
        mock_client.get_standings.return_value = _FAKE_STANDINGS
        mock_client.get_live_matches.return_value = []

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            await cmd_clasificacion(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Grupo K" in text
        assert "todavía" in text


# ══════════════════════════════════════════════════════════════════════════════
# cmd_lista_aciertos — official mode
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdListaAciertosOfficial:
    async def test_calls_engine_with_official_true(self, fake_settings):
        """cmd_lista_aciertos always passes official=True to the engine."""
        update = _make_update(username="testuser")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail",
                       return_value=_FAKE_DETAIL_OFFICIAL) as mock_engine:
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos(update, context)

        _, kwargs = mock_engine.call_args
        assert kwargs.get("official") is True

    async def test_start_help_mentions_listaaciertos_and_listaaciertosactual(self, fake_settings):
        """cmd_start help text lists both /listaaciertos and /listaaciertosactual."""
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "/listaaciertos" in text
        assert "/listaaciertosactual" in text


# ══════════════════════════════════════════════════════════════════════════════
# cmd_lista_aciertos_actual — provisional mode
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdListaAciertosActual:
    async def test_no_username_sends_no_username_message(self, fake_settings):
        update = _make_update(username=None)
        context = _make_context(fake_settings, args=[])

        await cmd_lista_aciertos_actual(update, context)

        update.message.reply_text.assert_called_once_with(_MSG_NO_USERNAME)

    async def test_no_arg_caller_found_reply_sent(self, fake_settings):
        update = _make_update(username="testuser")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail", return_value=_FAKE_DETAIL):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos_actual(update, context)

        update.message.reply_text.assert_called_once()

    async def test_calls_engine_with_official_false(self, fake_settings):
        """cmd_lista_aciertos_actual always passes official=False to the engine."""
        update = _make_update(username="testuser")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail",
                       return_value=_FAKE_DETAIL) as mock_engine:
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos_actual(update, context)

        _, kwargs = mock_engine.call_args
        assert kwargs.get("official") is False

    async def test_user_not_found_sends_not_found_message(self, fake_settings):
        update = _make_update(username="nobody")
        context = _make_context(fake_settings, args=[])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            await cmd_lista_aciertos_actual(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "nobody" in text.lower() or "No encontré" in text

    async def test_arg_at_prefix_stripped(self, fake_settings):
        update = _make_update(username="admin")
        context = _make_context(fake_settings, args=["@testuser"])

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_user_detail",
                       return_value=_FAKE_DETAIL):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    await cmd_lista_aciertos_actual(update, context)

        update.message.reply_text.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# participant_photo_url helper
# ══════════════════════════════════════════════════════════════════════════════


class TestParticipantPhotoUrl:
    def test_builds_correct_url(self):
        url = participant_photo_url("crispavon", "http://victorsaez.cat")
        assert url == "http://victorsaez.cat/crispavon.png"

    def test_strips_trailing_slash_from_base(self):
        url = participant_photo_url("crispavon", "http://victorsaez.cat/")
        assert url == "http://victorsaez.cat/crispavon.png"

    def test_custom_base_url(self):
        url = participant_photo_url("dsantosmerino", "http://example.com/photos")
        assert url == "http://example.com/photos/dsantosmerino.png"

    def test_username_lowercased_is_caller_responsibility(self):
        """participant_photo_url uses the username verbatim — callers pass lowercase."""
        url = participant_photo_url("pilarfreixas", "http://victorsaez.cat")
        assert url == "http://victorsaez.cat/pilarfreixas.png"


# ── shared fake rank rows ─────────────────────────────────────────────────────

def _make_row(username: str, display_name: str, score: float) -> UserRankEntry:
    return UserRankEntry(
        username=username,
        display_name=display_name,
        total_score=score,
        base_score=0.0,
        group_score=score,
        knockout_scores={},
        exact_group_hits=0,
    )


_TOP5_ROWS = [
    _make_row("crispavon",      "Cris",   10.0),
    _make_row("dsantosmerino",  "David",   8.0),
    _make_row("pilarfreixas",   "Pilar",   6.0),
    _make_row("josepmolina",    "Josep",   4.0),
    _make_row("annabernal",     "Anna",    2.0),
]

_TWO_ROWS = [
    _make_row("crispavon",     "Cris",  10.0),
    _make_row("dsantosmerino", "David",  8.0),
]

_ONE_ROW = [_make_row("crispavon", "Cris", 10.0)]


def _mock_requests_all_valid():
    """Return a mock for requests.get that always reports HTTP 200 image/png."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/png"}
    mock_resp.close = MagicMock()
    return mock_resp


def _mock_requests_all_invalid():
    """Return a mock for requests.get that always reports HTTP 404."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.close = MagicMock()
    return mock_resp


# ══════════════════════════════════════════════════════════════════════════════
# _send_ranking_with_top3_photos
# ══════════════════════════════════════════════════════════════════════════════


class TestSendRankingWithTop3Photos:
    async def test_send_media_group_called_with_top3(self, fake_settings):
        """With 5 rows and all URLs valid, send_media_group is called with exactly 3 items."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "ranking text", _TOP5_ROWS, fake_settings)

        context.bot.send_media_group.assert_called_once()
        _, kwargs = context.bot.send_media_group.call_args
        media = kwargs["media"]
        assert len(media) == 3
        assert media[0].media == "http://victorsaez.cat/crispavon.png"
        assert media[1].media == "http://victorsaez.cat/dsantosmerino.png"
        assert media[2].media == "http://victorsaez.cat/pilarfreixas.png"

    async def test_first_media_item_has_caption(self, fake_settings):
        """The first InputMediaPhoto carries the ranking text as caption."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "my caption", _TOP5_ROWS, fake_settings)

        _, kwargs = context.bot.send_media_group.call_args
        media = kwargs["media"]
        assert media[0].caption == "my caption"
        assert media[1].caption is None
        assert media[2].caption is None

    async def test_fallback_to_text_when_no_valid_urls(self, fake_settings):
        """When all URL checks fail, reply_text is called with the ranking text."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_invalid()):
            await _send_ranking_with_top3_photos(update, context, "fallback text", _TOP5_ROWS, fake_settings)

        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once_with("fallback text", parse_mode="HTML")

    async def test_fallback_when_requests_raises(self, fake_settings):
        """Network error during URL validation → skip that URL gracefully."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", side_effect=OSError("network error")):
            await _send_ranking_with_top3_photos(update, context, "fallback text", _TOP5_ROWS, fake_settings)

        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once_with("fallback text", parse_mode="HTML")

    async def test_fallback_when_send_media_group_raises(self, fake_settings):
        """If send_media_group itself raises, reply_text is used instead."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot.send_media_group = AsyncMock(side_effect=Exception("Telegram error"))

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "fallback text", _TOP5_ROWS, fake_settings)

        update.message.reply_text.assert_called_once_with("fallback text", parse_mode="HTML")

    async def test_empty_rows_sends_text_only(self, fake_settings):
        """Empty rows → reply_text called immediately, no URL checks."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get") as mock_get:
            await _send_ranking_with_top3_photos(update, context, "no data", [], fake_settings)

        mock_get.assert_not_called()
        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once_with("no data", parse_mode="HTML")

    async def test_fewer_than_3_rows_sends_what_exists(self, fake_settings):
        """With only 2 rows, album has 2 items (not 3)."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "text", _TWO_ROWS, fake_settings)

        _, kwargs = context.bot.send_media_group.call_args
        assert len(kwargs["media"]) == 2

    async def test_one_row_sends_single_item_album(self, fake_settings):
        """With only 1 row, album has 1 item."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "text", _ONE_ROW, fake_settings)

        _, kwargs = context.bot.send_media_group.call_args
        assert len(kwargs["media"]) == 1

    async def test_caption_truncated_at_1024_chars(self, fake_settings):
        """Caption longer than 1024 chars is truncated; full text sent as follow-up."""
        update = _make_update()
        context = _make_context(fake_settings)
        long_text = "x" * 2000

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, long_text, _ONE_ROW, fake_settings)

        _, kwargs = context.bot.send_media_group.call_args
        assert len(kwargs["media"][0].caption) == 1024
        # Full text sent as follow-up with HTML parse_mode
        update.message.reply_text.assert_called_once_with(long_text, parse_mode="HTML")

    async def test_uses_custom_photo_base_url(self, fake_settings):
        """photo_base_url from settings is used to build URLs."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            photo_base_url="http://custom.example.com",
        )
        update = _make_update()
        context = _make_context(settings)

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "text", _ONE_ROW, settings)

        _, kwargs = context.bot.send_media_group.call_args
        assert kwargs["media"][0].media == "http://custom.example.com/crispavon.png"


# ══════════════════════════════════════════════════════════════════════════════
# cmd_actual
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdActual:
    async def test_no_predictions_sends_error(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_EMPTY_PREDICTIONS):
            await cmd_actual(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "predicciones" in text.lower()

    async def test_sends_album_when_urls_valid(self, fake_settings):
        """cmd_actual calls send_media_group when top-3 URLs are reachable."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
                        await cmd_actual(update, context)

        context.bot.send_media_group.assert_called_once()
        _, kwargs = context.bot.send_media_group.call_args
        assert len(kwargs["media"]) == 3

    async def test_falls_back_to_text_when_no_valid_urls(self, fake_settings):
        """cmd_actual falls back to reply_text when no images are reachable."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_invalid()):
                        await cmd_actual(update, context)

        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "Clasificación provisional" in text

    async def test_caption_contains_provisional_title(self, fake_settings):
        """cmd_actual caption contains the provisional title."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
                        await cmd_actual(update, context)

        _, kwargs = context.bot.send_media_group.call_args
        caption = kwargs["media"][0].caption
        assert "provisional" in caption.lower()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_general
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdGeneral:
    async def test_no_predictions_sends_error(self, fake_settings):
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_EMPTY_PREDICTIONS):
            await cmd_general(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "predicciones" in text.lower()

    async def test_sends_album_when_urls_valid(self, fake_settings):
        """cmd_general calls send_media_group with 3 items when top-3 URLs are reachable."""
        update = _make_update()
        context = _make_context(fake_settings)

        mock_client = MagicMock()
        mock_client.get_finished_groups.return_value = set()

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
                    with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
                        await cmd_general(update, context)

        context.bot.send_media_group.assert_called_once()
        _, kwargs = context.bot.send_media_group.call_args
        assert len(kwargs["media"]) == 3

    async def test_caption_includes_footer(self, fake_settings):
        """cmd_general caption includes the 'Grupos cerrados: N/12' footer."""
        update = _make_update()
        context = _make_context(fake_settings)

        mock_client = MagicMock()
        mock_client.get_finished_groups.return_value = {"GROUP_A", "GROUP_B"}

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
                    with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
                        await cmd_general(update, context)

        _, kwargs = context.bot.send_media_group.call_args
        caption = kwargs["media"][0].caption
        assert "Grupos cerrados: 2/12" in caption

    async def test_fallback_text_includes_footer(self, fake_settings):
        """When URLs are all invalid, the fallback reply_text still includes the footer."""
        update = _make_update()
        context = _make_context(fake_settings)

        mock_client = MagicMock()
        mock_client.get_finished_groups.return_value = {"GROUP_A"}

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
                    with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_invalid()):
                        await cmd_general(update, context)

        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "Grupos cerrados: 1/12" in text


# ══════════════════════════════════════════════════════════════════════════════
# format_user_detail — provisional footer (started_groups)
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatUserDetailProvisionalFooter:
    def _base_detail(self, started: int, total: int = 12) -> dict:
        return {
            "username": "alice",
            "display_name": "Alice",
            "base_score": 0.0,
            "group_score": 1.0,
            "knockout_score": 0.0,
            "total_score": 1.0,
            "group_detail": [],
            "knockout_detail": [],
            "official": False,
            "finished_groups": None,
            "started_groups": started,
            "total_groups": total,
        }

    def test_grupos_en_juego_footer_shown_when_not_all_started(self):
        """Provisional with started_groups < total_groups shows the 'Grupos en juego' line."""
        detail = self._base_detail(started=4, total=12)
        text = format_user_detail(detail)
        assert "📋 Grupos en juego: 4/12" in text
        assert "los grupos sin empezar aún no puntúan" in text

    def test_grupos_en_juego_footer_not_shown_when_all_started(self):
        """Provisional with started_groups == total_groups does NOT show the 'Grupos en juego' line."""
        detail = self._base_detail(started=12, total=12)
        text = format_user_detail(detail)
        assert "Grupos en juego" not in text

    def test_grupos_en_juego_footer_not_shown_when_started_groups_none(self):
        """Provisional with started_groups=None (missing key) does not crash and no footer."""
        detail = self._base_detail(started=0)
        detail["started_groups"] = None
        text = format_user_detail(detail)
        assert "Grupos en juego" not in text

    def test_provisional_hint_always_present(self):
        """The base provisional hint line is always present regardless of started_groups."""
        for started in (0, 4, 12):
            detail = self._base_detail(started=started)
            text = format_user_detail(detail)
            assert "ℹ️ Provisional" in text

    def test_official_mode_does_not_show_grupos_en_juego_footer(self):
        """Official mode footer is unaffected by started_groups."""
        detail = {
            "username": "alice",
            "display_name": "Alice",
            "base_score": 0.0,
            "group_score": 1.0,
            "knockout_score": 0.0,
            "total_score": 1.0,
            "group_detail": [],
            "knockout_detail": [],
            "official": True,
            "finished_groups": 1,
            "started_groups": None,
            "total_groups": 12,
        }
        text = format_user_detail(detail)
        assert "Grupos en juego" not in text


# ══════════════════════════════════════════════════════════════════════════════
# format_user_detail — knockout section (acierto / fallo / pending)
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatUserDetailKnockout:
    def _detail(self) -> dict:
        return {
            "username": "alice",
            "display_name": "Alice",
            "base_score": 0.0,
            "group_score": 0.0,
            "knockout_score": 1.0,
            "total_score": 1.0,
            "group_detail": [],
            "knockout_detail": [
                {"stage": "LAST_32", "display": "Dieciseisavos de Final", "team": "CAN", "points": 1, "note": "acierto"},
                {"stage": "LAST_32", "display": "Dieciseisavos de Final", "team": "BRA", "points": 0, "note": "pending"},
                {"stage": "LAST_32", "display": "Dieciseisavos de Final", "team": "RSA", "points": 0, "note": "fallo"},
            ],
            "official": False,
            "finished_groups": None,
            "started_groups": 12,
            "total_groups": 12,
        }

    def test_section_header_and_total_present(self):
        text = format_user_detail(self._detail())
        assert "Fases eliminatorias" in text
        assert "Dieciseisavos de Final" in text
        assert "Total eliminatorias" in text

    def test_acierto_pending_and_fallo_icons_rendered(self):
        text = format_user_detail(self._detail())
        # CAN won → ✅, BRA not played yet → ⏳, RSA eliminated → ❌
        assert "✅" in next(l for l in text.splitlines() if "CAN" in l)
        assert "⏳" in next(l for l in text.splitlines() if "BRA" in l)
        assert "❌" in next(l for l in text.splitlines() if "RSA" in l)


# ══════════════════════════════════════════════════════════════════════════════
# cmd_ver_gol_callback
# ══════════════════════════════════════════════════════════════════════════════


def _make_callback_query(
    token: str,
    message_id: int = 42,
    chat_id: int = 99999,
) -> MagicMock:
    """Build a fake CallbackQuery-like object for 'Ver gol' tests."""
    query = MagicMock()
    query.data = f"vergol:{token}"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()
    query.message.message_id = message_id
    query.message.chat_id = chat_id
    return query


def _make_vergol_update(token: str, **kwargs) -> MagicMock:
    update = MagicMock()
    update.callback_query = _make_callback_query(token, **kwargs)
    return update


def _make_vergol_context(
    fake_settings: Settings,
    token: str,
    entry: dict | None,
) -> MagicMock:
    context = MagicMock()
    context.bot_data = {
        "settings": fake_settings,
        "clip_store": ({token: entry} if entry is not None else {}),
        "vergol_inflight": set(),
    }
    context.bot.send_message = AsyncMock()
    context.bot.send_video = AsyncMock()
    return context


def _sample_clip_entry(
    status: str = "ready",
    clip_path: str | None = "/app/state/clips/tok.mp4",
    file_id: str | None = None,
) -> dict:
    return {
        "chat_id": 99999,
        "message_id": 42,
        "home_name": "Sweden",
        "away_name": "Tunisia",
        "home_tla": "SWE",
        "away_tla": "TUN",
        "home_score": 3,
        "away_score": 1,
        "scoring_team": "Sweden",
        "scorer": "Viktor Gyökeres",
        "minute": "60",
        "status": status,
        "clip_path": clip_path,
        "file_id": file_id,
        "attempts": 3,
        "created_at": "2026-06-17T09:00:00+00:00",
    }


class TestGoalToken:
    def test_returns_12_hex_chars(self):
        tok = _goal_token("some:key:here")
        assert len(tok) == 12
        assert all(c in "0123456789abcdef" for c in tok)

    def test_stable(self):
        assert _goal_token("a:b") == _goal_token("a:b")

    def test_different_keys_differ(self):
        assert _goal_token("key1") != _goal_token("key2")


class TestCmdVerGolCallback:
    # ── unknown token ────────────────────────────────────────────────────────

    async def test_unknown_token_answers_alert_no_send(self, fake_settings):
        """Unknown token → query.answer with show_alert; no video sent."""
        token = "notpresent"
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry=None)

        await cmd_ver_gol_callback(update, context)

        update.callback_query.answer.assert_called_once()
        call_kwargs = update.callback_query.answer.call_args[1]
        assert call_kwargs.get("show_alert") is True
        context.bot.send_video.assert_not_called()
        context.bot.send_message.assert_not_called()

    # ── not-ready guard ──────────────────────────────────────────────────────

    async def test_searching_status_answers_not_ready(self, fake_settings):
        """Status 'searching' → answer 'aún no está listo'; no video sent."""
        token = "searchtok"
        entry = _sample_clip_entry(status="searching", clip_path=None)
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        await cmd_ver_gol_callback(update, context)

        update.callback_query.answer.assert_called_once()
        text = update.callback_query.answer.call_args[0][0]
        assert "listo" in text.lower()
        context.bot.send_video.assert_not_called()

    async def test_timeout_status_answers_not_ready(self, fake_settings):
        """Status 'timeout' → answer 'aún no está listo'; no video sent."""
        token = "timeouttok"
        entry = _sample_clip_entry(status="timeout", clip_path=None)
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        await cmd_ver_gol_callback(update, context)

        text = update.callback_query.answer.call_args[0][0]
        assert "listo" in text.lower()
        context.bot.send_video.assert_not_called()

    async def test_ready_no_clip_path_answers_not_ready(self, fake_settings):
        """Status 'ready' but clip_path None → answer 'aún no está listo'."""
        token = "noclipath"
        entry = _sample_clip_entry(status="ready", clip_path=None)
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        await cmd_ver_gol_callback(update, context)

        text = update.callback_query.answer.call_args[0][0]
        assert "listo" in text.lower()
        context.bot.send_video.assert_not_called()

    # ── in-flight guard ───────────────────────────────────────────────────────

    async def test_inflight_guard_answers_immediately_no_send(self, fake_settings, tmp_path):
        """Token pre-added to vergol_inflight → instant answer, no send."""
        token = "inflighttok"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)
        context.bot_data["vergol_inflight"].add(token)

        await cmd_ver_gol_callback(update, context)

        text = update.callback_query.answer.call_args[0][0]
        assert "enviando" in text.lower()
        context.bot.send_video.assert_not_called()

    async def test_inflight_token_discarded_after_send(self, fake_settings, tmp_path):
        """After a successful send, token is removed from vergol_inflight."""
        token = "discardtok"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"fakedata")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "FID1"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with patch(
            "worldcup_bot.bot.handlers.probe_video",
            new=AsyncMock(return_value={}),
        ):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_ver_gol_callback(update, context)

        assert token not in context.bot_data["vergol_inflight"]

    # ── happy path: ready → send from file ───────────────────────────────────

    async def test_ready_sends_video_as_reply_with_dims(self, fake_settings, tmp_path):
        """Status 'ready': send_video called as reply to original message with probed dims."""
        token = "happytok"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"fakevideodata")
        entry = _sample_clip_entry(
            status="ready",
            clip_path=str(clip_file),
        )
        update = _make_vergol_update(token, message_id=42, chat_id=99999)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "NEWID"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        fake_meta = {"width": 1920, "height": 1080, "duration": 15}

        with patch(
            "worldcup_bot.bot.handlers.probe_video",
            new=AsyncMock(return_value=fake_meta),
        ):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_ver_gol_callback(update, context)

        context.bot.send_video.assert_called_once()
        kw = context.bot.send_video.call_args[1]
        assert kw["chat_id"] == 99999
        assert kw["reply_to_message_id"] == 42
        assert kw["width"] == 1920
        assert kw["height"] == 1080
        assert kw["duration"] == 15

    async def test_fresh_send_caches_file_id_in_entry(self, fake_settings, tmp_path):
        """After a fresh send, file_id is stored in the clip-store entry and persisted."""
        token = "cachefid"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "STORED_FID"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with patch(
            "worldcup_bot.bot.handlers.probe_video",
            new=AsyncMock(return_value={}),
        ):
            with patch("worldcup_bot.bot.handlers._cs_save_clips") as mock_save:
                await cmd_ver_gol_callback(update, context)

        assert entry["file_id"] == "STORED_FID"
        mock_save.assert_called_once()

    # ── file_id cache: instant re-send ────────────────────────────────────────

    async def test_cached_file_id_resends_instantly_no_file_open(
        self, fake_settings, tmp_path
    ):
        """file_id in entry → send via file_id directly; no file I/O."""
        token = "fiidtok"
        entry = _sample_clip_entry(
            status="ready",
            clip_path=str(tmp_path / "clip.mp4"),
            file_id="CACHED_FID",
        )
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with patch("worldcup_bot.bot.handlers.probe_video") as mock_probe:
            await cmd_ver_gol_callback(update, context)

        context.bot.send_video.assert_called_once()
        kw = context.bot.send_video.call_args[1]
        assert kw["video"] == "CACHED_FID"
        # probe_video must NOT be called — we skip the file entirely
        mock_probe.assert_not_called()

    async def test_stale_file_id_evicted_falls_through_to_file(
        self, fake_settings, tmp_path
    ):
        """Stale file_id raises on send → evicted from entry, falls through to file send."""
        token = "stalefid"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"real data")
        entry = _sample_clip_entry(
            status="ready",
            clip_path=str(clip_file),
            file_id="STALE",
        )
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        call_count = 0

        async def _send_video_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("video") == "STALE":
                raise Exception("Bad file id")
            msg = MagicMock()
            msg.video = MagicMock()
            msg.video.file_id = "NEW_FID"
            return msg

        context.bot.send_video = AsyncMock(side_effect=_send_video_side_effect)

        with patch(
            "worldcup_bot.bot.handlers.probe_video",
            new=AsyncMock(return_value={}),
        ):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_ver_gol_callback(update, context)

        # First call with stale, second call from file
        assert call_count == 2
        assert "file_id" not in entry or entry.get("file_id") == "NEW_FID"

    # ── clip file missing ─────────────────────────────────────────────────────

    async def test_missing_clip_file_sends_error_message(self, fake_settings, tmp_path):
        """clip_path doesn't exist on disk → sends an error message."""
        token = "missingfile"
        entry = _sample_clip_entry(
            status="ready",
            clip_path=str(tmp_path / "ghost.mp4"),  # doesn't exist
        )
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        await cmd_ver_gol_callback(update, context)

        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args[1]["text"]
        assert "❌" in text
        context.bot.send_video.assert_not_called()

    # ── delete after send ─────────────────────────────────────────────────────

    async def test_clip_deleted_from_disk_after_successful_send(
        self, fake_settings, tmp_path
    ):
        """After a fresh send, the local clip file is deleted once file_id is saved."""
        token = "deltok1234"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"real data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "FID_SAVED"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with (
            patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})),
            patch("worldcup_bot.bot.handlers._cs_save_clips"),
        ):
            await cmd_ver_gol_callback(update, context)

        assert not clip_file.exists(), "local clip file must be deleted after send"

    async def test_clip_delete_not_called_when_send_video_raises(
        self, fake_settings, tmp_path
    ):
        """If send_video raises, the local clip file must NOT be deleted."""
        token = "nodelete"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)
        context.bot.send_video = AsyncMock(side_effect=Exception("network error"))

        with (
            patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})),
        ):
            await cmd_ver_gol_callback(update, context)

        assert clip_file.exists(), "clip file must not be deleted when send fails"

    async def test_clip_delete_not_called_when_no_file_id_returned(
        self, fake_settings, tmp_path
    ):
        """If send_video succeeds but returns no video attribute, file is not deleted."""
        token = "nofid"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        # send_video returns a message with no .video attribute
        fake_sent = MagicMock()
        fake_sent.video = None
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with (
            patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})),
            patch("worldcup_bot.bot.handlers._cs_save_clips"),
        ):
            await cmd_ver_gol_callback(update, context)

        assert clip_file.exists(), "clip file must not be deleted when no file_id available"

    async def test_stale_file_id_with_deleted_file_sends_error_message(
        self, fake_settings, tmp_path
    ):
        """Stale file_id raises AND the local file is already gone → graceful error, no crash.

        This is the post-delete-after-send state: the clip was sent, the file was
        deleted, and later Telegram evicts the file_id cache.  The handler must
        recover gracefully with an error message rather than raising.
        """
        token = "stalefid_nofile"
        # No actual file on disk — simulates post-delete-after-send state
        entry = _sample_clip_entry(
            status="ready",
            clip_path=str(tmp_path / f"{token}.mp4"),
            file_id="STALE_AND_GONE",
        )
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        # Stale file_id fails; no file to fall back to
        context.bot.send_video = AsyncMock(side_effect=Exception("Bad file id"))

        await cmd_ver_gol_callback(update, context)

        # Must send one error message and never a video
        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args[1]["text"]
        assert "❌" in text
        context.bot.send_video.assert_called_once()  # one failed stale attempt

    async def test_clip_delete_does_not_crash_if_file_already_gone(
        self, fake_settings, tmp_path
    ):
        """If the clip file is already gone when delete runs, no exception is raised."""
        token = "alreadygone"
        # clip_path points to a non-existent file
        entry = _sample_clip_entry(
            status="ready", clip_path=str(tmp_path / "gone.mp4")
        )
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "FID2"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with (
            patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})),
            patch("worldcup_bot.bot.handlers._cs_save_clips"),
        ):
            await cmd_ver_gol_callback(update, context)  # must not raise

    async def test_file_id_cached_before_delete(self, fake_settings, tmp_path):
        """file_id is persisted to disk before the local file is deleted."""
        token = "ordercheck"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, entry)

        save_called_before_delete: list[bool] = []

        def _track_save(*args, **kwargs):
            # When save is called, check if file still exists
            save_called_before_delete.append(clip_file.exists())

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "FID3"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with (
            patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})),
            patch("worldcup_bot.bot.handlers._cs_save_clips", side_effect=_track_save),
        ):
            await cmd_ver_gol_callback(update, context)

        # Save was called while the file still existed (delete happens after save)
        assert save_called_before_delete == [True]





def _no_pick() -> AsyncMock:
    """Patch asyncio.to_thread to simulate _pick_random_goal returning None (fallback)."""
    return patch("asyncio.to_thread", new_callable=AsyncMock, return_value=None)


def _make_finished_match(
    home_name: str = "France",
    away_name: str = "Morocco",
    home_tla: str = "FRA",
    away_tla: str = "MAR",
) -> Match:
    return Match(
        id=99,
        utc_date="2026-06-10T15:00:00Z",
        status="FINISHED",
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=2,
        away_score=0,
        winner="HOME_TEAM",
    )


# ── Fallback path ─────────────────────────────────────────────────────────────


class TestCmdSimulaGol:
    async def test_stores_clip_store_entry_with_correct_shape(self, fake_settings):
        """Fallback path: stores fixed Sweden-Tunisia clip-store entry with expected shape."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}

        with _no_pick():
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        clips = context.bot_data["clip_store"]
        assert len(clips) == 1
        token, info = next(iter(clips.items()))

        assert len(token) == 12
        assert all(c in "0123456789abcdef" for c in token)

        assert info["home_name"] == "Sweden"
        assert info["away_name"] == "Tunisia"
        assert info["home_score"] == 3
        assert info["away_score"] == 1
        assert info["scorer"] == "Viktor Gyökeres"
        assert info["minute"] == "60"
        assert info["scoring_team"] == "Sweden"
        assert info["home_tla"] == "SWE"
        assert info["away_tla"] == "TUN"
        assert info["status"] == "searching"

    async def test_reply_text_called_without_keyboard(self, fake_settings):
        """cmd_simula_gol sends the goal notification WITHOUT an inline keyboard."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}

        with _no_pick():
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        # At least 2 calls: ⏳ message + goal notification
        assert update.message.reply_text.await_count >= 2

        # Last call must NOT carry a keyboard (keyboard comes later via job)
        last_kwargs = update.message.reply_text.call_args[1]
        assert last_kwargs.get("reply_markup") is None

    async def test_token_matches_goal_token_of_sim_key(self, fake_settings):
        """Fallback token is sha1[:12] of the fixed Sweden-Tunisia simulation key."""
        expected_token = _goal_token("SIM:sweden-tunisia-3-1-60-gyokeres")

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}

        with _no_pick():
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        assert expected_token in context.bot_data["clip_store"]

    async def test_initialises_clip_store_when_absent(self, fake_settings):
        """cmd_simula_gol creates bot_data['clip_store'] if it doesn't exist yet."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data.pop("clip_store", None)

        with _no_pick():
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        assert "clip_store" in context.bot_data
        assert len(context.bot_data["clip_store"]) == 1

    async def test_reply_text_contains_simulation_marker(self, fake_settings):
        """The goal reply text contains a marker so users know it's a simulation."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}

        with _no_pick():
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "SIMULACI" in text.upper()

    async def test_simulagol_registered_in_app(self, fake_settings):
        """/simulagol is registered as a command in the built application."""
        from worldcup_bot.__main__ import build_app

        app = build_app(fake_settings)

        commands: set[str] = set()
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if hasattr(h, "commands"):
                    commands.update(h.commands)

        assert "simulagol" in commands


# ── Random path ───────────────────────────────────────────────────────────────


_CANNED_MATCH_SELFTEXT = (
    "**MATCH EVENTS** | via ESPN\n\n"
    "**35'** \u26bd **Goal! France 1, Morocco 0. Kylian Mbappé (France) right footed shot.**\n"
    "**72'** \u26bd **Goal! France 2, Morocco 0. Antoine Griezmann (France) header.**\n"
)


class TestCmdSimulaGolRandomPath:
    async def test_random_pick_stores_correct_shape(self, fake_settings):
        """Random path: mock client + scanner yield a real goal stored with correct shape."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [_make_finished_match()]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = (
            "/r/soccer/comments/post99/match_thread_france_vs_morocco/"
        )
        fake_scanner.get_thread_body.return_value = _CANNED_MATCH_SELFTEXT

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        clips = context.bot_data["clip_store"]
        assert len(clips) == 1
        token, info = next(iter(clips.items()))

        assert len(token) == 12
        assert info["home_name"] == "France"
        assert info["away_name"] == "Morocco"
        assert info["home_tla"] == "FRA"
        assert info["away_tla"] == "MAR"
        assert info["scorer"] in ("Kylian Mbappé", "Antoine Griezmann")
        assert info["status"] == "searching"

    async def test_random_pick_no_keyboard_on_message(self, fake_settings):
        """Random path: the sent message has no inline keyboard (keyboard added later by job)."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [_make_finished_match()]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = (
            "/r/soccer/comments/post99/match_thread_france_vs_morocco/"
        )
        fake_scanner.get_thread_body.return_value = _CANNED_MATCH_SELFTEXT

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        last_kwargs = update.message.reply_text.call_args[1]
        assert last_kwargs.get("reply_markup") is None

    async def test_random_pick_tla_aligned_to_fixture(self, fake_settings):
        """Random path: TLAs from the API fixture are used, not invented."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [
            _make_finished_match("France", "Morocco", "FRA", "MAR")
        ]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = (
            "/r/soccer/comments/post99/match_thread_france_vs_morocco/"
        )
        fake_scanner.get_thread_body.return_value = (
            "**35'** \u26bd **Goal! France 1, Morocco 0. Mbappé (France) shot.**\n"
        )

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["clip_store"].values()))
        assert info["home_tla"] == "FRA"
        assert info["away_tla"] == "MAR"

    async def test_falls_back_when_no_thread_found(self, fake_settings):
        """No match thread found → fallback to fixed Sweden-Tunisia goal."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [_make_finished_match()]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = None  # no thread

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["clip_store"].values()))
        assert info["home_name"] == "Sweden"
        assert info["scorer"] == "Viktor Gyökeres"

    async def test_falls_back_when_thread_has_no_goals(self, fake_settings):
        """Thread found but no goals parsed → fallback to fixed Sweden-Tunisia goal."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [_make_finished_match()]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = (
            "/r/soccer/comments/post99/match_thread/"
        )
        fake_scanner.get_thread_body.return_value = "No goal lines here."

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["clip_store"].values()))
        assert info["home_name"] == "Sweden"
        assert info["scorer"] == "Viktor Gyökeres"

    async def test_falls_back_when_no_finished_matches(self, fake_settings):
        """No finished matches → fallback to fixed Sweden-Tunisia goal."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = []  # no finished matches

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["clip_store"] = {}

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["clip_store"].values()))
        assert info["home_name"] == "Sweden"
        assert info["scorer"] == "Viktor Gyökeres"


# ── _pick_random_goal unit tests ──────────────────────────────────────────────


class TestPickRandomGoal:
    def test_returns_goal_tuple_on_success(self):
        """_pick_random_goal returns (GoalEvent, home_tla, away_tla) when a goal is found."""
        from worldcup_bot.reddit.models import GoalEvent

        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [
            _make_finished_match("France", "Morocco", "FRA", "MAR")
        ]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = (
            "/r/soccer/comments/post99/match_thread_france_vs_morocco/"
        )
        fake_scanner.get_thread_body.return_value = (
            "**35'** \u26bd **Goal! France 1, Morocco 0. Mbappé (France) shot.**\n"
        )

        result = _pick_random_goal(fake_client, fake_scanner)

        assert result is not None
        goal, home_tla, away_tla = result
        assert isinstance(goal, GoalEvent)
        assert home_tla == "FRA"
        assert away_tla == "MAR"

    def test_returns_none_when_no_finished_matches(self):
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = []
        fake_scanner = MagicMock()

        assert _pick_random_goal(fake_client, fake_scanner) is None

    def test_returns_none_when_all_threads_missing(self):
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [_make_finished_match()]
        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = None

        assert _pick_random_goal(fake_client, fake_scanner) is None

    def test_skips_fixture_then_succeeds_on_next(self):
        """First fixture has no thread; second has a goal → returns second goal."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [
            _make_finished_match("Germany", "Spain", "GER", "ESP"),
            _make_finished_match("France", "Morocco", "FRA", "MAR"),
        ]

        fake_scanner = MagicMock()
        # Germany-Spain: no thread; France-Morocco: valid thread
        fake_scanner.find_match_thread.side_effect = [
            None,
            "/r/soccer/comments/post99/match_thread_france_vs_morocco/",
        ]
        fake_scanner.get_thread_body.return_value = (
            "**35'** \u26bd **Goal! France 1, Morocco 0. Mbappé (France) shot.**\n"
        )

        with patch("random.shuffle"):  # disable shuffle for deterministic order
            result = _pick_random_goal(fake_client, fake_scanner)

        assert result is not None
        goal, home_tla, away_tla = result
        assert home_tla == "FRA"


# ══════════════════════════════════════════════════════════════════════════════
# cmd_tongo — probability-based Sanchez ens roba
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdTongo:
    @pytest.fixture(autouse=True)
    def _patch_tongo_load(self):
        """Provide a valid TongoConfig so tests don't fail on missing file."""
        cfg = TongoConfig(phrases=["Aguacate?", "La culpa es de Suñé"])
        with patch("worldcup_bot.bot.handlers.load_tongo_config", return_value=cfg):
            yield

    async def test_sanchez_path_when_random_below_threshold(self, fake_settings):
        """random.random() < 1/3 → reply is exactly 'Sanchez ens roba'."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.1
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Sanchez ens roba"

    async def test_phrase_path_when_random_above_threshold(self, fake_settings):
        """random.random() >= 1/3 → reply comes from the phrase pool (not Sanchez)."""
        update = _make_update()
        context = _make_context(fake_settings)
        known_phrase = "Aguacate?"

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = known_phrase
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == known_phrase
        assert text != "Sanchez ens roba"

    async def test_phrase_path_does_not_use_sanchez_constant(self, fake_settings):
        """When above threshold, random.choice is called (not the Sanchez constant)."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = "La culpa es de Suñé"
            await cmd_tongo(update, context)

        mock_random.choice.assert_called_once()


class TestCmdTongoConfigError:
    """Tests for the config-load-failure path of cmd_tongo."""

    async def test_missing_yaml_replies_error_message(self, fake_settings):
        """When TongoUsers.yml can't be loaded, a Spanish error is sent."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch(
            "worldcup_bot.bot.handlers.load_tongo_config",
            side_effect=TongoConfigError("fichero no encontrado"),
        ):
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "❌" in text
        assert "tongo" in text.lower()
        assert "/tongocheck" in text

    async def test_config_error_does_not_call_random_choice(self, fake_settings):
        """No phrase pool is consulted when config load fails."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch(
            "worldcup_bot.bot.handlers.load_tongo_config",
            side_effect=TongoConfigError("broken YAML"),
        ), patch("worldcup_bot.bot.handlers.random") as mock_random:
            await cmd_tongo(update, context)

        mock_random.choice.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_tongo — GIF / animation paths
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdTongoGifs:
    """Tests for the GIF branch of cmd_tongo."""

    @pytest.fixture(autouse=True)
    def _patch_tongo_load(self):
        """Provide a valid TongoConfig so tests don't fail on missing file."""
        cfg = TongoConfig(phrases=["Aguacate?", "La culpa es de Suñé"])
        with patch("worldcup_bot.bot.handlers.load_tongo_config", return_value=cfg):
            yield

    def _gif_settings(self, gifs_dir: str) -> Settings:
        return Settings(
            telegram_bot_token="fake-token",
            football_data_api_key="fake-api-key",
            predictions_path="fake_predictions.yml",
            tongo_gifs_dir=gifs_dir,
        )

    async def test_gif_chosen_sends_animation(self, tmp_path):
        """When random.choice returns a Path, send_animation is awaited and reply_text not called."""
        gif_file = tmp_path / "funny.gif"
        gif_file.write_bytes(b"GIF89a")

        update = _make_update()
        context = _make_context(self._gif_settings(str(tmp_path)))

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = gif_file
            await cmd_tongo(update, context)

        context.bot.send_animation.assert_awaited_once()
        call_kwargs = context.bot.send_animation.call_args
        assert call_kwargs.kwargs["chat_id"] == 12345
        update.message.reply_text.assert_not_called()

    async def test_phrase_chosen_does_not_send_animation(self, fake_settings):
        """When random.choice returns a string phrase, reply_text is called and send_animation is not."""
        update = _make_update()
        context = _make_context(fake_settings)
        known_phrase = "La culpa es de Suñé"

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = known_phrase
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with(known_phrase)
        context.bot.send_animation.assert_not_called()

    async def test_gif_send_failure_falls_back_to_phrase(self, tmp_path):
        """If send_animation raises, a fallback phrase is sent via reply_text."""
        gif_file = tmp_path / "broken.gif"
        gif_file.write_bytes(b"GIF89a")

        update = _make_update()
        context = _make_context(self._gif_settings(str(tmp_path)))
        context.bot.send_animation = AsyncMock(side_effect=Exception("Telegram error"))
        fallback_phrase = "Aguacate?"

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.side_effect = [gif_file, fallback_phrase]
            await cmd_tongo(update, context)

        context.bot.send_animation.assert_awaited_once()
        update.message.reply_text.assert_called_once_with(fallback_phrase)

    async def test_gifs_in_pool_when_dir_has_files(self, tmp_path):
        """GIF Paths are added to the pool when the gifs_dir contains supported files."""
        (tmp_path / "a.gif").write_bytes(b"GIF89a")
        (tmp_path / "b.mp4").write_bytes(b"\x00\x00\x00")

        update = _make_update()
        context = _make_context(self._gif_settings(str(tmp_path)))
        known_phrase = "Aguacate?"

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = known_phrase
            await cmd_tongo(update, context)

        pool = mock_random.choice.call_args[0][0]
        gif_paths = [p for p in pool if isinstance(p, Path)]
        assert len(gif_paths) == 2

    async def test_empty_gifs_dir_pool_has_no_paths(self, tmp_path):
        """If gifs_dir is empty, pool contains only strings."""
        update = _make_update()
        context = _make_context(self._gif_settings(str(tmp_path)))
        known_phrase = "Aguacate?"

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = known_phrase
            await cmd_tongo(update, context)

        pool = mock_random.choice.call_args[0][0]
        assert all(isinstance(item, str) for item in pool)

    async def test_nonexistent_gifs_dir_pool_has_no_paths(self, fake_settings):
        """Non-existent gifs_dir is tolerated; pool contains only strings."""
        update = _make_update()
        context = _make_context(fake_settings)
        known_phrase = "Aguacate?"

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = known_phrase
            await cmd_tongo(update, context)

        pool = mock_random.choice.call_args[0][0]
        assert all(isinstance(item, str) for item in pool)


# ══════════════════════════════════════════════════════════════════════════════
# cmd_ver_gol_callback — vergol stats counter wiring (Block 4)
# ══════════════════════════════════════════════════════════════════════════════


def _make_vergol_update_with_user(
    token: str,
    user_id: int = 7,
    full_name: str = "María García",
    username: str | None = "mariagarcia",
) -> MagicMock:
    """Build a fake Update with a real-ish from_user on the CallbackQuery."""
    update = _make_vergol_update(token)
    user = MagicMock()
    user.id = user_id
    user.full_name = full_name
    user.username = username
    update.callback_query.from_user = user
    return update


class TestCmdVerGolCallbackStats:
    """Test the vergol stats counter wiring added in Block 4."""

    async def test_fresh_send_calls_record_view_with_correct_args(
        self, fake_settings, tmp_path
    ):
        """After a fresh file send, record_view is called with correct user_id/name/token."""
        token = "statstoken"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update_with_user(token, user_id=42, full_name="Alice")
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "FID"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                with patch("worldcup_bot.bot.handlers._vs_record_view") as mock_rv:
                    with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value={}):
                        with patch("worldcup_bot.bot.handlers._vs_save_stats"):
                            await cmd_ver_gol_callback(update, context)

        mock_rv.assert_called_once()
        args = mock_rv.call_args[0]
        assert args[1] == 42        # user_id
        assert args[2] == "Alice"   # name
        assert args[3] == token     # token

    async def test_cached_file_id_send_calls_record_view(self, fake_settings, tmp_path):
        """After a cached file_id send, record_view is also called."""
        token = "cachedstats"
        entry = _sample_clip_entry(
            status="ready",
            clip_path=str(tmp_path / "clip.mp4"),
            file_id="CACHED",
        )
        update = _make_vergol_update_with_user(token, user_id=99, full_name="Bob")
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with patch("worldcup_bot.bot.handlers._vs_record_view") as mock_rv:
            with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value={}):
                with patch("worldcup_bot.bot.handlers._vs_save_stats"):
                    await cmd_ver_gol_callback(update, context)

        mock_rv.assert_called_once()
        args = mock_rv.call_args[0]
        assert args[1] == 99
        assert args[2] == "Bob"
        assert args[3] == token

    async def test_stats_failure_does_not_break_video_delivery(
        self, fake_settings, tmp_path
    ):
        """If save_stats raises, the video is still delivered — counter failures are best-effort."""
        token = "robusttoken"
        clip_file = tmp_path / f"{token}.mp4"
        clip_file.write_bytes(b"data")
        entry = _sample_clip_entry(status="ready", clip_path=str(clip_file))
        update = _make_vergol_update_with_user(token, user_id=1)
        context = _make_vergol_context(fake_settings, token, entry)

        fake_sent = MagicMock()
        fake_sent.video = MagicMock()
        fake_sent.video.file_id = "FID2"
        context.bot.send_video = AsyncMock(return_value=fake_sent)

        with patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})):
            with patch("worldcup_bot.bot.handlers._cs_save_clips"):
                with patch(
                    "worldcup_bot.bot.handlers._vs_save_stats",
                    side_effect=OSError("disk full"),
                ):
                    with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value={}):
                        with patch("worldcup_bot.bot.handlers._vs_record_view"):
                            # Must not raise
                            await cmd_ver_gol_callback(update, context)

        # Video was still sent
        context.bot.send_video.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_estadisticas
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdEstadisticas:
    async def test_empty_stats_sends_no_data_message(self, fake_settings):
        """No data → sends the 'aún no hay estadísticas' message."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value={}):
            await cmd_estadisticas(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "estadísticas" in text.lower()

    async def test_leaderboard_formatted_with_bold_html_names(self, fake_settings):
        """Leaderboard entries use <b>name</b> and the trophy header."""
        update = _make_update()
        context = _make_context(fake_settings)

        fake_data = {
            "1": {"name": "Alice", "tokens": ["a", "b", "c"]},
            "2": {"name": "Bob", "tokens": ["a"]},
        }

        with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value=fake_data):
            await cmd_estadisticas(update, context)

        update.message.reply_text.assert_called_once()
        call = update.message.reply_text.call_args
        text = call[0][0]
        kwargs = call[1]

        assert kwargs.get("parse_mode") == "HTML"
        assert "🏆" in text
        assert "<b>Alice</b>" in text
        assert "<b>Bob</b>" in text
        # Alice has more views → appears first
        assert text.index("Alice") < text.index("Bob")

    async def test_html_escapes_names(self, fake_settings):
        """Names with HTML-special chars are escaped."""
        update = _make_update()
        context = _make_context(fake_settings)

        fake_data = {
            "1": {"name": "<script>alert(1)</script>", "tokens": ["a"]},
        }

        with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value=fake_data):
            await cmd_estadisticas(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    async def test_uses_count_from_tokens_length(self, fake_settings):
        """The displayed count is len(tokens)."""
        update = _make_update()
        context = _make_context(fake_settings)

        fake_data = {"1": {"name": "María", "tokens": ["a", "b", "c", "d", "e"]}}

        with patch("worldcup_bot.bot.handlers._vs_load_stats", return_value=fake_data):
            await cmd_estadisticas(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "5" in text

    async def test_estadisticas_registered_in_app(self, fake_settings):
        """/estadisticas is registered as a CommandHandler in build_app."""
        from worldcup_bot.__main__ import build_app

        app = build_app(fake_settings)

        commands: set[str] = set()
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if hasattr(h, "commands"):
                    commands.update(h.commands)

        assert "estadisticas" in commands

    async def test_estadisticas_mentioned_in_cmd_start(self, fake_settings):
        """/estadisticas appears in the /start help text."""
        update = _make_update()
        context = _make_context(fake_settings)

        await cmd_start(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "/estadisticas" in text


# ══════════════════════════════════════════════════════════════════════════════
# cmd_en_directo — enriched live match detail
# ══════════════════════════════════════════════════════════════════════════════


_LIVE_MATCH = Match(
    id=1,
    utc_date="2026-06-17T18:00:00Z",
    status="IN_PLAY",
    stage="GROUP_STAGE",
    group="GROUP_A",
    home_tla="POR",
    away_tla="COD",
    home_name="Portugal",
    away_name="Congo DR",
    home_score=1,
    away_score=1,
    winner=None,
)

_ENRICHED_EVENTS = {
    "minute": "71",
    "goals": [
        {"minute": "6", "team": "Portugal", "scorer": "João Neves"},
        {"minute": "45+5", "team": "Congo DR", "scorer": "Yoane Wissa"},
    ],
    "cards": [
        {"minute": "13", "team": "Portugal", "player": "Bernardo Silva", "type": "yellow"},
    ],
    "subs": [
        {"minute": "71", "team": "Portugal", "in": "Rafael Leão", "out": "Pedro Neto"},
    ],
    "lineup": {"home": ["Diogo Costa", "Gonçalo Inácio"], "away": ["Masuaku", "Wissa"]},
}


class TestCmdEnDirecto:
    @pytest.mark.asyncio
    async def test_no_live_matches_sends_no_hay(self, fake_settings):
        """When get_live_matches returns [], the 'no hay' message is sent."""
        update = _make_update()
        context = _make_context(fake_settings)

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = []

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            await cmd_en_directo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "No hay partidos en directo" in text

    @pytest.mark.asyncio
    async def test_ai_disabled_uses_format_match_fallback(self, fake_settings):
        """When AI is disabled, format_match is used (no scanner thread calls)."""
        update = _make_update()
        context = _make_context(fake_settings)
        # settings has empty openai keys → ai_enabled returns False

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch(
                "worldcup_bot.bot.handlers.RedditMatchScanner"
            ) as mock_scanner_cls:
                await cmd_en_directo(update, context)

        # Scanner's find_match_thread must NOT have been called
        if mock_scanner_cls.called:
            instance = mock_scanner_cls.return_value
            instance.find_match_thread.assert_not_called()

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        # format_match output includes the score and live emoji
        assert "Portugal" in text
        assert "Congo DR" in text

    @pytest.mark.asyncio
    async def test_knockout_match_appends_camps_faceoff(self, fake_settings):
        """A live KNOCKOUT match appends the ⚔️ porra face-off with backers."""
        update = _make_update()
        context = _make_context(fake_settings)
        ko_match = Match(
            id=9, utc_date="2026-06-29T18:00:00Z", status="IN_PLAY",
            stage="LAST_32", group=None,
            home_tla="NED", away_tla="MAR", home_name="Netherlands", away_name="Morocco",
            home_score=0, away_score=0, winner=None,
        )
        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [ko_match]
        preds = {"participants": {
            "ann": {"display_name": "Ann", "groups": {}, "knockout": {"round_of_32": ["NED"]}},
            "bob": {"display_name": "Bob", "groups": {}, "knockout": {"round_of_32": ["MAR"]}},
        }}
        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=preds):
                await cmd_en_directo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "⚔️" in text
        assert "Ann" in text and "Bob" in text

    @pytest.mark.asyncio
    async def test_group_match_has_no_camps_faceoff(self, fake_settings):
        """A live GROUP-STAGE match does NOT append the ⚔️ face-off."""
        update = _make_update()
        context = _make_context(fake_settings)
        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]  # GROUP_STAGE
        preds = {"participants": {
            "ann": {"display_name": "Ann", "groups": {"A": ["POR", "COD", "MEX"]},
                    "knockout": {"round_of_32": ["POR"]}},
        }}
        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=preds):
                await cmd_en_directo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "⚔️" not in text

    @pytest.mark.asyncio
    async def test_ai_enabled_no_thread_uses_format_match_fallback(self, tmp_path):
        """AI enabled but no match thread found → falls back to format_match."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(return_value=None)
        mock_scanner.find_match_thread = MagicMock(return_value=None)

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner", return_value=mock_scanner):
                with patch("worldcup_bot.bot.handlers.AIClient"):
                    await cmd_en_directo(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "Portugal" in text
        assert "Congo DR" in text

    @pytest.mark.asyncio
    async def test_ai_enabled_with_thread_returns_enriched_block(self, tmp_path):
        """AI enabled + thread found + extract succeeds → enriched block in reply."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        mock_scanner = MagicMock()
        mock_scanner.find_match_thread = MagicMock(return_value="/r/soccer/comments/abc/")
        mock_scanner.get_thread_body = MagicMock(return_value="thread body text")

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner", return_value=mock_scanner):
                with patch("worldcup_bot.bot.handlers.AIClient"):
                    with patch(
                        "worldcup_bot.bot.handlers.extract_match_events",
                        new=AsyncMock(return_value=_ENRICHED_EVENTS),
                    ):
                        await cmd_en_directo(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        kwargs = update.message.reply_text.call_args.kwargs
        assert "🔴 EN DIRECTO" in text
        assert "João Neves" in text
        assert "Yoane Wissa" in text
        assert kwargs["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_per_match_exception_falls_back_to_format_match(self, tmp_path):
        """If enrichment raises an exception, falls back to format_match (no crash)."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(side_effect=RuntimeError("boom"))
        mock_scanner.find_match_thread = MagicMock(side_effect=RuntimeError("boom"))

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner", return_value=mock_scanner):
                with patch("worldcup_bot.bot.handlers.AIClient"):
                    await cmd_en_directo(update, context)

        # Must not crash; fallback format_match still produces a reply
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "Portugal" in text
        assert "Congo DR" in text

    @pytest.mark.asyncio
    async def test_multiple_matches_joined_by_separator(self, fake_settings):
        """Multiple live matches are sent as separate messages."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
        )
        update = _make_update()
        context = _make_context(settings)

        match2 = Match(
            id=2,
            utc_date="2026-06-17T20:00:00Z",
            status="IN_PLAY",
            stage="GROUP_STAGE",
            group="GROUP_B",
            home_tla="FRA",
            away_tla="ESP",
            home_name="France",
            away_name="Spain",
            home_score=0,
            away_score=0,
            winner=None,
        )
        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH, match2]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                await cmd_en_directo(update, context)

        assert update.message.reply_text.call_count == 2
        assert "Portugal" in update.message.reply_text.call_args_list[0][0][0]
        assert "France" in update.message.reply_text.call_args_list[1][0][0]

    @pytest.mark.asyncio
    async def test_ai_enabled_saves_snapshot(self, tmp_path):
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)
        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]
        mock_scanner = MagicMock()
        mock_scanner.find_match_thread = MagicMock(return_value="/r/soccer/comments/abc/")
        mock_scanner.get_thread_body = MagicMock(return_value="thread body text")

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner", return_value=mock_scanner):
                with patch("worldcup_bot.bot.handlers.AIClient"):
                    with patch(
                        "worldcup_bot.bot.handlers.extract_match_events",
                        new=AsyncMock(return_value=_ENRICHED_EVENTS),
                    ):
                        await cmd_en_directo(update, context)

        store_path = tmp_path / "endirecto.json"
        assert store_path.exists()
        data = __import__("json").loads(store_path.read_text(encoding="utf-8"))
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_ai_disabled_does_not_write_store(self, tmp_path):
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)
        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                await cmd_en_directo(update, context)

        assert not (tmp_path / "endirecto.json").exists()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_en_directo — shared scanner + find_thread_permalink
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdEnDirectoSharedScanner:
    """Verify that cmd_en_directo reuses the shared bot_data scanner and uses
    find_thread_permalink (cached /new/ listing) before falling back to the
    search endpoint."""

    @pytest.mark.asyncio
    async def test_reuses_existing_scanner_from_bot_data(self, tmp_path):
        """When bot_data already has 'reddit_scanner', cmd_en_directo must NOT
        construct a new RedditMatchScanner — it uses the existing instance."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(return_value=None)
        mock_scanner.find_match_thread = MagicMock(return_value=None)
        context.bot_data["reddit_scanner"] = mock_scanner

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner") as mock_cls:
                with patch("worldcup_bot.bot.handlers.AIClient"):
                    await cmd_en_directo(update, context)

        # The class constructor must NOT have been called — we reused the existing one.
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_lazy_init_stores_scanner_in_bot_data(self, tmp_path):
        """When bot_data has no 'reddit_scanner', cmd_en_directo creates one and
        stores it in bot_data so subsequent calls reuse it."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)
        # Ensure no scanner is pre-populated
        context.bot_data.pop("reddit_scanner", None)

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        mock_scanner = MagicMock()

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner", return_value=mock_scanner):
                await cmd_en_directo(update, context)

        assert context.bot_data.get("reddit_scanner") is mock_scanner

    @pytest.mark.asyncio
    async def test_find_thread_permalink_used_first_and_produces_keyboard(self, tmp_path):
        """When find_thread_permalink returns a permalink and AI returns events,
        the reply is sent WITH an InlineKeyboardMarkup (not the plain fallback)."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(return_value="/r/soccer/comments/xyz/")
        mock_scanner.get_thread_body = MagicMock(return_value="thread body text")
        context.bot_data["reddit_scanner"] = mock_scanner

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.AIClient"):
                with patch(
                    "worldcup_bot.bot.handlers.extract_match_events",
                    new=AsyncMock(return_value=_ENRICHED_EVENTS),
                ):
                    await cmd_en_directo(update, context)

        update.message.reply_text.assert_called_once()
        kwargs = update.message.reply_text.call_args.kwargs
        assert kwargs["reply_markup"] is not None
        # InlineKeyboardMarkup wraps a list of rows; each button is an InlineKeyboardButton.
        markup = kwargs["reply_markup"]
        button_count = sum(len(row) for row in markup.inline_keyboard)
        assert button_count >= 1
        # find_match_thread must NOT have been called (we found it via the cached listing)
        mock_scanner.find_match_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_find_match_thread_when_permalink_is_none(self, tmp_path):
        """When find_thread_permalink returns None, find_match_thread is tried next."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(return_value=None)
        mock_scanner.find_match_thread = MagicMock(return_value="/r/soccer/comments/abc/")
        mock_scanner.get_thread_body = MagicMock(return_value="thread body")
        context.bot_data["reddit_scanner"] = mock_scanner

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.AIClient"):
                with patch(
                    "worldcup_bot.bot.handlers.extract_match_events",
                    new=AsyncMock(return_value=_ENRICHED_EVENTS),
                ):
                    await cmd_en_directo(update, context)

        mock_scanner.find_match_thread.assert_called_once()
        update.message.reply_text.assert_called_once()
        kwargs = update.message.reply_text.call_args.kwargs
        assert kwargs["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_both_lookups_none_falls_back_to_format_match(self, tmp_path):
        """When both find_thread_permalink and find_match_thread return None,
        format_match is used (no keyboard)."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(return_value=None)
        mock_scanner.find_match_thread = MagicMock(return_value=None)
        context.bot_data["reddit_scanner"] = mock_scanner

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.AIClient"):
                await cmd_en_directo(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        # format_match output — no keyboard
        assert "Portugal" in text
        kwargs = update.message.reply_text.call_args.kwargs
        assert not kwargs.get("reply_markup")

    @pytest.mark.asyncio
    async def test_never_raises(self, tmp_path):
        """cmd_en_directo must not propagate any exception to the caller."""
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="key",
            openai_base_url="http://ai",
            openai_model="gpt-4",
            state_dir=str(tmp_path),
        )
        update = _make_update()
        context = _make_context(settings)

        mock_scanner = MagicMock()
        mock_scanner.find_thread_permalink = MagicMock(side_effect=RuntimeError("network"))
        mock_scanner.find_match_thread = MagicMock(side_effect=RuntimeError("network"))
        context.bot_data["reddit_scanner"] = mock_scanner

        mock_client = MagicMock()
        mock_client.get_live_matches.return_value = [_LIVE_MATCH]

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            with patch("worldcup_bot.bot.handlers.AIClient"):
                # Must not raise
                await cmd_en_directo(update, context)

        update.message.reply_text.assert_called_once()


def _make_endirecto_callback_update(token: str, code: str) -> MagicMock:
    update = MagicMock()
    update.callback_query.data = f"ed|{token}|{code}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


class TestCmdEndirectoCallback:
    @pytest.mark.asyncio
    async def test_reveal_section_edits_message(self, tmp_path, fake_settings):
        import json

        settings = replace(fake_settings, state_dir=str(tmp_path))
        snap = {
            "token": "abc12345",
            "match_id": 1,
            "minute": "71",
            "home_name": "Portugal",
            "away_name": "Congo DR",
            "home_tla": "POR",
            "away_tla": "COD",
            "home_score": 1,
            "away_score": 1,
            "goals": [{"minute": "6", "team": "Portugal", "scorer": "João Neves"}],
            "cards": [{"minute": "13", "team": "Portugal", "player": "Bernardo Silva", "type": "yellow"}],
            "subs": [],
            "lineup": {"home": ["Diogo Costa"], "away": ["Masuaku"]},
            "revealed": [],
            "created": 0.0,
        }
        (tmp_path / "endirecto.json").write_text(json.dumps({"abc12345": snap}), encoding="utf-8")
        update = _make_endirecto_callback_update("abc12345", "t")
        context = _make_context(settings)

        await cmd_endirecto_callback(update, context)

        update.callback_query.edit_message_text.assert_called_once()
        assert "🟨 Tarjetas" in update.callback_query.edit_message_text.call_args[0][0]
        update.callback_query.answer.assert_called()

    @pytest.mark.asyncio
    async def test_expired_token_answers_alert(self, fake_settings, tmp_path):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        update = _make_endirecto_callback_update("deadbeef", "t")
        context = _make_context(settings)

        await cmd_endirecto_callback(update, context)

        update.callback_query.answer.assert_called_once_with("Datos no disponibles.", show_alert=True)

    @pytest.mark.asyncio
    async def test_all_revealed_still_has_goles_button(self, tmp_path, fake_settings):
        import json

        settings = replace(fake_settings, state_dir=str(tmp_path))
        snap = {
            "token": "abc12345",
            "match_id": 1,
            "minute": "71",
            "home_name": "Portugal",
            "away_name": "Congo DR",
            "home_tla": "POR",
            "away_tla": "COD",
            "home_score": 1,
            "away_score": 1,
            "goals": [],
            "cards": [],
            "subs": [],
            "lineup": {"home": [], "away": []},
            "revealed": ["tarjetas", "alineacion", "cambios"],
            "created": 0.0,
        }
        (tmp_path / "endirecto.json").write_text(json.dumps({"abc12345": snap}), encoding="utf-8")
        update = _make_endirecto_callback_update("abc12345", "t")
        context = _make_context(settings)

        await cmd_endirecto_callback(update, context)

        # The ⚽ Goles button is always present, even once every section is revealed.
        markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        assert markup is not None
        assert markup.inline_keyboard[-1][0].callback_data == "ed|abc12345|g"

    @pytest.mark.asyncio
    async def test_invalid_code_answers_alert(self, fake_settings, tmp_path):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        update = _make_endirecto_callback_update("abc12345", "z")
        context = _make_context(settings)

        await cmd_endirecto_callback(update, context)

        update.callback_query.answer.assert_called_once_with("Sección desconocida.", show_alert=True)

    @pytest.mark.asyncio
    async def test_never_raises_on_bad_query_data(self, fake_settings, tmp_path):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        update = MagicMock()
        update.callback_query.data = "bad-data"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = _make_context(settings)

        await cmd_endirecto_callback(update, context)

        update.callback_query.answer.assert_called_once_with("Datos inválidos.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# /endirecto ⚽ Goles button — on-demand goal fetch + per-goal send
# ══════════════════════════════════════════════════════════════════════════════


def _write_snap(tmp_path, **overrides) -> dict:
    import json
    snap = {
        "token": "abc12345", "match_id": 1, "minute": "30",
        "home_name": "Brazil", "away_name": "Japan",
        "home_tla": "BRA", "away_tla": "JPN",
        "home_score": 1, "away_score": 0,
        "goals": [], "cards": [], "subs": [],
        "lineup": {"home": [], "away": []}, "revealed": [], "created": 0.0,
    }
    snap.update(overrides)
    (tmp_path / "endirecto.json").write_text(json.dumps({snap["token"]: snap}), encoding="utf-8")
    return snap


def _make_goles_update(data: str) -> MagicMock:
    update = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.message.chat_id = 999
    update.callback_query.message.message_id = 42
    return update


def _goal_event(minute="23", scorer="Neymar", hs=1, as_=0, key="p:1-0@23:neymar"):
    from worldcup_bot.reddit.models import GoalEvent
    return GoalEvent(
        minute_text=minute, minute_sort=float(minute), scorer=scorer, scoring_team="Brazil",
        home_team="Brazil", away_team="Japan", home_score=hs, away_score=as_, raw="", key=key,
    )


class TestEndirectoGolesButton:
    @pytest.mark.asyncio
    async def test_goles_fetches_and_shows_one_button_per_goal(self, tmp_path, fake_settings):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        _write_snap(tmp_path)
        update = _make_goles_update("ed|abc12345|g")
        context = _make_context(settings)
        context.bot.send_message = AsyncMock()
        scanner = MagicMock()
        scanner.find_thread_permalink.return_value = "/r/soccer/comments/xyz/match/"
        scanner.get_thread_body.return_value = "body"
        context.bot_data["reddit_scanner"] = scanner

        goals = [_goal_event("23", "Neymar", 1, 0, "k1"), _goal_event("67", "Mitoma", 1, 1, "k2")]
        with patch("worldcup_bot.bot.handlers.parse_goal_events", return_value=goals):
            await cmd_endirecto_callback(update, context)

        update.callback_query.edit_message_reply_markup.assert_called_once()
        markup = update.callback_query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        assert len(markup.inline_keyboard) == 2
        assert markup.inline_keyboard[0][0].callback_data == "edgol|abc12345|0"
        assert markup.inline_keyboard[1][0].callback_data == "edgol|abc12345|1"

    @pytest.mark.asyncio
    async def test_goles_only_adds_goals_not_already_stored(self, tmp_path, fake_settings):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        existing = {"minute_text": "23", "minute_sort": 23.0, "scorer": "Neymar", "scoring_team": "Brazil",
                    "home_team": "Brazil", "away_team": "Japan", "home_score": 1, "away_score": 0, "raw": "", "key": "k1"}
        _write_snap(tmp_path, reddit_goals=[existing])
        update = _make_goles_update("ed|abc12345|g")
        context = _make_context(settings)
        context.bot.send_message = AsyncMock()
        scanner = MagicMock()
        scanner.find_thread_permalink.return_value = "/r/soccer/comments/xyz/match/"
        scanner.get_thread_body.return_value = "body"
        context.bot_data["reddit_scanner"] = scanner

        # Reddit returns the already-known k1 plus a new k2 → only k2 added.
        goals = [_goal_event("23", "Neymar", 1, 0, "k1"), _goal_event("67", "Mitoma", 1, 1, "k2")]
        with patch("worldcup_bot.bot.handlers.parse_goal_events", return_value=goals):
            await cmd_endirecto_callback(update, context)

        markup = update.callback_query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        assert len(markup.inline_keyboard) == 2  # deduped to 2 unique goals

    @pytest.mark.asyncio
    async def test_goles_no_goals_sends_message_no_keyboard(self, tmp_path, fake_settings):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        _write_snap(tmp_path)
        update = _make_goles_update("ed|abc12345|g")
        context = _make_context(settings)
        context.bot.send_message = AsyncMock()
        scanner = MagicMock()
        scanner.find_thread_permalink.return_value = None
        scanner.find_match_thread.return_value = None
        context.bot_data["reddit_scanner"] = scanner

        await cmd_endirecto_callback(update, context)

        update.callback_query.edit_message_reply_markup.assert_not_called()
        context.bot.send_message.assert_called_once()
        assert "No he encontrado goles" in context.bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_goal_button_sends_goal_and_clears_keyboard(self, tmp_path, fake_settings):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        goal = {"minute_text": "23", "minute_sort": 23.0, "scorer": "Neymar", "scoring_team": "Brazil",
                "home_team": "Brazil", "away_team": "Japan", "home_score": 1, "away_score": 0, "raw": "", "key": "k1"}
        _write_snap(tmp_path, reddit_goals=[goal])
        update = _make_goles_update("edgol|abc12345|0")
        context = _make_context(settings)
        context.bot.send_message = AsyncMock()

        await cmd_endirecto_goal_callback(update, context)

        context.bot.send_message.assert_called_once()
        sent = context.bot.send_message.call_args.kwargs
        assert "Neymar" in sent["text"] and "¡GOL!" in sent["text"]
        assert sent["reply_to_message_id"] == 42
        # the goals keyboard is removed after posting
        update.callback_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)

    @pytest.mark.asyncio
    async def test_goal_button_invalid_index_alerts(self, tmp_path, fake_settings):
        settings = replace(fake_settings, state_dir=str(tmp_path))
        _write_snap(tmp_path, reddit_goals=[])
        update = _make_goles_update("edgol|abc12345|5")
        context = _make_context(settings)
        context.bot.send_message = AsyncMock()

        await cmd_endirecto_goal_callback(update, context)

        update.callback_query.answer.assert_called_once_with("Ese gol ya no está disponible.", show_alert=True)
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_edgol_handler_registered(self, fake_settings):
        from telegram.ext import CallbackQueryHandler
        from worldcup_bot.__main__ import build_app
        app = build_app(fake_settings)
        patterns = [h.pattern.pattern for group in app.handlers.values() for h in group
                    if isinstance(h, CallbackQueryHandler) and getattr(h, "pattern", None)]
        assert any("edgol" in p for p in patterns)
# ══════════════════════════════════════════════════════════════════════════════


def _hoy_match(status: str, uid: int = 1) -> Match:
    """Minimal Match fixture for cmd_hoy tests."""
    return Match(
        id=uid,
        utc_date="2026-06-18T18:00:00Z",
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla="ESP",
        away_tla="FRA",
        home_name="Spain",
        away_name="France",
        home_score=None if status in ("SCHEDULED", "TIMED") else 1,
        away_score=None if status in ("SCHEDULED", "TIMED") else 0,
        winner=None,
    )


def _make_offset_client(offset_map: dict[int, list]) -> MagicMock:
    """Return a mock client whose get_football_day_matches returns per-offset lists."""
    mock_client = MagicMock()

    def _get(tz, offset, h):
        return offset_map.get(offset, [])

    mock_client.get_football_day_matches.side_effect = _get
    return mock_client


class TestCmdHoy:
    """Tests for cmd_hoy rollover-to-next-jornada logic."""

    @pytest.mark.asyncio
    async def test_normal_day_shows_hoy_header_and_time_only(self, fake_settings):
        """offset 0 has a SCHEDULED match → 'Partidos de hoy' header, time-only format_match."""
        update = _make_update()
        context = _make_context(fake_settings)
        client = _make_offset_client({0: [_hoy_match("SCHEDULED")]})

        with patch("worldcup_bot.bot.handlers.make_client", return_value=client):
            with patch("worldcup_bot.bot.handlers.format_match", return_value="Spain vs France - ⌚ 20:00") as mock_fmt:
                with patch("worldcup_bot.bot.handlers.format_match_with_date") as mock_fmt_date:
                    await cmd_hoy(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Partidos de hoy" in text
        assert "09:00" in text  # default anchor hour
        mock_fmt.assert_called_once()
        mock_fmt_date.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_finished_rolls_to_offset1(self, fake_settings):
        """07:00 scenario: offset 0 all FINISHED, offset 1 has SCHEDULED → próximos header + dated format."""
        update = _make_update()
        context = _make_context(fake_settings)
        finished = _hoy_match("FINISHED")
        scheduled = _hoy_match("SCHEDULED", uid=2)
        client = _make_offset_client({0: [finished], 1: [scheduled]})

        with patch("worldcup_bot.bot.handlers.make_client", return_value=client):
            with patch("worldcup_bot.bot.handlers.format_match_with_date", return_value="19-06-2026: Spain vs France - ⌚ 09:00") as mock_fwd:
                with patch("worldcup_bot.bot.handlers.format_match"):
                    await cmd_hoy(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Ya han acabado los partidos de hoy" in text
        assert "próximos" in text
        mock_fwd.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_offset0_rolls_to_offset2(self, fake_settings):
        """offset 0 empty, offset 1 empty, offset 2 has SCHEDULED → shows offset 2 with próximos header."""
        update = _make_update()
        context = _make_context(fake_settings)
        client = _make_offset_client({2: [_hoy_match("SCHEDULED", uid=5)]})

        with patch("worldcup_bot.bot.handlers.make_client", return_value=client):
            with patch("worldcup_bot.bot.handlers.format_match_with_date", return_value="21-06-2026: line") as mock_fwd:
                with patch("worldcup_bot.bot.handlers.format_match"):
                    await cmd_hoy(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Ya han acabado los partidos de hoy" in text
        mock_fwd.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_upcoming_shows_offset0_finished_under_hoy_header(self, fake_settings):
        """All 15 offsets: only offset 0 has matches (all FINISHED), rest are empty → shows today's results under 'hoy' header."""
        update = _make_update()
        context = _make_context(fake_settings)
        finished = _hoy_match("FINISHED")
        # offset 0 all FINISHED, offsets 1-14 empty
        client = _make_offset_client({0: [finished]})

        with patch("worldcup_bot.bot.handlers.make_client", return_value=client):
            with patch("worldcup_bot.bot.handlers.format_match", return_value="Spain 1 - 0 France ⚽️") as mock_fmt:
                with patch("worldcup_bot.bot.handlers.format_match_with_date"):
                    await cmd_hoy(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Partidos de hoy" in text
        assert "Ya han acabado" not in text
        mock_fmt.assert_called_once()

    @pytest.mark.asyncio
    async def test_truly_nothing_replies_no_partidos(self, fake_settings):
        """All 15 offsets return [] → replies 'No hay partidos programados.'"""
        update = _make_update()
        context = _make_context(fake_settings)
        client = _make_offset_client({})  # every offset returns []

        with patch("worldcup_bot.bot.handlers.make_client", return_value=client):
            await cmd_hoy(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "No hay partidos programados" in text

    @pytest.mark.asyncio
    async def test_api_error_on_first_call_sends_error_message(self, fake_settings):
        """FootballAPIError on the first loop iteration → replies the api-error message."""
        update = _make_update()
        context = _make_context(fake_settings)
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = FootballAPIError(500, "boom")

        with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
            await cmd_hoy(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Error" in text or "Rate limit" in text or "❌" in text

    @pytest.mark.asyncio
    async def test_loop_stops_at_first_window_with_upcoming_match(self, fake_settings):
        """Loop stops at offset 1 and does NOT consult offset 2 if offset 1 already has SCHEDULED."""
        update = _make_update()
        context = _make_context(fake_settings)
        finished = _hoy_match("FINISHED")
        scheduled = _hoy_match("SCHEDULED", uid=10)
        client = _make_offset_client({0: [finished], 1: [scheduled], 2: [_hoy_match("SCHEDULED", uid=11)]})

        with patch("worldcup_bot.bot.handlers.make_client", return_value=client):
            with patch("worldcup_bot.bot.handlers.format_match_with_date", return_value="line"):
                with patch("worldcup_bot.bot.handlers.format_match"):
                    await cmd_hoy(update, context)

        # get_football_day_matches should have been called for offset 0 and 1 only
        call_offsets = [c.args[1] for c in client.get_football_day_matches.call_args_list]
        assert 2 not in call_offsets, "Should have stopped at offset 1, not queried offset 2"
        assert 0 in call_offsets
        assert 1 in call_offsets
