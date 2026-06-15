# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-06-15 — /actual (provisional) vs /general (official) split + /porra alias

**Implemented as user-approved design:**

- **`/actual`** → provisional ranking "a día de hoy": uses `engine.compute_general_ranking(official=False)` which scores all groups from live standings. `/porra` is an alias pointing to the same `cmd_actual` handler.
- **`/general`** → official ranking: uses `engine.compute_general_ranking(official=True)`. Group points only count for groups that are fully FINISHED (all matches status=FINISHED). Groups still in progress contribute 0 for all predicted teams. Shows a footer with count of closed groups and a hint to use `/actual` if not all groups are closed.
- **Key implementation details:**
  - `client.get_finished_groups()` computes the set of GROUP_X ids from `get_all_matches()` where every match in the group has `status == "FINISHED"`. Knockout matches (`group=None`) are ignored. Relies on the existing `_normalize_group` boundary so results are always in canonical `GROUP_X` form.
  - `_build_actual_standings(client, only_groups=None)` now accepts an optional `only_groups: set[str]` filter. When provided, standings for groups not in the set are excluded — causing `score_groups` to fall through its `no_data` branch and produce 0 pts for those groups.
  - `compute_general_ranking(predictions, client, official=False)` adds the `official` kwarg. `official=True` calls `get_finished_groups()` and passes the result as `only_groups`. Knockout scoring is unchanged in both modes.
  - The old `cmd_porra` (group-only ranking via `compute_group_ranking`) was removed. `/porra` now routes to `cmd_actual` in `__main__.py`. `compute_group_ranking` is preserved in engine.py.
  - `cmd_general` calls `get_finished_groups()` a second time (for the footer) after the engine already called it internally; the TTLCache ensures only one HTTP round-trip for the matches endpoint per command.
- **New tests added:** `TestGetFinishedGroups` (6 tests in `test_api_client.py`), `TestComputeGeneralRankingProvisional` + `TestComputeGeneralRankingOfficial` (11 tests in `test_engine.py`), `TestBuildAppRegistrations` (2 tests in `test_handlers.py`). Total test count: 137 → 156 (all green).

### 2026-06-15 — Removed per-stage ranking commands (approved by DrDonoso)

**Deleted (orphaned after removal of 5 commands):**
- `handlers.py`: `_cmd_knockout_stage`, `cmd_ronda32`, `cmd_octavos`, `cmd_cuartos`, `cmd_semis`, `cmd_final`, and `format_stage_ranking` import.
- `__main__.py`: imports and `CommandHandler` registrations for the 5 commands.
- `engine.py`: `compute_knockout_ranking(stage, predictions, client)` and `StageRankEntry` dataclass.
- `formatters.py`: `format_stage_ranking(rows, stage_display)`.
- `/start` help text: 5 command lines removed.
- `README.md`: 5 rows removed from command table.
- No test files needed changes (none had targeted those symbols).

**Kept intact (still used by `/general` and `/actual`):**
- `score_knockout` in `scoring.py` — the per-stage SCORING function that feeds `compute_general_ranking`. This is NOT the same as the removed `compute_knockout_ranking` (which was a per-stage RANKING function). Removal of the ranking commands does not touch scoring.
- `compute_general_ranking`, `compute_group_ranking`, `compute_user_detail`, `_build_actual_standings`, `_build_actual_winners` in `engine.py`.
- `KNOCKOUT_STAGES` config and escalating points in `stages.py`.
- All `TestScoreKnockout*` tests in `test_scoring.py`.
- Total: 156 tests, all green after removal.

### 2026-06-15 — Removed /resultados command (approved by DrDonoso)

**Deleted (orphaned; knockout phase not yet started):**
- `handlers.py`: `cmd_resultados` handler and `format_knockout_results` import.
- `__main__.py`: `cmd_resultados` import and `CommandHandler("resultados", cmd_resultados)` registration.
- `formatters.py`: `format_knockout_results(matches, stages_display)` function.
- `/start` help text: `/resultados — resultados de eliminatorias` line removed.
- `README.md`: `/resultados` row removed from command table.
- No test files needed changes (none targeted these symbols).

**Kept intact (still used by /general and /actual scoring):**
- `get_stage_results` and `get_knockout_results` in `client.py` — feed `engine._build_actual_winners` → `compute_general_ranking`. Removal of the display command does NOT touch the data-fetching layer.
- `StageResult` dataclass in `api/models.py`.
- `KNOCKOUT_STAGES` config in `stages.py`.
- All KO-related tests in `test_api_client.py` and `test_scoring.py`.
- Total: 156 tests, all green after removal.

**Will be re-added:** `/resultados` command will be restored when the knockout phase begins.

### 2026-06-15 — /listaaciertos split into official + provisional

- **`/listaaciertos`** → now OFFICIAL: calls `engine.compute_user_detail(official=True)`. Groups only score if ALL their matches are `FINISHED` (gated via `client.get_finished_groups()`). Knockout rounds only appear in detail/score if ALL matches in that stage are `FINISHED` (gated via new `client.get_finished_stages()`).
- **`/listaaciertosactual`** → PROVISIONAL "a día de hoy": calls `compute_user_detail(official=False)` — unchanged live behavior.
- **`client.get_finished_stages()`** added (mirror of `get_finished_groups`): filters `get_all_matches()` to `KNOCKOUT_STAGES` api names and returns stages where every match is `FINISHED`. Reuses the same TTL-cached `get_all_matches()` call.
- **`compute_user_detail`** gained `official: bool = False` kwarg (mirrors pattern of `compute_general_ranking`). In official mode: builds filtered standings/winners/user_ko before calling `score_groups`/`score_knockout`. Returns new keys: `"official"`, `"finished_groups"` (count or None), `"total_groups"` (12).
- **`format_user_detail`** updated: title differentiates official vs provisional; footer shows closed-group count when not all closed (official), or a provisional hint (provisional).
- **Handlers**: both commands share a private `_send_user_detail(update, context, *, official)` helper to avoid duplication.
- **Tests**: 156 → 187 (31 new). `TestGetFinishedStages` (6), `TestComputeUserDetailProvisional` (8), `TestComputeUserDetailOfficial` (9), `TestBuildAppRegistrations.test_listaaciertos_*` (1), `TestCmdListaAciertosOfficial` (2), `TestCmdListaAciertosActual` (5).

### 2026-06-15 — Football-day rolling window: /hoy repurposed + /ayer added

**Date:** 2026-06-15T16:21+02:00

**Context:** WC2026 is hosted in North America; matches fall late at night / early morning CEST. A calendar-day boundary at midnight splits a single matchday awkwardly for Madrid viewers.

**Implemented:**

- **Football-day window** = 24h rolling block `[anchor:00 local, anchor:00 local + 24h)` that _contains now_. If `now_local` is before the anchor (e.g. 02:00), the active block started at anchor the **previous** calendar day. This keeps a 01:00 CEST match on "tonight's" football day.
- **`_football_day_bounds(tz_name, day_offset, anchor_hour)`**: pytz-based, DST-safe (`local_tz.localize(naive_anchor)` not `.replace(tzinfo=...)`). Bounds converted to UTC for match comparison.
- **`get_football_day_matches(tz_name, day_offset, anchor_hour)`**: public method. `day_offset=0` → /hoy; `day_offset=-1` → /ayer. Sorted ascending by `utc_date`.
- **`get_today_matches`** deleted (calendar-day semantics replaced; no test references existed).
- **`/hoy`** handler updated: calls `get_football_day_matches(tz_name, 0, h)`. Header shows configured anchor hour.
- **`/ayer`** new command: calls `get_football_day_matches(tz_name, -1, h)`. Shows yesterday's football-day results.
- **`FOOTBALL_DAY_START_HOUR`** env var added to `Settings` (`football_day_start_hour: int = 9`, default 9). Mirrors `football_cache_ttl` pattern.
- `.env.example` updated with commented `FOOTBALL_DAY_START_HOUR=9` line (noted in decision file for Maldini).
- **16 new tests** (13 window tests + 4 config tests − 1 overlap counted). Total: 196 → 212.



**Root cause of HTTP 429 rate limit:** `make_client(settings)` in `handlers.py` built a NEW `FootballDataClient` on every Telegram command, and `FootballDataClient.__init__` had `self._cache = cache or TTLCache(ttl=60)` — so each command received its own fresh empty cache. The module-level `_default_cache` in `api/cache.py` was dead code, never injected anywhere. With 12 users and ~2 API calls per command, the 10 req/min free tier was easily exceeded.

**Fix applied:**
- `api/cache.py`: Changed `_default_cache` from an eager module-level instance to a lazily-initialized global (`None` initially). Added `get_default_cache(ttl=_DEFAULT_TTL)` (creates singleton on first call, returns it on all subsequent calls) and `reset_default_cache(ttl=_DEFAULT_TTL)` (test helper: replaces singleton with a fresh empty instance).
- `config.py`: Added `football_cache_ttl: float = 60.0` to `Settings` dataclass; `load_settings()` reads `FOOTBALL_CACHE_TTL` env var (default `"60"`).
- `bot/handlers.py`: `make_client` now imports and calls `get_default_cache(ttl=settings.football_cache_ttl)` and passes the result as `cache=` to `FootballDataClient`. All commands on all users now share ONE process-wide TTLCache — each distinct URL hits the network at most once per TTL window.
- `api/client.py`: 429 handler now logs `WARNING` with URL and `Retry-After` header before raising `FootballAPIError`.
- `tests/conftest.py`: Added autouse `reset_api_default_cache` fixture to isolate the singleton between test runs.
- **New tests**: `TestSharedDefaultCache` (5 tests in `test_api_client.py`), `TestSettings`/`TestLoadSettings` (4 tests in new `test_config.py`). Total: 187 → 196 (9 new), all green.

### 2026-06-15T16:34+02:00 — /clasificacion now accepts optional A–L letter

- `/clasificacion` without args → unchanged (all 12 groups via `format_standings`).
- `/clasificacion L` (or lowercase, or any position in args) → filters standings to `GROUP_L` before passing to `format_standings`. `format_standings` untouched.
- Invalid letter → friendly Spanish error returned early, no API call.
- Valid letter but no data → "No hay clasificación disponible para el Grupo X todavía."
- Help text and README updated. 5 new handler tests (`TestCmdClasificacion`). Total: 212 → 217 (all green).

### 2026-06-15T16:52+02:00 — /actual & /general now send top-3 photo album

- **`/actual`** and **`/general`** now send a Telegram photo album (`sendMediaGroup`) with the top-3 ranked participants' photos instead of a single winner photo.
- Photos fetched from `{PHOTO_BASE_URL}/{username}.png` (default `http://victorsaez.cat`). `username` = the lowercase predictions.yml key (e.g. `crispavon`, `dsantosmerino`).
- Each URL is validated with `requests.get(url, timeout=4, stream=True)` before use: must return HTTP 200 with `image/` Content-Type. Unreachable → skipped; order preserved. Network errors caught and skipped gracefully.
- If ≥1 valid URL: album sent via `context.bot.send_media_group`. Caption (≤1024 chars) on first item only; if caption truncated, full text follows as separate `reply_text`. On `send_media_group` failure → fallback to `reply_text`.
- If 0 valid URLs: plain `reply_text` with ranking text.
- `format_general_ranking` now returns `str` only (removed `winner_photo_url` tuple return). Text leader/tie line unchanged.
- `participant_photo_url(username, base_url) -> str` added to `formatters.py`.
- `photo_base_url: str` added to `Settings` (env `PHOTO_BASE_URL`, default `"http://victorsaez.cat"`), mirroring `football_cache_ttl`/`football_day_start_hour` pattern.
- `_send_ranking_with_top3_photos(update, context, text, rows, settings)` private helper in `handlers.py` shared by both commands. cmd_general pre-builds text with footer before passing it.
- `.env.example` updated with commented `# PHOTO_BASE_URL=http://victorsaez.cat` line.
- README documents the photo album behavior and the `PHOTO_BASE_URL` env var.
- **26 new tests** (4 config, 4 url helper, 10 helper, 4 cmd_actual, 4 cmd_general, minus 0 removed). Total: 217 → 243 (all green).
