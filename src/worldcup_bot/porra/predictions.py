"""YAML predictions loader with validation and mtime-based hot-reload.

load(path) -> dict  — returns the full parsed+validated predictions dict.
Validation errors for a single user are logged and that user is skipped.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

from worldcup_bot.data.stages import GROUPS, KNOCKOUT_STAGES, QUALIFY_PER_GROUP, STAGE_YAML_KEYS
from worldcup_bot.data.tla_map import TLA_TO_ISO

log = logging.getLogger(__name__)

VALID_TLAS = set(TLA_TO_ISO.keys()) | {"**"}

# ── module-level hot-reload state ─────────────────────────────────────────────
_cached_path: str | None = None
_cached_mtime: float = 0.0
_cached_data: dict = {}


# ── public API ────────────────────────────────────────────────────────────────


def load(path: str) -> dict:
    """Load predictions from YAML at *path*, using mtime-based hot-reload.

    Returns a dict with key "participants" → {username: {...}}.
    Invalid users are skipped (logged at ERROR level).
    Returns {"participants": {}} on missing file or parse error.
    """
    global _cached_path, _cached_mtime, _cached_data

    if not os.path.exists(path):
        log.error("Predictions file not found: %s", path)
        return {"participants": {}}

    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        log.error("Cannot stat predictions file: %s", exc)
        return {"participants": {}}

    if path == _cached_path and mtime == _cached_mtime and _cached_data:
        return _cached_data

    log.info("(Re)loading predictions from %s", path)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        log.error("YAML parse error in %s: %s", path, exc)
        return {"participants": {}}

    validated = _validate(raw)
    _cached_path = path
    _cached_mtime = mtime
    _cached_data = validated
    return validated


def get_participant(predictions: dict, username: str) -> dict | None:
    """Look up by username (case-insensitive). Returns user dict or None."""
    participants = predictions.get("participants", {})
    return participants.get(username.lower())


def find_by_display_name(predictions: dict, name: str) -> tuple[str, dict] | None:
    """Search participants by display_name (case-insensitive).

    Returns (username, user_dict) or None.
    """
    name_lower = name.lower()
    for uname, udata in predictions.get("participants", {}).items():
        display = (udata.get("display_name") or "").lower()
        if display == name_lower:
            return uname, udata
    return None


def display_name_for(username: str, user_data: dict) -> str:
    """Return display_name if set, otherwise '@username'."""
    return user_data.get("display_name") or f"@{username}"


def list_usernames(predictions: dict) -> list[str]:
    return list(predictions.get("participants", {}).keys())


# ── validation ────────────────────────────────────────────────────────────────

_KNOCKOUT_YAML_KEYS = set(STAGE_YAML_KEYS.values())


def _validate(raw: dict) -> dict:
    participants_raw = raw.get("participants", {})
    if not isinstance(participants_raw, dict):
        log.error("'participants' key must be a mapping in predictions YAML.")
        return {"participants": {}}

    valid_participants: dict[str, Any] = {}

    for username, udata in participants_raw.items():
        uname = str(username).lower().strip()
        if not uname:
            log.error("Empty username key — skipping.")
            continue
        if not isinstance(udata, dict):
            log.error("User %r data must be a mapping — skipping.", uname)
            continue

        groups_raw = udata.get("groups", {})
        if not isinstance(groups_raw, dict):
            log.error("User %r: 'groups' must be a mapping — skipping.", uname)
            continue

        if set(groups_raw.keys()) != set(GROUPS):
            missing = set(GROUPS) - set(groups_raw.keys())
            extra = set(groups_raw.keys()) - set(GROUPS)
            log.error(
                "User %r: groups mismatch — missing=%s, extra=%s — skipping.",
                uname, missing, extra,
            )
            continue

        groups_valid = True
        for grp, picks in groups_raw.items():
            if not isinstance(picks, list) or len(picks) != QUALIFY_PER_GROUP:
                log.error(
                    "User %r group %s: expected list of %d — skipping user.",
                    uname, grp, QUALIFY_PER_GROUP,
                )
                groups_valid = False
                break
            for tla in picks:
                if tla != "**" and tla.upper() not in TLA_TO_ISO:
                    log.error(
                        "User %r group %s: unknown TLA %r — skipping user.",
                        uname, grp, tla,
                    )
                    groups_valid = False
                    break
            if not groups_valid:
                break
        if not groups_valid:
            continue

        knockout_raw = udata.get("knockout", {})
        if not isinstance(knockout_raw, dict):
            log.error("User %r: 'knockout' must be a mapping — skipping.", uname)
            continue

        extra_keys = set(knockout_raw.keys()) - _KNOCKOUT_YAML_KEYS
        if extra_keys:
            log.error(
                "User %r: knockout has unknown keys %s — skipping.",
                uname, extra_keys,
            )
            continue

        knockout_valid = True
        for k, picks in knockout_raw.items():
            if not isinstance(picks, list):
                log.error("User %r knockout %s: expected list — skipping.", uname, k)
                knockout_valid = False
                break
            for tla in picks:
                if tla != "**" and tla.upper() not in TLA_TO_ISO:
                    log.error(
                        "User %r knockout %s: unknown TLA %r — skipping user.",
                        uname, k, tla,
                    )
                    knockout_valid = False
                    break
            if not knockout_valid:
                break
        if not knockout_valid:
            continue

        stored_knockout = {k: [t.upper() for t in v] for k, v in knockout_raw.items()}
        # Fill any missing keys with [] so downstream consumers never KeyError.
        for key in _KNOCKOUT_YAML_KEYS:
            stored_knockout.setdefault(key, [])

        valid_participants[uname] = {
            "display_name": udata.get("display_name") or None,
            "base_score": float(udata.get("base_score", 0)),
            "groups": {k: [t.upper() for t in v] for k, v in groups_raw.items()},
            "knockout": stored_knockout,
        }

    log.info("Loaded %d valid participants.", len(valid_participants))
    return {"participants": valid_participants}
