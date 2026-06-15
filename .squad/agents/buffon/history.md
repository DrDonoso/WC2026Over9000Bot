# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-06-15 — Initial test suite (Buffon)

**Test command (verified green):**
```
.venv\Scripts\python.exe -m pytest -q
# 137 passed in ~1.4s
```

**Setup:**
```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
```

**Coverage notes:**
- `tests/test_scoring.py` — 64 pure-function tests covering `score_groups` and `score_knockout`:
  exact (+1.0 after change), qualified-wrong-position (+0.5 after change), fallo (0), wildcard, no_data, empty inputs, all 5 KO stages,
  point values (ROUND_OF_32=1, LAST_16=1, QF=2, SF=3, FINAL=5), `score_user_groups_detail` alias.
  New test class `TestScoreGroupsQualifiesWrongPosition` added to verify qualification-at-wrong-position scoring.
- `tests/test_predictions_loader.py` — 32 tests: valid YAML load, 7 invalid-user cases (user skipped,
  no crash), mtime hot-reload (cache hit + cache miss), case-insensitive get_participant,
  find_by_display_name, display_name_for fallback, list_usernames.
- `tests/test_api_client.py` — 22 tests: TTLCache CRUD + expiry, standings parse, matches parse
  (null scores, null group), stage results (HOME/AWAY winner, SCHEDULED excluded),
  429/4xx/5xx FootballAPIError, TTL cache (2 calls → 1 HTTP request), cache expiry triggers
  new request, get_knockout_results uses single cached matches call.
- `tests/test_handlers.py` — 13 tests: cmd_start help text, cmd_lista_aciertos no-username fallback,
  caller-identity lowercasing, engine called with correct username, cmd_mis_predicciones
  identity + no-username, cmd_participantes empty and populated.

**Bugs found (see `.squad/decisions/inbox/buffon-findings.md`):**
1. `pyproject.toml` dependency `flag>=1.4` is wrong — correct package is `emoji-country-flag>=2.0`.
   Fixed in pyproject.toml as part of QA work.
2. `predictions.example.yml` uses `"SAU"` (Saudi Arabia) but `tla_map.py` has `"KSA"`.
   Causes `davidrodr` and `cris_username` to be silently skipped at startup.
   Root cause unclear — depends on what TLA `football-data.org` API actually returns.

**Testing conventions established:**
- Module-level predictions cache reset via autouse fixture in `conftest.py`.
- `responses` library used for all HTTP mocking (never real network).
- `asyncio_mode = "auto"` (pyproject.toml) means no `@pytest.mark.asyncio` needed.
- Handler tests use `unittest.mock.AsyncMock` + `patch("worldcup_bot.bot.handlers.*")`.
- File-based tests (hot-reload) use pytest `tmp_path` fixture (Windows temp dir, not /tmp).

**Group-phase scoring model change (Kanté):**
After this test run, Kanté replaced GROUP_SCORING model: exact_position +3, off_by_one +1 → exact_position +1.0, qualified_wrong_position +0.5.
All group-phase test assertions were recomputed; 137 tests now pass (6 new due to `TestScoreGroupsQualifiesWrongPosition`).
See `.squad/decisions.md` §7 for details.

### 2026-06-15 — Consolidation + Cross-Agent Learnings

- **Silent failures are deadly:** Group normalization bug ("Group A" → "GROUP_A") passed all unit tests because fixtures used canonical form. Only end-to-end testing caught it. Lesson: **mock third-party APIs with real response shapes**.
- **Dependency names matter:** PyPI has multiple packages with similar names. `flag` (the wrong one) is a Go CLI parser, not country emoji flags. Always verify package description on PyPI before adding to pyproject.toml.
- **Test fixtures should reflect reality:** Using hard-coded canonical forms in fixtures masked API format mismatches. Real API response shapes (even if they seem redundant) are worth including.
- **Two-stage verification:** Unit tests (isolation) caught pure-function bugs. End-to-end + live tests (integration) caught API format bugs.
- **Regression tests are insurance:** The group normalization fix included a regression test (real API format "Group A" → normalize → "GROUP_A"). This prevents future refactoring from reintroducing the bug.
- **Test suite as contract:** 131 passing tests serve as executable specification of the API and behavior. They're the most up-to-date documentation.
- **Lesson for future sessions:** When a bug requires API integration to manifest, it will probably escape unit testing. Plan for end-to-end testing early.
