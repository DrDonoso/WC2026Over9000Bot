# Buffon — QA / Tester — Historical Archive

## Archived Sessions (Consolidated 2026-07-01)

### 2026-06-27 — Catch-Up / Goal Pipeline Fix — QA Gate

**Kanté's change:** Four-part fix — 0-0 kickoff seed, `_attempt_goal_recovery` (proper scorer+keyboard per missed goal), two-tick FINISHED eviction (stops post-FT oscillation), immediate save in poll_thread_goals_job. Based on confirmed Uruguay-Spain post-FT double-notify (Egypt-Iran pattern in <4h window).

**Full suite:** 1661 passed on Kanté's baseline. ✅

**Scrutiny of +17 tests:**
- `test_second_finished_tick_evicts_match`: ✅ genuine regression guard (fails without fix)
- `test_uruguay_spain_full_timeline_zero_post_ft_sends`: ⚠️ WEAK — uses `[]→[0-1]` oscillation; `reconcile(seen=0-1, ann=0-1, 0, 1)` = step-2 no-change, passes with or without the fix. Real bug pattern `[0-0]→[0-1]` not tested.
- `TestCatchupRecovery` (4): all genuine regression guards ✅
- `TestKickoffSeedLiveScores` (3), `TestImmediateSave` (2), `TestPostFTEvictionDedup` (1), `TestPostponedEviction` (2): all pass. ✅

**Added edge-case coverage (+4):**
1. `test_var_flip_oscillation_post_ft_zero_sends` — proper B regression with VAR-flip `[0-0]→[0-1]` after FT. Would fire disallowed+GOOOL without eviction fix.
2. `test_age_prune_and_finished_eviction_no_crash` — >4h age prune + FINISHED two-tick coexist without crash; correct cleanup.
3. `test_recovery_dedup_no_resend_on_next_thread_tick` — after recovery claims seen_thread, next poll_thread tick = zero sends.
4. `test_neutral_fallback_no_loop_on_next_thread_tick` — neutral fallback doesn't loop; reconcile(None, {0,2}, 0, 2) returns [] because _ahead(equal, equal) is False.

**Network:** all scanner calls mocked, 5 s timeout in prod irrelevant in tests. ✅

**Final:** 1665 passed, 5 warnings (pre-existing). PASS WITH ADDED TESTS (+4).

---

### 2026-06-27 — Finished-Match Goal Loop Fix (Egypt-Iran) — QA Gate

**Verified:** Kanté's _match_is_over wall-clock cutoff for goal-polling jobs. All 1639 baseline tests passed immediately.

**Added edge-case coverage (+5):**
1. _match_is_over safe fallbacks (invalid/empty date → False)
2. Boundary direction (3h59m not-over, 4h2m over)
3. ET+penalties still announced (3h50m)
4. Cross-match prevention (two different games same UTC day)
5. Partial fetch success (one channel ok, one fails)

**Final:** 1644 passed, 5 warnings. All hazards resolved. PASS WITH ADDED TESTS (+5).

---

## Key Learnings (Consolidated)

**Silent failures are deadly:** Group normalization bug ("Group A" → "GROUP_A") passed unit tests because fixtures used canonical form. Only end-to-end testing caught it. **Mock third-party APIs with real response shapes.**

**Regression tests are insurance:** Every fix includes a regression test (e.g., "Group A" normalization, oscillating goal loop). These prevent future refactoring from reintroducing bugs.

**Test suite as contract:** 1644 passing tests serve as executable specification of behavior and API correctness.

---

### Earlier Sessions (2026-06-26, 2026-06-15)

For detailed historical sessions:
- 2026-06-26 — TVE label fix QA gate (PASS WITH ADDED TESTS +2)
- 2026-06-26 — Group-phase scoring model QA gate (137 tests, APPROVED)
- 2026-06-26 — Best-qualifying-thirds QA gate (1613 tests +42, APPROVED)
- 2026-06-15 — Initial group-phase testing and setup (131 tests, 6 found/fixed bugs)
