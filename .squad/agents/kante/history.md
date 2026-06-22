# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot  
**Stack:** Python, python-telegram-bot, football-data.org, Reddit scanner, LLM  
**Test count:** 1463 (as of 2026-06-19, per-user /tongo feature)

## Current Session: 2026-06-19 — Per-User /tongo Config

**Feature:** DrDonoso wanted `/tongo` behavior to vary per user (custom sanchez_ratio, custom phrase pool).

**Delivered:**
- `data/TongoUsers.yml` — YAML config file (committed, empty/commented by default, loads to `{}` = zero behavior change until opt-in)
- `TongoUserConfig` dataclass + `load_tongo_users(mtime cache)` in `tongo.py`
- `read_tongo_phrase_file(path-keyed mtime cache)` to support per-user phrase files
- `choose_tongo_response(pure, injectable rng)` extracted from handler
- `cmd_tongo` rewritten to compose effective_phrases + sanchez_ratio, then delegate selection
- 55 new tests; all existing tests green (1408 → 1463)

**Key design decisions:**
- Committed (not git-ignored) to version-control user configs
- Backward compatible: unconfigured users get exact original behavior (1/3 SANCHEZ, global pool)
- Effective phrases: per-user + global (append mode, default), or per-user only (replace mode, with fallback to global if empty)
- Path-keyed cache dict avoids thrash when alternating per-user file paths
- `rng=random` kwarg pattern lets existing handler tests (patching `worldcup_bot.bot.handlers.random`) control behavior without changes

**E2E verified:** Coordinator ran real Telegram tests (sanchez_ratio 1.0, 0.0, phrases_mode=replace, default user) — all 4 cases passed. Committed to origin/main (7ffaeb9).

## Past Sessions Summary

**Archived to history-archive.md:** Phases 1–29 (Goal detection, live-match infrastructure, rich images, LLM scoring, `/endirecto` redesign, Czechia alias fix, Reddit 429 fix, /tongo templated phrases). 1463 tests total. All design constraints preserved (module decoupling, shared TTLCache, injectable test patterns).

## Learnings

### 2026-06-19 — Merged single-YAML /tongo schema

**Schema change:** `data/TongoPhrases.txt` (plain-text global phrases) + `data/TongoUsers.yml`
(flat username → config mapping) merged into ONE YAML `data/TongoUsers.yml` with:

```yaml
phrases:                  # global pool (replaces TongoPhrases.txt)
  - "Frase {{first_name}}"
users:                    # per-user overrides (keyed by @username lowercase)
  algun_usuario:
    sanchez_ratio: 0.66   # optional, 0..1 (absent = 1/3 global)
    phrases_mode: append  # "append" (default) or "replace"
    phrases:              # optional inline phrases
      - "{{first_name}}, ..."
```

**Removed from `tongo.py`:**
- `load_tongo_phrases` + txt-based hot-reload cache (`_cached_path`, `_cached_mtime`, `_cached_data`)
- `read_tongo_phrase_file` + path-keyed cache (`_phrase_file_cache`)
- `phrases_file` field from `TongoUserConfig`
- `load_tongo_users` (merged into the new loader)

**Added to `tongo.py`:**
- `TongoConfig` dataclass: `phrases: list[str]`, `users: dict[str, TongoUserConfig]`
- `load_tongo_config(path)`: single-file YAML loader with mtime hot-reload, mirrors
  `porra/predictions.py` cache pattern. Graceful validation (never raises, logs warnings).

**Removed from `config.py`:** `tongo_phrases_path` field + `TONGO_PHRASES_PATH` env var.
`tongo_users_path` / `TONGO_USERS_PATH` now points to the merged file.

**Data file layout:**
- `data/TongoUsers.template.yml` — committed template (Spanish comments, 16 default phrases,
  2 commented fake user examples)
- `data/predictions.template.yml` — committed template for predictions.yml (fake data)
- `data/TongoUsers.yml` — git-ignored runtime file (migrated 22 phrases from TongoPhrases.txt,
  12 participant keys as commented blocks)

**Test count:** 1463 → 1452 (removed txt-loader and file-reader tests; replaced with 26
`TestLoadTongoConfig` tests covering merged schema validation).

### 2026-06-22 — Corrected group-stage scoring rule + /recalcular

**Scoring fix:** The original `score_groups` rule gave 0.5 to any team that
qualified to the top-3 at the wrong position — including two teams that simply
swapped within the top-2 direct-qualifying zone (e.g. pred=1/actual=2).  The
correct rule is:

- `pred ∈ {1,2} AND actual ∈ {1,2}` → **1.0** ("exacto") — order within top-2 is irrelevant
- `pred == actual == 3`              → **1.0** ("exacto") — exact 3rd
- One in top-2, other is 3rd        → **0.5** ("clasifica") — boundary near-miss
- Otherwise (actual ≥ 4)            → **0.0** ("fallo")

Implemented via `DIRECT_QUALIFY = 2` constant in `scoring.py` (separate from
`QUALIFY_PER_GROUP = 3` which counts picks-per-group and is unchanged).

**`ensure_history` force-rebuild:** Added `force: bool = False` parameter.
When `force=True` the function ignores the on-disk history and recomputes
every jornada from scratch — safe anytime, costs one `get_all_matches()` call.
The history is fully reconstructable from match results; no date-parameterised
API calls are needed.

**`/recalcular` hidden admin command:** Calls `ensure_history(…, force=True)`,
mirrors the visibility pattern of `/updatediario` (registered in `__main__.py`,
not exposed in `/start` help, not in BotFather menu).  Replies with jornada
count and a reminder that `/evolucion` reflects the new scoring.

**Test count:** 1452 → 1480 (28 new tests across test_scoring, test_history, test_evolucion_handler).


### 2026-06-22 — Four live goal-notification bugs fixed (production incident)

**Bug 1 — Duplicate goal (Spain 5-0 sent twice, ~8:03 PM):**
Root cause: `poll_goals_job` (API, ~60 s) and `poll_thread_goals_job` (thread, 25 s)
both shared `context.bot_data["live_scores"]` as the single "announced" score, but
each updated `scores[key]` AFTER the slow `await` (Reddit + OpenAI / Telegram send).
The PTB JobQueue schedules jobs concurrently; while one job awaited, the other read
the stale announced (4-0), reconciled new=5-0, and announced again → duplicate.

Fix: `goal_lock = context.bot_data.setdefault("goal_lock", asyncio.Lock())` shared by
both jobs.  Inside the lock: read announced → reconcile → IMMEDIATELY write `scores[key]`
= new_ann.  Then release the lock and do the slow send outside it.  A concurrent job
that acquires the lock next sees the updated announced and reconcile returns no delta.

**Bug 2 — Goal sent with no scorer and no "Ver gol" button (Spain 4-0, ~7:19 PM):**
Root cause: API detected 4-0 before the thread; `_enrich_scorer` returned (None, None)
(thread not ready / 429 / OpenAI miss).  A clip-store entry with scorer=None was
created; the clip finder needs a scorer to match the video title, so the button never
appeared.  Later the thread saw 4-0 but reconcile returned no delta → scorer never
applied.

Fix: `_backfill_scorer_in_clip_store(match, events, settings, context)` — called in
`poll_thread_goals_job` for every processed match (even when `not deltas`).  For each
thread event with a known scorer, it finds clip-store entries with scorer=None at that
match+score, edits the original Telegram message to add the `🎯 scorer (min')` line,
and sets the scorer in the entry so the clip search can proceed.  Idempotent (guarded
by `entry["scorer"] is not None`).

**Bug 3 — Wrong score in disallowed message (Spain 3-0 shown, actual post-VAR was 4-0, ~8:00 PM):**
Root cause: `format_disallowed_message` was fed `delta.new_home/new_away` from the
thread's current (dropped) read.  The thread momentarily under-read 3-0 (missed event
4) after goal 5 was VAR'd from an announced score of 5-0.  `reconcile` saw seen=5 →
new=3, emitted a disallowed with new_home=3 → message said "3-0".  Worse, announced
was also updated to 3-0, so the API next tick would re-announce goal 4 as new.

Fix: After reconcile, for each disallowed delta in the thread job, clamp:
`d.new_X = max(d.new_X, ann_homeaway[X] - 1)` for the dropping side; and
`new_ann[X] = clamped`.  A single VAR can only reverse one goal per side; the
authoritative post-VAR score is always announced−1 on the affected side.  A correctly-
read drop (e.g. thread reads 4-0 after goal 5 VAR'd from 5-0) is unchanged:
`max(4, 5-1) = 4`.

**Bug 4 — Missing goals (NZ–EGY goals dropped at ~4:30 AM):**
Root cause: the cross-job race (Bug 1) — one job updating announced past an intermediate
goal while the other had already read the stale announced.  The multi-goal per-target
expansion in `poll_thread_goals_job` (ranges from ann+1 to new_ann) already generates
one notification per intermediate score; this is correct.  The API path also generates
N deltas for an N-goal jump (though all show the final score, no goals are dropped).
Silent-hour sets disable_notification=True (goals still sent) — expected behavior.

Fix: Bug 1's lock covers Bug 4.  After the lock, the API job reads the already-claimed
announced and reconcile returns no delta, so no intermediate goals are skipped.
Confirmed with regression test: thread announces 1-1, 1-2, 1-3 in one tick; subsequent
API call at 1-3 sends 0 extra messages.

**Test count:** 1480 → 1489 (9 new regression tests in `test_poll_thread_goals_job.py`:
TestCrossJobRace×2, TestScorerBackfill×3, TestDisallowedAuthoritativeScore×2,
TestMultiGoalExpansion×2).


### 2026-06-22 — Backfill must re-attach Ver gol keyboard when clip is ready

`editMessageText` without `reply_markup` **silently removes the inline keyboard** from
the existing message (PTB omits `None` kwargs → field absent → Telegram clears it).
`_backfill_scorer_in_clip_store` was doing exactly this after the clip job had already
attached the "Ver gol" button.  Fix: check `entry.get("status") == "ready"` and pass
`reply_markup=build_goal_keyboard(tok)` in that case; otherwise `reply_markup=None`.
`build_goal_keyboard` was already imported.  Two regression tests added:
keyboard preserved (ready) and keyboard absent (searching).
**Test count:** 1489 → 1491.


### 2026-06-22 — TVE (RTVE) broadcast markers 📺

**Feature:** `/hoy`, `/siguiente`, and the daily AI update now show a 📺 emoji
next to World Cup fixtures that are broadcast on Spanish public TV (La 1 / Teledeporte).

**RTVE schedule API (no auth; verified working):**
- Endpoint: `https://www.rtve.es/api/schedule/{slug}.json`
  (`api.rtve.es` is dead/404 — use `www.rtve.es/api/schedule`)
- Channel slugs used: `tv1` (La 1) and `dep` (Teledeporte).
- Response: `{ "items": [ {item}, ... ] }`. Each item has `idPrograma`, `name`,
  `original_episode_name`, `original_event_name`, `begintime` (YYYYMMDDHHMMSS,
  Europe/Madrid local), and `description` (for La 1, contains "(HH:MM)" = actual kickoff).
- **WC filter:** `idPrograma == 1030562` AND "resumen" NOT in name/episode fields
  (case-insensitive) → excludes highlight/replay shows.
- **Current-week only:** the API returns ~10 days; fixtures further out won't have 📺 yet.
- **Madrid local times, DST-correct:** La 1 description provides the real kickoff as
  `(HH:MM)` (Madrid local); Teledeporte uses `begintime` directly. Both are localized
  with `pytz.timezone("Europe/Madrid").localize(...)` — never hardcode a UTC offset.
  June = CEST = UTC+2; winter = CET = UTC+1.

**ES→TLA mapping and time matching (`src/worldcup_bot/tve.py`):**
- `ES_NAME_TO_TLA` dict keys are accent-stripped lowercase (`_norm` helper via
  `unicodedata.normalize("NFKD", ...)`), so "Túnez"/"Tunez"/"TUNEZ" all map to TUN.
- `tve_channel_for(match, broadcasts)`: primary match = kickoff within ±20 min +
  unordered TLA pair. Time-only fallback (when TLAs are None) only when exactly one
  broadcast is in the time window (prevents mismatching simultaneous games).
  La 1 beats Teledeporte on tie.

**Graceful degrade rule (hard constraint):**
- A flaky/unreachable RTVE API must NEVER break `/hoy`, `/siguiente`, or the daily AI
  update. All three use `try/except` around `asyncio.to_thread(load_tve_broadcasts, ...)`
  and fall back to `[]` (no 📺) on any error.
- `load_tve_broadcasts` itself catches all per-channel fetch errors, caches `[]` on
  total failure, and respects a 6-hour TTL cache (module-level).
- Toggle with `TVE_ENABLED=false` in `.env` (Maldini wires it; Kanté reads it).

**Module:** `src/worldcup_bot/tve.py` (new). Changes to `config.py` (`tve_enabled`
field + `_parse_bool`), `formatters.py` (`tve_label` kwarg in `format_match` /
`format_match_with_date`), `handlers.py` (`cmd_hoy`, `cmd_siguiente`),
`daily_update.py` (`build_ai_user_message` + `tve_by_key` + `generate_daily_update`).
**Test count:** 1491 → 1545 (54 new tests in `tests/test_tve.py`).

