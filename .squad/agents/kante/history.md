# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2324 tests ✅

## Current Sessions (2026-07-01 → 2026-07-04)

### ✅ /elecciones hourglass UX (committed 8922308)
Owner feedback: on phase tap, the bot removed the keyboard silently then sent the result as a separate message — no feedback during multi-second image generation.

**New flow:**
1. `query.edit_message_text("⏳ Generando…", reply_markup=None)` — edits the selector message in-place (hourglass + removes keyboard atomically). Capture `placeholder_id = query.message.message_id`.
2. Generate artifact (try/except; `artifact=None` on any exception).
3. **Success:** `context.bot.delete_message(chat_id, placeholder_id)` → `send_photo` or `send_message`.
4. **Failure:** `context.bot.edit_message_text(chat_id, placeholder_id, "❌ Error…")` — no dangling hourglass.

**What changed:**
- `handlers.py`: replaced `_serve_elecciones` with `_serve_after_placeholder(context, chat_id, placeholder_id, artifact)`. Rewrote `cmd_elecciones_callback` to four-step flow. Error path uses `edit_message_text` on `context.bot` (not on `query`).
- `tests/test_elecciones.py`: added `delete_message` + `edit_message_text` AsyncMocks to `_make_context()` and `_make_query()`. Updated 6 existing callback tests. Added `test_generation_failure_edits_placeholder_to_error`.

**101 tests in elecciones file; 2324 passed full suite, 8 pre-existing unrelated failures.**

**Gotchas:**
- `query.edit_message_text` sets the hourglass; `context.bot.edit_message_text` writes the error after placeholder_id is captured. They are different objects — don't confuse them in tests.
- The `try/except` wrapping `_generate_elecciones_artifact` converts ANY exception (network, PIL, etc.) to `artifact=None`, which `_serve_after_placeholder` then turns into an edit-to-error. No silent failures, no crashes.

### ✅ /elecciones circular flags (committed 4b8f0e1)
Owner feedback: teams were rendering as TLA text in image mode. Now all team appearances in both images are circular flag tiles.

**What changed (`bot/elecciones_image.py` only):**
- Added `_circular_crop` to imports from `podium_image.py`
- `_fetch_flag_tile` now applies `_circular_crop(img, size)` after every fetch/cache-load — rectangular cached files remain valid (mask applied in memory)
- Knockout tie-label column: replaced `"CAN · RSA"` text with two 18px circular flags + small 7px TLA caption below each; "·" separator at centre; TLA text fallback if flag unavailable
- New constants: `_TIE_FLAG_D = 18`, `_TLA_FONT_SIZE = 7`
- Groups 2×2 cells and knockout pick/result cells all use `_fetch_flag_tile` → circular flags automatically (no other code changes needed)

**Flag resolution chain:** `tla_to_iso(tla)` → if len(iso)==2 → twemoji CDN URL → fetch → `_circular_crop` → RGBA round image. Non-2-char ISO (GBENG/GBSCT/GBWLS) → `None` → TLA text fallback. Same mapping as `team_flag()` in `formatters.py` via `tla_map.py`.

**3 new tests:** `test_fetch_flag_tile_returns_circular_image` (corner alpha=0, centre alpha>200), `test_render_knockout_matrix_with_flags_succeeds`, `test_render_groups_matrix_with_flags_succeeds`. **100 tests in elecciones file, 2331 total elecciones-related, 8 pre-existing unrelated failures unchanged.**

**Gotchas:**
- Store raw rectangular PNG to disk cache (pre-crop); apply `_circular_crop` on load. Old cached entries work transparently.
- `_apply_alpha` (for groups fade) composites correctly with circular flags: transparent corners stay at 0 alpha regardless of the scale factor.

### ✅ /elecciones increment 2 — groups image + eviction + defensive split (committed 7a0dcfc)
Groups 2×2 image renderer, tile-cache disk eviction, defensive line-level text split. Follows Pirlo's B4 design.

**Groups image (`bot/elecciones_image.py` additions):**
- `render_groups_matrix(group_compositions, participants, settings)` — public API, returns `BytesIO | None`
- `_render_groups(...)` — PIL impl: 12 rows (A–L), n participant columns, 2×2 flag grid per cell
- `group_compositions` built from `client.get_standings()` via `build_group_compositions()` (new helper in `porra/elecciones.py`)
- Alpha weighting: picks 1 & 2 → 255 (full), pick 3 (tercero) → 165 (~65%), not picked → 65 (~25%)
- `_apply_alpha(img, alpha)` — scales existing alpha channel (preserves antialiasing edges)
- Always called via `asyncio.to_thread` in handler (CPU-bound PIL, not blocking event loop)
- `group_compositions` API call happens on the event loop before `to_thread` (I/O, TTL-cached)
- Groups fallback to text when render fails (graceful degradation); `log.warning` not `log.info`

**Tile-cache eviction (`_evict_tile_cache`):**
- Called at the start of BOTH `_render` (knockout) and `_render_groups` (groups)
- Glob `flag_*.png`, sort by mtime, unlink oldest above `_MAX_TILE_CACHE_FILES=200`
- Best-effort (exceptions swallowed); no background thread needed

**Defensive line split (`porra/elecciones.py`):**
- `_HARD_LIMIT = 4090`
- `_split_block_at_lines(block, max_len)` — splits at `\n` boundaries; single line > max_len returned as-is
- `_split_messages` pre-processes each block through `_split_block_at_lines(_HARD_LIMIT)` before the threshold splitting — no message can exceed 4090 chars even for large user blocks

**Terceros strip:** skipped — the intermediate-alpha (165) rendering already makes tercero picks clearly visible; fitting 12 flags into an 84 px column is not clean. Noted in decision doc.

**asyncio.to_thread comment:** added to both `render_knockout_matrix` and `render_groups_matrix` docstrings explaining it's a short-lived single invocation (no background loop, no CPU/RAM runaway risk).

**Tests:** 18 new (97 total for the elecciones test file). `TestBuildGroupCompositions`, `TestDefensiveLineSplit`, `TestGroupsImage` (including image-mode-no-fallback-to-text and render-failure-fallback-to-text), `TestTileCacheEviction`. **2328 total, 0 failures.**

**Gotchas:**
- When inserting code before an existing function, the `edit` tool's `old_str` must INCLUDE the `def` line itself so it's preserved in `new_str`. Just matching the `def` line and NOT including it in `new_str` silently drops the function signature.
- Patch target for `render_groups_matrix` in callback tests: `worldcup_bot.bot.elecciones_image.render_groups_matrix` — the handler imports it lazily inside the function body; the patch on the module attribute is picked up at import time. Same pattern as `build_groups_text`.
- `_apply_alpha` uses `img.split()` + `.point(lambda x: x * alpha // 255)` — this correctly scales the EXISTING alpha channel rather than replacing it (`putalpha` would lose antialiasing).
- `asyncio.to_thread` runs the mock function in a thread during tests — `MagicMock` is thread-safe for simple return-value calls.

### ✅ /elecciones increment 1 (committed 38e00b2)
(details in prior session entry)

## Current Sessions (2026-07-01 → 2026-07-03)
Phase-selector inline keyboard + per-user text renderers (knockout + groups) + PIL knockout matrix image + `CHOICES_TYPE` env var + lazy bounded cache. Full design by Pirlo (`pirlo-elecciones-design.md`); zero-regressions on 2310 tests.

**Key decisions:**
- `porra/elecciones.py` — pure data helpers (no I/O); `build_knockout_text` / `build_groups_text` accept `team_flag_fn` for testability.
- `bot/elecciones_image.py` — PIL knockout matrix: rows = ties, columns = participants (circular headers + initials fallback), cells = flags; twemoji CDN for flag PNGs; non-2-char ISO (GBENG/GBSCT/GBWLS) → None → TLA text fallback.
- Groups image NOT in this increment — tapping grupos in image mode transparently falls back to text renderer.
- Cache in `bot_data["elecciones_cache"]`; key = `(yaml_key, mtime, results_hash)`; max 6 entries; eviction removes stale same-phase entries before adding new one; NO background thread.
- `_generate_elecciones_artifact` uses lazy imports (inside function body) — patch target for tests is `worldcup_bot.porra.elecciones.*`, not `worldcup_bot.bot.handlers.*`.
- Callback data `elecciones|<yaml_key>`; pattern `^elecciones\|`; keyboard is DELETE-on-tap (edit message to remove reply_markup before serving).
- `CHOICES_TYPE` env var (default `text`) wired into `config.py Settings` + `load_settings()` + both compose files + `.env.example`.

**Gotchas:**
- `InlineKeyboardButton` was not imported in `handlers.py` — always check telegram imports when adding keyboard code.
- `hashlib`, `io`, `os` not imported in `handlers.py` — added at top.
- `_fetch_tile` from `podium_image.py` is a private import across same package — acceptable but fragile; document if refactoring.
- Twemoji URL is `https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{codepoints}.png`; non-2-char ISO codes have no codepoint mapping → `_flag_url` returns `None`.
- `_split_messages` cannot split within a user block — a single block >3800 chars stays as-is (no silent data loss); threshold is "soft" for the purpose of fitting Telegram's 4096-char limit when multiple blocks combine.

## Current Sessions (2026-07-01 → 2026-07-03)

### ✅ Post-Final VAR Score Correction (awaiting commit)
**Bug:** Portugal-Croatia knockout: free-tier API briefly marked FINISHED at 2-2 (pre-VAR); bot announced "🏁 Final 2-2". Real score was 2-1. `poll_finished_matches_job` finalizes on the first FINISHED tick and never re-checks. The in-play VAR mechanism didn't catch it because the annulment happened at full-time.

**Feature (David-approved):** After finalization, watch each match for 30 min; if the API score changes (VAR correction), (1) post a correction message, (2) edit the original "¡GOOOL!" message to mark it annulled. New config `FINAL_CORRECTION_WINDOW_MINUTES=30`.

**Implementation:**
- **`reddit/finished_scores.py`** — new module: `load_finished_scores` / `save_finished_scores` for `{state_dir}/finished_scores.json`.
- **`bot/formatters.py`** — `format_var_correction(match, old_home, old_away)`: "⚠️ Corrección (VAR)\n🇵🇹 Portugal 2-1 Croatia 🇭🇷\nEl gol del 2-2 fue anulado."
- **`config.py`** — `final_correction_window_minutes: int = 30` + env var `FINAL_CORRECTION_WINDOW_MINUTES`.
- **`__main__.py`** — `poll_finished_matches_job`: records finalized score after send; VAR watch called on every tick (early-return restructured to always hit watch). New helpers: `_fs_entry_is_stale`, `_mark_goal_annulled` (token reconstruction for clip lookup, keyboard preserved), `_var_correction_watch`. `build_app` seeds `finished_scores` from disk.

**Clip lookup:** token reconstruction `f"{match_id}:{scoring_team}:{h}-{a}"` for both home/away scoring team — O(1), no schema change, invariant: `_process_goal_delta` always normalizes `scoring_team` to canonical match name.

**Safety:** penalty-shootout comparison is on-pitch only (home/away_score stable); `match_result_is_final` gate unchanged; all correction paths best-effort/non-fatal. **8 new tests; 2165 total, 0 failures.** Decision doc: `.squad/decisions/inbox/kante-var-final-correction.md`. **No commit** — David handles.

### ✅ TVE Knockout-Round Prefix Fix + 24:00 Midnight Notation Fix — 📺 Label Missing for All R32+ Matches (awaiting commit)
Every knockout-stage match was missing the 📺 TVE label. **Root cause 1:** RTVE names knockout items `"Futbol Copa Mundo Fifa 1/16 Argentina - Cabo Verde"`. `_parse_teams` stripped only `_WC_EPISODE_PREFIX`, leaving `"1/16 Argentina - Cabo Verde"`. Split on `" - "` → `home_raw="1/16 Argentina"` → `ES_NAME_TO_TLA.get(_norm("1/16 argentina"))` = None → `tve_channel_for` same-day TLA fallback requires both TLAs → None → no 📺. Fix: added `_ROUND_PREFIX_RE` in `tve.py`; live before: `(None, 'CPV')`, after: `('ARG', 'CPV')`.

**Root cause 2:** For midnight matches, La 1's description contains `"(24:00)"` (RTVE Spanish convention: midnight = 24:00). `_parse_kickoff_utc` called `datetime.strptime("20260703 24:00", "%Y%m%d %H:%M")` → `ValueError` (hour=24) → `except` returned `None` → La 1 broadcast dropped entirely → only Teledeporte survived → `tve_channel_for` returned `"Teledeporte"` instead of `"La 1"`. Fix: replaced `strptime` with manual hour/minute parse + `timedelta` rollover (`day_offset = hour // 24`, `hour_mod = hour % 24`). `"24:00"` on 20260703 → Madrid 2026-07-04 00:00 CEST = **UTC 2026-07-03 22:00** (exact match with fixture) → La 1 now hits the ±20 min primary window and wins.

Live before/after (both fixes): `_parse_kickoff_utc(La 1 item, "La 1")` before: `None`, after: `2026-07-03 22:00:00+00:00`; `tve_channel_for(ARG vs CPV)` after round-prefix fix only: `'Teledeporte'`; after both: **`'La 1'`** ✓. **23 new tests (17 round-prefix + 6 midnight); 2157 total, 0 failures.** Decision doc: `.squad/decisions/inbox/kante-tve-knockout-prefix-fix.md`. **No commit** — David handles.

### ✅ "Ver gol" Button Missing on Two Live Goals — Clip Pipeline Fix (awaiting commit)
Two goals never got the "Ver gol" button: Belgium 3-2 Senegal (Tielemans 120+5' ET penalty) and United States 1-0 Bosnia-Herzegovina (Balogun 45'). **Goal A root cause:** timeout — `_MAX_CLIP_ATTEMPTS = 25` × 45s = 18.75 min was too short for an ET match-ending clip posted after the window. **Goal B root cause:** search miss + timeout — HTML search `"United States Bosnia-Herzegovina"` returns zero goal clip posts because Reddit's index doesn't find `"USA"` for `"United States"`. Fix: (1) `_MAX_CLIP_ATTEMPTS` 25→40 (~30 min) in `__main__.py`; (2) added `_TEAM_SEARCH_SHORT = {"united states": "usa"}` + `_search_term(team)` in `clip_finder.py` — applied in `_fetch_html_search_posts` and `find_goal_clip` JSON path. Both clips reproduce live and match perfectly (verified via `find_goal_clip`). **13 new tests; 2134 total, 0 failures.** Decision doc: `.squad/decisions/inbox/kante-vergol-button-fix.md`. **No commit** — David handles.

## Learnings

### 2026-07-04 — Production Bugs: keyboard never attached + FINAL 9h late (commit a61757d)

#### Bug #1 Root Cause — "Ver gol" button never attached (2026-07-03 ALL goals affected)
`poll_goal_clips_job` sets `entry["status"] = "ready"` BEFORE calling `edit_message_reply_markup` (intentional: concurrent `_backfill_scorer_in_clip_store` must see the entry as ready). But if `edit_message_reply_markup` then FAILS (Telegram API blip), there was no retry path: the next tick's early-return `if not searching: return` exits before any retry code, and the main loop only processes `status="searching"` entries. For goals where `scorer` was already known, `_backfill_scorer_in_clip_store` also skips them (`scorer is not None → continue`). Result: every goal on 2026-07-03 ended up without the button permanently.

**Fix (files: `src/worldcup_bot/__main__.py`, `src/worldcup_bot/reddit/clip_store.py`):**
1. `clip_store.py add_entry`: added `"keyboard_attached": False` field to entry schema.
2. `__main__.py poll_goal_clips_job`: set `entry["keyboard_attached"] = True` after successful `edit_message_reply_markup`.
3. Compute `pending_retry` (status="ready" + not keyboard_attached) BEFORE the early-return guard (so it runs even with zero searching entries).
4. After the searching loop, iterate `pending_retry` and call `edit_message_reply_markup` until success.
5. `save_clips` is called only when `changed=True` — retry success sets `changed=True`.

**Key gotcha:** The early-return `if not searching: return` was at line ~1284 — the retry loop was AFTER it, so ready entries were never retried when there was no new searching work. Always put the `pending_retry` computation BEFORE the early-return.

**Key gotcha 2:** `editMessageText` without `reply_markup` = keyboard preserved (PTB DEFAULT_NONE). Explicitly passing `reply_markup=None` = keyboard CLEARED. The current code correctly omits reply_markup in `edit_message_text` when status is already ready — that is NOT the bug here.

#### Bug #2 Root Cause — Australia-Egypt FINAL announced 9h late (match ended 22:30 CEST, announced 08:00 next day)
`poll_finished_matches_job` computed `finished_ids = {m.id for m in all_matches if m.status == "FINISHED"}`. The football-data.org free-tier API stayed stuck on `IN_PLAY` for ~9.5h after the match ended. During this entire window the bot polled correctly but found nothing to announce. There was no wall-clock fallback.

**Fix (`src/worldcup_bot/__main__.py`):**
Added `stale_live_ids` computation in the main loop (after the seed pass returns):
```python
now_utc = datetime.now(timezone.utc)
stale_live_ids = {
    m.id for m in all_matches
    if _match_is_over(m, now_utc) and m.status in ("IN_PLAY", "PAUSED")
}
new_ids = (finished_ids | stale_live_ids) - announced
```
`_match_is_over(m, now_utc)` returns True when kickoff was >4h ago (MATCH_OVER_AGE). This caps worst-case delay at 4h from kickoff (~4h after a 90-min match, so ~2.5h from actual FT) regardless of API lag.

**Seed pass consistency:** The first-run seed pass already uses `_match_is_over` to silently seed stale IN_PLAY matches — so after a restart, previously wall-clock-announced matches are already in `announced` and won't re-fire.

**Key gotcha:** Only include `IN_PLAY` and `PAUSED` in the stale check — NOT `TIMED`/`SCHEDULED`. A postponed or future match >4h in the past should not be announced as a final result.

#### Regression tests
- `tests/test_poll_goal_clips_job.py` → `TestKeyboardRetry` (8 tests): tracks keyboard_attached flag, retry loop fires for unattached ready entries, skips already-attached and timeout entries, handles multiple entries, failed retry keeps keyboard_attached falsy for next tick.
- `tests/test_poll_finished_job.py` → `TestWallClockFallback` (6 tests): IN_PLAY >4h announced, PAUSED >4h announced, IN_PLAY <4h NOT announced, TIMED/SCHEDULED >4h NOT announced, already-announced not re-fired, first-run seed still works with stale IN_PLAY.
- **2209 tests total, 0 failures.**

### ✅ Live-Match / Goal-Notification Bug Fix — Schedule-Live Decoupling (awaiting commit)
Fixed the ~1h API-lag gap where football-data.org free tier still reports TIMED after kickoff. Root cause: `get_live_matches()` and `poll_goals_job`'s `relevant` filter both required `IN_PLAY/PAUSED` — so TIMED matches never seeded `live_scores`, the Reddit poller never looked for their thread, and `/endirecto` showed nothing. Added `match_is_schedule_live(match, now_utc)` to `api/client.py` (returns True when: status not terminal, kickoff ≤ now_utc, elapsed ≤ `MATCH_LIVE_WINDOW = timedelta(hours=4)`). Extended `get_live_matches()` and `poll_goals_job` relevant filter; added `"democratic republic of the congo"` alias to `WC_TEAM_ALIASES`. TIMED matches with null scores seed at 0-0 with no announce (existing invariant). **31 new tests; 2102 total, 0 failures.** Decision doc: `.squad/decisions/inbox/kante-live-seeding-fix.md`. **No commit** — David handles.


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
