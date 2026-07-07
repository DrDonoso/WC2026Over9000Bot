# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Recent Sessions (2026-06-26 onwards)

### 2026-07-07 — USA-Belgium VAR Reconcile Fix Review — PENDING

**Role:** Lead reviewer. Urgent concurrency fix awaiting go-ahead.

**Incident:** USA-Belgium match (2026-07-06) triggered 100+ alternating goal/disallowed messages — cross-source score reconciliation bug in reconcile() (score_state.py:220–241).

**Root cause:** When source A (Reddit thread, ~25s) announces VAR-disallowed goal before source B (API, ~60s) has ever seen the goal, B's delayed catch-up to the brief high score is mistaken for a brand-new goal → false goal announcement → catches up to disallowed → false disallowed announcement → loop repeats every ~60s.

**Proposed fix:** On processing disallowed delta, advance the OTHER source's seen baseline to pre-VAR announced score using max() (never decrease):
- poll_thread_goals_job: advance api_seen after thread disallowed
- poll_goals_job: advance thread_seen after API disallowed

**Files to review:** score_state.py (reconcile ~137, _ahead ~220–241), __main__.py (poll_thread_goals_job ~1204, poll_goals_job ~996)

**Blast radius:** Any future match with VAR reversal where thread is ahead of API.

**Status:** ⏳ PENDING — awaiting DrDonoso go-ahead + Kanté implementation. Test coverage gap flagged: existing test (line 518) doesn't cover seen_api below pre-goal score.

**Cross-team:** Buffon incoming regression test (`test_thread_disallowed_then_lagging_api_catchup_no_false_goal`). May require concurrency safeguards (potential future Buffon coordination).

### 2026-07-03 — Post-Final VAR Score Correction Watch — APPROVED

**Role:** Lead reviewer. Approved VAR correction watch architecture (6 concurrency checks: no double-correction, no false-correction, window/prune safety, edit safety, no regression). 2165 tests pass. Decision merged to decisions.md. Ship it.

### 2026-07-03 — TVE Knockout-Round Prefix + Midnight Notation Fix — APPROVED

**Role:** Lead reviewer. Approved round-prefix regex (anchored `^`, trailing `\s+`) and over-midnight hour rollover (identity-safe for hour<24). 2157 tests pass.

### 2026-07-02 — "Ver gol" Button Clip-Pipeline Fix — APPROVED

**Role:** Lead reviewer. Approved narrowly-scoped search-term normalization (USA alias) and timeout bump (25→40 attempts). No regression: post-fetch matching unchanged. 2134 tests pass.

### 2026-07-01 — Schedule-Live Seeding Fix — APPROVED

**Review gate:** 6 concurrency/correctness checks (double-announce, false-disallowed, window consistency, over-inclusion, null-safety, no regression). All PASS.

### 2026-06-30 — LLM Chat Features Implementation Review (APPROVED)

**Session:** Kanté implementation review (pirlo reviewer gate)  
**Status:** APPROVED — no blocking issues

**Reviewed files:** `chat/__init__.py`, `buffer.py`, `state.py`, `listener.py`, `picante.py`, `revive.py`, `config.py` additions, `__main__.py` wiring.

**Key verification points:**
1. All 10 checklist items PASS — filtering, rate limiting, privacy, candidate set, concurrency, resilience, zero-overhead when disabled, guardrails, mention construction, param fidelity.
2. Gate function purity enables comprehensive unit testing without mocks.
3. AIError/Exception catch-all in both features prevents LLM flakiness from crashing message processing.
4. Daily cap reset uses local timezone (`pytz.timezone(settings.timezone)`) for calendar day — correct for the Madrid-based group.
5. Revive candidate rotation wraps correctly with modulo; seeding at startup prevents day-1 spam.

**Learning:** Pure gate functions (probability, cooldown, daily_cap, min_buffer) separated from Telegram I/O orchestrators is an effective pattern — makes correctness obvious at review time and testable without PTB mocks.

### 2026-06-30 — Revive Quiet Hours + Jitter Self-Rescheduling Review (APPROVED)

**Session:** Kanté implementation review (pirlo reviewer gate)  
**Status:** APPROVED — no blocking issues

**Reviewed:** Self-rescheduling `run_once` loop replacing `run_repeating`, quiet-hours guard (23:00–06:00 local), ±jitter on base interval.

**Key verification points:**
1. `is_quiet_hours` correctly handles midnight wrap (`hour >= start OR hour < end`) and same-day (`start <= hour < end`). Start inclusive, end exclusive, consistent.
2. `next_revive_delay` guarantees post-quiet spread is additive-only (`rand(0, jitter)`) — cannot push wake backwards into the quiet window.
3. `finally` block reschedules on ALL exit paths (success, quiet-skip, no-candidates, AIError, Exception) — chain never silently dies while enabled.
4. `settings is not None and revive_enabled(settings)` guard in finally correctly stops the chain when feature is disabled.
5. `run_once` one-shot semantics prevent job accumulation — exactly one pending job at any time.

**Learning:** Self-rescheduling `run_once` loops with `finally`-based reschedule are more robust than `run_repeating` for jobs with variable timing — the `settings: T | None = None` pre-try pattern makes the finally guard safe against early KeyError failures.

### 2026-06-30 — LLM Chat Features Shipped (Picante + Revive)

**Event:** Successful team delivery of two LLM-driven group-chat features.

**Role:** Lead coordination + design gate + implementation review gate.

**Deliverables:**
- ✅ Design spec locked (13 open Qs → David's approval)
- ✅ Implementation review gate (Kanté) — APPROVED (all 10 checklist items PASS)
- ✅ QA gate (Buffon) — PASS WITH ADDED TESTS (+107 edge-case tests, 0 bugs)
- ✅ DevOps coordination (Maldini) — 12 env vars wired, README privacy-mode section

**Final status:** All 4 agent deliverables complete. Test suite: 1875 total (1768 + 107 new). Ready for deployment (if privacy mode disabled first).

**Key leadership decision locked:** Candidate set = PORRA PARTICIPANTS ONLY (override of initial "anyone who spoke" recommendation). Rationale: keeps porra-internal data off Revive targeting; participants are the intended audience.

**Blocking pre-deployment requirement documented:** BotFather privacy mode MUST be disabled. Failure mode obvious: features ship in code but produce zero group messages received because API gating blocks them. This requirement now lives in README with step-by-step setup instructions.

### 2026-06-30 — Revive Quiet Hours + Jitter Self-Rescheduling (commit 31f1a89)

**Team:** Kanté (Backend) + Maldini (DevOps) + Buffon (Testing) + Pirlo (Lead Review)  
**Shipped:** ✅ commit 31f1a89

**Pirlo's lead review & approval:**
- Comprehensive 8-item technical checklist:
  1. is_quiet_hours midnight wrap logic → correct (start inclusive, end exclusive)
  2. next_revive_delay correctness → next run guaranteed outside quiet hours
  3. Self-reschedule robustness → all exit paths covered (success, quiet-skip, no-candidates, AIError, Exception)
  4. JobQueue hygiene → at most 1 pending "revive_inactive" job at any time
  5. Initial schedule in __main__ → first run randomized + quiet-aware
  6. Picante untouched → zero side effects to other features
  7. David's spec fidelity → quiet 23–06 ✓, jitter ±45min ✓, base 4h ✓
  8. Test suite green → 1883 baseline + 53 new tests = 1936 passed, 0 failed

**Verdict:** ✅ **APPROVE** — Ship it

**Design quality notes documented:**
- Injectable rand() parameter excellent for deterministic testing
- settings: Settings | None = None pattern is clean and safe
- Spread after quiet_end prevents thundering herd (scales well for multi-instance)
- Double-layer quiet protection (delay calculation + runtime guard) is robust

**Leadership sign-off:** Self-rescheduling loop is bulletproof. Quiet-hours math is correct. Jitter guarantee holds. Chain cannot silently die while revive is enabled.

### 2026-06-30 — ChatState Eager Persistence Review (APPROVED)

**Session:** Kanté implementation review (pirlo reviewer gate)  
**Status:** APPROVED — ready to commit (merged to decisions.md)

**Reviewed:** Startup save + per-message save of `chat_state.json`. Ensures `last_seen` survives restarts.

**Key verification:** Placement correct (startup after seeding, step 7 before picante), guards safe (`.get()` + truthiness), best-effort resilience, privacy unchanged, atomic writes acceptable, suite green (1939 passed).

**Verdict:** ✅ **APPROVE** — Minimal, correct, well-guarded change. Ship it.

### 2026-07-01 — Podium Photo Feature: Feasibility + Implementation Review

**Session:** podium-feasibility (design) → podium-implementation (review)  
**Status:** ✅ FEASIBILITY APPROVED → ✅ IMPLEMENTATION APPROVED (committed 4343ddb)

**Pirlo roles:**
1. **Feasibility Assessment:** Evaluated merging tied photos (Option A, album-based) vs. single podium image (Option B, Pillow canvas). Recommendation: Option B — visually impactful, tie-aware layout, lower complexity than expected.
2. **Implementation Review Gate:** Verified Kanté's render_podium module + handlers integration.

**Key Design Decisions (Locked):**
- Single podium image always (replaces album, no branching on ties)
- Missing photos → placeholder (solid color + initials) ensuring image always renders
- Crown drawn programmatically with Pillow (no external PNG asset)
- Font from matplotlib `findfont` (no new deps, Docker-safe)
- Fallback chain: podium → album → text (graceful degradation)
- Tie-aware y-offsets: positions 1→205px, 2→237px, 3→257px

**Review Checklist (8/8 PASS):**
1. ✅ Fallback chain correct and tested
2. ✅ Non-blocking (asyncio.to_thread)
3. ✅ Never raises (all exceptions caught)
4. ✅ Tie-aware via standard_competition_positions
5. ✅ Caption handling (1024-char limit + overflow)
6. ✅ No new deps / no external assets
7. ✅ Missing-photo fallback robust
8. ✅ Test suite green (1968 baseline + 45 edge cases by Buffon = 2013 total)

**Verdict:** ✅ **APPROVE** — Implementation matches spec exactly. Tie logic correct. Fallback chain robust. Buffon's 45 edge-case tests all pass. Ready to ship.

**Design lessons:**
- Crown asset decision (draw vs. bundle PNG) was right call — reduced repo bloat, copyright-safe
- Font resolution pattern (matplotlib findfont + fallback) is reusable for future text-rendering needs
- Separating render_podium as pure sync function (called via asyncio.to_thread) allows deterministic testing without mocking async machinery

### 2026-07-01 — Crown Asset Integration Review (APPROVED)

**Session:** Crown asset swap (hand-drawn → Noto Emoji bundled PNG)  
**Status:** ✅ APPROVED (shipped commit e53b8a5)

**Pirlo lead review:** Verified asset loader (importlib.resources PEP 451), fallback dispatch, packaging (wheel verified), attribution (Apache 2.0), test suite green (2018 passed, 5 new crown tests). **Verdict: APPROVE** — ship it.

### 2026-07-01 — Podium Drawn-Base Layout Review (APPROVED)

**Session:** Kanté implementation review (podium rewrite with 3-block drawn base)  
**Status:** ✅ APPROVED (shipped commit 277ae2e)

**Pirlo lead review:** 6-item checklist all pass — never-raises, tie-aware blocks, robust n=1/n=2/placeholders, no dead code, constants tunable, 2018 tests green + David visual QA confirmed. **Verdict: APPROVE** — ship it.
