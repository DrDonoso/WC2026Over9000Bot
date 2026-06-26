# Decision: Live goal notification bugs — root causes and fixes

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-26  
**Status:** IMPLEMENTED — 1571 tests green (after Pirlo review + Buffon gate)

---

## Root Causes Found

### Bug A — Missed goal notifications (Ecuador-Germany 0-1, 1-1 never arrived)

**Two distinct causes:**

**A1 – API status-flip delay** (most likely for Ecuador-Germany):  
\poll_goals_job\ only processes matches with status \IN_PLAY\ or \PAUSED\.  
The football-data API sometimes takes 5–15 minutes to flip a match from \SCHEDULED\ to \IN_PLAY\.  
When it finally flips, it may already show a non-zero score (e.g. \1-1\).  
The seeding code in \__main__.py:519-532\ called \econcile(None, None, curr_home, curr_away)\ which silently stored the current score as the baseline, announcing nothing for the earlier goals.  
\poll_thread_goals_job\ also missed these because it guards on \scores.get(key) is None\.

**A2 – Bot restart mid-match** (possible contributor):  
\econcile()\ in \score_state.py:176-179\ had a blind seed pass:  
\\\python
if seen is None:
    ann = announced if announced is not None else new
    return ([], new, ann)   # ALWAYS [] — bug
\\\
On restart, the per-source \seen\ dict is empty (in-memory, not persisted).  
First tick: \econcile(None, {1,1}, 2, 1)\ → \
ew_seen={2,1}\, no deltas emitted.  
Second tick: \
ew == seen\ (both {2,1}) → no deltas again.  
The 1-1 → 2-1 transition is permanently lost.

### Bug B — Missing inline keyboards (Tunisia-NL, Japan-Sweden, Turkey-USA)

**Two causes:**

**B1 – Race condition between \poll_goal_clips_job\ and \_backfill_scorer_in_clip_store\:**  
\poll_goal_clips_job\ in \__main__.py:967-973\ set \ntry["status"] = "ready"\ AFTER  
\wait context.bot.edit_message_reply_markup(...)\.  
If \_backfill_scorer_in_clip_store\ ran in the asyncio gap during the network round-trip,  
it saw \status="searching"\, called \dit_message_text(reply_markup=None)\,  
which the Telegram API interprets as "clear the keyboard".  
This was confirmed at \__main__.py:353\ (\keyboard = ... if entry.get("status") == "ready" else None\).

**B2 – Disk-full download failures:**  
If the volume was full, \downloader.download()\ returned \None\ → status stays \"searching"\ → timeout → no keyboard ever added.  
This is expected behavior but exacerbated by clips accumulating over many matches.

### Bug C — Disk space assessment

~4 GB free is borderline. At ~30 MB per clip × ~3 goals/match × multiple concurrent matches, space fills quickly with a 7-day retention window. Disk-full download failures (Bug B2) are a direct consequence. The new delete-after-send (see below) mitigates this substantially going forward.

---

## Fixes Implemented

### Fix A1 — reconcile() restart case (\score_state.py\)

When \seen is None\ (first tick for this source after restart) and \nnounced is not None\ (persisted baseline exists), use \_ahead()\ to check whether goals were missed. Emits ONE neutral catch-up \GoalDelta(kind="catchup")\ instead of N fabricated per-goal deltas:

\\\python
if seen is None:
    if announced is None:
        return ([], new, new)          # truly first-seen — seed only
    if _ahead(new, announced):
        # Goals scored while bot was down — emit ONE neutral catch-up delta
        catchup = GoalDelta(kind="catchup", goals_missed=home_diff+away_diff, ...)
        return ([catchup], new, new)
    return ([], new, announced)        # source lagging — no delta
\\\

### Fix A2 — Initial non-zero seeding (\__main__.py — poll_goals_job\)

In the \stored is None\ branch, when \curr_home > 0 or curr_away > 0\, emit ONE \GoalDelta(kind="catchup")\ instead of N synthesised per-team goals. This prevents broadcasting fabricated scorelines that never existed.

### Fix B1 — Status before edit (\__main__.py — poll_goal_clips_job\)

Reordered:
\\\python
# Before fix: set status AFTER edit (keyboard race)
# After fix: set status BEFORE edit (backfill sees "ready" during network round-trip)
entry["status"] = "ready"
entry["clip_path"] = str(persistent_path)
await context.bot.edit_message_reply_markup(...)
\\\

### Fix B2 — Backfill keyboard hardening (\__main__.py — _backfill_scorer_in_clip_store\)

Changed to OMIT \eply_markup\ from \dit_message_text\ kwargs when status ≠ "ready", rather than passing \eply_markup=None\. Passing \None\ sends \eply_markup: null\ to Telegram which removes any existing keyboard. Omitting the key leaves the existing markup unchanged.

\\\python
edit_kwargs = {"chat_id": ..., "message_id": ..., "text": ..., "parse_mode": "HTML"}
if entry.get("status") == "ready":
    edit_kwargs["reply_markup"] = build_goal_keyboard(tok)
# If not ready: key is absent → Telegram preserves existing markup
await context.bot.edit_message_text(**edit_kwargs)
\\\

### Fix D — Delete clip after successful send (\handlers.py — cmd_ver_gol_callback\)

After \send_video\ succeeds and \ile_id\ is persisted to \goal_clips.json\, the local file is deleted:

\\\python
if sent_msg and sent_msg.video:
    entry["file_id"] = sent_msg.video.file_id
    _cs_save_clips(clips_path, clip_store)   # persist file_id FIRST
    # Delete local file — future taps use file_id; stale file_id falls back gracefully
    Path(clip_path_str).unlink(missing_ok=True)
\\\

**Safety guarantees:**
- Delete only runs AFTER successful send AND after file_id is saved to disk.  
- Never raises — wrapped in try/except/log.  
- \prune_old_entries\ already uses \missing_ok=True\, so no conflict.  
- If file_id later expires, the existing "file not found" path sends an error message.

---

## Catch-Up Message Format (neutral, no fabrication)

\\\
⚠️ Me perdí 2 goles
🇪🇨 Ecuador 1-1 Germany 🇩🇪
\\\

- ONE message per catch-up event, regardless of how many goals were missed.
- No scoring team attribution; no intermediate scoreline.
- A single clip-store entry is registered with token \{match_id}:catchup:{H}-{A}\.
  The clip finder can still locate a recent goal clip and attach a "Ver gol" button.

---

## Recommendation for Maldini (compose/volume)

The 7-day prune window (\prune_old_entries\) combined with many matches accumulating clips risks filling the volume. The new delete-after-send removes files as soon as Telegram caches them, dramatically reducing steady-state disk usage.

**Recommended:**
1. Consider reducing \max_age_days\ in \prune_old_entries\ from 7 to 2 for faster background cleanup of clips that were never pressed (search timed out or no one pressed the button).
2. Monitor volume with a disk-usage alert at <1 GB free.
3. The delete-after-send fix handles the "pressed" case; the prune handles the "never pressed" case.

---

## Tests

Full suite: **1571 passed** (1552 before this session; +16 by Kanté; +2 by Buffon; +3 catchup redesign by Kanté — net +21 total).

Files changed:
- \src/worldcup_bot/reddit/score_state.py\ — GoalDelta.goals_missed field, Fix A1 (single catchup delta)
- \src/worldcup_bot/reddit/notifier.py\ — format_catchup_message()
- \src/worldcup_bot/__main__.py\ — _notify_catchup(), Fix A2 (single catchup delta), Fix B1 (status before edit), Fix B2 (omit reply_markup)
- \src/worldcup_bot/bot/handlers.py\ — Fix D (delete after send)
- \	ests/test_score_state.py\ — restart tests updated for single catchup delta; Buffon's test updated
- \	ests/test_poll_goals_job.py\ — catchup tests updated; new neutral-message assertion test
- \	ests/test_poll_thread_goals_job.py\ — backfill-no-keyboard assertion updated (absent not None)
- \	ests/test_poll_goal_clips_job.py\ — keyboard race condition tests (unchanged, still valid)
- \	ests/test_handlers.py\ — delete-after-send tests (unchanged, still valid)

---

# Decision: Clip Disk Investigation: Retention, Disk Pressure & Missing Keyboards (2026-06-26)

**Author:** Maldini (DevOps)  
**Status:** Investigation summary

## 1. Clip Storage Infrastructure

### Disk Location
- **Container path:** \/app/state/clips/\
- **Volume mount:** Named volume \ot_state\ → \/app/state\ in both \docker-compose.yml\ and \docker-compose.local.yml\
- **Configuration:** 
  - \STATE_DIR\ env var defaults to \/app/state\ (set in both compose files)
  - \clips_dir = Path(settings.state_dir) / "clips"\ — created on first poll_goal_clips_job run
  - Directory is created on-demand: \clips_dir.mkdir(parents=True, exist_ok=True)\ in __main__.py:867

### Clips File Naming
- Stored as \{state_dir}/clips/{token}.mp4\ where \	oken = SHA1(goal_key)[:12]\
- Per-goal metadata persisted in \{state_dir}/goal_clips.json\

---

## 2. Current Retention Policy

### Active Cleanup: \prune_old_entries()\
- **File:** \src/worldcup_bot/reddit/clip_store.py:122\
- **Invocation:** Called every 45 seconds during \poll_goal_clips_job\ (async job)
- **Job scheduling:** \pplication.job_queue.run_repeating(poll_goal_clips_job, interval=45, first=20)\ in __main__.py
- **Max age:** **7 days** (default, line 122: \max_age_days: int = 7\)
- **Scope:** Removes entries + their disk files older than 7 days

### Clips NOT Deleted on Send
- **Handler:** \cmd_ver_gol_callback()\ in handlers.py:753
- **Behavior:** Clips are kept in persistent volume after sending to user
- **Reason:** Multiple users can tap the same "Ver gol" button; one send should not invalidate the clip for others
- **Note:** File existence check at line 821 logs error if clip missing (expected after pruning)

### Size Cap Today
- **Explicit size limit:** **NONE** — no total-volume size cap exists
- **Risk:** Pathological case (compression failures, edge cases) could theoretically fill the volume
- **Reality:** With 7-day retention + typical match-day volumes, disk pressure is unlikely unless retention is broken

---

## 3. Disk Pressure Estimation

### Typical Clip Sizes
- **Telegram limit:** 50 MB per video (video.py:16)
- **Compression logic:** Files over 50 MB are re-encoded (video.py:88-148)
- **Expected range:** 10–30 MB per goal clip (typical short goals, ~30 sec at 720p)
- **Worst case:** 1–2 uncompressible videos (edge cases, timeouts) → skipped

### Clips Stored at Any Time (7-day retention)
- **Typical match-day:** 3–4 goals per match × ~4 matches = 12–16 goals/day
- **Weekly volume:** 12–16 goals/day × 7 days = 84–112 clips stored
- **Disk usage estimate:** 
  - Conservative: 84 clips × 10 MB = **840 MB**
  - Aggressive: 112 clips × 30 MB = **3.36 GB**
  - **Expected range: 800 MB – 3 GB**

---

## 4. Assessment

**Disk-full is unlikely to be the direct cause** of yesterday's missing keyboards, but it's worth monitoring because:
- The 4GB free estimate assumes \prune_old_entries\ is working correctly
- If prune silently failed (corrupt JSON, permissions), retention would break and disk could fill
- Write failures during download/move don't throw explicit disk-full errors; they silently fail and manifest as missing keyboards

**Most likely causes of missing keyboards:**
1. Clip finder couldn't locate the goal on Reddit (title/name mismatch)
2. Download or compression failed silently
3. Poll job was slow → keyboard appeared minutes after goal

---

# Review: Live Goal Notification Bug Fixes

**Reviewer:** Pirlo (Lead / Tech Lead)  
**Date:** 2026-06-26  
**Changeset Author:** Kanté  
**Status:** APPROVE WITH REQUIRED CHANGES

---

## Decisions

### Decision 1 — Catch-Up Misinformation: OPTION (a) — Neutral Summary

**Requirement:** Replace the N individual fabricated goal messages with ONE neutral catch-up notification per match. No per-goal attribution, no intermediate scorelines, no scorer claims.

**Specification:** New formatter function — \ormat_catchup_message()\ in \eddit/notifier.py\:

\\\
⚠️ Me perdí {n} gol(es)
🇪🇨 Ecuador 1-1 Germany 🇩🇪
\\\

**Behaviour changes:**
1. Both \__main__.py\ first-seen branch and \score_state.py\ restart-ahead branch emit \kind="catchup"\ instead of N fabricated per-goal deltas.
2. \_process_goal_delta\: Handle \kind="catchup"\ by calling \_notify_catchup()\ instead of \_notify_goal()\.
3. Clip store for catch-up: Register ONE entry with token \{match_id}:catchup:{H}-{A}\. 

### Decision 2 — Race Fix Robustness: ADEQUATE + ONE HARDENING

**Required hardening:** In \_backfill_scorer_in_clip_store\ (line 353), change the \eply_markup\ handling to NEVER explicitly clear an existing keyboard. Instead of \eply_markup=None\, omit the key entirely when status ≠ "ready" to ensure Telegram preserves existing markup.

### Decision 3 — Delete-After-Send: APPROVED

The ordering is correct: send → file_id → persist → unlink. Safety properties confirmed.

---

## VERDICT: APPROVE WITH REQUIRED CHANGES

Ship Fix B1 (race reorder), Fix D (delete-after-send), and Fix A2 (reconcile restart detection logic) as-is.

**Required changes for Kanté:**
1. Replace catch-up goal fabrication with neutral summary message per Decision 1.
2. Harden \_backfill_scorer_in_clip_store\ to OMIT \eply_markup\ when status ≠ "ready".

---

# Gate Verdict — Live Goal Bug Fix (Kanté, 2026-06-26)

**Author:** Buffon (Tester / QA)  
**Date:** 2026-06-26  
**Reviewed:** Kanté's fixes for missed goals (A1/A2), keyboard race (B1), delete-after-send (D)  
**Final pytest count: 1570 passed** (was 1568 after Kanté; +2 added by Buffon)

---

## Step 1 — Suite Verification

Ran \.venv\Scripts\python.exe -m pytest -q\ independently.  
**Result: 1568 passed, 5 warnings in 88.74s** — matches Kanté's claim. ✅

---

## Step 2 — New Test Quality Audit

All 17 new tests are **real and non-tautological**. Each test would fail without its corresponding fix.

---

## Step 3 — Delete-After-Send Edge Case Analysis

Critical ordering verified: \ntry["file_id"] = ...\ → \_cs_save_clips(...)\ → \Path(...).unlink(...)\ — all synchronous, no \wait\ between them. No asyncio interleave window between save and delete. ✅

---

## Step 4 — Catch-Up Emit Edge Cases

All hazards covered by existing tests.  Double-announce analysis confirmed no race possible due to \goal_lock\.

---

## ⚠️ Documented Design Limitation

**Subject:** Token collision in \econcile()\ restart catch-up for 2+ same-team goals missed.

**Recommendation for Kanté:** Change the reconcile restart catch-up to emit deltas with incremental scores (similar to the \__main__.py\ catch-up logic).

**Regression guard added:** \	est_restart_catchup_deltas_carry_final_score\ in \	est_score_state.py\ documents this behavior.

---

## Tests Added by Buffon (+2)

1. **\	est_stale_file_id_with_deleted_file_sends_error_message\** (\	est_handlers.py\)  
2. **\	est_restart_catchup_deltas_carry_final_score\** (\	est_score_state.py\)

---

## VERDICT

**PASS WITH ADDED TESTS** — All 3 fixes verified, all 17 new tests are real, critical ordering hazard explicitly tested.

**Final pytest count: 1570 passed, 5 warnings**

