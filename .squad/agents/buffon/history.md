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

### 2026-06-26 — Live goal bug gate (Buffon)

**Reviewed PR:** Kanté's live-match goal-bug fixes (1552 → 1568 → 1570 passing).

**Fixes audited:**
- Fix A1 — `reconcile()` restart path (score_state.py): emit catch-up deltas when restarting mid-match.
- Fix A2 — `poll_goals_job` first-seen at non-zero score: emit incremental catch-up deltas.
- Fix B1 — `poll_goal_clips_job` keyboard race: set `entry["status"]="ready"` BEFORE `edit_message_reply_markup`.
- Fix D — `handlers.py` delete-after-send: delete local clip after file_id is persisted.

**Test audit results (all 17 new tests are real — none tautological):**
- Race-fix tests capture `entry["status"]` AT the moment `edit_message_reply_markup` is called; they WOULD FAIL without the fix.
- Delete-after-send tests use real temp files; file existence assertions confirm disk operations.
- Ordering test (`test_file_id_cached_before_delete`) uses a side-effect tracker to prove save precedes delete.
- Score-state restart tests correctly cover all branches: ahead, equal, below announced.

**Uncovered hazard flagged:**
- `reconcile()` restart catch-up emits all deltas with the FINAL score (not incremental). For 2+ same-team goals missed on restart, two deltas produce the same clip-store token key (`{id}:{team}:{H}-{A}`), and the second `add_entry` overwrites the first. The 3 goal notifications ARE still sent; only the clip association is wrong (first two buttons link to the same clip slot). Documented in gate verdict. No crash. Production fix needed from Kanté for the extreme multi-goal restart case.

**Tests added by Buffon (+2):**
1. `test_stale_file_id_with_deleted_file_sends_error_message` (test_handlers.py) — stale file_id + file deleted → graceful error message, no crash.
2. `test_restart_catchup_deltas_carry_final_score` (test_score_state.py) — regression guard documenting that reconcile restart deltas all carry the final score; includes the multi-goal-collision note as a comment.

**Final count: 1570 passed.**

### 2026-06-26 — Best-thirds qualifying scoring gate (Buffon)

**Reviewed PR:** Kanté's WC2026 best-thirds scoring change (1571 → 1613 passing).

**Fixes audited:**
- New `best_qualifying_thirds()` pure function — FIFA tiebreakers pts→GD→GF with stable group/TLA fallback.
- `score_groups` gained optional `qualifying_thirds` param; non-qualifying exact-3rd → 0.0; boundary+non-qualifying → 0.0; qualifying-3rd exact → 1.0; boundary+qualifying → 0.5. None = backward compat.
- `_build_qualifying_thirds()` helper in engine.py; wired into all engine public functions.
- `reconstruct_full_group_standings()` added to history.py; used by `compute_ranking_at_jornada`.
- `Standing` model gained `goal_difference` and `goals_for`; client parses them.

**Suite verification:** 1613 passed ✅ (matches Kanté's claim).

**Caller check (STEP 2):** All 7 production scoring paths correctly build and pass `qualifying_thirds`:
compute_general_ranking (provisional + official), compute_group_ranking, compute_user_detail (provisional + official), compute_ranking_at_jornada, ensure_history (latest uses compute_general_ranking which builds it internally; past jornadas use compute_ranking_at_jornada). ✅

**Coverage gap found and fixed:** No test in `test_engine.py` would have caught a caller forgetting to pass `qualifying_thirds` to `score_groups`. All existing engine tests use `points=0` standings with <8 groups, so provisional behavior (all thirds qualify) masked the bug. The history path had one good integration test (`test_non_qualifying_3rd_scores_zero_in_history_path`) but the direct engine paths were unguarded.

**Test quality audit (STEP 3):** All 42 new Kanté tests are real and non-tautological. Each would fail if the fix were reverted. Coverage confirmed for: empty/partial inputs, exactly-8-selected-from-12, ordering by pts/GD/GF, stable tie fallback, boundary/non-boundary scoring for qualifying and non-qualifying thirds, top-2 zone unaffected, backward-compat None, api client parsing.

**Edge cases (STEP 4):** 3-way tie at 8/9 boundary: deterministic via group+TLA stable sort, logged WARNING ✅. All 12 tied: covered ✅. Group with <3 entries: skipped ✅. Provisional (<8 thirds): all qualify ✅.

**Tests added by Buffon (+5):** Class `TestQualifyingThirdsCallerRegression` in `test_engine.py`:
1. `test_compute_general_ranking_provisional_non_qualifying_3rd_scores_zero`
2. `test_compute_general_ranking_official_non_qualifying_3rd_scores_zero`
3. `test_compute_user_detail_provisional_non_qualifying_3rd_scores_zero`
4. `test_compute_user_detail_official_non_qualifying_3rd_scores_zero`
5. `test_compute_group_ranking_non_qualifying_3rd_scores_zero` (first test ever for this function)

**Final count: 1618 passed, 5 warnings.**

**Session outcome:** Both Pirlo review and Buffon QA gates passed. Feature ready for owner deployment. Source changes (src/ + tests/) remain UNCOMMITTED per manifest (goal-notification fixes also uncommitted for parallel review).
