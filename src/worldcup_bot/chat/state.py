"""ChatState — persisted metadata for chat features.

Stores ONLY timing/counter metadata to disk (no message text).

Atomic temp-file-replace pattern mirrors endirecto_store._save_store.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ChatState:
    """All metadata that must survive bot restarts.  NO message text stored here."""

    last_seen: dict[str, str] = field(default_factory=dict)
    """username → ISO-8601 UTC timestamp of the user's last message."""

    last_mentioned: dict[str, str] = field(default_factory=dict)
    """username → ISO-8601 UTC timestamp of the last revive @mention sent."""

    picante_last_ts: float = 0.0
    """Unix timestamp of the last successful picante reply."""

    picante_daily_count: int = 0
    """Number of picante replies sent today (keyed to picante_last_date)."""

    picante_last_date: str = ""
    """'YYYY-MM-DD' (local tz) — the date picante_daily_count belongs to."""

    rotate_index: int = 0
    """Round-robin cursor for selecting the next revive candidate."""


def load_chat_state(path: str) -> ChatState:
    """Load ChatState from JSON at *path*.  Never raises.

    Returns a fresh empty ChatState if the file is missing, empty, or corrupt.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return ChatState(
            last_seen=dict(data.get("last_seen") or {}),
            last_mentioned=dict(data.get("last_mentioned") or {}),
            picante_last_ts=float(data.get("picante_last_ts") or 0.0),
            picante_daily_count=int(data.get("picante_daily_count") or 0),
            picante_last_date=str(data.get("picante_last_date") or ""),
            rotate_index=int(data.get("rotate_index") or 0),
        )
    except FileNotFoundError:
        return ChatState()
    except Exception as exc:
        log.warning(
            "load_chat_state(%s) failed: %s — starting with empty state", path, exc
        )
        return ChatState()


def save_chat_state(path: str, state: ChatState) -> None:
    """Persist ChatState to JSON atomically (temp-file replace).  Best-effort: never raises."""
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "last_seen": state.last_seen,
                    "last_mentioned": state.last_mentioned,
                    "picante_last_ts": state.picante_last_ts,
                    "picante_daily_count": state.picante_daily_count,
                    "picante_last_date": state.picante_last_date,
                    "rotate_index": state.rotate_index,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(tmp, path)
    except Exception as exc:
        log.warning("save_chat_state(%s) failed: %s", path, exc)
