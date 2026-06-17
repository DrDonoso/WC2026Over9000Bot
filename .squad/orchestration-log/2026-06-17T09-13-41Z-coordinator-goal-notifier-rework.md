# Orchestration Log: Goal Notifier & Match-Finish Rework

**Timestamp:** 2026-06-17T09:13:41Z  
**Agent:** Coordinator (Scribe Merge)  
**Commit Reference:** 48edda9  
**Release:** 20260617.04

## Spawn Manifest Summary

This entry summarizes the 5 interconnected decisions (Blocks 1–4) committed as 48edda9 and released via CI/CD to 20260617.04.

### Block 1: Goal Detection Rework (Decision #37)
- **Goal source:** Switched from Reddit parse-only to **football-data.org score changes** (authoritative).
- **Enrichment:** OpenAI `goal_extractor.py` handles any Reddit thread format (ESPN-structured OR human-narrated).
- **Persistence:** `reddit/score_state.py` maintains `live_scores.json` with match deltas.
- **Result:** Fixed France-Senegal narrated-format miss + Austria-Jordania flip-flop.
- **Test count:** 789 passing (56 new).

### Block 2: Decoupled Clip Flow (Decision #38)
- **Flow change:** Goal message sent immediately WITHOUT "Ver gol" button; background job adds button once clip is ready.
- **Persistence:** `reddit/clip_store.py` manages `goal_clips.json` with per-goal state (searching → ready → timeout).
- **Job:** `poll_goal_clips_job` (45s) finds + downloads clips, edits message with button.
- **Restart-resilient:** "ready" entries work immediately; "searching" entries resume.
- **Verified live:** Downloaded real Mbappé clip (16MB) to volume + added button.
- **Test count:** 826 passing (37 new).

### Block 3: Match-Finish Final Result + Always-Porra (Decision #39, #40)
- **Final result:** `🏁 Final` section always posted, regardless of ESPN/porra availability.
- **Porra commentary:** Always generated when `ai_enabled` + `bool(ranking)`, even if ranking didn't move.
- **Context:** `render_porra_context` shows current top-5 + movement text (or "Ninguno" if static).
- **Message structure:** `🏁 Final` --- stats (if found) --- commentary (if enabled).
- **Verified live:** Both cases (movement + no-movement) confirmed.
- **Test count:** 882 passing (65 new).

### Block 4: Ver-gol Stats (Decision #41)
- **Feature:** Persistent per-user "Ver gol" view counter (`reddit/vergol_stats.py`).
- **Dedup:** Token-based dedup prevents double-counts on repeat taps.
- **Leaderboard:** `/estadisticas` command shows users ranked by views.
- **Verified live:** Click tracking and leaderboard functional.
- **Test count:** 882 passing (final, no new tests in block 4 itself — only integration).

### Bonus: CI Paths-Ignore (Decision #42)
- Added `.squad/**` and `CHANGELOG.md` to `paths-ignore` in docker-deploy.yml.
- Prevents team-memory and auto-changelog commits from triggering redundant builds/releases.

## Coordination Checkpoints

- ✅ **689 → 882 tests:** All 5 blocks integrated and tested.
- ✅ **Container health:** 4 active jobs (`poll_goals` 60s, `poll_goal_clips` 45s, `poll_finished_matches` 120s, `daily_update`).
- ✅ **E2E verified live:** France-Senegal goals, real clips, porra commentary, "Ver gol" button, stats counter.
- ✅ **No infra/compose changes required:** All features use existing `/app/state` volume.

## Decision Cross-References

1. Decision #37: Goal Detection Rework — Block 1
2. Decision #38: Clip Flow — Block 2
3. Decision #39: Match-Finish Final Result Section
4. Decision #40: Always-Generate Porra Commentary
5. Decision #41: Ver-gol Stats — Block 4
6. Decision #42: CI Paths-Ignore

## Scribe Merge Notes

- All 6 inbox files (kante-*.md, maldini-*.md) merged into canonical `.squad/decisions.md`.
- Inbox directory purged post-merge.
- Decisions #37–42 appended as numbered entries for cross-reference clarity.
