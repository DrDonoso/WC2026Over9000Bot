"""Live porra ranking tracker — separate from the daily snapshot.

State file: {state_dir}/porra_live.json
Schema: {username: {"pos": int, "pts": float, "name": str}}

All I/O is best-effort (swallow + log) so the bot never crashes on state ops.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


# ── I/O ───────────────────────────────────────────────────────────────────────


def load_live(path: str) -> dict:
    """Load live state from JSON. Returns {} if missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("porra.live.load_live: could not read %s: %s", path, exc)
        return {}


def save_live(path: str, data: dict) -> None:
    """Save live state to JSON. Creates parent dirs. Best-effort."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning("porra.live.save_live: could not write %s: %s", path, exc)


# ── state helpers ─────────────────────────────────────────────────────────────


def build_state(ranking: list) -> dict:
    """Convert a UserRankEntry list to a state dict keyed by username.

    State schema: {username: {"pos": int, "pts": float, "name": str}}
    """
    return {
        entry.username: {
            "pos": idx + 1,
            "pts": entry.total_score,
            "name": entry.display_name,
        }
        for idx, entry in enumerate(ranking)
    }


# ── diff ──────────────────────────────────────────────────────────────────────


@dataclass
class LiveDiff:
    """Structured diff between two live ranking states."""

    changed: bool
    movements: list[dict] = field(default_factory=list)
    """Users whose position and/or points changed.
    Each item: {username, name, old_pos, new_pos, old_pts, new_pts}
    """
    new_entries: list[dict] = field(default_factory=list)
    """Users present in new state but absent from old (brand-new entrants).
    Each item: {username, name, pos, pts}
    """


def diff_live(old: dict, new: dict) -> LiveDiff:
    """Compare old and new ranking states and return a structured diff.

    Users absent from old but present in new are noted as new_entries.
    Users whose position or points changed are noted as movements.
    """
    movements: list[dict] = []
    new_entries: list[dict] = []

    for username, new_data in new.items():
        if username not in old:
            new_entries.append(
                {
                    "username": username,
                    "name": new_data.get("name", f"@{username}"),
                    "pos": new_data["pos"],
                    "pts": new_data["pts"],
                }
            )
            continue

        old_data = old[username]
        pos_changed = old_data["pos"] != new_data["pos"]
        pts_changed = abs(old_data.get("pts", 0.0) - new_data["pts"]) > 0.001

        if pos_changed or pts_changed:
            movements.append(
                {
                    "username": username,
                    "name": new_data.get("name", f"@{username}"),
                    "old_pos": old_data["pos"],
                    "new_pos": new_data["pos"],
                    "old_pts": old_data.get("pts", 0.0),
                    "new_pts": new_data["pts"],
                }
            )

    changed = bool(movements or new_entries)
    return LiveDiff(changed=changed, movements=movements, new_entries=new_entries)


# ── text rendering ────────────────────────────────────────────────────────────


def render_changes_text(diff: LiveDiff) -> str:
    """Build a plain-text description of ranking changes to feed the AI.

    Returns an empty string when diff.changed is False.
    """
    if not diff.changed:
        return ""

    lines: list[str] = []

    for m in sorted(diff.movements, key=lambda x: x["new_pos"]):
        name = m["name"]
        old_pos = m["old_pos"]
        new_pos = m["new_pos"]
        pts_delta = m["new_pts"] - m["old_pts"]

        if old_pos < new_pos:
            direction = f"baja del {old_pos}º al {new_pos}º"
        elif old_pos > new_pos:
            direction = f"sube del {old_pos}º al {new_pos}º"
        else:
            direction = f"se mantiene en el {new_pos}º"

        if abs(pts_delta) > 0.001:
            lines.append(f"{name} {direction} ({pts_delta:+.1f} pts)")
        else:
            lines.append(f"{name} {direction}")

    for entry in sorted(diff.new_entries, key=lambda x: x["pos"]):
        lines.append(
            f"{entry['name']} entra en el {entry['pos']}º puesto "
            f"con {entry['pts']:.1f} pts"
        )

    return "\n".join(lines)
