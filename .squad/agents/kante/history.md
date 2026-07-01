# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2018 tests ✅

## Current Sessions (2026-07-01)

### ✅ Podium Layout Rework — Vertical Stack (awaiting commit)
Replaced the flat tile layout with a proper vertical stack: podium BLOCK at bottom → circular photo "head" on block → crown on head. Each participant occupies one column; classic arrangement for n=3 (center=1st, left=2nd, right=3rd). Block height is tied to tie-aware position (1→175px tall/gold, 2→120px/silver, 3→85px/bronze). Photo (150px diameter, circular) rests on the block top with 10px overlap. Crown (asset, 105px wide, or drawn fallback) sits on the photo head with 30px overlap at its bottom — like a crown on a head. Position number is drawn on the block face, not on the crown. Canvas 760×560, dark-navy background. All magic numbers are module-level constants. Fixed a broken edit (duplicate content in file — old code was appended after new code at line 352; trimmed via `Set-Content lines[0..349]`). Updated two geometry assertions in `test_podium_image.py` (720→760, 400→560 and one `tile_y`→`photo_top_y` rename). **2018 tests pass**. Decision doc: `.squad/decisions/inbox/kante-podium-drawn-base.md`. **No commit** — David handles.

### ✅ Crown Asset Integration (awaiting commit)
Swapped podium crown from hand-drawn polygon to real Noto Emoji crown (`src/worldcup_bot/assets/crown.png`, 128×128 RGBA, Apache-2.0). Loaded at module init via `importlib.resources.files("worldcup_bot") / "assets" / "crown.png"`, cached in `_CROWN_IMG`. Scaled to 56×56 px and alpha-composited; position number drawn in the same 22 px gap below crown. `_draw_crown` kept as fallback when `_CROWN_IMG is None`. Updated `test_podium_image_edge_cases.py::test_draw_crown_exception_mid_render_returns_none` to also patch `_CROWN_IMG = None`. 5 new tests in `TestCrownAsset`. Decision doc: `.squad/decisions/inbox/kante-crown-asset.md`. **No commit** — David handles.

### ✅ Podium Image Feature (IMPLEMENTED + APPROVED, committed 4343ddb)
New module `src/worldcup_bot/bot/podium_image.py` — `render_podium(participants, settings) → BytesIO | None`. Sync function; caller uses `asyncio.to_thread`. 720×400 dark-navy canvas; 180px circular-cropped tiles; programmatic gold crown (single filled polygon + jewel circles, no assets); position number drawn between crown and tile; initials placeholder when photo missing. Fallback chain in `_send_ranking_with_top3_photos`: podium → album → text. Added autouse `_stub_render_podium` to `TestCmdActual`, `TestCmdGeneral`, and `TestSendRankingWithTop3Photos` (album tests stay clean). 17 new tests; 1968 total + 45 edge-case tests by Buffon (all pass). Pirlo reviewed and approved. Committed to main. Decision docs merged to `decisions.md`.

### ✅ Standard Competition Ranking (tied positions / 1224 style, committed 8987262)
Added `standard_competition_positions(rows) -> list[int]` pure helper in `formatters.py`. Uses `round(score, 1)` equality. Updated `format_general_ranking` to replace `enumerate` counter. 12 new tests; 1951 total. Committed to main. Decision doc merged to `decisions.md`.


## Previous Sessions (2026-06-30)

### ✅ Picante Prompt Refinement (SHIPPED, commit d964fbf)
Rewrote `_SYSTEM` and `build_picante_user_message` so picante replies focus on the LAST (triggering) message rather than force-weaving all buffered messages. Two-section user prompt: optional CONTEXTO block (prior messages, use only if clearly related) + ÚLTIMO MENSAJE block (trigger, always reply to this). Language rule: mirror the last message's language (Catalan→Catalan, Castilian→Castilian). Updated 3 tests in `test_chat.py` to assert new structure.

### ✅ ChatState Eager Persistence (APPROVED)
Startup + per-message persistence of `chat_state.json` (last_seen only, no message text). New guard: `.get()` + truthiness. Test suite: 1939 passed.

### ✅ Revive Quiet Hours + Jitter (SHIPPED)
Quiet-hours suppression (23:00-06:00 local), randomized self-rescheduling via `run_once` loop. New env vars: `REVIVE_QUIET_START_HOUR`, `REVIVE_QUIET_END_HOUR`, `REVIVE_JITTER_SECONDS`. Shipped commit 31f1a89.

### ✅ LLM Chat Features Ship (SHIPPED)
Two features: **Picante** (1-in-5 spicy replies) + **Revive** (4h inactive check). New `src/worldcup_bot/chat/` package (buffer, state, listener, picante, revive). Privacy: ZERO message text on disk. Both disabled by default. Shipped commit ce11647. **BLOCKING:** BotFather privacy mode must be disabled.

---

## Previous Sessions (2026-06-27)

### ✅ Catch-Up Recovery + FINISHED Eviction (SHIPPED)
Fixed missed-goal bugs (A/C) via: (1) 0-0 seed at kickoff, (2) recover scorer+video from Reddit thread (fallback: neutral), (3) FINISHED two-tick eviction, (4) immediate save after thread claim. 1661 tests passed.

### ✅ Egypt-Iran Goal Loop Fix (APPROVED)
Added `_match_is_over(match, now_utc)` wall-clock predicate (4h threshold). Prunes stale entries, excludes from goal polling. 1644 tests passed.

---

## Archive

Detailed sessions before 2026-06-27: see `history-archive.md` (TVE fix, Live goal bugs, Best-thirds, etc.)
