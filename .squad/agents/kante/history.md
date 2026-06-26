# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot  
**Stack:** Python, python-telegram-bot, football-data.org, Reddit scanner, LLM  
**Current test count:** 1629 (as of 2026-06-26)

## Latest Session: 2026-06-26 — TVE 📺 Label Fix

**Issue:** 09:00 daily update never showed TVE labels; manual `/updateDiario` later in day did.

**Root causes:**
- **RC1:** Failure-caching bug — `load_tve_broadcasts` cached empty results unconditionally even when all fetches failed
- **RC2:** RTVE publishes schedule mid-morning (~10:40), after 09:00 job fires; pre-show times miss ±20 min window

**Fixes:**
- Don't cache failed fetches; track `any_fetch_ok`
- 30-min TTL for empty results (vs 6h for populated)
- Same-day TLA-pair fallback tier in `tve_channel_for` for pre-show offsets

**Files:** `src/worldcup_bot/tve.py`, `tests/conftest.py`, `tests/test_tve.py` (+8), `tests/test_ai.py` (+1)

**Test delta:** 1618 → 1629 (+11 total from Kanté +9, Buffon +2)

**Gates:** Pirlo APPROVED; Buffon PASS WITH ADDED TESTS (+2 edge cases)

**Recommendation:** Move `DAILY_UPDATE_HOUR` to 11:00 (env-configurable, aligns with RTVE ~10:40 publish)

---

## Previous Sessions

See `history-archive.md` for detailed archived sessions:
- 2026-06-22 — Kickoff-Start Notifications
- 2026-06-26 — Live Goal Notification Bug Fixes
- 2026-06-26 — Best-Qualifying-Thirds Scoring

---

## Current Session: 2026-06-22 — Kickoff-Start Notifications

**Feature:** Match-start kickoff notices when scheduled UTC time arrives.

## Latest Implementation

### 2026-06-22 — Kickoff-start notice (`poll_kickoff_job`)

**Feature:** The bot posts `🟢 ¡Empieza el partido! {home_flag} <b>Home</b> vs <b>Away</b> {away_flag}` to the Telegram group within ~30 s of each match's scheduled kickoff time.  Time-based (the `utc_date` field from the football-data API), does NOT wait for the status to flip to IN_PLAY.

**Job:** `poll_kickoff_job(context)` in `__main__.py`.  Runs every 30 s (hardcoded; no new env var). Registered inside the existing `if settings.telegram_group_id:` block alongside `poll_finished_matches_job` and `poll_goal_clips_job`.

**State:** Persisted to `{state_dir}/kickoff_announced.json` as a sorted JSON array of match ids. Reuses `load_finished` / `save_finished` from `finished_state.py` (same generic helpers used by the finished-recap job) — no new module needed, stays DRY.  Wired in `build_app` as `app.bot_data["kickoff_announced"]` (loaded from disk) and `app.bot_data["kickoff_seeded"] = False`.

**Restart safety — seed pass (first run only):** On the first tick (`kickoff_seeded == False`), every match whose kickoff `<= now_utc` OR whose status is IN_PLAY / PAUSED / FINISHED is added to `announced`, the state is persisted, and the job returns immediately (no sends).  Container restarts therefore never re-announce matches that already kicked off before the restart.

**Grace window:** After the seed pass, the normal pass announces a match only when `kickoff <= now_utc AND elapsed <= 30 min`.  Matches that escaped the seed (e.g. a race between seed and the API) and are already > 30 min in the past are silently marked in `announced` without sending.

**Formatter:** `format_match_start(match) -> str` added to `bot/formatters.py` (pure function, testable without imports from `api/` or `porra/`). Returns HTML-safe text with bold team names and flag emojis.  Sent with `parse_mode="HTML"`.

**Silent hour:** `_is_silent_hour` reused — messages between 00:00–09:00 local time use `disable_notification=True`.

**Tests:** `tests/test_poll_kickoff_job.py` — 21 tests across TestSeedPass (5), TestNormalPass (6), TestRestartSafety (1), TestSilentHour (2), TestAPIError (1), TestFormatMatchStart (6).  All using real relative-time fixtures (no datetime mocking needed — offsets are computed at module load against `datetime.now(UTC)`).
**Test count:** 1531 → 1552.

---

## Learnings: 2026-06-26 — Live goal notification bugs (production incident)

**Test count:** 1552 → 1568.

### Root cause A1 — API status-flip delay (Ecuador-Germany missed 0-1, 1-1)

`poll_goals_job` only enters the `relevant` list when the API reports `IN_PLAY` or `PAUSED`.
football-data.org sometimes delays this status flip by 5–15 minutes.  When it finally flips,
the score can already be `1-1`.  The seeding code (`__main__.py:519`) called
`reconcile(None, None, 1, 1)` which returned `([], {1,1}, {1,1})` — seeded at 1-1, emitted
nothing.  The 0-1 and 1-1 goals were lost forever.

**Fix:** In the `stored is None` branch of `poll_goals_job`, if `curr_home + curr_away > 0`,
emit synthetic catch-up `GoalDelta` objects using home-first intermediate scores
`(1,0)..(H,0)` then `(H,1)..(H,A)` so each goal gets a unique token and a notification.

### Root cause A2 — Bot restart mid-match (missed goals while bot was down)

`reconcile()` `score_state.py:176-179` had a blind "seed pass" when `seen is None`:
```python
if seen is None:
    ann = announced if announced is not None else new
    return ([], new, ann)   # BUG: always [] even when new > announced
```
After a restart, `seen_api[key]` is empty (in-memory dict), but `live_scores.json` has the
last persisted score (e.g. `{1,1}`).  On first tick the seed pass set `new_seen = {2,1}`
but returned `[]` (no delta).  On the second tick `new == seen` → no delta.
The `{1,1} → {2,1}` goal is permanently lost.

**Fix:** `reconcile()` now distinguishes the restart case:
- `seen is None, announced is None` → seed both, emit nothing (unchanged).
- `seen is None, announced is not None, new > announced` → emit catch-up deltas from `announced` to `new`.
- `seen is None, announced is not None, new <= announced` → no delta (source lagging).

The existing "API lag" tests pass unchanged: `_ahead({3,2},{4,2})` is False → no delta.

Key file+line: `score_state.py:174-179` (old bug), `score_state.py:174-205` (fix).

### Root cause B1 — Keyboard race condition (Tunisia-NL, Japan-Sweden, Turkey-USA)

`poll_goal_clips_job` (`__main__.py:967-973`) set `entry["status"] = "ready"` AFTER
`await context.bot.edit_message_reply_markup(...)`.  During that network round-trip,
`_backfill_scorer_in_clip_store` could run, see `status="searching"`, and call
`edit_message_text(reply_markup=None)` — which the Telegram API interprets as "clear keyboard".

**Fix:** Reorder so `entry["status"] = "ready"` and `entry["clip_path"]` are set BEFORE the
`edit_message_reply_markup` call.  Backfill now always sees the correct status.

Key file+line: `__main__.py:954-973` (old), `__main__.py:954-977` (fixed).

### Root cause B2 — Disk-full download failures

With ~4 GB free and a 7-day prune window, clips accumulate.  Full disk → `download()` returns
`None` → status stays `"searching"` → timeout → no keyboard.  This is expected behavior; the
delete-after-send feature (Fix D) directly mitigates it.

### Fix D — Delete clip after successful send (`handlers.py`)

After `send_video` succeeds and `file_id` is persisted to `goal_clips.json`, the local file
is deleted (`Path.unlink(missing_ok=True)`).  Subsequent taps use the cached `file_id` fast
path.  Never raises.  Save happens BEFORE delete so file_id is durable on disk first.

Key file+line: `handlers.py:849-868` (new delete block).

### Pattern: `edit_message_text(reply_markup=None)` CLEARS the inline keyboard

Confirmed footgun: passing `reply_markup=None` to `edit_message_text` sends an explicit JSON
`null` to the Telegram API which removes the keyboard.  Any code path that edits a goal
message text (for scorer back-fill, etc.) MUST always check `entry["status"] == "ready"` and
pass `reply_markup=build_goal_keyboard(tok)` when it is, or omit the keyboard argument
entirely if you want to preserve it (do NOT pass `None`).

See `_backfill_scorer_in_clip_store` (`__main__.py:353`) for the correct pattern.

---

## Learnings: 2026-06-26 — Best-qualifying-thirds scoring (WC2026 format)

**Test count:** 1571 → 1613 (+42 tests).

### Problem
WC2026 has 12 groups of 4. Top-2 of each group qualify automatically. The 8 best
third-placed teams (by FIFA tiebreakers: pts > GD > GF) also qualify. The old
`score_groups` awarded 1.0 for exact 3rd without checking qualification.

### `best_qualifying_thirds()` algorithm

Pure function in `scoring.py`. Input: `{GROUP_X: [{"tla","points","goal_difference","goals_for"},…]}`.
1. Extract index-2 (3rd-place) entry per group (skip groups with < 3 entries).
2. Sort by `(-pts, -gd, -gf, group_key, tla)` — deterministic stable fallback: group letter then TLA alphabetically.
3. If < `NUM_QUALIFYING_THIRDS` (8) thirds present: return all as `frozenset` (provisional — all qualify).
4. If >= 8: take top 8. If a tie exists at positions 8/9 boundary, log a WARNING (we can't resolve disciplinary/drawing-lots tiebreakers from API data).
5. Returns `frozenset[str]` of qualifying TLAs.

Constants/knobs (all in `scoring.py`):
- `NUM_QUALIFYING_THIRDS = 8`
- `NON_QUALIFYING_THIRD_SCORE = 0.0` — owner may set to 0.5 for partial credit
- `DIRECT_QUALIFY = 2` (unchanged)

### STRICT scoring policy

| pred | actual | qualifies? | score | label |
|------|--------|-----------|-------|-------|
| top-2 | top-2 | (always) | 1.0 | exacto |
| 3 | 3 | yes | 1.0 | exacto |
| 3 | 3 | no | `NON_QUALIFYING_THIRD_SCORE` (0.0) | fallo |
| top-2 | 3 | yes | 0.5 | clasifica |
| top-2 | 3 | no | 0.0 | fallo |
| 3 | top-2 | (team advanced) | 0.5 | clasifica |
| top-2 | 3 | — (backward-compat, None) | 0.5 | clasifica |

`score_groups(user_groups, actual_standings, qualifying_thirds=None)` —
`None` means "treat all 3rds as qualifying" (backward-compatible default).

### Where qualifying_thirds is threaded

**engine.py (live API path):**
- `_build_qualifying_thirds(client, only_groups)` — pure helper after `_build_actual_standings`.
  Calls `get_standings()` (TTLCache 60 s — cache hit if already called), builds
  `{GROUP_X: [Standing…]}`, converts to `{GROUP_X: [{"tla","points","goal_difference","goals_for"},…]}`,
  calls `best_qualifying_thirds()`. Returns `frozenset`.
- Passed into `compute_general_ranking_from(…, qualifying_thirds=…)`,
  `compute_group_ranking`, `compute_general_ranking`, `compute_user_detail`.

**history.py (match-reconstruction path):**
- `reconstruct_full_group_standings(matches)` — new function returning
  `{GROUP_X: [{"tla","points","goal_difference","goals_for"},…]}` ordered by position.
  Built on the existing `_compute_group_stats`/`_sort_order` helpers.
- `compute_ranking_at_jornada(…)` calls `reconstruct_full_group_standings` then
  `best_qualifying_thirds` and passes the frozenset into `compute_general_ranking_from`.

### Provisional handling

When not all 12 groups have data (mid-tournament or `only_groups` filter):
- `_build_qualifying_thirds` / `reconstruct_full_group_standings` only sees N < 12 groups.
- `best_qualifying_thirds` with < 8 thirds: returns ALL known thirds as qualifying.
- This is intentionally optimistic (provisional) — consistent with the existing provisional
  group-scoring behavior where partial standings are used without penalizing users.
- Once all 12 groups are done and 12 thirds exist, the exact 8 are picked.

### Standing model extension

`api/models.py`: Added `goal_difference: int = 0` and `goals_for: int = 0` (optional fields
with defaults). All existing positional constructors remain valid.
`api/client.py`: `get_standings()` now parses `goalDifference` and `goalsFor` from payload.

### history.py `reconstruct_group_standings` (existing) vs `reconstruct_full_group_standings` (new)

The existing `reconstruct_group_standings` returns `{GROUP_X: [tla,…]}` — unchanged,
still used by other callers. The new `reconstruct_full_group_standings` returns richer dicts.
Both share `_compute_group_stats` and `_sort_order` helpers to avoid duplication.

## Learnings: 2026-06-26 — TVE 📺 label missing from 09:00 daily update

**Test count:** 1618 → 1627 (+9 tests).

### Confirmed root causes

**RC1 — Failure-caching bug (confirmed, code bug)**

`load_tve_broadcasts` unconditionally executed `_tve_cache["data"] = broadcasts` and `_tve_cache["fetched_at"] = now` even when ALL channel fetches returned `None` (network timeout, RTVE outage). An empty list was cached for 6 hours. Any `generate_daily_update` or `/updateDiario` call within that 6-hour window saw `tve_by_key = {}` → no TVE label. `/updateDiario` worked when the owner ran it after: (a) the cache naturally expired at 15:00, or (b) the bot was restarted (clears module-level cache).

**RC2 — RTVE schedule published mid-morning (~10:40, confirmed from live `diahoy` field)**

Live RTVE API (`diahoy = 20260626104143` for La 1, `20260626103942` for Teledeporte) shows the schedule is updated around 10:40 CEST, AFTER the 09:00 daily update runs. At 09:00, either:
- The schedule for today's WC matches was not yet published (fetches succeeded but `broadcasts = []`), OR
- Copa del Mundo items lacked the `(HH:MM)` kickoff in description (RTVE adds it on publish), causing `_parse_kickoff_utc` to fall back to `begintime` (the pre-match show start, which can be >20 min before actual kickoff), making `tve_channel_for` miss the ±20 min window.

RC1 also silenced RC2 by caching the incorrect result for 6 hours.

### Fixes applied — `src/worldcup_bot/tve.py`

**Fix 1 — Don't cache failed fetches (RC1)**
Track `any_fetch_ok`. Only update `_tve_cache` when at least one channel returned a non-None response. If all channels fail, return `[]` without caching so the next call (e.g., `/updateDiario`) retries immediately.

**Fix 2 — Short TTL for empty WC schedules (RC2 timing)**
When fetches succeed but no WC matches are found (`broadcasts = []`), store `_EMPTY_RESULT_TTL = 1800` (30 min) instead of 6 hours. The bot will retry before the next live window, picking up the RTVE update that lands ~10:40.

**Fix 3 — Same-day TLA-pair fallback in `tve_channel_for` (RC2 time-offset)**
Added a third matching tier after the primary ±20 min window and the time-only fallback: if the primary window finds no candidates, check for a broadcast on the same UTC calendar date with an exact TLA pair match. This correctly handles pre-show `begintime` values that are >20 min before the actual kickoff when the description hasn't been updated yet. Safe for WC: teams never play twice in the same day.

### Other changes
- `tests/conftest.py` — `reset_tve_cache` also pops `_ttl` key from cache dict.
- 9 new tests across `tests/test_tve.py` (+8) and `tests/test_ai.py` (+1).


**Test count:** 1570 → 1571 (after refinements; +1 net over Buffon's gate count)

### Required Change 1 — Neutral catch-up message (Pirlo design call)

Replaced the N synthesised per-goal catch-up messages with ONE honest neutral message.

**Motivation:** When the bot misses goals (status-flip delay or restart), it has no event data.
Emitting `"⚽ GOOOL! Ecuador — Ecuador 1-0 Germany"` fabricates a scoreline that never
existed and attributes goals to the wrong team.  Pirlo decided: emit ONE neutral summary.

**Format:**
```
⚠️ Me perdí 2 goles
🇪🇨 Ecuador 1-1 Germany 🇩🇪
```

**Changes:**
- `score_state.py`: `GoalDelta` gains `goals_missed: int = 0` field.  Restart-ahead path
  returns ONE `GoalDelta(kind="catchup", goals_missed=N)` instead of N fabricated goal deltas.
- `notifier.py`: `format_catchup_message(...)` added (produces the neutral message HTML).
- `__main__.py`: `_notify_catchup()` helper added (sends message + registers ONE clip-store entry
  keyed `{match_id}:catchup:{H}-{A}`).  `_process_goal_delta()` handles `kind="catchup"` by
  calling `_notify_catchup()` instead of `_notify_goal()`.  First-seen-non-zero branch now
  emits ONE `GoalDelta(kind="catchup")` instead of N per-team goal deltas.

**Clip-store token for catchup:** `{match.id}:catchup:{H}-{A}` — the clip finder still locates
any recent goal clip for this match; the "Ver gol" button can still appear on the catch-up
message if a clip is found.

### Required Change 2 — Backfill keyboard hardening (Pirlo + defence-in-depth)

Changed `_backfill_scorer_in_clip_store` (`__main__.py`) to OMIT `reply_markup` entirely from
`edit_message_text` kwargs when status ≠ "ready".  Previously it passed `reply_markup=None`
which sends `reply_markup: null` to Telegram → removes any existing keyboard.  Omitting the
key leaves existing Telegram markup unchanged regardless of timing.

```python
edit_kwargs = {"chat_id": ..., "message_id": ..., "text": ..., "parse_mode": "HTML"}
if entry.get("status") == "ready":
    edit_kwargs["reply_markup"] = build_goal_keyboard(tok)
# key absent → Telegram preserves existing markup
await context.bot.edit_message_text(**edit_kwargs)
```

### Test reconciliation

- `test_restart_new_ahead_of_announced_emits_home_delta`: updated to assert `kind="catchup"`, `goals_missed=1`
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
