# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 1939 tests ✅

## Current Sessions (2026-06-30)

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
