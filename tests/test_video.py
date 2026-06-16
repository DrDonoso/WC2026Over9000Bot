"""Tests for reddit.video — probe_video and compress_if_needed."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.reddit.video import (
    TELEGRAM_FILE_LIMIT,
    VideoTooLargeError,
    compress_if_needed,
    probe_video,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_ffprobe_output(width: int, height: int, duration: float) -> bytes:
    return json.dumps(
        {
            "streams": [
                {
                    "width": width,
                    "height": height,
                    "duration": str(duration),
                }
            ]
        }
    ).encode()


def _make_ffprobe_format_output(duration: float) -> bytes:
    return json.dumps({"format": {"duration": str(duration)}}).encode()


def _make_process(returncode: int, stdout: bytes, stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ── probe_video ───────────────────────────────────────────────────────────────


class TestProbeVideo:
    async def test_returns_width_height_duration(self, tmp_path):
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fakevideo")
        stdout = _make_ffprobe_output(1920, 1080, 12.5)
        proc = _make_process(0, stdout)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await probe_video(video_path)

        assert result == {"width": 1920, "height": 1080, "duration": 12}

    async def test_returns_empty_dict_on_nonzero_returncode(self, tmp_path):
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fakevideo")
        proc = _make_process(1, b"", b"error")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await probe_video(video_path)

        assert result == {}

    async def test_returns_empty_dict_on_exception(self, tmp_path):
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fakevideo")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("ffprobe not found"),
        ):
            result = await probe_video(video_path)

        assert result == {}

    async def test_partial_output_missing_dimension(self, tmp_path):
        """If only duration is present (no width/height), returns only duration."""
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fakevideo")
        stdout = json.dumps(
            {"streams": [{"duration": "10.0"}]}
        ).encode()
        proc = _make_process(0, stdout)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await probe_video(video_path)

        assert "width" not in result
        assert "height" not in result
        assert result["duration"] == 10

    async def test_duration_from_format_section_as_fallback(self, tmp_path):
        """Duration may live in streams[0].duration or format.duration."""
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fakevideo")
        stdout = json.dumps(
            {
                "streams": [{"width": 640, "height": 360}],
                "format": {"duration": "30.0"},
            }
        ).encode()
        proc = _make_process(0, stdout)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await probe_video(video_path)

        assert result["width"] == 640
        assert result["duration"] == 30


# ── compress_if_needed ────────────────────────────────────────────────────────


class TestCompressIfNeeded:
    async def test_returns_original_when_small(self, tmp_path):
        """File under 50 MB → returned as-is without calling ffmpeg."""
        small_file = tmp_path / "small.mp4"
        small_file.write_bytes(b"x" * 100)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await compress_if_needed(small_file)

        assert result == small_file
        mock_exec.assert_not_called()

    async def test_attempts_compression_when_over_limit(self, tmp_path):
        """File over 50 MB triggers ffmpeg compression."""
        large_file = tmp_path / "large.mp4"
        large_file.write_bytes(b"x" * (TELEGRAM_FILE_LIMIT + 1))

        compressed_file = tmp_path / "large_compressed.mp4"
        compressed_file.write_bytes(b"x" * 100)  # small compressed version

        # ffprobe (duration probe) returns 30s duration
        ffprobe_out = _make_ffprobe_format_output(30.0)
        ffprobe_proc = _make_process(0, ffprobe_out)

        # ffmpeg compression succeeds
        ffmpeg_proc = _make_process(0, b"", b"")

        call_count = [0]

        def _exec_side_effect(*args, **kwargs):
            call_count[0] += 1
            if "ffprobe" in args[0]:
                return ffprobe_proc
            # ffmpeg — create the compressed file
            compressed_file.write_bytes(b"x" * 100)
            return ffmpeg_proc

        with patch("asyncio.create_subprocess_exec", side_effect=_exec_side_effect):
            result = await compress_if_needed(large_file)

        assert result == compressed_file

    async def test_raises_when_duration_unavailable(self, tmp_path):
        """Cannot compress without knowing duration → VideoTooLargeError."""
        large_file = tmp_path / "large.mp4"
        large_file.write_bytes(b"x" * (TELEGRAM_FILE_LIMIT + 1))

        ffprobe_proc = _make_process(1, b"", b"error")  # ffprobe fails

        with patch("asyncio.create_subprocess_exec", return_value=ffprobe_proc):
            with pytest.raises(VideoTooLargeError, match="duration"):
                await compress_if_needed(large_file)

    async def test_raises_when_video_too_long_to_compress(self, tmp_path):
        """Very long video → required bitrate below 200kbps → VideoTooLargeError."""
        large_file = tmp_path / "large.mp4"
        large_file.write_bytes(b"x" * (TELEGRAM_FILE_LIMIT + 1))

        # 10 hours long — impossible to compress below 50 MB
        ffprobe_out = _make_ffprobe_format_output(36000.0)
        ffprobe_proc = _make_process(0, ffprobe_out)

        with patch("asyncio.create_subprocess_exec", return_value=ffprobe_proc):
            with pytest.raises(VideoTooLargeError, match="[Tt]oo long|bitrate"):
                await compress_if_needed(large_file)

    async def test_raises_when_ffmpeg_compression_fails(self, tmp_path):
        """ffmpeg non-zero exit → VideoTooLargeError."""
        large_file = tmp_path / "large.mp4"
        large_file.write_bytes(b"x" * (TELEGRAM_FILE_LIMIT + 1))

        ffprobe_out = _make_ffprobe_format_output(30.0)
        ffprobe_proc = _make_process(0, ffprobe_out)
        ffmpeg_proc = _make_process(1, b"", b"ffmpeg error output")

        def _exec_side_effect(*args, **kwargs):
            if "ffprobe" in args[0]:
                return ffprobe_proc
            return ffmpeg_proc

        with patch("asyncio.create_subprocess_exec", side_effect=_exec_side_effect):
            with pytest.raises(VideoTooLargeError, match="ffmpeg"):
                await compress_if_needed(large_file)

    async def test_raises_when_ffmpeg_not_found(self, tmp_path):
        """FileNotFoundError (ffmpeg not on PATH) → VideoTooLargeError."""
        large_file = tmp_path / "large.mp4"
        large_file.write_bytes(b"x" * (TELEGRAM_FILE_LIMIT + 1))

        ffprobe_out = _make_ffprobe_format_output(30.0)
        ffprobe_proc = _make_process(0, ffprobe_out)

        call_count = [0]

        def _exec_side_effect(*args, **kwargs):
            call_count[0] += 1
            if "ffprobe" in args[0]:
                return ffprobe_proc
            raise FileNotFoundError("ffmpeg not found")

        with patch("asyncio.create_subprocess_exec", side_effect=_exec_side_effect):
            with pytest.raises(VideoTooLargeError, match="[Ff]fmpeg|PATH"):
                await compress_if_needed(large_file)
