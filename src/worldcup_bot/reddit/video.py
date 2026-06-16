"""Video probe and compression helpers for sending goal clips to Telegram.

Standalone async functions so they can be tested independently.  Both rely on
system ``ffprobe`` / ``ffmpeg`` binaries (added to the Docker image by Maldini).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB
_COMPRESS_TARGET_BYTES = 49 * 1024 * 1024  # target slightly under the limit


class VideoTooLargeError(Exception):
    """Raised when a video cannot be compressed to fit Telegram's file size limit."""


async def probe_video(path: Path) -> dict:
    """Run ffprobe and return a dict with ``width``, ``height``, ``duration``.

    Returns an empty dict on failure — the video can still be sent; Telegram
    will render it square rather than at its native aspect ratio.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return {}
        data = json.loads(stdout)
        stream = data.get("streams", [{}])[0]
        result: dict = {}
        if "width" in stream:
            result["width"] = int(stream["width"])
        if "height" in stream:
            result["height"] = int(stream["height"])
        duration = stream.get("duration") or data.get("format", {}).get("duration")
        if duration:
            result["duration"] = int(float(duration))
        return result
    except Exception:
        log.debug("ffprobe failed for %s, sending without dimensions", path.name)
        return {}


async def _probe_duration(path: Path) -> float | None:
    """Return video duration in seconds via ffprobe, or None on failure."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return None
        data = json.loads(stdout)
        dur = data.get("format", {}).get("duration")
        return float(dur) if dur else None
    except Exception:
        return None


async def compress_if_needed(path: Path) -> Path:
    """Return path to send — original if ≤ 50 MB, compressed if larger.

    Raises ``VideoTooLargeError`` if the file exceeds the limit and cannot be
    re-encoded to fit (video too long, ffmpeg not found, or ffmpeg failed).
    """
    size = path.stat().st_size
    if size <= TELEGRAM_FILE_LIMIT:
        return path

    log.info("File too large (%d bytes), attempting compression...", size)

    duration = await _probe_duration(path)
    if not duration or duration <= 0:
        raise VideoTooLargeError(
            f"Cannot determine duration for compression of {path.name}"
        )

    audio_kbps = 128
    total_kbps = int((_COMPRESS_TARGET_BYTES * 8) / duration / 1000)
    video_kbps = int((total_kbps - audio_kbps) * 0.90)

    if video_kbps < 200:
        raise VideoTooLargeError(
            f"Video too long to compress under Telegram limit "
            f"(would need {video_kbps}kbps video bitrate, minimum 200kbps)"
        )

    compressed = path.with_name(path.stem + "_compressed.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-c:v", "libx264", "-preset", "slow",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{video_kbps}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-c:a", "aac", "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        str(compressed),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            compressed.unlink(missing_ok=True)
            raise VideoTooLargeError(
                f"ffmpeg compression failed: {stderr.decode(errors='replace')[:200]}"
            )
        new_size = compressed.stat().st_size
        log.info(
            "Compressed %s: %d → %d bytes", path.name, path.stat().st_size, new_size
        )
        if new_size > TELEGRAM_FILE_LIMIT:
            compressed.unlink(missing_ok=True)
            raise VideoTooLargeError(
                f"Compressed file still too large ({new_size} bytes)"
            )
        return compressed
    except VideoTooLargeError:
        raise
    except asyncio.TimeoutError:
        compressed.unlink(missing_ok=True)
        raise VideoTooLargeError("ffmpeg compression timed out")
    except FileNotFoundError:
        raise VideoTooLargeError("ffmpeg not found on PATH")
