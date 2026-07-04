"""Tests for reddit.downloader — multi-host video download."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from worldcup_bot.reddit.downloader import (
    ANY_MP4_RE,
    STREAMFF_CDN_ID_RE,
    STREAMFF_HOST_RE,
    STREAMFF_VIDEO_RE,
    STREAMIN_CDN_BASE,
    STREAMIN_CDN_ID_RE,
    MediaDownloader,
    _find_downloaded_file,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_session_for_download(content: bytes = b"fakevideodata") -> MagicMock:
    """Return a mock requests.Session whose get() behaves as a context manager."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_content = MagicMock(return_value=[content])

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)
    return session


def _make_session_for_page_scrape(
    page_html: str,
    file_content: bytes = b"fakevideodata",
) -> MagicMock:
    """Session that returns HTML on the first call and file bytes on the second."""
    calls = [0]

    # page response (plain get, not streaming)
    page_resp = MagicMock()
    page_resp.raise_for_status = MagicMock()
    page_resp.text = page_html

    # file response (streaming context manager)
    file_resp = MagicMock()
    file_resp.__enter__ = MagicMock(return_value=file_resp)
    file_resp.__exit__ = MagicMock(return_value=False)
    file_resp.raise_for_status = MagicMock()
    file_resp.iter_content = MagicMock(return_value=[file_content])

    def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return page_resp
        return file_resp

    session = MagicMock()
    session.get = MagicMock(side_effect=_get)
    return session


# ── _find_downloaded_file ─────────────────────────────────────────────────────


class TestFindDownloadedFile:
    def test_finds_file_with_mp4_extension(self, tmp_path):
        f = tmp_path / "stem.mp4"
        f.write_bytes(b"data")
        result = _find_downloaded_file(str(tmp_path / "stem"))
        assert result == f

    def test_returns_none_when_no_file(self, tmp_path):
        result = _find_downloaded_file(str(tmp_path / "stem"))
        assert result is None

    def test_ignores_empty_files(self, tmp_path):
        f = tmp_path / "stem.mp4"
        f.write_bytes(b"")  # zero bytes
        result = _find_downloaded_file(str(tmp_path / "stem"))
        assert result is None


# ── _download_streamff ────────────────────────────────────────────────────────


class TestDownloadStreamff:
    """streamff rotates domains, so the direct-CDN host is DERIVED from the
    domain of the matched clip URL (never a hardcoded TLD); a page-source scrape
    is the secondary fallback."""

    @pytest.mark.parametrize(
        "domain,vid",
        [
            ("streamff.pro", "92cb0999"),
            ("streamff.one", "abc123"),
            ("streamff.com", "xyz789"),
            ("streamff.gg", "cafebabe"),
            ("streamff.link", "deadbeef"),
        ],
    )
    def test_cdn_host_derived_from_matched_domain(self, tmp_path, domain, vid):
        """PRIMARY: cdn.<matched-domain>/<id>.mp4 — TLD comes from the matched URL."""
        session = _make_session_for_download(b"videobytes")
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff(f"https://{domain}/v/{vid}", dest)

        assert result == dest
        # The one and only request goes to the DERIVED host — not a hardcoded one.
        called_url = session.get.call_args[0][0]
        assert called_url == f"https://cdn.{domain}/{vid}.mp4"

    def test_derived_cdn_url_helper(self):
        d = MediaDownloader(session=MagicMock())
        assert (
            d._streamff_cdn_url("https://streamff.pro/v/92cb0999")
            == "https://cdn.streamff.pro/92cb0999.mp4"
        )
        # No hardcoded ``.one`` anywhere: a different matched TLD yields a
        # different derived host automatically.
        assert (
            d._streamff_cdn_url("https://streamff.com/v/xyz789")
            == "https://cdn.streamff.com/xyz789.mp4"
        )

    def test_no_hardcoded_stale_one_host_used(self, tmp_path):
        """Regression: a clip matched on .pro must NOT hit the stale cdn.streamff.one."""
        session = _make_session_for_download(b"videobytes")
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        d._download_streamff("https://streamff.pro/v/92cb0999", dest)

        for call in session.get.call_args_list:
            assert "cdn.streamff.one" not in call[0][0]

    def test_page_scrape_fallback_when_cdn_dead(self, tmp_path, monkeypatch):
        """Derived CDN dead (connection reset) → scrape page for the real source."""
        monkeypatch.setattr("worldcup_bot.reddit.downloader.time.sleep", lambda *_: None)

        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = '<source src="https://media.streamff.pro/real.mp4">'

        good_resp = MagicMock()
        good_resp.__enter__ = MagicMock(return_value=good_resp)
        good_resp.__exit__ = MagicMock(return_value=False)
        good_resp.raise_for_status = MagicMock()
        good_resp.iter_content = MagicMock(return_value=[b"videobytes"])

        seen: list[str] = []

        def _get(url, **kwargs):
            seen.append(url)
            if not kwargs.get("stream"):
                return page_resp  # page fetch (secondary)
            if url == "https://cdn.streamff.pro/89b5d5c1.mp4":
                raise requests.exceptions.ConnectionError(
                    "('Connection aborted.', ConnectionResetError(104, 'reset'))"
                )
            return good_resp  # the page-resolved source downloads fine

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/89b5d5c1", dest)

        assert result == dest
        # Derived CDN attempted first, then the page-scraped source.
        assert seen[0] == "https://cdn.streamff.pro/89b5d5c1.mp4"
        assert "https://media.streamff.pro/real.mp4" in seen

    def test_connection_reset_is_retried_then_succeeds(self, tmp_path, monkeypatch):
        """A transient connection reset on the derived CDN URL is retried."""
        monkeypatch.setattr("worldcup_bot.reddit.downloader.time.sleep", lambda *_: None)

        good_resp = MagicMock()
        good_resp.__enter__ = MagicMock(return_value=good_resp)
        good_resp.__exit__ = MagicMock(return_value=False)
        good_resp.raise_for_status = MagicMock()
        good_resp.iter_content = MagicMock(return_value=[b"videobytes"])

        calls = {"n": 0}

        def _get(url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.exceptions.ConnectionError("reset by peer")
            return good_resp

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/abc", dest)

        assert result == dest
        assert calls["n"] == 2  # first reset, retry succeeded on the same URL

    def test_returns_none_when_cdn_dead_and_page_has_no_source(self, tmp_path, monkeypatch):
        """Derived CDN dead AND page has no source → None (graceful, no yt-dlp)."""
        monkeypatch.setattr("worldcup_bot.reddit.downloader.time.sleep", lambda *_: None)

        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = "<html>nothing</html>"

        def _get(url, **kwargs):
            if not kwargs.get("stream"):
                return page_resp
            raise requests.exceptions.ConnectionError("dead")

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/gone", dest)
        assert result is None

    def test_no_id_falls_back_to_page_scrape(self, tmp_path):
        """URL with no ``/v/{id}`` (no derivable CDN) → page-scraped source."""
        page_html = '<source src="https://media.streamff.link/scraped.mp4" type="video/mp4">'
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.link/embed/page", dest)

        assert result == dest
        assert session.get.call_args_list[-1][0][0] == "https://media.streamff.link/scraped.mp4"

    def test_returns_none_when_no_id_and_no_source(self, tmp_path):
        """No derivable CDN and no mp4 in page → None."""
        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = "<html>nothing useful here</html>"
        session = MagicMock()
        session.get = MagicMock(return_value=page_resp)

        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.link/embed/nothing", dest)
        assert result is None


class TestStreamffPatterns:
    def test_host_regex_captures_matched_domain(self):
        m = STREAMFF_HOST_RE.search("https://streamff.pro/v/abc")
        assert m and m.group(1) == "streamff.pro"

    def test_video_re_extracts_keyed_sources(self):
        assert STREAMFF_VIDEO_RE.search(
            '<source src="https://x.one/a.mp4">'
        ).group(1) == "https://x.one/a.mp4"
        assert STREAMFF_VIDEO_RE.search(
            '"videoUrl":"https://x.one/b.mp4"'
        ).group(1) == "https://x.one/b.mp4"

    def test_any_mp4_re_matches_bare_url(self):
        assert ANY_MP4_RE.search("x https://x.one/c.mp4 y").group(0) == "https://x.one/c.mp4"


# ── _download_streamin ────────────────────────────────────────────────────────


class TestDownloadStreamin:
    def test_cdn_id_resolution_builds_correct_url(self, tmp_path):
        """`streamin.link/v/{id}` → CDN URL `c-cdn.streamin.top/uploads/{id}.mp4`."""
        session = _make_session_for_download()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamin("https://streamin.link/v/63433cf8", dest)

        assert result == dest
        called_url = session.get.call_args[0][0]
        assert called_url == f"{STREAMIN_CDN_BASE}/63433cf8.mp4"

    def test_streamin_me_cdn_id_resolution(self, tmp_path):
        """`streamin.me/v/{id}` → same CDN URL pattern."""
        session = _make_session_for_download()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamin("https://streamin.me/v/aabbcc", dest)

        assert result == dest
        called_url = session.get.call_args[0][0]
        assert called_url == f"{STREAMIN_CDN_BASE}/aabbcc.mp4"

    def test_embed_fallback_when_no_cdn_id(self, tmp_path):
        """URL without recognisable id → embed page scraped for mp4 source."""
        page_html = """
        <source src="https://cdn.streamff.one/embedded_video.mp4" type="video/mp4">
        """
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamin("https://streamin.link/embed/page", dest)

        assert result == dest
        assert session.get.call_count == 2


# ── _download_streamain ───────────────────────────────────────────────────────


class TestDownloadStreamain:
    def test_embed_scrape_extracts_cdn_mp4(self, tmp_path):
        """streamain.com embed page contains CDN .mp4 URL → downloaded."""
        embed_html = """
        <video>
          <source src="https://cdn.streamain.com/videos/goal_clip.mp4" />
        </video>
        """
        session = _make_session_for_page_scrape(embed_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamain(
            "https://streamain.com/en/sweden-goal-60/watch", dest
        )

        assert result == dest
        embed_call = session.get.call_args_list[0][0][0]
        assert "streamain.com/embed/sweden-goal-60" in embed_call

    def test_no_slug_returns_none(self, tmp_path):
        session = MagicMock()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"
        result = d._download_streamain("https://streamain.com/", dest)
        assert result is None
        session.get.assert_not_called()


# ── yt-dlp fallback ───────────────────────────────────────────────────────────


class TestYtDlpFallback:
    async def test_ytdlp_fallback_for_unknown_host(self, tmp_path):
        """An unrecognised host triggers the yt-dlp fallback."""
        d = MediaDownloader()

        # yt-dlp 'downloads' the file by our side_effect creating it
        fake_file = tmp_path / "vergol_output.mp4"
        fake_file.write_bytes(b"fakevideo")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "worldcup_bot.reddit.downloader._find_downloaded_file",
            return_value=fake_file,
        ):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ):
                result = await d._download_ytdlp(
                    "https://dubz.link/v/unknown123", tmp_path / "vergol_out.mp4"
                )

        assert result == fake_file

    async def test_ytdlp_returns_none_on_failure(self, tmp_path):
        """yt-dlp non-zero exit → None."""
        d = MediaDownloader()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error output"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await d._download_ytdlp(
                "https://example.com/video", tmp_path / "out.mp4"
            )

        assert result is None

    async def test_ytdlp_returns_none_on_not_found(self, tmp_path):
        """FileNotFoundError (yt-dlp not on PATH) → None, no crash."""
        d = MediaDownloader()

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("yt-dlp not found"),
        ):
            result = await d._download_ytdlp(
                "https://example.com/video", tmp_path / "out.mp4"
            )

        assert result is None

    async def test_download_routes_unknown_host_to_ytdlp(self, tmp_path):
        """download() with an unknown host calls _download_ytdlp."""
        fake_file = tmp_path / "vergol_out.mp4"
        fake_file.write_bytes(b"fakevideo")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        session = MagicMock()
        d = MediaDownloader(session=session)
        # Override _make_dest so we know the output prefix
        d._make_dest = lambda url: tmp_path / "vergol_out.mp4"

        with patch(
            "worldcup_bot.reddit.downloader._find_downloaded_file",
            return_value=fake_file,
        ):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await d.download("https://v.redd.it/some_clip")

        assert result == fake_file
        session.get.assert_not_called()

    async def test_download_routes_streamff_pro_to_streamff_handler(self, tmp_path):
        """download() with streamff.pro downloads from the DERIVED CDN host and
        never falls through to yt-dlp."""
        session = _make_session_for_download(b"videobytes")
        d = MediaDownloader(session=session)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await d.download("https://streamff.pro/v/89b5d5c1")

        assert result is not None
        # Derived from the matched domain, and yt-dlp was NOT invoked for streamff.
        assert session.get.call_args[0][0] == "https://cdn.streamff.pro/89b5d5c1.mp4"
        mock_exec.assert_not_called()

    async def test_download_routes_streamff_gg_to_streamff_handler(self, tmp_path):
        """download() with streamff.gg uses the derived CDN and skips yt-dlp."""
        session = _make_session_for_download(b"videobytes")
        d = MediaDownloader(session=session)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await d.download("https://streamff.gg/v/cafebabe")

        assert result is not None
        assert session.get.call_args[0][0] == "https://cdn.streamff.gg/cafebabe.mp4"
        mock_exec.assert_not_called()

    async def test_download_streamff_failure_does_not_call_ytdlp(self, tmp_path):
        """A total streamff failure returns None without invoking yt-dlp."""
        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = "<html>nothing</html>"
        session = MagicMock()
        # page ok (no mp4), every stream get resets → all CDN hosts fail
        session.get = MagicMock(
            side_effect=lambda url, **kw: (
                page_resp
                if not kw.get("stream")
                else (_ for _ in ()).throw(requests.exceptions.ConnectionError("dead"))
            )
        )
        d = MediaDownloader(session=session)

        with patch("worldcup_bot.reddit.downloader.time.sleep", lambda *_: None):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                result = await d.download("https://streamff.pro/v/gone")

        assert result is None
        mock_exec.assert_not_called()
