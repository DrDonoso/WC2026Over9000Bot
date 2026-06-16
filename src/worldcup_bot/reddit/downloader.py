"""Multi-host video downloader for goal clips.

Supports streamff.link/com, streamin.link/me, streamain.com, and a yt-dlp
subprocess fallback.  HTTP downloads use ``requests`` (synchronous) wrapped in
``asyncio.to_thread``; yt-dlp uses ``asyncio.create_subprocess_exec`` directly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# ── CDN / embed patterns ───────────────────────────────────────────────────────

STREAMFF_VIDEO_RE = re.compile(
    r'(?:source\s+src|file)\s*[=:]\s*["\']?(https?://[^"\'>\s]+\.mp4[^"\'>\s]*)',
    re.IGNORECASE,
)
STREAMFF_CDN_ID_RE = re.compile(r"streamff\.(?:com|link)/v/([a-zA-Z0-9]+)")
STREAMFF_CDN_BASE = "https://cdn.streamff.one"

STREAMIN_CDN_ID_RE = re.compile(r"streamin\.(?:link|me)/v/([a-zA-Z0-9]+)")
STREAMIN_CDN_BASE = "https://c-cdn.streamin.top/uploads"

STREAMAIN_SLUG_RE = re.compile(r"streamain\.com/(?:en/)?([a-zA-Z0-9_-]+)/watch")
STREAMAIN_EMBED_BASE = "https://streamain.com/embed"
STREAMAIN_MP4_RE = re.compile(
    r"https?://cdn\.streamain\.com/[^\"'>\s]+\.mp4[^\"'>\s]*",
    re.IGNORECASE,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _find_downloaded_file(prefix: str) -> Path | None:
    """Find the file yt-dlp actually wrote (extension may vary from .mp4)."""
    parent = Path(prefix).parent
    stem = Path(prefix).name
    for path in parent.iterdir():
        if path.name.startswith(stem) and path.is_file() and path.stat().st_size > 0:
            return path
    return None


class MediaDownloader:
    """Downloads goal clip videos from various hosting services.

    HTTP downloads are synchronous (``requests``) and must be called via
    ``asyncio.to_thread``; yt-dlp uses ``asyncio.create_subprocess_exec``.
    An injected ``requests.Session`` enables testing without network.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = _UA

    async def download(self, media_url: str) -> Path | None:
        """Download the video at *media_url*; returns local Path or None on failure."""
        dest = self._make_dest(media_url)

        if "streamff.link" in media_url or "streamff.com" in media_url:
            result = await asyncio.to_thread(self._download_streamff, media_url, dest)
            if result:
                return result
            log.info("Streamff direct download failed, trying yt-dlp fallback")

        elif "streamin.link" in media_url or "streamin.me" in media_url:
            result = await asyncio.to_thread(self._download_streamin, media_url, dest)
            if result:
                return result
            log.info("Streamin direct download failed, trying yt-dlp fallback")

        elif "streamain.com" in media_url:
            result = await asyncio.to_thread(self._download_streamain, media_url, dest)
            if result:
                return result
            log.info("Streamain direct download failed, trying yt-dlp fallback")

        # yt-dlp fallback for v.redd.it, streamable.com, dubz.link, and unknown hosts
        return await self._download_ytdlp(media_url, dest)

    # ── private helpers ────────────────────────────────────────────────────────

    def _make_dest(self, media_url: str) -> Path:
        """Build a deterministic temp-file path for a given media URL."""
        safe = re.sub(r"[^\w]", "_", media_url[-30:])
        return Path(tempfile.gettempdir()) / f"vergol_{safe}.mp4"

    def _download_file(self, video_url: str, dest: Path) -> Path | None:
        """Stream-download *video_url* to *dest*; return *dest* or None."""
        try:
            with self._session.get(video_url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            log.info("Downloaded %d bytes to %s", dest.stat().st_size, dest)
            return dest
        except Exception as exc:
            log.warning("File download failed for %s: %s", video_url, exc)
            dest.unlink(missing_ok=True)
            return None

    def _download_streamff(self, url: str, dest: Path) -> Path | None:
        try:
            id_match = STREAMFF_CDN_ID_RE.search(url)
            if id_match:
                video_url = f"{STREAMFF_CDN_BASE}/{id_match.group(1)}.mp4"
                log.info("Downloading from streamff CDN: %s", video_url)
                return self._download_file(video_url, dest)
            # Page-scrape fallback
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            m = STREAMFF_VIDEO_RE.search(resp.text)
            if not m:
                log.debug("Could not extract video URL from streamff page")
                return None
            return self._download_file(m.group(1), dest)
        except Exception as exc:
            log.warning("Streamff download failed: %s", exc)
            return None

    def _download_streamin(self, url: str, dest: Path) -> Path | None:
        try:
            id_match = STREAMIN_CDN_ID_RE.search(url)
            if id_match:
                video_url = f"{STREAMIN_CDN_BASE}/{id_match.group(1)}.mp4"
                log.info("Downloading from streamin CDN: %s", video_url)
                return self._download_file(video_url, dest)
            # Embed-page fallback: /v/{id} → /embed/{id}
            embed_url = url.replace("/v/", "/embed/")
            resp = self._session.get(embed_url, timeout=15)
            resp.raise_for_status()
            m = STREAMFF_VIDEO_RE.search(resp.text)
            if not m:
                log.debug("Could not extract video URL from streamin embed page")
                return None
            return self._download_file(m.group(1), dest)
        except Exception as exc:
            log.warning("Streamin download failed: %s", exc)
            return None

    def _download_streamain(self, url: str, dest: Path) -> Path | None:
        try:
            slug_m = STREAMAIN_SLUG_RE.search(url)
            if not slug_m:
                log.debug("Could not extract slug from streamain URL: %s", url)
                return None
            embed_url = f"{STREAMAIN_EMBED_BASE}/{slug_m.group(1)}"
            log.info("Fetching streamain embed: %s", embed_url)
            resp = self._session.get(embed_url, timeout=15)
            resp.raise_for_status()
            mp4_m = STREAMAIN_MP4_RE.search(resp.text)
            if not mp4_m:
                log.debug("Could not extract MP4 URL from streamain embed page")
                return None
            return self._download_file(mp4_m.group(0), dest)
        except Exception as exc:
            log.warning("Streamain download failed: %s", exc)
            return None

    async def _download_ytdlp(self, url: str, dest: Path) -> Path | None:
        output_template = str(dest.with_suffix(""))
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", f"{output_template}.%(ext)s",
            "--", url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                log.warning(
                    "yt-dlp failed (code %d): %s",
                    proc.returncode,
                    stderr.decode(errors="replace")[:500],
                )
                return None
            downloaded = _find_downloaded_file(output_template)
            if not downloaded:
                log.warning("yt-dlp completed but output file not found")
                return None
            log.info(
                "yt-dlp downloaded %d bytes to %s", downloaded.stat().st_size, downloaded
            )
            return downloaded
        except asyncio.TimeoutError:
            log.warning("yt-dlp timed out for %s", url)
            return None
        except FileNotFoundError:
            log.error("yt-dlp not found on PATH")
            return None
        except Exception as exc:
            log.warning("yt-dlp unexpected error: %s", exc)
            return None
