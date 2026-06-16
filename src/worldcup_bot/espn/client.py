"""ESPN Stats API client — sync, thin, mockable.

GET https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={gameId}
Returns normalized stats dict: {"home": {"name": ..., "stats": {name: displayValue}}, "away": ...}
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

_ESPN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_ESPN_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary"
)


class ESPNClient:
    """Thin sync client for ESPN's public soccer summary API."""

    def __init__(
        self,
        league_slug: str = "fifa.world",
        session: requests.Session | None = None,
    ) -> None:
        self._league = league_slug
        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": _ESPN_UA})

    def get_match_stats(self, game_id: str) -> dict | None:
        """Fetch ESPN match summary and return normalized home/away stats dict.

        Returns:
            {"home": {"name": str, "stats": {stat_name: display_value}},
             "away": {"name": str, "stats": {stat_name: display_value}}}
            or None on any error.
        """
        url = _ESPN_SUMMARY_URL.format(league=self._league)
        try:
            resp = self._session.get(url, params={"event": game_id}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("ESPNClient.get_match_stats failed for game_id=%s: %s", game_id, exc)
            return None

        teams = data.get("boxscore", {}).get("teams", [])
        if not teams:
            log.warning("ESPNClient: no boxscore.teams in response for game_id=%s", game_id)
            return None

        result: dict[str, dict] = {}
        for team_entry in teams:
            side = team_entry.get("homeAway", "")
            if side not in ("home", "away"):
                continue
            team_name = team_entry.get("team", {}).get("displayName", "")
            stats: dict[str, str] = {}
            for stat in team_entry.get("statistics", []):
                name = stat.get("name", "")
                value = stat.get("displayValue", "")
                if name:
                    stats[name] = value
            result[side] = {"name": team_name, "stats": stats}

        if "home" not in result or "away" not in result:
            log.warning(
                "ESPNClient: could not split home/away stats for game_id=%s (got sides: %s)",
                game_id,
                list(result.keys()),
            )
            return None

        return result
