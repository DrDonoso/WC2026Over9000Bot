"""Simple in-memory TTL cache keyed by URL.

Keeps football-data.org requests within the free-tier 10 req/min limit.
TTL defaults to 60 seconds.
"""

from __future__ import annotations

import time
from typing import Any

_DEFAULT_TTL = 60.0


class TTLCache:
    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        """Return cached value or None if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Store value with current timestamp."""
        self._store[key] = (time.monotonic(), value)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


_default_cache: TTLCache | None = None


def get_default_cache(ttl: float = _DEFAULT_TTL) -> TTLCache:
    """Return the process-wide shared TTLCache, creating it lazily on first call."""
    global _default_cache
    if _default_cache is None:
        _default_cache = TTLCache(ttl=ttl)
    return _default_cache


def reset_default_cache(ttl: float = _DEFAULT_TTL) -> None:
    """Test helper: replace the process-wide cache with a fresh empty instance."""
    global _default_cache
    _default_cache = TTLCache(ttl=ttl)
