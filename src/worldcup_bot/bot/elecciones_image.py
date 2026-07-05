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
    _circular_crop,
    _fetch_tile,
    _font,
    _text_centered,
)
from worldcup_bot.data.tla_map import tla_to_iso

log = logging.getLogger(__name__)

# ── Layout constants (knockout matrix) ───────────────────────────────────────

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
_TLA_FONT_SIZE  = 7   # small TLA caption below flag tiles in tie/group labels
# Circular flag in the tie-label column:
_TIE_FLAG_D = 18      # diameter (px) — fits inside _ROW_H=42 with room for TLA below

# Twemoji flag PNGs.  The npm package does NOT ship assets under this path
# (every flag 404s), so we use the GitHub-hosted asset tree, which serves both
# the regional-indicator (2-char ISO) flags and the GB subdivision tag-sequence
# flags (England / Scotland / Wales).
_TWEMOJI_BASE = "https://cdn.jsdelivr.net/gh/twitter/twemoji@v14.0.2/assets/72x72"

# ── Tile disk-cache cap ───────────────────────────────────────────────────────

_MAX_TILE_CACHE_FILES = 200  # max flag PNG files kept on disk per state_dir

# ── Groups image layout constants ─────────────────────────────────────────────

_GROUP_HEADER_H = 76     # header row height (same as knockout)
_GROUP_CELL_H = 82       # group data row height
_GROUP_LABEL_W = 38      # group-letter column width
_GROUP_PART_COL_W = 84   # participant column width
_MINI_FLAG = 28          # flag tile size inside a 2×2 cell
_MINI_GAP = 3            # gap between flags in the 2×2 arrangement
# Alpha levels for pick weighting:
_ALPHA_FULL = 255        # picks 1 & 2 (direct qualifiers) — full brightness
_ALPHA_DIM  = 165        # pick 3 (tercero) — ~65 % — visibly dimmed
_ALPHA_FADE = 65         # not picked — ~25 % — clearly faded


# ── Tile cache helpers ────────────────────────────────────────────────────────


def _evict_tile_cache(tile_dir: str, max_files: int = _MAX_TILE_CACHE_FILES) -> None:
    """Remove oldest flag-tile cache files when the directory exceeds max_files.

    Called at the start of every render so the on-disk cache stays bounded
    throughout the tournament without any background sweep.
    """
    path = Path(tile_dir)
    if not path.exists():
        return
    files = list(path.glob("flag_*.png"))
    if len(files) <= max_files:
        return
    # Sort oldest-first and remove the surplus.
    files.sort(key=lambda f: f.stat().st_mtime)
    for f in files[: len(files) - max_files]:
        try:
            f.unlink()
        except Exception:
            pass


def _apply_alpha(img: Image.Image, alpha: int) -> Image.Image:
    """Return a copy of *img* with its alpha channel scaled by alpha/255.

    Preserves the original per-pixel alpha shape (e.g. antialiased edges)
    while globally dimming or fading the image.
    """
    img = img.convert("RGBA")
    r, g, b, a_ch = img.split()
    a_ch = a_ch.point(lambda x: x * alpha // 255)
    return Image.merge("RGBA", (r, g, b, a_ch))


# ── Flag tile helpers ─────────────────────────────────────────────────────────


def _flag_url(tla: str) -> str | None:
    """Return the twemoji CDN URL for the flag of a TLA, or None if unsupported.

    Handles two flag families:
    - Standard nations: 2-char ISO 3166-1 alpha-2 → regional-indicator pair
      (e.g. ESP → ES → ``1f1ea-1f1f8.png``).
    - GB subdivisions: 5-char ISO starting with "GB" → tag-sequence emoji
      (ENG → GBENG → ``1f3f4-e0067-e0062-e0065-e006e-e0067-e007f.png``).
      NIR (GBNIR) has no twemoji asset, so it returns None and falls back to
      TLA text via the caller.
    """
    iso = tla_to_iso(tla)
    if not iso:
        return None
    if len(iso) == 2:
        codepoints = "-".join(
            format(0x1F1E6 + ord(c) - ord("A"), "x")
            for c in iso.upper()
        )
        return f"{_TWEMOJI_BASE}/{codepoints}.png"
    # GB subdivision flags (England/Scotland/Wales) use a black-flag base
    # (1f3f4) + one tag character per ISO letter + a cancel tag (e007f).
    if len(iso) == 5 and iso.upper().startswith("GB") and iso.upper() != "GBNIR":
        tags = "-".join(format(0xE0000 + ord(c), "x") for c in iso.lower())
        return f"{_TWEMOJI_BASE}/1f3f4-{tags}-e007f.png"
    # Anything else (e.g. GBNIR — no asset) → None → caller falls back to text.
    return None


def _fetch_flag_tile(tla: str, size: int, tile_cache_dir: str | None) -> Image.Image | None:
    """Fetch a circular flag PNG from twemoji CDN with on-disk cache.

    The returned image is always RGBA with a circular alpha mask (round flag).
    The disk cache stores the raw resized image; the circular mask is applied
    in memory so old cache entries remain valid after this change.
    Returns None on failure — callers must fall back to TLA text.
    """
    url = _flag_url(tla)
    if not url:
        return None

    cache_key = hashlib.md5(f"{url}:{size}".encode()).hexdigest()[:16]

    if tile_cache_dir:
        cache_path = Path(tile_cache_dir) / f"flag_{cache_key}.png"
        if cache_path.exists():
            try:
                img = (
                    Image.open(cache_path)
                    .convert("RGBA")
                    .resize((size, size), Image.LANCZOS)
                )
                return _circular_crop(img, size)
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
                    # Cache the rectangular image; circular crop is applied on load.
                    img.save(Path(tile_cache_dir) / f"flag_{cache_key}.png", format="PNG")
                except Exception:
                    pass
            return _circular_crop(img, size)
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
    _evict_tile_cache(tile_dir)

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

        # Tie label: circular flag for each team + small TLA caption below.
        # Falls back to TLA text when a flag cannot be fetched (e.g. non-standard
        # ISO codes like GBENG for England).
        fnt_tla = _font(_TLA_FONT_SIZE)
        home_cx = _TIE_COL_W // 4         # 38 px
        away_cx = 3 * _TIE_COL_W // 4     # 114 px
        mid_cx  = _TIE_COL_W // 2         # 76 px — separator "·"
        flag_y  = y0 + (_ROW_H - _TIE_FLAG_D) // 2   # vertically centred flag top
        tla_y   = flag_y + _TIE_FLAG_D + 3             # TLA text centre (below flag)

        home_flag = _fetch_flag_tile(home_tla, _TIE_FLAG_D, tile_dir)
        if home_flag is not None:
            canvas.paste(home_flag, (home_cx - _TIE_FLAG_D // 2, flag_y), home_flag)
            _text_centered(draw, home_cx, tla_y + 4, home_tla, fnt_tla, _TEXT_GREY)
        else:
            _text_centered(draw, home_cx, y0 + _ROW_H // 2, home_tla, fnt_cell, _TEXT_WHITE)

        _text_centered(draw, mid_cx, y0 + _ROW_H // 2, "·", fnt_cell, _TEXT_GREY)

        away_flag = _fetch_flag_tile(away_tla, _TIE_FLAG_D, tile_dir)
        if away_flag is not None:
            canvas.paste(away_flag, (away_cx - _TIE_FLAG_D // 2, flag_y), away_flag)
            _text_centered(draw, away_cx, tla_y + 4, away_tla, fnt_tla, _TEXT_GREY)
        else:
            _text_centered(draw, away_cx, y0 + _ROW_H // 2, away_tla, fnt_cell, _TEXT_WHITE)

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


# ── Groups image ──────────────────────────────────────────────────────────────


def render_groups_matrix(
    group_compositions: dict[str, list[str]],
    participants: dict,
    settings,
) -> io.BytesIO | None:
    """Render a grupos 2×2 matrix as PNG and return a BytesIO.

    This is a CPU-bound PIL function.  Always call via ``asyncio.to_thread``
    to avoid blocking the Telegram event loop.  It is a short-lived, single
    invocation — not a background loop or persistent thread — so it carries
    no risk of runaway CPU/RAM usage.

    Rows    = groups A–L (12 rows).
    Columns = participants in YAML order (circular profile-photo headers).
    Cells   = 2×2 flag grid of the 4 teams in that group (API standings order).

    Visual weighting per team in a cell:
        - Participant's predicted 1st and 2nd → full brightness (alpha 255).
        - Participant's predicted 3rd (tercero) → intermediate (alpha ~65 %).
        - Unpicked team → clearly faded (alpha ~25 %).

    Note: a separate "terceros strip" was considered but not added — the
    intermediate-alpha rendering in each cell already makes tercero picks
    clearly visible, and fitting 12 tercero flags into an 84 px column cleanly
    is not feasible.

    Args:
        group_compositions: {letter: [tla, tla, tla, tla]} in standings order,
            built from ``get_standings()`` via ``build_group_compositions()``.
        participants: YAML participants dict (insertion order = column order).
        settings: Settings (photo_base_url, state_dir).

    Returns:
        PNG BytesIO, or None on any rendering failure.
    """
    try:
        return _render_groups(group_compositions, participants, settings)
    except Exception as exc:
        log.warning("render_groups_matrix: %s", exc, exc_info=True)
        return None


def _render_groups(
    group_compositions: dict[str, list[str]],
    participants: dict,
    settings,
) -> io.BytesIO:
    from worldcup_bot.data.stages import GROUPS as GROUP_LETTERS

    p_list = list(participants.items())
    n_users = len(p_list)
    tile_dir = str(Path(settings.state_dir) / "elecciones_tiles")
    _evict_tile_cache(tile_dir)

    cw = _GROUP_LABEL_W + n_users * _GROUP_PART_COL_W
    ch = _GROUP_HEADER_H + len(GROUP_LETTERS) * _GROUP_CELL_H

    canvas = Image.new("RGB", (cw, ch), _BG)
    draw = ImageDraw.Draw(canvas)
    fnt_name = _font(_NAME_FONT_SIZE)
    fnt_cell = _font(_CELL_FONT_SIZE)

    # ── Header row ────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, cw, _GROUP_HEADER_H], fill=_HEADER_BG)
    _text_centered(
        draw, _GROUP_LABEL_W // 2, _GROUP_HEADER_H // 2, "GRUPOS", fnt_cell, _TEXT_WHITE
    )

    for i, (uname, udata) in enumerate(p_list):
        col_cx = _GROUP_LABEL_W + i * _GROUP_PART_COL_W + _GROUP_PART_COL_W // 2
        dname = udata.get("display_name") or f"@{uname}"
        short = (dname[:5] + "…") if len(dname) > 6 else dname

        tile = _fetch_tile(uname, dname, settings.photo_base_url, _PHOTO_D, i)
        ty = max(2, (_GROUP_HEADER_H - _PHOTO_D - 14) // 2)
        canvas.paste(tile, (col_cx - _PHOTO_D // 2, ty), tile)
        name_y = ty + _PHOTO_D + _NAME_Y_GAP + 4
        _text_centered(draw, col_cx, name_y, short, fnt_name, _TEXT_GREY)

    draw.line([(0, _GROUP_HEADER_H), (cw, _GROUP_HEADER_H)], fill=_DIVIDER, width=1)
    draw.line([(_GROUP_LABEL_W, 0), (_GROUP_LABEL_W, _GROUP_HEADER_H)], fill=_DIVIDER, width=1)

    # ── Group rows (A–L) ──────────────────────────────────────────────────────
    # Inner 2×2 grid dimensions (px)
    _inner_w = 2 * _MINI_FLAG + _MINI_GAP
    _inner_h = 2 * _MINI_FLAG + _MINI_GAP

    for row_idx, grp_letter in enumerate(GROUP_LETTERS):
        y0 = _GROUP_HEADER_H + row_idx * _GROUP_CELL_H
        y1 = y0 + _GROUP_CELL_H
        row_bg = _ROW_BG_EVEN if row_idx % 2 == 0 else _ROW_BG_ODD
        draw.rectangle([0, y0, cw, y1], fill=row_bg)
        draw.line([(0, y1 - 1), (cw, y1 - 1)], fill=_DIVIDER, width=1)

        # Group letter label
        _text_centered(
            draw, _GROUP_LABEL_W // 2, (y0 + y1) // 2, grp_letter, fnt_cell, _TEXT_WHITE
        )
        draw.line([(_GROUP_LABEL_W, y0), (_GROUP_LABEL_W, y1)], fill=_DIVIDER, width=1)

        # API group composition (4 teams in standings position order)
        grp_teams = [t.upper() for t in group_compositions.get(grp_letter, [])]

        for i, (uname, udata) in enumerate(p_list):
            col_x0 = _GROUP_LABEL_W + i * _GROUP_PART_COL_W
            col_x1 = col_x0 + _GROUP_PART_COL_W

            picks = udata.get("groups", {}).get(grp_letter, [])
            p1 = (picks[0] if picks else "**").upper()
            p2 = (picks[1] if len(picks) > 1 else "**").upper()
            p3 = (picks[2] if len(picks) > 2 else "**").upper()

            # Top-left of the centered 2×2 grid inside the cell
            ox = col_x0 + (_GROUP_PART_COL_W - _inner_w) // 2
            oy = y0 + (_GROUP_CELL_H - _inner_h) // 2

            # (column, row) → pixel offset for each of the 4 positions
            flag_positions = [
                (ox,                      oy),                       # TL
                (ox + _MINI_FLAG + _MINI_GAP, oy),                   # TR
                (ox,                      oy + _MINI_FLAG + _MINI_GAP),  # BL
                (ox + _MINI_FLAG + _MINI_GAP, oy + _MINI_FLAG + _MINI_GAP),  # BR
            ]

            for j, tla in enumerate(grp_teams[:4]):
                if j >= len(flag_positions):
                    break

                if tla == p1 and p1 != "**":
                    alpha = _ALPHA_FULL
                elif tla == p2 and p2 != "**":
                    alpha = _ALPHA_FULL
                elif tla == p3 and p3 != "**":
                    alpha = _ALPHA_DIM
                else:
                    alpha = _ALPHA_FADE

                px, py = flag_positions[j]
                ftile = _fetch_flag_tile(tla, _MINI_FLAG, tile_dir)
                if ftile is not None:
                    if alpha < 255:
                        ftile = _apply_alpha(ftile, alpha)
                    canvas.paste(ftile, (px, py), ftile)
                else:
                    # ISO code not mappable to twemoji — show TLA text
                    txt_color = _TEXT_WHITE if alpha >= _ALPHA_DIM else _TEXT_GREY
                    _text_centered(
                        draw,
                        px + _MINI_FLAG // 2,
                        py + _MINI_FLAG // 2,
                        tla[:3],
                        fnt_cell,
                        txt_color,
                    )

            # Right-edge vertical divider for this participant column
            draw.line([(col_x1, y0), (col_x1, y1)], fill=_DIVIDER, width=1)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf
