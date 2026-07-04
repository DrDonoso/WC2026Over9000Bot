"""Reddit match-thread scanner.

Discovers r/soccer "Match Thread" posts for in-play fixtures by:
  1. Fetching old.reddit.com JSON search (browser headers + over18 cookie).
  2. Falling back to HTML scraping of r/soccer/new/ on 403.
  3. Fuzzy-matching thread team names against football-data live fixtures.
  4. Fetching each matched thread body (JSON preferred, HTML fallback).
  5. Parsing goal events via the parser module.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
import urllib.parse
from difflib import SequenceMatcher
from html import unescape

import requests

from worldcup_bot.api.models import Match
from worldcup_bot.reddit.models import GoalEvent, MatchThreadResult, ThreadInfo
from worldcup_bot.reddit.parser import parse_goal_events

log = logging.getLogger(__name__)

# ── Reddit endpoints ──────────────────────────────────────────────────────────

_REDDIT_SEARCH_JSON = (
    "https://old.reddit.com/r/soccer/search.json"
    "?q=flair%3A%22Match+Thread%22&restrict_sr=1&sort=new&t=day&limit=50&raw_json=1"
)
_REDDIT_NEW_HTML = "https://old.reddit.com/r/soccer/new/?limit=50"
_REDDIT_OLD_BASE = "https://old.reddit.com"

# Maximum threads to process per poll tick (politeness + rate limit)
_MAX_THREADS_PER_TICK = 5

# Courtesy delay between thread-body fetches (seconds)
_FETCH_DELAY_SECONDS = 1

# ── in-memory TTL cache constants ─────────────────────────────────────────────

_MATCH_THREADS_TTL = 30   # seconds — shared across all consumers (goal poller, /endirecto, …)
_THREAD_BODY_TTL = 90     # seconds per permalink

# Bound the thread-body cache: finished-match permalinks are never re-read (their
# TTL only expires on a subsequent read of the SAME permalink), so without an
# explicit sweep they live for the whole tournament and leak memory.
_THREAD_BODY_CACHE_MAX = 40           # entries before a sweep is triggered
_THREAD_BODY_CACHE_TTL_FACTOR = 5     # sweep entries older than N × _THREAD_BODY_TTL

# ── browser headers (proven to work from Docker) ─────────────────────────────

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "over18=1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# ── team normalisation (reused from reference implementation) ─────────────────

# WC-specific alias map: covers common Reddit name differences
WC_TEAM_ALIASES: dict[str, str] = {
    "holland": "netherlands",
    "the netherlands": "netherlands",
    "usa": "united states",
    "united states of america": "united states",
    "south korea": "korea republic",
    "korea": "korea republic",
    "republic of korea": "korea republic",
    "ir iran": "iran",
    "cote d'ivoire": "ivory coast",
    "cote divoire": "ivory coast",
    "trinidad & tobago": "trinidad and tobago",
    "trinidad": "trinidad and tobago",
    "dr congo": "congo dr",
    "d r congo": "congo dr",  # "D.R. Congo" / "D.R.Congo" after dot→space normalization
    "democratic republic of congo": "congo dr",
    "democratic republic of the congo": "congo dr",  # official UN name variant
    "dem. rep. congo": "congo dr",
    "dem rep congo": "congo dr",  # "Dem. Rep. Congo" after dot→space normalization
    # Czech Republic: r/soccer and ESPN use "Czech Republic" but football-data uses "Czechia"
    "czech republic": "czechia",
    "czech rep": "czechia",   # covers "Czech Rep" and "Czech Rep." (dot stripped before lookup)
}


def _strip_accents(text: str) -> str:
    """Remove diacritics/accents from text."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_team(name: str) -> str:
    """Lowercase, strip accents, strip periods, apply WC alias map."""
    key = _strip_accents(name.strip()).lower()
    key = key.replace(".", " ")
    key = re.sub(r"\s+", " ", key).strip()
    return WC_TEAM_ALIASES.get(key, key)


def _teams_match(thread_name: str, fixture_name: str, tla: str = "") -> bool:
    """Return True if a Reddit thread team name matches a fixture team."""
    nt = _normalize_team(thread_name)
    nf = _normalize_team(fixture_name)
    ntla = _normalize_team(tla)

    if nt == nf or (ntla and nt == ntla):
        return True
    if nt in nf or nf in nt:
        return True
    if SequenceMatcher(None, nt, nf).ratio() >= 0.80:
        return True
    return False


# ── thread title helpers ──────────────────────────────────────────────────────

_THREAD_TEAMS_RE = re.compile(
    r"match\s+thread\s*:?\s+(.+?)\s+vs\.?\s+(.+?)(?:\s*\||\s*$)",
    re.IGNORECASE,
)


def _is_match_thread(title: str) -> bool:
    """Return True for live Match Threads (excludes Pre/Post Match Thread)."""
    norm = _strip_accents(title.strip()).lower()
    # Exclude pre and post variants first
    if re.match(r"(pre|post)[\s-]*match\s+thread", norm):
        return False
    return bool(re.match(r"match\s+thread", norm))


def _parse_thread_teams(title: str) -> tuple[str, str]:
    """Extract '(home, away)' from 'Match Thread: Home vs Away | Competition'."""
    m = _THREAD_TEAMS_RE.search(title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _find_matching_fixture(
    thread_home: str,
    thread_away: str,
    live_matches: list[Match],
) -> Match | None:
    """Return the first live fixture whose teams fuzzy-match the thread teams."""
    for match in live_matches:
        if _teams_match(thread_home, match.home_name, match.home_tla) and _teams_match(
            thread_away, match.away_name, match.away_tla
        ):
            return match
        # Also check reversed (thread title might have away team first)
        if _teams_match(thread_home, match.away_name, match.away_tla) and _teams_match(
            thread_away, match.home_name, match.home_tla
        ):
            return match
    return None


# ── HTML parsing helpers ──────────────────────────────────────────────────────

_POST_DATA_RE = re.compile(
    r'data-fullname="(?P<fullname>t3_[^"]+)".*?'
    r'data-timestamp="(?P<timestamp>\d+)".*?'
    r'data-permalink="(?P<permalink>[^"]*)"',
    re.DOTALL,
)
_TITLE_RE = re.compile(r'<a\s+class="[^"]*title[^"]*"[^>]*>(?P<title>[^<]+)</a>')

_SELFTEXT_DATA_RE = re.compile(r'data-selftext="(.*?)"(?=\s)', re.DOTALL)

_ESPN_GAME_ID_RE = re.compile(r"gameId=(\d+)")

# Search-result listings use a different structure: the link has class="search-title"
# and the full old.reddit.com URL in href.
_SEARCH_RESULT_LINK_RE = re.compile(
    r'href="https://old\.reddit\.com(/r/[^"]+)"[^>]+class="search-title[^"]*"[^>]*>([^<]+)</a>',
    re.DOTALL,
)


def _html_to_goaltext(html: str) -> str:
    """Convert rendered post-body HTML to pseudo-markdown for parse_goal_events.

    Match-thread goal lines look like:
      <p><strong>7&#39;</strong> ⚽ <strong>Goal! Sweden 1, Tunisia 0. Scorer (Team)...</strong></p>

    After conversion this becomes:
      **7'** ⚽ **Goal! Sweden 1, Tunisia 0. Scorer (Team)...**

    which parse_goal_events already handles (it strips ** before matching).
    """
    # Bold tags → ** markdown markers
    text = re.sub(r"</?(?:strong|b)(?:\s[^>]*)?>", "**", html, flags=re.IGNORECASE)
    # Block-level closing tags and <br> → newlines so each event is its own line
    text = re.sub(r"</(?:p|tr|li)>|<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities: &#39; → ', &amp; → &, etc.
    text = unescape(text)
    # Collapse runs of 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _parse_html_posts(html: str) -> list[dict]:
    """Parse old.reddit.com thread listing HTML into a list of post dicts."""
    posts: list[dict] = []
    blocks = re.split(r'(?=data-fullname="t3_)', html)
    for block in blocks:
        m = _POST_DATA_RE.search(block)
        if not m:
            continue
        tm = _TITLE_RE.search(block)
        title = unescape(tm.group("title").strip()) if tm else ""
        posts.append(
            {
                "id": m.group("fullname").replace("t3_", ""),
                "created_utc": int(m.group("timestamp")) / 1000,
                "permalink": unescape(m.group("permalink")),
                "title": title,
            }
        )
    return posts


# ── scanner ───────────────────────────────────────────────────────────────────


class RedditMatchScanner:
    """Polls Reddit r/soccer Match Thread posts and parses goal events.

    A ``requests.Session`` can be injected for testing (pass ``session=``).
    The session is set up with browser headers + over18 cookie so old.reddit.com
    serves HTML and JSON without 403s.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._ua = user_agent or _DEFAULT_UA
        if session is not None:
            self._session = session
        else:
            self._session = self._make_session()

        # In-memory TTL caches — allow all consumers (goal poller, /endirecto, …)
        # to share recent fetches on the same scanner instance.
        self._match_threads_cache: tuple[float, list[ThreadInfo]] | None = None
        self._thread_body_cache: dict[str, tuple[float, str]] = {}

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        headers = {**_BROWSER_HEADERS, "User-Agent": self._ua}
        s.headers.update(headers)
        return s

    # ── thread discovery ──────────────────────────────────────────────────────

    def _fetch_json_threads(self) -> list[ThreadInfo] | None:
        """Fetch match threads via Reddit JSON search.  Returns None on 403."""
        try:
            resp = self._session.get(_REDDIT_SEARCH_JSON, timeout=15)
            if resp.status_code == 403:
                log.info("Reddit search JSON returned 403; will fall back to HTML")
                return None
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            threads = []
            for child in children:
                d = child.get("data", {})
                threads.append(
                    ThreadInfo(
                        post_id=d.get("id", ""),
                        title=d.get("title", ""),
                        permalink=d.get("permalink", ""),
                        created_utc=float(d.get("created_utc", 0)),
                    )
                )
            return threads
        except requests.HTTPError:
            return None
        except Exception as exc:
            log.warning("Failed to fetch Reddit search JSON: %s", exc)
            return None

    def _fetch_html_threads(self) -> list[ThreadInfo]:
        """Fallback: scrape r/soccer/new HTML for match thread posts."""
        resp = self._session.get(_REDDIT_NEW_HTML, timeout=15)
        resp.raise_for_status()
        posts = _parse_html_posts(resp.text)
        return [
            ThreadInfo(
                post_id=p["id"],
                title=p["title"],
                permalink=p["permalink"],
                created_utc=p["created_utc"],
            )
            for p in posts
        ]

    def get_match_threads(self) -> list[ThreadInfo]:
        """Return all live (non-Pre/Post) Match Thread posts from r/soccer.

        Results are cached for _MATCH_THREADS_TTL seconds.  On any fetch error
        (including HTTP 429) a stale cached value is returned if one exists;
        otherwise [] is returned.  This method never raises.
        """
        now = time.monotonic()
        if self._match_threads_cache is not None:
            ts, cached = self._match_threads_cache
            if now - ts < _MATCH_THREADS_TTL:
                return cached

        try:
            threads = self._fetch_json_threads()
            if threads is None:
                threads = self._fetch_html_threads()
            result = [t for t in threads if _is_match_thread(t.title)]
            self._match_threads_cache = (now, result)
            return result
        except Exception as exc:
            log.warning("get_match_threads failed: %s", exc)
            if self._match_threads_cache is not None:
                _, stale = self._match_threads_cache
                log.warning("get_match_threads: returning stale cached result")
                return stale
            return []

    def find_thread_permalink(self, home_name: str, away_name: str) -> str | None:
        """Return a live Match Thread permalink from the cached /new/ listing.

        Uses the shared, cached get_match_threads() result so it never hits
        the 429-prone search endpoint.  Both team orderings in the thread title
        are accepted.  Returns None if no matching thread is found.
        """
        threads = self.get_match_threads()
        for thread in threads:
            thread_home, thread_away = _parse_thread_teams(thread.title)
            if not thread_home or not thread_away:
                continue
            if (
                _teams_match(thread_home, home_name) and _teams_match(thread_away, away_name)
            ) or (
                _teams_match(thread_home, away_name) and _teams_match(thread_away, home_name)
            ):
                return thread.permalink
        return None

    def find_match_thread(self, home_name: str, away_name: str) -> str | None:
        """Find the r/soccer Match Thread permalink for a given fixture.

        Searches via old.reddit.com HTML search (JSON 403s in datacenter envs).
        Works for finished matches, not only live ones.
        Returns the first matching post's permalink, or None if not found.
        """
        query = f"match thread {home_name} {away_name}"
        url = (
            "https://old.reddit.com/r/soccer/search"
            f"?q={urllib.parse.quote(query)}&restrict_sr=on&sort=new&include_over_18=on&t=week"
        )
        try:
            resp = self._session.get(url, timeout=5)
            resp.raise_for_status()
            # Search results use class="search-title" links, not the /new/ listing format.
            for m in _SEARCH_RESULT_LINK_RE.finditer(resp.text):
                permalink = unescape(m.group(1))
                title = unescape(m.group(2).strip())
                if not _is_match_thread(title):
                    continue
                thread_home, thread_away = _parse_thread_teams(title)
                if not thread_home or not thread_away:
                    continue
                # Accept either team order in the title
                if (
                    _teams_match(thread_home, home_name)
                    and _teams_match(thread_away, away_name)
                ) or (
                    _teams_match(thread_home, away_name)
                    and _teams_match(thread_away, home_name)
                ):
                    return permalink
            return None
        except Exception as exc:
            log.warning(
                "find_match_thread(%s vs %s) failed: %s", home_name, away_name, exc
            )
            return None

    # ── thread body ───────────────────────────────────────────────────────────

    def _fetch_thread_body_json(self, permalink: str) -> str | None:
        """Return raw markdown selftext from the thread JSON.  None on 403."""
        url = f"{_REDDIT_OLD_BASE}{permalink}.json?raw_json=1&limit=1"
        try:
            resp = self._session.get(url, timeout=15)
            if resp.status_code == 403:
                log.info("Thread body JSON 403 for %s; will fall back to HTML", permalink)
                return None
            resp.raise_for_status()
            return resp.json()[0]["data"]["children"][0]["data"]["selftext"]
        except requests.HTTPError:
            return None
        except Exception as exc:
            log.warning("Failed to fetch thread body JSON for %s: %s", permalink, exc)
            return None

    def _fetch_thread_body_html(self, permalink: str) -> str:
        """Fallback: extract selftext from old.reddit.com thread page HTML.

        The match-thread post body is rendered HTML (no data-selftext attribute).
        Goals appear as::

            <p><strong>7&#39;</strong> ⚽ <strong>Goal! Sweden 1, Tunisia 0. ...</strong></p>

        We cut before ``<div class="commentarea">`` to exclude comment-section
        Goal! lines, then convert bold/paragraph tags to pseudo-markdown so that
        ``parse_goal_events`` can process the result normally.
        """
        url = f"{_REDDIT_OLD_BASE}{permalink}"
        resp = self._session.get(url, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # Try data-selftext attribute (present on some legacy thread types)
        m = _SELFTEXT_DATA_RE.search(html)
        if m:
            return unescape(m.group(1))

        # Cut before the comment section — goals in comments must not be parsed
        commentarea_idx = html.find('<div class="commentarea"')
        if commentarea_idx != -1:
            html = html[:commentarea_idx]

        return _html_to_goaltext(html)

    def get_thread_body(self, permalink: str) -> str:
        """Return the selftext for a thread (JSON preferred, HTML fallback).

        Results are cached per permalink for _THREAD_BODY_TTL seconds.  On any
        fetch error a stale cached value is returned if one exists; otherwise ""
        is returned.  This method never raises.
        """
        now = time.monotonic()
        if permalink in self._thread_body_cache:
            ts, cached = self._thread_body_cache[permalink]
            if now - ts < _THREAD_BODY_TTL:
                return cached

        try:
            body = self._fetch_thread_body_json(permalink)
            if body is None:
                body = self._fetch_thread_body_html(permalink)
            self._thread_body_cache[permalink] = (now, body)
            self._evict_thread_body_cache(now)
            return body
        except Exception as exc:
            log.warning("get_thread_body(%s) failed: %s", permalink, exc)
            if permalink in self._thread_body_cache:
                _, stale = self._thread_body_cache[permalink]
                log.warning("get_thread_body: returning stale cached result for %s", permalink)
                return stale
            return ""

    def _evict_thread_body_cache(self, now: float) -> None:
        """Bound the thread-body cache: once it exceeds _THREAD_BODY_CACHE_MAX
        entries, drop every entry older than
        ``_THREAD_BODY_CACHE_TTL_FACTOR × _THREAD_BODY_TTL`` seconds.

        Finished-match permalinks are otherwise never revisited, so their cache
        entries would live forever without this sweep.
        """
        if len(self._thread_body_cache) <= _THREAD_BODY_CACHE_MAX:
            return
        max_age = _THREAD_BODY_TTL * _THREAD_BODY_CACHE_TTL_FACTOR
        stale = [
            key
            for key, (ts, _body) in self._thread_body_cache.items()
            if now - ts > max_age
        ]
        for key in stale:
            self._thread_body_cache.pop(key, None)
        if stale:
            log.debug(
                "get_thread_body: evicted %d stale cache entries (size now %d)",
                len(stale), len(self._thread_body_cache),
            )

    def get_espn_game_id(self, home: str, away: str) -> str | None:
        """Find the ESPN game ID embedded in the r/soccer match thread.

        Searches for the match thread (works for finished matches too), fetches
        the full thread HTML, and extracts the first ``gameId=`` query parameter
        (e.g. from the "MATCH EVENTS | via ESPN" header link).

        Returns the game ID string (e.g. "401866598") or None on any failure.
        """
        try:
            permalink = self.find_match_thread(home, away)
            if permalink is None:
                log.warning("get_espn_game_id: no match thread found for %s vs %s", home, away)
                return None
            url = f"{_REDDIT_OLD_BASE}{permalink}"
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            m = _ESPN_GAME_ID_RE.search(resp.text)
            if m:
                return m.group(1)
            log.warning("get_espn_game_id: no gameId found in thread HTML for %s vs %s", home, away)
            return None
        except Exception as exc:
            log.warning("get_espn_game_id(%s vs %s) failed: %s", home, away, exc)
            return None

    # ── main scan ─────────────────────────────────────────────────────────────

    def scan_live_matches(
        self,
        live_matches: list[Match],
        max_threads: int = _MAX_THREADS_PER_TICK,
    ) -> list[MatchThreadResult]:
        """Return parsed goal events for match threads matching live fixtures.

        Only threads whose teams fuzzy-match a football-data live fixture are
        processed.  At most *max_threads* thread bodies are fetched per call
        (politeness cap).  A 1-second courtesy delay is inserted between
        thread-body fetches.
        """
        if not live_matches:
            return []

        try:
            all_threads = self.get_match_threads()
        except Exception as exc:
            log.error("Failed to fetch Reddit match threads: %s", exc)
            return []

        results: list[MatchThreadResult] = []
        processed = 0

        for thread in all_threads:
            if processed >= max_threads:
                break

            thread_home, thread_away = _parse_thread_teams(thread.title)
            if not thread_home or not thread_away:
                log.debug("Could not parse teams from thread title: %s", thread.title)
                continue

            fixture = _find_matching_fixture(thread_home, thread_away, live_matches)
            if fixture is None:
                log.debug(
                    "No live fixture matched for thread '%s'", thread.title[:60]
                )
                continue

            # Courtesy delay between body fetches
            if processed > 0:
                time.sleep(_FETCH_DELAY_SECONDS)

            try:
                selftext = self.get_thread_body(thread.permalink)
            except Exception as exc:
                log.warning(
                    "Failed to fetch body for thread %s: %s", thread.post_id, exc
                )
                processed += 1
                continue

            events = parse_goal_events(selftext, post_id=thread.post_id)
            results.append(
                MatchThreadResult(
                    thread=thread,
                    events=events,
                    home_tla=fixture.home_tla,
                    away_tla=fixture.away_tla,
                )
            )
            processed += 1
            log.info(
                "Thread %s (%s vs %s): %d goal events parsed",
                thread.post_id,
                thread_home,
                thread_away,
                len(events),
            )

        return results
