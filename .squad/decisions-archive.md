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

---