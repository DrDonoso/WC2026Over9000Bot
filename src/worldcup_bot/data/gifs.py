"""GIF/animation helpers for /tongo hot-reload pool."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_TONGO_GIF_SUFFIXES = {".gif", ".mp4", ".webp"}


def list_tongo_gifs(gifs_dir: Path) -> list[Path]:
    """Return sorted list of supported animation files in *gifs_dir*.

    Never raises — if the directory doesn't exist or can't be read, returns [].
    Called fresh on every /tongo so adding a file on the server takes effect
    immediately without a bot restart.
    """
    try:
        return sorted(
            p for p in gifs_dir.iterdir() if p.suffix.lower() in _TONGO_GIF_SUFFIXES
        )
    except Exception as exc:
        log.debug("list_tongo_gifs: could not read %s: %s", gifs_dir, exc)
        return []
