# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot  
**Stack:** Python, python-telegram-bot, football-data.org, Reddit scanner, LLM  
**Current test count:** 1661 (as of 2026-06-27)

## Latest Session: 2026-06-30 — Chat LLM Features (Picante + Revive)

**Task:** Implement two LLM-driven group-chat features per Pirlo's approved design spec.

### Team Ship: Pirlo (Lead) + Kanté (Backend) + Buffon (Tester) + Maldini (DevOps)

- ✅ **Pirlo:** Design spec, open decisions (13 Qs with David), lead review gate (APPROVED)
- ✅ **Kanté:** Full implementation of `src/worldcup_bot/chat/` package (5 modules), config wiring
- ✅ **Buffon:** 107 edge-case tests, comprehensive coverage, 0 bugs found
- ✅ **Maldini:** README privacy-mode docs, 12 env vars wired (docker-compose.yml, docker-compose.local.yml, .env.example)

**Test count:** 1768 baseline + 38 new (Kanté) + 107 edge-case (Buffon) = 1875 total ✅

**Key constraint:** BotFather privacy mode MUST be disabled (blocking pre-deployment step).

**Locked parameters:** probability 0.20, cooldown 300s, max 30/day, buffer 30, min buffer 5, inactive 3d, check 4h, mention cooldown 2d, temps 0.9/0.8.

**Ready for deployment:** Yes (if privacy mode is disabled first).

---

## Latest Session: 2026-06-30 — Chat LLM Features (Picante + Revive)

### New Package: `src/worldcup_bot/chat/`

| File | Purpose |
|------|---------|
| `buffer.py` | `RingBuffer(maxlen)` — in-memory deque of last N messages (`append`, `snapshot`, `len`) |
| `state.py` | `ChatState` dataclass + `load_chat_state(path)` / `save_chat_state(path, state)` — atomic JSON persist (no message text) |
| `listener.py` | `on_group_text` — PTB MessageHandler callback; filter pipeline → buffer → last_seen → maybe picante |
| `picante.py` | Pure gates: `probability_gate`, `cooldown_gate`, `daily_cap_gate`, `min_buffer_gate`; prompt builders; `maybe_reply` orchestrator |
| `revive.py` | Pure funcs: `compute_inactive_candidates`, `select_candidate`, prompt builders; `revive_inactive_job` periodic job |

### Participant→Username Matching Approach

**Decision:** The predictions YAML key (`participants.{username}`) IS the Telegram @username (lowercase, no @), per the schema comment `# @username en minúsculas, sin @`. So ALL porra participants are valid @mention candidates — no filtering needed. The `last_seen` dict is keyed by Telegram username and matches predictions keys directly.

### last_seen Seeding Decision

At `build_app()` startup:
- Load porra participants from predictions file
- For any participant NOT already in the persisted `chat_state.last_seen`, seed with current UTC time
- This prevents anyone from being pinged for inactivity on the very first deploy
- On restart: existing `last_seen` entries are preserved (only absent keys get seeded), so the real inactivity clock is maintained across restarts

### Persistence Strategy

- `last_seen` and all metadata are persisted only when a picante or revive event fires (not on every message, to avoid per-message disk writes)
- In-memory `last_seen` updates are accurate between persist events; on restart, porra participants are re-seeded only if missing

### Key File Paths

- State: `{state_dir}/chat_state.json`
- Chat buffer: `bot_data["chat_buffer"]` (RingBuffer, in-memory only)
- Chat state: `bot_data["chat_state"]` (ChatState)
- Chat state path: `bot_data["chat_state_path"]` (str)
- Porra usernames: `bot_data["porra_usernames"]` (list[str])
- Porra display names: `bot_data["porra_display_names"]` (dict[str, str])
- AI client: `bot_data["ai_client"]` (AIClient | None)

### Env Vars Added

| Env Var | Field | Default |
|---------|-------|---------|
| `CHAT_PICANTE_ENABLED` | `chat_picante_enabled` | `False` |
| `CHAT_REVIVE_ENABLED` | `chat_revive_enabled` | `False` |
| `CHAT_BUFFER_SIZE` | `chat_buffer_size` | `30` |
| `PICANTE_PROBABILITY` | `picante_probability` | `0.20` |
| `PICANTE_COOLDOWN_SECONDS` | `picante_cooldown_seconds` | `300` |
| `PICANTE_MAX_PER_DAY` | `picante_max_per_day` | `30` |
| `PICANTE_MIN_BUFFER` | `picante_min_buffer` | `5` |
| `PICANTE_TEMPERATURE` | `picante_temperature` | `0.9` |
| `REVIVE_CHECK_INTERVAL_SECONDS` | `revive_check_interval_seconds` | `14400` |
| `REVIVE_INACTIVE_DAYS` | `revive_inactive_days` | `3` |
| `REVIVE_MENTION_COOLDOWN_DAYS` | `revive_mention_cooldown_days` | `2` |
| `REVIVE_TEMPERATURE` | `revive_temperature` | `0.8` |

### Tests (+38, total 1768)

All in `tests/test_chat.py`:
- `TestRingBuffer` (4): append, maxlen eviction, len, snapshot-is-a-copy
- `TestChatStatePersistence` (5): round-trip, missing file, creates dirs, corrupt file, tmp cleanup
- `TestCooldownGate` (4): pass, block, exact boundary, zero-ts with realistic now
- `TestDailyCapGate` (5): new day, under cap, at cap, over cap, empty last_date
- `TestMinBufferGate` (3): pass, block, exact boundary
- `TestPicanteUserMessage` (3): format, empty placeholder, username fallback
- `TestComputeInactiveCandidates` (8): inactive, active, recently-mentioned, cooldown-expired, non-porra, sorted, blank username, seeded-not-immediately-inactive
- `TestSelectCandidate` (4): index 0, wrap-around, increment, single candidate
- `TestReviveUserMessage` (3): identity, context messages, empty buffer placeholder

### Config Gate Helpers Added

- `picante_enabled(settings)` → `settings.chat_picante_enabled and ai_enabled(settings)`
- `revive_enabled(settings)` → `settings.chat_revive_enabled and ai_enabled(settings)`

Both features OFF by default. Zero overhead when both disabled (MessageHandler not registered).



**Task:** Implement 4-part fix for catch-up (missed goals) and double-notify (post-FT oscillation) bugs. Pirlo design spec followed precisely.

### Confirmed Root Cause — Symptom B (Uruguay-Spain, owner-provided timeline)

The "two different goals" hypothesis from the investigation was WRONG. Owner provided the actual post-FT timeline:
- Final recap sent ~04:07
- 04:10 → "❌ Gol anulado (VAR) Uruguay 0-0 Spain" (spurious, post-FT)
- 04:11 → "⚽ ¡GOOOL! Spain 0-1, Álex Baena (42')" (same goal re-announced)

This is the **same oscillation as Egypt-Iran** but in the **post-FT, <4h window** — so the existing `_match_is_over` >4h prune didn't catch it. The Reddit thread parse flickered the VAR-disallowed event after FT, dropping then restoring the score → DISALLOWED then GOAL re-announcement. The fix is FINISHED-match eviction (Part 3 below).

### What Was Implemented

**Part 1 — 0-0 seed at kickoff** (`poll_kickoff_job`, `__main__.py:1462-1469`):
`poll_kickoff_job` now seeds `live_scores[match_key] = {home:0, away:0, status:IN_PLAY}` in the `finally:` block after announcing kickoff. Idempotent (only seeds if key absent). Saves immediately. Combined with POSTPONED/SUSPENDED eviction guard: if a seeded match becomes POSTPONED/SUSPENDED before kickoff, it's removed from live state within one poll tick.

**Part 2 — Catch-up recovery from Reddit thread** (`_attempt_goal_recovery`, `__main__.py:370-515`):
New async function `_attempt_goal_recovery`. Called by `_process_goal_delta` for catchup kind (when `seen_thread` and `match_key` are provided). Attempts `scanner.find_thread_permalink` (cached, no HTTP), falls back to `scanner.find_match_thread` (HTTP, 5s timeout). Parses events with `parse_goal_events`. Builds `goals_to_notify` by matching each missed goal score against `GoalEvent` via `_teams_match`. Sends proper `_notify_goal` calls (scorer + "Ver gol" keyboard). Returns `True` on success (skips neutral), `False` to fall through to `_notify_catchup`. After success: sets `seen_thread[match_key] = {home:curr_home, away:curr_away}` for dedup. Rule: ALL-proper or ALL-neutral, never mixed. `GoalDelta` now carries `prev_home`/`prev_away` (defaulting to 0) so `_attempt_goal_recovery` knows the starting window.

**Part 3 — FINISHED two-tick eviction** (`poll_goals_job`, `__main__.py:872-886`):
`was_already_finished = stored is not None and stored.get("status") == "FINISHED"` set inside `goal_lock` before processing. In the `else:` (no-delta) branch: if `was_already_finished` → evict (`scores.pop`, `seen_api.pop`, `seen_scores["thread"].pop`), `changed = True`. First FINISHED tick: `was_already_finished = False` → goes to normal no-delta path → updates status to FINISHED. Second FINISHED tick: `was_already_finished = True` → evicts. FT goal (first FINISHED tick with delta): goes to `elif deltas:` not `else:` → processed normally, no eviction. FT recap job uses its own `finished_announced` set — unaffected.

**Part 4 — Immediate save in poll_thread_goals_job** (`__main__.py:1073`):
`save_scores(state_path, scores)` moved INSIDE the `goal_lock`, immediately after claiming `scores[key]["home/away"]`. Removed the deferred `if changed: save_scores(...)` at end of loop. Closes the save-window race where a crash between in-memory claim and deferred save could cause re-announcement on restart.

**Part 5 (non-blocking rec) — 5s timeout** (`scanner.py:~373`):
`find_match_thread` HTTP timeout reduced from 15s to 5s so recovery never hangs the poll job.

**POSTPONED/SUSPENDED eviction** (`poll_goals_job`, `__main__.py:755-772`):
Pre-processing step (after over_ids prune, before relevant filter) evicts any match with POSTPONED or SUSPENDED status that has an entry in `scores`. Saves immediately if any evicted.

### Tests Added (+17, total 1661)

**`TestFinishedEviction`** (5): first-FINISHED-tick-updates-status-no-eviction, second-FINISHED-tick-evicts, Uruguay-Spain full timeline zero post-FT sends, real VAR during IN_PLAY still fires, final goal at FT still notified.

**`TestCatchupRecovery`** (4): proper per-goal sends (not neutral) when thread available, seen_thread dedup claimed after recovery, fallback when thread unavailable, fallback when event can't be matched.

**`TestPostponedEviction`** (2): POSTPONED eviction, SUSPENDED eviction.

**`TestKickoffSeedLiveScores`** (3): seeds at 0-0, idempotent if key already present, integration: kickoff seed → 0-0 poll → 0-1 proper goal (not catchup).

**`TestImmediateSave`** (2): save called once with new score, save persists claim even when notify fails.

**`TestPostFTEvictionDedup`** (1): evicted match skipped by thread job, zero sends.

### Key Learnings

1. **Post-FT oscillation is <4h** — the Egypt-Iran fix (>4h wall-clock prune) does NOT cover the Uruguay-Spain case. Matches oscillate for 4-10 min after FT, well within the 4h window. The two-tick FINISHED eviction is the correct fix for this specific window.
2. **Recovery design: ALL-proper or ALL-neutral** — never mix in a single catch-up event. If any individual missed goal can't be matched to a thread event, fall back entirely to neutral. `prev_home`/`prev_away` on `GoalDelta` provide the window boundaries.
3. **0-0 seed changes the first-seen behavior** — after kickoff seed, `stored is not None` on the first `poll_goals_job` tick → goes to the normal `elif/else` branch, NOT the `stored is None` first-seen catchup path. This is the desired behavior: proper incremental goal detection from the start.
4. **Two-tick eviction timing** — Tick 1 keeps the match alive (catches any final goal reported at exact FT). Tick 2 (min ~2 minutes later) evicts if no new delta. This is sufficient to prevent post-FT thread oscillation from firing while still catching final-minute goals.



**Task:** Investigation + fix-proposal only (no code changed). Three live symptoms.

### Root Causes

**Symptom A — "Me perdí 1 gol" (NZL 0-1 BEL):** `poll_goals_job`'s `relevant` filter
(`__main__.py:589-596`) excludes SCHEDULED/TIMED matches. football-data.org takes 5-15 min
to flip status to IN_PLAY. Belgium scored in that window. When the API flipped, the match
was already 0-1 → `stored is None` branch (`__main__.py:630-660`) seeds at 0-1, emits ONE
neutral catch-up. Thread job cannot rescue (`__main__.py:800-805` — skips unseeded matches).
`poll_kickoff_job` sends the kickoff notice but does NOT seed `live_scores` at 0-0.

**Symptom C — "Me perdí 4 goles" (NOR 1-3 FRA):** Bot restarted mid-match. On restart,
`seen_api` and `seen_thread` reset to `{}` (`build_app:1461`). `live_scores.json` either
empty or stale. First poll_goals_job tick sees the match as IN_PLAY at 1-3 → seeds at 1-3
→ catch-up for 4 goals. Also possible: API flip so late the match was already 1-3 when
first seen (status-flip cause; less likely for 4 goals).

**Symptom B — España double-notify:** Code analysis exhausted; no deterministic single-
instance path found for a true same-goal duplicate. Three candidates:
1. **(Most likely) Two separate goals:** Thread announced goal 1 live (scorer/video). Thread
   job cannot scan FINISHED matches (`get_live_matches()` returns only IN_PLAY/PAUSED). Goal 2
   scored near FT, thread missed it. API announced goal 2 at FINISHED via `elif deltas`
   (`__main__.py:662-675`) when `_ahead(curr_final, ann_goal1) = True`. Owner perceived as dup.
2. **Save-window race on restart:** Thread job claims score in memory (line 858) but
   save_scores deferred to line 976. If crash in that window, disk has pre-goal score. On
   restart, first FINISHED tick → catch-up (⚠️ format). Owner sees proper + catch-up = "twice."
3. **FINISHED-first-sees-goal (B3):** API first reports goal at FINISHED (score skipped IN_PLAY
   confirmation). `reconcile({0,0},{0,0},1,0)` → proper goal delta. Only one notification in
   this sub-case (thread job doesn't fire on FINISHED). Owner confirmation required.

**Owner action needed:** Confirm España final score and whether second notification was ⚽ or ⚠️.

### Fix Plan (no code yet — awaiting Pirlo + owner decisions)

1. **Seed at 0-0 at kickoff** — extend `poll_kickoff_job` to write `live_scores[match_key] = {home:0, away:0}` when sending kickoff notice. Eliminates most Symptom A cases and the live-onset part of C. Risk: delayed matches leave stale 0-0 entries (self-heal via `_match_is_over` after 4h).

2. **Recover scorer+video for missed goals** — in `poll_goals_job`'s seed-at-nonzero path and in `_process_goal_delta` for catch-up deltas: attempt thread recovery via `scanner.find_thread_permalink` + `parse_goal_events`. If thread has goal events, emit proper `_notify_goal` per missed goal (scorer + "Ver gol" button). Fall back to neutral catch-up only when thread unavailable. **Requires Pirlo sign-off** — revises 2026-06-26 Decision 1 (neutral-only catch-up).

3. **Immediate save after thread-job goal claim** — move `save_scores` from line 976 to immediately after each matched goal claim inside the loop. Closes the save-window race (Symptom B Candidate 2). Low risk: one extra disk write per goal tick.

4. **FINISHED-match eviction after first processed tick** — after `poll_goals_job` processes a FINISHED match with no new delta and status already stored as FINISHED, mark it `evict=True` and remove on the next tick. Prevents any FINISHED-tick re-announce. **Requires Pirlo sign-off** — changes the "FINISHED-in-scores for up to 4h" policy.

### Full report
`.squad/decisions/inbox/kante-catchup-investigation-missed-goals-duplicate.md`

**Gates:** PENDING (no code changes; investigation only)

---

## Previous Session: 2026-06-27 — Finished-Match Goal Loop Fix

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
