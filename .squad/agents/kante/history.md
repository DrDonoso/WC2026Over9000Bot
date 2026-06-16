# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-06-16 (Phase 19) — /tongo: 3 new phrases + gender-aware argentino phrase

**Summary:** Added 3 simple phrases to `FRASES` and a new gender-aware phrase "Que tongo ni que tongo, eres mas pesad_ que un_ argentin_" that adapts to the Telegram user's gender (inferred offline from first_name via `gender-guesser`). The dynamic phrase is included in the 2/3 random pool alongside all static phrases. `SANCHEZ_ENS_ROBA` retains its exact 1/3 probability guarantee.

**Key implementations:**
- `pyproject.toml`: Added `gender-guesser>=0.4` to production dependencies.
- `src/worldcup_bot/data/gender.py` (new): `infer_gender(first_name)` using `gender_guesser.detector.Detector(case_sensitive=False)`. Strips non-alpha chars from first token (handles emojis/extra words). Returns `'f'` for female/mostly_female, `'m'` for everything else (male/mostly_male/andy/unknown/None).
- `src/worldcup_bot/data/tongo.py`: Appended 3 new static phrases ("Un conoooooo!! un cono!!!", "Por lo menos no somos italia.", "Ah, pero ChatGPT decia que si."). Added `frase_argentino(gender)` returning female or male variant (default male for unknown gender).
- `src/worldcup_bot/bot/handlers.py`: `cmd_tongo` else-branch expanded: reads `update.effective_user.first_name`, calls `infer_gender`, builds `candidatas = FRASES + [frase_argentino(gender)]`, then `random.choice(candidatas)`. SANCHEZ_ENS_ROBA is NOT in the pool.
- `tests/test_gender.py` (new): 8 tests — Laura→f, Maria→f, David→m, Juan→m, empty→m, None→m, unknown token→m, emoji prefix handled.
- `tests/test_tongo.py`: Extended `_NEW_PHRASES` with 3 new static phrases, updated count test to `>= 16`, added `TestFraseArgentino` class (female/male/unknown/empty variants).
- `tests/test_handlers.py`: Added `test_argentino_female_phrase_for_laura` and `test_argentino_male_phrase_for_david` — verify correct gendered phrase in candidate pool and sent as reply.
- **490 tests passing. Smoke: Laura→f, David→m, fem=expected phrase, count=16. Container rebuilt, State=Up, RestartCount=0, gender_guesser confirmed in image.**



**Summary:** `TELEGRAM_GROUP_ID` is now a required env var enforced by `load_settings()` (raises `RuntimeError` if missing/empty). The `Settings` dataclass field default (`str | None = None`) was intentionally kept so that `Settings(...)` test constructors remain unaffected. `__main__.py` always schedules `poll_goals_job` — the conditional `if settings.telegram_group_id` guard and the `DISABLED` warning branch were removed as dead code. Note: Maldini updated `docker-compose.yml` and `.env.example` in parallel.

**Key implementations:**
- `config.py`: Added group_id check after api_key check; `telegram_group_id=group_id` (no longer `or None`).
- `__main__.py`: Removed `if/else` around `run_repeating`; job is unconditionally scheduled; stale docstring in `poll_goals_job` updated.
- `tests/test_config.py`: All 6 existing `TestLoadSettings` tests patched with `TELEGRAM_GROUP_ID=-100123`. Two new tests: `test_missing_telegram_group_id_raises` and `test_telegram_group_id_reads_from_env`.
- **473 tests passing (+2). Smoke: raises without group id: OK; with group id: -100123.**

### 2026-06-16 (Phase 17) — /simulagol hidden from /start + /tongo probability rework

**Summary:** `/simulagol` removed from the `/start` visible help (command still registered and functional in `__main__.py`). `/tongo` reworked to use explicit 1/3 probability for `SANCHEZ_ENS_ROBA` instead of 25 duplicate list entries; 13 new phrases added to `FRASES`.

**Key implementations:**
- `cmd_start` in `handlers.py`: removed the `/simulagol — (test) …` line from the help string. The command remains registered via `build_app`.
- `tongo.py`: introduced `SANCHEZ_ENS_ROBA = "Sanchez ens roba"` constant; `FRASES` now holds only the 15 original non-Sanchez sarcasm phrases plus 13 new phrases (mix of Spanish/Catalan) = 28 total. No duplicates.
- `cmd_tongo` in `handlers.py`: `if random.random() < 1/3: frase = SANCHEZ_ENS_ROBA else: frase = random.choice(FRASES)`. Exact 1/3 probability, no double-counting.
- New test file `tests/test_tongo.py` (data integrity: Sanchez not in FRASES, all 13 new phrases present, constant value).
- New `TestCmdTongo` class in `test_handlers.py` (Sanchez path at 0.1, FRASES path at 0.9 with mock).
- `TestCmdStart` extended: asserts "simulagol" NOT in help text; asserts "/tongo" and "/hoy" still present.
- **471 tests passing. Smoke: sanchez not in FRASES=True, frases count=28, new phrase present=True. Container rebuilt, State=running, RestartCount=0.**

### 2026-06-16 (Phase 16) — Ver-gol concurrency hardened + file_id cache

**Summary:** `cmd_ver_gol_callback` hardened with a non-blocking in-flight token set (2nd concurrent click answers immediately with a toast — no double download, no 15s Telegram spinner) and a two-level file_id cache so repeat sends skip download/upload entirely.

**Key implementations:**
- `vergol_inflight: set` in `bot_data` (initialised in `build_app`): atomic check-and-add (no await between check and add) prevents concurrent overlap even if future edits introduce awaits between the status check and set. Belt-and-suspenders with the existing `status` field.
- `clip_file_ids: dict[str,str]` in `bot_data` (initialised in `build_app`): maps `media_url → file_id`. Per-goal `info["file_id"]` shortcut for instant re-send of the same goal without even calling `find_goal_clip`.
- Fast path A: if `info["file_id"]` is set, resend via `send_video(video=file_id)` immediately — no Reddit search, no download.
- Fast path B: if `clip_file_ids[media_url]` is set after `find_goal_clip`, resend via cached id — no download.
- Fresh send path: captures `sent_msg.video.file_id` after a real upload and stores in both caches.
- Bad file_id fallback: if a fast-path `send_video` raises, the stale file_id is evicted from both `info` and `clip_file_ids`, `status` reset to `"pending"`, and the exception propagates through the outer handler (user sees the generic error toast and can retry).
- `inflight.discard(token)` always runs in `finally` so the guard is never stuck.
- `build_app` now eagerly initialises `vergol_inflight = set()` and `clip_file_ids = {}`.
- **449 tests passing (6 new). Smoke ok. Container rebuilt, State=running, RestartCount=0.**

### 2026-06-16 (Phase 15) — /simulagol random goal from finished WC fixtures

**Summary:** `/simulagol` now picks a random goal from any FINISHED WC fixture instead of always firing the fixed Sweden-Tunisia Gyökeres 60' goal. Falls back to the fixed goal if no dynamic goal can be found, so the command never fails completely.

**Key implementations:**
- `RedditMatchScanner.find_match_thread(home_name, away_name) -> str | None`: New method that queries Reddit HTML search (`/r/soccer/search?q=...&t=week`) and matches results using the `class="search-title"` link format (NOT the `/new/` listing `data-fullname`/`data-permalink` format which is absent on search pages). Uses `_SEARCH_RESULT_LINK_RE` regex. Filters by `_is_match_thread` + `_teams_match` (both directions). Returns first matching permalink or None.
- `_pick_random_goal(client, scanner, max_candidates=6) -> tuple[GoalEvent, str, str] | None`: Sync helper in handlers.py. Gets FINISHED matches from football-data, shuffles them, tries up to 6 candidates calling `find_match_thread` → `get_thread_body` → `parse_goal_events` → `random.choice`. Aligns TLAs to the API fixture (handles Reddit title home/away reversal). Returns None if no goal found.
- `cmd_simula_gol`: Sends ⏳ message first; runs `_pick_random_goal` via `asyncio.to_thread`; stores result (or fixed fallback) in `bot_data["goal_clips"]` with same shape as `poll_goals_job`. "Ver gol" button flow unchanged.
- **Critical discovery:** Reddit search results page uses `class="search-title"` links (not `data-fullname`/`data-timestamp`/`data-permalink` attributes used by `/r/soccer/new/`). `_parse_html_posts` does NOT work for search; added `_SEARCH_RESULT_LINK_RE` constant for this purpose.
- **443 tests passing (17 new). Live E2E: 3 different random goals from real WC threads (Côte d'Ivoire 1-0 Ecuador: Amad Diallo 90', Saudi Arabia 1-1 Uruguay: Araújo 80', Sweden 2-0 Tunisia: Isak 30').**



### 2026-06-15 (Phase 1–11) — Architecture, Core Porra Features, and Command Surface Refinement (SUMMARIZED)

**Summary:** Complete rewrite from legacy Euro 2024 bot. YAML-driven predictions (hot-reloaded, username-keyed), WC2026 config-driven structure (12 groups A–L, knockout stages). Core commands: `/start`, `/clasificacion`, `/actual`/`/porra` (provisional), `/general` (official, closed-groups-only), `/listaaciertos`/`/listaaciertosactual` (official/provisional detail), `/hoy`/`/ayer` (football-day rolling window 09:00→09:00), `/siguiente`, `/endirecto`, `/participantes`, `/tongo`.

**Key implementations:**
- Shared process-wide `TTLCache` in `FootballDataClient` (fixed HTTP 429 rate limits).
- Official vs provisional split: only finished groups/stages count officially; only started groups provisionally (avoids seeded-standings scoring).
- Football-day rolling window: 24h block anchored at `09:00` local (configurable, DST-safe).
- Photo album feature: top-3 rankings with `participant_photo_url` helper; `PHOTO_BASE_URL` env var.
- Removed `/ronda32`–`/final` + `/resultados` (premature for group stage; documented restore procedure).
- `/clasificacion` accepts optional letter A–L.
- **243 tests passing; local Docker verified; SSL remediation for corporate network.**

### 2026-06-16 (Phases 12–14) — Reddit Live Goal Notifier + "Ver gol" Clip Download (SUMMARIZED)

**Summary:** Implemented Reddit live goal notifier (polls r/soccer Match Threads for new goals, sends Telegram notifications with "Ver gol" button). "Ver gol" button enables full clip download: multi-host downloader (streamff/streamin/streamain + yt-dlp fallback), ffprobe dimension probe (square-video fix), ffmpeg compression for >50 MB files. HTML fallback hardening for datacenter IP JSON 403 blocks.

**Key implementations:**
- `src/worldcup_bot/reddit/` package: `models.py`, `parser.py` (goal extraction), `scanner.py` (thread matching + fetching), `notifier.py` (formatting + keyboard).
- `poll_goals_job` JobQueue task: seeds on first poll to avoid notification spam, silent hours 00:00–08:59 (no waking sleeping users), 60-second polling interval.
- `clip_finder.py`: r/soccer search by team+scoreline+scorer/minute±2, JSON + HTML search fallback.
- `downloader.py`: host-specific CDN resolvers (streamff/streamin) + embed scrapers (streamain) + yt-dlp subprocess fallback (v.redd.it/streamable/dubz/unknown). Async-safe via `asyncio.to_thread`.
- `video.py`: `probe_video` (ffprobe dimensions to fix square-rendering), `compress_if_needed` (two-pass ffmpeg for >50 MB).
- Handler: token-based context (SHA1[:12]), concurrency guards, keyboard removal on success, error handling + temp cleanup.
- Dependencies: `yt-dlp>=2024.0` added; ffmpeg/ffprobe in Docker image.
- **420 tests passing; E2E verified in container: 10/10 clips (Sweden-Tunisia 6, Netherlands-Japan 4, zero failures).**
- **HTML fallback hardening:** `_html_to_goaltext` for goal extraction from HTML (no `data-selftext`), `_parse_search_results_html` for search result structure (`class="search-link"`).

### 2026-06-15 — /actual (provisional) vs /general (official) split + /porra alias (DETAILED)

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

### 2026-06-15T17:24+02:00 — Provisional group scoring gated to started groups

**Bug fixed:** `/listaaciertosactual`, `/actual`, `/porra` were awarding group aciertos for groups that hadn't played a single match yet. football-data.org returns a seeded standings table (0 played, meaningless order) for not-yet-started groups, so provisional scoring was incorrectly counting those positions.

**Fix:** Provisional mode now gates group scoring to "started" groups (≥1 FINISHED match), mirroring how official mode gates to "finished" groups (all matches FINISHED).

**Key details:**
- `client.get_started_groups()` added (mirrors `get_finished_groups`; uses `any(x.status == "FINISHED")` instead of `all`). Same TTL-cached `get_all_matches()` call → no extra HTTP request.
- `compute_general_ranking(official=False)` now calls `get_started_groups()` and passes result as `only_groups` to `_build_actual_standings`. Groups not started fall through `score_groups`' `no_data` branch → 0 pts / ⏳.
- `compute_user_detail(official=False)` does the same; returns new key `"started_groups": len(started_groups)`. Official mode returns `"started_groups": None`. `"finished_groups"` key unchanged.
- `format_user_detail` provisional footer now shows `"📋 Grupos en juego: N/12 — los grupos sin empezar aún no puntúan."` when `started_groups < total_groups`.
- Official path unchanged. Knockout scoring unchanged in both modes.
- **New tests:** `TestGetStartedGroups` (7 tests in `test_api_client.py`), new provisional tests in `TestComputeGeneralRankingProvisional` (3 new) and `TestComputeUserDetailProvisional` (4 new), `TestFormatUserDetailProvisionalFooter` (5 tests in `test_handlers.py`). Total: 243 → 261 (all green).


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

### 2026-06-16T08:45+02:00 — Reddit Live Goal Notifier

**Implemented as user-approved design:**

- **New package `src/worldcup_bot/reddit/`** with four modules:
  - `models.py`: `GoalEvent`, `ThreadInfo`, `MatchThreadResult` dataclasses.
  - `parser.py`: `parse_goal_events(selftext, post_id) -> list[GoalEvent]` — regex-based extraction of goal events from r/soccer Match Thread selftexts (MATCH EVENTS | via ESPN section). Handles: goals, own goals (scoring_team inverted), disallowed/VAR/penalty-missed lines (skipped), cards/subs (skipped). `compute_new_goals(thread_id, events, notified_set, seeded_set)` — pure dedup function.
  - `scanner.py`: `RedditMatchScanner` class — fetches old.reddit.com JSON search (browser UA + `Cookie: over18=1`), falls back to HTML scraping on 403; matches threads to football-data live fixtures via fuzzy team-name matching (accent-insensitive, alias map for WC teams); fetches each thread body (JSON → HTML fallback); parses goals. Accepts injected `requests.Session` for testability.
  - `notifier.py`: `format_goal_notification(event, home_tla, away_tla)` — r/soccer bracket convention for scoring side; `_is_silent_hour(now_local)` — returns True for hours [00:00, 09:00) local; `build_goal_keyboard()` — "Ver gol" placeholder InlineKeyboardMarkup with `callback_data="vergol:noop"`.

- **`config.py`** gained `goal_poll_interval_seconds: int = 60` (env `GOAL_POLL_INTERVAL_SECONDS`) and `reddit_user_agent: str` (env `REDDIT_USER_AGENT`, default Chrome 131 UA).

- **`pyproject.toml`** changed `python-telegram-bot>=21` → `python-telegram-bot[job-queue]>=21,<22` to enable APScheduler-backed `JobQueue`. **Maldini must rebuild the Docker image** after this change.

- **`__main__.py`** redesigned:
  - `build_app()` initialises `bot_data["notified_goal_keys"]` (set), `bot_data["seeded_threads"]` (set), `bot_data["reddit_scanner"]` (None, lazily init in job).
  - `poll_goals_job(context)` — async PTB JobQueue job: gets live matches from football-data, scans Reddit threads, calls `compute_new_goals` per thread (seed-on-first-poll dedup), sends Telegram notifications with goal keyboard. Per-goal send errors are caught and logged. Whole job body wrapped in try/except to survive any failure.
  - `_noop_vergol_callback` — answers "Ver gol" button presses with "🔜 Próximamente" toast.
  - `CallbackQueryHandler` registered for `r"^vergol:"`.
  - Job is scheduled only when `settings.telegram_group_id` is set; otherwise a WARNING is logged (feature is gracefully disabled).

- **Seed-on-first-poll dedup**: on the first time a thread is polled, all existing goal keys are added to the notified set WITHOUT sending notifications — prevents spamming goals that pre-dated the bot's startup.

- **Night silent window** 00:00–08:59 local (Madrid TZ): sends with `disable_notification=True` so users sleeping through US-time matches are not woken up.

- **Tests** (335 total, all green; +79 new):
  - `tests/test_reddit_parser.py` (31): parse, dedup, ordering, disallowed, own goal, key stability.
  - `tests/test_reddit_scanner.py` (32): `_is_match_thread`, `_parse_thread_teams`, team fuzzy match, JSON path, HTML fallback path.
  - `tests/test_reddit_notifier.py` (16): bracket side, scorer/minute text, silent hour, keyboard shape.

### 2026-06-16T09:45+02:00 — "Ver gol" inline button: clip finder, multi-host downloader, ffprobe fix

**Implemented as user-approved design:**

- **`clip_finder.py`**: `find_goal_clip(scanner, home_team, away_team, home_score, away_score, scorer, minute) -> str | None`. Searches r/soccer via JSON search (q=`home away`, restrict_sr, sort=new, t=day) or HTML fallback. Parses each post title with `GOAL_TITLE_PATTERN` (ported from RedditSoccerGoals). Matches by: teams fuzzy (reuses `_teams_match`/`_normalize_team` from scanner.py), exact scoreline, AND scorer-fuzzy OR minute ±2. Returns the first matching post's external URL (streamff/streamin/streamable/etc). Synchronous — callers use `asyncio.to_thread`.

- **`downloader.py`**: `MediaDownloader` class. Host-specific resolvers: `_download_streamff` (CDN id → `cdn.streamff.one/{id}.mp4`, else page scrape), `_download_streamin` (CDN id → `c-cdn.streamin.top/uploads/{id}.mp4`, else embed scrape), `_download_streamain` (embed scrape → cdn.streamain.com mp4). yt-dlp subprocess fallback (`asyncio.create_subprocess_exec`) for v.redd.it, streamable.com, dubz.link, and anything else. Uses `requests` (sync) in `asyncio.to_thread` for HTTP downloads. Writes to system temp dir (`tempfile.gettempdir()`).

- **`video.py`**: `probe_video(path) -> dict` (ffprobe → `{width, height, duration}`). `compress_if_needed(path) -> Path` (returns original if ≤50 MB; re-encodes with ffmpeg two-pass bitrate budget otherwise; raises `VideoTooLargeError` on failure). Passing `width`/`height` to `bot.send_video` prevents Telegram from rendering the video square.

- **`notifier.py`**: `build_goal_keyboard(token: str)` now accepts a 12-hex-char token → `callback_data=f"vergol:{token}"`. Token = `hashlib.sha1(event.key)[:12]`.

- **`handlers.py`**: `cmd_ver_gol_callback` handles the full flow: look up token in `bot_data["goal_clips"]`; concurrency guard (status "sending"/"sent"); `find_goal_clip` via `asyncio.to_thread`; `MediaDownloader.download`; `compress_if_needed`; `probe_video`; `bot.send_video(**meta)`; `query.edit_message_reply_markup(None)` to remove keyboard. All temp files cleaned up in `finally`. `_goal_token(key)` helper exported.

- **`__main__.py`**: `poll_goals_job` now computes token, stores `goal_clips[token]` with goal context before sending. `build_app` initialises `bot_data["goal_clips"] = {}`. `CallbackQueryHandler` now registers `cmd_ver_gol_callback` (real handler) replacing the old no-op.

- **`pyproject.toml`**: added `yt-dlp>=2024.0` — needed for the yt-dlp fallback.

- **Design decisions**: goal_clips is in-memory (lost on restart — acceptable v1); token is sha1(key)[:12] which fits the 64-byte callback_data limit with room to spare; keyboard is removed only on success (kept on failure so user can retry).

- **Tests** (407 total, all green; +72 new):
  - `tests/test_clip_finder.py`: GOAL_TITLE_PATTERN, _extract_media_url, _scorer_matches, _match_post (7 cases), find_goal_clip (6 cases incl. ±2 minute tolerance + Holland/Netherlands fuzzy match + HTML fallback), _parse_clip_posts_html.
  - `tests/test_downloader.py`: _find_downloaded_file, _download_streamff (CDN + scrape + failure), _download_streamin (CDN + embed), _download_streamain (embed scrape + no slug), yt-dlp fallback (success + failure + not found + routing).
  - `tests/test_video.py`: probe_video (full, nonzero rc, exception, partial, format fallback), compress_if_needed (small=passthrough, large=compress, no duration, too long, ffmpeg fail, ffmpeg missing).
  - `tests/test_handlers.py`: TestGoalToken (3), TestCmdVerGolCallback (unknown token, sending guard, sent guard, clip not found, download failure, happy path with width/height meta, reply_to_message_id).

### 2026-06-16T10:05+02:00 — Reddit HTML fallback hardened (JSON 403 from datacenter IPs)

**Diagnosis confirmed inside container:**
- `old.reddit.com/.../.json` → **HTTP 403** (blocked from datacenter/corporate IPs).
- `old.reddit.com/r/soccer/search.json?...` → **HTTP 403** (blocked).
- Thread HTML (200) has **NO `data-selftext`** attribute. Post body rendered as `<p><strong>7&#39;</strong> ⚽ <strong>Goal! Sweden 1, Tunisia 0. ...</strong></p>`.
- Old `_MD_DIV_RE` (non-greedy `.*?`) stopped at first `</div>` → 1363 chars → 0 goals parsed.
- Search results HTML (`/r/soccer/search?q=...`) returns 200 but uses a completely different structure from `/new/` listing: external clip URL is in footer `<a class="search-link" href="https://streamin.link/v/...">`, NOT a `data-url` attribute.

**FIX 1 — `get_thread_body` HTML fallback (`scanner.py`):**
- Removed broken `_MD_DIV_RE`.
- Added `_html_to_goaltext(html)`: replaces `<strong>`/`</strong>`/`<b>`/`</b>` → `**`, `</p>`/`<br>`/`</tr>`/`</li>` → `\n`, strips remaining tags, `html.unescape()`, collapses 3+ newlines.
- Updated `_fetch_thread_body_html`: try `data-selftext` first (legacy), then cut HTML at `<div class="commentarea"` (excludes comment-section Goals), then apply `_html_to_goaltext`. Yields `**7'** ⚽ **Goal! Sweden 1, Tunisia 0. Scorer (Team)...**` which parse_goal_events handles.

**FIX 2 — `find_goal_clip` HTML search fallback (`clip_finder.py`):**
- Added `_REDDIT_SEARCH_HTML` constant (`/r/soccer/search?q=...&restrict_sr=on&sort=new&include_over_18=on`).
- Added `_parse_search_results_html(html)`: parses search results structure using `class="search-title"` (title) and `class="search-link"` (external media URL). Skips blocks without `search-title` to avoid false positives on listing-format HTML.
- Added `_fetch_html_search_posts(scanner, home, away)` using the new parser.
- Updated `find_goal_clip` fallback chain: (1) JSON search, (2) HTML search by teams, (3) `/new/` HTML listing.

**Tests (+13 new, 420 total, all green):**
- `test_reddit_scanner.py`: `TestScannerThreadBodyHtmlFallback` (3): JSON 403 → HTML → 4 goals extracted, comment-section goals excluded, minutes correct. `TestHtmlToGoaltext` (4): strong→**, paragraph→newline, entity unescape, br→newline.
- `test_clip_finder.py`: `TestParseSearchResultsHtml` (3): title+link extraction, skip non-search format, self-post fallback. `TestFindGoalClipHtmlSearch` (3): JSON 403 → HTML search correct clip, decoy not returned, falls through to /new/ when search empty.

**E2E inside container (RESUMEN: 10 OK | 0 fallos | 0 sin clip):**
- Sweden vs Tunisia (1u62p01): 6 goals parsed from HTML; 6 clips downloaded (streamin.link, 1920×1080, 17–20 MB each).
- Netherlands vs Japan (1u5uc8w): 4 goals parsed; 4 clips downloaded (streamin.link + streamff.link, 1536×864/1920×1080).

### 2026-06-16T10:48+02:00 — /simulagol test command for end-to-end "Ver gol" testing

Added `/simulagol` — a utility command that fires a **real goal notification** (Sweden 3-1 Tunisia, Viktor Gyökeres 60') with full goal context stored in `bot_data["goal_clips"]`, so the "Ver gol" inline button works end-to-end without any live WC matches.

**Key details:**
- `cmd_simula_gol` in `handlers.py`: builds a `GoalEvent` with the Sweden-Tunisia fixed data, computes `token = _goal_token("SIM:sweden-tunisia-3-1-60-gyokeres")`, stores the EXACT dict shape used by `poll_goals_job` (home_team, away_team, home_score, away_score, scorer, minute_text, scoring_team, home_tla, away_tla, status="pending"), then calls `format_goal_notification` + `build_goal_keyboard` and replies with a `[SIMULACIÓN]`-prefixed message.
- `__main__.py`: added `CommandHandler("simulagol", cmd_simula_gol)` and import.
- `/start` help text updated with `/simulagol — (test) simula un gol para probar el botón Ver gol`.
- **Imports added to handlers.py**: `GoalEvent` from `reddit.models`; `build_goal_keyboard`, `format_goal_notification` from `reddit.notifier` (previously used only in `__main__.py`).
- **No admin restriction** — harmless test; can be made admin-only or removed once live testing is complete.
- **6 new tests** in `TestCmdSimulaGol` (`test_handlers.py`): shape verification, reply_text called once with keyboard, token matches `_goal_token(key)`, initialises `goal_clips` when absent, reply contains SIMULACIÓN marker, `simulagol` registered in app. **426 tests total, all green.**
- Container rebuilt + restarted; `State=running RestartCount=0`, `container has simulagol` confirmed.
