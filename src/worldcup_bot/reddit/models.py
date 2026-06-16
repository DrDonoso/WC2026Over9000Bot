"""Data models for the Reddit goal notifier."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GoalEvent:
    """A single goal event parsed from a Reddit match-thread selftext."""

    minute_text: str    # e.g. "7", "45+2"
    minute_sort: float  # for ordering: 7.0, 45.02
    scorer: str
    scoring_team: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    raw: str            # original Markdown line
    key: str            # stable dedup id: "{post_id}:{hs}-{as}@{min}:{scorer_norm}"


@dataclass
class ThreadInfo:
    """Minimal metadata about a Reddit match thread post."""

    post_id: str
    title: str
    permalink: str
    created_utc: float


@dataclass
class MatchThreadResult:
    """A match thread paired with its matched live fixture and parsed goal events."""

    thread: ThreadInfo
    events: list[GoalEvent] = field(default_factory=list)
    home_tla: str = ""
    away_tla: str = ""
