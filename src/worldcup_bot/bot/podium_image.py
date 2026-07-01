"""Podium image renderer for ranking commands.

Generates a single composite PNG showing the top-3 ranked participants on a
classic podium layout.  Each participant is rendered as a vertical stack:
  crown (emoji asset or drawn fallback)
    ↓ overlaps photo top
  circular photo (or initials placeholder)
    ↓ rests on block top with slight overlap
  podium block (coloured pedestal with position number)

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

# ── Tunable layout constants ──────────────────────────────────────────────────
# All magic numbers live here so they can be adjusted after a visual preview.

# Canvas
_CANVAS_W = 760
_CANVAS_H = 560
_BG = (22, 27, 34)           # dark navy background

# Podium blocks
_BLOCK_W = 200               # width of every block column (px)
_BLOCK_GAP = 8               # horizontal gap between blocks (px)
_BLOCK_HEIGHT = {1: 175, 2: 120, 3: 85}   # height by competition position
_BLOCK_HEIGHT_DEFAULT = 85
_BLOCK_COLOR = {
    1: (230, 184, 0),        # gold   ~#E6B800
    2: (192, 192, 192),      # silver ~#C0C0C0
    3: (205, 127, 50),       # bronze ~#CD7F32
}
_BLOCK_COLOR_DEFAULT = (205, 127, 50)
_BLOCK_DARK_COLOR = {        # darker shade for the top-edge depth strip
    1: (178, 140, 0),
    2: (148, 148, 148),
    3: (152, 95, 28),
}
_BLOCK_DARK_COLOR_DEFAULT = (152, 95, 28)
_BLOCK_TOP_INSET = 5         # height of the darker top-edge strip (px)
_FLOOR_Y = 420               # y-coordinate where all block bottoms sit

# Position number drawn on the block front
_BLOCK_NUM_FONT_SIZE = 60
_BLOCK_NUM_COLOR = (30, 25, 20)   # dark — readable on bright blocks

# Photo circle (the "head")
_PHOTO_D = 150               # circle diameter (px)
_PHOTO_R = _PHOTO_D // 2
_PHOTO_OVERLAP = 10          # px the photo's bottom edge dips into the block top

# Crown — emoji asset path
_CROWN_ASSET_SIZE = 105      # target size when scaling the crown asset (≈ 0.7 × _PHOTO_D)
_CROWN_OVERLAP = 30          # px the asset crown's bottom overlaps the photo top

# Crown — programmatic drawn fallback
_CROWN_H = 40                # height of the drawn-crown polygon
_CROWN_HW = 40               # half-width of the drawn-crown polygon
_DRAWN_CROWN_OVERLAP = 10    # px the drawn crown's bottom overlaps the photo top

# Other crown colors (used by drawn fallback)
_CROWN_GOLD = (255, 215, 0)
_CROWN_DARK = (160, 128, 0)
_JEWEL = (220, 80, 50)

# Participant name label
_NAME_FONT_SIZE = 16
_NAME_Y_OFFSET = 28          # px below _FLOOR_Y to the name text centre

# General colors
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
    """Draw *text* with its visual centre at *(cx, cy)*."""
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
    """Solid coloured circle with the participant's initials centred."""
    color = _PLACEHOLDER_PALETTE[color_idx % len(_PLACEHOLDER_PALETTE)]
    img = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=(*color, 255))
    fnt = _font(diameter // 3)
    _text_centered(draw, diameter // 2, diameter // 2, _initials(display_name), fnt, _TEXT_WHITE)
    return img


def _paste_crown_asset(canvas: Image.Image, cx: int, photo_top_y: int) -> None:
    """Alpha-composite the crown asset onto the canvas, worn on the photo's head.

    The crown is centred at *cx*; its bottom edge overlaps the photo's top
    edge by ``_CROWN_OVERLAP`` px, giving the "crown on head" look.
    """
    crown = _CROWN_IMG.resize((_CROWN_ASSET_SIZE, _CROWN_ASSET_SIZE), Image.LANCZOS)
    x = cx - _CROWN_ASSET_SIZE // 2
    y = photo_top_y + _CROWN_OVERLAP - _CROWN_ASSET_SIZE
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
    """Return a circular photo tile, or an initials placeholder if unavailable."""
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


def _col_x_starts(n: int) -> list[int]:
    """Return the left x-coordinate of each block column for *n* participants."""
    total_w = n * _BLOCK_W + (n - 1) * _BLOCK_GAP
    left_margin = (_CANVAS_W - total_w) // 2
    return [left_margin + i * (_BLOCK_W + _BLOCK_GAP) for i in range(n)]


def _render_podium(participants: list[dict], settings) -> io.BytesIO:
    n = min(len(participants), 3)
    participants = participants[:n]

    # Fetch photo tiles (circular crop or initials placeholder)
    tiles = [
        _fetch_tile(p["username"], p["display_name"], settings.photo_base_url, _PHOTO_D, i)
        for i, p in enumerate(participants)
    ]

    canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), _BG)
    draw = ImageDraw.Draw(canvas)

    # Classic podium column assignment for 3 participants:
    #   left column   → participants[1] (2nd place)
    #   centre column → participants[0] (1st place — tallest block)
    #   right column  → participants[2] (3rd place)
    # For n < 3: left-to-right in input order.
    display_order = [1, 0, 2] if n == 3 else list(range(n))

    x_starts = _col_x_starts(n)
    fnt_block_num = _font(_BLOCK_NUM_FONT_SIZE)
    fnt_name = _font(_NAME_FONT_SIZE)

    for col_idx, p_idx in enumerate(display_order):
        p = participants[p_idx]
        tile = tiles[p_idx]
        pos = p.get("position", col_idx + 1)
        cx = x_starts[col_idx] + _BLOCK_W // 2
        x0 = x_starts[col_idx]
        x1 = x0 + _BLOCK_W

        # ── 1. Podium block ───────────────────────────────────────────────────
        block_h = _BLOCK_HEIGHT.get(pos, _BLOCK_HEIGHT_DEFAULT)
        block_top = _FLOOR_Y - block_h
        block_color = _BLOCK_COLOR.get(pos, _BLOCK_COLOR_DEFAULT)
        block_dark = _BLOCK_DARK_COLOR.get(pos, _BLOCK_DARK_COLOR_DEFAULT)

        draw.rectangle([x0, block_top, x1, _FLOOR_Y], fill=block_color)
        # Subtle darker top-edge for depth
        draw.rectangle([x0, block_top, x1, block_top + _BLOCK_TOP_INSET], fill=block_dark)

        # Position number centred on block front
        block_mid_y = (block_top + _FLOOR_Y) // 2
        _text_centered(draw, cx, block_mid_y, str(pos), fnt_block_num, _BLOCK_NUM_COLOR)

        # ── 2. Photo circle resting on block top ──────────────────────────────
        # photo_bottom overlaps slightly into the block top (_PHOTO_OVERLAP px)
        photo_bottom = block_top + _PHOTO_OVERLAP
        photo_top = photo_bottom - _PHOTO_D
        canvas.paste(tile, (cx - _PHOTO_R, photo_top), tile)

        # ── 3. Crown worn on the photo's head ─────────────────────────────────
        if _CROWN_IMG is not None:
            _paste_crown_asset(canvas, cx, photo_top)
        else:
            drawn_crown_top = photo_top + _DRAWN_CROWN_OVERLAP - _CROWN_H
            _draw_crown(draw, cx, drawn_crown_top)

        # ── 4. Participant name below the floor ───────────────────────────────
        name = p.get("display_name", "")
        if len(name) > 14:
            name = name[:13] + "…"
        _text_centered(draw, cx, _FLOOR_Y + _NAME_Y_OFFSET, name, fnt_name, _TEXT_GREY)

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
            - ``"display_name"`` (str): shown below the block
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
