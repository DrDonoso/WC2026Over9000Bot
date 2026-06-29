"""Match "camps" — split participants into the two teams of a knockout match.

For a knockout match A vs B, each participant "backs" whichever of {A, B} they
predicted to advance in that round (their round_of_X pick list).  This powers the
⚔️ "guerra de la porra" face-off shown at kickoff, in /endirecto and in the
match-finish recap.

Group-stage matches are intentionally not split (the porra predicts standings,
not head-to-head winners), so compute_match_camps returns everyone as undecided
for them and the caller simply omits the block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from worldcup_bot.data.stages import STAGE_YAML_KEYS


@dataclass
class MatchCamps:
    """Participants split by the team they back for a single match."""

    home_tla: str
    away_tla: str
    home_name: str = ""
    away_name: str = ""
    home_backers: list[str] = field(default_factory=list)
    away_backers: list[str] = field(default_factory=list)
    undecided: list[str] = field(default_factory=list)

    @property
    def total_backers(self) -> int:
        return len(self.home_backers) + len(self.away_backers)


def _side_for(udata: dict, home_tla: str, away_tla: str, yaml_key: str | None) -> str | None:
    """Return 'home', 'away' or None for one participant.

    yaml_key None (group stage) → None (face-off disabled).  Otherwise the
    participant backs whichever team appears in their pick list for that round;
    opponents can never both appear, so the result is unambiguous.
    """
    if yaml_key is None:
        return None
    picks = udata.get("knockout", {}).get(yaml_key, []) or []
    picks_up = {str(p).upper() for p in picks}
    home_in = home_tla in picks_up
    away_in = away_tla in picks_up
    if home_in and not away_in:
        return "home"
    if away_in and not home_in:
        return "away"
    return None


def compute_match_camps(
    home_tla: str,
    away_tla: str,
    stage: str,
    group: str | None,
    predictions: dict,
    *,
    home_name: str = "",
    away_name: str = "",
) -> MatchCamps:
    """Split participants into home/away/undecided for a match.

    stage uses API names (e.g. "LAST_32"); only knockout stages produce a
    split (see module docstring).  predictions is the loaded predictions dict.
    """
    yaml_key = STAGE_YAML_KEYS.get(stage)
    camps = MatchCamps(
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
    )
    for uname, udata in predictions.get("participants", {}).items():
        name = udata.get("display_name") or f"@{uname}"
        side = _side_for(udata, home_tla, away_tla, yaml_key)
        if side == "home":
            camps.home_backers.append(name)
        elif side == "away":
            camps.away_backers.append(name)
        else:
            camps.undecided.append(name)
    return camps
