# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot  
**Stack:** Python, python-telegram-bot, football-data.org, Reddit scanner, LLM  
**Current test count:** 1644 (as of 2026-06-27)

## Latest Session: 2026-06-27 — Finished-Match Goal Loop Fix

**Issue:** Egypt-Iran match (played yesterday, finished hours ago) kept emitting "⚽ gol de Irán" / "🚫 gol anulado" in an endless loop every few minutes.

**Root causes confirmed:**

1. **Stuck API status** — football-data.org kept reporting Egypt-Iran as `IN_PLAY` long after FT. The match was already seeded in `live_scores.json`, so `poll_goals_job`'s `relevant` filter (`IN_PLAY` OR `FINISHED and id in scores`) kept including it on every tick.
2. **Oscillating Reddit thread** — A VAR-disallowed Iran goal flickered in/out of the parsed events. `thread_away = max(e.away_score ...)` flipped between N and N-1 each poll. Via `reconcile()`: one tick new>announced → emits GOAL (announced up); next tick announced>new AND seen(thread) was high → emits DISALLOWED (announced down, clamped); repeat forever.
3. **No wall-clock cutoff in goal polling** — `MATCH_OVER_AGE = timedelta(hours=4)` existed and was used in `poll_finished_matches_job` seeding, but the goal-polling jobs (`poll_goals_job`, `poll_thread_goals_job`) had NO age-based exclusion — they trusted the lagging API status unconditionally.

**Fix:**

1. **`_match_is_over(match, now_utc)` predicate** — Added pure wall-clock guard: returns True when `kickoff > MATCH_OVER_AGE (4h) ago`. Deliberately ignores API status. ET + penalties fit within 4h; FINISHED matches within 4h pass (eligible for final-goal catch-up).

2. **`poll_goals_job` — prune + filter:**
   - Before building `relevant`: compute `over_ids = {str(m.id) for m in all_matches if _match_is_over(m, now_utc)}`, then `pruned = [k for k in over_ids if k in scores]`. Evict pruned keys from `scores`, `seen_api`, and `seen_scores["thread"]`, save immediately. Self-heals stuck entries (Egypt-Iran) on next tick after deploy.
   - Add `not _match_is_over(m, now_utc)` to the `relevant` filter. Existing FINISHED-within-4h catch-up behavior preserved.

3. **`poll_thread_goals_job` — filter live_matches:** After `get_live_matches()`, drop over-matches: `live_matches = [m for m in live_matches if not _match_is_over(m, now_utc)]`. Avoids scanning Reddit for a dead match.

**Tests (+10):**
- `TestMatchOverFilter` (7 tests in `test_poll_goals_job.py`): stale exclusion, prune of both dicts, exact Egypt-Iran oscillation scenario, recent match still works, recently-FINISHED still works, FINISHED-5h-ago excluded, real VAR on live match still fires.
- `TestMatchOverFilterThread` (3 tests in `test_poll_thread_goals_job.py`): stale match filtered, oscillation zero sends, recent match still processed.

**Files changed:** `src/worldcup_bot/__main__.py`, `tests/test_poll_goals_job.py`, `tests/test_poll_thread_goals_job.py`

**Test delta:** 1639 (post-TVE) → 1644 (+5 from Buffon QA gate)

**Gates:** Pirlo APPROVED; Buffon PASS WITH ADDED TESTS (+5)

---

## Session Archive

For detailed historical sessions, see `.squad/agents/kante/history-archive.md`:
- 2026-06-26 — TVE 📺 Label Fix (daily update failure-caching + same-day fallback)
- 2026-06-26 — Live Goal Notification Bug Fixes (API lag, restart losses, keyboard race)
- 2026-06-26 — Best-Qualifying-Thirds Scoring (WC2026 format, 8 of 12 thirds qualify)
- 2026-06-22 — Kickoff-Start Notifications (match-start alerts)
- Earlier initial architecture + group-phase scoring

- `test_restart_new_ahead_multiple_goals_emits_all`: updated to assert ONE delta, `goals_missed=3`
- `test_restart_away_goal_missed_emits_away_delta`: updated to assert `kind="catchup"`
- `test_restart_delta_scoring_team_empty_for_caller` → renamed `test_restart_catchup_delta_has_no_scoring_team`
- `test_restart_catchup_deltas_carry_final_score` (Buffon's test) → replaced with
  `test_restart_catchup_single_delta_no_token_collision` documenting the new single-delta design
- `test_seed_nonzero_first_sight_announces_catchup_goals`: updated to assert 1 send with "⚠️"/"perdí"
- `test_seed_nonzero_clips_store_entries_created`: updated to assert 1 clip-store entry (not 2)
- `test_restart_mid_match_missed_goal_announced`: updated to assert catch-up format
- `test_catchup_message_no_scorer_attribution_no_keyboard`: NEW — asserts no "GOOOL"/no "⚽"/no keyboard on initial send
- `test_backfill_no_keyboard_when_clip_not_ready`: updated to assert `"reply_markup" not in edit_kwargs` (absence, not None)
