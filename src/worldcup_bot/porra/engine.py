"""Porra engine — orchestrates API + scoring to produce rankings.

All public functions accept a Settings object and a FootballDataClient
so they are testable with mocks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from worldcup_bot.api.client import FootballDataClient
from worldcup_bot.data.stages import GROUPS, KNOCKOUT_STAGES, STAGE_YAML_KEYS
from worldcup_bot.porra import predictions as pred_loader
from worldcup_bot.porra.scoring import score_groups, score_knockout

log = logging.getLogger(__name__)


# ── result types ──────────────────────────────────────────────────────────────


@dataclass
class UserRankEntry:
    username: str
    display_name: str
    total_score: float
    base_score: float
    group_score: float
    knockout_scores: dict[str, float]  # api_stage → points
    exact_group_hits: int


# ── standings helpers ─────────────────────────────────────────────────────────


def _build_actual_standings(
    client: FootballDataClient,
    only_groups: set[str] | None = None,
) -> dict[str, list[str]]:
    """Return {GROUP_A: ["TLA1", "TLA2", ...]} ordered by position.

    If only_groups is given, include ONLY those GROUP_X keys (omit the rest).
    Default None = all groups (unchanged behavior).
    """
    standings = client.get_standings()
    result: dict[str, list[str]] = {}
    for s in sorted(standings, key=lambda x: (x.group, x.position)):
        if only_groups is not None and s.group not in only_groups:
            continue
        result.setdefault(s.group, []).append(s.tla)
    return result


def _build_actual_winners(client: FootballDataClient) -> dict[str, list[str]]:
    """Return {ROUND_OF_32: ["ESP", ...]} for all knockout stages."""
    return client.get_knockout_results()


# ── public ranking functions ──────────────────────────────────────────────────


def compute_group_ranking(
    predictions: dict,
    client: FootballDataClient,
) -> list[UserRankEntry]:
    """Rank all participants by group-phase score only."""
    actual_standings = _build_actual_standings(client)
    participants = predictions.get("participants", {})
    rows: list[UserRankEntry] = []

    for uname, udata in participants.items():
        base = udata.get("base_score", 0.0)
        grp_pts, detail = score_groups(udata.get("groups", {}), actual_standings)
        exact_hits = sum(1 for d in detail if d.get("note") == "exacto")
        dname = udata.get("display_name") or f"@{uname}"
        rows.append(
            UserRankEntry(
                username=uname,
                display_name=dname,
                total_score=base + grp_pts,
                base_score=base,
                group_score=grp_pts,
                knockout_scores={},
                exact_group_hits=exact_hits,
            )
        )

    return _sort_ranking(rows)


def compute_general_ranking(
    predictions: dict,
    client: FootballDataClient,
    official: bool = False,
) -> list[UserRankEntry]:
    """Compute full porra ranking: base_score + group_pts + sum(all knockout stages).

    official=False (default): group points use live standings — provisional.
    official=True: group points only count for groups whose matches are ALL FINISHED.
                   Unfinished groups fall through score_groups' no_data branch → 0.

    Tie-break: (1) more exact group position hits, (2) alphabetical by display_name.
    """
    if official:
        finished = client.get_finished_groups()
        actual_standings = _build_actual_standings(client, only_groups=finished)
    else:
        started = client.get_started_groups()
        actual_standings = _build_actual_standings(client, only_groups=started)
    actual_winners = _build_actual_winners(client)
    participants = predictions.get("participants", {})
    rows: list[UserRankEntry] = []

    for uname, udata in participants.items():
        base = udata.get("base_score", 0.0)
        grp_pts, detail = score_groups(udata.get("groups", {}), actual_standings)
        exact_hits = sum(1 for d in detail if d.get("note") == "exacto")

        ko_scores: dict[str, float] = {}
        ko_pts, _ = score_knockout(udata.get("knockout", {}), actual_winners)
        # Also record per-stage breakdown
        for api_stage, _, stage_pts_val in KNOCKOUT_STAGES:
            yaml_key = STAGE_YAML_KEYS.get(api_stage, api_stage.lower())
            stage_picks = {yaml_key: udata.get("knockout", {}).get(yaml_key, [])}
            stage_actual = {api_stage: actual_winners.get(api_stage, [])}
            pts_for_stage, _ = score_knockout(stage_picks, stage_actual, [(api_stage, "", stage_pts_val)])
            ko_scores[api_stage] = pts_for_stage

        total = base + grp_pts + ko_pts
        dname = udata.get("display_name") or f"@{uname}"
        rows.append(
            UserRankEntry(
                username=uname,
                display_name=dname,
                total_score=total,
                base_score=base,
                group_score=grp_pts,
                knockout_scores=ko_scores,
                exact_group_hits=exact_hits,
            )
        )

    return _sort_ranking(rows)


def compute_user_detail(
    username: str,
    predictions: dict,
    client: FootballDataClient,
    official: bool = False,
) -> dict | None:
    """Return full scoring detail for a single user, or None if not found.

    official=False (default): live/provisional — all groups and knockout stages score.
    official=True: only CLOSED groups score; only FINISHED knockout stages score.
                   Unclosed groups → 'no_data' → ⏳ 0. Pending KO rounds produce no entries.
    """
    udata = pred_loader.get_participant(predictions, username)
    if udata is None:
        return None

    started_groups: set[str] | None = None  # set only in provisional mode

    if official:
        finished_groups = client.get_finished_groups()
        finished_stages = client.get_finished_stages()
        actual_standings = _build_actual_standings(client, only_groups=finished_groups)
        full_winners = _build_actual_winners(client)
        actual_winners = {api: full_winners.get(api, []) for api in finished_stages}
        user_ko = {
            yaml: udata.get("knockout", {}).get(yaml, [])
            for api, yaml in STAGE_YAML_KEYS.items()
            if api in finished_stages
        }
        ko_pts, ko_detail = score_knockout(user_ko, actual_winners)
    else:
        finished_groups = None
        started_groups = client.get_started_groups()
        actual_standings = _build_actual_standings(client, only_groups=started_groups)
        actual_winners = _build_actual_winners(client)
        ko_pts, ko_detail = score_knockout(udata.get("knockout", {}), actual_winners)

    grp_pts, grp_detail = score_groups(udata.get("groups", {}), actual_standings)
    base = udata.get("base_score", 0.0)

    return {
        "username": username,
        "display_name": udata.get("display_name") or f"@{username}",
        "base_score": base,
        "group_score": grp_pts,
        "knockout_score": ko_pts,
        "total_score": base + grp_pts + ko_pts,
        "group_detail": grp_detail,
        "knockout_detail": ko_detail,
        "official": official,
        "finished_groups": len(finished_groups) if official else None,
        "started_groups": len(started_groups) if started_groups is not None else None,
        "total_groups": len(GROUPS),
    }


# ── sort helper ───────────────────────────────────────────────────────────────


def _sort_ranking(rows: list[UserRankEntry]) -> list[UserRankEntry]:
    """Sort descending by total, tie-break: exact hits desc, then name alpha."""
    return sorted(
        rows,
        key=lambda r: (-r.total_score, -r.exact_group_hits, r.display_name.lower()),
    )
