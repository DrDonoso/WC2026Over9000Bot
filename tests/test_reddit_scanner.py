"""Tests for reddit.scanner — thread discovery, team matching, HTML fallback."""

from __future__ import annotations

import json

import pytest
import requests

from worldcup_bot.api.models import Match
from worldcup_bot.reddit.parser import parse_goal_events
from worldcup_bot.reddit.scanner import (
    RedditMatchScanner,
    _find_matching_fixture,
    _html_to_goaltext,
    _is_match_thread,
    _normalize_team,
    _parse_thread_teams,
    _teams_match,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _live_match(home_name: str, away_name: str, home_tla: str = "HOM", away_tla: str = "AWY") -> Match:
    return Match(
        id=1,
        utc_date="2026-06-16T20:00:00Z",
        status="IN_PLAY",
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=0,
        away_score=0,
        winner=None,
    )


class FakeResponse:
    """Minimal requests.Response substitute for tests."""

    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body

    @property
    def text(self) -> str:
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Fake requests.Session that serves canned FakeResponse objects in order."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._queue = list(responses)
        self.headers = {}

    def headers_update(self, h: dict) -> None:
        self.headers.update(h)

    def get(self, url: str, **kwargs) -> FakeResponse:
        if not self._queue:
            raise RuntimeError(f"FakeSession: no more canned responses for GET {url}")
        return self._queue.pop(0)


# ── canned Reddit JSON payloads ───────────────────────────────────────────────

_SEARCH_JSON_ONE_MATCH_THREAD = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "post1",
                    "title": "Match Thread: Sweden vs Tunisia | FIFA World Cup",
                    "permalink": "/r/soccer/comments/post1/match_thread_sweden_vs_tunisia/",
                    "created_utc": 1718560000.0,
                }
            },
            {
                "data": {
                    "id": "post2",
                    "title": "Post Match Thread: France vs Germany | UEFA Euro",
                    "permalink": "/r/soccer/comments/post2/post_match/",
                    "created_utc": 1718559000.0,
                }
            },
            {
                "data": {
                    "id": "post3",
                    "title": "Pre Match Thread: Brazil vs Argentina | WC 2026",
                    "permalink": "/r/soccer/comments/post3/pre_match/",
                    "created_utc": 1718558000.0,
                }
            },
        ]
    }
}

_SEARCH_JSON_EMPTY = {"data": {"children": []}}

_THREAD_BODY_JSON = [
    {
        "data": {
            "children": [
                {
                    "data": {
                        "selftext": (
                            "**MATCH EVENTS** | via ESPN\n\n"
                            "**7'** \u26bd **Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) header...**\n"
                            "**30'** \u26bd **Goal! Sweden 2, Tunisia 0. Alexander Isak (Sweden) ...**\n"
                        )
                    }
                }
            ]
        }
    },
    {},
]

# Minimal old.reddit HTML with two posts
_HTML_LISTING = """
<div class="thing id-t3_htmlpost1" data-fullname="t3_htmlpost1"
     data-timestamp="1718560000000"
     data-permalink="/r/soccer/comments/htmlpost1/match_thread_argentina_vs_usa/">
  <a class="title may-blank" href="/r/soccer/comments/htmlpost1/">Match Thread: Argentina vs United States | WC 2026</a>
</div>
<div class="thing id-t3_htmlpost2" data-fullname="t3_htmlpost2"
     data-timestamp="1718559000000"
     data-permalink="/r/soccer/comments/htmlpost2/post_match_thread/">
  <a class="title may-blank" href="/r/soccer/comments/htmlpost2/">Post Match Thread: Italy vs Spain</a>
</div>
"""


# ══════════════════════════════════════════════════════════════════════════════
# _is_match_thread
# ══════════════════════════════════════════════════════════════════════════════


class TestIsMatchThread:
    def test_match_thread_accepted(self):
        assert _is_match_thread("Match Thread: Sweden vs Tunisia | FIFA World Cup")

    def test_match_thread_no_colon(self):
        assert _is_match_thread("Match Thread Sweden vs Tunisia | FIFA World Cup")

    def test_match_thread_lowercase(self):
        assert _is_match_thread("match thread: Brazil vs Argentina | WC 2026")

    def test_post_match_thread_excluded(self):
        assert not _is_match_thread("Post Match Thread: France vs Germany")

    def test_pre_match_thread_excluded(self):
        assert not _is_match_thread("Pre Match Thread: Spain vs Italy")

    def test_pre_match_hyphen_excluded(self):
        assert not _is_match_thread("Pre-Match Thread: Belgium vs Croatia")

    def test_post_match_hyphen_excluded(self):
        assert not _is_match_thread("Post-Match Thread: Netherlands vs Senegal")

    def test_unrelated_title_excluded(self):
        assert not _is_match_thread("[Özil] I scored a hat-trick today")


# ══════════════════════════════════════════════════════════════════════════════
# _parse_thread_teams
# ══════════════════════════════════════════════════════════════════════════════


class TestParseThreadTeams:
    def test_standard_format(self):
        home, away = _parse_thread_teams("Match Thread: Sweden vs Tunisia | FIFA World Cup")
        assert home == "Sweden"
        assert away == "Tunisia"

    def test_us_team_with_pipe(self):
        home, away = _parse_thread_teams("Match Thread: United States vs Iran | WC 2026")
        assert home == "United States"
        assert away == "Iran"

    def test_no_pipe(self):
        home, away = _parse_thread_teams("Match Thread: Brazil vs Argentina")
        assert home == "Brazil"
        assert away == "Argentina"

    def test_returns_empty_on_no_match(self):
        home, away = _parse_thread_teams("Post Match Thread: France 3-1 Germany")
        assert home == "" and away == ""


# ══════════════════════════════════════════════════════════════════════════════
# _teams_match / _find_matching_fixture
# ══════════════════════════════════════════════════════════════════════════════


class TestTeamMatching:
    def test_exact_name_match(self):
        assert _teams_match("Sweden", "Sweden", "SWE")

    def test_tla_match(self):
        assert _teams_match("SWE", "Sweden", "SWE")

    def test_fuzzy_match(self):
        assert _teams_match("United States", "United States of America", "USA")

    def test_alias_holland_netherlands(self):
        assert _teams_match("Holland", "Netherlands", "NED")

    def test_no_match(self):
        assert not _teams_match("Brazil", "Argentina", "ARG")

    def test_find_matching_fixture_home_away(self):
        matches = [_live_match("Sweden", "Tunisia", "SWE", "TUN")]
        result = _find_matching_fixture("Sweden", "Tunisia", matches)
        assert result is not None
        assert result.home_tla == "SWE"

    def test_find_matching_fixture_reversed_title(self):
        # Thread says "Tunisia vs Sweden" but fixture has home=Sweden, away=Tunisia
        matches = [_live_match("Sweden", "Tunisia", "SWE", "TUN")]
        result = _find_matching_fixture("Tunisia", "Sweden", matches)
        assert result is not None

    def test_find_matching_fixture_no_match(self):
        matches = [_live_match("Brazil", "Argentina", "BRA", "ARG")]
        result = _find_matching_fixture("Sweden", "Tunisia", matches)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# _normalize_team — dotted name normalization (Bug fix: D.R. Congo)
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeTeam:
    def test_dr_congo_with_dots_and_space(self):
        assert _normalize_team("D.R. Congo") == "congo dr"

    def test_dr_congo_dots_no_space(self):
        assert _normalize_team("D.R.Congo") == "congo dr"

    def test_dr_congo_alias_no_dots(self):
        assert _normalize_team("DR Congo") == "congo dr"

    def test_democratic_republic_of_congo(self):
        assert _normalize_team("Democratic Republic of Congo") == "congo dr"

    def test_normal_name_unchanged(self):
        assert _normalize_team("Portugal") == "portugal"

    def test_teams_match_dr_congo_dotted(self):
        assert _teams_match("D.R. Congo", "Congo DR") is True

    def test_teams_match_dr_congo_dots_no_space(self):
        assert _teams_match("D.R.Congo", "Congo DR") is True




class TestScannerJsonPath:
    def test_discover_threads_filters_pre_post(self):
        """JSON path: only the live Match Thread is kept."""
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD),
                FakeResponse(200, _THREAD_BODY_JSON),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        live = [_live_match("Sweden", "Tunisia", "SWE", "TUN")]
        results = scanner.scan_live_matches(live)
        assert len(results) == 1
        assert results[0].thread.post_id == "post1"

    def test_goal_events_parsed_from_body(self):
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD),
                FakeResponse(200, _THREAD_BODY_JSON),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        live = [_live_match("Sweden", "Tunisia", "SWE", "TUN")]
        results = scanner.scan_live_matches(live)
        assert len(results[0].events) == 2

    def test_home_away_tla_populated_from_fixture(self):
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD),
                FakeResponse(200, _THREAD_BODY_JSON),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        live = [_live_match("Sweden", "Tunisia", "SWE", "TUN")]
        results = scanner.scan_live_matches(live)
        assert results[0].home_tla == "SWE"
        assert results[0].away_tla == "TUN"

    def test_no_live_matches_returns_empty(self):
        session = FakeSession([])
        scanner = RedditMatchScanner(session=session)
        results = scanner.scan_live_matches([])
        assert results == []

    def test_unmatched_thread_skipped(self):
        """Thread for Sweden vs Tunisia but live fixture is Brazil vs Argentina."""
        session = FakeSession([FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD)])
        scanner = RedditMatchScanner(session=session)
        live = [_live_match("Brazil", "Argentina", "BRA", "ARG")]
        results = scanner.scan_live_matches(live)
        assert results == []


# ══════════════════════════════════════════════════════════════════════════════
# RedditMatchScanner — 403 JSON → HTML fallback path
# ══════════════════════════════════════════════════════════════════════════════


class TestScannerHtmlFallback:
    def test_json_403_falls_back_to_html_for_discovery(self):
        """If search JSON returns 403, scanner falls back to HTML listing."""
        # Search returns 403; HTML listing has a valid match thread
        html_selftext = (
            "**MATCH EVENTS** | via ESPN\n\n"
            "**10'** \u26bd **Goal! Argentina 1, United States 0. Messi (Argentina) ...**\n"
        )
        thread_body_json = [
            {"data": {"children": [{"data": {"selftext": html_selftext}}]}},
            {},
        ]
        session = FakeSession(
            [
                FakeResponse(403, "Forbidden"),           # search JSON → 403
                FakeResponse(200, _HTML_LISTING),          # HTML listing fallback
                FakeResponse(200, thread_body_json),       # thread body JSON
            ]
        )
        scanner = RedditMatchScanner(session=session)
        live = [_live_match("Argentina", "United States", "ARG", "USA")]
        results = scanner.scan_live_matches(live)
        assert len(results) == 1
        assert results[0].thread.post_id == "htmlpost1"
        assert len(results[0].events) == 1

    def test_html_post_match_thread_excluded(self):
        """Post Match Thread in HTML listing is filtered out."""
        session = FakeSession(
            [
                FakeResponse(403, "Forbidden"),
                FakeResponse(200, _HTML_LISTING),
                # No further fetches expected — Argentina thread matches, Italy/Spain post-match excluded
            ]
        )
        scanner = RedditMatchScanner(session=session)
        # No live fixture for Argentina/USA → no results either, but Post Match Thread still excluded
        live = [_live_match("France", "Germany", "FRA", "GER")]
        results = scanner.scan_live_matches(live)
        assert results == []


# ── Trimmed match-thread HTML fixture ─────────────────────────────────────────
# Mimics old.reddit.com rendered HTML: no data-selftext; goals are <p><strong>…
# Contains a commentarea section with a fake "Goal!" that must be excluded.

_THREAD_HTML_PAGE = """\
<html><body>
<div id="siteTable">
  <div class="thing" data-fullname="t3_1u62p01">
    <div class="entry unvoted">
      <div class="usertext-body">
        <div class="md">
          <h3>MATCH EVENTS | via ESPN</h3>
          <p><strong>7&#39;</strong> \u26bd <strong>Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) right footed shot from outside the box to the top right corner.</strong></p>
          <p><strong>30&#39;</strong> \u26bd <strong>Goal! Sweden 2, Tunisia 0. Alexander Isak (Sweden) right footed shot from close range.</strong></p>
          <p><strong>43&#39;</strong> \u26bd <strong>Goal! Sweden 2, Tunisia 1. Omar Rekik (Tunisia) header from the centre of the box.</strong></p>
          <p><strong>59&#39;</strong> \u26bd <strong>Goal! Sweden 3, Tunisia 1. Viktor Gy\u00f6keres (Sweden) right footed shot from outside the box.</strong></p>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="commentarea">
  <div class="thing" data-fullname="t1_comment1">
    <div class="entry">
      <div class="md">
        <p><strong>99&#39;</strong> \u26bd <strong>Goal! Sweden 99, Tunisia 99. FakeScorer (Sweden) amazing comment goal!</strong></p>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


# ══════════════════════════════════════════════════════════════════════════════
# RedditMatchScanner — thread body HTML fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestScannerThreadBodyHtmlFallback:
    """Thread body HTML fallback: when .json endpoint returns 403, parse rendered page."""

    def test_html_fallback_extracts_goals_from_rendered_html(self):
        """JSON 403 → HTML page → 4 goal events parsed from rendered <p><strong> markup."""
        session = FakeSession(
            [
                FakeResponse(403, "Forbidden"),          # .json endpoint → 403
                FakeResponse(200, _THREAD_HTML_PAGE),    # HTML page → 200
            ]
        )
        scanner = RedditMatchScanner(session=session)
        body = scanner.get_thread_body(
            "/r/soccer/comments/1u62p01/match_thread_sweden_vs_tunisia/"
        )
        goals = parse_goal_events(body, post_id="1u62p01")
        assert len(goals) == 4
        scorers = [g.scorer for g in goals]
        assert "Yasin Ayari" in scorers
        assert "Alexander Isak" in scorers
        assert "Omar Rekik" in scorers
        assert "Viktor Gy\u00f6keres" in scorers

    def test_html_fallback_excludes_comment_goals(self):
        """Goals in the commentarea section are NOT included in the parsed result."""
        session = FakeSession(
            [
                FakeResponse(403, "Forbidden"),
                FakeResponse(200, _THREAD_HTML_PAGE),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        body = scanner.get_thread_body(
            "/r/soccer/comments/1u62p01/match_thread_sweden_vs_tunisia/"
        )
        goals = parse_goal_events(body, post_id="1u62p01")
        scorers = [g.scorer for g in goals]
        assert "FakeScorer" not in scorers
        assert not any(g.home_score == 99 for g in goals)

    def test_html_fallback_minute_values_correct(self):
        """Parsed goals carry the correct minute values from the rendered HTML."""
        session = FakeSession(
            [
                FakeResponse(403, "Forbidden"),
                FakeResponse(200, _THREAD_HTML_PAGE),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        body = scanner.get_thread_body(
            "/r/soccer/comments/1u62p01/match_thread_sweden_vs_tunisia/"
        )
        goals = parse_goal_events(body, post_id="1u62p01")
        minutes = sorted(int(g.minute_sort) for g in goals)
        assert minutes == [7, 30, 43, 59]


# ══════════════════════════════════════════════════════════════════════════════
# _html_to_goaltext unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestHtmlToGoaltext:
    def test_converts_strong_to_bold_markers(self):
        html = (
            "<p><strong>7&#39;</strong> \u26bd "
            "<strong>Goal! Sweden 1, Tunisia 0. Scorer (Sweden) right shot.</strong></p>"
        )
        result = _html_to_goaltext(html)
        assert "**7'**" in result
        assert "**Goal! Sweden 1, Tunisia 0. Scorer (Sweden) right shot.**" in result

    def test_paragraph_becomes_newline(self):
        html = "<p>Line one.</p><p>Line two.</p>"
        result = _html_to_goaltext(html)
        lines = [ln for ln in result.splitlines() if ln.strip()]
        assert len(lines) == 2

    def test_html_entity_unescaped(self):
        html = "<p>It&#39;s &amp; fine &lt;here&gt;</p>"
        result = _html_to_goaltext(html)
        assert "It's & fine <here>" in result

    def test_br_tag_becomes_newline(self):
        html = "Line one.<br/>Line two.<br>Line three."
        result = _html_to_goaltext(html)
        lines = [ln for ln in result.splitlines() if ln.strip()]
        assert len(lines) == 3


# ══════════════════════════════════════════════════════════════════════════════
# RedditMatchScanner.find_match_thread
# ══════════════════════════════════════════════════════════════════════════════

# Canned search-results HTML with:
#   abc123 — live Match Thread: Sweden vs Tunisia
#   def456 — Pre Match Thread: Sweden vs Tunisia  (must be excluded)
#   ghi789 — Post Match Thread: Sweden vs Tunisia (must be excluded)
#   jkl012 — live Match Thread: Germany vs Spain  (different fixture)
#
# Uses the actual old.reddit.com search-result HTML structure:
#   <a href="https://old.reddit.com/r/soccer/comments/..." class="search-title ...">Title</a>

_SEARCH_LISTING_HTML = """\
<div data-fullname="t3_abc123">
  <a href="https://old.reddit.com/r/soccer/comments/abc123/match_thread_sweden_vs_tunisia_wc2026/" class="search-title may-blank" >Match Thread: Sweden vs Tunisia | FIFA World Cup 2026</a>
</div>
<div data-fullname="t3_def456">
  <a href="https://old.reddit.com/r/soccer/comments/def456/pre_match_thread_sweden_vs_tunisia/" class="search-title may-blank" >Pre Match Thread: Sweden vs Tunisia | FIFA World Cup 2026</a>
</div>
<div data-fullname="t3_ghi789">
  <a href="https://old.reddit.com/r/soccer/comments/ghi789/post_match_thread_sweden_vs_tunisia/" class="search-title may-blank" >Post Match Thread: Sweden vs Tunisia | FIFA World Cup 2026</a>
</div>
<div data-fullname="t3_jkl012">
  <a href="https://old.reddit.com/r/soccer/comments/jkl012/match_thread_germany_vs_spain/" class="search-title may-blank" >Match Thread: Germany vs Spain | FIFA World Cup 2026</a>
</div>
"""


class TestFindMatchThread:
    def test_returns_permalink_for_matching_thread(self):
        """Returns the first live Match Thread permalink for the given fixture."""
        session = FakeSession([FakeResponse(200, _SEARCH_LISTING_HTML)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_match_thread("Sweden", "Tunisia")
        assert result == "/r/soccer/comments/abc123/match_thread_sweden_vs_tunisia_wc2026/"

    def test_excludes_pre_match_thread(self):
        """Pre Match Thread is skipped even if team names match."""
        session = FakeSession([FakeResponse(200, _SEARCH_LISTING_HTML)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_match_thread("Sweden", "Tunisia")
        assert result is not None
        assert "pre_match" not in result

    def test_excludes_post_match_thread(self):
        """Post Match Thread is skipped even if team names match."""
        session = FakeSession([FakeResponse(200, _SEARCH_LISTING_HTML)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_match_thread("Sweden", "Tunisia")
        assert result is not None
        assert "post_match" not in result

    def test_returns_none_when_no_fixture_match(self):
        """Returns None when no thread title matches the given fixture."""
        session = FakeSession([FakeResponse(200, _SEARCH_LISTING_HTML)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_match_thread("Brazil", "Argentina")
        assert result is None

    def test_returns_none_on_http_error(self):
        """Returns None (no exception) when the HTTP request fails."""
        session = FakeSession([FakeResponse(404, "Not Found")])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_match_thread("Sweden", "Tunisia")
        assert result is None

    def test_matches_reversed_team_order_in_title(self):
        """Accepts fixture home/away reversed relative to the Reddit title order."""
        session = FakeSession([FakeResponse(200, _SEARCH_LISTING_HTML)])
        scanner = RedditMatchScanner(session=session)
        # fixture has home=Tunisia, away=Sweden but title says "Sweden vs Tunisia"
        result = scanner.find_match_thread("Tunisia", "Sweden")
        assert result == "/r/soccer/comments/abc123/match_thread_sweden_vs_tunisia_wc2026/"

    def test_different_fixture_returns_different_permalink(self):
        """Germany vs Spain returns the Germany-Spain thread, not Sweden-Tunisia."""
        session = FakeSession([FakeResponse(200, _SEARCH_LISTING_HTML)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_match_thread("Germany", "Spain")
        assert result == "/r/soccer/comments/jkl012/match_thread_germany_vs_spain/"

