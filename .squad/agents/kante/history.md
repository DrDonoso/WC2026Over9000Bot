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

## Test Count History

- 1135 (rich-image, kante-29)
- 1152 (clip-finder baseline for kante-35)
- 1161 (+ clip-scorer, kante-35)
- 1163 (+ clip-finder merge, kante-34)
- 1205 (+ /endirecto enrichment, kante-33)
- 1248 (+ /endirecto buttons, kante-32)
- **1267** (+ streamff + thread goals, kante-36)
