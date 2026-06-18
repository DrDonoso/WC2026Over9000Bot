# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (python-telegram-bot), football-data.org API, Docker + compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15
- **Status:** 1267 tests green

## Session 2026-06-17: Streamff Mirrors + Thread-Based Goals + /endirecto Redesign + Clip Scorer (kante-32 through kante-36)

**Phases:** 6 major implementations completing live-match infrastructure  
**Archived from 17391 bytes on 2026-06-17 to history-archive.md for future reference**

### Block 1: Streamff Mirror Fix (kante-36, 19 tests) — Live-verified

**Fix A:** `streamff.* → cdn.streamff.one/{id}.mp4` routing.
- Regex broadened from `streamff\.(?:com|link)` → `streamff\.[a-z]+/v/` (any TLD)
- Host check changed to `"streamff." in media_url` (guard all mirrors)
- Coordinator verified live: `streamff.pro` + `streamff.gg` clips download 27MB via CDN

**Fix B:** Thread-based goal detection with race-free dedup (1161→1267 tests).
- Shared in-memory `bot_data["live_scores"]` dict used by both `poll_goals_job` (60s, football-data) and new `poll_thread_goals_job` (25s, Reddit thread)
- Thread updates score in-place → football-data diff returns `[]` on next tick → no duplicate notification
- Extracted `_notify_goal` helper for both job paths
- Thread scorer passed directly (no OpenAI enrichment = speed win)
- Coordinator verified live: England 3-2 Croatia notified from thread before football-data confirm

**Key learnings:**
- streamff CDN is TLD-agnostic: any mirror's video ID is the same (`cdn.streamff.one/{id}`)
- Race-free dedup requires shared dict (not per-job disk loads)
- `asyncio.to_thread` required for sync scanner call in async job context

### Block 2: /endirecto Live Detail Enrichment (kante-33, 42 tests) — 1163→1205 tests

New `src/worldcup_bot/ai/match_events.py` module (mirrors `goal_extractor.py`):
- Trims Reddit thread on "MATCH EVENTS" anchor, caps at 6000 chars
- LLM extracts JSON: `{minute, goals, cards, subs}`
- New formatter `format_live_match_detail`: header + score + optional sections (goals/cards/subs)

Handler `cmd_en_directo`: enriches each live match (cap 4) via thread + LLM, fallback to plain `format_match` on error.

**Key learning:** football-data free tier has no detail arrays (`goals`, `bookings`, `substitutions`). Reddit MATCH EVENTS section is ESPN-structured and highly LLM-parseable.

### Block 3: Clip Finder Merge + Timeout (kante-34, 2 tests) — 1161→1163 tests

LIVE bug: Cancelo clip post existed in r/soccer `/new/` but not HTML search index (lag). Old logic only checked `/new/` when HTML search returned EMPTY.

Fix: Always merge HTML search + `/new/` results, deduplicated by post id. Now catches both indexed and brand-new clips.

**Key learning:** r/soccer HTML search index lags by minutes.

### Block 4: Clip Scorer Robust Match (kante-35, 11 tests) — 1152→1161 tests

LIVE bug: Wissa scorer match failed due to `_scorer_matches("Wissa Y. goal", "Yoane Wissa")` → False (noise token "goal" misaligned) + minute tolerance too tight (diff=4, limit=2).

Fix:
- Rewrote `_scorer_matches`: tokenize + drop noise set (`{goal, penalty, og, ...}`) + single-char tokens + set intersection or substring match
- Handles accents via NFKD + combining-mark strip
- Minute tolerance ±3 (defense-in-depth)

**Key learning:** Accent folding + noise filtering required for robust natural-name matching across languages.

### Block 5: /endirecto Inline Buttons (kante-32, 43 tests) — 1205→1248 tests

David requested: stop dumping all detail inline; send header+goals only, buttons to reveal tarjetas/alineación/cambios on-demand.

**New module:** `src/worldcup_bot/bot/endirecto_store.py` — persists snapshots to `{state_dir}/endirecto.json`, keyed by 8-hex token.
**Extended:** `match_events.py` now includes `lineup` extraction (caps at 8000 chars, anchors on "Starting XI" if present).
**New formatter:** `render_endirecto` — returns `(text, keyboard_rows)` with FIXED section order (goles→tarjetas→alineación→cambios), buttons only for unrevealed sections.
**Handler:** `cmd_en_directo` saves snapshot; new `cmd_endirecto_callback` reveals section + edits message in-place.

**Key learning:** Persistent JSON dict store is restart-resilient (unlike in-memory clip_store). FIXED render order in code maintains consistent UX regardless of click order.

### Block 6: Rich-Image Finalization (kante-25–29, earlier session) — 1135 tests

Archived to history-archive.md. 5 iterations: model-driven escalation, hybrid multi-image anchor, Azure moderation compliance, caption normalization (no slashes), rich emphasis.

---

## Design Constraints Preserved

1. **Module decoupling:** api/ ← config + cache; never imports bot/ or porra/
2. **Shared TTLCache singleton:** Fixes HTTP 429 rate limit
3. **Goal tokens:** SHA1[:12] hex (12 bytes fits callback limit)
4. **Non-blocking in-flight guard:** Set of tokens in bot_data
5. **Two-level file_id cache:** Per-goal + per-url cache layer
6. **asyncio.to_thread:** Correct pattern for sync calls from async context

## Session 2026-06-18: Czechia Team Alias Fix (live bug, clip-finder)

**Problem:** "Ver gol" never appeared for Czechia 1-0 South Africa (Sadílek 6').
Clip existed on r/soccer: `"Czech Republic [1] - 0 South Africa - M. Sadílek 6'"` → `https://streamin.link/v/9801698f`.
`find_goal_clip` returned `None` because `_teams_match("Czech Republic", "Czechia")` was `False`.

**Root cause:** `WC_TEAM_ALIASES` in `scanner.py` had no Czech Republic↔Czechia entry.
football-data.org canonical name = `"Czechia"`; r/soccer / ESPN clip titles use `"Czech Republic"`.

**Fix:** Added to `WC_TEAM_ALIASES`:
```python
"czech republic": "czechia",
"czech rep": "czechia",   # covers "Czech Rep" and "Czech Rep." (dot stripped before lookup)
```

**Tests added (7):**
- `TestCzechiaAlias` × 5 in `test_reddit_scanner.py` (normalize equality, both-order teams_match)
- `TestMatchPost.test_czech_republic_clip_title_matches_czechia_fixture`
- `TestFindGoalClip.test_czechia_czech_republic_clip_title_integration` (exact live clip + streamin URL)

**Key learning:** r/soccer and ESPN clip titles use the old name "Czech Republic" while football-data's REST API normalizes to "Czechia". Same class of bug as D.R. Congo↔Congo DR — requires explicit alias in WC_TEAM_ALIASES rather than relying on fuzzy matching (SequenceMatcher ratio "czech republic" vs "czechia" ≈ 0.67 < 0.80 threshold).

---

## Test Count History

- 1135 (rich-image, kante-29)
- 1152 (clip-finder baseline for kante-35)
- 1161 (+ clip-scorer, kante-35)
- 1163 (+ clip-finder merge, kante-34)
- 1205 (+ /endirecto enrichment, kante-33)
- 1248 (+ /endirecto buttons, kante-32)
- 1267 (+ streamff + thread goals, kante-36)
- 1313 (+ beloved teams ❤️, 2026-06-18)
- 1336 (+ Czechia alias fix, 2026-06-18)
- **1357** (+ shared scanner + TTL cache + /endirecto 429 fix, 2026-06-18)

---

## Session 2026-06-18: /endirecto 429 Fix — Shared Scanner + TTL Cache (kante-endirecto-429)

**Problem diagnosed live:** `/endirecto` showed NO inline keyboard in prod.
- `cmd_en_directo` created a FRESH `RedditMatchScanner` per call → hit Reddit cold (no cache).
- `find_match_thread` uses `old.reddit.com/r/soccer/search` → Reddit returned HTTP 429 (Too Many Requests) → returned `None` → fell back to plain `format_match` (score only, no keyboard).
- Concurrent goal-poller (25s), clip-finder, AND on-demand `/endirecto` all hitting Reddit independently → exceeded rate limit.

**Fix — three changes:**

### 1. `src/worldcup_bot/reddit/scanner.py` — TTL cache (30s/90s)

Added module-level TTL constants:
```python
_MATCH_THREADS_TTL = 30   # seconds
_THREAD_BODY_TTL   = 90   # seconds per permalink
```
Added per-instance cache fields: `_match_threads_cache` (tuple of timestamp + list) and `_thread_body_cache` (dict permalink → timestamp + body).

**`get_match_threads()`:** Returns cached result if age < 30s; on any exception (including 429) returns stale cache if available, else `[]`. Never raises.

**`get_thread_body(permalink)`:** Returns cached result if age < 90s; on any exception returns stale cache if available, else `""`. Never raises.

**New method `find_thread_permalink(home_name, away_name)`:** Scans the *cached* `get_match_threads()` result using `_parse_thread_teams` + `_teams_match` (both orderings). Uses the reliable `/new/` listing instead of the 429-prone `/search` endpoint.

### 2. `src/worldcup_bot/bot/handlers.py` — shared scanner + new lookup order

`cmd_en_directo` now:
1. Lazy-inits from `context.bot_data.get("reddit_scanner")` (same instance as goal/clip jobs).
2. Tries `scanner.find_thread_permalink(...)` **first** (cached, no new Reddit hit).
3. Falls back to `scanner.find_match_thread(...)` only if `None`.
4. Goal poller's 25s ticks keep the cache warm → `/endirecto` reuses those fetches → no 429.

### 3. Tests (+21)

- **`TestFindThreadPermalink` (6):** Czechia↔South Africa, reversed order, Post Match excluded, empty list, cache reuse.
- **`TestScannerMatchThreadsCache` (4):** Second call within TTL → one fetch; past TTL → refetch; 429 with cache → stale returned; 429 no cache → `[]`.
- **`TestScannerThreadBodyCache` (5):** Same pattern per-permalink; multiple permalinks independent.
- **`TestCmdEnDirectoSharedScanner` (6):** Reuses existing scanner, lazy-init stores in bot_data, `find_thread_permalink` produces keyboard (3+ buttons), falls back to `find_match_thread`, both-None → `format_match`, never raises.

**Key learnings:**
- Reddit rate-limits datacenter IPs aggressively; two callers (goal poller + /endirecto) each creating fresh sessions is enough to 429.
- The `/new/` listing endpoint is less 429-prone than the `/search` endpoint and is already cached by the goal poller — ideal primary source for `/endirecto`.
- The fix requires only a shared scanner instance (bot_data) + per-instance TTL caches; no external cache store needed.

