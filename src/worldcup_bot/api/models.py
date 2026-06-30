"""API data models (dataclasses)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Match:
    id: int
    utc_date: str           # ISO8601 string
    status: str             # SCHEDULED, IN_PLAY, PAUSED, FINISHED, etc.
    stage: str              # GROUP_STAGE, LAST_16, QUARTER_FINALS, etc.
    group: str | None       # "GROUP_A" etc. — only for group stage
    home_tla: str
    away_tla: str
    home_name: str
    away_name: str
    home_score: int | None  # on-pitch score (regular+ET); excludes penalty shootout
    away_score: int | None
    winner: str | None      # HOME_TEAM, AWAY_TEAM, DRAW, or None
    duration: str = ""      # REGULAR, EXTRA_TIME, PENALTY_SHOOTOUT
    penalty_home: int | None = None  # shootout score (None if no shootout)
    penalty_away: int | None = None

    @property
    def in_penalty_shootout(self) -> bool:
        """True once the match is in or past a penalty shootout.

        Detected from any signal football-data exposes (``duration`` or a
        populated ``penalties`` block), so goal detectors can stop treating
        penalty kicks as goals.
        """
        return (
            self.duration == "PENALTY_SHOOTOUT"
            or self.penalty_home is not None
            or self.penalty_away is not None
        )


@dataclass
class Standing:
    group: str              # "GROUP_A"
    position: int
    tla: str
    team_name: str
    points: int
    played: int
    goal_difference: int = 0
    goals_for: int = 0


@dataclass
class StageResult:
    stage: str
    home_tla: str
    away_tla: str
    winner_tla: str | None  # None if no result yet
