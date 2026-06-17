"""Goal-clip post finder for r/soccer.

Locates the r/soccer clip post matching a given goal event and returns the
external media URL.  Synchronous — call via ``asyncio.to_thread`` in handlers.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import quote_plus

from worldcup_bot.reddit.scanner import (
    RedditMatchScanner,
    _normalize_team,
    _teams_match,
)

log = logging.getLogger(__name__)

# ── goal-clip title regex ──────────────────────────────────────────────────────
# Matches: "Sweden [3] - 1 Tunisia - Viktor Gyökeres 60'"
# The scoring team has its score wrapped in [].

GOAL_TITLE_PATTERN = re.compile(
    r"^(?P<home_team>.+?)\s+"
    r"(?P<home_bracket>\[)?(?P<home_score>\d+)\]?\s*"
    r"-\s*"
    r"(?P<away_bracket>\[)?(?P<away_score>\d+)\]?\s+"
    r"(?P<away_team>.+?)\s+"
    r"(?:\[.*?\]\s*)?"
    r"-\s+"
    r"(?P<scorer>.+?)\s+"
    r"(?P<minute>\d+)['+]",
    re.IGNORECASE,
)

# ── media URL patterns ─────────────────────────────────────────────────────────

STREAMFF_RE = re.compile(
    r"https?://(?:www\.)?streamff\.(?:link|com)/\S+", re.IGNORECASE
)
VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:streamable\.com|v\.redd\.it"
    r"|streamin\.(?:me|link)|streamain\.com|dubz\.link|dropr\.co)/\S+",
    re.IGNORECASE,
)

# ── Reddit search endpoints ────────────────────────────────────────────────────

_REDDIT_SEARCH_JSON = (
    "https://old.reddit.com/r/soccer/search.json"
    "?q={query}&restrict_sr=1&sort=new&t=day&limit=100&raw_json=1"
)
_REDDIT_SEARCH_HTML = (
    "https://old.reddit.com/r/soccer/search"
    "?q={query}&restrict_sr=on&sort=new&include_over_18=on"
)
_REDDIT_NEW_HTML = "https://old.reddit.com/r/soccer/new/?limit=100"

# ── HTML listing parser (old.reddit.com /new/ and r/soccer/new) ───────────────
# These pages expose the external media URL via the data-url="..." attribute.

_CLIP_POST_DATA_RE = re.compile(
    r'data-fullname="(?P<fullname>t3_[^"]+)".*?'
    r'data-timestamp="(?P<timestamp>\d+)".*?'
    r'data-url="(?P<url>[^"]*)".*?'
    r'data-permalink="(?P<permalink>[^"]*)"',
    re.DOTALL,
)
_TITLE_RE = re.compile(r'<a\s+class="[^"]*title[^"]*"[^>]*>(?P<title>[^<]+)</a>')


def _parse_clip_posts_html(html: str) -> list[dict]:
    """Parse old.reddit.com listing HTML; return post dicts with url field."""
    posts: list[dict] = []
    blocks = re.split(r'(?=data-fullname="t3_)', html)
    for block in blocks:
        m = _CLIP_POST_DATA_RE.search(block)
        if not m:
            continue
        tm = _TITLE_RE.search(block)
        title = unescape(tm.group("title").strip()) if tm else ""
        posts.append(
            {
                "id": m.group("fullname").replace("t3_", ""),
                "title": title,
                "url": unescape(m.group("url")),
                "permalink": unescape(m.group("permalink")),
            }
        )
    return posts


# ── HTML search-results parser (old.reddit.com/r/soccer/search?q=...) ─────────
# Search results use a different HTML structure from the listing pages.
# Link posts expose the external URL in a footer anchor with class="search-link":
#   <a href="https://streamin.link/v/…" class="search-link may-blank">…</a>
# Titles are in: <a href="/r/…" class="search-title may-blank">Title</a>

_SEARCH_FULLNAME_RE = re.compile(r'data-fullname="(t3_[^"]+)"')
_SEARCH_TITLE_RE = re.compile(r'class="[^"]*search-title[^"]*"[^>]*>([^<]+)<')
_SEARCH_PERMALINK_RE = re.compile(r'href="([^"]+)"[^>]*class="[^"]*search-title')
_SEARCH_LINK_RE = re.compile(r'href="(https?://[^"]+)"\s+class="[^"]*search-link')


def _parse_search_results_html(html: str) -> list[dict]:
    """Parse old.reddit.com search-results HTML into post dicts with url field.

    Search results use a different structure from /new/ listing pages: titles are
    in ``class="search-title"`` anchors and external media URLs are in
    ``class="search-link"`` footer anchors.  Blocks without a ``search-title``
    (i.e. not in search-results format) are skipped so that this parser does not
    produce false positives when accidentally given a listing-format page.
    """
    posts: list[dict] = []
    blocks = re.split(r'(?=data-fullname="t3_)', html)
    for block in blocks:
        fm = _SEARCH_FULLNAME_RE.search(block)
        if not fm:
            continue
        tm = _SEARCH_TITLE_RE.search(block)
        if not tm:
            continue  # Not in search-results format; skip silently
        pm = _SEARCH_PERMALINK_RE.search(block)
        lm = _SEARCH_LINK_RE.search(block)
        title = unescape(tm.group(1).strip())
        permalink = unescape(pm.group(1)) if pm else ""
        url = unescape(lm.group(1)) if lm else permalink
        posts.append(
            {
                "id": fm.group(1).replace("t3_", ""),
                "title": title,
                "url": url,
                "permalink": permalink,
            }
        )
    return posts


# ── media URL extraction ───────────────────────────────────────────────────────


def _extract_media_url(post_url: str) -> str | None:
    """Return the media URL if *post_url* points at a known video host.

    Falls back to returning the URL as-is for any http(s) URL that is not a
    reddit/redd.it/imgur link and whose path does not end in a static-image
    extension.  This ensures future clip hosts work without allowlist updates.
    """
    m = STREAMFF_RE.search(post_url)
    if m:
        return m.group(0)
    m = VIDEO_URL_RE.search(post_url)
    if m:
        return m.group(0)
    # Generic fallback: any external http(s) URL that is not Reddit/imgur and
    # not a static image.  Safe because _match_post only calls this after the
    # post title has already matched the exact goal via GOAL_TITLE_PATTERN +
    # team/score/scorer-or-minute checks.
    lower = post_url.lower()
    if lower.startswith(("http://", "https://")):
        if any(d in lower for d in ("reddit.com", "redd.it", "imgur.com")):
            return None
        path = post_url.split("?", 1)[0]
        if re.search(r"\.(jpg|jpeg|png|gif|webp)$", path, re.IGNORECASE):
            return None
        return post_url
    return None


# ── scorer fuzzy match ─────────────────────────────────────────────────────────


def _scorer_matches(clip_scorer: str, target_scorer: str) -> bool:
    """Return True if clip_scorer is a plausible match for target_scorer."""
    if not clip_scorer or not target_scorer:
        return False
    cn = clip_scorer.lower().strip()
    tn = target_scorer.lower().strip()
    if cn == tn or cn in tn or tn in cn:
        return True
    # Last-name match
    clip_last = cn.split()[-1] if cn.split() else cn
    target_last = tn.split()[-1] if tn.split() else tn
    return clip_last == target_last


# ── internal fetchers ──────────────────────────────────────────────────────────


def _fetch_search_posts(scanner: RedditMatchScanner, url: str) -> list[dict] | None:
    """Fetch r/soccer search JSON. Returns None on 403 or failure (caller falls back)."""
    try:
        resp = scanner._session.get(url, timeout=15)
        if resp.status_code == 403:
            return None
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
        posts = []
        for child in children:
            d = child.get("data", {})
            post_url = d.get("url_overridden_by_dest") or d.get("url", "")
            posts.append(
                {
                    "id": d.get("id", ""),
                    "title": d.get("title", ""),
                    "url": post_url,
                    "permalink": d.get("permalink", ""),
                }
            )
        return posts
    except Exception as exc:
        log.warning("find_goal_clip: JSON search failed: %s", exc)
        return None


def _fetch_html_posts(scanner: RedditMatchScanner) -> list[dict]:
    """Fallback: scrape r/soccer/new HTML for recent posts."""
    try:
        resp = scanner._session.get(_REDDIT_NEW_HTML, timeout=15)
        resp.raise_for_status()
        return _parse_clip_posts_html(resp.text)
    except Exception as exc:
        log.warning("find_goal_clip: HTML fallback failed: %s", exc)
        return []


def _fetch_html_search_posts(
    scanner: RedditMatchScanner, home: str, away: str
) -> list[dict]:
    """Search r/soccer via HTML search endpoint (returns 200 where JSON is 403)."""
    query = quote_plus(f"{home} {away}")
    url = _REDDIT_SEARCH_HTML.format(query=query)
    try:
        resp = scanner._session.get(url, timeout=15)
        resp.raise_for_status()
        return _parse_search_results_html(resp.text)
    except Exception as exc:
        log.warning("find_goal_clip: HTML search failed: %s", exc)
        return []


# ── post title matching ────────────────────────────────────────────────────────


def _match_post(
    post: dict,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    scorer: str,
    minute: int,
) -> str | None:
    """Return media_url if *post* matches the target goal, else None."""
    title = post.get("title", "")
    m = GOAL_TITLE_PATTERN.match(title)
    if not m:
        return None

    clip_home = m.group("home_team").strip()
    clip_away = m.group("away_team").strip()
    clip_hs = int(m.group("home_score"))
    clip_as = int(m.group("away_score"))
    clip_scorer = m.group("scorer").strip()
    clip_minute = int(m.group("minute"))

    # Teams must fuzzy-match
    home_ok = _teams_match(clip_home, home_team)
    away_ok = _teams_match(clip_away, away_team)

    if home_ok and away_ok:
        target_hs, target_as = home_score, away_score
    else:
        # Try reversed (clip may list away team first)
        if _teams_match(clip_home, away_team) and _teams_match(clip_away, home_team):
            target_hs, target_as = away_score, home_score
        else:
            return None

    # Scores must match exactly
    if clip_hs != target_hs or clip_as != target_as:
        return None

    # At least one of: scorer fuzzy-match OR minute within ±2
    scorer_ok = _scorer_matches(clip_scorer, scorer)
    minute_ok = abs(clip_minute - minute) <= 2
    if not (scorer_ok or minute_ok):
        return None

    post_url = post.get("url", "")
    media_url = _extract_media_url(post_url)
    if media_url:
        log.info("find_goal_clip: matched '%s' → %s", title[:70], media_url)
        return media_url

    log.debug(
        "find_goal_clip: title matched but no extractable media URL: %s", post_url
    )
    return None


# ── public API ─────────────────────────────────────────────────────────────────


def find_goal_clip(
    scanner: RedditMatchScanner,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    scorer: str,
    minute: int,
) -> str | None:
    """Return the external media URL of the r/soccer clip post matching the goal.

    Searches r/soccer by team names (JSON search, HTML fallback), parses each
    post title with ``GOAL_TITLE_PATTERN``, and returns the first match.

    This is **synchronous** — call via ``await asyncio.to_thread(find_goal_clip, ...)``.
    Returns None if no matching post is found.
    """
    query = quote_plus(f"{home_team} {away_team}")
    search_url = _REDDIT_SEARCH_JSON.format(query=query)

    posts = _fetch_search_posts(scanner, search_url)
    if posts is None:
        log.info("find_goal_clip: JSON search 403/failed, trying HTML search")
        posts = _fetch_html_search_posts(scanner, home_team, away_team)
        if not posts:
            log.info(
                "find_goal_clip: HTML search empty/failed, falling back to /new/ listing"
            )
            posts = _fetch_html_posts(scanner)

    for post in posts:
        media_url = _match_post(
            post, home_team, away_team, home_score, away_score, scorer, minute
        )
        if media_url is not None:
            return media_url

    log.info(
        "find_goal_clip: no match for %s vs %s %d-%d %s %d'",
        home_team,
        away_team,
        home_score,
        away_score,
        scorer,
        minute,
    )
    return None
