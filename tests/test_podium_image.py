"""Smoke tests for worldcup_bot.bot.podium_image.render_podium."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from worldcup_bot.bot.podium_image import render_podium, _render_podium
from worldcup_bot.config import Settings


# ── Helpers ────────────────────────────────────────────────────────────────────


def _tiny_png() -> bytes:
    """Return bytes for a minimal valid 10×10 red PNG."""
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _photo_resp(content: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "image/png"}
    resp.content = content
    return resp


def _error_resp() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 404
    resp.headers = {"Content-Type": "text/html"}
    resp.content = b""
    return resp


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="t",
        football_data_api_key="k",
        photo_base_url="http://example.com/photos",
    )


def _p(username: str, display_name: str, position: int) -> dict:
    return {"username": username, "display_name": display_name, "position": position}


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestRenderPodiumSmoke:
    def test_three_valid_photos_returns_png(self):
        """Happy path: 3 participants with fetchable photos → valid PNG BytesIO."""
        participants = [
            _p("david",  "David Santos",       1),
            _p("pilar",  "Pilar Freixas",       1),
            _p("miquel", "Miquel Llagostera",   3),
        ]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        img = Image.open(result)
        assert img.format == "PNG"

    def test_missing_photo_uses_placeholder_not_none(self):
        """404 response → placeholder tile used; result is still a valid PNG, not None."""
        participants = [
            _p("user1", "Alice",   1),
            _p("user2", "Bob",     2),
            _p("user3", "Charlie", 3),
        ]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_error_resp(),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        img = Image.open(result)
        assert img.format == "PNG"

    def test_tie_case_1_1_3_returns_png(self):
        """Positions [1, 1, 3] — tied first place — must not crash and return a PNG."""
        participants = [
            _p("user1", "David",  1),
            _p("user2", "Pilar",  1),
            _p("user3", "Miquel", 3),
        ]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        assert Image.open(result).format == "PNG"

    def test_all_tied_1_1_1_returns_png(self):
        """All three tied at position 1 — must not crash."""
        participants = [_p(f"u{i}", f"Name{i}", 1) for i in range(3)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None

    def test_tie_1_2_2_returns_png(self):
        """Positions [1, 2, 2] — tied second place — must not crash."""
        participants = [_p("u1", "A", 1), _p("u2", "B", 2), _p("u3", "C", 2)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None

    def test_network_error_falls_back_to_placeholder_not_none(self):
        """requests.get raises → placeholder used; render still returns a valid image."""
        participants = [_p("user1", "Alice", 1)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            side_effect=OSError("network error"),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        assert Image.open(result).format == "PNG"

    def test_empty_participants_returns_none(self):
        """Empty list → None (nothing to render)."""
        assert render_podium([], _settings()) is None

    def test_total_failure_returns_none(self):
        """If the internal render raises an exception, render_podium returns None (never raises)."""
        participants = [_p("u", "U", 1)]
        with patch(
            "worldcup_bot.bot.podium_image._render_podium",
            side_effect=RuntimeError("boom"),
        ):
            result = render_podium(participants, _settings())

        assert result is None

    def test_one_participant_returns_png(self):
        """Single participant — graceful handling without crash."""
        participants = [_p("solo", "Solo Player", 1)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        assert Image.open(result).format == "PNG"

    def test_two_participants_returns_png(self):
        """Two participants — no crash, valid PNG."""
        participants = [_p("u1", "Alpha", 1), _p("u2", "Beta", 2)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        assert Image.open(result).format == "PNG"

    def test_result_is_seeked_to_start(self):
        """The returned BytesIO must be seeked to position 0 (ready for Telegram send_photo)."""
        participants = [_p("u", "Name", 1)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        assert result is not None
        assert result.tell() == 0

    def test_canvas_dimensions_720x400(self):
        """The output image must be exactly 720×400 pixels."""
        participants = [_p("u1", "A", 1), _p("u2", "B", 2), _p("u3", "C", 3)]
        with patch(
            "worldcup_bot.bot.podium_image.requests.get",
            return_value=_photo_resp(_tiny_png()),
        ):
            result = render_podium(participants, _settings())

        img = Image.open(result)
        assert img.size == (720, 400)
