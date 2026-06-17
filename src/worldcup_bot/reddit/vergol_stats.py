"""Persistent per-user 'Ver gol' view counter.

Stores data in {state_dir}/vergol_stats.json.

Schema::

    {
        "<user_id>": {
            "name":   "<display name>",
            "tokens": ["<goal token>", ...]
        },
        ...
    }

count = len(distinct tokens) for that user.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def load_stats(path: str) -> dict:
    """Load vergol stats from JSON.  Returns {} on missing or corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("load_stats(%s) failed: %s", path, exc)
        return {}


def save_stats(path: str, data: dict) -> None:
    """Persist vergol stats to JSON.  Best-effort — swallows and logs on failure."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:
        log.warning("save_stats(%s) failed: %s", path, exc)


def record_view(data: dict, user_id: int | str, name: str, token: str) -> bool:
    """Record that a user watched a goal clip.

    Dedupes per (user, token): adding the same token twice has no effect.
    Always updates the stored display name to the latest value.

    Returns True if this was a new (not previously seen) view for this user.
    """
    key = str(user_id)
    entry = data.setdefault(key, {"name": name, "tokens": []})
    entry["name"] = name
    if token in entry["tokens"]:
        return False
    entry["tokens"].append(token)
    return True


def leaderboard(data: dict) -> list[tuple[str, int]]:
    """Return (name, distinct_goal_count) pairs sorted by count desc, name asc."""
    rows = [
        (entry["name"], len(entry["tokens"]))
        for entry in data.values()
        if entry.get("tokens")
    ]
    return sorted(rows, key=lambda x: (-x[1], x[0]))
