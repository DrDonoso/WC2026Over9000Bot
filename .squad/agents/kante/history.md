# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2351 tests ✅

## Learnings

### 2026-07-08 — KO draw-deferral fix (Switzerland 0-0 Colombia false notification)

**Bug:** `match_result_is_final` only deferred when `duration == "PENALTY_SHOOTOUT"`. football-data's free tier initially reports a 0-0 KO match as `FINISHED` with `duration="REGULAR"` and `winner="DRAW"` (or `None`), before later setting `duration="PENALTY_SHOOTOUT"` and populating the penalties block. The old gate returned `True` immediately → the wrong bare "0-0" Final notification fired.

**Fix:** Added module-level `_KNOCKOUT_STAGE_NAMES` frozenset (derived from `KNOCKOUT_STAGES` + `"THIRD_PLACE"`) in `formatters.py`. New branch in `match_result_is_final`: if `match.stage in _KNOCKOUT_STAGE_NAMES` and `match.winner not in ("HOME_TEAM", "AWAY_TEAM")` → return `False`. Group-stage draws (winner=`"DRAW"`) are still valid finals and return `True` unchanged.

**Key invariant:** A KO match can NEVER legitimately end level — so any FINISHED KO match without a decisive winner is still mid-processing at the API tier. The existing deferral loop in `__main__.py:1858-1869` retries without marking the match announced, so it self-corrects on the next tick once the API populates the winner + penalties.

**Files changed:** `src/worldcup_bot/bot/formatters.py` only. `THIRD_PLACE` included cheaply since it's also single-elimination. Tests: 161 tests in `test_formatters.py` + `test_poll_finished_job.py` all green (no new tests written — Buffon owns that).

**Gotcha:** The module docstring says "Depends only on data/tla_map" — now also imports `data/stages`. Both are pure data modules; no circular dependency risk.



### 2026-07-08 — Rich image birthday mode

**Feature:** On July 8 each year, `run_rich_iteration` enters birthday mode — the image still wealth-escalates but also gets a lavish birthday-party theme (cake showing the age, balloons, banner). Caption also celebrates the birthday. Age auto-increments from `RICH_BIRTH_YEAR = 1984`; turns 42 in 2026 (meaning-of-life gag).

**Key file:** `src/worldcup_bot/ai/rich_image.py`  
- Constants added at ~line 125: `RICH_BIRTHDAY_MONTH`, `RICH_BIRTHDAY_DAY`, `RICH_BIRTH_YEAR`, `RICH_BIRTHDAY_CLAUSE`  
- Pure helpers at ~line 138: `is_rich_birthday(now)`, `rich_birthday_age(now)`  
- `build_rich_prompt` — new `birthday=False, age=None` params; birthday clause appended BEFORE anchor clause  
- `generate_rich_caption` — new `birthday=False, age=None` kwargs; birthday instruction injected BEFORE JSON format part  
- `run_rich_iteration` — computes birthday/age after `now`, logs info when active, passes to both functions; fallback caption is birthday-themed when active

**Test fragility to flag:** 3 pre-existing tests (`test_caption_falls_back_when_caption_client_raises`, `test_caption_falls_back_when_chat_not_configured`, `test_caption_error_memo_not_appended_image_still_written`) call `run_rich_iteration` without pinning `_now`. They fail on July 8 every year because birthday mode fires and the fallback caption changes. Buffon must add `_now=datetime(year, 3, 15, ...)` (any non-July-8 date) to those 3 tests for date independence.

## 2026-07-05 Summary (REJECTED & REWORKED)

**Sessions 2026-07-01 → 2026-07-04 evening:** Multiple /elecciones increments submitted (hourglass UX, circular flags, groups image + eviction + split) and production keyboard/FINAL fixes. 

**Status:**
- ✅ /elecciones command MVP (38e00b2) — approved-with-followups, 79 tests
- 🔴 Production bug fixes (a61757d) — REJECTED by Pirlo (Bug #2: stale wall-clock final score risk)
  - Revisions: Cannavaro (615c34e, rejected seed-path bug), Nesta (1b4045b, approved)
- 🔴 /elecciones increment 2 (7a0dcfc) — REJECTED by Pirlo (cache staleness + split ≤4096 blockers)
  - Revision: Nesta (5df06de, approved-with-followups, 115 tests)
- 🔴 /elecciones hourglass (8922308) — REJECTED (depends on increment 2 fix)

**Key pattern:** All rejected features were reworked by different agents (Cannavaro/Nesta) and passed on re-submission. Pirlo identified three blockers across three separate rejects; all three fixed in final revisions.

## Production Bug Learnings (2026-07-04)

### Keyboard Retry Unbounded Loop (a61757d, Bug #1)
**Root:** `poll_goal_clips_job` set `status="ready"` before `edit_message_reply_markup` retry. Early return blocked retry when no searching entries existed.
**Fix:** `keyboard_attached` field + compute `pending_retry` BEFORE early-return + iterate until success.
**Gotcha:** Early-return placement above retry logic makes retry dead code on zero-search ticks.

### FINAL Wall-Clock Fallback Can Announce Wrong Score (a61757d, Bug #2 → fixed by Nesta)
**Root:** Stale `IN_PLAY`/`PAUSED` >4h announced final from unfinialized score; `PAUSED` treated as final despite resumable suspensions.
**Fixed path:** Separate provisional vs official split (provisional = temporary notice, never consumes `finished_announced`); FINISHED-only invariant on all seed writes.

## /Elecciones Architecture Revisions

### Cache Staleness Blocker (30919a7 → 5df06de, Nesta's fix)
**Problem:** Cache key only hashed `get_stage_results()` (finished matches). "Cuadro no disponible" served until first match finished, even after ties were scheduled.
**Fix:** Include scheduled tie identity from `get_all_matches()` + non-FINISHED results in cache version hash.

### Message Split ≤4096 Blocker (30919a7 → 5df06de, Nesta's fix)
**Problem:** `_split_messages` added header/prefix/separators AFTER `_split_block_at_lines`, causing final message length to exceed 4096.
**Fix:** Reserve header budget upfront; pre-split blocks to `4096 - header - prefix`; hard-split single oversized lines at char boundary.

## Key Gotchas (from this sprint)

## 2026-07-06 — Clip Fallback Fix (SHIPPED)

Fixed regression where `find_goal_clip` skipped HTML fallback when Reddit's JSON search returned HTTP 200 with empty `children` list (soft-block on datacenter IPs).

**Problem:** `posts is None` gate only caught hard 403, not empty `[]` from soft-block. Mexico vs England match (5 goals) had no clip buttons.

**Root:** Datacenter IPs get HTTP 200-empty from Reddit; residential IPs get 403. Code gated fallback on `posts is None` → soft-block path never consulted HTML.

**Fix:** Normalize with `or []`, then unconditional fallback when no JSON match found. Two log lines distinguish "no posts" from "posts but no match" for diagnostics.

**Tests:** 5 new regression tests in `TestFindGoalClipFallbackBehavior` (empty JSON, None JSON, non-matching JSON, happy path no-fallback, no-match-anywhere). All 2351 tests green.

**Commit:** 4766a02

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
Text + image renderers (knockout + groups), phase keyboard, `CHOICES_TYPE` env var, bounded cache. **2310 tests** (79 new for elecciones). Pirlo approved-with-followups.

**Approvals & Rejections (summary):**
- 38e00b2: /elecciones MVP approved-with-followups
- a61757d: keyboard retry + FINAL wall-clock fix REJECTED (Bug #2: stale score risk)
- 7a0dcfc: groups increment REJECTED (cache staleness + split blockers)
- 8922308: hourglass REJECTED (depends on groups fix)
- **Fixes:** Cannavaro/Nesta fixed a61757d + 7a0dcfc; both re-approved

**Key gotchas (elecciones):**
- `InlineKeyboardButton` not in handlers imports — check telegram imports.
- `_split_messages` cannot split within user block; threshold is soft for Telegram 4096 limit.
- Lazy imports in callback: patch target = `worldcup_bot.porra.elecciones.*`.
- Twemoji URL is jsDelivr (GitHub-hosted); non-2-char ISO codes → None → TLA fallback.

## 2026-07-07 — USA-Belgium Goal Flood Incident (Post-Mortem)

### Root cause: cross-source seen-baseline mismatch after a thread-sourced disallowed

**Symptom:** 100+ alternating "⚽ GOOOOL! 1-0" / "❌ Gol anulado (VAR) — 0-0" messages sent during the USA-Belgium match.

**Bug:** When Source A (Reddit thread, ~25s) announces BOTH a goal AND its disallowed before Source B (football-data API, ~60s) has polled even once, `seen_api` stays at the pre-goal score. After the thread disallowed resets `announced` back down, `seen_api == announced` (both at the old low). When the API eventually catches up to the brief high score, `reconcile()` sees `_ahead(new, ann)` = True (score_state.py line 220) and fires a **false goal**. Then when the API catches up to the VAR score, it fires a **false disallowed**. If the API is unstable during the review, this cycle repeats indefinitely — every ~60s.

**Key files and lines:**
- `src/worldcup_bot/reddit/score_state.py:220–241` — `_ahead(new, ann)` branch that fires the false goal
- `src/worldcup_bot/__main__.py:931–998` — `poll_goals_job` lock section (missing: reset thread's `seen` after disallowed)
- `src/worldcup_bot/__main__.py:1169–1207` — `poll_thread_goals_job` lock section (missing: reset API's `seen` after disallowed)

**Why this match:** Thread was fast enough to see goal+VAR in <60s. API was still behind on both events. The brief score that was disallowed looked like a "new goal" from the API's perspective.

**Why existing tests missed it:** `test_real_var_thread_goal_then_disallowed` sets `seen_api` to the pre-goal score (synchronized). The bug requires `seen_api` to be BELOW the pre-goal score when the disallowed fires — a distinct and untested case.

**Fix direction:** After any disallowed (in either job, inside the lock), advance the OTHER source's `seen` to the pre-VAR announced score (`ann_homeaway` = the score that was disallowed). Use `max(current, ann_homeaway)` — never decrease. This marks the brief high score as "already seen" by the lagging source.

**Blast radius:** Any future match with a VAR reversal where the thread is faster than the API. Routine scenario — HIGH urgency.

**Incident report:** `.squad/decisions/inbox/kante-usa-belgium-goal-flood.md`  
**Skill:** `.squad/skills/two-source-score-reconciliation/SKILL.md`

---

## 2026-07-06 Summary — Empty-JSON Fallback Fix

**Bug:** All 5 Mexico-England goals notified, none got "Ver gol" button on server.

**Root cause:** `find_goal_clip` in `clip_finder.py` only ran the HTML search + `/new/` fallback when `_fetch_search_posts` returned `None` (hard 403). Reddit soft-blocks datacenter IPs with HTTP 200 + empty `children` list → `posts == []` → `if posts is None` skipped → empty loop → all clips missed.

**Fix:** `or []` to normalise `None`/`[]`; try JSON posts first (return early if matched → efficiency preserved); always fall through to HTML fallback when no JSON match. Two INFO logs distinguish "no posts" vs "non-matching posts" for diagnosability.

**Tests:** 5 new in `TestFindGoalClipFallbackBehavior` — key regression (empty JSON → fallback), None path, non-matching JSON, happy-path efficiency (HTML not called), no-match-anywhere. **2346 → 2351, all green.**

**Live results (MEX-ENG 5 goals):** All 5 → `streamin.link` URLs. No regression.

**Key gotcha:** Reddit soft-blocks return 200-empty, not 403. The `is None` guard is insufficient — must also treat `[]` as a fallback trigger. The `or []` idiom handles both cases uniformly.

## Previous Sessions (2026-06-30 and earlier)
