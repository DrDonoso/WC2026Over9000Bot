"""Tests for scanner.get_espn_game_id."""

from __future__ import annotations

import pytest
import requests

from worldcup_bot.reddit.scanner import RedditMatchScanner


# ── helpers ───────────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.text = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns canned responses in FIFO order."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._queue = list(responses)
        self.headers = {}

    def update(self, h: dict) -> None:
        self.headers.update(h)

    def get(self, url: str, **kwargs) -> FakeResponse:
        if not self._queue:
            raise RuntimeError(f"FakeSession: no more canned responses for GET {url}")
        return self._queue.pop(0)


_SEARCH_HTML_MATCH_THREAD = """
<html>
  <a href="https://old.reddit.com/r/soccer/comments/abc123/match_thread_spain_vs_france_world_cup"
     class="search-title">Match Thread: Spain vs France | World Cup</a>
</html>
"""

_THREAD_HTML_WITH_ESPN = """
<html>
  <div class="usertext-body">
    <p>Match stats via ESPN: 
    <a href="http://www.espn.com/soccer/match?gameId=401866598">Match Events | via ESPN</a>
    </p>
  </div>
</html>
"""

_THREAD_HTML_WITHOUT_ESPN = """
<html>
  <div class="usertext-body">
    <p>No ESPN link here.</p>
  </div>
</html>
"""

_SEARCH_HTML_NO_THREAD = """
<html>
  <p>No results found.</p>
</html>
"""


class TestGetESPNGameId:
    def test_finds_game_id_from_thread(self):
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_HTML_MATCH_THREAD),  # find_match_thread search
                FakeResponse(200, _THREAD_HTML_WITH_ESPN),  # fetch thread HTML
            ]
        )
        scanner = RedditMatchScanner(session=session)
        result = scanner.get_espn_game_id("Spain", "France")
        assert result == "401866598"

    def test_returns_none_when_no_thread_found(self):
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_HTML_NO_THREAD),  # find_match_thread → None
            ]
        )
        scanner = RedditMatchScanner(session=session)
        result = scanner.get_espn_game_id("Spain", "France")
        assert result is None

    def test_returns_none_when_no_game_id_in_html(self):
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_HTML_MATCH_THREAD),
                FakeResponse(200, _THREAD_HTML_WITHOUT_ESPN),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        result = scanner.get_espn_game_id("Spain", "France")
        assert result is None

    def test_returns_none_on_http_error_for_thread_fetch(self):
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_HTML_MATCH_THREAD),
                FakeResponse(503, ""),  # thread fetch fails
            ]
        )
        scanner = RedditMatchScanner(session=session)
        result = scanner.get_espn_game_id("Spain", "France")
        assert result is None

    def test_extracts_first_game_id_when_multiple(self):
        html = """
        <html>
          <a href="http://www.espn.com/soccer/match?gameId=111">First</a>
          <a href="http://www.espn.com/soccer/match?gameId=222">Second</a>
        </html>
        """
        session = FakeSession(
            [
                FakeResponse(200, _SEARCH_HTML_MATCH_THREAD),
                FakeResponse(200, html),
            ]
        )
        scanner = RedditMatchScanner(session=session)
        result = scanner.get_espn_game_id("Spain", "France")
        assert result == "111"

    def test_returns_none_on_exception(self, monkeypatch):
        def bad_find(*args, **kwargs):
            raise RuntimeError("Network failure")

        scanner = RedditMatchScanner(session=FakeSession([]))
        monkeypatch.setattr(scanner, "find_match_thread", bad_find)
        result = scanner.get_espn_game_id("Spain", "France")
        assert result is None
