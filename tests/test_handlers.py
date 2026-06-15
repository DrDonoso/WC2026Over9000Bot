"""Lightweight integration tests for Telegram command handlers.

All external dependencies (engine, predictions loader, API client) are mocked
so no network calls or real files are needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.bot.handlers import (
    _MSG_NO_USERNAME,
    _MSG_USER_NOT_FOUND,
    _send_ranking_with_top3_photos,
    cmd_actual,
    cmd_clasificacion,
    cmd_general,
    cmd_lista_aciertos,
    cmd_lista_aciertos_actual,
    cmd_mis_predicciones,
    cmd_participantes,
    cmd_start,
)
from worldcup_bot.api.models import Standing
from worldcup_bot.bot.formatters import participant_photo_url
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
