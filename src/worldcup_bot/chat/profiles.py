"""Profiles store — per-user AI-learned profiles for picante personalisation.

Ruta: {state_dir}/picante_profiles.json

Atomic load/save pattern mirrors state.py (save_chat_state / load_chat_state).
Never raises on load/save — graceful degradation as per picante resilience rules.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """Auto-learned per-user profile populated by the daily batch job."""

    username: str
    rasgos: str | None = None
    """Free-text personality description."""
    equipo: str | None = None
    """Favourite team / selection."""
    motes: list[str] = field(default_factory=list)
    """Recurring nicknames / in-jokes."""
    temas: list[str] = field(default_factory=list)
    """Favourite topics / hobbies."""
    tono: str | None = None
    """Tone instruction to use when generating a picante reply for this user."""
    piques_recientes: list[dict] = field(default_factory=list)
    """Recent bot replies persisted from maybe_reply (ts + texto ≤200 chars)."""
    pinned_fields: list[str] = field(default_factory=list)
    """Fields the auto-updater must never overwrite (set manually)."""
    updated_at: str | None = None
    """ISO-8601 UTC timestamp of last AI update."""


def _profile_from_dict(data: dict) -> UserProfile:
    return UserProfile(
        username=str(data.get("username") or ""),
        rasgos=data.get("rasgos") or None,
        equipo=data.get("equipo") or None,
        motes=list(data.get("motes") or []),
        temas=list(data.get("temas") or []),
        tono=data.get("tono") or None,
        piques_recientes=list(data.get("piques_recientes") or []),
        pinned_fields=list(data.get("pinned_fields") or []),
        updated_at=data.get("updated_at") or None,
    )


def _profile_to_dict(p: UserProfile) -> dict:
    return {
        "username": p.username,
        "rasgos": p.rasgos,
        "equipo": p.equipo,
        "motes": p.motes,
        "temas": p.temas,
        "tono": p.tono,
        "piques_recientes": p.piques_recientes,
        "pinned_fields": p.pinned_fields,
        "updated_at": p.updated_at,
    }


def load_profiles(path: str) -> dict[str, UserProfile]:
    """Load all profiles from JSON.  Never raises.

    Returns {} if the file is missing, empty, or corrupt + logs WARNING.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("profiles JSON root must be an object")
        return {k: _profile_from_dict(v) for k, v in raw.items() if isinstance(v, dict)}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("load_profiles(%s) failed: %s — returning {}", path, exc)
        return {}


def save_profiles(path: str, profiles: dict[str, UserProfile]) -> None:
    """Persist profiles to JSON atomically (temp-file replace).  Best-effort — never raises."""
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{path}.tmp"
        data = {k: _profile_to_dict(v) for k, v in profiles.items()}
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        log.warning("save_profiles(%s) failed: %s", path, exc)


def get_profile(profiles: dict[str, UserProfile], username: str) -> UserProfile | None:
    """Return the profile for *username*, or None if not found."""
    return profiles.get(username)
