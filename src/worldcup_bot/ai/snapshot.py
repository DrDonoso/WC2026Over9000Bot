"""Snapshot module: tracks provisional porra ranking positions across days.

File schema (JSON):
    { "YYYY-MM-DD": { username: position(int) }, ... }
    Keeps only the last 7 dates (pruned on each save).

All functions are path-injected for testability.
Failures in I/O are swallowed + logged so the bot never crashes on state ops.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_MAX_DATES = 7


@dataclass
class Movement:
    """A position change for one participant between two snapshots."""

    username: str
    display_name: str
    old_pos: int
    new_pos: int
    delta: int  # old_pos - new_pos; positive = climbed, negative = dropped


# ── I/O ───────────────────────────────────────────────────────────────────────


def load_snapshots(path: str) -> dict:
    """Load snapshot data from JSON file. Returns {} if missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("snapshot.load_snapshots: could not read %s: %s", path, exc)
        return {}


def save_snapshots(path: str, data: dict) -> None:
    """Save snapshot data to JSON file. Creates parent dirs. Best-effort — swallows errors."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning("snapshot.save_snapshots: could not write %s: %s", path, exc)


# ── logic ─────────────────────────────────────────────────────────────────────


def compute_movements(
    baseline: dict[str, int],
    current: dict[str, int],
    names: dict[str, str],
) -> list[Movement]:
    """Return position changes between baseline and current.

    baseline: {username: position}
    current:  {username: position}
    names:    {username: display_name}

    Users absent from baseline are skipped.
    Users with no positional change are omitted.
    Results are sorted ascending by new_pos.
    """
    movements: list[Movement] = []
    for username, new_pos in current.items():
        if username not in baseline:
            continue
        old_pos = baseline[username]
        if old_pos == new_pos:
            continue
        movements.append(
            Movement(
                username=username,
                display_name=names.get(username, f"@{username}"),
                old_pos=old_pos,
                new_pos=new_pos,
                delta=old_pos - new_pos,
            )
        )
    return sorted(movements, key=lambda m: m.new_pos)


def update_and_diff(
    path: str,
    today_date: str,
    current_positions: dict[str, int],
) -> tuple[dict | None, dict]:
    """Load snapshots, find baseline (most recent date < today_date), update and save.

    1. Load snapshots from *path* (or {} on first run).
    2. baseline = positions from the most-recent stored date strictly < today_date
       (or None if no prior date exists).
    3. Overwrite snapshots[today_date] = current_positions.
    4. Prune so only the most-recent _MAX_DATES dates are kept.
    5. Save.

    Returns (baseline_positions_or_None, updated_snapshots_dict).
    """
    snapshots = load_snapshots(path)

    past_dates = sorted(d for d in snapshots if d < today_date)
    baseline: dict | None = snapshots[past_dates[-1]] if past_dates else None

    snapshots[today_date] = current_positions

    all_dates = sorted(snapshots.keys())
    if len(all_dates) > _MAX_DATES:
        for old_date in all_dates[:-_MAX_DATES]:
            del snapshots[old_date]

    save_snapshots(path, snapshots)
    return baseline, snapshots
