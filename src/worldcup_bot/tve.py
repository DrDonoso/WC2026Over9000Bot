"""TVE (RTVE) broadcast schedule integration.

Fetches the RTVE public schedule API (no auth) to determine which World Cup
fixtures are broadcast on Spanish public TV, adding a 📺 marker.

API: https://www.rtve.es/api/schedule/{slug}.json
Channels: tv1 (La 1), dep (Teledeporte) — current broadcast week only.
WC matches: idPrograma == 1030562, excluding "resumen" items.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytz
import requests

log = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

_BASE_URL = "https://www.rtve.es/api/schedule/{slug}.json"

# Slugs and their display labels (La 1 preferred over Teledeporte on tie)
_CHANNELS: dict[str, str] = {
    "tv1": "La 1",
    "dep": "Teledeporte",
}

WC_PROGRAMA_ID = 1030562

_UTC = timezone.utc
_MADRID_TZ = pytz.timezone("Europe/Madrid")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_WC_EPISODE_PREFIX = re.compile(r"^futbol\s+copa\s+mundo\s+fifa\s*", re.IGNORECASE)
_KICKOFF_RE = re.compile(r"\((\d{2}:\d{2})\)")
_MATCH_WINDOW = timedelta(minutes=20)

# Short TTL used when fetches succeed but no WC matches are returned — the RTVE
# schedule is typically published mid-morning (~10:40), AFTER the 09:00 daily
# update runs, so an empty result here may just mean "not yet updated".
_EMPTY_RESULT_TTL = 1800  # 30 minutes


# ── normalisation ─────────────────────────────────────────────────────────────


def _norm(s: str) -> str:
    """Normalize a Spanish team name: accent-strip, lowercase, trim whitespace."""
    nfkd = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ── Spanish team name → FIFA TLA ──────────────────────────────────────────────
# Keys are pre-normalized (accent-stripped lowercase) so lookup is case and
# accent-insensitive.  Cross-checked against data/tla_map.py.

_ES_RAW: dict[str, str] = {
    # UEFA
    "España": "ESP",
    "Espana": "ESP",
    "Alemania": "GER",
    "Francia": "FRA",
    "Portugal": "POR",
    "Bélgica": "BEL",
    "Belgica": "BEL",
    "Suiza": "SUI",
    "Noruega": "NOR",
    "Escocia": "SCO",
    "Inglaterra": "ENG",
    "Croacia": "CRO",
    "Turquía": "TUR",
    "Turquia": "TUR",
    "Austria": "AUT",
    "Países Bajos": "NED",
    "Paises Bajos": "NED",
    "Holanda": "NED",
    "Suecia": "SWE",
    "Bosnia": "BIH",
    "Bosnia Herzegovina": "BIH",
    "Serbia": "SRB",
    "Eslovaquia": "SVK",
    "Eslovenia": "SVN",
    "Hungría": "HUN",
    "Hungria": "HUN",
    "Rumanía": "ROU",
    "Rumania": "ROU",
    "Ucrania": "UKR",
    "Dinamarca": "DEN",
    "Finlandia": "FIN",
    "Gales": "WAL",
    "País de Gales": "WAL",
    "Pais de Gales": "WAL",
    "Irlanda del Norte": "NIR",
    "Italia": "ITA",
    "Polonia": "POL",
    "Albania": "ALB",
    "Georgia": "GEO",
    "República Checa": "CZE",
    "Republica Checa": "CZE",
    "Chipre": "CYP",
    "Montenegro": "MNE",
    "Macedonia del Norte": "MKD",
    "Armenia": "ARM",
    "Azerbaiyán": "AZE",
    "Azerbaiyan": "AZE",
    # CONMEBOL
    "Argentina": "ARG",
    "Brasil": "BRA",
    "Colombia": "COL",
    "Ecuador": "ECU",
    "Uruguay": "URY",
    "Paraguay": "PAR",
    "Venezuela": "VEN",
    "Bolivia": "BOL",
    "Chile": "CHI",
    "Perú": "PER",
    "Peru": "PER",
    # CONCACAF
    "México": "MEX",
    "Mexico": "MEX",
    "Estados Unidos": "USA",
    "EE. UU.": "USA",
    "EEUU": "USA",
    "Canadá": "CAN",
    "Canada": "CAN",
    "Panamá": "PAN",
    "Panama": "PAN",
    "Haití": "HAI",
    "Haiti": "HAI",
    "Curaçao": "CUW",
    "Curacao": "CUW",
    "Curazao": "CUW",
    "Jamaica": "JAM",
    "Costa Rica": "CRC",
    "Trinidad y Tobago": "TRI",
    "Trinidad": "TRI",
    # AFC
    "Arabia Saudí": "KSA",
    "Arabia Saudi": "KSA",
    "Arabia Saudi": "KSA",
    "Japón": "JPN",
    "Japon": "JPN",
    "Corea del Sur": "KOR",
    "Corea Sur": "KOR",
    "Irán": "IRN",
    "Iran": "IRN",
    "Catar": "QAT",
    "Qatar": "QAT",
    "Australia": "AUS",
    "Jordania": "JOR",
    "Uzbekistán": "UZB",
    "Uzbekistan": "UZB",
    "China": "CHN",
    "Indonesia": "IDN",
    # CAF
    "Marruecos": "MAR",
    "Senegal": "SEN",
    "Ghana": "GHA",
    "Nigeria": "NGA",
    "Egipto": "EGY",
    "Argelia": "ALG",
    "Túnez": "TUN",
    "Tunez": "TUN",
    "Tunez resumen": "TUN",   # never matches — just ensures norm variant is there
    "Costa de Marfil": "CIV",
    "Sudáfrica": "RSA",
    "Sudafrica": "RSA",
    "Cabo Verde": "CPV",
    "Camerún": "CMR",
    "Camerun": "CMR",
    "Malí": "MLI",
    "Mali": "MLI",
    # OFC
    "Nueva Zelanda": "NZL",
    "Fiyi": "FIJ",
}

# Build the lookup dict with normalized keys
ES_NAME_TO_TLA: dict[str, str] = {_norm(k): v for k, v in _ES_RAW.items()}


# ── dataclass ─────────────────────────────────────────────────────────────────


@dataclass
class TveBroadcast:
    """A single WC fixture broadcast on TVE."""

    kickoff_utc: datetime    # tz-aware UTC
    home_tla: str | None
    away_tla: str | None
    channel: str             # "La 1" or "Teledeporte"


# ── TTL cache ─────────────────────────────────────────────────────────────────

_tve_cache: dict = {"data": None, "fetched_at": 0.0}


# ── fetch ─────────────────────────────────────────────────────────────────────


def fetch_rtve_schedule(slug: str, *, timeout: int = 10) -> dict | None:
    """Fetch the RTVE schedule for *slug*.

    Returns the parsed JSON dict or None on any error (logs warning, never raises).
    SSL verification uses the system CA bundle (truststore compatible); no verify=False.
    """
    url = _BASE_URL.format(slug=slug)
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("fetch_rtve_schedule(%r): %s", slug, exc)
        return None


# ── parsers ───────────────────────────────────────────────────────────────────


def _is_resumen(item: dict) -> bool:
    """Return True if the item is a highlights/replay (resumen) show."""
    combined = " ".join(
        [
            item.get("name", ""),
            item.get("original_episode_name", ""),
            item.get("original_event_name", ""),
        ]
    ).lower()
    return "resumen" in combined


def _parse_kickoff_utc(item: dict, channel_label: str) -> datetime | None:
    """Return the kickoff as a UTC-aware datetime, or None if unparseable."""
    begintime = item.get("begintime", "")
    if len(begintime) < 8:
        return None

    date_str = begintime[:8]  # YYYYMMDD

    time_str: str | None = None

    # La 1 often buries the actual kickoff in description as "(HH:MM)"
    if channel_label == "La 1":
        desc = item.get("description", "")
        m = _KICKOFF_RE.search(desc)
        if m:
            time_str = m.group(1)  # "HH:MM"

    # Fallback: extract time from begintime itself (YYYYMMDDHHMMSS)
    if time_str is None:
        if len(begintime) >= 12:
            time_str = f"{begintime[8:10]}:{begintime[10:12]}"
        else:
            return None

    try:
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M")
        # Localize in Madrid (handles DST automatically — do NOT hardcode UTC offset)
        local_dt = _MADRID_TZ.localize(dt_naive)
        return local_dt.astimezone(_UTC)
    except Exception as exc:
        log.debug("TVE: failed to parse kickoff from item %r: %s", item, exc)
        return None


def _parse_teams(item: dict) -> tuple[str | None, str | None]:
    """Extract (home_tla, away_tla) from original_episode_name / original_event_name.

    Returns (None, None) if the name fields are absent or unparseable.
    Individual TLAs may be None when a team name isn't in ES_NAME_TO_TLA.
    """
    for field_name in ("original_episode_name", "original_event_name"):
        raw = (item.get(field_name) or "").strip()
        if not raw:
            continue

        # Strip "Futbol Copa Mundo Fifa " prefix (case-insensitive)
        stripped = _WC_EPISODE_PREFIX.sub("", raw).strip()

        # Split on " - " or " / "
        if " - " in stripped:
            parts = stripped.split(" - ", 1)
        elif " / " in stripped:
            parts = stripped.split(" / ", 1)
        else:
            continue

        if len(parts) != 2:
            continue

        home_raw, away_raw = parts
        home_tla = ES_NAME_TO_TLA.get(_norm(home_raw))
        away_tla = ES_NAME_TO_TLA.get(_norm(away_raw))
        return home_tla, away_tla

    return None, None


def parse_wc_broadcasts(
    schedule_json: dict, channel_label: str
) -> list[TveBroadcast]:
    """Filter and parse WC matches from an RTVE schedule JSON response.

    Keeps items where idPrograma == WC_PROGRAMA_ID and "resumen" is NOT in
    the name/episode fields.  Skips items whose kickoff cannot be parsed.
    """
    items = schedule_json.get("items", [])
    if not isinstance(items, list):
        return []

    broadcasts: list[TveBroadcast] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # Must be a WC programme
        if item.get("idPrograma") != WC_PROGRAMA_ID:
            continue

        # Exclude highlights/replay shows
        if _is_resumen(item):
            continue

        kickoff_utc = _parse_kickoff_utc(item, channel_label)
        if kickoff_utc is None:
            log.debug("TVE: skipping item with unparseable kickoff: %r", item)
            continue

        home_tla, away_tla = _parse_teams(item)

        broadcasts.append(
            TveBroadcast(
                kickoff_utc=kickoff_utc,
                home_tla=home_tla,
                away_tla=away_tla,
                channel=channel_label,
            )
        )

    return broadcasts


# ── match correlation ─────────────────────────────────────────────────────────


def tve_channel_for(
    match,  # worldcup_bot.api.models.Match — avoid circular import
    broadcasts: list[TveBroadcast],
) -> str | None:
    """Return the TVE channel label for *match*, or None if not on TVE.

    Matching rules (in priority order):
    1. Primary: kickoff within ±20 min of match.utc_date AND unordered TLA pair matches.
    2. Time-only fallback (when broadcast TLAs are None): only when exactly one
       broadcast falls within the time window (avoids mismatching simultaneous games).
    3. Same-day TLA-pair fallback: same UTC calendar date AND exact TLA pair, regardless
       of time offset.  Handles the case where RTVE's description hasn't been updated
       with the actual kickoff time yet at 09:00, so _parse_kickoff_utc falls back to
       begintime (the pre-match show start), which can be >20 min before real kickoff.
       Requires both TLAs to be known to avoid mismatching simultaneous same-day games.
    - If both La 1 and Teledeporte qualify, La 1 wins.
    """
    try:
        match_utc = datetime.strptime(
            match.utc_date, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=_UTC)
    except (ValueError, AttributeError):
        return None

    match_tlas = {match.home_tla, match.away_tla}
    match_date = match_utc.date()

    # All broadcasts within the time window (used for time-only fallback check)
    time_window_hits = [
        b for b in broadcasts if abs(b.kickoff_utc - match_utc) <= _MATCH_WINDOW
    ]

    candidates: list[str] = []
    for b in time_window_hits:
        if b.home_tla is not None and b.away_tla is not None:
            # Full match: time window + TLA pair
            if {b.home_tla, b.away_tla} == match_tlas:
                candidates.append(b.channel)
        else:
            # Time-only fallback: safe only when this is the sole broadcast in window
            if len(time_window_hits) == 1:
                candidates.append(b.channel)

    # Same-day TLA-pair fallback — only when primary window matched nothing
    if not candidates:
        for b in broadcasts:
            if (
                b.home_tla is not None
                and b.away_tla is not None
                and {b.home_tla, b.away_tla} == match_tlas
                and b.kickoff_utc.date() == match_date
            ):
                candidates.append(b.channel)

    if not candidates:
        return None
    if "La 1" in candidates:
        return "La 1"
    return candidates[0]


# ── orchestrated loader ───────────────────────────────────────────────────────


def load_tve_broadcasts(
    *,
    ttl_seconds: int = 21600,  # 6 hours
    tve_enabled: bool = True,
) -> list[TveBroadcast]:
    """Fetch TVE schedule for both channels, parse WC matches, TTL-cache the result.

    - If *tve_enabled* is False, returns [] immediately without any HTTP request.
    - If ALL channel fetches fail (all return None), returns [] WITHOUT caching so
      the next call retries immediately (transient RTVE errors don't poison 6 h).
    - If fetches succeed but no WC matches are found, caches with _EMPTY_RESULT_TTL
      (30 min) so the bot retries well before the next match window.  RTVE publishes
      today's schedule mid-morning (~10:40), after the 09:00 daily update runs.
    - Cache is module-level; repeated calls within the effective TTL return cached data.
    """
    if not tve_enabled:
        return []

    now = time.monotonic()
    if (
        _tve_cache["data"] is not None
        and now - _tve_cache["fetched_at"] < _tve_cache.get("_ttl", ttl_seconds)
    ):
        return _tve_cache["data"]

    broadcasts: list[TveBroadcast] = []
    any_fetch_ok = False
    for slug, label in _CHANNELS.items():
        sched = fetch_rtve_schedule(slug)
        if sched is not None:
            any_fetch_ok = True
            broadcasts.extend(parse_wc_broadcasts(sched, label))

    if any_fetch_ok:
        # Full TTL when we found WC matches; short TTL when empty (may not be updated yet)
        effective_ttl = ttl_seconds if broadcasts else min(ttl_seconds, _EMPTY_RESULT_TTL)
        _tve_cache["data"] = broadcasts
        _tve_cache["fetched_at"] = now
        _tve_cache["_ttl"] = effective_ttl
    # else: all fetches failed → don't update cache → retry on next call

    return broadcasts
