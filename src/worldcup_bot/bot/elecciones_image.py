"""Knockout matrix image renderer for /elecciones.

Renders a PIL grid: rows = knockout ties, columns = participants + results.
Reuses primitives from podium_image (_circular_crop, _fetch_tile, _font, etc.).
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
from pathlib import Path

import requests as _requests
from PIL import Image, ImageDraw

from worldcup_bot.bot.podium_image import (
    _BG,
    _TEXT_GREY,
    _TEXT_WHITE,
    _fetch_tile,
    _font,
    _text_centered,
)
from worldcup_bot.data.tla_map import tla_to_iso

log = logging.getLogger(__name__)

# ── Layout constants ──────────────────────────────────────────────────────────

_HEADER_H = 76          # header row height (px)
_PHOTO_D = 42           # profile photo diameter in header (px)
_NAME_Y_GAP = 3         # gap between photo bottom and name in header (px)
_ROW_H = 42             # data row height (px)
_TIE_COL_W = 152        # tie label column width (px)
_PART_COL_W = 54        # participant column width (px)
_RESULT_COL_W = 54      # results column width (px)
_FLAG_SIZE = 26         # flag tile size for cells (px)
_ROW_BG_EVEN = (22, 27, 34)
_ROW_BG_ODD  = (30, 37, 46)
_HEADER_BG   = (12, 17, 26)
_DIVIDER     = (50, 60, 80)
_NAME_FONT_SIZE = 9
_CELL_FONT_SIZE = 10

# Twemoji CDN for standard country flag PNGs (ISO 3166-1 alpha-2 only).
_TWEMOJI_BASE = "https://cdn.jsdelivr.net/npm/twemoji@14.0.2/assets/72x72"


# ── Flag tile helpers ─────────────────────────────────────────────────────────


def _flag_url(tla: str) -> str | None:
    """Return twemoji CDN URL for the flag of a TLA, or None for unsupported codes."""
    iso = tla_to_iso(tla)
    if not iso or len(iso) != 2:
        # Non-standard codes (e.g. "GBENG" for England) use tag-sequence emoji
        # not supported by the simple regional-indicator twemoji URL.
        return None
    codepoints = "-".join(
        format(0x1F1E6 + ord(c) - ord("A"), "x")
        for c in iso.upper()
    )
    return f"{_TWEMOJI_BASE}/{codepoints}.png"


def _fetch_flag_tile(tla: str, size: int, tile_cache_dir: str | None) -> Image.Image | None:
    """Fetch a flag PNG from twemoji CDN with on-disk cache. Returns None on failure."""
    url = _flag_url(tla)
    if not url:
        return None

    cache_key = hashlib.md5(f"{url}:{size}".encode()).hexdigest()[:16]

    if tile_cache_dir:
        cache_path = Path(tile_cache_dir) / f"flag_{cache_key}.png"
        if cache_path.exists():
            try:
                return (
                    Image.open(cache_path)
                    .convert("RGBA")
                    .resize((size, size), Image.LANCZOS)
                )
            except Exception:
                pass  # stale/corrupt file — re-fetch

    try:
        resp = _requests.get(url, timeout=4)
        if resp.status_code == 200 and resp.content:
            img = (
                Image.open(io.BytesIO(resp.content))
                .convert("RGBA")
                .resize((size, size), Image.LANCZOS)
            )
            if tile_cache_dir:
                try:
                    os.makedirs(tile_cache_dir, exist_ok=True)
                    img.save(Path(tile_cache_dir) / f"flag_{cache_key}.png", format="PNG")
                except Exception:
                    pass
            return img
    except Exception:
        log.debug("_fetch_flag_tile: fetch failed for TLA=%s url=%s", tla, url)
    return None


# ── Public API ────────────────────────────────────────────────────────────────


def render_knockout_matrix(
    ties: list[tuple[str, str]],
    participants: dict,
    yaml_key: str,
    results_by_tie: dict[tuple[str, str], str | None],
    settings,
) -> io.BytesIO | None:
    """Render a knockout matrix as PNG and return a BytesIO.

    Rows  = knockout ties (home_tla · away_tla).
    Columns = participants in YAML order (circular photo header) + RESULTS column.
    Cells = flag tile for the team a participant picked to advance (or "?" text).
    Results column = winner flag (blank if tie not yet played).

    Args:
        ties: [(home_tla, away_tla), ...] ordered by match date.
        participants: YAML participants dict (insertion order preserved).
        yaml_key: e.g. "round_of_32" (used for phase label in header).
        results_by_tie: {(home, away): winner_tla | None}.
        settings: Settings (photo_base_url, state_dir).

    Returns:
        PNG BytesIO, or None on any rendering failure.
    """
    try:
        return _render(ties, participants, yaml_key, results_by_tie, settings)
    except Exception as exc:
        log.warning("render_knockout_matrix: %s", exc, exc_info=True)
        return None


def _render(
    ties: list[tuple[str, str]],
    participants: dict,
    yaml_key: str,
    results_by_tie: dict[tuple[str, str], str | None],
    settings,
) -> io.BytesIO:
    from worldcup_bot.porra.elecciones import _pick_for_tie, phase_label

    p_list = list(participants.items())
    n_users = len(p_list)
    n_ties = len(ties)
    tile_dir = str(Path(settings.state_dir) / "elecciones_tiles")

    cw = _TIE_COL_W + n_users * _PART_COL_W + _RESULT_COL_W
    ch = _HEADER_H + n_ties * _ROW_H

    canvas = Image.new("RGB", (cw, ch), _BG)
    draw = ImageDraw.Draw(canvas)
    fnt_name = _font(_NAME_FONT_SIZE)
    fnt_cell = _font(_CELL_FONT_SIZE)

    # ── Header row ────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, cw, _HEADER_H], fill=_HEADER_BG)

    # Phase label in tie column
    phase_text = phase_label(yaml_key).upper()
    _text_centered(draw, _TIE_COL_W // 2, _HEADER_H // 2, phase_text, fnt_cell, _TEXT_WHITE)

    # Profile photos + short names for each participant
    for i, (uname, udata) in enumerate(p_list):
        col_cx = _TIE_COL_W + i * _PART_COL_W + _PART_COL_W // 2
        dname = udata.get("display_name") or f"@{uname}"
        short = (dname[:5] + "…") if len(dname) > 6 else dname

        tile = _fetch_tile(uname, dname, settings.photo_base_url, _PHOTO_D, i)
        ty = max(2, (_HEADER_H - _PHOTO_D - 14) // 2)
        canvas.paste(tile, (col_cx - _PHOTO_D // 2, ty), tile)

        name_y = ty + _PHOTO_D + _NAME_Y_GAP + 4
        _text_centered(draw, col_cx, name_y, short, fnt_name, _TEXT_GREY)

    # "RES" header for results column
    res_cx = _TIE_COL_W + n_users * _PART_COL_W + _RESULT_COL_W // 2
    _text_centered(draw, res_cx, _HEADER_H // 2, "RES", fnt_cell, _TEXT_GREY)

    # Vertical dividers in header
    draw.line([(_TIE_COL_W, 0), (_TIE_COL_W, _HEADER_H)], fill=_DIVIDER, width=1)
    draw.line(
        [(cw - _RESULT_COL_W, 0), (cw - _RESULT_COL_W, _HEADER_H)],
        fill=_DIVIDER, width=1,
    )
    draw.line([(0, _HEADER_H), (cw, _HEADER_H)], fill=_DIVIDER, width=1)

    # ── Tie rows ──────────────────────────────────────────────────────────────
    for row_idx, (home_tla, away_tla) in enumerate(ties):
        y0 = _HEADER_H + row_idx * _ROW_H
        y1 = y0 + _ROW_H
        row_bg = _ROW_BG_EVEN if row_idx % 2 == 0 else _ROW_BG_ODD
        draw.rectangle([0, y0, cw, y1], fill=row_bg)
        draw.line([(0, y1 - 1), (cw, y1 - 1)], fill=_DIVIDER, width=1)

        # Tie label (TLAs only — flag tiles for the tie itself would be redundant)
        tie_text = f"{home_tla} · {away_tla}"
        _text_centered(
            draw, _TIE_COL_W // 2, y0 + _ROW_H // 2, tie_text, fnt_cell, _TEXT_WHITE
        )
        draw.line([(_TIE_COL_W, y0), (_TIE_COL_W, y1)], fill=_DIVIDER, width=1)

        # Per-participant cells
        for i, (uname, udata) in enumerate(p_list):
            col_x0 = _TIE_COL_W + i * _PART_COL_W
            cx = col_x0 + _PART_COL_W // 2
            cy = y0 + _ROW_H // 2

            picked = _pick_for_tie(udata, home_tla, away_tla, yaml_key)
            if picked is not None:
                ftile = _fetch_flag_tile(picked, _FLAG_SIZE, tile_dir)
                if ftile is not None:
                    canvas.paste(
                        ftile,
                        (cx - _FLAG_SIZE // 2, cy - _FLAG_SIZE // 2),
                        ftile,
                    )
                else:
                    # ISO code not mappable to twemoji (e.g. ENG) — show TLA text
                    _text_centered(draw, cx, cy, picked[:3], fnt_cell, _TEXT_WHITE)
            else:
                _text_centered(draw, cx, cy, "?", fnt_cell, _TEXT_GREY)

            draw.line(
                [(col_x0 + _PART_COL_W, y0), (col_x0 + _PART_COL_W, y1)],
                fill=_DIVIDER, width=1,
            )

        # Results cell
        res_x0 = _TIE_COL_W + n_users * _PART_COL_W
        res_cx2 = res_x0 + _RESULT_COL_W // 2
        res_cy = y0 + _ROW_H // 2

        winner = results_by_tie.get((home_tla, away_tla))
        if winner:
            ftile = _fetch_flag_tile(winner, _FLAG_SIZE, tile_dir)
            if ftile is not None:
                canvas.paste(
                    ftile,
                    (res_cx2 - _FLAG_SIZE // 2, res_cy - _FLAG_SIZE // 2),
                    ftile,
                )
            else:
                _text_centered(draw, res_cx2, res_cy, winner[:3], fnt_cell, _TEXT_WHITE)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf
