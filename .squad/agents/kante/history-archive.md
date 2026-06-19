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
