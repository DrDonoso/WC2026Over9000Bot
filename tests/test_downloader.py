"""Tests for reddit.downloader — multi-host video download."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.reddit.downloader import (
    STREAMFF_CDN_BASE,
    STREAMFF_CDN_ID_RE,
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
    def test_cdn_id_resolution_builds_correct_url(self, tmp_path):
        """`streamff.link/v/{id}` → CDN URL `cdn.streamff.one/{id}.mp4`."""
        session = _make_session_for_download()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.link/v/abc123", dest)

        assert result == dest
        called_url = session.get.call_args[0][0]
        assert called_url == f"{STREAMFF_CDN_BASE}/abc123.mp4"

    def test_streamff_com_cdn_id_resolution(self, tmp_path):
        """`streamff.com/v/{id}` → same CDN URL pattern."""
        session = _make_session_for_download()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.com/v/xyz789", dest)

        assert result == dest
        called_url = session.get.call_args[0][0]
        assert called_url == f"{STREAMFF_CDN_BASE}/xyz789.mp4"

    def test_streamff_pro_cdn_id_resolution(self, tmp_path):
        """`streamff.pro/v/{id}` → CDN URL `cdn.streamff.one/{id}.mp4`."""
        session = _make_session_for_download()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/89b5d5c1", dest)

        assert result == dest
        called_url = session.get.call_args[0][0]
        assert called_url == f"{STREAMFF_CDN_BASE}/89b5d5c1.mp4"

    def test_streamff_gg_cdn_id_resolution(self, tmp_path):
        """`streamff.gg/v/{id}` → CDN URL `cdn.streamff.one/{id}.mp4`."""
        session = _make_session_for_download()
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.gg/v/aabbccdd", dest)

        assert result == dest
        called_url = session.get.call_args[0][0]
        assert called_url == f"{STREAMFF_CDN_BASE}/aabbccdd.mp4"

    def test_page_scrape_fallback_when_no_cdn_id(self, tmp_path):
        """URL with no recognisable id → page-scrape for video source."""
        page_html = """
        <source src="https://cdn.streamff.one/scraped.mp4" type="video/mp4">
        """
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.link/embed/page", dest)

        assert result == dest
        # Second session.get call is for the actual file
        assert session.get.call_count == 2

    def test_returns_none_when_no_mp4_in_page(self, tmp_path):
        page_html = "<html>nothing useful here</html>"
        # Just page response, no file download
        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = page_html
        session = MagicMock()
        session.get = MagicMock(return_value=page_resp)

        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.link/embed/nothing", dest)
        assert result is None


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
        """download() with streamff.pro routes to _download_streamff, not yt-dlp."""
        session = _make_session_for_download(b"videobytes")
        d = MediaDownloader(session=session)

        result = await d.download("https://streamff.pro/v/89b5d5c1")

        # Session.get was called by _download_streamff for the CDN URL — not yt-dlp
        assert result is not None
        called_url = session.get.call_args[0][0]
        assert "cdn.streamff.one" in called_url
        assert "89b5d5c1" in called_url

    async def test_download_routes_streamff_gg_to_streamff_handler(self, tmp_path):
        """download() with streamff.gg routes to _download_streamff, not yt-dlp."""
        session = _make_session_for_download(b"videobytes")
        d = MediaDownloader(session=session)

        result = await d.download("https://streamff.gg/v/cafebabe")

        assert result is not None
        called_url = session.get.call_args[0][0]
        assert "cdn.streamff.one" in called_url
        assert "cafebabe" in called_url
