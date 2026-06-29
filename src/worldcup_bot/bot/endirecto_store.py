"""Persistent snapshot store for /endirecto inline reveal buttons.

Stores per-match snapshots to {state_dir}/endirecto.json, keyed by 8-hex token.
All public functions are best-effort and never raise.

Snapshot schema:
  {"token": str, "match_id": int, "minute": str|None,
   "home_name": str, "away_name": str, "home_tla": str, "away_tla": str,
   "home_score": int|None, "away_score": int|None,
   "goals": [...], "cards": [...], "subs": [...],
   "lineup": {"home": [...], "away": [...]},
   "reddit_goals": [GoalEvent-as-dict, ...]  # on-demand "⚽ Goles" fetch
   "revealed": [], "created": float (unix ts)}
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time

log = logging.getLogger(__name__)


def new_token() -> str:
    return secrets.token_hex(4)


def _load_store(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("endirecto_store: failed to load %s: %s", path, exc)
        return {}


def _save_store(path: str, store: dict) -> None:
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as exc:
        log.warning("endirecto_store: failed to save %s: %s", path, exc)


def prune(path: str, max_age_secs: int = 21600) -> None:
    try:
        store = _load_store(path)
        now = time.time()
        kept = {
            token: snap
            for token, snap in store.items()
            if now - snap.get("created", 0) <= max_age_secs
        }
        if len(kept) != len(store):
            _save_store(path, kept)
    except Exception as exc:
        log.warning("endirecto_store: prune failed for %s: %s", path, exc)


def save_snapshot(path: str, snap: dict) -> None:
    try:
        store = _load_store(path)
        token = snap.get("token")
        if not token:
            return
        store[token] = snap
        _save_store(path, store)
        prune(path)
    except Exception as exc:
        log.warning("endirecto_store: save_snapshot failed for %s: %s", path, exc)


def load_snapshot(path: str, token: str) -> dict | None:
    try:
        return _load_store(path).get(token)
    except Exception:
        return None


def set_revealed(path: str, token: str, section: str) -> dict | None:
    try:
        store = _load_store(path)
        snap = store.get(token)
        if snap is None:
            return None
        revealed = snap.setdefault("revealed", [])
        if not isinstance(revealed, list):
            revealed = snap["revealed"] = []
        if section not in revealed:
            revealed.append(section)
        store[token] = snap
        _save_store(path, store)
        return snap
    except Exception:
        return None


def set_reddit_goals(path: str, token: str, new_goals: list[dict]) -> dict | None:
    """Merge *new_goals* into the snapshot's ``reddit_goals``, dedup by ``key``.

    Existing goals are kept (we only add the ones we don't have yet — "que no
    tengas"); the merged list is sorted by ``minute_sort``.  Returns the updated
    snapshot, or None if the token is unknown.
    """
    try:
        store = _load_store(path)
        snap = store.get(token)
        if snap is None:
            return None
        existing = snap.get("reddit_goals")
        if not isinstance(existing, list):
            existing = []
        by_key = {g.get("key"): g for g in existing if isinstance(g, dict)}
        for g in new_goals:
            if isinstance(g, dict) and g.get("key") not in by_key:
                by_key[g["key"]] = g
        merged = sorted(by_key.values(), key=lambda g: g.get("minute_sort", 0))
        snap["reddit_goals"] = merged
        store[token] = snap
        _save_store(path, store)
        return snap
    except Exception as exc:
        log.warning("endirecto_store: set_reddit_goals failed for %s: %s", path, exc)
        return None
