"""Pure scoring functions — zero I/O.

score_groups: group standings scoring.
  Corrected rule (2026-06-22):
  - pred ∈ {1,2} AND actual ∈ {1,2} → 1.0  (both in the direct-qualifying top-2; order irrelevant)
  - pred == actual == 3               → 1.0  (exact 3rd)
  - one in top-2, other is 3rd        → 0.5  (boundary near-miss)
  - otherwise                         → 0.0
score_knockout: knockout stage scoring (correct qualifier → +stage_points).
score_user_groups_detail: same as score_groups but returns per-team breakdown.
"""

from __future__ import annotations

from worldcup_bot.data.stages import GROUP_SCORING, KNOCKOUT_STAGES, QUALIFY_PER_GROUP, STAGE_YAML_KEYS

# The top-2 finishers are direct qualifiers; swapping within this zone still earns full points.
# QUALIFY_PER_GROUP (=3) means "3 picks per group" and is left unchanged.
DIRECT_QUALIFY = 2

# ── type aliases ──────────────────────────────────────────────────────────────

# user_groups: {"A": ["GER", "HUN", "SUI"], ...}
UserGroups = dict[str, list[str]]
# actual_standings: {"GROUP_A": ["GER", "SUI", "HUN", "SCO"], ...}
# (ordered by position, full group table)
ActualStandings = dict[str, list[str]]

# user_knockout: {"round_of_32": ["ESP", ...], ...}
UserKnockout = dict[str, list[str]]
# actual_winners: {"ROUND_OF_32": ["ESP", "GER", ...], ...}
ActualWinners = dict[str, list[str]]

DetailEntry = dict  # {"group"|"stage", "team", "predicted_pos", "actual_pos", "points"}


# ── group scoring ─────────────────────────────────────────────────────────────


def score_groups(
    user_groups: UserGroups,
    actual_standings: ActualStandings,
) -> tuple[float, list[DetailEntry]]:
    """Score group-phase predictions against actual standings.

    user_groups keys are plain letters ("A"), actual_standings keys are
    "GROUP_A" style (as returned by football-data.org).

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
                # Both in the direct-qualifying zone (positions 1–2); order irrelevant.
                pts = GROUP_SCORING["exact_position"]
                note = "exacto"
            elif pred_pos == actual_pos:
                # Exact match at position 3 (the only remaining exact-match case).
                pts = GROUP_SCORING["exact_position"]
                note = "exacto"
            elif actual_pos <= QUALIFY_PER_GROUP:
                # Boundary near-miss: one side is top-2, the other is 3rd.
                pts = GROUP_SCORING["qualified_wrong_position"]
                note = "clasifica"
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
) -> tuple[float, list[DetailEntry]]:
    """Alias kept for symmetry with migration map (calculate_hits → here)."""
    return score_groups(user_groups, actual_standings)


# ── knockout scoring ──────────────────────────────────────────────────────────


def score_knockout(
    user_knockout: UserKnockout,
    actual_winners: ActualWinners,
    stages_config: list[tuple[str, str, int]] = KNOCKOUT_STAGES,
) -> tuple[float, list[DetailEntry]]:
    """Score knockout-phase predictions.

    user_knockout uses yaml keys (e.g. "round_of_32").
    actual_winners uses API stage names (e.g. "ROUND_OF_32").

    Returns (total_points, detail_list).
    """
    total = 0.0
    detail: list[DetailEntry] = []

    for api_stage, display_es, stage_pts in stages_config:
        yaml_key = STAGE_YAML_KEYS.get(api_stage, api_stage.lower())
        predicted = user_knockout.get(yaml_key, [])
        actual = set(actual_winners.get(api_stage, []))

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
                detail.append(
                    {
                        "stage": api_stage,
                        "display": display_es,
                        "team": team,
                        "points": stage_pts,
                        "note": "acierto",
                    }
                )
            else:
                detail.append(
                    {
                        "stage": api_stage,
                        "display": display_es,
                        "team": team,
                        "points": 0,
                        "note": "fallo",
                    }
                )

    return total, detail
