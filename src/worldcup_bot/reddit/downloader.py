"""Multi-host video downloader for goal clips.

Supports streamff (.pro/.one/.com/.link/.gg/… — domain rotates), streamin
(.link/.me), streamain.com, and a yt-dlp subprocess fallback.  HTTP downloads
use ``requests`` (synchronous) wrapped in ``asyncio.to_thread``; yt-dlp uses
``asyncio.create_subprocess_exec`` directly.

streamff domains and their CDN hosts change periodically, so the streamff path
RESOLVES the real ``.mp4`` from the actual matched page first and only falls
back to guessing a direct-CDN host (derived from the matched domain) when the
page cannot be parsed.  yt-dlp does not support streamff, so streamff never
falls through to it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# ── CDN / embed patterns ───────────────────────────────────────────────────────

# Keyed source extraction: <source src="…mp4">, file: "…mp4", src="…mp4",
# "videoUrl":"…mp4", "url":"…mp4".  Anchored on ``.mp4`` so it stays specific.
STREAMFF_VIDEO_RE = re.compile(
    r'(?:source\s+src|file|src|(?:video)?url)["\']?\s*[=:]\s*["\']?'
    r'(https?://[^"\'>\s]+\.mp4[^"\'>\s]*)',
    re.IGNORECASE,
)
# Last-resort: any absolute .mp4 URL anywhere in the page/JSON.
ANY_MP4_RE = re.compile(r'https?://[^"\'>\s]+\.mp4[^"\'>\s]*', re.IGNORECASE)

STREAMFF_CDN_ID_RE = re.compile(r"streamff\.[a-z]+/v/([a-zA-Z0-9]+)")
# Capture the matched streamff host (e.g. ``streamff.pro``) so a fallback CDN
# host can be derived from the SAME domain the clip was matched on.
STREAMFF_HOST_RE = re.compile(
    r"https?://(?:www\.)?(streamff\.[a-z]+)", re.IGNORECASE
)
# Direct-CDN host candidates tried (in order) only when page extraction fails.
# The matched domain's ``cdn.<domain>`` is prepended at call time.  This list is
# a best-effort of hosts seen in the wild; domains rotate, so the page-resolved
# path above is the durable fix.
STREAMFF_CDN_HOSTS: tuple[str, ...] = (
    "cdn.streamff.one",
    "cdn.streamff.pro",
    "cdn.streamff.com",
)
# Back-compat: first known host as a base URL.
STREAMFF_CDN_BASE = f"https://{STREAMFF_CDN_HOSTS[0]}"

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

        if "streamff." in media_url:
            # streamff is not supported by yt-dlp, so the direct/extracted path
            # is authoritative — never fall through to the yt-dlp branch.
            return await asyncio.to_thread(self._download_streamff, media_url, dest)

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

    def _download_file(
        self, video_url: str, dest: Path, retries: int = 2
    ) -> Path | None:
        """Stream-download *video_url* to *dest*; return *dest* or None.

        A transient connection reset (``ConnectionResetError`` / requests
        ``ConnectionError`` — e.g. a dead-on-arrival CDN edge) is retried up to
        *retries* times with a short linear backoff before giving up.
        """
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with self._session.get(video_url, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                log.info("Downloaded %d bytes to %s", dest.stat().st_size, dest)
                return dest
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                ConnectionResetError,
            ) as exc:
                last_exc = exc
                dest.unlink(missing_ok=True)
                if attempt < retries:
                    log.info(
                        "Retrying download (%d/%d) for %s after connection error: %s",
                        attempt + 1,
                        retries,
                        video_url,
                        exc,
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                log.warning("File download failed for %s: %s", video_url, exc)
                dest.unlink(missing_ok=True)
                return None
        log.warning(
            "File download failed for %s after %d retries: %s",
            video_url,
            retries,
            last_exc,
        )
        return None

    def _resolve_streamff_source(self, url: str) -> str | None:
        """Fetch the streamff ``/v/{id}`` page and extract the real ``.mp4`` URL.

        This is the durable, domain-independent path: rather than guessing a
        ``cdn.<domain>/{id}.mp4`` host (which breaks every time streamff rotates
        domains), we read the source the page itself references.
        """
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            html = resp.text or ""
        except Exception as exc:
            log.debug("streamff: page fetch failed for %s: %s", url, exc)
            return None
        m = STREAMFF_VIDEO_RE.search(html) or ANY_MP4_RE.search(html)
        if not m:
            log.debug("streamff: no mp4 source found in page %s", url)
            return None
        return m.group(1) if m.re is STREAMFF_VIDEO_RE else m.group(0)

    def _streamff_cdn_candidates(self, url: str) -> list[str]:
        """Return direct-CDN hosts to try, matched-domain host first."""
        hosts = list(STREAMFF_CDN_HOSTS)
        host_m = STREAMFF_HOST_RE.search(url)
        if host_m:
            matched = f"cdn.{host_m.group(1).lower()}"
            if matched in hosts:
                hosts.remove(matched)
            hosts.insert(0, matched)
        return hosts

    def _download_streamff(self, url: str, dest: Path) -> Path | None:
        # 1. Durable path: resolve the real mp4 from the actual matched page.
        video_url = self._resolve_streamff_source(url)
        if video_url:
            log.info("streamff: resolved page source %s", video_url)
            result = self._download_file(video_url, dest)
            if result:
                return result
            log.info("streamff: page-resolved source failed, trying direct CDN")

        # 2. Fallback: guess a direct-CDN URL, derived from the matched domain
        #    first, then other known streamff CDN hosts.
        id_match = STREAMFF_CDN_ID_RE.search(url)
        if not id_match:
            log.warning("streamff: no video id in %s and page resolution failed", url)
            return None
        vid = id_match.group(1)
        for host in self._streamff_cdn_candidates(url):
            cdn_url = f"https://{host}/{vid}.mp4"
            log.info("streamff: trying direct CDN %s", cdn_url)
            result = self._download_file(cdn_url, dest)
            if result:
                return result
        log.warning("streamff: all download paths failed for %s", url)
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
