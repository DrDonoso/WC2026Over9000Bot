"""Parse Reddit match-thread selftext to extract goal events.

Handles the "MATCH EVENTS | via ESPN" section format used by r/soccer.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from worldcup_bot.reddit.models import GoalEvent

log = logging.getLogger(__name__)

# ── text normalisation ────────────────────────────────────────────────────────

def _strip_accents(text: str) -> str:
    """Remove diacritics/accents from text."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_name(name: str) -> str:
    return _strip_accents(name.strip()).lower().replace(" ", "_")


def _parse_minute_sort(minute_text: str) -> float:
    """Parse '45+2' → 45.02, '7' → 7.0."""
    parts = minute_text.split("+")
    try:
        base = int(parts[0])
        stoppage = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 0.0
    return base + stoppage / 100


# ── regexes ───────────────────────────────────────────────────────────────────

# Minute at the start of a line (with or without ** bold wrappers)
_MINUTE_RE = re.compile(r"^[\s\*]*(\d+(?:\+\d+)?)[\'\u2019]", re.MULTILINE)

# Goal event body: "Goal! HomeTeam hs, AwayTeam as. Scorer (ScoringTeam)"
_GOAL_RE = re.compile(
    r"Goal!\s+"
    r"(?P<home>.+?)\s+(?P<hs>\d+),\s+(?P<away>.+?)\s+(?P<as_>\d+)\.\s+"
    r"(?P<scorer>.+?)\s+\((?P<team>[^)]+)\)",
    re.IGNORECASE,
)

# Lines we should unconditionally skip (not real goals)
_SKIP_PATTERNS = re.compile(
    r"(goal\s+disallowed|disallowed|var[\s\u2014\-]+no\s+goal|"
    r"penalty\s+missed|no\s+goal|off?side)",
    re.IGNORECASE,
)

# Own-goal indicator
_OWN_GOAL_RE = re.compile(r"\bown\s+goal\b", re.IGNORECASE)

# Non-goal event emojis (cards, subs — present but no ⚽)
_CARD_SUB_RE = re.compile(r"[\U0001F7E8\U0001F7E5\U0001F504\U0001F6B7🟨🟥🔄]")


def _fuzzy_match(a: str, b: str) -> bool:
    from difflib import SequenceMatcher
    na, nb = _strip_accents(a).lower(), _strip_accents(b).lower()
    return na == nb or na in nb or nb in na or SequenceMatcher(None, na, nb).ratio() >= 0.80


def parse_goal_events(selftext: str, post_id: str = "") -> list[GoalEvent]:
    """Parse all goal events from a Reddit match thread selftext.

    Returns a list of GoalEvent in document order.  Non-goal lines (cards,
    subs, disallowed goals, VAR cancellations, missed penalties) are ignored.
    """
    events: list[GoalEvent] = []

    for raw_line in selftext.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Must contain the ⚽ emoji and "Goal!" text
        if "⚽" not in line and "\u26bd" not in line:
            continue
        if "goal!" not in line.lower():
            continue

        # Skip explicitly non-goal goal-adjacent lines
        if _SKIP_PATTERNS.search(line):
            log.debug("Skipping non-goal line: %s", line[:80])
            continue

        # Strip markdown bold markers for cleaner parsing
        clean = line.replace("**", "").replace("__", "")

        # Extract minute
        m_min = _MINUTE_RE.match(clean)
        if not m_min:
            # Try searching anywhere in the cleaned line
            m_min = re.search(r"(\d+(?:\+\d+)?)[\'\u2019]", clean)
        if not m_min:
            log.debug("Could not extract minute from: %s", clean[:80])
            continue

        minute_text = m_min.group(1)
        minute_sort = _parse_minute_sort(minute_text)

        # Extract goal details
        m_goal = _GOAL_RE.search(clean)
        if not m_goal:
            log.debug("Could not match goal pattern in: %s", clean[:80])
            continue

        home_team = m_goal.group("home").strip()
        away_team = m_goal.group("away").strip()
        home_score = int(m_goal.group("hs"))
        away_score = int(m_goal.group("as_"))
        raw_scorer = m_goal.group("scorer").strip()
        parsed_team = m_goal.group("team").strip()

        # Own goal handling
        is_own_goal = bool(_OWN_GOAL_RE.search(clean))
        if is_own_goal:
            scorer = f"{raw_scorer} (en propia)"
            # The player's team scored the OG → benefiting team is the opponent
            if _fuzzy_match(parsed_team, home_team):
                scoring_team = away_team
            elif _fuzzy_match(parsed_team, away_team):
                scoring_team = home_team
            else:
                scoring_team = parsed_team  # best effort
        else:
            scorer = raw_scorer
            scoring_team = parsed_team

        scorer_norm = _normalize_name(scorer)
        key = f"{post_id}:{home_score}-{away_score}@{minute_text}:{scorer_norm}"

        events.append(
            GoalEvent(
                minute_text=minute_text,
                minute_sort=minute_sort,
                scorer=scorer,
                scoring_team=scoring_team,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                raw=raw_line,
                key=key,
            )
        )

    return events
