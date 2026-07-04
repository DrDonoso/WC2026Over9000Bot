"""Tests for reddit.downloader — multi-host video download."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from worldcup_bot.reddit.downloader import (
    ANY_MP4_RE,
    STREAMFF_CDN_BASE,
    STREAMFF_CDN_HOSTS,
    STREAMFF_CDN_ID_RE,
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
    """streamff domains rotate, so the real ``.mp4`` is resolved from the actual
    matched page first; a direct-CDN guess (derived from the matched domain) is
    only a fallback."""

    def test_resolves_mp4_from_page_source(self, tmp_path):
        """Primary path: the ``<source src>`` in the matched page is downloaded."""
        page_html = (
            '<video><source src="https://cdn.streamff.pro/real92cb.mp4" '
            'type="video/mp4"></video>'
        )
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/92cb0999", dest)

        assert result == dest
        # First get() is the page; second get() is the resolved mp4 (not a
        # guessed cdn.streamff.one host).
        assert session.get.call_count == 2
        assert session.get.call_args_list[1][0][0] == "https://cdn.streamff.pro/real92cb.mp4"

    def test_resolves_mp4_from_json_url_key(self, tmp_path):
        """A JSON ``"videoUrl":"…mp4"`` embedded in the page is resolved."""
        page_html = '{"videoUrl":"https://cdn.streamff.one/json42.mp4","x":1}'
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/abc", dest)

        assert result == dest
        assert session.get.call_args_list[1][0][0] == "https://cdn.streamff.one/json42.mp4"

    def test_resolves_bare_mp4_url_in_page(self, tmp_path):
        """A bare absolute ``.mp4`` URL with no key is still picked up."""
        page_html = "loading https://cdn.streamff.gg/bare777.mp4 now"
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/xyz", dest)

        assert result == dest
        assert session.get.call_args_list[1][0][0] == "https://cdn.streamff.gg/bare777.mp4"

    def test_cdn_fallback_uses_matched_domain_first(self, tmp_path):
        """When the page has no source, the direct-CDN guess is derived from the
        SAME domain the clip was matched on (streamff.pro → cdn.streamff.pro)."""
        # Page returns no mp4; the CDN file download then succeeds.
        session = _make_session_for_page_scrape("<html>no video here</html>")
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.pro/v/89b5d5c1", dest)

        assert result == dest
        assert session.get.call_count == 2
        cdn_url = session.get.call_args_list[1][0][0]
        assert cdn_url == "https://cdn.streamff.pro/89b5d5c1.mp4"

    def test_cdn_fallback_iterates_hosts_on_dead_host(self, tmp_path, monkeypatch):
        """A dead CDN host (connection reset) is skipped and the next host tried."""
        monkeypatch.setattr("worldcup_bot.reddit.downloader.time.sleep", lambda *_: None)

        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = "<html>no source</html>"

        good_resp = MagicMock()
        good_resp.__enter__ = MagicMock(return_value=good_resp)
        good_resp.__exit__ = MagicMock(return_value=False)
        good_resp.raise_for_status = MagicMock()
        good_resp.iter_content = MagicMock(return_value=[b"videobytes"])

        seen: list[str] = []

        def _get(url, **kwargs):
            seen.append(url)
            if not kwargs.get("stream"):
                return page_resp  # page fetch
            if "cdn.streamff.gg" in url:
                # matched-domain host is dead → connection reset every attempt
                raise requests.exceptions.ConnectionError(
                    "('Connection aborted.', ConnectionResetError(104, 'reset'))"
                )
            return good_resp  # next host works

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.gg/v/deadbeef", dest)

        assert result == dest
        # Dead host attempted (with retries) before falling to a working host.
        assert any("cdn.streamff.gg/deadbeef.mp4" in u for u in seen)
        assert any(
            "cdn.streamff.gg" not in u and u.endswith("deadbeef.mp4") for u in seen
        )

    def test_connection_reset_is_retried_then_succeeds(self, tmp_path, monkeypatch):
        """A transient connection reset on the resolved URL is retried."""
        monkeypatch.setattr("worldcup_bot.reddit.downloader.time.sleep", lambda *_: None)

        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = '<source src="https://cdn.streamff.pro/r.mp4">'

        good_resp = MagicMock()
        good_resp.__enter__ = MagicMock(return_value=good_resp)
        good_resp.__exit__ = MagicMock(return_value=False)
        good_resp.raise_for_status = MagicMock()
        good_resp.iter_content = MagicMock(return_value=[b"videobytes"])

        calls = {"n": 0}

        def _get(url, **kwargs):
            if not kwargs.get("stream"):
                return page_resp
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
        assert calls["n"] == 2  # first reset, retry succeeded

    def test_page_scrape_fallback_when_no_cdn_id(self, tmp_path):
        """URL with no ``/v/{id}`` → page-resolved video source."""
        page_html = '<source src="https://cdn.streamff.one/scraped.mp4" type="video/mp4">'
        session = _make_session_for_page_scrape(page_html)
        d = MediaDownloader(session=session)
        dest = tmp_path / "out.mp4"

        result = d._download_streamff("https://streamff.link/embed/page", dest)

        assert result == dest
        assert session.get.call_count == 2

    def test_returns_none_when_page_and_cdn_all_fail(self, tmp_path, monkeypatch):
        """No page source AND every CDN host dead → None (graceful)."""
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

    def test_returns_none_when_no_mp4_and_no_id(self, tmp_path):
        """No mp4 in page and no ``/v/{id}`` → None without a CDN guess."""
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
        from worldcup_bot.reddit.downloader import STREAMFF_HOST_RE

        m = STREAMFF_HOST_RE.search("https://streamff.pro/v/abc")
        assert m and m.group(1) == "streamff.pro"

    def test_cdn_candidates_put_matched_host_first(self):
        d = MediaDownloader(session=MagicMock())
        hosts = d._streamff_cdn_candidates("https://streamff.pro/v/abc")
        assert hosts[0] == "cdn.streamff.pro"
        # Known hosts are still present (no duplicates).
        assert set(STREAMFF_CDN_HOSTS).issubset(set(hosts))
        assert len(hosts) == len(set(hosts))

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
        """download() with streamff.pro routes to _download_streamff (page-resolved),
        and never falls through to yt-dlp."""
        page_html = '<source src="https://cdn.streamff.pro/89b5d5c1.mp4">'
        session = _make_session_for_page_scrape(page_html, b"videobytes")
        d = MediaDownloader(session=session)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await d.download("https://streamff.pro/v/89b5d5c1")

        assert result is not None
        # Resolved from the page, and yt-dlp was NOT invoked for streamff.
        assert session.get.call_args_list[1][0][0] == "https://cdn.streamff.pro/89b5d5c1.mp4"
        mock_exec.assert_not_called()

    async def test_download_routes_streamff_gg_to_streamff_handler(self, tmp_path):
        """download() with streamff.gg resolves via page and skips yt-dlp."""
        page_html = '<source src="https://cdn.streamff.gg/cafebabe.mp4">'
        session = _make_session_for_page_scrape(page_html, b"videobytes")
        d = MediaDownloader(session=session)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await d.download("https://streamff.gg/v/cafebabe")

        assert result is not None
        assert session.get.call_args_list[1][0][0] == "https://cdn.streamff.gg/cafebabe.mp4"
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
