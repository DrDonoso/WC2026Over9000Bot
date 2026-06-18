# Session Log: Goal Flip-Flop Fix

**Date:** 2026-06-18  
**Commit:** 25643b7  
**Agent:** Kanté  

## Change Summary

FIX: Flip-flop loop in goal notifications caused by shared score state between two detectors.

**Key files:**
- `src/worldcup_bot/reddit/score_state.py` — new `reconcile()` function + `_ahead()` helper
- `src/worldcup_bot/__main__.py` — init `seen_scores` in `build_app`; refactored `poll_goals_job` + `poll_thread_goals_job` to use `reconcile()`
- Tests: 16 new tests across 3 files, 1283 total passing

**Result:** Each detector maintains its own in-memory baseline (`seen`); shared announced score never regresses due to lag. VAR disallowed only when source's own value drops below announced.
