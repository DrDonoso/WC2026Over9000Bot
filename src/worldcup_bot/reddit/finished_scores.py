"""Persistent score-recording for the post-final VAR-correction watch.

Stores per-match finalized scores to {state_dir}/finished_scores.json so that
poll_finished_matches_job can detect when the football-data API retroactively
corrects a score after VAR annulment at full-time.

Entry schema::

    {match_id_str: {
        "home":         int,    # on-pitch home score at finalization
        "away":         int,    # on-pitch away score at finalization
        "finalized_at": str,    # ISO-8601 UTC timestamp of finalization
        "corrected":    bool,   # True once a VAR correction has been posted
    }}

All functions are best-effort (never raise).
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def load_finished_scores(path: str) -> dict:
    """Load finished_scores from JSON. Returns {} on missing or corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("load_finished_scores(%s) failed: %s", path, exc)
        return {}


def save_finished_scores(path: str, data: dict) -> None:
    """Persist finished_scores to JSON. Best-effort — swallows and logs on failure."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:
        log.warning("save_finished_scores(%s) failed: %s", path, exc)
