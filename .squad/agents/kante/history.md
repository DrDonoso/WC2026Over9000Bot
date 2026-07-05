# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2346 tests ✅

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

## Previous Sessions (2026-06-30 and earlier)
