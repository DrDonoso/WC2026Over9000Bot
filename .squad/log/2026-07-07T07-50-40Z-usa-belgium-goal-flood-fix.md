# Session Log: USA-Belgium Goal-Flood Cross-Source Fix

**Date:** 2026-07-07T07:50:40Z  
**Scope:** Root cause, implementation, testing, review, deployment  
**Commit:** 22f4ce9  
**Status:** ✅ SHIPPED (deployed to Docker Hub)  

---

## Incident

**USA vs Belgium** match (2026-07-06) generated 100+ alternating "⚽ GOOOOL!" and "❌ Gol anulado" messages in the live match thread.

---

## Root Cause

Cross-source score reconciliation bug in `reconcile()`:

1. Thread source announces goal (1-0) → `seen_thread={1,0}`, `seen_api={0,0}` (API lagged)
2. Thread announces disallowed (VAR) → `announced={0,0}`, `seen_thread={0,0}`
3. API later catches up to 1-0 (delayed API response)
4. `reconcile()` sees `_ahead(1-0, 0-0) = True` → treats as NEW goal
5. Announces goal → immediately catches up to disallowed
6. Loop repeats every API poll (~60s) for duration of VAR delay

**Blast Radius:** Any future match with VAR reversal delayed inside one API poll window triggers the same loop.

---

## Solution

Advanced the lagging source's `seen` baseline to the pre-VAR announced score using `max()` (never decrease), executed inside `goal_lock`.

### Files Changed

- `src/worldcup_bot/__main__.py`: poll_goals_job + poll_thread_goals_job (both sources)

### Tests Added

Four regression tests in `tests/test_poll_thread_goals_job.py::TestVARCrossSourceRaceRegression`:

1. test_thread_fast_api_lag_var_no_false_goal
2. test_api_fast_thread_lag_var_no_false_goal
3. test_thread_fast_real_goal_after_var_not_suppressed
4. test_api_fast_real_goal_after_var_not_suppressed

**Empirical Proof:** Tests fail red without fix (phantom oscillation), pass green with fix.

### Review Verdict

**Lead:** Pirlo (approved 2026-07-07)

Verified:
- No over-suppression (seen naturally drops back when lagging source catches up)
- ann_homeaway is the pre-VAR score
- max() correctness per-component
- Lock/concurrency safety
- Symmetry across both sources
- All 4 regression tests satisfy follow-up requirement

**Full suite:** 2365 passed, 0 failures

---

## Deployment

- **Committed:** 22f4ce9 (fix + tests, Co-authored-by Copilot)
- **Pushed:** origin/main
- **CI:** "Build and Deploy Docker Image" triggered
- **Status:** ✅ Deployed to Docker Hub

---

## Team Contribution

- **Kanté** (Backend): Root-cause analysis + implementation
- **Buffon** (QA): Regression test coverage with empirical proof
- **Pirlo** (Lead): Review gate + approval
- **Coordinator:** Commit + push + deployment trigger

---

