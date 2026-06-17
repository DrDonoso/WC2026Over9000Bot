"""OpenAI-powered scorer extraction from Reddit match threads.

Used as enrichment when football-data.org (the authoritative score source)
does not provide scorer/minute on the free tier.  Handles both the ESPN-structured
format and the human-narrated r/soccer format because the LLM reads natural language.
"""

from __future__ import annotations

import json
import logging
import re

from worldcup_bot.ai.client import AIClient

log = logging.getLogger(__name__)

# Maximum characters to send to the LLM (keep token count reasonable)
_MAX_THREAD_CHARS = 8000

# System prompt template — filled with match context before each call.
# Uses double-braces for literal JSON braces in the format string.
_SYSTEM_TEMPLATE = (
    "Eres un extractor de información. Te doy el texto de un hilo de Reddit de un partido "
    "y el dato de que {scoring_team} acaba de marcar, dejando el marcador "
    "{home_team} {new_home}-{new_away} {away_team}. "
    'Devuelve ÚNICAMENTE JSON {{"scorer": <nombre del goleador de ESE gol o null>, '
    '"minute": <minuto como \'66\' o \'90+6\' o null>}}. '
    "Es el gol MÁS RECIENTE de {scoring_team}. "
    "No inventes; si no lo encuentras, null."
)


def _trim_thread(thread_text: str) -> str:
    """Focus the LLM on the goal-bearing region.

    r/soccer thread bodies often carry trailing nav/footer junk, so a blind tail
    slice misses the goals.  Anchor on the "MATCH EVENTS" marker (and include the
    scorers summary that sits just above it) when present; otherwise keep the head
    of the post (where the content lives).
    """
    marker = thread_text.find("MATCH EVENTS")
    if marker != -1:
        start = max(0, marker - 1500)
        return thread_text[start:start + _MAX_THREAD_CHARS]
    if len(thread_text) > _MAX_THREAD_CHARS:
        return thread_text[:_MAX_THREAD_CHARS]
    return thread_text


def _parse_extractor_json(raw: str) -> tuple[str | None, str | None]:
    """Parse the LLM JSON response → (scorer, minute).

    Handles:
    - Clean JSON: {"scorer": "Kylian Mbappé", "minute": "66"}
    - Fenced JSON: ```json\\n{...}\\n```
    - Garbage / parse error → (None, None)
    """
    # Strip ``` code fences (with optional language tag)
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip()

    try:
        data = json.loads(text)
        scorer = data.get("scorer") or None
        minute = data.get("minute") or None
        if scorer is not None:
            scorer = str(scorer).strip() or None
        if minute is not None:
            minute = str(minute).strip() or None
        return scorer, minute
    except Exception:
        log.warning("goal_extractor: could not parse JSON from AI response: %r", raw[:200])
        return None, None


async def extract_scorer(
    ai: AIClient,
    thread_text: str,
    scoring_team: str,
    home_team: str,
    away_team: str,
    new_home: int,
    new_away: int,
) -> tuple[str | None, str | None]:
    """Ask the AI to identify who scored the most recent goal for scoring_team.

    Returns (scorer_name | None, minute_str | None).
    Never raises — returns (None, None) on any failure so the caller can degrade
    to a goal message without scorer info.

    The prompt works for both the ESPN-structured thread format and human-narrated
    r/soccer threads (e.g. 66': [](#icon-ball-big)**GOAL FRANCE!! ...**).
    """
    trimmed = _trim_thread(thread_text)
    system = _SYSTEM_TEMPLATE.format(
        scoring_team=scoring_team,
        home_team=home_team,
        new_home=new_home,
        new_away=new_away,
        away_team=away_team,
    )
    try:
        raw = await ai.complete(
            system=system,
            user=trimmed,
            temperature=0.0,
            max_completion_tokens=100,
        )
        return _parse_extractor_json(raw)
    except Exception as exc:
        log.warning("extract_scorer failed: %s", exc)
        return None, None
