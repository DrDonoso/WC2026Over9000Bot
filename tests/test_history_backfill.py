"""Tests for history_backfill_job (startup + daily refresh) and scheduling wiring."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.config import Settings


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        state_dir=str(tmp_path),
        predictions_path=str(tmp_path / "predictions.yml"),
    )


def _make_context(settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    return ctx


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


# ══════════════════════════════════════════════════════════════════════════════
# history_backfill_job — behaviour
# ══════════════════════════════════════════════════════════════════════════════


class TestHistoryBackfillJob:
    async def test_calls_ensure_history_when_predictions_present(self, tmp_path):
        """Job calls ensure_history (via asyncio.to_thread) when predictions exist."""
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)

        fake_history = {"2026-06-13": {"alice": {"pos": 1, "pts": 3.0, "name": "Alice"}}}

        with patch("worldcup_bot.__main__.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.__main__.make_client"):
                with patch(
                    "worldcup_bot.__main__.ensure_history",
                    return_value=fake_history,
                ) as mock_ensure:
                    await main_mod.history_backfill_job(ctx)

        mock_ensure.assert_called_once()

    async def test_skips_when_no_predictions(self, tmp_path):
        """Job exits early (no ensure_history call) when predictions has no participants."""
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)

        with patch("worldcup_bot.__main__.pred_loader.load", return_value={}):
            with patch("worldcup_bot.__main__.ensure_history") as mock_ensure:
                await main_mod.history_backfill_job(ctx)

        mock_ensure.assert_not_called()

    async def test_api_error_does_not_raise(self, tmp_path):
        """An exception inside ensure_history must be swallowed — job never raises."""
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)

        with patch("worldcup_bot.__main__.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.__main__.make_client"):
                with patch(
                    "worldcup_bot.__main__.ensure_history",
                    side_effect=RuntimeError("API down"),
                ):
                    # Must NOT raise
                    await main_mod.history_backfill_job(ctx)

    async def test_predictions_load_error_does_not_raise(self, tmp_path):
        """If loading predictions itself raises, the job swallows it gracefully."""
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)

        with patch(
            "worldcup_bot.__main__.pred_loader.load",
            side_effect=FileNotFoundError("no file"),
        ):
            await main_mod.history_backfill_job(ctx)  # must not raise

    async def test_logs_jornada_count_on_success(self, tmp_path, caplog):
        """On success the job logs the number of jornadas at INFO level."""
        import logging
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path)
        ctx = _make_context(settings)

        fake_history = {
            "2026-06-13": {},
            "2026-06-14": {},
        }

        with patch("worldcup_bot.__main__.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.__main__.make_client"):
                with patch("worldcup_bot.__main__.ensure_history", return_value=fake_history):
                    with caplog.at_level(logging.INFO, logger="worldcup_bot.__main__"):
                        await main_mod.history_backfill_job(ctx)

        assert any("2" in r.message and "jornada" in r.message for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════════════
# Scheduling — run_once (startup) + run_daily wired in main()
# ══════════════════════════════════════════════════════════════════════════════


class TestHistoryBackfillScheduling:
    def test_main_schedules_run_once_at_startup(self):
        """main() source contains run_once(history_backfill_job, when=15)."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert "history_backfill_job" in src
        assert "run_once" in src
        # when=15 appears in the scheduling block
        assert "when=15" in src

    def test_main_schedules_run_daily_for_history(self):
        """main() source contains run_daily(history_backfill_job, ...)."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert "run_daily" in src
        assert "history_backfill_job" in src

    def test_main_logs_porra_history_refresh_enabled(self):
        """main() source logs the history-refresh startup message."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert "history" in src.lower()
        assert "09:05" in src or "minute=5" in src

    def test_history_backfill_job_importable(self):
        """history_backfill_job is a top-level importable coroutine in __main__."""
        from worldcup_bot.__main__ import history_backfill_job
        import asyncio

        assert callable(history_backfill_job)
        assert asyncio.iscoroutinefunction(history_backfill_job)
