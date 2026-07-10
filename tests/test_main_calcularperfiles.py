"""Tests for cmd_calcularperfiles, _run_profile_update, and profile_update_job regression.

All three live in worldcup_bot.__main__.  No network calls, no real files needed.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.config import Settings

# ── Settings / context helpers ────────────────────────────────────────────────


def _settings_profiles_on(state_dir: str = ".") -> Settings:
    """Settings where picante_profiles_enabled(settings) returns True."""
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        openai_api_key="sk-test",
        openai_base_url="http://localhost/v1",
        openai_model="gpt-4",
        chat_picante_enabled=True,
        picante_profiles_enabled=True,
        state_dir=state_dir,
    )


def _settings_profiles_off() -> Settings:
    """Settings where picante_profiles_enabled(settings) returns False (default)."""
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
    )


def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_ctx(settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# cmd_calcularperfiles
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdCalcularPerfiles:
    """Tests for the hidden /calcularperfiles command in worldcup_bot.__main__."""

    # ── feature disabled ──────────────────────────────────────────────────────

    async def test_feature_off_replies_disabled_message(self):
        """Feature OFF → reply mentions PICANTE_PROFILES_ENABLED; _run_profile_update not called."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_off())

        with patch.object(main_mod, "_run_profile_update") as mock_helper:
            await main_mod.cmd_calcularperfiles(update, ctx)

        mock_helper.assert_not_called()
        text = update.message.reply_text.call_args[0][0]
        assert "PICANTE_PROFILES_ENABLED" in text
        assert "No hay nada que calcular" in text

    async def test_feature_off_full_reply_text(self):
        """Feature OFF exact reply: contains the full off-message substring."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_off())

        with patch.object(main_mod, "_run_profile_update"):
            await main_mod.cmd_calcularperfiles(update, ctx)

        text = update.message.reply_text.call_args[0][0]
        assert "La función de perfiles está desactivada" in text

    # ── feature ON, new messages (N > 0) ──────────────────────────────────────

    async def test_feature_on_n_gt_0_sends_progress_message(self):
        """Feature ON, helper returns N>0 → first reply contains '⏳ Calculando perfiles…'."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(main_mod, "_run_profile_update", new=AsyncMock(return_value=3)):
            await main_mod.cmd_calcularperfiles(update, ctx)

        all_calls = [c.args[0] for c in update.message.reply_text.await_args_list]
        assert any("⏳ Calculando perfiles" in t for t in all_calls)

    async def test_feature_on_n_gt_0_sends_success_with_count(self):
        """Feature ON, helper returns 3 → reply contains '✅ Perfiles actualizados: 3 usuario(s) procesado(s).'"""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(main_mod, "_run_profile_update", new=AsyncMock(return_value=3)):
            await main_mod.cmd_calcularperfiles(update, ctx)

        all_calls = [c.args[0] for c in update.message.reply_text.await_args_list]
        assert any("✅ Perfiles actualizados: 3 usuario(s) procesado(s)." in t for t in all_calls)

    async def test_feature_on_n_gt_0_two_replies_sent(self):
        """Feature ON, N>0 → exactly 2 replies (progress + result)."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(main_mod, "_run_profile_update", new=AsyncMock(return_value=7)):
            await main_mod.cmd_calcularperfiles(update, ctx)

        assert update.message.reply_text.await_count == 2

    # ── feature ON, no new messages (N == 0) ──────────────────────────────────

    async def test_feature_on_zero_sends_no_new_messages_reply(self):
        """Feature ON, helper returns 0 → reply contains 'ℹ️ No hay mensajes nuevos…'."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(main_mod, "_run_profile_update", new=AsyncMock(return_value=0)):
            await main_mod.cmd_calcularperfiles(update, ctx)

        all_calls = [c.args[0] for c in update.message.reply_text.await_args_list]
        assert any(
            "ℹ️ No hay mensajes nuevos desde la última actualización; perfiles sin cambios." in t
            for t in all_calls
        )

    async def test_feature_on_zero_sends_progress_before_no_new_msg(self):
        """Feature ON, 0 → still sends '⏳ Calculando perfiles…' before the ℹ️ reply."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(main_mod, "_run_profile_update", new=AsyncMock(return_value=0)):
            await main_mod.cmd_calcularperfiles(update, ctx)

        all_calls = [c.args[0] for c in update.message.reply_text.await_args_list]
        assert any("⏳ Calculando perfiles" in t for t in all_calls)

    # ── helper raises ──────────────────────────────────────────────────────────

    async def test_helper_raises_sends_friendly_error_reply(self):
        """Helper raises → friendly '💥 Error calculando los perfiles, revisa los logs.' reply sent."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(
            main_mod,
            "_run_profile_update",
            new=AsyncMock(side_effect=RuntimeError("AI borked")),
        ):
            await main_mod.cmd_calcularperfiles(update, ctx)  # must not raise

        all_calls = [c.args[0] for c in update.message.reply_text.await_args_list]
        assert any("💥 Error calculando los perfiles, revisa los logs." in t for t in all_calls)

    async def test_helper_raises_does_not_propagate(self):
        """Helper raises → exception is swallowed; cmd_calcularperfiles returns normally."""
        import worldcup_bot.__main__ as main_mod

        update = _make_update()
        ctx = _make_ctx(_settings_profiles_on())

        with patch.object(
            main_mod,
            "_run_profile_update",
            new=AsyncMock(side_effect=Exception("crash")),
        ):
            # Must complete without raising
            await main_mod.cmd_calcularperfiles(update, ctx)

    # ── hidden command guard ──────────────────────────────────────────────────

    def test_calcularperfiles_not_in_help_commands(self):
        """'calcularperfiles' does NOT appear in _HELP_COMMANDS (hidden command)."""
        from worldcup_bot.bot.handlers import _HELP_COMMANDS

        assert "calcularperfiles" not in _HELP_COMMANDS.lower()

    def test_calcularperfiles_registered_in_main(self):
        """cmd_calcularperfiles IS wired up as a CommandHandler in __main__ (sanity)."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod)
        assert 'CommandHandler("calcularperfiles", cmd_calcularperfiles)' in src


# ══════════════════════════════════════════════════════════════════════════════
# _run_profile_update — shared helper
# ══════════════════════════════════════════════════════════════════════════════


class TestRunProfileUpdateHelper:
    """Unit tests for _run_profile_update, the core AI-profile-update helper."""

    # ── no new messages → 0, no AI call ──────────────────────────────────────

    async def test_no_messages_returns_0(self, tmp_path):
        """No messages since last_run → returns 0."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        ctx.bot_data["profile_ai_client"] = MagicMock()

        with (
            patch("worldcup_bot.chat.timeline_store.load_last_run", return_value=None),
            patch("worldcup_bot.chat.timeline_store.load_since", return_value=[]),
            patch("worldcup_bot.chat.timeline_store.save_last_run"),
            patch(
                "worldcup_bot.chat.profile_updater.update_profiles_from_conversation"
            ) as mock_ai,
        ):
            result = await main_mod._run_profile_update(ctx)

        assert result == 0
        mock_ai.assert_not_called()

    async def test_no_messages_ai_not_called(self, tmp_path):
        """No messages → update_profiles_from_conversation is never called (no AI spend)."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        ctx.bot_data["profile_ai_client"] = MagicMock()

        with (
            patch("worldcup_bot.chat.timeline_store.load_last_run", return_value=None),
            patch("worldcup_bot.chat.timeline_store.load_since", return_value=[]),
            patch("worldcup_bot.chat.timeline_store.save_last_run"),
            patch(
                "worldcup_bot.chat.profile_updater.update_profiles_from_conversation",
                new=AsyncMock(),
            ) as mock_ai,
        ):
            await main_mod._run_profile_update(ctx)

        mock_ai.assert_not_called()

    async def test_no_messages_last_run_advanced(self, tmp_path):
        """No messages → save_last_run is still called (advances the watermark)."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        ctx.bot_data["profile_ai_client"] = MagicMock()

        with (
            patch("worldcup_bot.chat.timeline_store.load_last_run", return_value=None),
            patch("worldcup_bot.chat.timeline_store.load_since", return_value=[]),
            patch("worldcup_bot.chat.timeline_store.save_last_run") as mock_save_run,
            patch("worldcup_bot.chat.profile_updater.update_profiles_from_conversation"),
        ):
            await main_mod._run_profile_update(ctx)

        mock_save_run.assert_called_once()

    # ── with messages → AI called, correct count returned ────────────────────

    async def test_with_messages_calls_ai(self, tmp_path):
        """Messages present → update_profiles_from_conversation is called once."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        ctx.bot_data["profile_ai_client"] = MagicMock()

        messages = [
            {"username": "ana", "text": "hola"},
            {"username": "bob", "text": "adiós"},
        ]

        with (
            patch("worldcup_bot.chat.timeline_store.load_last_run", return_value=None),
            patch("worldcup_bot.chat.timeline_store.load_since", return_value=messages),
            patch("worldcup_bot.chat.timeline_store.save_last_run"),
            patch("worldcup_bot.chat.profiles.load_profiles", return_value={}),
            patch("worldcup_bot.chat.profiles.save_profiles"),
            patch(
                "worldcup_bot.chat.profile_updater.update_profiles_from_conversation",
                new=AsyncMock(return_value={}),
            ) as mock_ai,
        ):
            await main_mod._run_profile_update(ctx)

        mock_ai.assert_called_once()

    async def test_with_messages_returns_distinct_participant_count(self, tmp_path):
        """Returns count of distinct usernames (not message count)."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        ctx.bot_data["profile_ai_client"] = MagicMock()

        messages = [
            {"username": "ana", "text": "hola"},
            {"username": "bob", "text": "ciao"},
            {"username": "ana", "text": "adios"},  # ana again — counts once
        ]

        with (
            patch("worldcup_bot.chat.timeline_store.load_last_run", return_value=None),
            patch("worldcup_bot.chat.timeline_store.load_since", return_value=messages),
            patch("worldcup_bot.chat.timeline_store.save_last_run"),
            patch("worldcup_bot.chat.profiles.load_profiles", return_value={}),
            patch("worldcup_bot.chat.profiles.save_profiles"),
            patch(
                "worldcup_bot.chat.profile_updater.update_profiles_from_conversation",
                new=AsyncMock(return_value={}),
            ),
        ):
            result = await main_mod._run_profile_update(ctx)

        assert result == 2  # ana + bob, not 3

    async def test_messages_without_username_excluded_from_count(self, tmp_path):
        """Messages with missing/empty username don't count toward participant total."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        ctx.bot_data["profile_ai_client"] = MagicMock()

        messages = [
            {"username": "ana", "text": "hola"},
            {"text": "anonymous message"},  # no username key
            {"username": "", "text": "empty username"},
        ]

        with (
            patch("worldcup_bot.chat.timeline_store.load_last_run", return_value=None),
            patch("worldcup_bot.chat.timeline_store.load_since", return_value=messages),
            patch("worldcup_bot.chat.timeline_store.save_last_run"),
            patch("worldcup_bot.chat.profiles.load_profiles", return_value={}),
            patch("worldcup_bot.chat.profiles.save_profiles"),
            patch(
                "worldcup_bot.chat.profile_updater.update_profiles_from_conversation",
                new=AsyncMock(return_value={}),
            ),
        ):
            result = await main_mod._run_profile_update(ctx)

        assert result == 1  # only "ana"

    # ── error propagation (raises, unlike the job) ────────────────────────────

    async def test_no_profile_ai_client_raises_runtime_error(self, tmp_path):
        """No profile_ai_client in bot_data → raises RuntimeError (not swallowed)."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on(state_dir=str(tmp_path)))
        # profile_ai_client intentionally absent

        with pytest.raises(RuntimeError, match="no profile_ai_client"):
            await main_mod._run_profile_update(ctx)


# ══════════════════════════════════════════════════════════════════════════════
# profile_update_job — regression: best-effort wrapper still swallows errors
# ══════════════════════════════════════════════════════════════════════════════


class TestProfileUpdateJobRegression:
    """profile_update_job must remain best-effort (swallows errors) after refactor."""

    async def test_job_swallows_run_helper_exception(self):
        """_run_profile_update raising → profile_update_job does NOT propagate."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on())
        ctx.bot_data["profile_ai_client"] = MagicMock()

        with patch.object(
            main_mod,
            "_run_profile_update",
            new=AsyncMock(side_effect=RuntimeError("simulated crash")),
        ):
            await main_mod.profile_update_job(ctx)  # must not raise

    async def test_job_swallows_arbitrary_exception(self):
        """Any exception from _run_profile_update is swallowed by the job."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on())
        ctx.bot_data["profile_ai_client"] = MagicMock()

        with patch.object(
            main_mod,
            "_run_profile_update",
            new=AsyncMock(side_effect=ValueError("unexpected")),
        ):
            await main_mod.profile_update_job(ctx)  # must not raise

    async def test_job_skips_when_feature_off(self):
        """Feature OFF → job returns without calling _run_profile_update."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_off())

        with patch.object(main_mod, "_run_profile_update") as mock_helper:
            await main_mod.profile_update_job(ctx)

        mock_helper.assert_not_called()

    async def test_job_skips_when_no_profile_ai_client(self):
        """No profile_ai_client in bot_data → job logs warning, skips helper."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on())
        # profile_ai_client intentionally absent (returns None via dict.get)

        with patch.object(main_mod, "_run_profile_update") as mock_helper:
            await main_mod.profile_update_job(ctx)

        mock_helper.assert_not_called()

    async def test_job_calls_helper_when_feature_on_and_ai_configured(self):
        """Feature ON + ai_client present → _run_profile_update is awaited."""
        import worldcup_bot.__main__ as main_mod

        ctx = _make_ctx(_settings_profiles_on())
        ctx.bot_data["profile_ai_client"] = MagicMock()

        with patch.object(
            main_mod, "_run_profile_update", new=AsyncMock(return_value=0)
        ) as mock_helper:
            await main_mod.profile_update_job(ctx)

        mock_helper.assert_awaited_once()
