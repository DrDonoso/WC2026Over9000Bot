# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Recent Sessions (2026-06-26 onwards)

### 2026-06-26 — TVE 📺 Label Fix — Review Gate (APPROVED)

**Session:** TVE daily-update fix, kante-2 implementation  
**Status:** APPROVED — no required code changes

**Decisions reviewed:**
1. Same-day TLA-pair fallback — SAFE (unique pairing per UTC date in tournament)
2. Cache redesign (no-cache-on-all-fail, 30-min TTL for empty, 6h for populated) — SOUND
3. Residual timing issue (09:00 fires before RTVE publishes ~10:40) — RECOMMENDED: move `daily_update_hour` to 11:00

**Recommendation:** Move `DAILY_UPDATE_HOUR` to 11:00 (env-configurable, no code change needed). Owner discretionary.

**Test count:** 1629 passed (1618 baseline + 11 new from Kanté/Buffon)
- **Scoring:** Groups = 3pts exact position, 1pt off-by-one. Knockout = per-stage configurable points per correct qualifier (1/1/2/3/5). General = base_score + groups + all knockout stages.
- **WC2026:** 48 teams, 12 groups (A–L), 5 knockout rounds (Round of 32, R16, QF, SF, Final).
- **All legacy commands preserved.** Added `/ronda32`, `/semis`, `/final`. Renamed `/euroPorraDiaria` → `/porra`.
- **`/listaaciertos` now auto-detects caller** by Telegram username (no arg needed for own predictions).
- **Key learning:** User wants simplicity — YAML file editable live on host, no DB, no complex flows. The bot is a *reader* of pre-submitted predictions, not a prediction submission system.

**Role:** Lead reviewer for Kanté's best-thirds implementation.

**Key decisions locked:**
1. Scoring model coherence — all 7 cases correctly implement STRICT policy (non-qualifying exact-3rd → 0.0).
2. Provisional handling KEEP AS-IS — code already computes best-8-of-available once ≥9 thirds exist (better than doc describes).
3. Tiebreaker fallback acceptable — stable alphabetical (group+TLA) with WARNING for FIFA disciplinary/drawing-of-lots unavailability.
4. Backward-compat seam low-risk — all callers explicitly build and pass `qualifying_thirds`.

**Outcome:** APPROVE. Ready for Buffon QA gate.

**Buffon added 5 regression tests** (TestQualifyingThirdsCallerRegression) to guard against callers dropping `qualifying_thirds` param. Coverage gap closed.

### 2026-06-27 — Catch-Up Recovery + FINISHED-Eviction Fix — Design & Review Gates

**Session:** kante-4 (investigation) → pirlo-4 (design) → kante-5 (implementation) → pirlo-5 (review) → buffon-4 (QA)  
**Status:** GATES PASSED (Pirlo-5 APPROVE, Buffon-4 PASS WITH ADDED TESTS +4)

**Pirlo-4 Design Role:**
- Reviewed Kanté's investigation of three production symptoms (A: missed goals, B: Spain double-notify, C: 4-goal catch-up)
- Issued two key design decisions:
  1. **Goal recovery from thread (revises 2026-06-26 Decision 1):** Attempt to extract real goal events from Reddit match thread and emit proper per-goal notifications (scorer + "Ver gol" keyboard). Fallback to neutral "Me perdí N goles" only if thread unavailable or goals can't be matched. Rule: ALL-proper or ALL-neutral, never mixed.
  2. **Seed at 0-0 + FINISHED two-tick eviction:** Seed `live_scores` at 0-0 when kickoff fires (poll_kickoff_job). Evict FINISHED matches after first processed tick with no delta (two-tick minimum, prevents post-FT oscillation).

**Pirlo-5 Review (Implementation Gate):**
- Verified deduplication safety: first-seen recovery + concurrent thread job = no duplicate-announce window
- Verified two-tick eviction correct: first FINISHED (status update), second FINISHED (evict if no delta)
- Verified recovery fallback strict (ALL-proper or ALL-neutral)
- Verified hang safety bounded (~35s worst-case, acceptable for one-time event per match)
- Confirmed no regression with recap job or real in-play VAR

**Outcome:** APPROVE — Implementation is correct, matches design spec, well-tested.

---

### 2026-06-27 — Finished-Match Goal Loop Fix (Egypt-Iran) — Review Gate

**Session:** kante-3 implementation + pirlo-3 review  
**Status:** APPROVED — no required code changes

**Reviewed:** Kanté's `_match_is_over` wall-clock guard for stuck goal-polling loop.

**Key approvals:**
1. 4h threshold is correct (ET+penalties fit comfortably, margin safe)
2. Prune safety verified (no interaction with recap job)
3. Concurrency atomic (no interleaving on single-threaded asyncio)
4. Error path safe (date parse failure → match stays live)

**Verdict:** APPROVE — fix is correct, minimal, safe. Ship it.

### 2026-06-30 — LLM Chat Features Design (Picante + Revive Inactive)

**Session:** pirlo design/refinement for two new LLM-powered chat features  
**Status:** PROPOSED — awaiting David's decisions

**Key architectural decisions:**
1. New `src/worldcup_bot/chat/` package with clean separation: `listener.py` (Telegram), `picante.py` / `revive.py` (LLM orchestration), `buffer.py` / `state.py` (pure state).
2. **Privacy stance:** In-memory ring buffer ONLY for message text. NO message bodies persisted to disk. Only `last_seen`, `last_mentioned`, and cooldown metadata saved as JSON.
3. Both features independently toggleable via `CHAT_PICANTE_ENABLED` / `CHAT_REVIVE_ENABLED` env vars (default: False).
4. Reuses existing `AIClient` and `OPENAI_*` config — no new API credentials needed.
5. **Blocking infra requirement:** Bot privacy mode must be DISABLED in BotFather + bot re-added to group.
6. MessageHandler with `TEXT & ~COMMAND & GROUPS` filter, registered after existing CommandHandlers in `build_app()`.
7. Rate limiting: per-message probability + cooldown timestamp + daily counter (picante); periodic job + per-user mention cooldown + rotation (revive).

**Open decisions document:** `.squad/decisions/inbox/pirlo-llm-chat-features.md`

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

---

## Follow-Up Session: 2026-06-30 — Revive Quiet Hours + Jitter Self-Rescheduling (commit 31f1a89)

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

---

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

