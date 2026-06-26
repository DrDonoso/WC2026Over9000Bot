"""Persistent live-match score state for football-data-driven goal detection.

Stores home/away scores per match_id in {state_dir}/live_scores.json.
Goals are detected by comparing the current score reported by football-data.org
against the last stored state — football-data is the authoritative score source.

The reconcile() function implements per-source deduplication:
- Each detector (api / thread) has its own "seen" baseline.
- A single "announced" score is shared — the score users have been told.
- A lagging source's catch-up is never treated as a disallowed goal.
- A disallowed is only emitted when the SAME source that was high drops.
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

    side: str           # "home", "away", or "" (catchup)
    scoring_team: str   # team name for this side; "" for catchup
    new_home: int       # current home score after the change
    new_away: int       # current away score after the change
    kind: str           # "goal", "disallowed", or "catchup"
    goals_missed: int = 0  # number of goals missed (catchup only)


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


def _ahead(a: dict, b: dict) -> bool:
    """Return True if score a is strictly ahead of score b on at least one side."""
    return (
        a["home"] >= b["home"]
        and a["away"] >= b["away"]
        and (a["home"] > b["home"] or a["away"] > b["away"])
    )


def reconcile(
    seen: dict | None,
    announced: dict | None,
    new_home: int,
    new_away: int,
) -> tuple[list[GoalDelta], dict, dict]:
    """Per-source reconciliation — the core of the flip-flop fix.

    Parameters
    ----------
    seen:       This source's last known {"home": int, "away": int}, or None (first tick).
    announced:  The single official score users have been told, or None (match not yet seeded).
    new_home:   This source's current home score.
    new_away:   This source's current away score.

    Returns
    -------
    (deltas, new_seen, new_announced)

    - deltas:        GoalDeltas to announce.  scoring_team is "" — callers must fill it.
    - new_seen:      Updated per-source baseline (always set to new).
    - new_announced: Updated official announced score.

    Rules
    -----
    1. First-seen (seen is None):
       - announced is None (match truly first-seen by any source): seed both baselines
         to new, announce NOTHING.
       - announced is not None (restart — per-source seen was reset, announced persisted):
         if new > announced, goals were scored while the bot was down — emit ONE neutral
         catch-up GoalDelta(kind="catchup", goals_missed=N) so users are informed without
         fabricating per-goal attributions.  If new <= announced (source lagging or
         unchanged), announce NOTHING and keep announced.
    2. No change (new == seen): nothing to do.
    3. Source changed and new is AHEAD of announced: emit goal deltas for each extra
       goal (home then away), set new_announced = new.
    4. Source changed and announced is AHEAD of new (potential disallowed):
       - If this source's OWN prior value was above new (ahead(seen, new) is True):
         this is a REAL disallowed — emit one GoalDelta(kind="disallowed") per dropped
         side, set new_announced = new.
       - Otherwise the source is merely catching up from behind announced (pure lag):
         announce NOTHING, keep new_announced = announced (unchanged).
    5. Equal or mixed (incomparable vs announced): announce nothing, keep announced.

    In all cases new_seen is set to new so the source's own baseline advances.
    """
    new = {"home": new_home, "away": new_away}

    # Step 1: first-seen for this source.
    if seen is None:
        if announced is None:
            # Truly first-seen for this match: seed both baselines, announce nothing.
            return ([], new, new)
        # Restart case: per-source in-memory seen was reset but announced is persisted.
        # If new is ahead of announced, goals were scored during downtime — emit ONE
        # neutral catch-up notification instead of N fabricated per-goal deltas.
        if _ahead(new, announced):
            home_diff = new_home - announced["home"]
            away_diff = new_away - announced["away"]
            catchup = GoalDelta(
                side="",
                scoring_team="",
                new_home=new_home,
                new_away=new_away,
                kind="catchup",
                goals_missed=home_diff + away_diff,
            )
            return ([catchup], new, new)
        # new <= announced: source is lagging or at the same level — no delta.
        return ([], new, announced)

    # Step 2: source didn't change — nothing to do.
    if new == seen:
        return ([], seen, announced)  # type: ignore[return-value]

    # Step 3 / 4 / 5: source changed.
    ann = announced
    if ann is None:
        # Defensive: shouldn't happen after step 1 seeded it, but handle gracefully.
        return ([], new, new)

    if _ahead(new, ann):
        # New is ahead of announced → unannounced goal(s).
        deltas: list[GoalDelta] = []
        home_diff = new_home - ann["home"]
        away_diff = new_away - ann["away"]
        for _ in range(home_diff):
            deltas.append(GoalDelta(
                side="home",
                scoring_team="",   # caller fills
                new_home=new_home,
                new_away=new_away,
                kind="goal",
            ))
        for _ in range(away_diff):
            deltas.append(GoalDelta(
                side="away",
                scoring_team="",   # caller fills
                new_home=new_home,
                new_away=new_away,
                kind="goal",
            ))
        return (deltas, new, new)

    if _ahead(ann, new):
        # Announced is ahead of new — potential disallowed.
        if _ahead(seen, new):
            # This source's OWN prior value dropped → real VAR disallowed.
            deltas = []
            if seen["home"] > new_home:
                deltas.append(GoalDelta(
                    side="home",
                    scoring_team="",
                    new_home=new_home,
                    new_away=new_away,
                    kind="disallowed",
                ))
            if seen["away"] > new_away:
                deltas.append(GoalDelta(
                    side="away",
                    scoring_team="",
                    new_home=new_home,
                    new_away=new_away,
                    kind="disallowed",
                ))
            return (deltas, new, new)
        # Source was BEHIND announced and is still below — pure lag, not a disallowed.
        return ([], new, ann)

    # Equal to announced or mixed (one side up, other down) — announce nothing.
    return ([], new, ann)
