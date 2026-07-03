# Decisions Log

## 2026-07-03: Post-Final VAR Score Correction (kante — Backend Implementation)

**Date:** 2026-07-03  
**Author:** Kanté (Backend Implementation)  
**Status:** ✅ IMPLEMENTED — awaiting Buffon tests + Pirlo review, then commit

### Problem

Portugal-Croatia knockout match: the football-data.org free-tier API briefly marked
the match `FINISHED` with score 2-2 (pre-VAR).  `poll_finished_matches_job` finalizes
on the **first** `FINISHED` tick, adds the match to `finished_announced`, and never
re-checks.  The API later corrected to 2-1 but the bot had already announced "🏁 Final
2-2".  The in-play VAR mechanism (`poll_thread_goals_job`) didn't catch it because the
annulment happened right at full-time.

### Design

#### New State: `finished_scores`

A new persisted dict `bot_data["finished_scores"]` (→ `{state_dir}/finished_scores.json`)
records the on-pitch score at the moment a match is finalized:

```json
{
  "101": {
    "home": 2,
    "away": 2,
    "finalized_at": "2026-07-03T20:05:00+00:00",
    "corrected": false
  }
}
```

- Seeded in `build_app` via `load_finished_scores()` (new `reddit/finished_scores.py`).
- Written immediately after `poll_finished_matches_job` successfully sends the recap
  for a new match (inside the `try` block, after `send_message`).
- Uses a nested `try/except` so a recording failure never breaks the main finalization.

#### New Config: `FINAL_CORRECTION_WINDOW_MINUTES=30`

Added `final_correction_window_minutes: int = 30` to `Settings`.  Entries older than
this window are pruned on every tick.

#### VAR Correction Watch: `_var_correction_watch`

Runs at the end of **every** `poll_finished_matches_job` tick (including ticks where
`new_ids` is empty — the previous `if not new_ids: return` was replaced with a
conditional VAR-watch call before the early return).

For each entry in `finished_scores` within the window:
1. **Prune** stale entries (age > window).
2. **Compare** `current.home_score / current.away_score` vs `entry["home"] / entry["away"]`.
3. If different:
   a. **Post** `format_var_correction(match, old_home, old_away)` to `telegram_group_id`.
   b. **Edit** the original "¡GOOOL!" message via `_mark_goal_annulled`.
   c. **Update** `entry["home"] / ["away"]` to the new score, set `corrected=True`, persist.
4. If same → skip.

This means the `corrected` flag is informational only and does NOT prevent future
re-corrections (if the score changed twice, the diff logic fires again).

#### Clip-Store Lookup in `_mark_goal_annulled`

**Decision: token reconstruction (Option A).**

We reconstruct the SHA-1 token for both possible scoring teams:
```python
for scoring_team in (match.home_name, match.away_name):
    token_key = f"{match_id}:{scoring_team}:{annulled_home}-{annulled_away}"
    tok = _cs_goal_token(token_key)
    entry = clip_data.get(tok)
    if entry is not None:
        break
```

Rationale: in `_process_goal_delta`, `scoring_team` is always normalized to
`match.home_name` or `match.away_name` — so these two probes are exhaustive.
O(1) lookup, no schema change.

If found: rebuild the original message text via `format_new_goal_message` + append
`"\n❌ <b>ANULADO (VAR)</b>"`.  Preserve the inline keyboard: pass
`build_goal_keyboard(tok)` only when `entry["status"] == "ready"` (same pattern
as `_backfill_scorer`).

If not found: log and continue — correction message was already sent.

#### Penalty-Shootout Safety

`match_result_is_final(match)` already requires both `penalty_home/away` and a
decisive winner for `PENALTY_SHOOTOUT` duration.  On-pitch scores don't change
during the shootout, so the diff comparison on `home_score/away_score` is
intrinsically safe.

#### Non-Fatal / Best-Effort

Every code path in `_var_correction_watch` and `_mark_goal_annulled` is wrapped in
`try/except`; any failure logs a warning and continues.  A correction failure can
never disrupt the main `poll_finished_matches_job` run.

### Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/config.py` | + `final_correction_window_minutes: int = 30` + env var |
| `src/worldcup_bot/reddit/finished_scores.py` | NEW — `load_finished_scores` / `save_finished_scores` |
| `src/worldcup_bot/bot/formatters.py` | + `format_var_correction(match, old_home, old_away)` |
| `src/worldcup_bot/__main__.py` | + imports; `poll_finished_matches_job` restructured (score recording + VAR watch); + `_fs_entry_is_stale`, `_mark_goal_annulled`, `_var_correction_watch`; `build_app` seeds `finished_scores` |
| `tests/test_poll_finished_job.py` | + `TestVARCorrectionWatch` (8 tests); `_make_context` + `edit_message_text = AsyncMock()` |

### Invariants Preserved

- `finished_announced` dedup set: unchanged — matches still finalized exactly once.
- Penalty shootout detection: `match_result_is_final` gate unchanged.
- Early return on first-run seed pass: unchanged.
- Clip-store `match_id`-less schema: unchanged — no new field added.
- Best-effort everywhere: a correction failure cannot break the finished-match pipeline.
- No duplicate corrections: updated recorded score = new score; next tick sees no diff.

### Test Count

**2165 passed** (2157 existing + 8 new in `TestVARCorrectionWatch`). 0 failures.

New tests cover:
1. Score change → correction posted + goal edited (format, group_id, ANULADO mark)
2. `ready` clip → keyboard preserved on edit
3. Stable score → no correction
4. Third tick (post-correction, recorded=new score) → no duplicate
5. Penalty shootout (on-pitch stable) → no false positive
6. Window expiry (45 min > 30 min) → entry pruned, no correction
7. Goal message absent from clip_store → correction still sent, edit skipped gracefully
8. Score recorded at finalization → `finished_scores` entry written correctly

---

## 2026-07-03: Review: Post-Final VAR Score Correction Watch (pirlo — Lead)

**Reviewer:** Pirlo (Lead)  
**Date:** 2026-07-03  
**Scope:** `__main__.py` (VAR watch + score recording), `formatters.py` (format_var_correction), `config.py` (window setting), `reddit/finished_scores.py` (new persistence module)  
**Test suite:** 2165 passed ✅

### Review Checklist

#### 1. No Double Correction ✅ PASS

After a correction fires, the watch updates the recorded score to the new API value:

```python
# 3. Update recorded score so subsequent ticks see no diff
entry["home"] = new_home
entry["away"] = new_away
entry["corrected"] = True
dirty = True
```

On the **next tick**, the comparison is:
```python
if new_home == recorded_home and new_away == recorded_away:
    continue  # stable — no correction needed
```

Since `recorded_home/away` now equals the API score → `continue` → no duplicate. ✓

The `corrected` flag is **informational only** (not used as a gate) — deliberate design
so a genuine second VAR correction (e.g. 2-2→2-1→2-0) would produce a second diff
against the UPDATED recorded score (2-1 vs 2-0) and correctly fire again. ✓

Test `test_no_duplicate_correction_on_third_tick` verifies this: entry with `home=2, away=1, corrected=True`, API still at 2-1 → `send_message.assert_not_awaited()`. ✓

#### 2. No False Correction ✅ PASS

**Normal stable match:** recorded == current → `continue`. Verified by
`test_no_correction_when_score_stable`. ✓

**Penalty shootout:** The watch compares `match.home_score`/`match.away_score`
(on-pitch regulation+ET score, which stays stable at e.g. 1-1 through the shootout).
`penalty_home`/`penalty_away` are entirely separate fields never read by this code.

Additionally, the check `if not match_result_is_final(current): continue` ensures
that a shootout match where penalties haven't fully settled yet is SKIPPED entirely —
no premature comparison against transient data. ✓

Test `test_penalty_shootout_no_false_correction`: GER-BRA 1-1 (shootout 4-3),
recorded 1-1, current 1-1 → no correction fired. ✓

**None scores:** `current.home_score if current.home_score is not None else 0` —
safe mapping. At recording time: same None→0 conversion. Both sides use the same
convention so they compare consistently. No spurious diff from None vs 0. ✓

#### 3. Window / Prune ✅ PASS

```python
stale = [
    mid_str for mid_str, entry in finished_scores.items()
    if _fs_entry_is_stale(entry, now_utc, window)
]
for mid_str in stale:
    finished_scores.pop(mid_str, None)
```

- Prune runs **before** the correction check → stale entries never fire corrections. ✓
- Window: `settings.final_correction_window_minutes = 30` → 30-min default.
- `_fs_entry_is_stale` returns True on unparseable timestamps → corrupted entries get
  pruned, not stuck. ✓
- Dict growth bounded: entries live max 30 minutes. With ~4 matches per day in
  knockout, the dict never holds more than ~4 entries at once.

Test `test_window_expiry_prunes_entry_no_correction`: 45-min-old entry pruned,
no correction posted, entry removed from dict. ✓

#### 4. Edit Safety ✅ PASS

**Keyboard preservation:**
```python
if entry.get("status") == "ready":
    edit_kwargs["reply_markup"] = build_goal_keyboard(tok)
```

When status is `"ready"` (clip found), `reply_markup` is explicitly passed →
Telegram's `editMessageText` preserves it. When status is `"searching"` or
other, `reply_markup` is **omitted** (not set to None) — this means Telegram
preserves whatever was there before. ✓

Test `test_keyboard_preserved_when_clip_ready`: asserts `reply_markup` is present
and equals `build_goal_keyboard(tok)`. ✓

**Token reconstruction (correct target):**
```python
for scoring_team in (match.home_name, match.away_name):
    token_key = f"{match_id}:{scoring_team}:{annulled_home}-{annulled_away}"
```

This probes both possible scoring teams (exhaustive — `_process_goal_delta` always
uses `match.home_name` or `match.away_name`). The annulled score (old pre-VAR score)
is used in the token, matching how it was stored at announce time. ✓

**Edit failure → non-fatal:**
```python
try:
    await context.bot.edit_message_text(**edit_kwargs)
except Exception as exc:
    log.warning(...)
```

The correction message is sent BEFORE the edit attempt (line order in
`_var_correction_watch`), so even if the edit fails, users still see the correction.
Outer try/except in `_mark_goal_annulled` also catches any unexpected error. ✓

Test `test_correction_sent_even_if_goal_message_absent`: clip_store empty → correction
message still sent, `edit_message_text.assert_not_awaited()`. ✓

#### 5. No Regression to Normal Finalize Path ✅ PASS

**Recording is nested try/except AFTER the successful send:**
```python
# (after send_message for the recap)
try:
    fs[str(match_id)] = {...}
    save_finished_scores(...)
except Exception as _rse:
    log.warning(...)
```

A recording failure cannot break finalization. The `finished_announced.add(match_id)`
runs in the `finally` block — always executes regardless. ✓

**`finished_announced` dedup unchanged:** The `announced.add(match_id)` + `save_finished`
pattern in the `finally` block is untouched. A match is still finalized exactly once. ✓

**`match_result_is_final` gate:** The VAR watch only processes matches where
`match_result_is_final(current)` is True — same gate that controls initial finalization.
No premature watch trigger. ✓

**Shootout deferral:** The initial finalization still defers via `match_result_is_final`.
The VAR watch also skips when that returns False. Both paths consistent. ✓

**Structural change:** The `if not new_ids: return` early-return was changed to call
`_var_correction_watch` BEFORE returning. This ensures the watch runs on every tick
(even without new finalizations), which is correct — corrections happen on subsequent
ticks by definition. The watch is also called AFTER the main finalize loop completes. ✓

#### 6. Suite Green ✅ PASS

```
2165 passed, 5 warnings in 60.94s
```

8 new tests specifically covering the correction watch; all existing finished-job
tests pass unchanged.

### VERDICT: ✅ APPROVE

The implementation is sound. No double correction (updated-score-then-diff), no false
positives (on-pitch score comparison + `match_result_is_final` gate), bounded window
with pruning, edit preserves the keyboard, and all failure paths are non-fatal with
graceful degradation (correction message is always sent even if the edit fails). Normal
finalize path is untouched. 2165 tests pass. Ship it.
