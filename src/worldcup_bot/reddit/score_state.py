"""Persistent live-match score state for football-data-driven goal detection.

Stores home/away scores per match_id in {state_dir}/live_scores.json.
Goals are detected by comparing the current score reported by football-data.org
against the last stored state — football-data is the authoritative score source.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from worldcup_bot.api.models import Match

log = logging.getLogger(__name__)


@dataclass
class GoalDelta:
    """Describes a single score-change event for one side of a match."""

    side: str           # "home" or "away"
    scoring_team: str   # team name for this side
    new_home: int       # current home score after the change
    new_away: int       # current away score after the change
    kind: str           # "goal" (score increase) or "disallowed" (score decrease)


def load_scores(path: str) -> dict:
    """Load persistent score state from JSON file.

    Returns empty dict if the file doesn't exist or is unreadable.
    Schema: { "<match_id>": {"home": int, "away": int, "status": str} }
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("load_scores(%s) failed: %s", path, exc)
        return {}


def save_scores(path: str, data: dict) -> None:
    """Persist score state to JSON file. Best-effort: swallows and logs on failure."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:
        log.warning("save_scores(%s) failed: %s", path, exc)


def diff_scores(stored: dict | None, match: Match) -> list[GoalDelta]:
    """Compute goal deltas between stored state and current match score.

    - stored is None (first-seen) → return [] (seed only, notify nothing).
    - Score INCREASE on a side → one GoalDelta(kind="goal") per extra goal.
    - Score DECREASE on a side → one GoalDelta(kind="disallowed").
    - No change → [].

    The new_home/new_away on every delta reflect the *current* final score.
    For a multi-goal increase in one tick, all deltas share the same final score
    (intermediate state was missed due to polling interval).
    """
    if stored is None:
        return []

    prev_home = int(stored.get("home", 0))
    prev_away = int(stored.get("away", 0))
    curr_home = int(match.home_score) if match.home_score is not None else 0
    curr_away = int(match.away_score) if match.away_score is not None else 0

    deltas: list[GoalDelta] = []

    home_diff = curr_home - prev_home
    away_diff = curr_away - prev_away

    if home_diff > 0:
        for _ in range(home_diff):
            deltas.append(GoalDelta(
                side="home",
                scoring_team=match.home_name,
                new_home=curr_home,
                new_away=curr_away,
                kind="goal",
            ))
    elif home_diff < 0:
        deltas.append(GoalDelta(
            side="home",
            scoring_team=match.home_name,
            new_home=curr_home,
            new_away=curr_away,
            kind="disallowed",
        ))

    if away_diff > 0:
        for _ in range(away_diff):
            deltas.append(GoalDelta(
                side="away",
                scoring_team=match.away_name,
                new_home=curr_home,
                new_away=curr_away,
                kind="goal",
            ))
    elif away_diff < 0:
        deltas.append(GoalDelta(
            side="away",
            scoring_team=match.away_name,
            new_home=curr_home,
            new_away=curr_away,
            kind="disallowed",
        ))

    return deltas
