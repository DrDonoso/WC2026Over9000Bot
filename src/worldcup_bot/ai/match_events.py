"""OpenAI-powered live match event extraction from Reddit match threads.

Extracts minute, goals, cards, substitutions and current lineups from the
'MATCH EVENTS' section
of an r/soccer match thread.  Used to enrich /endirecto with live detail that
football-data.org does not provide on the free tier.
"""

from __future__ import annotations

import json
import logging
import re

from worldcup_bot.ai.client import AIClient

log = logging.getLogger(__name__)

# Maximum characters to send to the LLM (keep token count reasonable)
_MAX_THREAD_CHARS = 8000

# System prompt — uses double-braces for literal JSON braces
_SYSTEM_TEMPLATE = (
    "Eres un extractor de información deportiva. "
    "Te doy el texto de un hilo de Reddit de un partido de fútbol. "
    "El partido es {home} vs {away}; usa esos nombres exactos para el campo 'team'. "
    "Devuelve ÚNICAMENTE JSON con este esquema exacto:\n"
    '{{"minute": <minuto actual aproximado como string p.ej. "74" o "45+5", o null>, '
    '"goals": [{{"minute": "6", "team": "<nombre equipo>", "scorer": "<jugador>"}}], '
    '"cards": [{{"minute": "13", "team": "<equipo>", "player": "<jugador>", "type": "yellow"}}], '
    '"subs": [{{"minute": "45", "team": "<equipo>", "in": "<entra>", "out": "<sale>"}}], '
    '"lineup": {{"home": ["<jugador1>", ...], "away": ["<jugador1>", ...]}}}}\n'
    "Reglas: no inventes información; si no hay datos, listas vacías y minute null; "
    "ordena los eventos por minuto ascendente. "
    "Para tarjetas: usa 'yellow' para amarilla y 'red' para roja. "
    'Para lineup: devuelve el XI actual en el campo (once inicial con cambios '
    'aplicados: quita jugadores que salieron, añade los que entraron). {home} = '
    'equipo local, {away} = equipo visitante. Si no puedes determinar el lineup, '
    'devuelve {{"home": [], "away": []}}.'
)

_EMPTY_EVENTS: dict = {
    "minute": None,
    "goals": [],
    "cards": [],
    "subs": [],
    "lineup": {"home": [], "away": []},
}


def _trim_events_region(thread_text: str) -> str:
    """Focus the LLM on the MATCH EVENTS region, dropping MATCH STATS noise.

    Anchors on the earlier of the 'Starting XI' or 'MATCH EVENTS' markers, then
    truncates at 'MATCH STATS' if present (removes the stats table).
    Falls back to the head of the post when the marker is absent.
    """
    markers = [idx for idx in (thread_text.find("Starting XI"), thread_text.find("MATCH EVENTS")) if idx != -1]
    if markers:
        start = max(0, min(markers) - 200)
        snippet = thread_text[start:]
        stats_idx = snippet.find("MATCH STATS")
        if stats_idx != -1:
            snippet = snippet[:stats_idx]
        return snippet[:_MAX_THREAD_CHARS]
    return thread_text[:_MAX_THREAD_CHARS]


def _parse_events_json(raw: str) -> dict:
    """Parse the LLM JSON response.

    Handles fenced JSON (```json … ```) and plain JSON.
    Returns an empty dict on any parse failure.
    """
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data
    except Exception:
        log.warning("match_events: could not parse JSON from AI response: %r", raw[:200])
        return {}


def _coerce_events(raw: dict) -> dict:
    """Normalise the parsed dict: ensure lists of dicts with string values.

    Drops malformed entries; coerces all values to strings.
    """

    def _coerce_list(key: str, required_keys: list[str]) -> list[dict]:
        items = raw.get(key, [])
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if not all(k in item for k in required_keys):
                continue
            result.append({k: str(v) if v is not None else "" for k, v in item.items()})
        return result

    def _coerce_lineup(raw_data: dict) -> dict:
        lineup = raw_data.get("lineup", {})
        if not isinstance(lineup, dict):
            return {"home": [], "away": []}

        def _clean(side: str) -> list[str]:
            players = lineup.get(side, [])
            if not isinstance(players, list):
                return []
            result = []
            for player in players:
                if not isinstance(player, str):
                    continue
                cleaned = player.strip()
                if cleaned:
                    result.append(cleaned)
            return result

        return {"home": _clean("home"), "away": _clean("away")}

    minute = raw.get("minute")
    if minute is not None:
        minute = str(minute).strip() or None

    return {
        "minute": minute,
        "goals": _coerce_list("goals", ["minute", "team", "scorer"]),
        "cards": _coerce_list("cards", ["minute", "team", "player", "type"]),
        "subs": _coerce_list("subs", ["minute", "team", "in", "out"]),
        "lineup": _coerce_lineup(raw),
    }


async def extract_match_events(
    ai: AIClient,
    thread_text: str,
    home_team: str,
    away_team: str,
) -> dict:
    """Ask the AI to extract live match events from an r/soccer match thread.

    Returns a dict with keys: minute, goals, cards, subs, lineup.
    Never raises — returns the empty structure on any failure.
    """
    trimmed = _trim_events_region(thread_text)
    system = _SYSTEM_TEMPLATE.format(home=home_team, away=away_team)
    try:
        raw = await ai.complete(
            system=system,
            user=trimmed,
            temperature=0.0,
            max_completion_tokens=1200,
        )
        parsed = _parse_events_json(raw)
        if not parsed:
            return dict(_EMPTY_EVENTS)
        return _coerce_events(parsed)
    except Exception as exc:
        log.warning("extract_match_events failed: %s", exc)
        return dict(_EMPTY_EVENTS)
