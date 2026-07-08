# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 2387 (as of 2026-07-08)

## Session: 2026-07-08 — KO Draw Deferral Regression Tests — QA Gate (✅ PASS)

**Bug fixed by Kanté:** `match_result_is_final` in `formatters.py` was returning `True` for a
FINISHED knockout match with `winner="DRAW"` / `winner=None` and `duration="REGULAR"` or
`"EXTRA_TIME"`, causing a bare "🏁 Switzerland 0-0 Colombia" Final card to fire before
penalties were resolved.

**Kanté's fix (already landed):** Added `_KNOCKOUT_STAGE_NAMES` frozenset and a guard:
```python
if match.stage in _KNOCKOUT_STAGE_NAMES and match.winner not in ("HOME_TEAM", "AWAY_TEAM"):
    return False
```
Group-stage draws still return `True` (valid final results). `THIRD_PLACE` also included in the
knockout set.

**Tests added:** `tests/test_formatters.py` → extended `TestMatchResultIsFinal` (+6 tests).
`tests/test_poll_finished_job.py` → new helper `_ko_draw_match` + class `TestKnockoutDrawDeferral` (+2 tests).

### tests/test_formatters.py — TestMatchResultIsFinal (6 new)

- **`test_ko_finished_draw_regular_is_not_final`** — BUG REPRO: LAST_16 FINISHED 0-0 winner=DRAW duration=REGULAR → False (deferred)
- **`test_ko_finished_winner_none_regular_is_not_final`** — same but winner=None → False
- **`test_ko_finished_extra_time_no_winner_is_not_final`** — LAST_16 duration=EXTRA_TIME winner=None → False
- **`test_ko_settled_by_penalties_is_final`** — LAST_16 PENALTY_SHOOTOUT penalty_home=4, penalty_away=3, winner=HOME_TEAM → True
- **`test_ko_decided_in_regulation_is_final`** — QUARTER_FINALS 2-1 winner=HOME_TEAM duration=REGULAR → True
- **`test_group_stage_draw_regular_is_final`** — GROUP_STAGE 0-0 winner=DRAW duration=REGULAR → True (group draws are valid)

### tests/test_poll_finished_job.py — TestKnockoutDrawDeferral (2 new)

- **`test_ko_draw_finished_regular_deferred_not_announced`** — BUG INTEGRATION: SUI 0-0 COL LAST_16 FINISHED winner=DRAW → `send_message` not called, `1 not in finished_announced`
- **`test_ko_draw_announced_once_penalties_settle`** — same match with PENALTY_SHOOTOUT penalty_home=4, penalty_away=3, winner=HOME_TEAM → `send_message` called, `1 in finished_announced`

**Status:** All tests GREEN (Kanté's fix already landed concurrently). Red/green cycle confirmed
by code inspection — tests 1–3 and integration test 1 would have been RED against the original
`match_result_is_final` (which always returned True for non-PENALTY_SHOOTOUT).

**Outcome:** 8 new tests. Full suite: 2387 passed, 3 warnings. PASS. ✅

## Session: 2026-07-08 — Rich Birthday Mode — QA Gate (✅ PASS)

**Kanté's change:** Birthday mode in `src/worldcup_bot/ai/rich_image.py`.
On July 8 (every year) the daily "rich" image celebrates the character's birthday —
prompt and caption are augmented with a birthday-party theme and age (auto-increments yearly).

**New constants added by Kanté:**
- `RICH_BIRTHDAY_MONTH = 7`, `RICH_BIRTHDAY_DAY = 8`, `RICH_BIRTH_YEAR = 1984`
- `is_rich_birthday(now)` → True iff month==7 and day==8
- `rich_birthday_age(now)` → now.year - RICH_BIRTH_YEAR
- `build_rich_prompt(birthday=True, age=N)` → augments base prompt with birthday-party clause
- `generate_rich_caption(..., birthday, age)` → injects Spanish birthday instruction into messages
- `run_rich_iteration` computes birthday/age from `_now` and passes through
- Birthday-aware fallback caption: `🎂 ¡Hoy cumplo 42 y me lo monto a lo grande a vuestra costa!`

**Tests added:** `tests/test_rich_image.py` → new class `TestRichBirthdayMode` (+14 tests).

- **`test_is_rich_birthday_true_on_july_8_2026`** — July 8 2026 → True
- **`test_is_rich_birthday_true_another_year_july_8`** — July 8 2030 → True (year-invariant)
- **`test_is_rich_birthday_false_july_7`** — July 7 → False
- **`test_is_rich_birthday_false_july_9`** — July 9 → False
- **`test_is_rich_birthday_false_jan_8_guards_month_day_confusion`** — Jan 8 → False (guards month/day swap)
- **`test_rich_birthday_age_2026_is_42`** — datetime(2026,7,8) → 2026 - RICH_BIRTH_YEAR
- **`test_rich_birthday_age_increments_year_on_year`** — 2027 yields age_2026 + 1
- **`test_build_rich_prompt_birthday_true_contains_age_and_celebration`** — "42" + cake/birthday/celebr wording present
- **`test_build_rich_prompt_birthday_false_no_birthday_clause`** — no birthday wording when birthday=False
- **`test_build_rich_prompt_birthday_true_augments_base_not_replaces`** — starts with RICH_EDIT_PROMPT, "same face" present
- **`test_run_rich_iteration_birthday_date_prompt_has_birthday_clause`** — `_now=datetime(2026,7,8)` → prompt contains "42" + party wording
- **`test_run_rich_iteration_non_birthday_date_no_birthday_clause`** — `_now=datetime(2026,7,9)` → prompt has no birthday clause
- **`test_run_rich_iteration_birthday_caption_receives_birthday_instruction`** — caption messages contain "42" + birthday wording
- **`test_run_rich_iteration_birthday_fallback_caption_when_no_chat`** — no chat configured, birthday date → fallback caption birthday-aware

**Regression fixed (+3 pre-existing tests broken by Kanté):**
Three tests in `TestRunRichIteration` (`test_caption_falls_back_when_caption_client_raises`,
`test_caption_falls_back_when_chat_not_configured`, `test_caption_error_memo_not_appended_image_still_written`)
were failing because they call `run_rich_iteration` without `_now` and today IS July 8 (birthday).
The birthday-aware fallback `🎂 ¡Hoy cumplo 42…` was returned instead of the generic `🤑 Cada día…`.
Fix: inject `_now=datetime(2026, 7, 9, 11, 0, 0, tzinfo=pytz.UTC)` to pin them to a non-birthday date.

**Outcome:** All 14 new + 3 fixed tests PASS.
targeted: `tests/test_rich_image.py` → 251 passed.
Full suite: 2379 passed, 3 warnings. PASS (+17 effective). ✅



**Kanté investigation:** Root-cause analysis of USA-Belgium 100-message flood complete. Cross-source score reconciliation bug identified (reconcile() in score_state.py:220–241). Fix: advance OTHER source's seen baseline to pre-VAR announced score using max() on disallowed claim inside goal_lock.

**Tests added:** `tests/test_poll_thread_goals_job.py` → new class `TestVARCrossSourceRaceRegression` (+4 tests).

- **`test_thread_fast_api_lag_var_no_false_goal`** — primary USA-Belgium regression. Drives thread tick 1 (goal 1-0), tick 2 (VAR 0-0), then API tick (lagging catch-up to 1-0). Asserts zero sends on the API tick.
- **`test_api_fast_thread_lag_var_no_false_goal`** — symmetric. API does goal+disallowed; lagging thread reports 1-0. Asserts zero sends on thread tick.
- **`test_thread_fast_real_goal_after_var_not_suppressed`** — Pirlo's over-suppression guard (required). Drives thread goal+VAR, API catch-up to real post-VAR 0-0 (seen_api drops to {0,0}), then real thread goal. Asserts exactly 1 ⚽ send on the real goal — not zero (over-suppressed) and not >1 (duplicated).
- **`test_api_fast_real_goal_after_var_not_suppressed`** — symmetric over-suppression guard. API goal+VAR, then real API goal. Asserts exactly 1 ⚽ send.

**Coverage gap closed:** Existing `test_real_var_thread_goal_then_disallowed` (line 518) seeds `seen_api={3,2}` (already synced to pre-goal score). That does NOT reproduce the bug. The new tests seed `seen_api={0,0}` (BELOW the pre-goal score), which is the exact precondition for the oscillation loop.

**Outcome:** All 4 tests PASS. Red/green stash-cycle confirmed. Full suite: 2365 passed. +4 tests total.

## Learnings

### KO-draw deferral: test base stage must be a real knockout stage name
The `_match` helper in test_formatters.py defaults to `stage="LAST_32"` (a knockout stage). When
writing KO-draw deferral tests, explicitly pass the target stage name (e.g. `stage="LAST_16"`,
`stage="QUARTER_FINALS"`) for readability and to make the test self-documenting. Group-stage tests
must explicitly pass `stage="GROUP_STAGE"` to ensure the guard doesn't fire.

### _KNOCKOUT_STAGE_NAMES includes THIRD_PLACE
Kanté's frozenset is: `frozenset(api for api, _, _ in KNOCKOUT_STAGES) | {"THIRD_PLACE"}`.
So LAST_32, LAST_16, QUARTER_FINALS, SEMI_FINALS, FINAL, and THIRD_PLACE all trigger the
no-decisive-winner deferral. Group-stage draws are unaffected.

### Birthday test harness: always inject `_now` for fallback caption tests
Any test that asserts on the exact generic fallback caption string (`"🤑 Cada día más rico a vuestra costa"`)
MUST inject `_now` with a non-birthday date (e.g. `datetime(2026, 7, 9, tzinfo=pytz.UTC)`).
Without `_now`, the function calls `datetime.now()` which is the real clock — and if run on July 8
(birthday), the birthday-aware fallback is returned instead, breaking the assertion.
Rule: **all fallback-caption assertions must pin `_now` to a non-birthday date.**

### Birthday integration tests: use lazy imports for new symbols
For new birthday functions (`is_rich_birthday`, `rich_birthday_age`, `RICH_BIRTH_YEAR`) that may not
exist when tests are written (Kanté working in parallel), import them inside the test method body
rather than at module level. This prevents a collection failure from preventing the entire
test file from running. Once Kanté ships, the in-method import Just Works.

### Birthday prompt assertions: use multi-word OR checks
Kanté may write the birthday clause in English (`birthday`, `cake`) or Spanish (`cumpleaños`,
`tarta`, `fiesta`). Assert with a broad OR: `"birthday" in lower or "cumpleaños" in lower or
"cake" in lower or ...`. Same for the age: check `"42" in prompt` as a string.
This makes the assertion robust to localization choices.

### Coverage gap: two-source disagreement on VAR disallowed
The critical gap: two-source regression tests must vary `seen_api` to be BELOW the pre-goal score (not just synced to it). The oscillation only triggers when `seen_api < pre-VAR score` at the time the disallowed fires. Any existing test that seeds `seen_api` at the pre-VAR score misses the bug entirely. Future cross-source VAR tests should always include a variant with the second source lagging behind the pre-goal score.

### Harness pattern for driving both jobs in sequence
Use `_make_context` from `test_poll_thread_goals_job.py` which provides `live_scores` in `bot_data`. Both `poll_thread_goals_job` and `poll_goals_job` share the same `ctx` and thus the same `live_scores`, `seen_scores`, and `goal_lock`. Drive them sequentially; reset `send_message` mock between ticks with `ctx.bot.send_message.reset_mock()`. Set `ctx.bot.edit_message_text = AsyncMock()` to prevent `_backfill_scorer_in_clip_store` from failing when scorer-less clip entries are present.

### Key file paths
- `src/worldcup_bot/__main__.py` — both polling jobs, cross-source fix at lines 1221-1231 (thread→api) and 1000-1010 (api→thread)
- `src/worldcup_bot/reddit/score_state.py` — `reconcile()` function, stateless, lines 140-269
- `tests/test_poll_thread_goals_job.py` — full cross-source integration test harness; new class `TestVARCrossSourceRaceRegression` at end of file

---

## Latest Session: 2026-07-01 — Podium Image Feature — QA Gate (PASS)

**Kanté's change:** New `src/worldcup_bot/bot/podium_image.py` module — `render_podium` (sync, never raises),
`_render_podium`, `_draw_crown`, `_fetch_tile`, `_circular_crop`, `_placeholder_tile`, `_initials`.
`_send_ranking_with_top3_photos` reworked with podium → album → plain-text fallback chain.
Kanté delivered +17 smoke tests (1968 baseline). ✅

**New file:** `tests/test_podium_image_edge_cases.py` — 45 tests added.

**Coverage added (+45):**

*`_initials` (7):* two-word ("DS"), single-word ("M"), empty ("?"), whitespace-only ("?"),
three-word uses first+last ("JN"), lowercase uppercased, single-char words ("AB").

*`_circular_crop` (4):* output RGBA mode, output size matches diameter, center pixel alpha=255,
all four corners alpha=0 (outside circle).

*`_draw_crown` (3):* polygon has exactly 11 vertices (band + 3 spikes), ellipse called exactly 3 times
(one jewel per spike), polygon filled with `_CROWN_GOLD` constant.

*Name truncation (4):* via `_text_centered` spy — 14-char name unchanged, 15-char truncated to
13+"…", 30-char truncated correctly, 50-char name no crash.

*Font fallback (3):* `_FONT_PATH=None` still returns valid PNG; `_font()` returns object when path None;
`_font()` falls back on non-existent truetype path.

*Mixed photo failures (3):* all three failure modes in one render (404 + wrong CT + OSError) →
all placeholders + valid PNG; 200 OK with `application/json` CT → placeholder; first photo OK,
rest 404 → valid PNG.

*Total-failure variants (4):* `Image.new` raises MemoryError → None; `_draw_crown` raises ValueError
mid-render → None; `canvas.save` raises OSError → None; never raises regardless of exception type.

*`_text_centered` (2):* no crash with real ImageDraw; AttributeError fallback still calls `draw.text`.

*Tie-aware positions (5):* `[10,10,8]→[1,1,3]`, `[10,8,8]→[1,2,2]`, `[5,5,5]→[1,1,1]`,
`[10,8,6]→[1,2,3]`, participant dicts include username+display_name.

*send_photo kwargs (6):* photo kwarg is the exact BytesIO returned; chat_id matches effective_chat.id;
parse_mode="HTML"; exactly 1024 chars → no reply_text; 1025 chars → truncated caption + overflow
reply_text; send_media_group not called when podium succeeds.

*cmd_actual podium path (2):* send_photo called, send_media_group not called; caption contains
"provisional" + parse_mode HTML.

*cmd_general podium path (2):* send_photo called, send_media_group not called; caption contains
"Grupos cerrados: 1/12" footer + parse_mode HTML.

**New patterns discovered:**
- `patch.object(Image.Image, "save", side_effect=...)` — patches PIL save on the class to test save
  failures without touching any other image operations.
- `_text_centered` spy pattern — replace the drawing helper with a list-appending no-op to verify
  what text values were computed (truncated names, position labels) without pixel inspection.
- `MagicMock()` as `draw` parameter to `_draw_crown` — cleanly intercepts polygon/ellipse calls
  for geometry verification without needing a real PIL canvas.

**Bugs found:** None. Kanté's implementation is solid against all edge cases including mixed photo
failures, font fallback, inner-render exceptions, and tie-aware position derivation.

**Full suite:** 1968 + 45 = 2013 passed, 5 pre-existing warnings. PASS (+45). ✅

---

## Previous Session: 2026-06-30 — Revive Quiet Hours + Jitter Scheduling — QA Gate (PASS)

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

## Skills Updated

- `.squad/skills/ptb-async-testing.md` — added patterns for testing podium image with `asyncio.to_thread` and mocked HTTP requests; consolidated frozen-datetime pattern for time control in async tests.

---

For historical sessions (2026-06-27, 2026-06-26, 2026-06-15), see `.squad/agents/buffon/history-archive.md`.


## Session: 2026-07-08 — Rich Birthday Mode — QA Gate (✅ PASS)

**Kanté's change:** Birthday mode in `src/worldcup_bot/ai/rich_image.py`.
On July 8 (every year) the daily "rich" image celebrates the character's birthday —
prompt and caption are augmented with a birthday-party theme and age (auto-increments yearly).

**New constants added by Kanté:**
- `RICH_BIRTHDAY_MONTH = 7`, `RICH_BIRTHDAY_DAY = 8`, `RICH_BIRTH_YEAR = 1984`
- `is_rich_birthday(now)` → True iff month==7 and day==8
- `rich_birthday_age(now)` → now.year - RICH_BIRTH_YEAR
- `build_rich_prompt(birthday=True, age=N)` → augments base prompt with birthday-party clause
- `generate_rich_caption(..., birthday, age)` → injects Spanish birthday instruction into messages
- `run_rich_iteration` computes birthday/age from `_now` and passes through
- Birthday-aware fallback caption: `🎂 ¡Hoy cumplo 42 y me lo monto a lo grande a vuestra costa!`

**Tests added:** `tests/test_rich_image.py` → new class `TestRichBirthdayMode` (+14 tests).

- **`test_is_rich_birthday_true_on_july_8_2026`** — July 8 2026 → True
- **`test_is_rich_birthday_true_another_year_july_8`** — July 8 2030 → True (year-invariant)
- **`test_is_rich_birthday_false_july_7`** — July 7 → False
- **`test_is_rich_birthday_false_july_9`** — July 9 → False
- **`test_is_rich_birthday_false_jan_8_guards_month_day_confusion`** — Jan 8 → False (guards month/day swap)
- **`test_rich_birthday_age_2026_is_42`** — datetime(2026,7,8) → 2026 - RICH_BIRTH_YEAR
- **`test_rich_birthday_age_increments_year_on_year`** — 2027 yields age_2026 + 1
- **`test_build_rich_prompt_birthday_true_contains_age_and_celebration`** — "42" + cake/birthday/celebr wording present
- **`test_build_rich_prompt_birthday_false_no_birthday_clause`** — no birthday wording when birthday=False
- **`test_build_rich_prompt_birthday_true_augments_base_not_replaces`** — starts with RICH_EDIT_PROMPT, "same face" present
- **`test_run_rich_iteration_birthday_date_prompt_has_birthday_clause`** — `_now=datetime(2026,7,8)` → prompt contains "42" + party wording
- **`test_run_rich_iteration_non_birthday_date_no_birthday_clause`** — `_now=datetime(2026,7,9)` → prompt has no birthday clause
- **`test_run_rich_iteration_birthday_caption_receives_birthday_instruction`** — caption messages contain "42" + birthday wording
- **`test_run_rich_iteration_birthday_fallback_caption_when_no_chat`** — no chat configured, birthday date → fallback caption birthday-aware

**Regression fixed (+3 pre-existing tests broken by Kanté):**
Three tests in `TestRunRichIteration` (`test_caption_falls_back_when_caption_client_raises`,
`test_caption_falls_back_when_chat_not_configured`, `test_caption_error_memo_not_appended_image_still_written`)
were failing because they call `run_rich_iteration` without `_now` and today IS July 8 (birthday).
The birthday-aware fallback `🎂 ¡Hoy cumplo 42…` was returned instead of the generic `🤑 Cada día…`.
Fix: inject `_now=datetime(2026, 7, 9, 11, 0, 0, tzinfo=pytz.UTC)` to pin them to a non-birthday date.

**Outcome:** All 14 new + 3 fixed tests PASS.
targeted: `tests/test_rich_image.py` → 251 passed.
Full suite: 2379 passed, 3 warnings. PASS (+17 effective). ✅



**Kanté investigation:** Root-cause analysis of USA-Belgium 100-message flood complete. Cross-source score reconciliation bug identified (reconcile() in score_state.py:220–241). Fix: advance OTHER source's seen baseline to pre-VAR announced score using max() on disallowed claim inside goal_lock.

**Tests added:** `tests/test_poll_thread_goals_job.py` → new class `TestVARCrossSourceRaceRegression` (+4 tests).

- **`test_thread_fast_api_lag_var_no_false_goal`** — primary USA-Belgium regression. Drives thread tick 1 (goal 1-0), tick 2 (VAR 0-0), then API tick (lagging catch-up to 1-0). Asserts zero sends on the API tick.
- **`test_api_fast_thread_lag_var_no_false_goal`** — symmetric. API does goal+disallowed; lagging thread reports 1-0. Asserts zero sends on thread tick.
- **`test_thread_fast_real_goal_after_var_not_suppressed`** — Pirlo's over-suppression guard (required). Drives thread goal+VAR, API catch-up to real post-VAR 0-0 (seen_api drops to {0,0}), then real thread goal. Asserts exactly 1 ⚽ send on the real goal — not zero (over-suppressed) and not >1 (duplicated).
- **`test_api_fast_real_goal_after_var_not_suppressed`** — symmetric over-suppression guard. API goal+VAR, then real API goal. Asserts exactly 1 ⚽ send.

**Coverage gap closed:** Existing `test_real_var_thread_goal_then_disallowed` (line 518) seeds `seen_api={3,2}` (already synced to pre-goal score). That does NOT reproduce the bug. The new tests seed `seen_api={0,0}` (BELOW the pre-goal score), which is the exact precondition for the oscillation loop.

**Outcome:** All 4 tests PASS. Red/green stash-cycle confirmed. Full suite: 2365 passed. +4 tests total.

## Learnings

### Birthday test harness: always inject `_now` for fallback caption tests
Any test that asserts on the exact generic fallback caption string (`"🤑 Cada día más rico a vuestra costa"`)
MUST inject `_now` with a non-birthday date (e.g. `datetime(2026, 7, 9, tzinfo=pytz.UTC)`).
Without `_now`, the function calls `datetime.now()` which is the real clock — and if run on July 8
(birthday), the birthday-aware fallback is returned instead, breaking the assertion.
Rule: **all fallback-caption assertions must pin `_now` to a non-birthday date.**

### Birthday integration tests: use lazy imports for new symbols
For new birthday functions (`is_rich_birthday`, `rich_birthday_age`, `RICH_BIRTH_YEAR`) that may not
exist when tests are written (Kanté working in parallel), import them inside the test method body
rather than at module level. This prevents a collection failure from preventing the entire
test file from running. Once Kanté ships, the in-method import Just Works.

### Birthday prompt assertions: use multi-word OR checks
Kanté may write the birthday clause in English (`birthday`, `cake`) or Spanish (`cumpleaños`,
`tarta`, `fiesta`). Assert with a broad OR: `"birthday" in lower or "cumpleaños" in lower or
"cake" in lower or ...`. Same for the age: check `"42" in prompt` as a string.
This makes the assertion robust to localization choices.

### Coverage gap: two-source disagreement on VAR disallowed
The critical gap: two-source regression tests must vary `seen_api` to be BELOW the pre-goal score (not just synced to it). The oscillation only triggers when `seen_api < pre-VAR score` at the time the disallowed fires. Any existing test that seeds `seen_api` at the pre-VAR score misses the bug entirely. Future cross-source VAR tests should always include a variant with the second source lagging behind the pre-goal score.

### Harness pattern for driving both jobs in sequence
Use `_make_context` from `test_poll_thread_goals_job.py` which provides `live_scores` in `bot_data`. Both `poll_thread_goals_job` and `poll_goals_job` share the same `ctx` and thus the same `live_scores`, `seen_scores`, and `goal_lock`. Drive them sequentially; reset `send_message` mock between ticks with `ctx.bot.send_message.reset_mock()`. Set `ctx.bot.edit_message_text = AsyncMock()` to prevent `_backfill_scorer_in_clip_store` from failing when scorer-less clip entries are present.

### Key file paths
- `src/worldcup_bot/__main__.py` — both polling jobs, cross-source fix at lines 1221-1231 (thread→api) and 1000-1010 (api→thread)
- `src/worldcup_bot/reddit/score_state.py` — `reconcile()` function, stateless, lines 140-269
- `tests/test_poll_thread_goals_job.py` — full cross-source integration test harness; new class `TestVARCrossSourceRaceRegression` at end of file

---

## Latest Session: 2026-07-01 — Podium Image Feature — QA Gate (PASS)

**Kanté's change:** New `src/worldcup_bot/bot/podium_image.py` module — `render_podium` (sync, never raises),
`_render_podium`, `_draw_crown`, `_fetch_tile`, `_circular_crop`, `_placeholder_tile`, `_initials`.
`_send_ranking_with_top3_photos` reworked with podium → album → plain-text fallback chain.
Kanté delivered +17 smoke tests (1968 baseline). ✅

**New file:** `tests/test_podium_image_edge_cases.py` — 45 tests added.

**Coverage added (+45):**

*`_initials` (7):* two-word ("DS"), single-word ("M"), empty ("?"), whitespace-only ("?"),
three-word uses first+last ("JN"), lowercase uppercased, single-char words ("AB").

*`_circular_crop` (4):* output RGBA mode, output size matches diameter, center pixel alpha=255,
all four corners alpha=0 (outside circle).

*`_draw_crown` (3):* polygon has exactly 11 vertices (band + 3 spikes), ellipse called exactly 3 times
(one jewel per spike), polygon filled with `_CROWN_GOLD` constant.

*Name truncation (4):* via `_text_centered` spy — 14-char name unchanged, 15-char truncated to
13+"…", 30-char truncated correctly, 50-char name no crash.

*Font fallback (3):* `_FONT_PATH=None` still returns valid PNG; `_font()` returns object when path None;
`_font()` falls back on non-existent truetype path.

*Mixed photo failures (3):* all three failure modes in one render (404 + wrong CT + OSError) →
all placeholders + valid PNG; 200 OK with `application/json` CT → placeholder; first photo OK,
rest 404 → valid PNG.

*Total-failure variants (4):* `Image.new` raises MemoryError → None; `_draw_crown` raises ValueError
mid-render → None; `canvas.save` raises OSError → None; never raises regardless of exception type.

*`_text_centered` (2):* no crash with real ImageDraw; AttributeError fallback still calls `draw.text`.

*Tie-aware positions (5):* `[10,10,8]→[1,1,3]`, `[10,8,8]→[1,2,2]`, `[5,5,5]→[1,1,1]`,
`[10,8,6]→[1,2,3]`, participant dicts include username+display_name.

*send_photo kwargs (6):* photo kwarg is the exact BytesIO returned; chat_id matches effective_chat.id;
parse_mode="HTML"; exactly 1024 chars → no reply_text; 1025 chars → truncated caption + overflow
reply_text; send_media_group not called when podium succeeds.

*cmd_actual podium path (2):* send_photo called, send_media_group not called; caption contains
"provisional" + parse_mode HTML.

*cmd_general podium path (2):* send_photo called, send_media_group not called; caption contains
"Grupos cerrados: 1/12" footer + parse_mode HTML.

**New patterns discovered:**
- `patch.object(Image.Image, "save", side_effect=...)` — patches PIL save on the class to test save
  failures without touching any other image operations.
- `_text_centered` spy pattern — replace the drawing helper with a list-appending no-op to verify
  what text values were computed (truncated names, position labels) without pixel inspection.
- `MagicMock()` as `draw` parameter to `_draw_crown` — cleanly intercepts polygon/ellipse calls
  for geometry verification without needing a real PIL canvas.

**Bugs found:** None. Kanté's implementation is solid against all edge cases including mixed photo
failures, font fallback, inner-render exceptions, and tie-aware position derivation.

**Full suite:** 1968 + 45 = 2013 passed, 5 pre-existing warnings. PASS (+45). ✅

---

## Previous Session: 2026-06-30 — Revive Quiet Hours + Jitter Scheduling — QA Gate (PASS)

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

## Skills Updated

- `.squad/skills/ptb-async-testing.md` — added patterns for testing podium image with `asyncio.to_thread` and mocked HTTP requests; consolidated frozen-datetime pattern for time control in async tests.

---

For historical sessions (2026-06-27, 2026-06-26, 2026-06-15), see `.squad/agents/buffon/history-archive.md`.

