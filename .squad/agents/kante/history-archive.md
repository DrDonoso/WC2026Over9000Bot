# Kante History Archive

**Archive date:** 2026-06-17  
**Purpose:** Preserve key learnings from Phases 1–25 for future reference  

## Condensed Key Learnings (Phases 1–25)

### Block 1: Goal Detection Architecture (2026-06-17)

**Root cause:** Reddit match threads use human-narrated format (`66': [](#icon-ball-big)**GOAL FRANCE!!**`) not ESPN-structured lines. Old `parse_goal_events` found 0 goals. Re-parsing also caused VAR flip-flops (score 1-0 → 1-1 → 1-0).

**Fix:** Use football-data score changes as authoritative source; enrich with LLM scorer/minute extraction. Persistent `live_scores.json` prevents flip-flops. `extract_scorer` handles any thread format via natural-language LLM processing.

**Files:** `src/worldcup_bot/reddit/score_state.py`, `src/worldcup_bot/ai/goal_extractor.py`, rewrote `__main__.py::poll_goals_job`.

### LiteLLM/OpenAI Token Parameter Fix (2026-06-16)

**Problem:** User's LiteLLM backend ignores/clamps legacy `max_tokens` to 100 tokens (`finish_reason="length"`). Switching to `max_completion_tokens=1500` yields full natural responses (`finish_reason="stop"`).

**Rule for future:** Always use `max_completion_tokens` (not `max_tokens`) for every `chat.completions.create` call via `AIClient.complete`. Never send both params — some backends error on duplicates.

### Football-day Rolling Window Pattern (9am→9am, configurable)

The same 9am→9am window is used consistently across:
- `get_football_day_matches` (live command matching)
- `football_day_of(match, tz, anchor_hour)` (history jornada labeling)
- Config: `settings.football_day_start_hour` (env `FOOTBALL_DAY_START_HOUR`, default 9)

Handles UTC/local boundary: a 02:00 local match on June 14 belongs to June 13's matchday for a 9am Madrid viewer.

### Persistent State Volume Ownership (Dockerfile fix)

Docker named volumes inherit directory ownership from the **image state** at the mount path. Must create and chown directories in Dockerfile BEFORE the `USER app` directive, so volumes inherit app user ownership on first creation.

**Fix:** Extended Dockerfile RUN to create both `/app/data` and `/app/state` with `chown app:app`.

### Porra Evolution: Jornada-keyed Reconstruction

`porra/history.py` reconstructs standings from match results (not API `?date=` calls) because consecutive football-days can share UTC calendar dates, breaking `?date=` semantics. 

**Key functions:** `football_day_of`, `build_jornadas`, `reconstruct_group_standings` (W=3/D=1/L=0, GD, GF, TLA tie-break), `compute_ranking_at_jornada`.

**Hybrid approach:** Past jornadas use reconstruction (acceptable for trend). Latest jornada uses exact live ranking `engine.compute_general_ranking(predictions, client, official=False)` to avoid tie-break mismatch at chart tip.

### Changelog from Commit-Body Bullets

Python heredoc in `.github/workflows/docker-deploy.yml` preserves body bullets from squash commits, not just commit subjects. Parses indent-based bullet continuation, excludes trailers, falls back to subject-only when no bullets exist.

### Daily AI Update: Always Use HTML parse_mode

All participant names rendered in `<b>…</b>` HTML; all team names bold; AI-provided text HTML-escaped. Helper: `bold_person_names(text, names)` — longest-name-first regex, single pass, handles Unicode word boundaries.

### Design Constraints to Preserve

1. **Module decoupling:** `api/client.py` ← config + cache; never imports bot/ or porra/. `porra/scoring.py` pure functions. `porra/engine.py` orchestrates scoring but no I/O.
2. **Shared TTLCache singleton:** Fixes HTTP 429 rate limit. Lazily initialised in `api/cache.py`, injected into each `FootballDataClient`.
3. **Goal tokens:** SHA1[:12] hex — 12 bytes fits in 64-byte callback data limit.
4. **Non-blocking in-flight guard:** Set of tokens in bot_data prevents multiple concurrent downloads. Status field is belt-and-suspenders.
5. **Two-level file_id cache:** Per-goal shortcut + per-media-url cache layer. Stale file_id evicted on TelegramError, falls through to fresh disk send.

## Test Count History

- Phase 1–5 (Arch + Infra): 156 tests
- Phase 15 (Ver gol E2E): 426 tests
- Phase 20 (OpenAI daily): 538 tests
- Phase 23–25 (Finished match round): 702–733 tests
- Block 1–4 (Goal detection to stats): 836–882 tests
- Porra evolution (jornada + startup backfill): **962 tests**

---

## Rich-Image Feature — Session 2026-06-17

**Archived:** 2026-06-17 from 58534 bytes (537 lines)  
**Final state:** 1135 tests green

Over 2026-06-15 and 2026-06-17, completed rich-image feature with 6 major refinements:

1. **Model-Driven Escalation** — Removed hardcoded `_ESCALATION_CLAUSES`. Richness evolves implicitly: each iteration receives current image + instruction to add FEW new touches (pose, hands, entourage, vehicles, settings). Bounded history (30 memos) + captions (6 recent).

2. **Hybrid Multi-Image Face-Anchor** — Run 2+ passes `[evolved, original]` pair to gpt-image-2. Face anchored to original while inventing new clothing/pose/scene. Single-image fallback if original missing.

3. **Azure Moderation Compliance** — Reframed to positive-dressing language ("dress in fully-clothed luxury outfit"). Never "change/remove/alter clothing" in image prompts. Safe framing verified live.

4. **Caption Normalization & Variety** — Fixed literal `\n` via `_normalize_caption()`. Removed `" / "` separators from stored examples (model was imitating them). Explicit instruction: line breaks, never slashes. 6-caption bounded store.

5. **Rich Emphasis & Accessories** — Escalation now PRIMARY critical ask in prompt. Optional accessories (sunglasses/hat) occasionally added, never every time.

6. **JSON Caption Extraction** — Model returns JSON `{"caption": "...", "memo": "..."}`. Fallback to raw text on failure.

**Decisions linked:** kante-24, kante-25 (anchor), kante-26 (moderation), kante-27 (newline+richer), kante-29 (no-slashes)  
**Key files:** `src/worldcup_bot/ai/rich_image.py`, `tests/test_rich_image.py`  
**Final commit:** a8c773a on origin/main

---

## Session 2026-06-17: Streamff Mirrors + Thread-Based Goals + /endirecto Redesign + Clip Scorer (kante-32–36)

6 major implementations completing live-match infrastructure. 1267 tests green.

**Key changes:**
- Streamff CDN mirror fix (any TLD via `cdn.streamff.one/{id}`)
- Thread-based goal detection (race-free dedup via shared `bot_data` dict)
- /endirecto live detail enrichment (Reddit MATCH EVENTS → JSON LLM extraction)
- Clip finder merge (HTML search + /new/, deduplicated)
- Robust clip scorer (accent folding + noise filtering)
- /endirecto inline buttons (persistent JSON store, fixed render order)

**Tests:** 1135 → 1267 (+132)

**Key learnings:**
- streamff CDN is TLD-agnostic; video IDs are consistent
- Race-free dedup requires shared dict, not per-job disk loads
- football-data free tier lacks detail arrays; Reddit MATCH EVENTS section is highly parseable
- r/soccer HTML search index lags by minutes
- Accent folding + noise filtering required for robust natural-name matching

---

## Session 2026-06-18: Czechia Team Alias Fix (live bug, clip-finder)

**Problem:** "Ver gol" never appeared for Czechia 1-0 South Africa (Sadílek 6'). Clip existed but `_teams_match("Czech Republic", "Czechia")` was False.

**Fix:** Added `WC_TEAM_ALIASES` entries for Czech Republic ↔ Czechia (+ variants). Same class of bug as D.R. Congo ↔ Congo DR.

**Tests:** +7

**Key learning:** r/soccer + ESPN clip titles use old names while football-data normalizes to new names. Requires explicit alias rather than fuzzy matching.

---

## Session 2026-06-18: /endirecto 429 Fix — Shared Scanner + TTL Cache (kante-endirecto-429)

**Problem diagnosed live:** `/endirecto` showed no inline keyboard in prod. Each call created fresh `RedditMatchScanner` → hit Reddit cold → 429 (Too Many Requests) → returned None → fell back to plain format_match (score only).

**Solution:** Three changes:
1. **Scanner TTL caches** (30s match threads, 90s per-thread body). Never raises; returns stale cache on exception.
2. **New `find_thread_permalink` method** scanning cached `/new/` listing (less 429-prone than /search).
3. **Shared scanner in bot_data.** `/endirecto` reuses warm cache from goal poller (25s ticks).

**Tests:** +21

**Key learnings:**
- Reddit rate-limits datacenter IPs aggressively; two independent callers ≈ 429
- `/new/` listing is more reliable than `/search`; already cached by goal poller
- Shared instance + per-instance TTL caches fix the problem; no external store needed

---

## Session 2026-06-19: /tongo Per-User Config (kante-tongo-per-user)

**Design:** Committed `data/TongoUsers.yml` (empty/commented by default), keyed by lowercased username. Per-user settings: `sanchez_ratio` override, `phrases_mode` (append/replace), `phrases` (inline) or `phrases_file`.

**Implementation:**
- `TongoUserConfig` dataclass in `tongo.py`
- `load_tongo_users` (mtime hot-reload, graceful degradation, per-field validation)
- `read_tongo_phrase_file` (path-keyed mtime cache to avoid thrash when alternating per-user files)
- `choose_tongo_response` pure function (injectable `rng` for testability)
- Effective phrases composition: per-user + global (append), or per-user only (replace), with fallback to global if replace is empty

**Files:** `data/TongoUsers.yml` (NEW), `tongo.py` (+TongoUserConfig, loaders, pure fn), `config.py` (+TONGO_USERS_PATH), `handlers.py` (rewritten cmd_tongo), `test_tongo_users.py` (NEW, 55 tests)

**Tests:** 1408 → 1463 (+55)

**Key learnings:**
- `rng=random` kwarg pattern: pure selector passes the random module as an explicit kwarg, so existing handler tests (patching `worldcup_bot.bot.handlers.random`) control behavior without changes
- Path-keyed cache dict avoids thrash when per-user files have alternating paths
- GIF fallback inside `except` avoids consuming `side_effect` slots in tests that don't hit error path
- Empty/commented YAML ships as `{}` → zero behavioral change on first deploy

Backward compatibility preserved: unconfigured users get exact original behavior (1/3 SANCHEZ, global pool).

---

## Archive Trigger

Kanté history.md archived at 16,618 bytes (>= 15,360 threshold) on 2026-06-19T09:51:10Z.

---

## Session 2026-06-22: Scoring Rule Correction + /recalcular (kante-scoring-groupstage-fix)

**Problem:** Group-stage scoring gave 0.5 points to any team that qualified to top-3 at the wrong position, including teams that simply swapped within the top-2 direct-qualifying zone (e.g., pred=1/actual=2).

**Fix:** Implemented correct rule:
- `pred ∈ {1,2} AND actual ∈ {1,2}` → **1.0** (exacto — order within top-2 irrelevant)
- `pred == actual == 3` → **1.0** (exacto — exact 3rd)
- One in top-2, other is 3rd → **0.5** (clasifica — boundary near-miss)
- Otherwise (actual ≥ 4) → **0.0** (fallo)

**Implementation:**
- `DIRECT_QUALIFY = 2` constant in `src/worldcup_bot/porra/scoring.py`
- `ensure_history(force: bool = False)` — when `force=True`, recomputes all jornadas from scratch (safe, requires one `get_all_matches()` call)
- `/recalcular` hidden admin command (visibility = HIDDEN, same as `/updatediario`)

**Tests:** 1463 → 1480 (+28)

**Key learning:** History is fully reconstructable from match results; no date-parameterized API calls needed for force-rebuild.

---

## Session 2026-06-22: Four Live Goal-Notification Bugs Fixed (production incident)

**Bug 1 — Duplicate goals (Spain 5-0 sent twice, ~8:03 PM):**
- Root: `poll_goals_job` (API, ~60s) and `poll_thread_goals_job` (thread, 25s) both shared `context.bot_data["live_scores"]` but each updated AFTER slow `await` (Reddit + OpenAI / Telegram send).
- Fix: `goal_lock = context.bot_data.setdefault("goal_lock", asyncio.Lock())`. Inside lock: read announced → reconcile → IMMEDIATELY write new_ann. Slow send outside lock. Concurrent job sees updated announced.

**Bug 2 — Goal sent with no scorer and no "Ver gol" button (Spain 4-0, ~7:19 PM):**
- Root: API detected 4-0 before thread; `_enrich_scorer` returned (None, None); clip-store entry created with scorer=None; clip finder requires scorer to match video title.
- Fix: `_backfill_scorer_in_clip_store(match, events, settings, context)` in `poll_thread_goals_job`. Finds clip-store entries with scorer=None at match+score, edits original message to add scorer line, sets scorer in entry (idempotent, guarded by `entry["scorer"] is not None`).

**Bug 3 — Wrong score in disallowed (Spain 3-0 shown, actual post-VAR was 4-0, ~8:00 PM):**
- Root: `format_disallowed_message` fed `delta.new_home/away` from thread's under-read (3-0 vs actual 4-0 after VAR drop). Announced also updated to 3-0, causing API re-announce next tick.
- Fix: After reconcile, for each disallowed delta, clamp: `d.new_X = max(d.new_X, ann_homeaway[X] - 1)`. Single VAR can only reverse one goal per side; post-VAR score is always ann-1 on affected side.

**Bug 4 — Missing goals (NZ–EGY, ~4:30 AM):**
- Root: Cross-job race (Bug 1) — one job updating announced past intermediate goal while other read stale announced.
- Fix: Bug 1's lock. After lock, API job reads already-claimed announced; reconcile returns no delta; no intermediate goals skipped.

**Tests:** 1480 → 1491 (+9 regression tests)

**Key learnings:**
- PTB's JobQueue runs jobs concurrently; shared mutable state needs explicit locking
- Authoritative score after VAR drop is announced-1 on affected side
- `asyncio.Lock()` must wrap the state mutation only, not slow I/O operations (send message)

---

## Session 2026-06-22: Goal Message Keyboard Preservation Fix

**Problem:** `editMessageText` without `reply_markup` silently removes inline keyboards (PTB omits None kwargs → Telegram clears field).

**Fix:** `_backfill_scorer_in_clip_store` checks `entry.get("status") == "ready"` and passes `reply_markup=build_goal_keyboard(tok)` to preserve the "Ver gol" button; otherwise `reply_markup=None`.

**Tests:** 1491 → 1491 (2 new regression tests in existing suite)

**Key learning:** Telegram API silently clears `reply_markup` field when omitted; must explicitly re-attach when editing.

---

## Session 2026-06-22: TVE (RTVE) Broadcast Markers 📺 (kante-tve-rtve-markers)

**Feature:** `/hoy`, `/siguiente`, and daily AI update now show 📺 emoji next to World Cup fixtures broadcast on Spanish public TV (La 1 / Teledeporte).

**RTVE schedule API (no auth):**
- Endpoint: `https://www.rtve.es/api/schedule/{slug}.json` (slug: `tv1` for La 1, `dep` for Teledeporte)
- Response: `{ "items": [ {...} ] }` with `idPrograma`, `name`, `begintime` (YYYYMMDDHHmmss, Europe/Madrid local), description
- World Cup filter: `idPrograma == 1030562` AND "resumen" NOT in name/episode (excludes highlights)
- Current-week only (~10 days); future fixtures won't have 📺 yet

**ES→TLA mapping and time matching (`src/worldcup_bot/tve.py`):**
- `ES_NAME_TO_TLA` dict with accent-stripped keys ("Túnez"/"Tunez" → TUN)
- `tve_channel_for(match, broadcasts)`: primary = kickoff within ±20 min + unordered TLA pair; time-only fallback (exactly one broadcast in window); La 1 beats Teledeporte

**Graceful degrade (hard constraint):**
- Flaky RTVE API must NEVER break `/hoy`, `/siguiente`, or daily update
- All use `try/except` around `asyncio.to_thread(load_tve_broadcasts, ...)`, fall back to `[]` on error
- `load_tve_broadcasts` catches per-channel errors, caches `[]` on total failure, respects 6-hour TTL
- Toggle: `TVE_ENABLED=false` in `.env`

**Changes:** `config.py` (`tve_enabled`, `_parse_bool`), `formatters.py` (`tve_label` kwarg), `handlers.py` (`cmd_hoy`, `cmd_siguiente`), `daily_update.py` (`build_ai_user_message`, `tve_by_key`, `generate_daily_update`)

**Tests:** 1491 → 1545 (+54)

**Key learnings:**
- RTVE schedule requires DST-aware localization (`pytz.timezone("Europe/Madrid")`)
- Time windows (±20 min) match broadcasts to kickoffs; TLA fallback only when exactly one broadcast in window
- Graceful degrade: NEVER let external flaky APIs break core bot commands

---

## Session 2026-06-22: 📺 TVE Marker Placement + /tongocheck (kante-dailyupdate-tve-and-tongocheck)

**Task A — Deterministic TVE in `/updatediario`:**
- **Problem:** 📺 channel label fed to AI via `build_ai_user_message` + `_SYSTEM` rule asking model to repeat. Fragile: AI could paraphrase, omit, or double it.
- **Solution:** Move to `render_message` (deterministic HTML builder, like `/hoy`).
- **Changes:**
  - `render_message` gains `tve_by_key: dict[str, str] | None = None`
  - Match line extended with ` 📺 {label}` when key present (Section 2, today fixtures)
  - Removed `tve_by_key` from `build_ai_user_message` and `_SYSTEM` TVE rule
  - `generate_daily_update` passes `tve_by_key` to `render_message` instead
- **Net effect:** Deterministic > probabilistic for factual data; AI note focuses purely on curiosity/conflict

**Task B — `/tongocheck` hidden admin validator:**
- **Problem:** `load_tongo_config` swallows YAML errors, falls back to built-in FRASES. Stray character breaks file silently.
- **Solution:** `check_tongo_config(path) → (bool, str)` pure validator exposed as `/tongocheck` (hidden, like `/recalcular`).
- **Contract:**
  - Missing file → `(False, "no encontrado en {path}")`
  - YAML error → `(False, "Error de YAML: {exc}")` with line/col
  - Non-mapping → `(False, "El fichero no es un mapping YAML válido")`
  - Empty/comment-only → success (treated as `{}`)
  - Success → `(True, "{N} frases globales, {M} usuarios configurados: alice, bob")` or `"sin overrides por persona"`
  - Never raises; never modifies hot-reload cache
- **Handler:** `cmd_tongocheck` — resolves path, replies `✅ TongoUsers.yml OK — {summary}` or `❌ TongoUsers.yml: {detail}`
- **Registration:** `CommandHandler("tongocheck", cmd_tongocheck)` in `__main__.py` (hidden section)

**Tests:** 1545 → 1565 (+20 net: render_message TVE ×5, AI no-TVE ×4, generate_daily_update TVE ×2, _SYSTEM ×1, check_tongo_config ×7, cmd_tongocheck ×5; minus 1 removed)

**Key learnings:**
- Deterministic rendering eliminates need for AI probabilistic inference on factual data
- Silent YAML failures require explicit validation tools to diagnose from Telegram
- Read-only admin tools (zero production risk) are safe entry points for operator diagnostics

---

**Test progression: 1463 → 1480 → 1491 → 1545 → 1565 (all green)**

**Phases 26–31 now archived (2026-06-22 spawn complete).**

---

## Session 2026-06-22: TongoUsers Required + Kickoff Notifications (kante-tongo-required-and-kickoff)

**Phase 1 — TongoUsers.yml is now REQUIRED:**
- `load_tongo_config` raises `TongoConfigError` on missing file (was: graceful empty return)
- Removed legacy fallback to `FRASES` constant and `infer_gender` (deprecated code path)
- `/tongo` command wraps load in try/except; replies with actionable error message + `/tongocheck` hint
- Deleted `src/worldcup_bot/data/gender.py` + `gender-guesser` dependency
- **Tests:** 1565 → 1531 (net −34: removed 36 legacy tests; added 2 error-path tests)
- **Key learning:** Explicit required files with clear error messages beat silent fallbacks

**Phase 2 — Kickoff-start notice (`poll_kickoff_job`):**
- New repeating job posts `🟢 ¡Empieza el partido! {flags+teams}` to group when `utc_date <= now_utc`
- Time-based trigger, not waiting for API status flip → faster user notification
- **Seed pass (restart-safe):** First run marks all past-kickoff + IN_PLAY/PAUSED/FINISHED matches as announced (no re-send after restart)
- **Grace window:** Matches > 30 min past kickoff silently marked, no stale announcement
- **Silent hour aware:** Uses existing `_is_silent_hour` (00:00–09:00 local = quiet, disable_notification=True)
- **State reuse:** Leverages existing `load_finished`/`save_finished` helpers from `finished_state.py` (DRY, no new module)
- **Formatter:** `format_match_start(match) → str` in `formatters.py` (pure, testable, returns HTML-safe text with flags)
- **Job interval:** Hardcoded 30s (mirrors existing goal-job pattern; no new env var)
- **Files:** `__main__.py` (job + state wiring), `formatters.py` (formatter), `tests/test_poll_kickoff_job.py` (21 tests)
- **Tests:** 1531 → 1552 (+21: seed, normal, restart, grace window, silent hour, API error, formatter)
- **Key learning:** Time-based deterministic firing (not waiting for status API lag) gives responsive user experience; restart-safe seed pass + grace window prevent stale announcements

**Test progression: 1565 → 1531 → 1552**  
**Spawned by:** kante (Claude Sonnet 4.6) + coordinator verification  
**Decisions linked:** `.squad/decisions.md` (Kickoff-start notice at scheduled kickoff time)

---

## Session Summary (2026-06-30 — Revive Quiet Hours + Jitter)

**Kanté's follow-up feature enhancement — 2026-06-30:**

Shipped self-rescheduling jitter scheduling + quiet-hours window for the Revive feature (commit 31f1a89). Three new pure functions:
- is_quiet_hours(hour, quiet_start, quiet_end) — UTC-aware quiet window check with midnight-wrap support
- 
ext_revive_delay(base, jitter, now_local, quiet_start, quiet_end, rand) — adaptive delay with jitter ± and quiet-push (injectable rand for deterministic testing)
- schedule_next_revive(job_queue, settings) — one-shot job scheduling replacing old run_repeating

Refactored evive_inactive_job with robust self-rescheduling via finally block (all exit paths: success, quiet-skip, no-candidates, AIError, Exception). Config: 3 new Settings fields (revive_quiet_start_hour, revive_quiet_end_hour, revive_jitter_seconds). Env parsing integrated.

Updated __main__.py for initial schedule via schedule_next_revive (first run randomized + quiet-aware). Added 8 new smoke tests (all pass).

**Result:** Full suite 1936 passed, 0 failed.
