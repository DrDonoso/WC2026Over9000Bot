# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 1936 (as of 2026-06-30)

## Latest Session: 2026-06-30 — Revive Quiet Hours + Jitter Scheduling — QA Gate (PASS)

**Kanté's change:** Added quiet-hours window + randomized jitter to revive scheduling.
Three new pure helpers in `chat/revive.py`: `is_quiet_hours`, `next_revive_delay`, `schedule_next_revive`.
`revive_inactive_job` reworked to self-reschedule via a `finally` block on every exit path.
Kanté delivered +8 smoke tests (1883 baseline). ✅

**New file:** `tests/test_revive_schedule.py` — 53 tests added.

**Coverage added (+53):**

*is_quiet_hours (16 + sweeps):* All 16 spec vectors — wrap window (23→6): 23, 0, 3, 5 True; 6, 7, 12,
22 False. Non-wrap (1→5): 1, 4 True; 0, 5, 6 False. start==end (0,0): always False. Plus exhaustive
boundary sweeps: every hour [0–23] against both wrap and non-wrap windows; exact quiet_end hour always
False (exclusive boundary).

*next_revive_delay (16):* deterministic via injectable `rand` kwarg.
- Clamp: tiny base + large negative jitter → ≥ 60.0.
- Daytime no-push (10:00, 4 h base, rand→min): delay == base, target not in quiet.
- Midnight-wrap push from evening (23:30 → pushed to 06:00+ next day): assert
  `is_quiet_hours(target.hour, 23, 6) is False` and target lands in [06:00, 06:45].
- Past-midnight push (01:00 → target 03:30 inside quiet → pushed to same-day 06:xx).
- Same-day push (08:00, base 1 h, quiet 9→10 → target 09:xx → pushed to 10:xx).
- Target exactly at quiet_end (10:00, 1 h, quiet 9→10 → target == 10:00, not quiet → no push).
- Cross-midnight date: next-day date correct when pushed from late evening.
- Spread-additive proof (rand=0, mid, max): pushed target ≥ quiet_end, never before quiet_end.

*schedule_next_revive (4):* `run_once` called with correct callable, `when` ≥ 60 s, `name` matches
pattern, called exactly once.

*revive_inactive_job rescheduling (17):* using frozen `datetime` subclass for time control.
- Quiet-skip: now in quiet hours → no `send_message`, but `run_once` called exactly once (reschedule).
- ALWAYS-RESCHEDULE on 4 paths: success (sends mention), no-candidates, `AIError`, generic `Exception`.
- Exactly-one-run-once per execution on all paths.
- Disabled (revive off): no send, no reschedule.
- `settings` missing from bot_data: no reschedule (settings=None guard in finally).
- `ai_client=None` with revive enabled: reschedules but does not send.
- `ai_enabled=False` (no API keys): `revive_enabled=False` → no reschedule.

**New pattern discovered:** `_frozen_datetime_cls(hour, minute)` — factory that returns a
`datetime.datetime` subclass with `.now()` overridden to return a fixed local time.
Patches `worldcup_bot.chat.revive.datetime` to control both the quiet-hours check and the
delay calculation inside `revive_inactive_job` and `schedule_next_revive`.

**Bugs found:** None. All `is_quiet_hours`/`next_revive_delay` edge cases pass correctly.

**Full suite:** 1883 + 53 = 1936 passed, 5 pre-existing warnings. PASS (+53). ✅

---

## Previous Session: 2026-06-30 — Chat LLM Features (Picante + Revive) — QA Gate (PASS)

**Team ship:** Pirlo (Design) + Kanté (Implementation) + Buffon (Testing) + Maldini (DevOps).

**Kanté's scope:** Two LLM-driven group-chat features in `src/worldcup_bot/chat/` package (buffer, state, listener, picante, revive + config wiring).

**Buffon's scope:** Comprehensive edge-case coverage — 107 new tests for gates, filtering, concurrency, privacy, fallbacks, candidate selection, rotation logic.

**Full suite:** 1768 baseline + 107 new = 1875 passed, 5 pre-existing deprecation warnings (unrelated).

**Quality:** 0 bugs found. All edge cases covered: rate limits, PORRA-participant filtering, concurrency scenarios, resilience to AI errors, privacy (no message text on disk).

**Artifact created:** `.squad/skills/ptb-async-testing.md` — PTB async testing best practices.

**Ready for deployment:** Yes (if privacy mode is disabled first).

---

## Latest Session: 2026-06-30 — Chat LLM Features (Picante + Revive) — QA Gate
`buffer.py` (RingBuffer), `state.py` (ChatState + atomic save), `listener.py` (5-stage filter),
`picante.py` (gates + maybe_reply), `revive.py` (candidates + revive_inactive_job).
Kanté delivered +38 smoke tests (1768 total baseline). ✅

**Full suite on Kanté's baseline:** 1768 passed immediately. ✅

**New file:** `tests/test_chat_edge_cases.py` — 107 tests added.

**Coverage added (+107):**

*RingBuffer (8):* empty snapshot, maxlen-1, 10-appends-to-3 keeps last-3 in order,
snapshot independence, post-eviction oldest-first, all-fields integrity, len-tracks-evictions.

*ChatState persistence (6):* **privacy check** (reads back raw JSON, asserts no `"text"` key at
any depth — confirms no message text reaches disk), empty-`{}`-file → defaults, null-fields JSON →
defaults, empty-file content → defaults, atomic write leaves no `.tmp`, round-trip preserves
`last_seen`/`last_mentioned`.

*probability_gate (5):* `probability=0.0` never fires; `1.0` always fires; exactly-at-threshold
does NOT fire (strict `<`); just-below fires; just-above doesn't.

*cooldown_gate extras (4):* 1 s below blocked, 1 s above allowed, zero elapsed blocked,
zero cooldown always passes.

*daily_cap extras (5):* one-under-cap allowed, count-0 same-day allowed, rollover high-count passes,
max=1 first send allowed, max=1 second send blocked.

*min_buffer extras (4):* one-below blocked, exact allowed, one-above allowed, zero/zero allowed.

*Listener null-guards (2):* `effective_message=None` → no crash; `effective_user=None` → no crash,
buffer stays empty.

*Listener command rejection (7):* parametrized `/tongo`, `/listaaciertosactual`, `/siguiente`,
`/start`; leading-whitespace command; command-with-args.

*Listener media rejection (11):* all 8 media fields individually via parametrize; photo+caption;
video+caption; sticker+None text.

*Listener text rejection (6):* None, empty, whitespace-only, newlines-only, 4-char (< 5),
exact-5-char passes.

*Listener chat_id filter (3):* wrong ID rejected, correct ID accepted, no-group-ID accepts all.

*Listener bot rejection (2):* bot's own `user.id == bot.id` rejected; normal user not rejected.

*Listener acceptance (5):* buffer recorded, last_seen updated, username lowercased, no-username
key not stored in last_seen, accumulates across calls.

*maybe_reply orchestrator (11):* all-gates-pass → AI called + reply_text called with exact text;
counters updated; new-day resets count to 1; same-day increments; each gate individually failing →
no AI call (min_buffer / cooldown / daily_cap / probability); AIError → no crash no reply;
RuntimeError → no crash; reply receives exact AI output.

*compute_inactive_candidates extras (12):* exact inactivity boundary (NOT inactive); 1-second over
boundary (inactive); exact mention-cooldown still excluded; 1-second over cooldown → candidate;
absent-from-last_seen immediately inactive; non-porra user never candidate; all-active → empty;
corrupt-last_seen → inactive; corrupt-last_mentioned → cooldown skipped still candidate;
empty porra_list → empty; multi-user sorted; seeded-within-threshold not candidate.

*select_candidate extras (4):* large index wraps; single candidate always selected + index increments;
6 consecutive calls cycle a-b-c-a-b-c; index-3 mod-2 → "y".

*revive_inactive_job (13):* sends `@alice …`; `parse_mode=None`; updates `last_mentioned`;
persists to disk (JSON verified); `rotate_index` advanced; no candidates → no send; revive disabled →
no-op; AI not configured → no-op; `ai_client=None` → no-op; AIError → no crash no send;
ValueError → no crash; porra_display_names used in AI prompt; sends to configured group_id.

**Bugs found:** None. Kanté's implementation is solid against all edge cases.

**Gaps / notes:**
- `select_candidate([])` raises `ZeroDivisionError` — this is documented as a precondition
  ("must be non-empty"); the caller (`revive_inactive_job`) guards with `if not candidates`. Acceptable.
- No test for `build_picante_system_prompt()` / `build_revive_system_prompt()` — they return
  module-level string constants; tested implicitly through maybe_reply/revive_inactive_job.

**Final:** 1875 passed, 5 warnings (all pre-existing). PASS WITH ADDED TESTS (+107). ✅

---

## Previous Session: 2026-06-27 — Catch-Up / Goal Pipeline Fix — QA Gate

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

## Previous Session: 2026-06-27 — Finished-Match Goal Loop Fix (Egypt-Iran) — QA Gate

**Verified:** Kanté's _match_is_over wall-clock cutoff for goal-polling jobs. All 1639 baseline tests passed immediately.

**Added edge-case coverage (+5):**
1. _match_is_over safe fallbacks (invalid/empty date → False)
2. Boundary direction (3h59m not-over, 4h2m over)
3. ET+penalties still announced (3h50m)
4. Cross-match prevention (two different games same UTC day)
5. Partial fetch success (one channel ok, one fails)

**Final:** 1644 passed, 5 warnings. All hazards resolved. PASS WITH ADDED TESTS (+5).

---

## Session Archive

For detailed historical sessions, see .squad/agents/buffon/history-archive.md:
- 2026-06-26 — TVE label fix QA gate (PASS WITH ADDED TESTS +2)
- 2026-06-26 — Group-phase scoring model QA gate (137 tests, APPROVED)
- 2026-06-26 — Best-qualifying-thirds QA gate (1613 tests +42, APPROVED)
- 2026-06-15 — Initial group-phase testing and setup (131 tests, 6 found/fixed bugs)

## Key Learnings (Consolidated)

**Silent failures are deadly:** Group normalization bug ("Group A" → "GROUP_A") passed unit tests because fixtures used canonical form. Only end-to-end testing caught it. **Mock third-party APIs with real response shapes.**

**Regression tests are insurance:** Every fix includes a regression test (e.g., "Group A" normalization, oscillating goal loop). These prevent future refactoring from reintroducing bugs.

**Test suite as contract:** 1644 passing tests serve as executable specification of behavior and API correctness.

---

## Follow-Up Session: 2026-06-30 — Revive Quiet Hours + Jitter Self-Rescheduling (commit 31f1a89)

**Team:** Kanté (Backend) + Maldini (DevOps) + Buffon (Testing) + Pirlo (Lead Review)  
**Shipped:** ✅ commit 31f1a89

**Buffon's comprehensive test coverage:**
- New file: `tests/test_revive_schedule.py` — 53 new tests added
- `is_quiet_hours` tests: all boundary conditions (no-window, midnight wrap 23→6, same-day windows, exhaustive hour sweeps)
- `next_revive_delay` tests: jitter range, clamp to 60s minimum, quiet-push same-day vs next-day, rand injection for deterministic testing
- `schedule_next_revive` tests: mock job_queue, verify run_once call args + name
- `revive_inactive_job` integration tests: quiet-hours skip with no send_message, self-reschedule via finally, settings=None safety path
- Regression: all existing revive tests pass with new finally block in place
- Updated ptb-async-testing skill for frozen-datetime pattern

**Test result:** Full suite: **1936 passed, 0 failed** (53 new tests all pass, no regressions)

**Test quality notes:**
- Excellent injectable rand() parameter for deterministic jitter testing
- Clean settings-is-None-before-try pattern verification
- Comprehensive edge case coverage (midnight transitions, boundary conditions, exception paths)
