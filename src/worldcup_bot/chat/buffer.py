"""In-memory ring buffer for the last N group messages.

Pure — no I/O.  Shared by both picante and revive features.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any


class RingBuffer:
    """Rolling window of the last *maxlen* group messages.

    Each item is a plain dict::

        {
            "username":     str,       # Telegram @username, lowercase, no @; "" if unset
            "display_name": str,       # Telegram full name (best-effort)
            "user_id":      int,       # Telegram user id
            "text":         str,       # raw message text
            "timestamp":    datetime,  # UTC-aware
        }

    Text lives ONLY here, in RAM.  Nothing is written to disk.
    """

    def __init__(self, maxlen: int) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def append(
        self,
        *,
        username: str,
        display_name: str,
        user_id: int,
        text: str,
        timestamp: datetime,
    ) -> None:
        self._buf.append(
            {
                "username": username,
                "display_name": display_name,
                "user_id": user_id,
                "text": text,
                "timestamp": timestamp,
            }
        )

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a stable list of all buffered messages, oldest first."""
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)
