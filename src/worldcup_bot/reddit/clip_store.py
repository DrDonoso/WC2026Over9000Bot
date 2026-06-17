"""Persistent clip state for the goal-notifier background search.

Stores one entry per goal token in {state_dir}/goal_clips.json.
Each entry tracks whether a clip has been found, downloaded to the persistent
volume, and whether its Telegram file_id has been cached.

All functions are pure / synchronous (no asyncio, no Telegram) — safe to
call from jobs, handlers, or tests without ceremony.

Entry schema::

    {
        "chat_id":       int | str,     # group/chat the goal message was sent to
        "message_id":    int,            # Telegram message id of the goal message
        "home_name":     str,
        "away_name":     str,
        "home_tla":      str,
        "away_tla":      str,
        "home_score":    int,
        "away_score":    int,
        "scoring_team":  str,
        "scorer":        str | null,    # may be None if enrichment failed
        "minute":        str | null,    # "65", "45+2", etc., or None
        "status":        "searching" | "ready" | "timeout",
        "clip_path":     str | null,    # absolute path once downloaded
        "file_id":       str | null,    # Telegram file_id once sent
        "attempts":      int,
        "created_at":    str,           # ISO-8601 UTC
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# ── token helper ───────────────────────────────────────────────────────────────


def goal_token(key: str) -> str:
    """Return a short stable token (SHA-1 hex[:12]) for a goal event key."""
    return hashlib.sha1(key.encode()).hexdigest()[:12]


# ── IO helpers ─────────────────────────────────────────────────────────────────


def load_clips(path: str) -> dict:
    """Load clip-store from JSON.  Returns {} on missing or corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("load_clips(%s) failed: %s", path, exc)
        return {}


def save_clips(path: str, data: dict) -> None:
    """Persist clip-store to JSON.  Best-effort — swallows and logs on failure."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:
        log.warning("save_clips(%s) failed: %s", path, exc)


# ── entry helpers ─────────────────────────────────────────────────────────────


def add_entry(
    data: dict,
    token: str,
    *,
    chat_id: int | str,
    message_id: int,
    home_name: str,
    away_name: str,
    home_tla: str,
    away_tla: str,
    home_score: int,
    away_score: int,
    scoring_team: str,
    scorer: str | None,
    minute: str | None,
) -> None:
    """Add a new *searching* clip entry for *token* to *data* (in-place).

    Always overwrites an existing entry for the same token so a re-detection
    (e.g. restart mid-match) updates rather than duplicates.
    """
    data[token] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "home_name": home_name,
        "away_name": away_name,
        "home_tla": home_tla,
        "away_tla": away_tla,
        "home_score": home_score,
        "away_score": away_score,
        "scoring_team": scoring_team,
        "scorer": scorer,
        "minute": minute,
        "status": "searching",
        "clip_path": None,
        "file_id": None,
        "attempts": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ── retention / pruning ───────────────────────────────────────────────────────


def prune_old_entries(data: dict, clips_dir: Path, max_age_days: int = 7) -> None:
    """Remove entries older than *max_age_days* and their clip files (in-place).

    Entries with a missing or unparseable *created_at* are retained (safe
    default — we don't want to silently delete clips whose age is unknown).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stale: list[str] = []

    for token, entry in data.items():
        created_raw = entry.get("created_at")
        if not created_raw:
            continue
        try:
            created = datetime.fromisoformat(created_raw)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                stale.append(token)
        except (ValueError, TypeError):
            continue

    for token in stale:
        entry = data.pop(token)
        # Delete the clip file if recorded
        clip_path_str = entry.get("clip_path")
        if clip_path_str:
            try:
                Path(clip_path_str).unlink(missing_ok=True)
            except Exception as exc:
                log.debug("prune_old_entries: could not delete %s: %s", clip_path_str, exc)
        # Also try the canonical clips-dir location
        candidate = clips_dir / f"{token}.mp4"
        try:
            candidate.unlink(missing_ok=True)
        except Exception as exc:
            log.debug("prune_old_entries: could not delete %s: %s", candidate, exc)

    if stale:
        log.info("prune_old_entries: removed %d stale clip entries", len(stale))
