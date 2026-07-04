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


class TestCzechiaAlias:
    def test_normalize_czech_republic_equals_czechia(self):
        assert _normalize_team("Czech Republic") == _normalize_team("Czechia")

    def test_normalize_czech_rep_dot_equals_czechia(self):
        assert _normalize_team("Czech Rep.") == _normalize_team("Czechia")

    def test_teams_match_czech_republic_vs_czechia(self):
        assert _teams_match("Czech Republic", "Czechia") is True

    def test_teams_match_czechia_vs_czech_republic(self):
        assert _teams_match("Czechia", "Czech Republic") is True

    def test_teams_match_czech_rep_dot_vs_czechia(self):
        assert _teams_match("Czech Rep.", "Czechia") is True


class TestCongoDRAlias:
    """Test Democratic Republic of Congo name variants map to 'congo dr'."""

    def test_normalize_democratic_republic_of_the_congo(self):
        """Official UN name variant (with 'the') normalizes to 'congo dr'."""
        assert _normalize_team("Democratic Republic of the Congo") == "congo dr"

    def test_normalize_dr_congo_plain(self):
        assert _normalize_team("DR Congo") == "congo dr"

    def test_normalize_dotted_dr_congo(self):
        assert _normalize_team("D.R. Congo") == "congo dr"

    def test_teams_match_democratic_republic_of_the_congo_vs_fixture(self):
        """r/soccer thread 'Democratic Republic of the Congo' matches football-data 'Congo DR'."""
        assert _teams_match("Democratic Republic of the Congo", "Congo DR") is True

    def test_teams_match_reversed(self):
        assert _teams_match("Congo DR", "Democratic Republic of the Congo") is True

    def test_find_fixture_with_the_variant(self):
        """_find_matching_fixture handles 'Democratic Republic of the Congo' in thread title."""
        matches = [_live_match("England", "Congo DR", "ENG", "COD")]
        result = _find_matching_fixture("England", "Democratic Republic of the Congo", matches)
        assert result is not None
        assert result.away_tla == "COD"




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


# ══════════════════════════════════════════════════════════════════════════════
# RedditMatchScanner.find_thread_permalink
# ══════════════════════════════════════════════════════════════════════════════

# A tiny /new/-style listing with one live Match Thread for Czechia vs South Africa.
_CZECHIA_LISTING_JSON = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "czk001",
                    "title": "Match Thread: Czechia vs South Africa | FIFA World Cup 2026",
                    "permalink": "/r/soccer/comments/czk001/match_thread_czechia_vs_south_africa/",
                    "created_utc": 1718560000.0,
                }
            },
            {
                "data": {
                    "id": "czk002",
                    "title": "Post Match Thread: Germany vs Spain | WC 2026",
                    "permalink": "/r/soccer/comments/czk002/post_match/",
                    "created_utc": 1718559000.0,
                }
            },
        ]
    }
}


class TestFindThreadPermalink:
    def test_returns_permalink_for_matching_thread(self):
        """find_thread_permalink returns the correct permalink via the /new/ listing."""
        session = FakeSession([FakeResponse(200, _CZECHIA_LISTING_JSON)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_thread_permalink("Czechia", "South Africa")
        assert result == "/r/soccer/comments/czk001/match_thread_czechia_vs_south_africa/"

    def test_reversed_team_order_still_matches(self):
        """Thread title has 'Czechia vs South Africa'; fixture home=South Africa works too."""
        session = FakeSession([FakeResponse(200, _CZECHIA_LISTING_JSON)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_thread_permalink("South Africa", "Czechia")
        assert result == "/r/soccer/comments/czk001/match_thread_czechia_vs_south_africa/"

    def test_returns_none_when_no_matching_thread(self):
        """Returns None when no thread title matches the given fixture."""
        session = FakeSession([FakeResponse(200, _CZECHIA_LISTING_JSON)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_thread_permalink("Brazil", "Argentina")
        assert result is None

    def test_post_match_thread_is_excluded(self):
        """Post Match Thread is filtered by _is_match_thread before lookup."""
        session = FakeSession([FakeResponse(200, _CZECHIA_LISTING_JSON)])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_thread_permalink("Germany", "Spain")
        assert result is None  # Post Match Thread must not match

    def test_returns_none_when_listing_empty(self):
        """Returns None gracefully when the /new/ listing has no threads."""
        session = FakeSession([FakeResponse(200, {"data": {"children": []}})])
        scanner = RedditMatchScanner(session=session)
        result = scanner.find_thread_permalink("France", "Brazil")
        assert result is None

    def test_uses_cached_threads_second_call_no_extra_fetch(self):
        """Second call within the TTL window reuses the cache — no extra HTTP request."""
        from unittest.mock import patch as _patch

        session = FakeSession([FakeResponse(200, _CZECHIA_LISTING_JSON)])
        scanner = RedditMatchScanner(session=session)

        # First call fetches and caches
        result1 = scanner.find_thread_permalink("Czechia", "South Africa")
        assert result1 is not None

        # Session is now empty; a second fetch would raise RuntimeError.
        # Second call should use the cache → must not raise.
        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 1.0  # within TTL
            result2 = scanner.find_thread_permalink("Czechia", "South Africa")

        assert result2 == result1


# ══════════════════════════════════════════════════════════════════════════════
# RedditMatchScanner — get_match_threads TTL cache
# ══════════════════════════════════════════════════════════════════════════════


class TestScannerMatchThreadsCache:
    """get_match_threads() caches results for _MATCH_THREADS_TTL seconds."""

    def _make_scanner_with_json_responses(self, *responses) -> RedditMatchScanner:
        return RedditMatchScanner(session=FakeSession(list(responses)))

    def test_second_call_within_ttl_uses_cache(self):
        """Two calls within the TTL window → underlying fetch happens only once."""
        from unittest.mock import patch as _patch

        scanner = self._make_scanner_with_json_responses(
            FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD)
        )

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            threads1 = scanner.get_match_threads()

            # Same timestamp — still within TTL
            threads2 = scanner.get_match_threads()

        # Both calls return the same list and the session has no more responses
        # (if a second fetch were attempted it would raise RuntimeError).
        assert threads1 == threads2
        assert len(threads1) == 1
        assert threads1[0].post_id == "post1"

    def test_call_after_ttl_refetches(self):
        """A call after the TTL has expired triggers a new HTTP fetch."""
        from unittest.mock import patch as _patch
        from worldcup_bot.reddit.scanner import _MATCH_THREADS_TTL

        scanner = self._make_scanner_with_json_responses(
            FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD),
            FakeResponse(200, _SEARCH_JSON_EMPTY),
        )

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            threads1 = scanner.get_match_threads()

            # Advance clock past TTL
            mock_time.monotonic.return_value = _MATCH_THREADS_TTL + 1.0
            threads2 = scanner.get_match_threads()

        assert len(threads1) == 1   # first fetch had one thread
        assert len(threads2) == 0   # second fetch returned empty

    def test_fetch_error_with_cache_returns_stale(self):
        """On fetch error, if a cached value exists, return it (does not raise)."""
        from unittest.mock import patch as _patch
        from worldcup_bot.reddit.scanner import _MATCH_THREADS_TTL

        scanner = self._make_scanner_with_json_responses(
            FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD),
            FakeResponse(429, "Too Many Requests"),  # will raise via raise_for_status
        )

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            # First call — populates cache at t=0
            mock_time.monotonic.return_value = 0.0
            threads1 = scanner.get_match_threads()
            assert len(threads1) == 1

            # Second call past TTL — 429 on JSON, 429 on HTML fallback too
            # FakeSession only had 2 responses; JSON 429 triggers HTML fallback which
            # would try another request — but we've run out. Let's mock _fetch_json_threads
            # and _fetch_html_threads directly.

        scanner2 = RedditMatchScanner(session=FakeSession([FakeResponse(200, _SEARCH_JSON_ONE_MATCH_THREAD)]))
        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            scanner2.get_match_threads()  # populate cache

            mock_time.monotonic.return_value = _MATCH_THREADS_TTL + 1.0
            # Both internal fetchers raise now
            with _patch.object(scanner2, "_fetch_json_threads", side_effect=requests.HTTPError("429")):
                with _patch.object(scanner2, "_fetch_html_threads", side_effect=requests.HTTPError("429")):
                    stale = scanner2.get_match_threads()

        assert len(stale) == 1  # stale cache returned, not []

    def test_fetch_error_with_no_cache_returns_empty(self):
        """On fetch error with no cache, returns [] gracefully (does not raise)."""
        from unittest.mock import patch as _patch

        scanner = RedditMatchScanner(session=FakeSession([]))
        with _patch.object(scanner, "_fetch_json_threads", side_effect=requests.HTTPError("429")):
            with _patch.object(scanner, "_fetch_html_threads", side_effect=requests.HTTPError("429")):
                result = scanner.get_match_threads()

        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# RedditMatchScanner — get_thread_body TTL cache
# ══════════════════════════════════════════════════════════════════════════════


class TestScannerThreadBodyCache:
    """get_thread_body() caches results per permalink for _THREAD_BODY_TTL seconds."""

    _PERMALINK = "/r/soccer/comments/test123/match_thread/"

    def test_second_call_within_ttl_uses_cache(self):
        """Two calls for the same permalink within the TTL → underlying fetch once."""
        from unittest.mock import patch as _patch

        scanner = RedditMatchScanner(session=FakeSession([FakeResponse(200, _THREAD_BODY_JSON)]))

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 500.0
            body1 = scanner.get_thread_body(self._PERMALINK)

            # Still within TTL — session is empty, a second fetch would raise
            body2 = scanner.get_thread_body(self._PERMALINK)

        assert body1 == body2
        assert "Goal! Sweden" in body1

    def test_call_after_ttl_refetches(self):
        """A call after the TTL triggers a new fetch for the same permalink."""
        from unittest.mock import patch as _patch
        from worldcup_bot.reddit.scanner import _THREAD_BODY_TTL

        body_v1 = [{"data": {"children": [{"data": {"selftext": "**7'** ⚽ **Goal! A 1-0.**"}}]}}, {}]
        body_v2 = [{"data": {"children": [{"data": {"selftext": "**7'** ⚽ **Goal! A 1-0.**\n**30'** ⚽ **Goal! A 2-0.**"}}]}}, {}]

        scanner = RedditMatchScanner(session=FakeSession([
            FakeResponse(200, body_v1),
            FakeResponse(200, body_v2),
        ]))

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            body1 = scanner.get_thread_body(self._PERMALINK)

            mock_time.monotonic.return_value = _THREAD_BODY_TTL + 1.0
            body2 = scanner.get_thread_body(self._PERMALINK)

        assert body1 != body2
        assert "Goal! A 2-0." in body2

    def test_fetch_error_with_cache_returns_stale(self):
        """On fetch error, if a cached body exists, return it (does not raise)."""
        from unittest.mock import patch as _patch
        from worldcup_bot.reddit.scanner import _THREAD_BODY_TTL

        scanner = RedditMatchScanner(session=FakeSession([FakeResponse(200, _THREAD_BODY_JSON)]))

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            body1 = scanner.get_thread_body(self._PERMALINK)

            mock_time.monotonic.return_value = _THREAD_BODY_TTL + 1.0
            with _patch.object(scanner, "_fetch_thread_body_json", side_effect=requests.HTTPError("429")):
                with _patch.object(scanner, "_fetch_thread_body_html", side_effect=requests.HTTPError("429")):
                    stale = scanner.get_thread_body(self._PERMALINK)

        assert stale == body1  # stale cache returned

    def test_fetch_error_with_no_cache_returns_empty_string(self):
        """On fetch error with no cache, returns '' gracefully (does not raise)."""
        from unittest.mock import patch as _patch

        scanner = RedditMatchScanner(session=FakeSession([]))
        with _patch.object(scanner, "_fetch_thread_body_json", side_effect=requests.HTTPError("429")):
            with _patch.object(scanner, "_fetch_thread_body_html", side_effect=requests.HTTPError("429")):
                result = scanner.get_thread_body(self._PERMALINK)

        assert result == ""

    def test_different_permalinks_cached_independently(self):
        """Cache entries are per-permalink; different permalinks get different bodies."""
        from unittest.mock import patch as _patch

        body_a = [{"data": {"children": [{"data": {"selftext": "body_A"}}]}}, {}]
        body_b = [{"data": {"children": [{"data": {"selftext": "body_B"}}]}}, {}]

        scanner = RedditMatchScanner(session=FakeSession([
            FakeResponse(200, body_a),
            FakeResponse(200, body_b),
        ]))

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            result_a = scanner.get_thread_body("/r/soccer/comments/aaa/")
            result_b = scanner.get_thread_body("/r/soccer/comments/bbb/")

        assert result_a == "body_A"
        assert result_b == "body_B"

    def test_cache_evicts_old_entries_when_over_limit(self):
        """Once the cache exceeds _THREAD_BODY_CACHE_MAX, entries older than
        _THREAD_BODY_CACHE_TTL_FACTOR × _THREAD_BODY_TTL are swept out.

        Regression: finished-match permalinks are never re-read, so without this
        sweep the cache would grow unbounded for the whole tournament."""
        from unittest.mock import patch as _patch
        from worldcup_bot.reddit.scanner import (
            _THREAD_BODY_CACHE_MAX,
            _THREAD_BODY_CACHE_TTL_FACTOR,
            _THREAD_BODY_TTL,
        )

        scanner = RedditMatchScanner(session=FakeSession([]))

        with _patch("worldcup_bot.reddit.scanner.time") as mock_time, _patch.object(
            scanner, "_fetch_thread_body_json", return_value="body"
        ):
            # Insert MAX+1 distinct permalinks all at t=0: over the limit, but
            # none old enough to sweep yet, so the cache holds them all.
            mock_time.monotonic.return_value = 0.0
            n = _THREAD_BODY_CACHE_MAX + 1
            for i in range(n):
                scanner.get_thread_body(f"/r/soccer/comments/old{i}/")
            assert len(scanner._thread_body_cache) == n

            # A later insert past the sweep horizon evicts all the t=0 entries.
            mock_time.monotonic.return_value = (
                _THREAD_BODY_TTL * _THREAD_BODY_CACHE_TTL_FACTOR + 1.0
            )
            scanner.get_thread_body("/r/soccer/comments/fresh/")

        assert len(scanner._thread_body_cache) == 1
        assert "/r/soccer/comments/fresh/" in scanner._thread_body_cache
