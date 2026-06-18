# Session Log: Finished-Match Restart Dedup Fix

**Timestamp:** 2026-06-18T09-41-44Z  
**Commit:** 1dcc780  
**Decision:** #42

## Change Summary

Fixed container-restart re-sends of finished-match "🏁 Final" recaps by introducing persistent dedup state (`finished_announced.json`) and kickoff-age seeding (4h threshold).

## Root Cause

Two bugs compounded:
1. In-memory `finished_seen` wiped on restart
2. football-data status lag: match ends hours ago but still shows IN_PLAY at seed time

## Solution

- New `src/worldcup_bot/reddit/finished_state.py`: load/save helpers
- `MATCH_OVER_AGE = timedelta(hours=4)`: seed matches older than 4h as already-handled
- First-run seed marks any FINISHED or kickoff-age-past match as announced
- Per-match persist: each recap send immediately saves state

## Verification

Container restart testing (coordinator verified):
- "seeded 24 already-handled matches (no sends)" logged on each startup
- `finished_announced.json` persisted with 24 match IDs
- Zero "🏁 Final" re-sends across 2 restarts ✅

## Test Coverage

1297 tests passing (+14 new tests for this fix, up from 1283 baseline).
