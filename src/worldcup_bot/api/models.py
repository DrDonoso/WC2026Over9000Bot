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
    home_score: int | None
    away_score: int | None
    winner: str | None      # HOME_TEAM, AWAY_TEAM, DRAW, or None


@dataclass
class Standing:
    group: str              # "GROUP_A"
    position: int
    tla: str
    team_name: str
    points: int
    played: int


@dataclass
class StageResult:
    stage: str
    home_tla: str
    away_tla: str
    winner_tla: str | None  # None if no result yet
