"""Podium image renderer for ranking commands.

Generates a single composite PNG showing the top-3 ranked participants
on a classic podium layout with circular photo tiles, a real crown asset
(Noto Emoji crown, Apache-2.0) and tie-aware position numbers.

Usage (from an async handler)::

    from worldcup_bot.bot.podium_image import render_podium

    buf = await asyncio.to_thread(render_podium, participants, settings)
    if buf is not None:
        await context.bot.send_photo(chat_id=..., photo=buf, caption=..., parse_mode="HTML")
"""

from __future__ import annotations

import io
import logging
from importlib.resources import files

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# ── Visual constants ──────────────────────────────────────────────────────────

_CANVAS_W = 720
_CANVAS_H = 400

_TILE_D = 180            # circle diameter (px)
_TILE_R = _TILE_D // 2   # circle radius

# Y-center of each tile (from canvas top) per competition position
_TILE_CY: dict[int, int] = {1: 205, 2: 237, 3: 257}
_TILE_CY_DEFAULT = 257

# Column x-centers keyed by participant count
_COL_X: dict[int, list[int]] = {
    1: [360],
    2: [240, 480],
    3: [180, 360, 540],
}

# Crown geometry
_CROWN_ASSET_SIZE = 56   # target size (px) when scaling the emoji crown asset
_CROWN_H = 40            # height of the fallback drawn crown
_CROWN_GAP = 22          # gap between crown bottom and tile top; position label drawn here
_CROWN_HW = 40           # half-width of fallback drawn crown

# Colors
_BG = (22, 27, 34)
_CROWN_GOLD = (255, 215, 0)
_CROWN_DARK = (160, 128, 0)
_JEWEL = (220, 80, 50)
_TEXT_WHITE = (255, 255, 255)
_TEXT_GREY = (200, 200, 200)

_PLACEHOLDER_PALETTE = [
    (70, 130, 180),
    (46, 139, 87),
    (178, 34, 34),
]

# ── Crown asset loader ────────────────────────────────────────────────────────


def _load_crown_asset() -> Image.Image | None:
    """Load crown.png from the worldcup_bot package assets.

    Uses ``importlib.resources.files`` so it works from both a source checkout
    and a pip-installed (Docker) package.  Returns ``None`` on any failure so
    the hand-drawn crown is used as fallback.
    """
    try:
        resource = files("worldcup_bot") / "assets" / "crown.png"
        return Image.open(io.BytesIO(resource.read_bytes())).convert("RGBA")
    except Exception:
        return None


_CROWN_IMG: Image.Image | None = _load_crown_asset()

# ── Font loading ──────────────────────────────────────────────────────────────


def _resolve_font_path() -> str | None:
    try:
        from matplotlib.font_manager import findfont, FontProperties  # noqa: PLC0415
        return findfont(FontProperties(family="DejaVu Sans", weight="bold"))
    except Exception:
        return None


_FONT_PATH: str | None = _resolve_font_path()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if _FONT_PATH:
        try:
            return ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── Drawing primitives ────────────────────────────────────────────────────────


def _text_centered(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, text: str, font, color
) -> None:
    """Draw *text* with its visual center at *(cx, cy)*."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        x = cx - (bbox[2] - bbox[0]) // 2 - bbox[0]
        y = cy - (bbox[3] - bbox[1]) // 2 - bbox[1]
    except AttributeError:
        x, y = cx - 5, cy - 7
    draw.text((x, y), text, font=font, fill=color)


def _circular_crop(img: Image.Image, diameter: int) -> Image.Image:
    """Resize *img* to *diameter × diameter* and apply a circular alpha mask."""
    img = img.resize((diameter, diameter), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    img.putalpha(mask)
    return img


def _initials(display_name: str) -> str:
    parts = display_name.strip().split()
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _placeholder_tile(display_name: str, diameter: int, color_idx: int) -> Image.Image:
    """Solid colored circle with the participant's initials centered."""
    color = _PLACEHOLDER_PALETTE[color_idx % len(_PLACEHOLDER_PALETTE)]
    img = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=(*color, 255))
    fnt = _font(diameter // 3)
    _text_centered(draw, diameter // 2, diameter // 2, _initials(display_name), fnt, _TEXT_WHITE)
    return img


def _paste_crown_asset(canvas: Image.Image, cx: int, tile_y: int) -> None:
    """Scale and alpha-composite the real crown asset above the tile.

    The crown is centered at *cx* with its bottom edge ``_CROWN_GAP`` px above
    *tile_y* (the tile's top edge), leaving room for the position-number label.
    """
    crown = _CROWN_IMG.resize((_CROWN_ASSET_SIZE, _CROWN_ASSET_SIZE), Image.LANCZOS)
    x = cx - _CROWN_ASSET_SIZE // 2
    y = tile_y - _CROWN_GAP - _CROWN_ASSET_SIZE
    canvas.paste(crown, (x, y), crown)


def _draw_crown(draw: ImageDraw.ImageDraw, cx: int, y_top: int) -> None:
    """Fallback: draw a filled gold crown programmatically (no asset required).

    The crown is a single filled polygon (band + 3 upward spikes) with small
    jewel circles at the spike tips.
    """
    hw = _CROWN_HW
    h = _CROWN_H
    y0 = y_top
    y1 = y_top + h * 2 // 5
    y2 = y_top + h * 3 // 5
    y3 = y_top + h

    pts = [
        (cx - hw, y3),
        (cx - hw, y2),
        (cx - hw // 2, y1),
        (cx - hw // 4, y2),
        (cx - hw // 5, y2),
        (cx, y0),
        (cx + hw // 5, y2),
        (cx + hw // 4, y2),
        (cx + hw // 2, y1),
        (cx + hw, y2),
        (cx + hw, y3),
    ]
    draw.polygon(pts, fill=_CROWN_GOLD, outline=_CROWN_DARK)

    for jx, jy, r in [
        (cx - hw // 2, y1, 3),
        (cx, y0, 4),
        (cx + hw // 2, y1, 3),
    ]:
        draw.ellipse([jx - r, jy - r, jx + r, jy + r], fill=_JEWEL, outline=_CROWN_DARK)


def _fetch_tile(
    username: str, display_name: str, base_url: str, diameter: int, color_idx: int
) -> Image.Image:
    """Return a circular photo tile, or an initials placeholder if the photo is unavailable."""
    url = f"{base_url.rstrip('/')}/{username}.png"
    try:
        resp = requests.get(url, timeout=4)
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            return _circular_crop(img, diameter)
    except Exception:
        pass
    return _placeholder_tile(display_name, diameter, color_idx)


# ── Layout ────────────────────────────────────────────────────────────────────


def _render_podium(participants: list[dict], settings) -> io.BytesIO:
    n = min(len(participants), 3)
    participants = participants[:n]

    tiles = [
        _fetch_tile(
            p["username"], p["display_name"], settings.photo_base_url, _TILE_D, i
        )
        for i, p in enumerate(participants)
    ]

    canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), _BG)
    draw = ImageDraw.Draw(canvas)

    col_xs = _COL_X.get(n, _COL_X[3])

    # Classic podium column assignment for 3 participants:
    #   left column   → index 1 (2nd place)
    #   center column → index 0 (1st place, raised)
    #   right column  → index 2 (3rd place)
    # For ties (e.g. 1,1,3): tied participants share the same tile height.
    # For n<3: keep input order left-to-right.
    display_order = [1, 0, 2] if n == 3 else list(range(n))

    fnt_pos = _font(22)
    fnt_name = _font(16)

    for col_idx, p_idx in enumerate(display_order):
        p = participants[p_idx]
        tile = tiles[p_idx]
        cx = col_xs[col_idx]
        pos = p.get("position", col_idx + 1)

        tile_cy = _TILE_CY.get(pos, _TILE_CY_DEFAULT)
        tile_x = cx - _TILE_R
        tile_y = tile_cy - _TILE_R

        # Crown above tile: asset if available, drawn fallback otherwise
        if _CROWN_IMG is not None:
            _paste_crown_asset(canvas, cx, tile_y)
        else:
            crown_top = tile_y - _CROWN_H - _CROWN_GAP
            _draw_crown(draw, cx, crown_top)

        # Position number centered in the gap between crown bottom and tile top
        pos_label_y = tile_y - _CROWN_GAP // 2
        _text_centered(draw, cx, pos_label_y, str(pos), fnt_pos, _TEXT_WHITE)

        # Paste circular photo tile (RGBA with circular mask) onto RGB canvas
        canvas.paste(tile, (tile_x, tile_y), tile)

        # Participant name below tile
        name = p.get("display_name", "")
        if len(name) > 14:
            name = name[:13] + "…"
        name_y = tile_y + _TILE_D + 14
        _text_centered(draw, cx, name_y, name, fnt_name, _TEXT_GREY)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Public API ────────────────────────────────────────────────────────────────


def render_podium(participants: list[dict], settings) -> io.BytesIO | None:
    """Render a podium image for up to 3 participants.

    Args:
        participants: list of dicts, each with:
            - ``"username"`` (str): used to build photo URL
            - ``"display_name"`` (str): shown below the tile
            - ``"position"`` (int): tie-aware competition position (e.g. 1, 1, 3)
        settings: Settings instance with ``photo_base_url``.

    Returns:
        A PNG ``BytesIO`` ready for ``context.bot.send_photo``,
        or ``None`` on any rendering failure (caller should fall back).

    This function is synchronous; call it via ``asyncio.to_thread`` from async code.
    """
    if not participants:
        return None
    try:
        return _render_podium(participants, settings)
    except Exception as exc:
        log.warning("render_podium failed: %s", exc, exc_info=True)
        return None
