"""Edge-case and integration tests for worldcup_bot.bot.podium_image.

Complements the 12 smoke tests in tests/test_podium_image.py.
Covers: _initials, circular-crop alpha, crown geometry, name truncation,
font fallback, mixed photo failure modes, inner-render exception variants,
_text_centered helper, tie-aware positions passed to render_podium, exact
send_photo kwargs, cmd_actual/cmd_general podium paths.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image, ImageDraw

import worldcup_bot.bot.podium_image as _podium_module
from worldcup_bot.bot.handlers import (
    _send_ranking_with_top3_photos,
    cmd_actual,
    cmd_general,
)
from worldcup_bot.bot.podium_image import (
    _circular_crop,
    _draw_crown,
    _font,
    _initials,
    _text_centered,
    render_podium,
)
from worldcup_bot.config import Settings
from worldcup_bot.porra.engine import UserRankEntry


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _tiny_png() -> bytes:
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _tiny_png_buf() -> io.BytesIO:
    buf = io.BytesIO(_tiny_png())
    buf.seek(0)
    return buf


def _photo_resp(content: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "image/png"}
    resp.content = content
    return resp


def _error_resp(status: int = 404) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
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


def _make_row(username: str, display_name: str, score: float) -> UserRankEntry:
    return UserRankEntry(
        username=username,
        display_name=display_name,
        total_score=score,
        base_score=0.0,
        group_score=score,
        knockout_scores={},
        exact_group_hits=0,
    )


def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    update.effective_user.username = "testuser"
    return update


def _make_context(settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    ctx.args = []
    ctx.bot.send_photo = AsyncMock()
    ctx.bot.send_media_group = AsyncMock()
    ctx.bot.send_animation = AsyncMock()
    return ctx


_FAKE_PREDICTIONS = {"participants": {"testuser": {"display_name": "Test User"}}}

_TOP5_ROWS = [
    _make_row("crispavon",     "Cris",  10.0),
    _make_row("dsantosmerino", "David",  8.0),
    _make_row("pilarfreixas",  "Pilar",  6.0),
    _make_row("josepmolina",   "Josep",  4.0),
    _make_row("annabernal",    "Anna",   2.0),
]


@pytest.fixture
def fake_settings() -> Settings:
    return Settings(
        telegram_bot_token="fake-token",
        football_data_api_key="fake-api-key",
        predictions_path="fake_predictions.yml",
    )


# ══════════════════════════════════════════════════════════════════════════════
# _initials pure function
# ══════════════════════════════════════════════════════════════════════════════


class TestInitials:
    def test_two_word_name(self):
        assert _initials("David Santos") == "DS"

    def test_single_word_name_first_initial_only(self):
        assert _initials("Madonna") == "M"

    def test_empty_string_returns_question_mark(self):
        assert _initials("") == "?"

    def test_whitespace_only_returns_question_mark(self):
        assert _initials("   ") == "?"

    def test_three_words_uses_first_and_last_initials(self):
        assert _initials("Juan Carlos Navarro") == "JN"

    def test_lowercase_uppercased(self):
        assert _initials("peter gabriel") == "PG"

    def test_single_char_words(self):
        assert _initials("A B") == "AB"


# ══════════════════════════════════════════════════════════════════════════════
# _circular_crop alpha mask
# ══════════════════════════════════════════════════════════════════════════════


class TestCircularCrop:
    def test_output_mode_is_rgba(self):
        img = Image.new("RGB", (50, 50), (255, 0, 0))
        assert _circular_crop(img, 50).mode == "RGBA"

    def test_output_size_matches_requested_diameter(self):
        img = Image.new("RGB", (80, 60), (0, 128, 255))
        assert _circular_crop(img, 60).size == (60, 60)

    def test_center_pixel_is_fully_opaque(self):
        """The pixel at the geometric center of the circle must have alpha == 255."""
        d = 100
        img = Image.new("RGB", (d, d), (200, 100, 50))
        result = _circular_crop(img, d)
        *_, alpha = result.getpixel((d // 2, d // 2))
        assert alpha == 255

    def test_corner_pixels_are_fully_transparent(self):
        """All four image corners fall outside the inscribed circle → alpha == 0."""
        d = 100
        img = Image.new("RGB", (d, d), (200, 100, 50))
        result = _circular_crop(img, d)
        for corner in [(0, 0), (d - 1, 0), (0, d - 1), (d - 1, d - 1)]:
            *_, alpha = result.getpixel(corner)
            assert alpha == 0, f"Corner {corner} should be transparent, got alpha={alpha}"


# ══════════════════════════════════════════════════════════════════════════════
# _draw_crown geometry
# ══════════════════════════════════════════════════════════════════════════════


class TestDrawCrown:
    def test_polygon_has_exactly_11_vertices(self):
        """Band + 3 spikes = 11 polygon vertices."""
        draw = MagicMock()
        _draw_crown(draw, cx=100, y_top=20)
        draw.polygon.assert_called_once()
        pts = draw.polygon.call_args.args[0]
        assert len(pts) == 11

    def test_three_jewel_ellipses_drawn(self):
        """One jewel per spike tip → ellipse called exactly 3 times."""
        draw = MagicMock()
        _draw_crown(draw, cx=100, y_top=20)
        assert draw.ellipse.call_count == 3

    def test_crown_polygon_filled_with_gold_constant(self):
        from worldcup_bot.bot.podium_image import _CROWN_GOLD
        draw = MagicMock()
        _draw_crown(draw, cx=100, y_top=20)
        _, kwargs = draw.polygon.call_args
        assert kwargs["fill"] == _CROWN_GOLD


# ══════════════════════════════════════════════════════════════════════════════
# Name truncation (verified via _text_centered spy)
# ══════════════════════════════════════════════════════════════════════════════


class TestNameTruncation:
    """Names > 14 chars must be truncated to 13 chars + '…' in the rendered output."""

    def _render_and_capture(self, display_name: str) -> list[str]:
        """Return every text string passed to _text_centered during a single-participant render."""
        drawn: list[str] = []

        def _spy(draw, cx, cy, text, font, color):
            drawn.append(text)

        with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=OSError()):
            with patch("worldcup_bot.bot.podium_image._text_centered", side_effect=_spy):
                render_podium([_p("u", display_name, 1)], _settings())
        return drawn

    def test_exactly_14_chars_not_truncated(self):
        name = "A" * 14
        assert name in self._render_and_capture(name)

    def test_15_chars_truncated_with_ellipsis(self):
        name = "B" * 15
        expected = "B" * 13 + "…"
        texts = self._render_and_capture(name)
        assert expected in texts
        assert name not in texts, "Full 15-char name must NOT reach _text_centered"

    def test_30_chars_truncated_correctly(self):
        name = "C" * 30
        assert "C" * 13 + "…" in self._render_and_capture(name)

    def test_very_long_name_does_not_crash_render(self):
        """render_podium with a 50-char name must return a valid PNG, not None."""
        with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=OSError()):
            result = render_podium([_p("u", "Z" * 50, 1)], _settings())
        assert result is not None
        assert Image.open(result).format == "PNG"


# ══════════════════════════════════════════════════════════════════════════════
# Font fallback (matplotlib unavailable)
# ══════════════════════════════════════════════════════════════════════════════


class TestFontFallback:
    def test_render_returns_png_when_font_path_is_none(self):
        """When _FONT_PATH is None (matplotlib absent), render still produces a valid PNG."""
        with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=OSError()):
            with patch.object(_podium_module, "_FONT_PATH", None):
                result = render_podium([_p("u", "Test", 1)], _settings())
        assert result is not None
        assert Image.open(result).format == "PNG"

    def test_font_function_returns_object_when_path_none(self):
        """_font() must return a usable object even when _FONT_PATH is None."""
        with patch.object(_podium_module, "_FONT_PATH", None):
            fnt = _font(16)
        assert fnt is not None

    def test_font_function_falls_back_on_bad_truetype_path(self):
        """_font() falls back to load_default() if the truetype path is invalid."""
        with patch.object(_podium_module, "_FONT_PATH", "/nonexistent/fake/font.ttf"):
            fnt = _font(16)
        assert fnt is not None


# ══════════════════════════════════════════════════════════════════════════════
# Mixed photo failure modes
# ══════════════════════════════════════════════════════════════════════════════


class TestMixedPhotoFailures:
    def test_404_non_image_ct_and_connection_error_all_use_placeholders(self):
        """404, wrong Content-Type, and OSError in the same render → all placeholders; valid PNG."""
        non_image = MagicMock()
        non_image.status_code = 200
        non_image.headers = {"Content-Type": "text/plain"}
        non_image.content = b"nope"

        def _varied(url, timeout):
            if "user1" in url:
                return _error_resp(404)
            if "user2" in url:
                return non_image
            raise OSError("refused")

        participants = [_p("user1", "Alice", 1), _p("user2", "Bob", 2), _p("user3", "Carol", 3)]
        with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=_varied):
            result = render_podium(participants, _settings())

        assert result is not None
        assert Image.open(result).format == "PNG"

    def test_non_image_content_type_falls_back_to_placeholder(self):
        """200 OK but Content-Type: application/json → placeholder used; result not None."""
        bad_ct = MagicMock()
        bad_ct.status_code = 200
        bad_ct.headers = {"Content-Type": "application/json"}
        bad_ct.content = b'{"err":"nope"}'

        with patch("worldcup_bot.bot.podium_image.requests.get", return_value=bad_ct):
            result = render_podium([_p("u", "User", 1)], _settings())

        assert result is not None

    def test_first_photo_ok_others_fail_still_valid_png(self):
        """First participant has a valid photo; participants 2 and 3 get 404 → valid PNG."""
        calls = [0]

        def _mixed(url, timeout):
            idx = calls[0]; calls[0] += 1
            return _photo_resp(_tiny_png()) if idx == 0 else _error_resp()

        participants = [_p(f"u{i}", f"N{i}", i + 1) for i in range(3)]
        with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=_mixed):
            result = render_podium(participants, _settings())

        assert result is not None
        assert Image.open(result).format == "PNG"


# ══════════════════════════════════════════════════════════════════════════════
# Total-failure variants: inner exceptions caught by render_podium
# ══════════════════════════════════════════════════════════════════════════════


class TestTotalFailureVariants:
    def test_image_new_raises_returns_none(self):
        """MemoryError from PIL Image.new propagates to render_podium → returns None, never raises."""
        with patch("worldcup_bot.bot.podium_image.Image.new", side_effect=MemoryError("OOM")):
            result = render_podium([_p("u", "Test", 1)], _settings())
        assert result is None

    def test_draw_crown_exception_mid_render_returns_none(self):
        """ValueError raised inside _draw_crown is caught → render_podium returns None.

        _CROWN_IMG must be patched to None so the fallback drawn-crown path is taken
        (when the real asset is loaded, _draw_crown is never called).
        """
        with patch("worldcup_bot.bot.podium_image._CROWN_IMG", None):
            with patch("worldcup_bot.bot.podium_image._draw_crown", side_effect=ValueError("geometry")):
                with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=OSError()):
                    result = render_podium([_p("u", "Test", 1)], _settings())
        assert result is None

    def test_canvas_save_raises_returns_none(self):
        """OSError from canvas.save → render_podium returns None."""
        with patch.object(Image.Image, "save", side_effect=OSError("disk full")):
            with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=OSError()):
                result = render_podium([_p("u", "Test", 1)], _settings())
        assert result is None

    def test_render_podium_never_raises_regardless_of_inner_error(self):
        """render_podium must never propagate exceptions — caller must never need to catch."""
        with patch("worldcup_bot.bot.podium_image.Image.new", side_effect=RuntimeError("crash")):
            try:
                result = render_podium([_p("u", "Test", 1)], _settings())
            except Exception as exc:
                pytest.fail(f"render_podium raised unexpectedly: {exc}")
            else:
                assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# _text_centered helper
# ══════════════════════════════════════════════════════════════════════════════


class TestTextCentered:
    def test_no_crash_with_real_draw(self):
        """_text_centered must not raise when called with a real PIL ImageDraw."""
        img = Image.new("RGB", (200, 100), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        _text_centered(draw, 100, 50, "Hello", _font(12), (255, 255, 255))

    def test_fallback_when_textbbox_raises_attribute_error(self):
        """When draw.textbbox is absent (old PIL), _text_centered falls back and still calls draw.text."""
        draw = MagicMock()
        draw.textbbox.side_effect = AttributeError("textbbox not available")
        _text_centered(draw, 50, 50, "Hi", _font(12), (255, 255, 255))
        draw.text.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Integration: tie-aware positions passed to render_podium
# ══════════════════════════════════════════════════════════════════════════════


class TestSendRankingTieAwarePositions:
    """_send_ranking_with_top3_photos must derive positions from standard_competition_positions."""

    async def _capture_podium_call(self, rows: list) -> list[list[dict]]:
        settings = _settings()
        captured: list[list[dict]] = []

        def _grab(participants, s):
            captured.append(list(participants))
            return None  # force album path to avoid album mock setup

        update = _make_update()
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", side_effect=_grab):
            with patch("worldcup_bot.bot.handlers._requests.get", side_effect=OSError()):
                await _send_ranking_with_top3_photos(update, ctx, "t", rows, settings)

        return captured

    async def test_top_two_tied_yields_positions_1_1_3(self):
        rows = [_make_row("u1", "A", 10.0), _make_row("u2", "B", 10.0), _make_row("u3", "C", 8.0)]
        captured = await self._capture_podium_call(rows)
        assert [p["position"] for p in captured[0]] == [1, 1, 3]

    async def test_bottom_two_tied_yields_positions_1_2_2(self):
        rows = [_make_row("u1", "A", 10.0), _make_row("u2", "B", 8.0), _make_row("u3", "C", 8.0)]
        captured = await self._capture_podium_call(rows)
        assert [p["position"] for p in captured[0]] == [1, 2, 2]

    async def test_all_tied_yields_positions_1_1_1(self):
        rows = [_make_row(f"u{i}", f"N{i}", 5.0) for i in range(3)]
        captured = await self._capture_podium_call(rows)
        assert [p["position"] for p in captured[0]] == [1, 1, 1]

    async def test_no_ties_yields_positions_1_2_3(self):
        rows = [_make_row("u1", "A", 10.0), _make_row("u2", "B", 8.0), _make_row("u3", "C", 6.0)]
        captured = await self._capture_podium_call(rows)
        assert [p["position"] for p in captured[0]] == [1, 2, 3]

    async def test_participant_dicts_include_username_and_display_name(self):
        rows = [_make_row("alice", "Alice Smith", 10.0)]
        captured = await self._capture_podium_call(rows)
        p = captured[0][0]
        assert p["username"] == "alice"
        assert p["display_name"] == "Alice Smith"


# ══════════════════════════════════════════════════════════════════════════════
# Integration: send_photo call kwargs when podium path succeeds
# ══════════════════════════════════════════════════════════════════════════════


class TestSendRankingPodiumKwargs:
    async def test_send_photo_receives_exact_bytesio_buffer(self):
        """The BytesIO returned by render_podium must be passed as photo= to send_photo."""
        settings = _settings()
        buf = _tiny_png_buf()
        rows = [_make_row("u1", "Alice", 10.0)]
        update = _make_update()
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", return_value=buf):
            await _send_ranking_with_top3_photos(update, ctx, "text", rows, settings)

        _, kwargs = ctx.bot.send_photo.call_args
        assert kwargs["photo"] is buf

    async def test_send_photo_chat_id_equals_effective_chat_id(self):
        settings = _settings()
        rows = [_make_row("u1", "Alice", 10.0)]
        update = _make_update()
        update.effective_chat.id = 77777
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
            await _send_ranking_with_top3_photos(update, ctx, "text", rows, settings)

        _, kwargs = ctx.bot.send_photo.call_args
        assert kwargs["chat_id"] == 77777

    async def test_send_photo_parse_mode_is_html(self):
        settings = _settings()
        rows = [_make_row("u1", "Alice", 10.0)]
        update = _make_update()
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
            await _send_ranking_with_top3_photos(update, ctx, "text", rows, settings)

        _, kwargs = ctx.bot.send_photo.call_args
        assert kwargs["parse_mode"] == "HTML"

    async def test_exactly_1024_chars_no_overflow_reply_text(self):
        """Caption == 1024 chars: NOT followed by reply_text (boundary is >1024, not >=1024)."""
        settings = _settings()
        text = "x" * 1024
        update = _make_update()
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
            await _send_ranking_with_top3_photos(update, ctx, text, [_make_row("u1", "A", 1.0)], settings)

        _, kwargs = ctx.bot.send_photo.call_args
        assert kwargs["caption"] == text
        update.message.reply_text.assert_not_called()

    async def test_1025_chars_triggers_overflow_reply_text_with_full_text(self):
        """Caption of 1025 chars: send_photo gets 1024-char slice; reply_text gets the full text."""
        settings = _settings()
        text = "y" * 1025
        update = _make_update()
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
            await _send_ranking_with_top3_photos(update, ctx, text, [_make_row("u1", "A", 1.0)], settings)

        _, kwargs = ctx.bot.send_photo.call_args
        assert kwargs["caption"] == "y" * 1024
        update.message.reply_text.assert_called_once_with(text, parse_mode="HTML")

    async def test_send_media_group_not_called_when_podium_succeeds(self):
        settings = _settings()
        update = _make_update()
        ctx = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
            await _send_ranking_with_top3_photos(update, ctx, "t", [_make_row("u1", "A", 1.0)], settings)

        ctx.bot.send_media_group.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Handler integration: cmd_actual — podium path
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdActualPodiumPath:
    """cmd_actual must call send_photo (not send_media_group) when render_podium returns a buffer."""

    async def test_send_photo_called_not_send_media_group(self, fake_settings):
        update = _make_update()
        ctx = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
                        await cmd_actual(update, ctx)

        ctx.bot.send_photo.assert_called_once()
        ctx.bot.send_media_group.assert_not_called()

    async def test_send_photo_caption_contains_provisional_title(self, fake_settings):
        update = _make_update()
        ctx = _make_context(fake_settings)

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client"):
                    with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
                        await cmd_actual(update, ctx)

        _, kwargs = ctx.bot.send_photo.call_args
        assert "provisional" in kwargs["caption"].lower()
        assert kwargs["parse_mode"] == "HTML"


# ══════════════════════════════════════════════════════════════════════════════
# Handler integration: cmd_general — podium path
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdGeneralPodiumPath:
    """cmd_general must call send_photo (not send_media_group) when render_podium returns a buffer."""

    async def test_send_photo_called_not_send_media_group(self, fake_settings):
        update = _make_update()
        ctx = _make_context(fake_settings)
        mock_client = MagicMock()
        mock_client.get_finished_groups.return_value = {"GROUP_A", "GROUP_B"}

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
                    with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
                        await cmd_general(update, ctx)

        ctx.bot.send_photo.assert_called_once()
        ctx.bot.send_media_group.assert_not_called()

    async def test_send_photo_caption_includes_grupos_cerrados_footer(self, fake_settings):
        update = _make_update()
        ctx = _make_context(fake_settings)
        mock_client = MagicMock()
        mock_client.get_finished_groups.return_value = {"GROUP_A"}

        with patch("worldcup_bot.bot.handlers.pred_loader.load", return_value=_FAKE_PREDICTIONS):
            with patch("worldcup_bot.bot.handlers.engine.compute_general_ranking", return_value=_TOP5_ROWS):
                with patch("worldcup_bot.bot.handlers.make_client", return_value=mock_client):
                    with patch("worldcup_bot.bot.handlers.render_podium", return_value=_tiny_png_buf()):
                        await cmd_general(update, ctx)

        _, kwargs = ctx.bot.send_photo.call_args
        assert "Grupos cerrados: 1/12" in kwargs["caption"]
        assert kwargs["parse_mode"] == "HTML"
