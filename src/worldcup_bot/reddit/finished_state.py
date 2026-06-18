"""Persistent dedup state for finished-match recaps.

Stores the set of match ids already recapped (or seeded as already-handled)
to `{state_dir}/finished_announced.json` so that container restarts never
re-fire a "🏁 Final" recap for a match that ended before the restart.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def load_finished(path: str) -> set[int]:
    """Load the set of already-announced match ids from JSON.  Never raises.

    Returns an empty set if the file is missing, empty, or corrupt.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(x) for x in data}
    except FileNotFoundError:
        return set()
    except Exception as exc:
        log.warning("load_finished(%s) failed: %s — starting with empty set", path, exc)
        return set()


def save_finished(path: str, ids: set[int]) -> None:
    """Persist the set of announced match ids to JSON.  Best-effort: never raises."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(ids), f)
    except Exception as exc:
        log.warning("save_finished(%s) failed: %s", path, exc)
