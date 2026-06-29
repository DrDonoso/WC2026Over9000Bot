# Session Log — Catch-Up Recovery + FINISHED-Eviction Fix

**Date:** 2026-06-27T18:49:00Z  
**Session:** catchup-recovery-fix (spawn manifest coordinated fix session)  
**Coordinator:** drdonoso (repo owner, requested fix)  
**Status:** COMPLETE — GATES PASSED, READY FOR OWNER DECISION  

---

## Scope

Fix live production bugs causing "Me perdí N goles" (missed goal) catch-up messages and post-FT double-notifications on matches like Uruguay-Spain.

**Symptoms:**
- **A** — Missed goal notification (NZL 0-1 BEL) due to API status-flip delay
- **B** — España goal announced twice (live + at/after FT), confirmed root cause: post-FT VAR oscillation
- **C** — 4-goal catch-up (NOR 1-3 FRA) due to bot restart mid-match

---

## Agents & Roles

| Agent | Type | Model | Role | Status |
|-------|------|-------|------|--------|
| kante-4 | Backend | Sonnet | Investigation | ✅ Complete |
| pirlo-4 | Lead | Opus | Design decisions | ✅ Complete |
| kante-5 | Backend | Sonnet | Implementation | ✅ Complete |
| pirlo-5 | Lead | Opus | Implementation review | ✅ Complete |
| buffon-4 | QA | Sonnet | QA gate | ✅ Complete |

---

## Fixes Implemented

### 1. Seed at 0-0 at Kickoff
Eliminates Symptom A (missed goals during API status-flip lag). When `poll_kickoff_job` sends kickoff notice, it also seeds `live_scores[mid] = {0,0}` so the first API poll sees a 0→1 incremental delta.

### 2. Recover Scorer + Video from Thread
Upgrades catch-up notifications from neutral "⚠️ Me perdí N goles" to proper per-goal notifications with scorer, minute, and "Ver gol" button — by extracting real goal events from the Reddit match thread.

**Fallback:** If thread unavailable or goals can't be matched, emit neutral catch-up. **Rule:** ALL-proper or ALL-neutral, never mixed.

### 3. FINISHED Two-Tick Eviction
Prevents post-FT oscillation loops (Symptom B). Evicts match after first FINISHED tick with no new delta, so repeated thread oscillations don't trigger re-announces.

### 4. Immediate Save in Thread Job
Closes save-window race (Symptom B candidate): `save_scores` now called inside `goal_lock` immediately after score claim, not deferred to end of loop.

---

## Test Results

| Phase | Count | Delta |
|-------|-------|-------|
| Baseline (before session) | 1644 | — |
| After Kante-5 implementation | 1661 | +17 new tests |
| After Buffon-4 QA additions | 1665 | +4 edge-case tests |

**All tests pass, 5 pre-existing warnings.**

---

## Gates

✅ **Pirlo-5 (Implementation Review):** APPROVED — no required changes  
✅ **Buffon-4 (QA Gate):** PASS WITH ADDED TESTS (+4) — all hazards resolved  

---

## Files Changed

**Scribe bookkeeping only:**
- `.squad/decisions.md` — merged 5 inbox files (+17 KB)
- `.squad/orchestration-log/` — 5 new agent logs
- `.squad/log/` — this session log

**Source changes (NOT committed by Scribe):**
- `src/worldcup_bot/__main__.py` — poll_kickoff_job, poll_goals_job, poll_thread_goals_job, _attempt_goal_recovery, _process_goal_delta
- `src/worldcup_bot/reddit/score_state.py` — GoalDelta fields
- `src/worldcup_bot/reddit/scanner.py` — timeout reduction
- `tests/test_poll_*.py` — +21 new tests

---

## Owner Decision Required

**Source code fix is ready for commit.** Coordinator awaits owner confirmation:
- `git add src/ tests/`
- `git commit -m "feat: recover missed goals from thread + FINISHED eviction (fix #catch-up-recovery-2026-06-27)"`

Scribe has committed .squad/ bookkeeping changes independently.

---

## Notes

- B root cause confirmed: Uruguay-Spain post-FT timeline shows VAR oscillation in <4h window (❌ then ⚽)
- Two-tick eviction specifically designed to prevent this pattern going forward
- Recovery fall back path guarantees owner always receives a notification (proper if thread available, neutral if not)
