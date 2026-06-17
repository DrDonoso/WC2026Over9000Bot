# Session Log: Streamff Mirrors + Thread-Based Early Goal Detection

**Date:** 2026-06-17  
**Commit:** b61013a on origin/main  
**Status:** PUBLISHED + LIVE (Coordinator verified)  

## Highlights

1. **Streamff Mirror Coverage:** Broadened regex + host check. All streamff TLDs (`.com`, `.link`, `.pro`, `.gg`, `.one`, `.top`, etc.) now route to `https://cdn.streamff.one/{id}.mp4`.

2. **Thread-Based Early Goal Detection:** New `poll_thread_goals_job` (25s interval) uses Reddit match thread events as faster signal than football-data (60s). Shared in-memory score dict ensures race-free dedup with football-data poll.

3. **Extracted Shared Helper:** `_notify_goal` factored out for use by both goal sources. Thread path uses scorer from Reddit directly (no OpenAI call).

4. **Test Coverage:** 19 new tests covering all paths. Baseline 1248 → 1267 passing.

## Coordination Notes

- **Upstream:** Coordinator live-tested both fixes before publication
- **Evidence:** England 3-2 Croatia notification from thread observed before football-data confirm
- **Download:** Verified 27MB clip from streamff.pro via CDN routing
