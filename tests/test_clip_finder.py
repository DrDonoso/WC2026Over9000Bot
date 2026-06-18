"""Tests for reddit.clip_finder — goal-clip post lookup in r/soccer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from worldcup_bot.reddit.clip_finder import (
    GOAL_TITLE_PATTERN,
    _extract_media_url,
    _match_post,
    _parse_clip_posts_html,
    _parse_search_results_html,
    _scorer_matches,
    find_goal_clip,
)
from worldcup_bot.reddit.scanner import RedditMatchScanner


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_scanner(json_response: dict | None = None, html_response: str = "") -> RedditMatchScanner:
    """Return a RedditMatchScanner backed by a mocked session."""
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    def _get(url, **kwargs):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        if "search.json" in url:
            if json_response is None:
                r.status_code = 403
            else:
                r.status_code = 200
                r.json.return_value = json_response
        else:
            r.status_code = 200
            r.text = html_response
        return r

    session.get = MagicMock(side_effect=_get)
    return RedditMatchScanner(session=session)


def _search_json(*posts: dict) -> dict:
    """Wrap post dicts in the Reddit search JSON envelope."""
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "id": p.get("id", "x"),
                        "title": p.get("title", ""),
                        "url": p.get("url", ""),
                        "url_overridden_by_dest": p.get("url", ""),
                        "permalink": p.get("permalink", "/r/soccer/comments/x/y/"),
                    }
                }
                for p in posts
            ]
        }
    }


# ── GOAL_TITLE_PATTERN ────────────────────────────────────────────────────────


class TestGoalTitlePattern:
    def test_home_scored_bracket(self):
        m = GOAL_TITLE_PATTERN.match("Sweden [3] - 1 Tunisia - Viktor Gyökeres 60'")
        assert m is not None
        assert m.group("home_team") == "Sweden"
        assert m.group("home_bracket") == "["
        assert m.group("home_score") == "3"
        assert m.group("away_score") == "1"
        assert m.group("away_team") == "Tunisia"
        assert m.group("scorer") == "Viktor Gyökeres"
        assert m.group("minute") == "60"

    def test_away_scored_bracket(self):
        m = GOAL_TITLE_PATTERN.match("Sweden 1 - [1] Tunisia - Omar Rekik 43'")
        assert m is not None
        assert m.group("away_bracket") == "["
        assert m.group("away_score") == "1"

    def test_plus_sign_minute(self):
        m = GOAL_TITLE_PATTERN.match("Spain [2] - 0 Portugal - Yamal 90+'")
        assert m is not None
        assert m.group("minute") == "90"

    def test_no_match_non_goal_title(self):
        assert GOAL_TITLE_PATTERN.match("Match Thread: Sweden vs Tunisia") is None

    def test_no_match_plain_title(self):
        assert GOAL_TITLE_PATTERN.match("Daily Discussion Thread") is None


# ── _extract_media_url ────────────────────────────────────────────────────────


class TestExtractMediaUrl:
    def test_streamff_link(self):
        url = _extract_media_url("https://streamff.link/v/abc123")
        assert url == "https://streamff.link/v/abc123"

    def test_streamin_link(self):
        url = _extract_media_url("https://streamin.link/v/63433cf8")
        assert url == "https://streamin.link/v/63433cf8"

    def test_streamable(self):
        url = _extract_media_url("https://streamable.com/abcdef")
        assert url == "https://streamable.com/abcdef"

    def test_v_redd_it(self):
        url = _extract_media_url("https://v.redd.it/abcdef")
        assert url == "https://v.redd.it/abcdef"

    def test_reddit_permalink_returns_none(self):
        url = _extract_media_url("https://www.reddit.com/r/soccer/comments/abc/def/")
        assert url is None

    def test_reddit_self_post_returns_none(self):
        url = _extract_media_url("https://old.reddit.com/r/soccer/comments/abc/def/")
        assert url is None

    def test_dropr_co_known_host(self):
        url = _extract_media_url("https://dropr.co/v/3ba063ff")
        assert url == "https://dropr.co/v/3ba063ff"

    def test_generic_fallback_novel_host(self):
        url = _extract_media_url("https://newcliphost.xyz/v/abc123")
        assert url == "https://newcliphost.xyz/v/abc123"

    def test_generic_fallback_excludes_redd_it_image(self):
        assert _extract_media_url("https://i.redd.it/abc.jpg") is None

    def test_generic_fallback_excludes_reddit_com(self):
        assert _extract_media_url("https://www.reddit.com/r/soccer/abc") is None

    def test_generic_fallback_excludes_imgur(self):
        assert _extract_media_url("https://imgur.com/a/x") is None

    def test_generic_fallback_excludes_static_image_png_case_insensitive(self):
        assert _extract_media_url("https://host.com/pic.PNG") is None

    def test_generic_fallback_excludes_jpeg(self):
        assert _extract_media_url("https://cdn.example.com/image.jpeg") is None

    def test_generic_fallback_allows_image_extension_in_query_string(self):
        """URL with .jpg only in query string (not path) should NOT be excluded."""
        url = "https://newcliphost.xyz/v/clip?thumb=preview.jpg"
        assert _extract_media_url(url) == url


# ── _scorer_matches ───────────────────────────────────────────────────────────


class TestScorerMatches:
    def test_exact_match(self):
        assert _scorer_matches("Gyökeres", "Gyökeres") is True

    def test_full_name_contains_last_name(self):
        assert _scorer_matches("Viktor Gyökeres", "Gyökeres") is True

    def test_last_name_match(self):
        assert _scorer_matches("Viktor Gyökeres", "Viktor Gyökeres") is True

    def test_no_match(self):
        assert _scorer_matches("Messi", "Ronaldo") is False

    def test_empty_scorer(self):
        assert _scorer_matches("", "Messi") is False

    def test_partial_last_name_accent_stripped(self):
        """Accent-folding makes 'Gyokeres' identical to 'Gyökeres' → match."""
        assert _scorer_matches("Gyokeres", "Viktor Gyökeres") is True

    def test_surname_initial_goal_wissa(self):
        """r/soccer 'Surname Initial. goal' format: Wissa Y. goal → Yoane Wissa."""
        assert _scorer_matches("Wissa Y. goal", "Yoane Wissa") is True

    def test_surname_initial_goal_neves(self):
        """r/soccer 'Surname Initial. goal' format: Neves J. goal → João Neves."""
        assert _scorer_matches("Neves J. goal", "João Neves") is True

    def test_full_firstname_lastname_joao_cancelo(self):
        assert _scorer_matches("João Cancelo", "João Cancelo") is True

    def test_surname_only_against_full_name(self):
        """Clip has only surname (e.g. 'Gyökeres') vs full target name."""
        assert _scorer_matches("Gyökeres", "Viktor Gyökeres") is True

    def test_r_initial_goal_format_leao(self):
        assert _scorer_matches("R. Leão goal", "Rafael Leão") is True

    def test_noise_only_clip_returns_false(self):
        """After stripping noise 'goal' leaves no tokens → fallback → False."""
        assert _scorer_matches("goal", "Ronaldo") is False

    def test_truly_different_names_false(self):
        assert _scorer_matches("Lukaku", "Viktor Gyökeres") is False


# ── _match_post ───────────────────────────────────────────────────────────────


class TestMatchPost:
    def _post(self, title: str, url: str) -> dict:
        return {"id": "x", "title": title, "url": url, "permalink": "/r/soccer/x/"}

    def test_exact_match_returns_media_url(self):
        post = self._post(
            "Sweden [3] - 1 Tunisia - Viktor Gyökeres 60'",
            "https://streamin.link/v/63433cf8",
        )
        result = _match_post(post, "Sweden", "Tunisia", 3, 1, "Viktor Gyökeres", 60)
        assert result == "https://streamin.link/v/63433cf8"

    def test_wrong_score_returns_none(self):
        post = self._post(
            "Sweden [2] - 1 Tunisia - Gyökeres 60'",
            "https://streamin.link/v/63433cf8",
        )
        result = _match_post(post, "Sweden", "Tunisia", 3, 1, "Gyökeres", 60)
        assert result is None

    def test_wrong_teams_returns_none(self):
        post = self._post(
            "Argentina [2] - 0 Brazil - Messi 30'",
            "https://streamff.link/v/xxx",
        )
        result = _match_post(post, "Sweden", "Tunisia", 2, 0, "Messi", 30)
        assert result is None

    def test_minute_tolerance_plus_one(self):
        """Target minute 59 should match a clip titled with minute 60 (within ±2)."""
        post = self._post(
            "Sweden [3] - 1 Tunisia - Gyökeres 60'",
            "https://streamin.link/v/abc",
        )
        result = _match_post(post, "Sweden", "Tunisia", 3, 1, "OtherScorer", 59)
        assert result is not None

    def test_minute_tolerance_minus_two(self):
        """Target minute 62 should match a clip titled with minute 60 (within ±2)."""
        post = self._post(
            "Sweden [3] - 1 Tunisia - Gyökeres 60'",
            "https://streamin.link/v/abc",
        )
        result = _match_post(post, "Sweden", "Tunisia", 3, 1, "OtherScorer", 62)
        assert result is not None

    def test_minute_out_of_tolerance_and_wrong_scorer_returns_none(self):
        post = self._post(
            "Sweden [3] - 1 Tunisia - Gyökeres 60'",
            "https://streamin.link/v/abc",
        )
        result = _match_post(post, "Sweden", "Tunisia", 3, 1, "SomeoneElse", 75)
        assert result is None

    def test_no_media_url_in_post_url_returns_none(self):
        post = self._post(
            "Sweden [3] - 1 Tunisia - Gyökeres 60'",
            "https://www.reddit.com/r/soccer/comments/abc/",
        )
        result = _match_post(post, "Sweden", "Tunisia", 3, 1, "Gyökeres", 60)
        assert result is None

    def test_reversed_teams_match(self):
        """Clip lists away team first but URL is extractable."""
        post = self._post(
            "Tunisia [0] - 3 Sweden - Gyökeres 60'",
            "https://streamin.link/v/abc",
        )
        # home=Sweden, away=Tunisia, hs=3, as=0; clip has Tunisia first with hs=0, as=3
        result = _match_post(post, "Sweden", "Tunisia", 3, 0, "Gyökeres", 60)
        assert result is not None

    def test_fuzzy_team_name_netherlands_holland(self):
        """'Holland' in clip title should match 'Netherlands'."""
        post = self._post(
            "Holland [1] - 0 Morocco - Depay 55'",
            "https://streamff.link/v/dep55",
        )
        result = _match_post(post, "Netherlands", "Morocco", 1, 0, "Depay", 55)
        assert result is not None

    def test_portugal_dr_congo_dotted_name_dropr_url(self):
        """Live bug: D.R. Congo in clip title + dropr.co URL must match."""
        post = self._post(
            "Portugal [1] - 0 D.R. Congo - Neves J. goal 5'",
            "https://dropr.co/v/3ba063ff",
        )
        result = _match_post(post, "Portugal", "Congo DR", 1, 0, "João Neves", 6)
        assert result == "https://dropr.co/v/3ba063ff"

    def test_wissa_scorer_format_minute_off_by_four(self):
        """Live bug: 'Wissa Y. goal 49'' must match target (Yoane Wissa, 45').

        Scorer fix is the primary signal (token intersection), minute diff=4 > ±3
        so minute_ok is False — the scorer fix alone must carry the match.
        """
        post = self._post(
            "Portugal 1 - [1] D.R. Congo - Wissa Y. goal 49'",
            "https://dropr.co/v/849532d6",
        )
        result = _match_post(post, "Portugal", "Congo DR", 1, 1, "Yoane Wissa", 45)
        assert result == "https://dropr.co/v/849532d6"

    def test_guard_wrong_scorer_and_minute_far_off_returns_none(self):
        """Different scorer + minute off by more than ±3 must not match."""
        post = self._post(
            "Portugal 1 - [1] D.R. Congo - Lukaku 80'",
            "https://dropr.co/v/999999",
        )
        result = _match_post(post, "Portugal", "Congo DR", 1, 1, "Yoane Wissa", 45)
        assert result is None

    def test_czech_republic_clip_title_matches_czechia_fixture(self):
        """Live bug: 'Czech Republic [1] - 0 South Africa' must match Czechia fixture."""
        post = self._post(
            "Czech Republic [1] - 0 South Africa - M. Sadílek 6'",
            "https://streamin.link/v/9801698f",
        )
        result = _match_post(post, "Czechia", "South Africa", 1, 0, "Michal Sadílek", 6)
        assert result == "https://streamin.link/v/9801698f"


# ── find_goal_clip ────────────────────────────────────────────────────────────


class TestFindGoalClip:
    def test_returns_streamin_url_for_matching_goal(self):
        """JSON search returns a matching post; find_goal_clip returns its media URL."""
        response = _search_json(
            {
                "id": "abc123",
                "title": "Sweden [3] - 1 Tunisia - Viktor Gyökeres 60'",
                "url": "https://streamin.link/v/63433cf8",
                "permalink": "/r/soccer/comments/abc123/",
            },
            {  # decoy
                "id": "decoy1",
                "title": "Argentina [2] - 0 Brazil - Messi 30'",
                "url": "https://streamff.link/v/zzz",
                "permalink": "/r/soccer/comments/decoy1/",
            },
        )
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Sweden", "Tunisia", 3, 1, "Viktor Gyökeres", 60)
        assert result == "https://streamin.link/v/63433cf8"

    def test_minute_tolerance_target_59_matches_title_60(self):
        """Target minute 59 should match a clip titled with minute 60."""
        response = _search_json(
            {
                "id": "abc123",
                "title": "Sweden [3] - 1 Tunisia - Gyökeres 60'",
                "url": "https://streamin.link/v/63433cf8",
                "permalink": "/r/soccer/comments/abc123/",
            }
        )
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Sweden", "Tunisia", 3, 1, "SomeBody", 59)
        assert result == "https://streamin.link/v/63433cf8"

    def test_returns_none_when_no_post_matches(self):
        """No matching post → returns None."""
        response = _search_json(
            {
                "id": "decoy1",
                "title": "Argentina [2] - 0 Brazil - Messi 30'",
                "url": "https://streamff.link/v/zzz",
                "permalink": "/r/soccer/comments/decoy1/",
            }
        )
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Sweden", "Tunisia", 3, 1, "Gyökeres", 60)
        assert result is None

    def test_html_fallback_used_on_403(self):
        """On 403 from JSON search, HTML fallback returns correct URL."""
        html = """
        <div data-fullname="t3_xyz"
             data-timestamp="1750000000000"
             data-url="https://streamin.link/v/fallback"
             data-permalink="/r/soccer/comments/xyz/sweden_3_1_tunisia/">
          <a class="title may-blank" href="/r/soccer/comments/xyz/">
            Sweden [3] - 1 Tunisia - Gyökeres 60&#39;
          </a>
        </div>
        """
        scanner = _make_scanner(json_response=None, html_response=html)
        result = find_goal_clip(scanner, "Sweden", "Tunisia", 3, 1, "Gyökeres", 60)
        assert result == "https://streamin.link/v/fallback"

    def test_fuzzy_team_match_netherlands_vs_holland(self):
        """'Holland' in a clip title matches a lookup for 'Netherlands'."""
        response = _search_json(
            {
                "id": "hol1",
                "title": "Holland [1] - 0 Morocco - Depay 55'",
                "url": "https://streamff.link/v/dep55",
                "permalink": "/r/soccer/comments/hol1/",
            }
        )
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Netherlands", "Morocco", 1, 0, "Depay", 55)
        assert result == "https://streamff.link/v/dep55"

    def test_returns_none_on_empty_search_results(self):
        """Empty search results → None, no exception."""
        response = _search_json()  # empty children list
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Sweden", "Tunisia", 3, 1, "Gyökeres", 60)
        assert result is None

    def test_portugal_dr_congo_dropr_integration(self):
        """Integration: D.R. Congo dotted-name + dropr.co URL → finds clip."""
        response = _search_json(
            {
                "id": "dropr1",
                "title": "Portugal [1] - 0 D.R. Congo - Neves J. goal 5'",
                "url": "https://dropr.co/v/3ba063ff",
                "permalink": "/r/soccer/comments/dropr1/",
            }
        )
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Portugal", "Congo DR", 1, 0, "João Neves", 6)
        assert result == "https://dropr.co/v/3ba063ff"

    def test_czechia_czech_republic_clip_title_integration(self):
        """Live bug: clip title 'Czech Republic [1] - 0 South Africa' finds streamin URL
        when target fixture uses football-data's canonical name 'Czechia'."""
        response = _search_json(
            {
                "id": "cze1",
                "title": "Czech Republic [1] - 0 South Africa - M. Sadílek 6'",
                "url": "https://streamin.link/v/9801698f",
                "permalink": "/r/soccer/comments/cze1/",
            }
        )
        scanner = _make_scanner(json_response=response)
        result = find_goal_clip(scanner, "Czechia", "South Africa", 1, 0, "Michal Sadílek", 6)
        assert result == "https://streamin.link/v/9801698f"


# ── _parse_clip_posts_html ────────────────────────────────────────────────────


class TestParseClipPostsHtml:
    def test_extracts_url_from_data_url_attribute(self):
        html = """
        <div data-fullname="t3_abc"
             data-timestamp="1750000000000"
             data-url="https://streamin.link/v/abc"
             data-permalink="/r/soccer/comments/abc/title/">
          <a class="title may-blank" href="/r/soccer/comments/abc/">Title Here</a>
        </div>
        """
        posts = _parse_clip_posts_html(html)
        assert len(posts) == 1
        assert posts[0]["url"] == "https://streamin.link/v/abc"
        assert posts[0]["title"] == "Title Here"

    def test_multiple_posts(self):
        html = """
        <div data-fullname="t3_p1" data-timestamp="1750000000000"
             data-url="https://streamff.link/v/p1" data-permalink="/p1/">
          <a class="title may-blank" href="/p1/">Post 1</a>
        </div>
        <div data-fullname="t3_p2" data-timestamp="1750000001000"
             data-url="https://streamin.link/v/p2" data-permalink="/p2/">
          <a class="title may-blank" href="/p2/">Post 2</a>
        </div>
        """
        posts = _parse_clip_posts_html(html)
        assert len(posts) == 2
        urls = {p["url"] for p in posts}
        assert "https://streamff.link/v/p1" in urls
        assert "https://streamin.link/v/p2" in urls


# ── HTML search fallback ──────────────────────────────────────────────────────

# Fixture: real search-results HTML structure (old.reddit.com/r/soccer/search?q=…).
# Link posts expose the external media URL via class="search-link" footer anchor.
_HTML_SEARCH_LISTING = """
<div data-fullname="t3_abc123">
  <header class="search-result-header">
    <a href="https://old.reddit.com/r/soccer/comments/abc123/sweden_3_1_tunisia_gyokeres_60/" class="search-title may-blank">Sweden [3] - 1 Tunisia - Viktor Gy\u00f6keres 60'</a>
  </header>
  <div class="search-result-footer">
    <a href="https://streamin.link/v/63433cf8" class="search-link may-blank">https://streamin.link/v/63433cf8</a>
  </div>
</div>
<div data-fullname="t3_decoy">
  <header class="search-result-header">
    <a href="https://old.reddit.com/r/soccer/comments/decoy/argentina_1_0_brazil/" class="search-title may-blank">Argentina [1] - 0 Brazil - Messi 30'</a>
  </header>
  <div class="search-result-footer">
    <a href="https://streamff.link/v/decoy" class="search-link may-blank">https://streamff.link/v/decoy</a>
  </div>
</div>
"""


class TestParseSearchResultsHtml:
    """Tests for _parse_search_results_html — search results page parser."""

    def test_extracts_title_and_link_url(self):
        posts = _parse_search_results_html(_HTML_SEARCH_LISTING)
        assert len(posts) == 2
        gyokeres = next(p for p in posts if "Gy" in p["title"])
        assert gyokeres["url"] == "https://streamin.link/v/63433cf8"
        assert "Viktor Gy\u00f6keres" in gyokeres["title"]

    def test_skips_blocks_without_search_title(self):
        """Old listing-format HTML (no search-title class) yields no posts."""
        old_listing = """
        <div data-fullname="t3_xyz" data-timestamp="1750000000000"
             data-url="https://streamin.link/v/xyz"
             data-permalink="/r/soccer/comments/xyz/">
          <a class="title may-blank" href="/r/soccer/comments/xyz/">Title</a>
        </div>
        """
        posts = _parse_search_results_html(old_listing)
        assert posts == []

    def test_self_post_without_search_link_uses_permalink_as_url(self):
        """A self-post search result (no external link) falls back to permalink."""
        html = """
        <div data-fullname="t3_selfpost">
          <header>
            <a href="https://old.reddit.com/r/soccer/comments/selfpost/match_thread_x_vs_y/" class="search-title may-blank">Match Thread: X vs Y</a>
          </header>
        </div>
        """
        posts = _parse_search_results_html(html)
        assert len(posts) == 1
        assert posts[0]["url"] == "https://old.reddit.com/r/soccer/comments/selfpost/match_thread_x_vs_y/"


class TestFindGoalClipHtmlSearch:
    """HTML search fallback when JSON endpoint returns 403."""

    def test_html_search_returns_correct_clip_on_json_403(self):
        """JSON 403 -> HTML search endpoint -> returns the matching clip URL."""
        from unittest.mock import MagicMock

        urls_hit: list[str] = []

        def _get(url, **kwargs):
            urls_hit.append(url)
            r = MagicMock()
            r.raise_for_status = MagicMock()
            if "search.json" in url:
                r.status_code = 403
            else:
                r.status_code = 200
                r.text = _HTML_SEARCH_LISTING
            return r

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        scanner = RedditMatchScanner(session=session)

        result = find_goal_clip(scanner, "Sweden", "Tunisia", 3, 1, "Viktor Gy\u00f6keres", 59)

        assert result == "https://streamin.link/v/63433cf8"
        # The HTML search endpoint (not /new/) must have been called
        html_search_urls = [u for u in urls_hit if "search" in u and "search.json" not in u]
        assert len(html_search_urls) >= 1
        assert "Sweden" in html_search_urls[0] or "sweden" in html_search_urls[0].lower()

    def test_html_search_decoy_not_returned(self):
        """HTML search listing with a decoy post: only the matching clip is returned."""
        from unittest.mock import MagicMock

        def _get(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.status_code = 403 if "search.json" in url else 200
            r.text = _HTML_SEARCH_LISTING
            return r

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        scanner = RedditMatchScanner(session=session)

        result = find_goal_clip(scanner, "Argentina", "Brazil", 1, 0, "Messi", 30)
        assert result == "https://streamff.link/v/decoy"

    def test_html_search_falls_through_to_new_listing_when_empty(self):
        """If HTML search returns no posts, falls back to /new/ listing."""
        from unittest.mock import MagicMock

        new_html = """
        <div data-fullname="t3_new1" data-timestamp="1750000000000"
             data-url="https://streamff.link/v/newclip"
             data-permalink="/r/soccer/comments/new1/sweden_goal/">
          <a class="title may-blank" href="/r/soccer/comments/new1/">
            Sweden [1] - 0 Tunisia - Isak 10&#39;
          </a>
        </div>
        """

        def _get(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.status_code = 200
            if "search.json" in url:
                r.status_code = 403
            elif "search?" in url and "search.json" not in url:
                r.text = ""
            else:
                r.text = new_html
            return r

        session = MagicMock()
        session.get = MagicMock(side_effect=_get)
        scanner = RedditMatchScanner(session=session)

        result = find_goal_clip(scanner, "Sweden", "Tunisia", 1, 0, "Isak", 10)
        assert result == "https://streamff.link/v/newclip"


class TestFindGoalClipMergeNewListing:
    """HTML search + /new/ listing are always merged when JSON is unavailable."""

    def test_clip_only_in_new_listing_found_when_html_search_has_unrelated_posts(self):
        """HTML search returns unrelated posts; matching clip is only in /new/ → still found."""
        from unittest.mock import patch

        unrelated = {
            "id": "unrelated1",
            "title": "Portugal [1] - 0 D.R. Congo - Neves J. goal 5'",
            "url": "https://dropr.co/v/3ba063ff",
            "permalink": "/r/soccer/comments/unrelated1/",
        }
        cancelo_post = {
            "id": "cancelo1",
            "title": "Portugal [2] - 1 D.R. Congo - João Cancelo 55'",
            "url": "https://streamin.link/v/f5eabdf2",
            "permalink": "",
        }

        with (
            patch("worldcup_bot.reddit.clip_finder._fetch_search_posts", return_value=None),
            patch("worldcup_bot.reddit.clip_finder._fetch_html_search_posts", return_value=[unrelated]),
            patch("worldcup_bot.reddit.clip_finder._fetch_html_posts", return_value=[cancelo_post]),
        ):
            result = find_goal_clip(
                MagicMock(), "Portugal", "Congo DR", 2, 1, "João Cancelo", 55
            )

        assert result == "https://streamin.link/v/f5eabdf2"

    def test_dedupe_same_post_id_in_html_search_and_new_listing(self):
        """Same post id in both sources → matched exactly once, no crash or duplication."""
        from unittest.mock import patch

        shared_post = {
            "id": "dupe123",
            "title": "Portugal [2] - 1 D.R. Congo - João Cancelo 55'",
            "url": "https://streamin.link/v/f5eabdf2",
            "permalink": "/r/soccer/comments/dupe123/",
        }

        with (
            patch("worldcup_bot.reddit.clip_finder._fetch_search_posts", return_value=None),
            patch("worldcup_bot.reddit.clip_finder._fetch_html_search_posts", return_value=[shared_post]),
            patch("worldcup_bot.reddit.clip_finder._fetch_html_posts", return_value=[shared_post]),
        ):
            result = find_goal_clip(
                MagicMock(), "Portugal", "Congo DR", 2, 1, "João Cancelo", 55
            )

        assert result == "https://streamin.link/v/f5eabdf2"
