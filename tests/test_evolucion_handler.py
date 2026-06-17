"""Tests for cmd_evolucion handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.bot.handlers import cmd_evolucion, cmd_start
from worldcup_bot.config import Settings


# ── fixtures / helpers ─────────────────────────────────────────────────────────


def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    update.effective_user.username = "testuser"
    return update


def _make_context(settings: Settings) -> MagicMock:
    context = MagicMock()
    context.bot_data = {"settings": settings}
    context.bot.send_photo = AsyncMock()
    return context


@pytest.fixture
def fake_settings(tmp_path):
    return Settings(
        telegram_bot_token="fake-token",
        football_data_api_key="fake-api-key",
        predictions_path="fake_predictions.yml",
        state_dir=str(tmp_path),
    )


_FAKE_PREDICTIONS = {
    "participants": {
        "alice": {
            "display_name": "Alice",
            "base_score": 0.0,
            "groups": {},
            "knockout": {},
        }
    }
}

_FAKE_HISTORY = {
    "2026-06-13": {"alice": {"pos": 1, "pts": 3.0, "name": "Alice"}},
    "2026-06-14": {"alice": {"pos": 1, "pts": 5.0, "name": "Alice"}},
}


# ══════════════════════════════════════════════════════════════════════════════
# /start help
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdStartEvolucion:
    async def test_evolucion_in_start_help(self, fake_settings):
        """cmd_start help text must include /evolucion."""
        update = _make_update()
        context = _make_context(fake_settings)
        await cmd_start(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "/evolucion" in text


# ══════════════════════════════════════════════════════════════════════════════
# cmd_evolucion — behaviour
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdEvolucion:
    async def test_no_predictions_replies_error(self, fake_settings):
        """No predictions file → replies with no-predictions message."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value={}):
            await cmd_evolucion(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "predicciones" in text.lower() or "predictions" in text.lower() or "no se han" in text

    async def test_empty_history_replies_no_matches(self, fake_settings):
        """Empty history → replies with 'no hay partidos' message."""
        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.make_client"):
                with patch(
                    "worldcup_bot.bot.handlers.ensure_history",
                    return_value={},
                ):
                    await cmd_evolucion(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "no hay" in text.lower() or "aún" in text.lower()

    async def test_sends_photo_on_success(self, fake_settings, tmp_path):
        """Happy path: history computed, PNG rendered, send_photo called."""
        update = _make_update()
        context = _make_context(fake_settings)

        def fake_render(history, out_path):
            # Write a minimal PNG header so open() succeeds
            with open(out_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            return out_path

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.make_client"):
                with patch(
                    "worldcup_bot.bot.handlers.ensure_history",
                    return_value=_FAKE_HISTORY,
                ):
                    with patch(
                        "worldcup_bot.bot.handlers.render_evolution_png",
                        side_effect=fake_render,
                    ):
                        await cmd_evolucion(update, context)

        context.bot.send_photo.assert_called_once()
        call_kwargs = context.bot.send_photo.call_args
        assert call_kwargs.kwargs.get("caption") == "📈 Evolución de la porra"
        assert call_kwargs.kwargs.get("chat_id") == 12345

    async def test_api_error_replies_friendly_message(self, fake_settings):
        """FootballAPIError → friendly Spanish error message."""
        from worldcup_bot.api.client import FootballAPIError

        update = _make_update()
        context = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.make_client"):
                with patch(
                    "worldcup_bot.bot.handlers.ensure_history",
                    side_effect=FootballAPIError(429, "Rate limit"),
                ):
                    await cmd_evolucion(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "⚠️" in text or "❌" in text

    async def test_render_exception_replies_error(self, fake_settings, tmp_path):
        """If render_evolution_png fails, a friendly error is sent."""
        update = _make_update()
        context = _make_context(fake_settings)
        fake_png = tmp_path / "evolucion.png"
        fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.make_client"):
                with patch(
                    "worldcup_bot.bot.handlers.ensure_history",
                    return_value=_FAKE_HISTORY,
                ):
                    with patch(
                        "worldcup_bot.bot.handlers.render_evolution_png",
                        side_effect=RuntimeError("render failed"),
                    ):
                        await cmd_evolucion(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "❌" in text

    async def test_importable_functions(self):
        """ensure_history and render_evolution_png are directly importable."""
        from worldcup_bot.porra.history import ensure_history as _eh
        from worldcup_bot.porra.chart import render_evolution_png as _rep
        assert callable(_eh)
        assert callable(_rep)


# ══════════════════════════════════════════════════════════════════════════════
# build_app registration check
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdEvolucionRegistered:
    def test_evolucion_handler_in_build_app(self, fake_settings):
        """Verify CommandHandler('evolucion', cmd_evolucion) is in __main__.build_app."""
        import worldcup_bot.__main__ as main_mod
        # Inspect the source of build_app for the evolucion registration
        import inspect
        src = inspect.getsource(main_mod.build_app)
        assert "evolucion" in src
        assert "cmd_evolucion" in src
