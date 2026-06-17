"""football-data.org HTTP client (synchronous, requests-based).

Thin wrapper that:
- Authenticates via X-Auth-Token header.
- Respects 10 req/min (free tier) via in-memory TTL cache.
- Raises FootballAPIError on HTTP errors so handlers can translate to Spanish.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytz
import requests

from worldcup_bot.api.cache import TTLCache
from worldcup_bot.api.models import Match, Standing, StageResult

log = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"


class FootballAPIError(Exception):
    """Raised on any non-200 response from football-data.org."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class FootballDataClient:
    def __init__(
        self,
        api_key: str,
        competition_code: str = "WC",
        cache: TTLCache | None = None,
    ) -> None:
        self._api_key = api_key
        self._competition = competition_code
        self._cache = cache or TTLCache(ttl=60)
        self._session = requests.Session()
        self._session.headers.update({"X-Auth-Token": api_key})

    # ── low-level fetch ──────────────────────────────────────────────────────

    def _get(self, url: str, params: dict | None = None) -> dict:
        cache_key = url
        if params:
            qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            cache_key = f"{url}?{qs}"

        cached = self._cache.get(cache_key)
        if cached is not None:
            log.debug("Cache hit: %s", cache_key)
            return cached

        log.debug("Fetching: %s", cache_key)
        resp = self._session.get(url, params=params, timeout=15)

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "")
            log.warning(
                "HTTP 429 rate limit on %s%s",
                cache_key,
                f" — Retry-After: {retry_after}" if retry_after else "",
            )
            raise FootballAPIError(429, "Rate limit alcanzado")
        if resp.status_code != 200:
            raise FootballAPIError(resp.status_code, f"HTTP {resp.status_code}")

        data = resp.json()
        self._cache.set(cache_key, data)
        return data

    # ── public API ───────────────────────────────────────────────────────────

    def get_standings(self) -> list[Standing]:
        """Return all group standings, sorted by group then position."""
        url = f"{BASE_URL}/competitions/{self._competition}/standings"
        data = self._get(url)

        result: list[Standing] = []
        for group_block in data.get("standings", []):
            group_name = self._normalize_group(group_block.get("group", ""))
            for entry in group_block.get("table", []):
                result.append(
                    Standing(
                        group=group_name,
                        position=entry["position"],
                        tla=entry["team"]["tla"],
                        team_name=entry["team"]["name"],
                        points=entry["points"],
                        played=int(entry.get("playedGames", 0)),
                    )
                )
        return result

    def get_all_matches(self) -> list[Match]:
        """Return all competition matches (schedule + results)."""
        url = f"{BASE_URL}/competitions/{self._competition}/matches"
        data = self._get(url)
        return [self._parse_match(m) for m in data.get("matches", [])]

    def get_stage_results(self, stage: str) -> list[StageResult]:
        """Return finished match results for a specific knockout stage.

        stage: API name e.g. "LAST_16", "QUARTER_FINALS".
        """
        matches = self.get_all_matches()
        results = []
        for m in matches:
            if m.stage == stage and m.status == "FINISHED":
                winner_tla: str | None = None
                if m.winner == "HOME_TEAM":
                    winner_tla = m.home_tla
                elif m.winner == "AWAY_TEAM":
                    winner_tla = m.away_tla
                results.append(
                    StageResult(
                        stage=stage,
                        home_tla=m.home_tla,
                        away_tla=m.away_tla,
                        winner_tla=winner_tla,
                    )
                )
        return results

    def _football_day_bounds(
        self, tz_name: str, day_offset: int = 0, anchor_hour: int = 9
    ) -> tuple[datetime, datetime]:
        """Return (start, end) aware datetimes for the football-day window.

        The "football day" is the 24h block [anchor:00, anchor:00) that
        contains ``now`` in local time.  If now is before the anchor, the
        active block started at anchor the previous calendar day.
        ``day_offset`` shifts the resulting block by whole days.
        """
        local_tz = pytz.timezone(tz_name)
        now_local = datetime.now(local_tz)
        naive_anchor = now_local.replace(tzinfo=None).replace(
            hour=anchor_hour, minute=0, second=0, microsecond=0
        )
        anchor = local_tz.localize(naive_anchor)
        start = anchor if now_local >= anchor else anchor - timedelta(days=1)
        start = start + timedelta(days=day_offset)
        end = start + timedelta(days=1)
        return start, end

    def get_football_day_matches(
        self,
        tz_name: str = "Europe/Madrid",
        day_offset: int = 0,
        anchor_hour: int = 9,
    ) -> list[Match]:
        """Return matches in the 24h football-day window [anchor:00, anchor:00).

        ``day_offset=0`` → current window (used by /hoy).
        ``day_offset=-1`` → previous window (used by /ayer).
        """
        start, end = self._football_day_bounds(tz_name, day_offset, anchor_hour)
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        result = []
        for m in self.get_all_matches():
            try:
                utc_dt = datetime.strptime(m.utc_date, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, AttributeError):
                log.warning("Could not parse match date: %s", getattr(m, "utc_date", None))
                continue
            if start_utc <= utc_dt < end_utc:
                result.append(m)
        result.sort(key=lambda x: x.utc_date)
        return result

    def get_next_match(self, tz_name: str = "Europe/Madrid") -> Match | None:
        """Return the next upcoming (SCHEDULED/TIMED) match."""
        matches = self.get_all_matches()
        now_utc = datetime.now(timezone.utc)

        for m in sorted(
            matches,
            key=lambda x: x.utc_date,
        ):
            if m.status in ("SCHEDULED", "TIMED"):
                try:
                    utc_dt = datetime.strptime(
                        m.utc_date, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                    if utc_dt > now_utc:
                        return m
                except ValueError:
                    continue
        return None

    def get_live_matches(self) -> list[Match]:
        """Return matches currently IN_PLAY or PAUSED."""
        matches = self.get_all_matches()
        return [m for m in matches if m.status in ("IN_PLAY", "PAUSED")]

    def get_knockout_results(self) -> dict[str, list[str]]:
        """Return a dict of stage → list of winner TLAs for all knockout stages."""
        from worldcup_bot.data.stages import KNOCKOUT_STAGES

        result: dict[str, list[str]] = {}
        for api_stage, _display, _pts in KNOCKOUT_STAGES:
            stage_results = self.get_stage_results(api_stage)
            result[api_stage] = [
                r.winner_tla for r in stage_results if r.winner_tla
            ]
        return result

    def get_finished_groups(self) -> set[str]:
        """Return GROUP_X ids whose group-stage matches are ALL FINISHED."""
        matches = self.get_all_matches()
        by_group: dict[str, list[Match]] = {}
        for m in matches:
            if m.group:
                by_group.setdefault(m.group, []).append(m)
        return {g for g, ms in by_group.items() if ms and all(x.status == "FINISHED" for x in ms)}

    def get_started_groups(self) -> set[str]:
        """Return GROUP_X ids with at least one FINISHED group-stage match."""
        matches = self.get_all_matches()
        by_group: dict[str, list[Match]] = {}
        for m in matches:
            if m.group:
                by_group.setdefault(m.group, []).append(m)
        return {g for g, ms in by_group.items() if any(x.status == "FINISHED" for x in ms)}

    def get_finished_stages(self) -> set[str]:
        """Return knockout API stage names whose matches are ALL FINISHED."""
        from worldcup_bot.data.stages import KNOCKOUT_STAGES

        ko_names = {api for api, _disp, _pts in KNOCKOUT_STAGES}
        matches = self.get_all_matches()
        by_stage: dict[str, list[Match]] = {}
        for m in matches:
            if m.stage in ko_names:
                by_stage.setdefault(m.stage, []).append(m)
        return {s for s, ms in by_stage.items() if ms and all(x.status == "FINISHED" for x in ms)}

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_group(raw: str | None) -> str | None:
        """Normalize group identifiers to canonical GROUP_X form.

        "Group A" -> "GROUP_A"; "GROUP_A" -> "GROUP_A"; None/'' -> passthrough.
        """
        if not raw:
            return raw
        return raw.strip().upper().replace(" ", "_")

    @staticmethod
    def _parse_match(m: dict) -> Match:
        score = m.get("score", {})
        full_time = score.get("fullTime", {}) or {}
        home_score = full_time.get("home")
        away_score = full_time.get("away")

        return Match(
            id=m.get("id", 0),
            utc_date=m.get("utcDate", ""),
            status=m.get("status", ""),
            stage=m.get("stage", ""),
            group=FootballDataClient._normalize_group(m.get("group")),
            home_tla=(m.get("homeTeam") or {}).get("tla", ""),
            away_tla=(m.get("awayTeam") or {}).get("tla", ""),
            home_name=(m.get("homeTeam") or {}).get("name", "Equipo local"),
            away_name=(m.get("awayTeam") or {}).get("name", "Equipo visitante"),
            home_score=home_score,
            away_score=away_score,
            winner=score.get("winner"),
        )
