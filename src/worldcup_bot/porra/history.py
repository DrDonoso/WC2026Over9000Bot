"""Porra ranking history — builds and persists a timeline of jornada rankings.

Schema of porra_history.json:
  { "YYYY-MM-DD": { username: {"pos": int, "pts": float, "name": str} } }

Keys are football-day labels (the 9am→9am window boundary date), consistent
with /hoy and /ayer. Group standings are fully reconstructed from match results —
no ?date= API calls needed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytz

from worldcup_bot.api.models import Match
from worldcup_bot.data.stages import KNOCKOUT_STAGES

log = logging.getLogger(__name__)


def load_history(path: str) -> dict:
    """Load history from JSON file; return {} on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("load_history: could not load %s", path, exc_info=True)
    return {}


def save_history(path: str, data: dict) -> None:
    """Persist history to JSON file; best-effort (logs but never raises)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        log.warning("save_history: could not save %s", path, exc_info=True)


def football_day_of(match: Match, tz: str, anchor_hour: int) -> str:
    """Return the football-day label (YYYY-MM-DD) for a match.

    Uses the same 9am→9am windowing as get_football_day_matches:
    - local hour >= anchor_hour → label is the local calendar date
    - local hour < anchor_hour → label is the local date minus 1 day
      (the match belongs to the previous day's football window)
    """
    local_tz = pytz.timezone(tz)
    utc_dt = datetime.strptime(match.utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    local_dt = utc_dt.astimezone(local_tz)
    if local_dt.hour >= anchor_hour:
        return local_dt.strftime("%Y-%m-%d")
    return (local_dt - timedelta(days=1)).strftime("%Y-%m-%d")


def build_jornadas(matches: list[Match], tz: str, anchor_hour: int) -> list[str]:
    """Return sorted distinct football-day labels with at least one FINISHED match.

    Uses the 9am→9am football-day window so early-morning matches (before
    anchor_hour local) group into the previous day's jornada, consistent
    with /hoy and /ayer. Replaces build_checkpoint_dates.
    """
    jornadas: set[str] = set()
    for m in matches:
        if m.status != "FINISHED":
            continue
        try:
            jornadas.add(football_day_of(m, tz, anchor_hour))
        except (ValueError, AttributeError):
            log.warning(
                "build_jornadas: could not parse date %s",
                getattr(m, "utc_date", None),
            )
    return sorted(jornadas)


def reconstruct_group_standings(
    finished_group_matches: list[Match],
) -> dict[str, list[str]]:
    """Reconstruct group standings from finished group-stage matches.

    For each group computes per-team: points (W=3/D=1/L=0), goal difference
    (GD), goals for (GF). Teams ordered: points DESC, GD DESC, GF DESC, TLA asc.
    Head-to-head is NOT used — a sufficient approximation for a trend chart.

    Returns {GROUP_A: ["TLA1", "TLA2", ...]} for groups with finished matches.
    Matches with missing scores or group are silently skipped.
    """
    group_stats: dict[str, dict[str, dict[str, int]]] = {}

    for m in finished_group_matches:
        if m.group is None or m.status != "FINISHED":
            continue
        if m.home_score is None or m.away_score is None:
            continue

        g = m.group
        if g not in group_stats:
            group_stats[g] = {}

        hs, as_ = m.home_score, m.away_score

        if m.home_tla not in group_stats[g]:
            group_stats[g][m.home_tla] = {"pts": 0, "gd": 0, "gf": 0}
        if m.away_tla not in group_stats[g]:
            group_stats[g][m.away_tla] = {"pts": 0, "gd": 0, "gf": 0}

        home_stats = group_stats[g][m.home_tla]
        away_stats = group_stats[g][m.away_tla]

        home_stats["gf"] += hs
        home_stats["gd"] += hs - as_
        away_stats["gf"] += as_
        away_stats["gd"] += as_ - hs

        if hs > as_:
            home_stats["pts"] += 3
        elif as_ > hs:
            away_stats["pts"] += 3
        else:
            home_stats["pts"] += 1
            away_stats["pts"] += 1

    result: dict[str, list[str]] = {}
    for g, teams in sorted(group_stats.items()):
        ordered = sorted(
            teams.keys(),
            key=lambda tla: (
                -teams[tla]["pts"],
                -teams[tla]["gd"],
                -teams[tla]["gf"],
                tla,
            ),
        )
        result[g] = ordered

    return result


def compute_ranking_at_jornada(
    predictions: dict,
    all_matches: list[Match],
    jornada: str,
    tz: str,
    anchor_hour: int,
) -> list:
    """Compute provisional ranking as of the given football-day (YYYY-MM-DD).

    - Cutoff: FINISHED matches whose football-day label <= jornada.
    - Group standings: reconstructed from cutoff GROUP_STAGE matches.
    - Knockout winners: from cutoff knockout matches (FINISHED, winner field).
    - Returns engine.compute_general_ranking_from(predictions, standings, winners).
    No API calls are made — all data comes from the passed matches list.
    """
    from worldcup_bot.porra import engine  # avoid top-level circular imports

    ko_names = {api for api, _, _ in KNOCKOUT_STAGES}

    cutoff: list[Match] = []
    for m in all_matches:
        if m.status != "FINISHED":
            continue
        try:
            day = football_day_of(m, tz, anchor_hour)
        except (ValueError, AttributeError):
            continue
        if day <= jornada:
            cutoff.append(m)

    group_stage_matches = [m for m in cutoff if m.stage == "GROUP_STAGE"]
    actual_standings = reconstruct_group_standings(group_stage_matches)

    actual_winners: dict[str, list[str]] = {api: [] for api, _, _ in KNOCKOUT_STAGES}
    for m in cutoff:
        if m.stage not in ko_names:
            continue
        winner_tla: str | None = None
        if m.winner == "HOME_TEAM":
            winner_tla = m.home_tla
        elif m.winner == "AWAY_TEAM":
            winner_tla = m.away_tla
        if winner_tla:
            actual_winners[m.stage].append(winner_tla)

    return engine.compute_general_ranking_from(predictions, actual_standings, actual_winners)


def ensure_history(client, predictions: dict, settings, path: str) -> dict:
    """Build/update ranking history for every jornada (football-day window).

    - Loads existing history from path.
    - Calls get_all_matches() ONCE; derives jornadas from football_day_of.
    - Past jornadas not already stored → ranking via reconstruct_group_standings.
    - LATEST jornada always (re)computed using the exact live ranking
      (engine.compute_general_ranking, official=False) so the newest data
      point matches /actual exactly, with no approximation.
    - Saves and returns the updated history dict.
    """
    from worldcup_bot.porra import engine  # avoid top-level circular import

    history = load_history(path)

    try:
        matches = client.get_all_matches()
    except Exception:
        log.exception("ensure_history: could not get matches from API")
        return history

    jornadas = build_jornadas(matches, settings.timezone, settings.football_day_start_hour)

    if not jornadas:
        return history

    latest = jornadas[-1]

    for jornada in jornadas:
        if jornada in history and jornada != latest:
            continue
        try:
            if jornada == latest:
                ranking = engine.compute_general_ranking(predictions, client, official=False)
            else:
                ranking = compute_ranking_at_jornada(
                    predictions,
                    matches,
                    jornada,
                    settings.timezone,
                    settings.football_day_start_hour,
                )
            history[jornada] = {
                r.username: {
                    "pos": idx + 1,
                    "pts": r.total_score,
                    "name": r.display_name,
                }
                for idx, r in enumerate(ranking)
            }
        except Exception:
            log.exception(
                "ensure_history: failed to compute ranking for jornada %s", jornada
            )

    log.info(
        "ensure_history: latest jornada %s uses exact live ranking; %d jornadas total",
        latest,
        len(history),
    )

    save_history(path, history)
    return history
