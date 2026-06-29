"""Pure scoring functions — zero I/O.

score_groups: group standings scoring.
  Scoring rules (2026-06-26, best-thirds aware):
  - pred in {1,2} AND actual in {1,2} -> 1.0  (direct-qualifying zone; order irrelevant)
  - pred == actual == 3 AND team is qualifying third -> 1.0
  - pred == actual == 3 AND team is NOT qualifying third -> NON_QUALIFYING_THIRD_SCORE (0.0)
  - boundary: one of {pred,actual} is top-2, other is 3rd:
      * 3rd-place team qualifies -> 0.5
      * 3rd-place team does NOT qualify -> NON_QUALIFYING_THIRD_SCORE (0.0)
  - qualifying_thirds=None (default): backward-compat -- all 3rds treated as qualifying
  - otherwise -> 0.0
score_knockout: knockout stage scoring (correct qualifier -> +stage_points;
  optional decided_teams marks not-yet-played picks as pending instead of fallo).
score_user_groups_detail: same as score_groups but returns per-team breakdown.
best_qualifying_thirds: FIFA third-place ranking -- return the 8 best thirds.
"""

from __future__ import annotations

import logging

from worldcup_bot.data.stages import GROUP_SCORING, KNOCKOUT_STAGES, QUALIFY_PER_GROUP, STAGE_YAML_KEYS

log = logging.getLogger(__name__)

# The top-2 finishers are direct qualifiers; swapping within this zone still earns full points.
# QUALIFY_PER_GROUP (=3) means "3 picks per group" and is left unchanged.
DIRECT_QUALIFY = 2

# Number of best third-placed teams that advance to the Round of 32.
NUM_QUALIFYING_THIRDS: int = 8

# Points awarded when a 3rd-place pick does not qualify (team eliminated).
# Knob: the owner may flip this to 0.5 to still reward exact-3rd predictions.
NON_QUALIFYING_THIRD_SCORE: float = 0.0

# -- type aliases ---------------------------------------------------------------

# user_groups: {"A": ["GER", "HUN", "SUI"], ...}
UserGroups = dict[str, list[str]]
# actual_standings: {"GROUP_A": ["TLA1", "TLA2", ...], ...}
# (ordered by position, full group table)
ActualStandings = dict[str, list[str]]

# user_knockout: {"round_of_32": ["ESP", ...], ...}
UserKnockout = dict[str, list[str]]
# actual_winners: {"LAST_32": ["ESP", "GER", ...], ...}
ActualWinners = dict[str, list[str]]

DetailEntry = dict  # {"group"|"stage", "team", "predicted_pos", "actual_pos", "points"}


# -- third-place qualifying -----------------------------------------------------


def best_qualifying_thirds(
    full_group_standings: dict[str, list[dict]],
) -> frozenset[str]:
    """Return TLAs of the best NUM_QUALIFYING_THIRDS third-placed teams.

    Tiebreakers in FIFA order: (1) points, (2) goal difference, (3) goals for.
    Disciplinary points and lots are not available; a stable (group_key, TLA)
    order is used as the final tiebreaker with a logged WARNING.

    full_group_standings: {GROUP_X: [{"tla", "points", "goal_difference",
    "goals_for"}, ...]} ordered 1st->last per group.  Groups with fewer than
    3 entries are skipped (not enough data for a 3rd-place team yet).

    If fewer than NUM_QUALIFYING_THIRDS thirds are present (mid-tournament),
    all known thirds are returned -- every current 3rd is treated as advancing
    (provisional, consistent with the rest of the scoring).
    """
    thirds: list[dict] = []
    for group_key in sorted(full_group_standings):
        entries = full_group_standings[group_key]
        if len(entries) >= 3:
            t = entries[2]
            thirds.append(
                {
                    "tla": t["tla"],
                    "group": group_key,
                    "points": int(t.get("points", 0)),
                    "goal_difference": int(t.get("goal_difference", 0)),
                    "goals_for": int(t.get("goals_for", 0)),
                }
            )

    if not thirds:
        return frozenset()

    thirds.sort(
        key=lambda x: (
            -x["points"],
            -x["goal_difference"],
            -x["goals_for"],
            x["group"],   # stable group-letter fallback
            x["tla"],     # stable TLA fallback
        )
    )

    if len(thirds) <= NUM_QUALIFYING_THIRDS:
        return frozenset(t["tla"] for t in thirds)

    # Check for a tie at the qualifying boundary (position 8 vs position 9+).
    cutoff = thirds[NUM_QUALIFYING_THIRDS - 1]
    next_one = thirds[NUM_QUALIFYING_THIRDS]
    ck = (cutoff["points"], cutoff["goal_difference"], cutoff["goals_for"])
    nk = (next_one["points"], next_one["goal_difference"], next_one["goals_for"])
    if ck == nk:
        log.warning(
            "best_qualifying_thirds: tie at boundary pos 8/9 "
            "(pts=%d gd=%d gf=%d); using stable group/TLA order -- "
            "official result may differ",
            *ck,
        )

    return frozenset(t["tla"] for t in thirds[:NUM_QUALIFYING_THIRDS])


def _team_advances(team: str, actual_pos: int, qualifying_thirds: frozenset[str] | None) -> bool:
    """True if a team advances from the group stage.

    Top-2 always advance.  3rd-place advance only if in qualifying_thirds.
    qualifying_thirds=None -> backward-compat (treat all 3rds as advancing).
    """
    if actual_pos <= DIRECT_QUALIFY:
        return True
    if actual_pos == QUALIFY_PER_GROUP:  # position 3
        return qualifying_thirds is None or team in qualifying_thirds
    return False


# -- group scoring --------------------------------------------------------------


def score_groups(
    user_groups: UserGroups,
    actual_standings: ActualStandings,
    qualifying_thirds: frozenset[str] | None = None,
) -> tuple[float, list[DetailEntry]]:
    """Score group-phase predictions against actual standings.

    user_groups keys are plain letters ("A"), actual_standings keys are
    "GROUP_A" style (as returned by football-data.org).

    qualifying_thirds: TLAs of the 8 best third-placed teams that advance to
    the Round of 32.  None (default): backward-compatible -- all 3rd-place
    picks are treated as qualifying (behaviour before 2026-06-26).

    Returns (total_points, detail_list).
    """
    total = 0.0
    detail: list[DetailEntry] = []

    for group_letter, predicted_teams in user_groups.items():
        api_key = f"GROUP_{group_letter}"
        actual_order = actual_standings.get(api_key, [])

        for pred_pos, team in enumerate(predicted_teams, start=1):
            if team == "**" or not team:
                detail.append(
                    {
                        "group": group_letter,
                        "team": team,
                        "predicted_pos": pred_pos,
                        "actual_pos": None,
                        "points": 0,
                        "note": "wildcard",
                    }
                )
                continue

            # Find actual position (1-indexed)
            try:
                actual_pos = actual_order.index(team) + 1
            except ValueError:
                # Team not yet in standings (hasn't played)
                detail.append(
                    {
                        "group": group_letter,
                        "team": team,
                        "predicted_pos": pred_pos,
                        "actual_pos": None,
                        "points": 0,
                        "note": "no_data",
                    }
                )
                continue

            if pred_pos <= DIRECT_QUALIFY and actual_pos <= DIRECT_QUALIFY:
                # Both in the direct-qualifying zone (positions 1-2); order irrelevant.
                pts = GROUP_SCORING["exact_position"]
                note = "exacto"
            elif pred_pos == actual_pos:
                # Exact match at position 3 (the only remaining exact-match case).
                if _team_advances(team, actual_pos, qualifying_thirds):
                    pts = GROUP_SCORING["exact_position"]
                    note = "exacto"
                else:
                    pts = NON_QUALIFYING_THIRD_SCORE
                    note = "fallo"
            elif actual_pos <= QUALIFY_PER_GROUP:
                # Boundary: actual is in the qualifying zone (1-3); check advancement.
                if _team_advances(team, actual_pos, qualifying_thirds):
                    pts = GROUP_SCORING["qualified_wrong_position"]
                    note = "clasifica"
                else:
                    pts = NON_QUALIFYING_THIRD_SCORE
                    note = "fallo"
            else:
                pts = 0
                note = "fallo"

            total += pts
            detail.append(
                {
                    "group": group_letter,
                    "team": team,
                    "predicted_pos": pred_pos,
                    "actual_pos": actual_pos,
                    "points": pts,
                    "note": note,
                }
            )

    return total, detail


def score_user_groups_detail(
    user_groups: UserGroups,
    actual_standings: ActualStandings,
    qualifying_thirds: frozenset[str] | None = None,
) -> tuple[float, list[DetailEntry]]:
    """Alias kept for symmetry with migration map (calculate_hits -> here)."""
    return score_groups(user_groups, actual_standings, qualifying_thirds)


# -- knockout scoring -----------------------------------------------------------


def score_knockout(
    user_knockout: UserKnockout,
    actual_winners: ActualWinners,
    stages_config: list[tuple[str, str, int]] = KNOCKOUT_STAGES,
    decided_teams: dict[str, set[str]] | None = None,
) -> tuple[float, list[DetailEntry]]:
    """Score knockout-phase predictions.

    user_knockout uses yaml keys (e.g. "round_of_32").
    actual_winners uses API stage names (e.g. "LAST_32").

    decided_teams: optional {api_stage: set(TLAs that played a FINISHED match in
      that stage)} — winners and losers alike.  When provided, a predicted team
      whose match has NOT finished yet is marked "pending" (⏳, 0 pts) instead of
      "fallo", mirroring the group-stage "no_data" handling so a not-yet-played
      pick does not look like a loss.  None (default): backward-compatible —
      every non-winner is "fallo".

    A knockout result is definitive the moment its match is FINISHED, so each
    finished match scores immediately (provisional and official alike) — the
    same idea as a closed group counting in the group phase.

    Returns (total_points, detail_list).
    """
    total = 0.0
    detail: list[DetailEntry] = []

    for api_stage, display_es, stage_pts in stages_config:
        yaml_key = STAGE_YAML_KEYS.get(api_stage, api_stage.lower())
        predicted = user_knockout.get(yaml_key, [])
        actual = set(actual_winners.get(api_stage, []))
        decided = None if decided_teams is None else set(decided_teams.get(api_stage, set()))

        for team in predicted:
            if team == "**" or not team:
                detail.append(
                    {
                        "stage": api_stage,
                        "display": display_es,
                        "team": team,
                        "points": 0,
                        "note": "wildcard",
                    }
                )
                continue

            if team in actual:
                total += stage_pts
                note, pts = "acierto", stage_pts
            elif decided is not None and team not in decided:
                # Its match has not been played yet — pending, not a loss.
                note, pts = "pending", 0
            else:
                note, pts = "fallo", 0

            detail.append(
                {
                    "stage": api_stage,
                    "display": display_es,
                    "team": team,
                    "points": pts,
                    "note": note,
                }
            )

    return total, detail
