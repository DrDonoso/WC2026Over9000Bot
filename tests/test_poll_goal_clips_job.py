"""Tests for poll_goal_clips_job — background clip search, download, keyboard edit."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.config import Settings


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="tok",
        football_data_api_key="key",
        telegram_group_id="-1001234567",
        state_dir=str(tmp_path),
    )


def _make_context(settings: Settings, clip_data: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "reddit_scanner": MagicMock(),
        "clip_store": clip_data,
    }
    ctx.bot.edit_message_reply_markup = AsyncMock()
    return ctx


def _searching_entry(attempts: int = 0, created_at: str | None = None) -> dict:
    return {
        "chat_id": -100999,
        "message_id": 42,
        "home_name": "France",
        "away_name": "Senegal",
        "home_tla": "FRA",
        "away_tla": "SEN",
        "home_score": 1,
        "away_score": 0,
        "scoring_team": "France",
        "scorer": "Mbappé",
        "minute": "66",
        "status": "searching",
        "clip_path": None,
        "file_id": None,
        "attempts": attempts,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }


from worldcup_bot.__main__ import poll_goal_clips_job, _MAX_CLIP_ATTEMPTS


# ══════════════════════════════════════════════════════════════════════════════
# Attempts tracking
# ══════════════════════════════════════════════════════════════════════════════


class TestAttemptsTracking:
    @pytest.mark.asyncio
    async def test_attempts_incremented_when_no_clip_found(self, tmp_path):
        """Each tick without a clip increments attempts by 1."""
        settings = _make_settings(tmp_path)
        token = "abc123def456"
        entry = _searching_entry(attempts=2)
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        with (
            patch("worldcup_bot.__main__.find_goal_clip", return_value=None),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert entry["attempts"] == 3
        assert entry["status"] == "searching"

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded_sets_timeout(self, tmp_path):
        """When attempts > _MAX_CLIP_ATTEMPTS, status becomes 'timeout'."""
        settings = _make_settings(tmp_path)
        token = "timeouttok"
        entry = _searching_entry(attempts=_MAX_CLIP_ATTEMPTS)
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        with (
            patch("worldcup_bot.__main__.find_goal_clip") as mock_find,
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert entry["status"] == "timeout"
        mock_find.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_searching_entries_returns_early(self, tmp_path):
        """If all entries are 'ready' or 'timeout', find_goal_clip is never called."""
        settings = _make_settings(tmp_path)
        clip_data = {
            "tok1": {**_searching_entry(), "status": "ready"},
            "tok2": {**_searching_entry(), "status": "timeout"},
        }
        ctx = _make_context(settings, clip_data)

        with (
            patch("worldcup_bot.__main__.find_goal_clip") as mock_find,
            patch("worldcup_bot.__main__.save_clips") as mock_save,
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        mock_find.assert_not_called()
        mock_save.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Happy path — clip found, downloaded, message edited
# ══════════════════════════════════════════════════════════════════════════════


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_clip_found_download_status_ready_edit_called(self, tmp_path):
        """Found URL → download → move to clips dir → status 'ready' + keyboard edit."""
        settings = _make_settings(tmp_path)
        token = "happytok1234"
        entry = _searching_entry()
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        fake_video = tmp_path / "vergol_test.mp4"
        fake_video.write_bytes(b"fakevideodata")

        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        with (
            patch(
                "worldcup_bot.__main__.find_goal_clip",
                return_value="https://streamff.link/v/abc",
            ),
            patch(
                "worldcup_bot.__main__.MediaDownloader",
                return_value=fake_downloader,
            ),
            patch(
                "worldcup_bot.__main__.compress_if_needed",
                new=AsyncMock(return_value=fake_video),
            ),
            patch("worldcup_bot.__main__.shutil.move"),
            patch("worldcup_bot.__main__.save_clips") as mock_save,
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert entry["status"] == "ready"
        expected_clip = str(tmp_path / "clips" / f"{token}.mp4")
        assert entry["clip_path"] == expected_clip
        ctx.bot.edit_message_reply_markup.assert_called_once()
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_message_called_with_correct_chat_message(self, tmp_path):
        """edit_message_reply_markup uses chat_id and message_id from the entry."""
        settings = _make_settings(tmp_path)
        token = "edittok5678"
        entry = _searching_entry()
        entry["chat_id"] = -100999
        entry["message_id"] = 123
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        fake_video = tmp_path / "v.mp4"
        fake_video.write_bytes(b"data")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        with (
            patch(
                "worldcup_bot.__main__.find_goal_clip",
                return_value="https://streamff.link/v/x",
            ),
            patch("worldcup_bot.__main__.MediaDownloader", return_value=fake_downloader),
            patch(
                "worldcup_bot.__main__.compress_if_needed",
                new=AsyncMock(return_value=fake_video),
            ),
            patch("worldcup_bot.__main__.shutil.move"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        call_kwargs = ctx.bot.edit_message_reply_markup.call_args.kwargs
        assert call_kwargs["chat_id"] == -100999
        assert call_kwargs["message_id"] == 123

    @pytest.mark.asyncio
    async def test_edit_fails_but_status_still_ready(self, tmp_path):
        """If edit_message_reply_markup raises, status is still set to 'ready'."""
        settings = _make_settings(tmp_path)
        token = "editfailtok"
        entry = _searching_entry()
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)
        ctx.bot.edit_message_reply_markup = AsyncMock(side_effect=Exception("TG error"))

        fake_video = tmp_path / "v.mp4"
        fake_video.write_bytes(b"data")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        with (
            patch(
                "worldcup_bot.__main__.find_goal_clip",
                return_value="https://streamff.link/v/x",
            ),
            patch("worldcup_bot.__main__.MediaDownloader", return_value=fake_downloader),
            patch(
                "worldcup_bot.__main__.compress_if_needed",
                new=AsyncMock(return_value=fake_video),
            ),
            patch("worldcup_bot.__main__.shutil.move"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert entry["status"] == "ready"

    @pytest.mark.asyncio
    async def test_download_returns_none_does_not_set_ready(self, tmp_path):
        """If download fails (returns None), status stays 'searching'."""
        settings = _make_settings(tmp_path)
        token = "dlnone"
        entry = _searching_entry()
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=None)

        with (
            patch(
                "worldcup_bot.__main__.find_goal_clip",
                return_value="https://streamff.link/v/abc",
            ),
            patch("worldcup_bot.__main__.MediaDownloader", return_value=fake_downloader),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert entry["status"] == "searching"
        ctx.bot.edit_message_reply_markup.assert_not_called()

    @pytest.mark.asyncio
    async def test_video_too_large_sets_timeout(self, tmp_path):
        """VideoTooLargeError during compression → status 'timeout'."""
        from worldcup_bot.reddit.video import VideoTooLargeError

        settings = _make_settings(tmp_path)
        token = "bigtok"
        entry = _searching_entry()
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        fake_video = tmp_path / "v.mp4"
        fake_video.write_bytes(b"data")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        with (
            patch(
                "worldcup_bot.__main__.find_goal_clip",
                return_value="https://streamff.link/v/x",
            ),
            patch("worldcup_bot.__main__.MediaDownloader", return_value=fake_downloader),
            patch(
                "worldcup_bot.__main__.compress_if_needed",
                new=AsyncMock(side_effect=VideoTooLargeError("too big")),
            ),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert entry["status"] == "timeout"
        ctx.bot.edit_message_reply_markup.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Per-entry isolation
# ══════════════════════════════════════════════════════════════════════════════


class TestPerEntryIsolation:
    @pytest.mark.asyncio
    async def test_error_in_one_entry_does_not_affect_others(self, tmp_path):
        """Exception in one entry's processing must not prevent other entries from running."""
        settings = _make_settings(tmp_path)
        entry_bad = _searching_entry(attempts=0)
        entry_good = _searching_entry(attempts=0)
        clip_data = {"bad": entry_bad, "good": entry_good}
        ctx = _make_context(settings, clip_data)

        call_count = 0

        def side_effect_find(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated error for first entry")
            return None  # second entry: not found yet

        with (
            patch(
                "worldcup_bot.__main__.find_goal_clip",
                side_effect=side_effect_find,
            ),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)  # must not raise

        # Good entry still got its attempts incremented (processed after bad)
        assert entry_good["attempts"] == 1

    @pytest.mark.asyncio
    async def test_save_clips_called_even_with_multiple_entries(self, tmp_path):
        """save_clips is called once at the end regardless of per-entry failures."""
        settings = _make_settings(tmp_path)
        clip_data = {
            "a": _searching_entry(),
            "b": _searching_entry(),
        }
        ctx = _make_context(settings, clip_data)

        with (
            patch("worldcup_bot.__main__.find_goal_clip", return_value=None),
            patch("worldcup_bot.__main__.save_clips") as mock_save,
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        mock_save.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Persistence
# ══════════════════════════════════════════════════════════════════════════════


class TestPersistence:
    @pytest.mark.asyncio
    async def test_save_clips_called_after_attempts_incremented(self, tmp_path):
        """save_clips is called so attempts persist across bot restarts."""
        settings = _make_settings(tmp_path)
        token = "savetok"
        entry = _searching_entry(attempts=0)
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        with (
            patch("worldcup_bot.__main__.find_goal_clip", return_value=None),
            patch("worldcup_bot.__main__.save_clips") as mock_save,
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        mock_save.assert_called_once()
        saved_path = mock_save.call_args[0][0]
        assert "goal_clips.json" in saved_path

    @pytest.mark.asyncio
    async def test_clip_store_in_bot_data_updated(self, tmp_path):
        """bot_data['clip_store'] is updated in-place (same object reference)."""
        settings = _make_settings(tmp_path)
        token = "inplacetok"
        entry = _searching_entry(attempts=0)
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        with (
            patch("worldcup_bot.__main__.find_goal_clip", return_value=None),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        # The dict in bot_data IS the clip_data dict (mutated in-place)
        assert ctx.bot_data["clip_store"][token]["attempts"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Keyboard race-condition fix (Fix B1)
# ══════════════════════════════════════════════════════════════════════════════


class TestKeyboardRaceConditionFix:
    @pytest.mark.asyncio
    async def test_status_set_ready_before_edit_message_called(self, tmp_path):
        """entry['status'] must be 'ready' BEFORE edit_message_reply_markup is awaited.

        Ensures that any concurrent _backfill_scorer_in_clip_store call that runs
        during the network round-trip sees status='ready' and preserves the keyboard.
        """
        settings = _make_settings(tmp_path)
        token = "racetok1234"
        entry = _searching_entry()
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        status_at_edit_time: list[str] = []

        async def _capture_status_then_edit(**kwargs):
            # Record what status was when edit was called
            status_at_edit_time.append(entry.get("status", "?"))

        ctx.bot.edit_message_reply_markup = AsyncMock(side_effect=_capture_status_then_edit)

        fake_video = tmp_path / "clip.mp4"
        fake_video.write_bytes(b"data")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        with (
            patch("worldcup_bot.__main__.find_goal_clip", return_value="https://x.com/v"),
            patch("worldcup_bot.__main__.MediaDownloader", return_value=fake_downloader),
            patch("worldcup_bot.__main__.compress_if_needed", new=AsyncMock(return_value=fake_video)),
            patch("worldcup_bot.__main__.shutil.move"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert status_at_edit_time == ["ready"], (
            f"expected status='ready' when edit was called, got {status_at_edit_time}"
        )

    @pytest.mark.asyncio
    async def test_clip_path_set_before_edit_message_called(self, tmp_path):
        """entry['clip_path'] is set before edit_message_reply_markup so the entry is complete."""
        settings = _make_settings(tmp_path)
        token = "racetok5678"
        entry = _searching_entry()
        clip_data = {token: entry}
        ctx = _make_context(settings, clip_data)

        clip_path_at_edit: list = []

        async def _capture(**kwargs):
            clip_path_at_edit.append(entry.get("clip_path"))

        ctx.bot.edit_message_reply_markup = AsyncMock(side_effect=_capture)

        fake_video = tmp_path / "clip.mp4"
        fake_video.write_bytes(b"data")
        fake_downloader = MagicMock()
        fake_downloader.download = AsyncMock(return_value=fake_video)

        with (
            patch("worldcup_bot.__main__.find_goal_clip", return_value="https://x.com/v"),
            patch("worldcup_bot.__main__.MediaDownloader", return_value=fake_downloader),
            patch("worldcup_bot.__main__.compress_if_needed", new=AsyncMock(return_value=fake_video)),
            patch("worldcup_bot.__main__.shutil.move"),
            patch("worldcup_bot.__main__.save_clips"),
            patch("worldcup_bot.__main__.prune_old_entries"),
        ):
            await poll_goal_clips_job(ctx)

        assert clip_path_at_edit[0] is not None, "clip_path must be set before keyboard edit"
