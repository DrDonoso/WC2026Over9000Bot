"""Lightweight integration tests for Telegram command handlers.

All external dependencies (engine, predictions loader, API client) are mocked
so no network calls or real files are needed.
"""

from __future__ import annotations

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
    cmd_general,
    cmd_lista_aciertos,
    cmd_lista_aciertos_actual,
    cmd_mis_predicciones,
    cmd_participantes,
    cmd_simula_gol,
    cmd_start,
    cmd_tongo,
    cmd_ver_gol_callback,
)
from worldcup_bot.api.models import Match, Standing
from worldcup_bot.bot.formatters import format_user_detail, participant_photo_url
from worldcup_bot.config import Settings
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
        update.message.reply_text.assert_called_once_with("fallback text")

    async def test_fallback_when_requests_raises(self, fake_settings):
        """Network error during URL validation → skip that URL gracefully."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get", side_effect=OSError("network error")):
            await _send_ranking_with_top3_photos(update, context, "fallback text", _TOP5_ROWS, fake_settings)

        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once_with("fallback text")

    async def test_fallback_when_send_media_group_raises(self, fake_settings):
        """If send_media_group itself raises, reply_text is used instead."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot.send_media_group = AsyncMock(side_effect=Exception("Telegram error"))

        with patch("worldcup_bot.bot.handlers._requests.get", return_value=_mock_requests_all_valid()):
            await _send_ranking_with_top3_photos(update, context, "fallback text", _TOP5_ROWS, fake_settings)

        update.message.reply_text.assert_called_once_with("fallback text")

    async def test_empty_rows_sends_text_only(self, fake_settings):
        """Empty rows → reply_text called immediately, no URL checks."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers._requests.get") as mock_get:
            await _send_ranking_with_top3_photos(update, context, "no data", [], fake_settings)

        mock_get.assert_not_called()
        context.bot.send_media_group.assert_not_called()
        update.message.reply_text.assert_called_once_with("no data")

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
        # Full text sent as follow-up
        update.message.reply_text.assert_called_once_with(long_text)

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
    info: dict | None,
) -> MagicMock:
    context = MagicMock()
    context.bot_data = {
        "settings": fake_settings,
        "reddit_scanner": None,
        "goal_clips": ({token: info} if info is not None else {}),
        "vergol_inflight": set(),
        "clip_file_ids": {},
    }
    context.bot.send_message = AsyncMock()
    context.bot.send_video = AsyncMock()
    return context


def _sample_goal_info(status: str = "pending") -> dict:
    return {
        "home_team": "Sweden",
        "away_team": "Tunisia",
        "home_score": 3,
        "away_score": 1,
        "scorer": "Viktor Gyökeres",
        "minute_text": "60",
        "scoring_team": "Sweden",
        "home_tla": "SWE",
        "away_tla": "TUN",
        "status": status,
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
        """Unknown token → query.answer with show_alert; no video or message sent."""
        token = "notpresent"
        update = _make_vergol_update(token)
        context = _make_vergol_context(fake_settings, token, info=None)

        await cmd_ver_gol_callback(update, context)

        update.callback_query.answer.assert_called_once()
        call_kwargs = update.callback_query.answer.call_args[1]
        assert call_kwargs.get("show_alert") is True
        context.bot.send_video.assert_not_called()
        context.bot.send_message.assert_not_called()

    # ── concurrency guard: "sending" ─────────────────────────────────────────

    async def test_already_sending_answers_toast_no_double_send(self, fake_settings):
        """Status 'sending' → quick toast answer, no second download."""
        token = "tok123"
        update = _make_vergol_update(token)
        info = _sample_goal_info(status="sending")
        context = _make_vergol_context(fake_settings, token, info)

        await cmd_ver_gol_callback(update, context)

        update.callback_query.answer.assert_called_once()
        text = update.callback_query.answer.call_args[0][0]
        assert "enviando" in text.lower()
        context.bot.send_video.assert_not_called()

    async def test_already_sent_answers_toast_no_send(self, fake_settings):
        """Status 'sent' → toast answer, no further action."""
        token = "tok456"
        update = _make_vergol_update(token)
        info = _sample_goal_info(status="sent")
        context = _make_vergol_context(fake_settings, token, info)

        await cmd_ver_gol_callback(update, context)

        update.callback_query.answer.assert_called_once()
        text = update.callback_query.answer.call_args[0][0]
        assert "envió" in text.lower()
        context.bot.send_video.assert_not_called()

    # ── clip not found ────────────────────────────────────────────────────────

    async def test_clip_not_found_sends_not_available_message(self, fake_settings):
        """Clip not on Reddit yet → sends 'aún no está disponible', keyboard kept."""
        token = "tok789"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)

        with patch(
            "worldcup_bot.bot.handlers.find_goal_clip", return_value=None
        ):
            with patch(
                "worldcup_bot.bot.handlers.RedditMatchScanner"
            ):
                await cmd_ver_gol_callback(update, context)

        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args[1]["text"]
        assert "disponible" in text.lower()
        # Keyboard must NOT be removed
        update.callback_query.edit_message_reply_markup.assert_not_called()
        # Status reset to pending (allow retry)
        assert info["status"] == "pending"

    # ── download fails ────────────────────────────────────────────────────────

    async def test_download_failure_sends_error_message(self, fake_settings):
        """Download returns None → error message sent, keyboard kept, status pending."""
        token = "tokdl"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)

        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=None)

        with patch(
            "worldcup_bot.bot.handlers.find_goal_clip",
            return_value="https://streamin.link/v/abc",
        ):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                with patch(
                    "worldcup_bot.bot.handlers.MediaDownloader",
                    return_value=fake_downloader,
                ):
                    await cmd_ver_gol_callback(update, context)

        context.bot.send_message.assert_called_once()
        msg_text = context.bot.send_message.call_args[1]["text"]
        assert "descargar" in msg_text.lower() or "❌" in msg_text
        context.bot.send_video.assert_not_called()
        assert info["status"] == "pending"

    # ── happy path ────────────────────────────────────────────────────────────

    async def test_happy_path_sends_video_with_meta_and_removes_keyboard(
        self, tmp_path, fake_settings
    ):
        """Full success: find → download → probe → send_video; keyboard removed; status sent."""
        token = "tokhappy"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)

        fake_video = tmp_path / "clip.mp4"
        fake_video.write_bytes(b"fakevideodata")

        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        fake_meta = {"width": 1920, "height": 1080, "duration": 15}

        # Mock the returned Message object so file_id capture doesn't crash
        fake_sent_msg = MagicMock()
        fake_sent_msg.video = MagicMock()
        fake_sent_msg.video.file_id = "FAKEFID"
        context.bot.send_video = AsyncMock(return_value=fake_sent_msg)

        with patch(
            "worldcup_bot.bot.handlers.find_goal_clip",
            return_value="https://streamin.link/v/abc",
        ):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                with patch(
                    "worldcup_bot.bot.handlers.MediaDownloader",
                    return_value=fake_downloader,
                ):
                    with patch(
                        "worldcup_bot.bot.handlers.compress_if_needed",
                        new=AsyncMock(return_value=fake_video),
                    ):
                        with patch(
                            "worldcup_bot.bot.handlers.probe_video",
                            new=AsyncMock(return_value=fake_meta),
                        ):
                            await cmd_ver_gol_callback(update, context)

        # send_video called with width and height
        context.bot.send_video.assert_called_once()
        send_kwargs = context.bot.send_video.call_args[1]
        assert send_kwargs["width"] == 1920
        assert send_kwargs["height"] == 1080
        assert send_kwargs["duration"] == 15

        # Keyboard removed
        update.callback_query.edit_message_reply_markup.assert_called_once_with(
            reply_markup=None
        )

        # Status set to "sent"
        assert info["status"] == "sent"

    async def test_happy_path_reply_to_message_id(self, tmp_path, fake_settings):
        """send_video reply_to_message_id matches the original goal message id."""
        token = "tokrply"
        update = _make_vergol_update(token, message_id=777, chat_id=88888)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)

        fake_video = tmp_path / "clip.mp4"
        fake_video.write_bytes(b"fakevideodata")

        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        fake_sent_msg = MagicMock()
        fake_sent_msg.video = MagicMock()
        fake_sent_msg.video.file_id = "FAKEFID2"
        context.bot.send_video = AsyncMock(return_value=fake_sent_msg)

        with patch(
            "worldcup_bot.bot.handlers.find_goal_clip",
            return_value="https://streamff.link/v/abc",
        ):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                with patch(
                    "worldcup_bot.bot.handlers.MediaDownloader",
                    return_value=fake_downloader,
                ):
                    with patch(
                        "worldcup_bot.bot.handlers.compress_if_needed",
                        new=AsyncMock(return_value=fake_video),
                    ):
                        with patch(
                            "worldcup_bot.bot.handlers.probe_video",
                            new=AsyncMock(return_value={}),
                        ):
                            await cmd_ver_gol_callback(update, context)

        send_kwargs = context.bot.send_video.call_args[1]
        assert send_kwargs["reply_to_message_id"] == 777
        assert send_kwargs["chat_id"] == 88888

    # ── in-flight guard ───────────────────────────────────────────────────────

    async def test_inflight_guard_answers_immediately_no_download(self, fake_settings):
        """Pre-adding token to vergol_inflight → instant toast, no download or find."""
        token = "tokinflight"
        update = _make_vergol_update(token)
        info = _sample_goal_info(status="pending")
        context = _make_vergol_context(fake_settings, token, info)
        context.bot_data["vergol_inflight"].add(token)

        with patch("worldcup_bot.bot.handlers.find_goal_clip") as mock_find:
            await cmd_ver_gol_callback(update, context)

        update.callback_query.answer.assert_called_once()
        text = update.callback_query.answer.call_args[0][0]
        assert "enviando" in text.lower()
        mock_find.assert_not_called()
        context.bot.send_video.assert_not_called()

    async def test_inflight_token_discarded_after_successful_run(
        self, tmp_path, fake_settings
    ):
        """After a normal successful send, token is removed from vergol_inflight."""
        token = "tokfinallydisc"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)

        fake_video = tmp_path / "clip.mp4"
        fake_video.write_bytes(b"data")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        fake_sent_msg = MagicMock()
        fake_sent_msg.video = MagicMock()
        fake_sent_msg.video.file_id = "DISCFID"
        context.bot.send_video = AsyncMock(return_value=fake_sent_msg)

        with patch("worldcup_bot.bot.handlers.find_goal_clip", return_value="https://x.com/v"):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                with patch("worldcup_bot.bot.handlers.MediaDownloader", return_value=fake_downloader):
                    with patch("worldcup_bot.bot.handlers.compress_if_needed", new=AsyncMock(return_value=fake_video)):
                        with patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})):
                            await cmd_ver_gol_callback(update, context)

        assert token not in context.bot_data["vergol_inflight"]

    # ── file_id cache: per-goal shortcut ─────────────────────────────────────

    async def test_cached_file_id_on_info_resends_instantly_no_download(self, fake_settings):
        """info['file_id'] set → resend via file_id, no find_goal_clip, status sent."""
        token = "tokcachedgoal"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        info["file_id"] = "VID123"
        context = _make_vergol_context(fake_settings, token, info)

        fake_sent_msg = MagicMock()
        fake_sent_msg.video = MagicMock()
        fake_sent_msg.video.file_id = "VID123"
        context.bot.send_video = AsyncMock(return_value=fake_sent_msg)

        with patch("worldcup_bot.bot.handlers.find_goal_clip") as mock_find:
            await cmd_ver_gol_callback(update, context)

        context.bot.send_video.assert_called_once()
        send_kwargs = context.bot.send_video.call_args[1]
        assert send_kwargs["video"] == "VID123"
        mock_find.assert_not_called()
        update.callback_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)
        assert info["status"] == "sent"

    # ── file_id cache: per media_url shortcut ─────────────────────────────────

    async def test_cached_file_id_per_media_url_resends_instantly(self, fake_settings):
        """clip_file_ids[url] set → resend via that file_id, no download, info['file_id'] updated."""
        token = "tokcachedurl"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)
        media_url = "https://streamin.link/v/xyz"
        context.bot_data["clip_file_ids"][media_url] = "VID456"

        fake_sent_msg = MagicMock()
        fake_sent_msg.video = MagicMock()
        fake_sent_msg.video.file_id = "VID456"
        context.bot.send_video = AsyncMock(return_value=fake_sent_msg)

        with patch("worldcup_bot.bot.handlers.find_goal_clip", return_value=media_url):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                with patch("worldcup_bot.bot.handlers.MediaDownloader") as mock_dl:
                    await cmd_ver_gol_callback(update, context)

        context.bot.send_video.assert_called_once()
        send_kwargs = context.bot.send_video.call_args[1]
        assert send_kwargs["video"] == "VID456"
        mock_dl.assert_not_called()
        assert info.get("file_id") == "VID456"
        assert info["status"] == "sent"

    # ── file_id capture on fresh send ─────────────────────────────────────────

    async def test_fresh_send_stores_file_id_in_cache(self, tmp_path, fake_settings):
        """After a fresh download+upload, file_id is stored in clip_file_ids and info."""
        token = "tokfreshfid"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        context = _make_vergol_context(fake_settings, token, info)
        media_url = "https://streamin.link/v/fresh"

        fake_video = tmp_path / "clip.mp4"
        fake_video.write_bytes(b"videodata")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        fake_sent_msg = MagicMock()
        fake_sent_msg.video = MagicMock()
        fake_sent_msg.video.file_id = "NEWID"
        context.bot.send_video = AsyncMock(return_value=fake_sent_msg)

        with patch("worldcup_bot.bot.handlers.find_goal_clip", return_value=media_url):
            with patch("worldcup_bot.bot.handlers.RedditMatchScanner"):
                with patch("worldcup_bot.bot.handlers.MediaDownloader", return_value=fake_downloader):
                    with patch("worldcup_bot.bot.handlers.compress_if_needed", new=AsyncMock(return_value=fake_video)):
                        with patch("worldcup_bot.bot.handlers.probe_video", new=AsyncMock(return_value={})):
                            await cmd_ver_gol_callback(update, context)

        assert context.bot_data["clip_file_ids"][media_url] == "NEWID"
        assert info["file_id"] == "NEWID"
        assert info["status"] == "sent"

    # ── bad file_id fallback ──────────────────────────────────────────────────

    async def test_bad_file_id_evicted_and_status_reset(self, fake_settings):
        """Stale file_id raises on send → evicted from info, status reset to pending."""
        token = "tokbadfid"
        update = _make_vergol_update(token)
        info = _sample_goal_info()
        info["file_id"] = "BAD"
        context = _make_vergol_context(fake_settings, token, info)

        context.bot.send_video = AsyncMock(side_effect=Exception("Bad file id"))

        with patch("worldcup_bot.bot.handlers.find_goal_clip") as mock_find:
            await cmd_ver_gol_callback(update, context)

        assert "file_id" not in info
        assert info["status"] == "pending"
        mock_find.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# cmd_simula_gol
# ══════════════════════════════════════════════════════════════════════════════


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
    async def test_stores_goal_clips_with_correct_shape(self, fake_settings):
        """Fallback path: stores fixed Sweden-Tunisia goal with expected shape."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["goal_clips"] = {}

        with _no_pick():
            await cmd_simula_gol(update, context)

        clips = context.bot_data["goal_clips"]
        assert len(clips) == 1
        token, info = next(iter(clips.items()))

        assert len(token) == 12
        assert all(c in "0123456789abcdef" for c in token)

        assert info["home_team"] == "Sweden"
        assert info["away_team"] == "Tunisia"
        assert info["home_score"] == 3
        assert info["away_score"] == 1
        assert info["scorer"] == "Viktor Gyökeres"
        assert info["minute_text"] == "60"
        assert info["scoring_team"] == "Sweden"
        assert info["home_tla"] == "SWE"
        assert info["away_tla"] == "TUN"
        assert info["status"] == "pending"

    async def test_reply_text_called_with_keyboard(self, fake_settings):
        """cmd_simula_gol sends ⏳ first, then the goal notification with an InlineKeyboardMarkup."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["goal_clips"] = {}

        with _no_pick():
            await cmd_simula_gol(update, context)

        # At least 2 calls: ⏳ message + goal notification
        assert update.message.reply_text.await_count >= 2

        # Last call carries the keyboard
        last_kwargs = update.message.reply_text.call_args[1]
        keyboard = last_kwargs["reply_markup"]
        assert keyboard is not None

        clips = context.bot_data["goal_clips"]
        token = next(iter(clips))
        button = keyboard.inline_keyboard[0][0]
        assert button.callback_data == f"vergol:{token}"

    async def test_token_matches_goal_token_of_sim_key(self, fake_settings):
        """Fallback token is sha1[:12] of the fixed Sweden-Tunisia simulation key."""
        expected_token = _goal_token("SIM:sweden-tunisia-3-1-60-gyokeres")

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["goal_clips"] = {}

        with _no_pick():
            await cmd_simula_gol(update, context)

        clips = context.bot_data["goal_clips"]
        assert expected_token in clips

    async def test_initialises_goal_clips_when_absent(self, fake_settings):
        """cmd_simula_gol creates bot_data['goal_clips'] if it doesn't exist yet."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data.pop("goal_clips", None)

        with _no_pick():
            await cmd_simula_gol(update, context)

        assert "goal_clips" in context.bot_data
        assert len(context.bot_data["goal_clips"]) == 1

    async def test_reply_text_contains_simulation_marker(self, fake_settings):
        """The goal reply text contains a marker so users know it's a simulation."""
        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["goal_clips"] = {}

        with _no_pick():
            await cmd_simula_gol(update, context)

        # last call is the goal notification
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
        context.bot_data["goal_clips"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            await cmd_simula_gol(update, context)

        clips = context.bot_data["goal_clips"]
        assert len(clips) == 1
        token, info = next(iter(clips.items()))

        assert len(token) == 12
        assert info["home_team"] == "France"
        assert info["away_team"] == "Morocco"
        assert info["home_tla"] == "FRA"
        assert info["away_tla"] == "MAR"
        assert info["scorer"] in ("Kylian Mbappé", "Antoine Griezmann")
        assert info["status"] == "pending"

    async def test_random_pick_keyboard_callback_data(self, fake_settings):
        """Random path: button callback_data is vergol:<token> matching the stored key."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = [_make_finished_match()]

        fake_scanner = MagicMock()
        fake_scanner.find_match_thread.return_value = (
            "/r/soccer/comments/post99/match_thread_france_vs_morocco/"
        )
        fake_scanner.get_thread_body.return_value = _CANNED_MATCH_SELFTEXT

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["goal_clips"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            await cmd_simula_gol(update, context)

        clips = context.bot_data["goal_clips"]
        token = next(iter(clips))
        last_kwargs = update.message.reply_text.call_args[1]
        keyboard = last_kwargs["reply_markup"]
        assert keyboard is not None
        button = keyboard.inline_keyboard[0][0]
        assert button.callback_data == f"vergol:{token}"

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
        context.bot_data["goal_clips"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["goal_clips"].values()))
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
        context.bot_data["goal_clips"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["goal_clips"].values()))
        assert info["home_team"] == "Sweden"
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
        context.bot_data["goal_clips"] = {}
        context.bot_data["reddit_scanner"] = fake_scanner

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["goal_clips"].values()))
        assert info["home_team"] == "Sweden"
        assert info["scorer"] == "Viktor Gyökeres"

    async def test_falls_back_when_no_finished_matches(self, fake_settings):
        """No finished matches → fallback to fixed Sweden-Tunisia goal."""
        fake_client = MagicMock()
        fake_client.get_all_matches.return_value = []  # no finished matches

        update = _make_update()
        context = _make_context(fake_settings)
        context.bot_data["goal_clips"] = {}

        with patch("worldcup_bot.bot.handlers.make_client", return_value=fake_client):
            await cmd_simula_gol(update, context)

        info = next(iter(context.bot_data["goal_clips"].values()))
        assert info["home_team"] == "Sweden"
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
    async def test_sanchez_path_when_random_below_threshold(self, fake_settings):
        """random.random() < 1/3 → reply is exactly 'Sanchez ens roba'."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.1
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Sanchez ens roba"

    async def test_frases_path_when_random_above_threshold(self, fake_settings):
        """random.random() >= 1/3 → reply comes from FRASES (not Sanchez)."""
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

    async def test_frases_path_does_not_use_sanchez_constant(self, fake_settings):
        """When above threshold, random.choice is called (not the Sanchez constant)."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = "La culpa es de Suñé"
            await cmd_tongo(update, context)

        mock_random.choice.assert_called_once()

    async def test_argentino_female_phrase_for_laura(self, fake_settings):
        """Laura → female argentino phrase is in the candidate pool and sent."""
        from worldcup_bot.data.tongo import frase_argentino

        update = _make_update()
        update.effective_user.first_name = "Laura"
        context = _make_context(fake_settings)
        expected = frase_argentino("f")

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = expected
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == expected
        pool = mock_random.choice.call_args[0][0]
        assert expected in pool

    async def test_argentino_male_phrase_for_david(self, fake_settings):
        """David → male argentino phrase is in the candidate pool and sent."""
        from worldcup_bot.data.tongo import frase_argentino

        update = _make_update()
        update.effective_user.first_name = "David"
        context = _make_context(fake_settings)
        expected = frase_argentino("m")

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = expected
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == expected
        pool = mock_random.choice.call_args[0][0]
        assert expected in pool


# ══════════════════════════════════════════════════════════════════════════════
# cmd_tongo — GIF / animation paths
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdTongoGifs:
    """Tests for the GIF branch of cmd_tongo."""

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
