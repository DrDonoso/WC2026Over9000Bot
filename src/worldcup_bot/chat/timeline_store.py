"""Chronological timeline of ALL group messages for picante profiles.

Single JSONL file at {state_dir}/picante_timeline.jsonl
Each line: {"ts": "<ISO-8601 UTC>", "username": "<str>", "text": "<str>"}

Refinement 3: a shared conversational timeline (not per-user files) so the
profile updater sees users IN CONTEXT — threads, banter between users, dynamics.

Privacy note: text only written when PICANTE_STORE_TEXT=True and PICANTE_PROFILES_ENABLED=1.
2-day sliding window (PICANTE_PROFILES_WINDOW_DAYS default=2); trim-on-write.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

log = logging.getLogger(__name__)

_TIMELINE_FILENAME = "picante_timeline.jsonl"
_LAST_RUN_FILENAME = "picante_profiles_last_run.json"

# Injectable clock — tests can override with a fixed datetime
_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def _timeline_path(state_dir: str) -> str:
    return os.path.join(state_dir, _TIMELINE_FILENAME)


def _last_run_path(state_dir: str) -> str:
    return os.path.join(state_dir, _LAST_RUN_FILENAME)


def append_message(
    state_dir: str,
    username: str,
    text: str,
    ts: datetime,
    *,
    store_text: bool = True,
    window_days: int = 2,
) -> None:
    """Append one message to the timeline.  Best-effort — never raises.

    No-op when:
    - username is empty
    - store_text is False
    """
    if not username or not store_text:
        return
    try:
        path = _timeline_path(state_dir)
        os.makedirs(state_dir, exist_ok=True)
        entry = json.dumps({"ts": ts.isoformat(), "username": username, "text": text}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
        _trim_timeline(path, window_days=window_days)
    except Exception as exc:
        log.warning("timeline_store.append_message failed: %s", exc)


def _trim_timeline(path: str, *, window_days: int) -> None:
    """Rewrite timeline keeping only entries within window_days.  Best-effort."""
    try:
        cutoff = _now() - timedelta(days=window_days)
        lines: list[str] = []
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                    ts = datetime.fromisoformat(entry["ts"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        lines.append(raw)
                except Exception:
                    pass  # drop corrupt lines
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        os.replace(tmp, path)
    except Exception as exc:
        log.warning("timeline_store._trim_timeline failed: %s", exc)


def load_since(state_dir: str, since_ts: datetime | None) -> list[dict]:
    """Return timeline entries with ts > since_ts (or all if since_ts is None).

    Never raises — returns [] on missing/corrupt file + logs WARNING.
    """
    path = _timeline_path(state_dir)
    try:
        if not os.path.exists(path):
            return []
        result: list[dict] = []
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                    ts = datetime.fromisoformat(entry["ts"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if since_ts is None or ts > since_ts:  # strictly after last_run; ts == last_run is excluded
                        result.append({"ts": entry["ts"], "username": entry["username"], "text": entry["text"]})
                except Exception:
                    pass  # skip corrupt lines
        return result
    except Exception as exc:
        log.warning("timeline_store.load_since(%s) failed: %s", state_dir, exc)
        return []


def load_last_run(state_dir: str) -> datetime | None:
    """Load persisted last-run timestamp.  Returns None if not set or on error."""
    path = _last_run_path(state_dir)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ts = datetime.fromisoformat(data["last_run"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("timeline_store.load_last_run(%s) failed: %s", state_dir, exc)
        return None


def save_last_run(state_dir: str, ts: datetime) -> None:
    """Persist last-run timestamp atomically.  Best-effort — never raises."""
    path = _last_run_path(state_dir)
    try:
        os.makedirs(state_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"last_run": ts.isoformat()}, fh)
        os.replace(tmp, path)
    except Exception as exc:
        log.warning("timeline_store.save_last_run(%s) failed: %s", state_dir, exc)
