# Archived Decisions (older than 7 days from 2026-07-08)

**Archived:** 2026-06-30 entries

---

# Decision: Picante Prompt Refinement (2026-06-30 SHIPPED)

**Date:** 2026-06-30
**Author:** Kanté (Backend Developer)
**Status:** ✅ SHIPPED (commit d964fbf)

---

## Summary

Refined the picante prompt and uild_picante_user_message function to reply exclusively to the LAST (triggering) message, use recent context only when clearly related, and mirror the language of the last message (Catalan→Catalan, else Castilian). Updated tests; suite 1939 green.

---

## Problem

Picante was passing ALL buffered messages as a flat list to the AI. The model force-wove unrelated topics and people into replies, producing incoherent outputs.

---

## Changes

### New _SYSTEM prompt

Eres el asistente gamberro del grupo de Telegram de una porra del Mundial 2026 entre amigos.
MISIÓN: Suelta UN comentario pícaro e ingenioso dirigido EXCLUSIVAMENTE al ÚLTIMO MENSAJE.
REGLA DE CONTEXTO: El bloque 'CONTEXTO RECIENTE' es solo de apoyo. Úsalo ÚNICAMENTE si está claramente relacionado con el ÚLTIMO MENSAJE.
IDIOMA: Responde SIEMPRE en el mismo idioma del ÚLTIMO MENSAJE. Si el último mensaje está en catalán → responde en catalán.
TONO: Banter amigable con picardía — con chispa, pero nunca cruel.
FORMATO: 1-2 frases cortas, directas. Sin saludos ni presentaciones.

### Modified uild_picante_user_message(messages)

- messages[-1] is always the triggering message
- messages[:-1] is prior context (only included if present)
- Sections separated by double newline
- Empty case: "(sin contexto)"

### Tests Updated

All three tests in TestPicanteUserMessage pass:
- 	est_last_message_is_trigger_prior_in_context ✅
- 	est_empty_returns_placeholder ✅
- 	est_single_message_no_context_block_username_fallback ✅

---

# Decision: ChatState Eager Persistence — Startup + Live Sync (2026-06-30 MERGED)

**Date:** 2026-06-30  
**Authors:** Kanté (Backend Implementation), Pirlo (Lead Review)  
**Status:** ✅ APPROVED

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the chatstate eager persistence feature:
1. `kante-chatstate-eager-persist.md` — Implementation details
2. `pirlo-chatstate-eager-persist-review.md` — Lead review (APPROVED)

---

## Summary

Two-point change to persist `chat_state.json` from startup and after every qualifying group message, ensuring `last_seen` timestamps survive bot restarts independently of picante/revive feature activity.

1. **Startup save** — In `build_app()`, immediately after seeding `chat_state.last_seen` for all porra participants, call `save_chat_state(chat_state_path, chat_state)`. File exists from minute 0 with all known participants.

2. **Per-message save** — In `on_group_text` step 7 (after `state.last_seen[username] = now_utc.isoformat()`), call `save_chat_state(state_path, state)` if path is truthy. Runs on every qualifying message, independent of picante enabled.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/__main__.py` | Import `save_chat_state`; call it after seeding loop in `build_app()` |
| `src/worldcup_bot/chat/listener.py` | Import `save_chat_state`; call it in step 7 of `on_group_text` |
| `tests/test_chat.py` | `TestChatStateEagerPersist` (3 new tests using `tmp_path`) |

---

## Design Decisions

- **Best-effort, never raises** — `save_chat_state` wraps everything in `except Exception → log.warning`. Disk failure logs warning, continues.
- **Guard: `if state_path:`** — Uses `.get()` on `bot_data` (safe if key absent in tests) and truthiness check (empty-string path is falsy). Existing tests with `chat_state_path: ""` → no save, no warning.
- **Scope: step 7 only, before picante (step 8)** — Save runs even in revive-only mode so `last_seen` is always up-to-date on disk.
- **Per-message atomic write acceptable** — Low-volume private group; `save_chat_state` atomic temp-file-replace pattern ensures no torn writes.

---

## Test Coverage

### `TestChatStateEagerPersist` (3 tests in `tests/test_chat.py`)

**`test_qualifying_message_writes_state_file(tmp_path)`**
- Sends qualifying message through `on_group_text` with real `tmp_path` state file.
- Asserts file exists and `load_chat_state` finds sender in `last_seen`.

**`test_missing_state_path_key_does_not_raise(tmp_path)`**
- Removes `chat_state_path` from `bot_data` entirely.
- Calls `on_group_text` — must not raise.
- Asserts `last_seen` updated in-memory.

**`test_startup_save_writes_seeded_participants(tmp_path)`**
- Directly calls `save_chat_state` with seeded state (simulating startup).
- Asserts `load_chat_state` returns both participants.

---

## Pirlo Lead Review (2026-06-30 APPROVED)

✅ **Verdict: APPROVE** — Minimal, correct, well-guarded change. All checklist items pass.

**Checklist results:**
- ✅ Startup save placement (after seeding loop in `build_app()`, line 1784)
- ✅ Per-message save placement (step 7 of `on_group_text`, before picante step 8)
- ✅ Resilience (wrapped in try/except, logs warning on failure)
- ✅ Privacy unchanged (still only metadata, zero message text on disk)
- ✅ Performance (one atomic write per qualifying message, negligible for low-volume group)
- ✅ Suite green (1939 passed, 5 warnings)

---

# Decision: Revive Feature Enhancement — Quiet Hours + Jitter Self-Rescheduling (2026-06-30 MERGED)

**Date:** 2026-06-30  
**Authors:** Kanté (Backend Implementation), Maldini (DevOps), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 31f1a89)

---

## MERGED DECISIONS (3 files → 1 entry)

This entry consolidates the revive feature enhancement follow-up:
1. `kante-revive-quiet-jitter.md` — Backend implementation details
2. `maldini-revive-quiet-jitter.md` — DevOps/environment configuration
3. `pirlo-revive-quiet-jitter-review.md` — Lead review (APPROVED)

---

## Summary

Two behavioral enhancements to the **Revive** chat feature (quiet hours + jitter scheduling):

1. **Quiet Hours** — `revive_inactive_job` never sends mentions between `REVIVE_QUIET_START_HOUR:00` and `REVIVE_QUIET_END_HOUR:00` local time (respecting bot `TIMEZONE`). Default: 23:00–06:00 (7-hour nightly window).

2. **Self-Rescheduling with Jitter** — Replaced fixed `run_repeating(interval=4h)` with adaptive `run_once` loop where each next interval = base ± randomized jitter (clamped ≥60s). If computed target lands in quiet window, pushed to `quiet_end:00 + rand(0, jitter)` to cluster runs just after quiet ends, preventing thundering herd.

**Scope:** Revive only. Picante remains untouched.

---

## New Configuration

### Environment Variables (3 new)

| Var | Settings Field | Type | Default | Purpose |
|-----|----------------|------|---------|---------|
| `REVIVE_QUIET_START_HOUR` | `revive_quiet_start_hour` | int | `23` | Hour (0-23) local time, inclusive start of quiet window |
| `REVIVE_QUIET_END_HOUR` | `revive_quiet_end_hour` | int | `6` | Hour (0-23) local time, exclusive end (wake hour) |
| `REVIVE_JITTER_SECONDS` | `revive_jitter_seconds` | int | `2700` | ±45 min; applied symmetrically to base interval + as spread post quiet_end |

**Wiring:** `.env.example`, `docker-compose.yml`, `docker-compose.local.yml` (Maldini)

---

## Implementation Details

### New Functions in `src/worldcup_bot/chat/revive.py`

#### `is_quiet_hours(hour: int, quiet_start: int, quiet_end: int) -> bool`

Returns `True` when hour (0-23) falls inside configured quiet window.

**Rules:**
- `quiet_start == quiet_end` → no window, always False
- `quiet_start > quiet_end` (midnight wrap, e.g. 23→06): `hour >= quiet_start OR hour < quiet_end`
- `quiet_start < quiet_end` (same-day, e.g. 01→06): `quiet_start <= hour < quiet_end`

#### `next_revive_delay(base_seconds, jitter_seconds, now_local, quiet_start, quiet_end, rand=random.uniform) -> float`

Returns seconds (float) until next revive run, with quiet-hours awareness.

**Algorithm:**
1. `delay = base_seconds + rand(-jitter_seconds, +jitter_seconds)` (clamped to ≥60s)
2. `target = now_local + timedelta(seconds=delay)`
3. If target falls in quiet hours:
   - `wake = target.replace(hour=quiet_end, minute=0, second=0, microsecond=0)`
   - If `wake <= target`: add 1 day (push to next day)
   - Add `rand(0, jitter_seconds)` to spread (avoid pile-ups)
   - `delay = (wake - now_local).total_seconds()`
4. Return delay

**Key:** `rand` is injectable for deterministic testing. Pass `lambda a, b: 0.0` for fixed values.

#### `schedule_next_revive(job_queue, settings: Settings) -> None`

Schedules exactly one `run_once` job for the next revive run.

- Computes `now_local = datetime.now(pytz.timezone(settings.timezone))`
- Calls `next_revive_delay(...)` with all settings
- Calls `job_queue.run_once(revive_inactive_job, when=delay, name="revive_inactive")`

### `revive_inactive_job` Changes

**Quiet-hours guard** (inside try, before AI/Telegram work):
```python
now_local = datetime.now(pytz.timezone(settings.timezone))
if is_quiet_hours(now_local.hour, settings.revive_quiet_start_hour, settings.revive_quiet_end_hour):
    log.info("revive_inactive_job: quiet hours (%02d:00) — skipping mention", now_local.hour)
    return   # still rescheduled via finally
```

**Self-rescheduling `finally` block:**
```python
settings: Settings | None = None
try:
    settings = context.bot_data["settings"]
    ...
finally:
    if settings is not None and revive_enabled(settings):
        schedule_next_revive(context.job_queue, settings)
```

- Rescheduling happens on EVERY exit: success, quiet-skip, no-candidates, AIError, unexpected Exception
- When revive_enabled is False, finally guard prevents scheduling (no orphan jobs)

### `__main__.py` Changes

**Initial scheduling** (replaces `run_repeating`):
```python
if revive_enabled(settings):
    schedule_next_revive(app.job_queue, settings)
    log.info(
        "Revive inactive users ENABLED — base %ds ±%ds, quiet %02d:00–%02d:00 %s, group %s",
        settings.revive_check_interval_seconds,
        settings.revive_jitter_seconds,
        settings.revive_quiet_start_hour,
        settings.revive_quiet_end_hour,
        settings.timezone,
        settings.telegram_group_id,
    )
```

First run is also randomized + quiet-aware.

---

## Test Coverage

**New tests in `tests/test_revive_schedule.py`:** 53 tests added

- `is_quiet_hours` — all boundary conditions (wrap, same-day, no-window)
- `next_revive_delay` — jitter range, clamp, quiet-push, rand injection
- `schedule_next_revive` — mock job_queue, verify run_once call args
- `revive_inactive_job` — quiet-hours skip, self-reschedule via finally, settings-is-None path
- Regression: all existing revive tests pass with new finally block

**Result:** Full test suite: 1936 passed, 0 failed

---

## Design Rationale

1. **Quiet window:** Suppresses nightly mentions (default 23:00–06:00 local) for better UX. Respects bot timezone + DST.

2. **Randomized jitter:** Base interval 14400s (4h) ± 2700s (45m) = actual 11700s–17100s (3.25h–4.75h). Prevents thundering herd if bot is ever scaled or multiple instances deployed.

3. **Self-rescheduling loop:** Single `run_once` per execution, replacing old `run_repeating`. Exactly 1 pending "revive_inactive" job at any time. Robust exit handling: quiet-skip, no-candidates, AIError, Exception all reschedule safely.

4. **Spread after quiet_end:** Not exact boundary (prevents pile-ups during multi-instance deployments).

---

## Verification (Pirlo Review)

✅ **Checklist Results:**
- is_quiet_hours midnight wrap logic: correct
- next_revive_delay correctness: next run never in quiet hours
- Self-reschedule robustness: all exit paths handled
- JobQueue hygiene: at most 1 pending job at any time
- Initial schedule in __main__: first run randomized + quiet-aware
- Picante untouched: no changes to other features
- David's spec fidelity: quiet 23-06, jitter ±45m, base 4h
- Test suite: 1883 passed, 5 warnings (all new smoke tests pass)

**Verdict:** ✅ APPROVE — Ship it.

---

# Decision: LLM Chat Features Ship — Picante + Revive (2026-06-30 MERGED)

**Date:** 2026-06-30  
**Authors:** Pirlo (Design), Kanté (Implementation), Maldini (DevOps), Buffon (Testing)  
**Status:** ✅ SHIPPED  

---

## MERGED DECISIONS (4 files → 1 entry)

This entry consolidates the complete chat-features feature ship:
1. `pirlo-llm-chat-features.md` — Design spec + open decisions  
2. `kante-chat-features-impl.md` — Implementation details  
3. `pirlo-chat-features-review.md` — Lead review (APPROVED)  
4. `maldini-chat-features-ops.md` — DevOps/infrastructure  

---

## Overview

Two new LLM-driven group-chat features shipped in `src/worldcup_bot/chat/` package:
- **Picante**: Random spicy replies to group messages (~1-in-5 probability, 5-min cooldown, 30/day cap)
- **Revive**: Periodic @mentions of inactive users (4h check interval, 3-day threshold, 2-day mention cooldown)

Both features:
- **Disabled by default** (`CHAT_PICANTE_ENABLED=0`, `CHAT_REVIVE_ENABLED=0`)
- Share in-memory ring buffer (30 messages), JSON-persisted state (last_seen/last_mentioned only, no message text on disk)
- Reuse existing AIClient + OPENAI_* config (no new API key required)
- Require **BotFather privacy mode to be DISABLED** (blocking pre-deployment step — documented in README)

---

## Architecture

```
src/worldcup_bot/chat/  (NEW package)
├── __init__.py
├── buffer.py          # RingBuffer class (in-memory, N messages)
├── state.py           # ChatState dataclass + load/save (last_seen, last_mentioned, cooldowns)
├── listener.py        # MessageHandler + filtering + buffer recording
├── picante.py         # Probability gate, cooldown, prompt build, reply
└── revive.py          # Candidate selection, rotation, prompt build, send
```

**Existing files touched:**
- `src/worldcup_bot/config.py` — 12 new Settings fields
- `src/worldcup_bot/__main__.py` — MessageHandler registration, chat_state + chat_buffer seeding, revive job scheduling
- `README.md` — Privacy mode section (Maldini)
- `.env.example`, `docker-compose.yml`, `docker-compose.local.yml` — 12 env vars (Maldini)

---

## Locked Parameters (David approved 2026-06-30)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Picante probability | 0.20 | 1-in-5 eligible messages |
| Picante cooldown | 300s | 5 min minimum between replies |
| Picante daily cap | 30 | Hard cap per day |
| Buffer size | 30 | Recent messages kept in RAM |
| Min buffer | 5 | Don't fire until buffer has ≥5 |
| Inactive threshold | 3 days | Days silent = considered inactive |
| Revive check interval | 14400s | Every 4 hours |
| Mention cooldown | 2 days | Don't re-mention same user within 2 days |
| Picante temperature | 0.9 | LLM temperature for spicy replies |
| Revive temperature | 0.8 | LLM temperature for revive messages |
| Candidate set | PORRA PARTICIPANTS ONLY | (override of Pirlo's "anyone who spoke") |
| Language | ES + CAT | Spanish primary, Catalan when natural |

---

## Environment Variables (Maldini wired across all surfaces)

12 new env vars in `.env.example`, `docker-compose.yml`, `docker-compose.local.yml`:

```
CHAT_PICANTE_ENABLED=0
CHAT_REVIVE_ENABLED=0
CHAT_BUFFER_SIZE=30
PICANTE_PROBABILITY=0.20
PICANTE_COOLDOWN_SECONDS=300
PICANTE_MAX_PER_DAY=30
PICANTE_MIN_BUFFER=5
PICANTE_TEMPERATURE=0.9
REVIVE_CHECK_INTERVAL_SECONDS=14400
REVIVE_INACTIVE_DAYS=3
REVIVE_MENTION_COOLDOWN_DAYS=2
REVIVE_TEMPERATURE=0.8
```

---

## Privacy & Data Design

- **Message text**: In-memory only (lost on restart; buffer refills in minutes)
- **Persisted to disk** (JSON): only `last_seen`, `last_mentioned`, `picante_daily_count`, `picante_last_date`, `rotate_index` — ZERO message text on disk
- **GDPR compliant**: No message history disk footprint
- **Picante prompt guardrails**: "Prohibido: insultos reales, contenido sexual, información personal sensible, discursos de odio" (no real insults, no sexual content, no personal info, no hate speech)
- **Revive prompt guardrails**: "Tono: cálido, con gracia, sin agresividad" (warm, graceful, non-aggressive)

---

## Testing

**1768 tests total** (baseline 1730 + 38 new tests added by Buffon for edge cases):
- `tests/test_chat_edge_cases.py` — 107 edge-case tests covering all gates, fallbacks, concurrency, and PORRA-only filtering
- All tests green, 0 bugs found

---

## Deployment Checklist (Maldini)

**BLOCKING PRE-STEP** (must be done before deployment):

1. In BotFather: `/setprivacy` → **DISABLE** (bot needs to receive ALL group messages, not just /commands + replies)
2. **Remove bot from group and re-add** — privacy mode setting only applies to new memberships
3. Deploy bot (environment vars default to disabled)
4. To enable: set `CHAT_PICANTE_ENABLED=1` and/or `CHAT_REVIVE_ENABLED=1` when ready

---

## Pirlo Lead Review (2026-06-30 APPROVED)

✅ **Verdict: APPROVE** — Implementation is correct, well-structured, faithfully follows spec.

**Checklist results:**
- ✅ Filtering completeness (all media types rejected, commands rejected, text length checked)
- ✅ Rate limiting correctness (probability gate, cooldown via Unix time, daily cap with timezone-aware reset)
- ✅ Privacy (ZERO message text on disk)
- ✅ Candidate set = PORRA ONLY (sourced from predictions.yml participant keys)
- ✅ Concurrency (handlers sequential, state fields non-overlapping, no data loss possible)
- ✅ Resilience (both orchestrators wrapped in try/except, AI errors logged and swallowed)
- ✅ Disabled = zero overhead (handler only registered if feature enabled, job only scheduled if enabled)
- ✅ Guardrails (clear prohibitions on insults, sexual content, personal info, hate speech)
- ✅ Mention construction (plain text @username, Telegram resolves natively)
- ✅ Fidelity to locked params (all 10 params verified 1:1)

---

## Optional Nits (non-blocking, shipped as-is)

1. Could add explicit `parse_mode=None` to picante reply (defensive coding, low risk)
2. Inline import in listener.py:101 to avoid circular dep (acceptable)
3. Buffer allocated unconditionally even when both features disabled (negligible cost)

---

## Buffon QA Gate (107 edge-case tests, all green, 0 bugs)

**1875 tests total passed** (1768 baseline + 107 new edge-case tests).

Edge cases covered:
- All rate-limit gates (probability, cooldown, daily cap, min buffer)
- PORRA participant filtering (candidate set correctness)
- Timezone-aware daily reset
- Message filtering (media rejection, command rejection, length check)
- Inactive calculation (3-day threshold, mention cooldown)
- Rotation logic (round-robin, wrap-around)
- AI error resilience
- Concurrency scenarios

---

## Delivery Artifacts

**Code:**
- ✅ `src/worldcup_bot/chat/` package (5 modules: buffer, state, listener, picante, revive)
- ✅ `src/worldcup_bot/config.py` — 12 new Settings fields
- ✅ `src/worldcup_bot/__main__.py` — handler registration, state seeding, job scheduling

**Configuration:**
- ✅ `README.md` — Privacy mode section + setup instructions
- ✅ `.env.example` — 12 new env vars with defaults
- ✅ `docker-compose.yml` — 12 env vars wired
- ✅ `docker-compose.local.yml` — 12 env vars wired

**Tests:**
- ✅ `tests/test_chat_edge_cases.py` — 107 comprehensive edge-case tests
- ✅ All 1875 tests passing

---

## Known Limitations (Deferred to v2)

- Opt-out per user (`/norevive` command) — deferred to v2
- No disciplinary/drawing-of-lots for mention candidate ties — uses deterministic rotation as fallback
- No explicit Markdown safety on generated messages (LLM system prompt provides guardrails instead)

---# Decision: "Ver gol" Button Missing — Clip-Pipeline Fix (2026-07-02 SHIPPED)

**Date:** 2026-07-02  
**Authors:** Kanté (Backend Implementation), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 522ba6d)

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the "Ver gol" button clip-search fix:
1. kante-vergol-button-fix.md — Root cause analysis and implementation
2. pirlo-vergol-button-review.md — Lead review (APPROVED)

---

## Summary

Two goals lacked the "Ver gol" clip button in the live match thread; reproduced ind_goal_clip LIVE for both:

**(A) Belgium 3-2 Senegal — Tielemans 120+5' ET penalty**
- Root cause: Search timeout (18.75 min window vs. 20–30 min for ET clip posting)
- Fix: _MAX_CLIP_ATTEMPTS 25 → 40 (~30 min window)

**(B) USA 1-0 Bosnia-Herzegovina — Balogun 45'**
- Root cause: Reddit search miss ("United States" query doesn't match "USA" posts) + timeout
- Fix: Added search-term normalization (_TEAM_SEARCH_SHORT + _search_term() for "usa" alias and hyphen stripping); applied to both JSON and HTML search paths; post-fetch matching unchanged

---

## Root Cause per Goal

### Goal A — Timeout (ET / match-ending penalty)

_MAX_CLIP_ATTEMPTS = 25 × 45 s = ~18.75 min window.

The Tielemans goal was scored at 120+5'—literally the last playable moment. After an ET penalty that clinches the match, the clip poster typically watches the final whistle + celebrations before clipping and posting. This takes 20–30 min, exceeding the 18.75 min window.

### Goal B — Search Miss + Timeout (first-half stoppage goal)

Two compounding issues:
1. **Search miss:** _fetch_html_search_posts built query from raw football-data names: "United States Bosnia-Herzegovina". Reddit's index does NOT match "USA" for "United States". The clip title uses USA [1] - 0 Bosnia & Herzegovina—"United States" appears nowhere. Result: 25 HTML search results contained no goal clips.
2. **Timeout:** A 45' goal clip posted during/after half-time may appear >18.75 min after detection.

---

## Fixes

### 1. Extend clip search window — __main__.py

\\\
_MAX_CLIP_ATTEMPTS: 25 → 40   (~18.75 min → ~30 min)
\\\

Rationale: "clips rarely appear >30–40 min after" (David's constraint). 40 attempts × 45 s = 30 min covers ET goals, halftime goals, and late-posted clips. Well within sane bounds.

### 2. Search-query normalisation — clip_finder.py

Added:
\\\python
_TEAM_SEARCH_SHORT: dict[str, str] = {"united states": "usa"}

def _search_term(team: str) -> str:
    norm = _normalize_team(team)          # WC alias applied, lowercased
    short = _TEAM_SEARCH_SHORT.get(norm, team)
    return short.replace("-", " ")        # strips hyphens for broader Reddit search
\\\

Applied in:
- _fetch_html_search_posts: query now \"{_search_term(home)} {_search_term(away)}"\
- ind_goal_clip JSON path: same query construction

Effect on Goal B:
- \_search_term("United States")\ → \"usa"\ (via alias)
- \_search_term("Bosnia-Herzegovina")\ → \"Bosnia Herzegovina"\ (hyphen stripped)
- Search query: \"usa+Bosnia+Herzegovina"\ → finds \USA [1] - 0 Bosnia & Herzegovina\ ✓

---

## Invariants Preserved

- \_match_post\ is unchanged — all matching logic (exact score, fuzzy teams, scorer/minute) is unaffected.
- \_teams_match\ is unchanged — post-fetch title matching works as before.
- Dedup in merged /new + HTML search posts is unchanged.
- Goal A's \120+5'\ regex already worked.
- No changes to \poll_goal_clips_job\, \_cs_add_entry\, or clip store — only search window and query strings.

---

## Tests Added (13 new → 2134 total)

All tests pass ✅. Coverage includes:
- ET penalty regex parsing (\120+5'\ → minute 120)
- Full \_match_post\ for both goals with actual titles
- Search-term alias ("United States" → "usa")
- Hyphen stripping ("Bosnia-Herzegovina" → "Bosnia Herzegovina")
- End-to-end search URL normalization
- Regression: non-aliased teams unaffected

---

## Review: APPROVED ✅

**Reviewer:** Pirlo (Lead)

Surgical, safe changes:
1. \_search_term\ only affects Reddit search QUERY (both paths); never post-matching logic.
2. USA alias narrowly scoped to one entry in \_TEAM_SEARCH_SHORT\.
3. Timeout bump (25→40) is bounded and reasonable (30 min < sane upper bound).
4. Post-fetch matching uses original team names via \_teams_match\ fuzzy logic — no regression.
5. Best-effort / non-fatal behavior preserved.
6. **2134 tests pass, 0 failures.**

---

## Files Changed

| File | Change |
|------|--------|
| \src/worldcup_bot/reddit/clip_finder.py\ | Added \_TEAM_SEARCH_SHORT\, \_search_term()\; patched \_fetch_html_search_posts\ + \ind_goal_clip\ |
| \src/worldcup_bot/__main__.py\ | \_MAX_CLIP_ATTEMPTS\ 25 → 40 |
| \	ests/test_clip_finder.py\ | 13 new tests (2134 total) |
| \.squad/agents/kante/history.md\ | Session entry added |

---


---



# Decision: Schedule-Live Decoupling — Live Match / Goal Notification Bug Fix (2026-07-01 SHIPPED)

**Date:** 2026-07-01
**Authors:** Kanté (Backend Implementation), Pirlo (Lead Review)
**Status:** ✅ SHIPPED (commit b2e9a71)

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the schedule-live seeding fix:
1. kante-live-seeding-fix.md — Implementation details
2. pirlo-live-seeding-review.md — Lead review (APPROVED)

---



# Decision: Schedule-Live Decoupling — Live Match / Goal Notification Bug Fix

**Author:** Kanté  
**Date:** 2026-07-01  
**Status:** Implemented, awaiting commit

---

## Root Cause

football-data.org free tier updates live match status/scores with a **~1 h delay**. During that window a match that is already playing is still reported as `TIMED`. The entire goal pipeline was gated behind `IN_PLAY/PAUSED`:

- `get_live_matches()` → `[m for m in ... if m.status in ("IN_PLAY","PAUSED")]`
- `poll_goals_job` `relevant` filter → only `IN_PLAY/PAUSED` or `FINISHED+in scores`
- `poll_thread_goals_job` calls `get_live_matches()` and only processes seeded matches

Net effect: during the ~1 h API lag, nothing seeds `live_scores`, the Reddit real-time poller never looks at the thread, and `/endirecto` returns "No hay partidos en directo". Goals are announced ~1 h late when the API finally catches up.

---

## The Fix

### 1. Schedule-Live Predicate

New function `match_is_schedule_live(match: Match, now_utc: datetime) -> bool` added to **`api/client.py`** (module-level, importable with no circular-import risk).

Returns `True` when **all** of:
- `match.status` not in `_TERMINAL_STATUSES = {"FINISHED","POSTPONED","SUSPENDED","CANCELLED","AWARDED"}`
- `kickoff <= now_utc` (match has started per schedule)
- `now_utc - kickoff <= MATCH_LIVE_WINDOW` (4 h — same ceiling as `MATCH_OVER_AGE` in `__main__.py`)

New constants also in `api/client.py`:
```python
MATCH_LIVE_WINDOW = timedelta(hours=4)
_TERMINAL_STATUSES = frozenset({"FINISHED", "POSTPONED", "SUSPENDED", "CANCELLED", "AWARDED"})
```

**Cross-reference:** `MATCH_LIVE_WINDOW` (4 h) must stay in sync with `MATCH_OVER_AGE` (4 h) in `__main__.py`. Both define the same ceiling for "could still be live".

### 2. `get_live_matches()` Fix (`api/client.py`)

```python
def get_live_matches(self) -> list[Match]:
    matches = self.get_all_matches()
    now_utc = datetime.now(timezone.utc)
    return [
        m for m in matches
        if m.status in ("IN_PLAY", "PAUSED") or match_is_schedule_live(m, now_utc)
    ]
```

Fixes `/endirecto` (cmd_en_directo) and the standings live-highlight (cmd_clasificacion) with no changes to handlers.

### 3. `poll_goals_job` Relevant Filter (`__main__.py`)

Added `or match_is_schedule_live(m, now_utc)` to the `relevant` filter:

```python
relevant = [
    m for m in all_matches
    if not _match_is_over(m, now_utc)
    and not m.in_penalty_shootout
    and (
        m.status in ("IN_PLAY", "PAUSED")
        or (m.status == "FINISHED" and str(m.id) in scores)
        or match_is_schedule_live(m, now_utc)   # NEW: catches API-lagged TIMED
    )
]
```

**Seeding TIMED at 0-0:** When a TIMED match has null API scores (`home_score=None`, `away_score=None`):
- `curr_home = curr_away = 0`
- `reconcile(None, None, 0, 0)` → `([], {"home":0,"away":0}, {"home":0,"away":0})`
- `stored is None` → enters seeding branch
- `curr_home > 0 or curr_away > 0` → `False` → **no catch-up delta, no announce**
- Seeds `live_scores[match_key] = {"home":0,"away":0,"status":"TIMED"}` ✓

**Invariants preserved:**
- `goal_lock` atomic claim: unchanged
- `reconcile()`/per-source `seen` dedup: unchanged
- No-double-announce guarantee: seed is at 0-0; subsequent delta uses same reconcile path
- Disallowed/VAR handling: unchanged (only triggered when same source's own value drops)
- POSTPONED/SUSPENDED eviction: executed before `relevant` filter, evicts even newly-seeded TIMED entries
- Over-match (4h) prune: still runs first; TIMED match >4h is evicted AND not schedule-live

### 4. Reddit Thread Matching (`reddit/scanner.py`)

**Findings:** `WC_TEAM_ALIASES` already handled the key Congo DR variants:
- `"dr congo"` → `"congo dr"` ✓
- `"d r congo"` → `"congo dr"` (D.R.Congo after dot→space) ✓
- `"democratic republic of congo"` → `"congo dr"` ✓
- `"dem rep congo"` → `"congo dr"` ✓

**Gap found:** `"democratic republic of the congo"` (official UN name, includes "the") was missing.

**Fix:** Added one alias:
```python
"democratic republic of the congo": "congo dr",  # official UN name variant
```

The `_normalize_team` / `_teams_match` / `_find_matching_fixture` / `scan_live_matches` pipeline was already robust. No structural changes needed.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/api/client.py` | Added `MATCH_LIVE_WINDOW`, `_TERMINAL_STATUSES`, `match_is_schedule_live()`; updated `get_live_matches()` |
| `src/worldcup_bot/__main__.py` | Imported `match_is_schedule_live`; extended `relevant` filter in `poll_goals_job` |
| `src/worldcup_bot/reddit/scanner.py` | Added `"democratic republic of the congo"` alias |
| `tests/test_api_client.py` | Added `TestScheduleLivePredicate` (13 tests) + `TestGetLiveMatchesScheduleLive` (5 tests) |
| `tests/test_poll_goals_job.py` | Added `TestScheduleLiveSeeding` (4 tests); fixed `test_no_relevant_matches_returns_early` (future kickoff) |
| `tests/test_poll_thread_goals_job.py` | Added `TestPollThreadGoalsJobScheduleLive` (2 tests) |
| `tests/test_handlers.py` | Added `TestCmdEnDirectoScheduleLive` (2 tests) |
| `tests/test_reddit_scanner.py` | Added `TestCongoDRAlias` (6 tests) |

**Full suite: 2102 passed, 0 failures.**


---

## Lead Review — Pirlo (APPROVED)

# Review: Schedule-Live Seeding Fix (Goal Pipeline)

**Reviewer:** Pirlo (Lead)  
**Date:** 2026-07-01  
**Scope:** `api/client.py` (new predicate + get_live_matches), `__main__.py` (relevant filter), `reddit/scanner.py` (alias)  
**Test suite:** 2102 passed ✅  

---

## Checklist

### 1. No Double Announce ✅ PASS

Traced both orderings through `reconcile()` + `goal_lock`:

**Thread-first-then-API-catchup (primary real-world path):**

1. `poll_goals_job` seeds match at 0-0 (API scores are None → 0):  
   `reconcile(None, None, 0, 0)` → `([], {0,0}, {0,0})` — seeds `scores[key]={0,0}`, no announce.  
   Sets `seen_api[key] = {0,0}`.

2. `poll_thread_goals_job` reads 0-1 from Reddit thread:  
   `reconcile(None, {0,0}, 0, 1)` — seen=None, announced≠None, `_ahead({0,1},{0,0})` → True → emits ONE catchup delta.  
   Claims `scores[key] = {0,1}` under `goal_lock`. Announces. ✓

3. `poll_goals_job` ~1h later, API now reports 0-1:  
   `reconcile({0,0}, {0,1}, 0, 1)` — new={0,1} != seen={0,0} → proceed.  
   `_ahead({0,1}, {0,1})` → False (equal, not strictly ahead).  
   Step 5: `([], {0,1}, {0,1})`. **No delta, no announce.** ✓

**API-first (rare — API catches up before thread):**

1. API reports 1-0: `reconcile({0,0}, {0,0}, 1, 0)` → `_ahead({1,0},{0,0})` → True → goal delta. Claims `scores[key]={1,0}`. Announces. ✓

2. Thread later reads 1-0: `reconcile(None, {1,0}, 1, 0)` — seen=None, `_ahead({1,0},{1,0})` → False → `([], {1,0}, {1,0})`. **No delta.** ✓

The `goal_lock` ensures the "read announced → reconcile → claim" is atomic between
both pollers. The per-source `seen` baselines prevent a lagging source from interpreting
the other source's already-announced delta as new.

### 2. No False Disallowed ✅ PASS

The disallowed path in `reconcile` (line 243–266) only fires when:
- `_ahead(ann, new)` (announced > new) — announced is strictly higher
- AND `_ahead(seen, new)` (source's own prior > new) — this source itself dropped

With a 0-0 seed baseline:
- Thread reads 0-1: `_ahead({0,0}, {0,1})` → False (ann not ahead of new) → disallowed branch NEVER entered.
- API reads 0-1 after thread claimed {0,1}: `_ahead({0,1}, {0,1})` → False → not entered.

The only way to trigger disallowed is if the SAME source's own `seen` was higher than
its current reading — which is genuine VAR/goal reversal. The 0-0 seed cannot produce
a false disallowed because any forward movement from 0-0 is strictly "ahead" by definition.

### 3. Window Consistency ✅ PASS — No Oscillation

| Elapsed | `match_is_schedule_live` | `_match_is_over` | Net status |
|---------|--------------------------|-------------------|-----------|
| < 4h    | True (`<=`)              | False (`>`)       | Live ✓    |
| = 4h    | True (`<=`)              | False (`>`)       | Live ✓    |
| > 4h    | False                    | True              | Evicted ✓ |

The operators are complementary: `<=` (schedule-live) and `>` (over). At the exact
boundary (4h), the match is still considered live. At 4h+ε it transitions to "over"
and is both evicted AND excluded from `relevant`. No gap, no overlap, no thrash.

Both constants are 4h: `MATCH_LIVE_WINDOW = timedelta(hours=4)` in `client.py` and
`MATCH_OVER_AGE = timedelta(hours=4)` in `__main__.py`. The comment on `MATCH_LIVE_WINDOW`
explicitly notes "Must match MATCH_OVER_AGE in __main__.py".

### 4. Over-Inclusion Prevention ✅ PASS

`match_is_schedule_live` returns False when:
- Status is FINISHED/POSTPONED/SUSPENDED/CANCELLED/AWARDED (checked first, line 48)
- Kickoff is in the future (`elapsed < 0`)
- Kickoff was >4h ago (`elapsed > MATCH_LIVE_WINDOW`)
- `utc_date` parsing fails (returns False on any Exception)

POSTPONED/SUSPENDED eviction (lines 794-808) runs BEFORE the `relevant` filter and
evicts seeded entries. A re-seeding is impossible because `match_is_schedule_live`
returns False for terminal statuses → the match is NOT in `relevant`.

Order of operations in `poll_goals_job`:
1. Over-match eviction (>4h)
2. POSTPONED/SUSPENDED eviction  
3. Build `relevant` list (won't include evicted or terminal matches)

No stale match can re-seed after eviction. ✓

### 5. Null Scores ✅ PASS

```python
curr_home = int(match.home_score) if match.home_score is not None else 0
curr_away = int(match.away_score) if match.away_score is not None else 0
```

None → 0 (no crash). Then `reconcile(None, None, 0, 0)` → seeds at 0-0, announces
nothing. Subsequent ticks with still-null scores: `reconcile({0,0}, {0,0}, 0, 0)` →
`new == seen` → no-op (step 2). Correct and safe.

### 6. No Regression ✅ PASS

- Normal IN_PLAY matches: still hit the `m.status in ("IN_PLAY", "PAUSED")` branch
  first — unchanged logic path.
- VAR/disallowed: reconcile logic untouched; disallowed tests still pass.
- FINISHED catch-up: `m.status == "FINISHED" and str(m.id) in scores` branch untouched.
- FT recap (`poll_finished_job`): uses its own `finished_announced` set — completely
  independent of this change.
- `get_live_matches()`: OR-expanded, not replaced. IN_PLAY/PAUSED matches are still
  included unconditionally.

Full suite: **2102 passed**, 5 warnings (pre-existing deprecation).

---

## Additional Notes

- The Congo alias addition (`"democratic republic of the congo": "congo dr"`) is a
  trivial dictionary entry with 6 passing tests. No risk.
- The `match_is_schedule_live` function is conservative by design: it returns False on
  any parsing error, uses a try/except, and is gated by terminal-status exclusion. It
  cannot widen the pipeline dangerously even with malformed API data.

---

## VERDICT: ✅ APPROVE

The fix is sound. The concurrency guarantees (no double announce, no false disallowed)
are preserved by the unchanged `reconcile` + `goal_lock` mechanism — the change only
widens WHICH matches enter the pipeline, not HOW goals are detected/claimed. The window
arithmetic is tight with no oscillation risk. 2102 tests pass. Ship it.


---



# Decision: Podium Drawn-Base Layout Rewrite (2026-07-01 SHIPPED)

**Date:** 2026-07-01  
**Authors:** Kanté (Backend), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 277ae2e)

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the podium layout rewrite:
1. \kante-podium-drawn-base.md\ — Drawn podium base implementation
2. \pirlo-podium-drawn-review.md\ — Lead review (APPROVED)

---

## Summary

Rewrote \src/worldcup_bot/bot/podium_image.py\ to render a drawn 3-block podium (gold/silver/bronze) with tie-aware heights, position numbers on block fronts, circular photos as "heads" standing on each block, and crown asset (or drawn fallback) worn on top. Canvas 760×560 px. All 2018 tests green; David visually verified rendered output.

---

## Layout Description

Each participant is rendered as a vertical stack from top to bottom:

1. **Crown** — asset (\crown.png\) or drawn fallback — sits on the photo head
2. **Circular photo** ("head") — rests on top of the block with a slight overlap
3. **Podium block** ("feet/pedestal") — anchored to the floor, height varies by rank

Classic left/center/right arrangement for n=3:
- **Center** = participants[0] (1st ranked) — tallest block
- **Left** = participants[1] (2nd ranked)
- **Right** = participants[2] (3rd ranked)

Column display order for n=3: \[1, 0, 2]\ (index into participants list).

---

## Module-Level Constants (all in \podium_image.py\, easy to tune)

\\\python
_CANVAS_W       = 760          # canvas total width (px)
_CANVAS_H       = 560          # canvas total height (px)
_BG             = (22, 27, 34) # background color (dark navy)

_FLOOR_Y        = 420          # y-coordinate of the floor (all blocks end here)
_BLOCK_W        = 200          # width of each podium block (px)
_BLOCK_GAP      = 8            # gap between blocks (px)
_BLOCK_HEIGHT   = {1: 175, 2: 120, 3: 85}  # height by tie-aware position
_BLOCK_COLORS   = {            # flat fill color by position
    1: (230, 184,   0),        # gold
    2: (192, 192, 192),        # silver
    3: (205, 127,  50),        # bronze
}
_BLOCK_TOP_DARKEN = 20         # how much to darken the top edge for depth

_PHOTO_D        = 150          # photo circle diameter (px)
_PHOTO_OVERLAP  = 10           # px the photo overlaps down into the block top

_CROWN_ASSET_SIZE = 105        # width to scale the crown asset to (px)
_CROWN_OVERLAP    = 30         # px the crown asset overlaps down into the photo top
_DRAWN_CROWN_W    = 70         # width of the drawn (fallback) crown (px)
_DRAWN_CROWN_H    = 40         # height of the drawn crown (px)
_DRAWN_CROWN_OVERLAP = 10      # px the drawn crown overlaps into the photo top

_FONT_SIZE_NUM  = 52           # font size for position number on block face
_FONT_SIZE_NAME = 18           # font size for participant name label (below block)
_NAME_Y_OFFSET  = 28           # px below block bottom for name label
\\\

---

## Tie-Height Mapping

Ties share the **same** block height (determined by \participant["position"]\):

| Positions | Block heights              |
|-----------|---------------------------|
| 1, 2, 3   | 175 / 120 / 85            |
| 1, 1, 3   | 175 / 175 / 85            |
| 1, 2, 2   | 175 / 120 / 120           |
| 1, 1, 1   | 175 / 175 / 175           |

The \position\ field comes from \standard_competition_positions()\ in \ormatters.py\, passed through \_send_ranking_with_top3_photos\ → \
ender_podium\.

---

## Crown Placement

- **Asset (\_CROWN_IMG\ is not None):** scale to \_CROWN_ASSET_SIZE\ wide (preserve aspect ratio), alpha-composite centered on the photo column, with the crown's bottom overlapping \_CROWN_OVERLAP\ px into the photo top.
- **Drawn fallback (\_CROWN_IMG is None\):** \_draw_crown(draw, cx, crown_top)\ draws a gold polygon crown of size \_DRAWN_CROWN_W × _DRAWN_CROWN_H\ above the photo, overlapping \_DRAWN_CROWN_OVERLAP\ px.
- The **position number** is drawn on the **block face**, not on the crown.

---

## Fallback Chain (unchanged)

\
ender_podium\ → \syncio.to_thread\ in \_send_ranking_with_top3_photos\:

1. **Podium image** (\
ender_podium\) → if \None\, falls back to:
2. **Album** (existing \send_media_group\ photo strip) → if that fails, falls back to:
3. **Plain text** (existing reply_text)

\
ender_podium\ **never raises** — wraps the entire \_render_podium\ call in \	ry/except\, returns \None\ on any error.

---

## Tests Changed

File: \	ests/test_podium_image.py\
- \	est_canvas_dimensions_720x400\ → renamed \	est_canvas_dimensions_760x560\, assertion updated from \(720, 400)\ to \(760, 560)\
- \	est_asset_crown_pastes_non_background_pixels\: parameter renamed \	ile_y=115\ → \photo_top_y=115\ to match new \_paste_crown_asset\ signature
- \TestCrownAsset::test_fallback_drawn_crown_when_asset_missing\: size assertion updated \(720, 400)\ → \(760, 560)\

All other tests remain unchanged; 2018 pass.

---

## Pirlo Lead Review (2026-07-01 APPROVED)

✅ **Verdict: APPROVE**

**Checklist results:**
- ✅ Never raises — full try/except around internal renderer, returns None on any failure
- ✅ Tie-awareness — block height, color, position number keyed by \p.get("position", ...)\
- ✅ Robustness — n=1 and n=2 handled; missing photo → placeholder; crown fallback works
- ✅ No dead code — 350-line module with 13 functions, all called
- ✅ Constants tunable — all layout magic numbers at module top as named constants
- ✅ Suite green + tests retargeted — 2018 passed, new dimensions correctly asserted

The rewrite is clean: 350-line module with no dead code, all correctness invariants preserved (never-raises, tie-aware, robust for edge cases), constants fully tunable, and tests correctly retargeted. David visually confirmed the output. Ship it.

---




# Decision: Crown Asset Integration (2026-07-01 SHIPPED)

**Date:** 2026-07-01  
**Authors:** Kanté (Backend), Maldini (DevOps), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit e53b8a5)

---

## MERGED DECISIONS (3 files → 1 entry)

This entry consolidates the crown asset integration:
1. `kante-crown-asset.md` — Asset loader implementation
2. `maldini-crown-packaging.md` — Packaging & attribution
3. `pirlo-crown-asset-review.md` — Lead review (APPROVED)

---

## Summary

Swapped hand-drawn gold crown for Noto Emoji crown asset (128×128 RGBA, Apache-2.0). Asset loader prefers bundled PNG; falls back to drawn crown if missing. Packaging fix ensures asset ships in wheel/Docker image.

---

## Asset Loader

```python
# src/worldcup_bot/bot/podium_image.py

from importlib.resources import files

def _load_crown_asset() -> Image.Image | None:
    try:
        resource = files("worldcup_bot") / "assets" / "crown.png"
        return Image.open(io.BytesIO(resource.read_bytes())).convert("RGBA")
    except Exception:
        return None

_CROWN_IMG: Image.Image | None = _load_crown_asset()
```

**Why `importlib.resources.files`?**  
Works identically from source checkout and pip-installed package in Docker, as long as `pyproject.toml` ships the PNG via `package-data`. PEP 451-compliant for Python 3.9+.

---

## Crown Rendering

```python
def _paste_crown_asset(canvas: Image.Image, cx: int, tile_y: int) -> None:
    crown = _CROWN_IMG.resize((_CROWN_ASSET_SIZE, _CROWN_ASSET_SIZE), Image.LANCZOS)
    x = cx - _CROWN_ASSET_SIZE // 2
    y = tile_y - _CROWN_GAP - _CROWN_ASSET_SIZE
    canvas.paste(crown, (x, y), crown)  # uses RGBA alpha channel as mask
```

- `_CROWN_ASSET_SIZE = 56` px
- Crown bottom edge = `tile_y - _CROWN_GAP` = 22 px above tile top
- Alpha-composite via RGBA mask

**Fallback dispatch in `_render_podium`:**

```python
if _CROWN_IMG is not None:
    _paste_crown_asset(canvas, cx, tile_y)
else:
    crown_top = tile_y - _CROWN_H - _CROWN_GAP
    _draw_crown(draw, cx, crown_top)
```

Original 11-vertex drawn crown remains as fallback.

---

## Packaging (Maldini)

**pyproject.toml changes:**

```toml
[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
worldcup_bot = ["assets/*.png", "assets/*.md"]
```

**Attribution:** `src/worldcup_bot/assets/ATTRIBUTION.md` created (Noto Emoji, Google, Apache 2.0)

**Verification:** Wheel built successfully; `worldcup_bot/assets/crown.png` confirmed present in wheel zip.

---

## Testing

- 5 new tests in `TestCrownAsset`: asset loaded; fallback with asset=None; fallback tie case; draw_crown and paste mutate canvas
- 12 smoke tests in `TestRenderPodiumSmoke` pass unchanged
- **Total: 2018 tests passed** ✅

---

## Pirlo Lead Review (2026-07-01 APPROVED)

✅ **Verdict: APPROVE**

**Checklist results:**
- ✅ Asset loading correct (`importlib.resources.files` PEP 451)
- ✅ Fallback dispatch works (asset preferred, drawn as silent backup)
- ✅ Packaging verified (wheel inspection confirms PNG + ATTRIBUTION.md present)
- ✅ Attribution satisfies Apache 2.0
- ✅ No regression (2018 tests passed)

---

---



# Decision: Standard Competition Ranking (1224 style)

**Date:** 2026-07-01  
**Author:** Kanté (backend)  
**Status:** Implemented, committed in 8987262

## Summary
Added `standard_competition_positions` helper to formatters.py that implements "1224 style" tie-aware ranking: tied participants share the same position and the next position skips accordingly. E.g., scores [31, 31, 30] → positions [1, 1, 3].

## Key Details
- **Input:** Pre-sorted list of ranking rows with `.total_score` attribute
- **Output:** List of 1-based competition positions
- **Tie rule:** Two rows are tied if `round(score_a, 1) == round(score_b, 1)`
- **Used by:** `/porra`, `/general`, `/clasificacion` commands and podium image feature
- **Test count:** 1951 passed (added 12 new tests)

## Files Changed
- `src/worldcup_bot/bot/formatters.py`: Added `standard_competition_positions` helper; updated `format_general_ranking`
- `tests/test_formatters.py`: Added `TestStandardCompetitionPositions` (9 cases) + `TestFormatGeneralRankingTieAwareNumbering` (3 cases)

---



# Decision: Podium Photo Compositing Feasibility & Approach

**Author:** Pirlo (Lead)  
**Date:** 2026-07-01  
**Status:** Proposal approved, implementation completed

## Feasibility Verdict
✅ **Merging tied photos into one combined image:** Fully feasible with Pillow 12.2.0  
✅ **Single podium image with crowns + position numbers:** Fully feasible with Pillow canvas + ImageDraw

## Recommended Approach (Option B — Single Podium Image)
- **Canvas:** Fixed 700 × 350 px, dark background
- **Tiles:** Uniform 200×200 px, circular crop optional, LANCZOS resize
- **Crown:** Single overlay per tile with position number inside/below
- **Placeholders:** Missing photos render as solid-color circles + initials (first letter of display name)
- **Layout:** Tie-aware positioning — tied positions share same y-height on canvas
- **Fallback chain:** Podium image → album (old code) → plain text

## Assets Needed
- `crown.png`: ~5 KB, 64×64 px, transparent background (or hand-drawn)
- `podium_font.ttf`: DejaVu Sans Bold (~700 KB, SIL OFL licensed) — required for Docker consistency

## Key Decisions
- **Missing photos:** Always generate placeholder (ensures podium always renders)
- **Crown rendering:** Bundle PNG asset (cleanest option)
- **Font:** Bundle TTF in assets (Docker slim images don't have system fonts reliably)
- **Layout adaptability:** Use `standard_competition_positions` to determine tie-aware heights
- **Always-on mode:** Replace album with podium image always (no branching on ties)

## Risk Level
Low — graceful fallback to text if anything fails. Effort estimate: ~1 working day.

## Prerequisite
`standard_competition_positions` helper must land first.

---



# Decision: Rich Image — Country-Themed Winners (2026-07-01 SHIPPED)

**Date:** 2026-07-01  
**Author:** Kanté (Backend)  
**Status:** ✅ SHIPPED (commit 47b7e41)

---

## Summary

Extended the daily `rich_image` feature: each day's image now incorporates opulent, country-themed luxury props inspired by yesterday's football-day winners — while the day-over-day wealth escalation continues unchanged.

---

## New / Changed Signatures

### `RICH_THEME_PROMPT` (module-level constant in `rich_image.py`)
A tunable prompt string instructing the chat model to return one opulent/funny/specific luxury visual element per winning country — comma-separated, no extra text. Bakes in David's vibe examples: Norway→golden Viking helmet; France→jewel-encrusted baguette; Mexico→gourmet nachos with truffle; England→tea in a solid gold cup; Belgium→a parliament building they bought outright; USA→surrounded by piles of US dollar bills.

### `generate_wealth_themes`
```python
async def generate_wealth_themes(
    api_key: str,
    base_url: str,
    model: str,
    winners: list[str],
    *,
    _client: object | None = None,   # inject for tests
) -> str
```
- Returns `""` immediately when `winners` is empty.
- Calls `client.chat.completions.create` with `RICH_THEME_PROMPT + " " + ", ".join(winners)`.
- **Best-effort / never raises**: on any exception returns `", ".join(f"opulent luxury {c}-themed elements" for c in winners)`.
- `_client` injectable (same pattern as `generate_rich_caption`).

### `build_rich_prompt`
```python
def build_rich_prompt(
    history: str = "",
    anchor: bool = False,
    themes: str = "",   # NEW — comma-sep opulent props
    pose: str = "",     # NEW — random activity
) -> str
```
When `themes` is non-empty appends:  
`" ALSO incorporate a few of these opulent, country-themed luxury elements into the scene, worked in tastefully (inspired by yesterday's winning countries): {themes}."`  

When `pose` is non-empty appends:  
`" In THIS image, show the person {pose}. VARY the pose and activity each time — do NOT default to sitting and toasting with champagne."`  

Insertion order: `history clause → themes clause → pose clause → anchor clause`.

### `POSE_ACTIVITIES` (module-level list, 14 entries)
Covering: dancing, standing on red carpet, lounging on a chaise longue, spa massage, partying with a crowd, napping in opulent bed, embracing a companion, walking a red carpet, posing with entourage, relaxing in infinity pool, being served by staff, laughing mid-celebration, striding through a luxury penthouse, being pampered at a private salon.

### `run_rich_iteration`
```python
async def run_rich_iteration(
    settings: Settings,
    *,
    _client: object | None = None,
    _caption_client: object | None = None,
    _data_dir: str = "/app/data",
    _now: datetime | None = None,
    winners: list[str] | None = None,   # NEW
) -> tuple[str, int, str]
```
- Computes themes: calls `generate_wealth_themes(... _client=_caption_client)` when `winners` is truthy and all three chat-model settings are non-empty; otherwise `themes = ""`.
- Picks random pose from `POSE_ACTIVITIES`.
- Passes `themes` and `pose` to `build_rich_prompt`.
- Does NOT pass `themes` to `generate_rich_caption` (caption uses original rude tone only).
- Logs `winners` and `themes`.

---

## Winners → Themes → Pose Flow

```
rich_image_job
    │
    ├─ make_client(settings)
    │       ↓
    │   client.get_football_day_matches(timezone, day_offset=-1, anchor_hour=...)
    │       ↓
    │   [FINISHED matches only; HOME_TEAM / AWAY_TEAM winners; DRAW skipped]
    │       ↓
    │   winners = ["Norway", "France", ...]   (or [] on error)
    │
    └─ run_rich_iteration(settings, winners=winners)
            │
            ├─ generate_wealth_themes(api_key, base_url, model, winners, _client=_caption_client)
            │       → "golden Viking helmet, jewel-encrusted baguette"  (or fallback)
            │
            ├─ random.choice(POSE_ACTIVITIES)
            │       → "dancing with champagne"
            │
            ├─ build_rich_prompt(history, anchor, themes=..., pose=...)
            │       → image-edit prompt with themes + pose clauses woven in
            │
            ├─ edit_rich_image(... prompt=prompt ...)
            │
            └─ generate_rich_caption(...)
                    → caption (themes NOT mentioned; original rude tone only)
```

Error-handling at every level:
- `get_football_day_matches` failure → `winners = []`, job continues.
- `generate_wealth_themes` exception → fallback string, never propagates.
- `generate_rich_caption` exception → default fallback caption, never propagates.

---

## Refinements Applied (2026-07-01, live-test feedback)

### 1. Too Much Gold → Varied Luxury

`RICH_THEME_PROMPT` now explicitly instructs the model NOT to default to gold/golden for every element and lists varied luxury materials: diamonds, platinum, marble, silk, crystal, caviar, designer furs, exotic woods, haute couture, precious jewels, rare materials. Examples reworked:
- Norway → a diamond-encrusted Viking longship
- France → a caviar-topped artisan baguette on a marble tray
- Mexico → a crystal platter of truffle nachos
- England → a silk-lined tea set with hand-painted porcelain cups
- Belgium → a private parliament building filled with Belgian chocolate sculptures
- USA → surrounded by piles of platinum-banded US dollar bills

### 2. Repeated Pose → Random Pose/Activity

`POSE_ACTIVITIES` list added with 14 varied entries. `build_rich_prompt` gained `pose` parameter. `run_rich_iteration` picks with `random.choice(POSE_ACTIVITIES)` each iteration. `RICH_EDIT_PROMPT` softened to encourage variation.

### 3. Caption Reverted (Themes OUT of Caption)

The rude/chulesco caption (`RICH_CAPTION_PROMPT`) is UNCHANGED and does NOT mention themes. Themes appear only in the image prompt (`build_rich_prompt`).

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/ai/rich_image.py` | `RICH_THEME_PROMPT`, `POSE_ACTIVITIES` consts; `generate_wealth_themes` func; extended `build_rich_prompt`, `run_rich_iteration` |
| `src/worldcup_bot/__main__.py` | `rich_image_job`: fetch yesterday's winners before calling `run_rich_iteration(settings, winners=winners)` |
| `tests/test_rich_image.py` | 53 new tests (35 initial + 18 refinements) |

---

## Test Count

**2071 passed** (+53 new tests, up from 2018). All green. Live-tested by coordinator: 2 runs of 5 iterations each sent to Telegram chat 3041850; David reviewed and approved.

---


