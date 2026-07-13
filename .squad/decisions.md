# Decisión: /perfil → teclado inline en lugar de lista de texto

**Fecha:** 2026-07-13  
**Autor:** Kanté  
**Estado:** Implementado

## Contexto

El comando oculto `/perfil` mostraba en su rama sin-args un mensaje de texto plano con la lista de perfiles disponibles ("Uso: /perfil @usuario\n\nPerfiles disponibles: @pepe, @juan…"). Era funcional pero poco ergonómico: el usuario tenía que teclear el nombre manualmente.

## Decisión

Reemplazar la rama sin-args por un `InlineKeyboardMarkup` con un botón por perfil (`@{username}`, `callback_data="perfil:{username}"`), 2 por fila, en orden alfabético. Pulsar un botón edita el mismo mensaje con el perfil completo y elimina el teclado.

## Diseño

- **`_format_profile(profile: UserProfile) -> str`** (`handlers.py:1374`) — helper de módulo que centraliza el renderizado. Usado por `/perfil @usuario` (ruta directa) y por `cb_perfil_select` (callback).
- **Teclado:** `InlineKeyboardMarkup` construido desde `sorted(profiles)`, filas de 2.
- **`cb_perfil_select`** (`handlers.py:1481`) — `query.answer()` primero (ack spinner); carga perfiles vía `context.bot_data["picante_profiles_path"]`; si perfil existe → `edit_message_text(_format_profile(profile))` sin `reply_markup` (elimina el teclado en el mismo paso); si ya no existe → mensaje amistoso.
- **Registro** (`__main__.py:2482`): `CallbackQueryHandler(cb_perfil_select, pattern=r"^perfil:")`.

## Truco clave

`await query.edit_message_text(text)` sin `reply_markup` elimina el teclado inline automáticamente — no se necesita una llamada separada a `edit_message_reply_markup`.

## Compatibilidad

`/perfil @usuario` (ruta con arg) funciona exactamente igual que antes. Sin args + sin perfiles → "No hay perfiles todavía…" (mismo texto que la ruta con arg cuando no hay perfiles).

## Tests para Buffon

Deben actualizarse:
1. `TestCmdPerfil::test_no_args_empty_profiles_replies_simple_usage` — ahora espera "No hay perfiles todavía…" en lugar de "Uso: /perfil @usuario".
2. `TestCmdPerfil::test_no_args_with_existing_profiles_lists_them` — ahora espera texto "Elige un perfil:" + `InlineKeyboardMarkup` con botones (no texto plano). Buffon debe añadir pruebas para `cb_perfil_select` (found, not_found, malformed_data, error_path).


# Decision: /perfil hidden admin command

**Date:** 2026-07-10  
**Author:** Kanté  
**Status:** implemented

## Context

Admin needed to inspect auto-learned picante user profiles without docker-exec'ing into the container to read `picante_profiles.json` directly.

## Decision

Added a hidden `/perfil @usuario` Telegram command. Read-only inspector of `UserProfile` data — no changes to profile logic.

## Key choices

| # | Choice | Rationale |
|---|--------|-----------|
| 1 | **Placed in `handlers.py`** (not `__main__.py`) | Mirrors `/tongocheck`; keeps hidden admin commands co-located. |
| 2 | **No access-control gate** | Matches the existing hidden-by-omission pattern (`/tongocheck`, `/recalcular`, `/evilsanchez` have none). |
| 3 | **Profiles path from `bot_data["picante_profiles_path"]` with fallback** | Consistent with how `maybe_reply` reads it; no hardcoded paths. |
| 4 | **Plain text output (no HTML parse_mode)** | All adjacent hidden commands use plain text. Profile values are free text — plain text avoids escaping complexity and matches the surrounding style. |
| 5 | **Lists available usernames on not-found / no-args** | Avoids the frustrating "no hay perfil" dead end — admin immediately knows what keys exist. |
| 6 | **Top-level import of `load_profiles`/`get_profile`** | Consistent with codebase rule (no inline imports in production modules). |

## Files changed

- `src/worldcup_bot/bot/handlers.py` — new import (line 86) + `cmd_perfil` (line 1374)
- `src/worldcup_bot/__main__.py` — import (line 61) + `CommandHandler("perfil", cmd_perfil)` (line 2435)

## Tests

2573 pass, 0 regressions (test_handlers.py: 166 pass).


# Decision: Picante prompt — balanced conditional context usage

**Date:** 2026-07-10T11:31:40+02:00
**By:** Kanté (requested by drdonoso)
**File:** `src/worldcup_bot/chat/picante.py`

## Decision

Recalibrate the picante `_SYSTEM` prompt and the inline CONTEXTO RECIENTE instruction in `build_picante_user_message` to use a **balanced conditional** for recent context:

- **IF** the CONTEXTO RECIENTE is clearly related to the ÚLTIMO MENSAJE (same topic, ongoing thread, or continuing exchange) → **actively use it**: weave in continuity/callbacks so the comment is sharper and connected.
- **IF** the CONTEXTO RECIENTE is not related → **ignore it completely** and comment only on the last message.

## What was wrong before

The previous wording was too absolute toward ignoring context:
- `_SYSTEM`: "dirigido EXCLUSIVAMENTE al ÚLTIMO MENSAJE", "El bloque 'CONTEXTO RECIENTE' es solo de apoyo", "IGNÓRALOS por completo"
- Inline instruction: "úsalo SOLO si está claramente relacionado... si no, ignóralo"

This over-suppression caused the model to drop context even when the recent conversation was clearly on the same topic, making replies feel disconnected from live threads.

## New wording (summary)

`_SYSTEM` REGLA DE CONTEXTO:
> "Si el bloque 'CONTEXTO RECIENTE' está claramente relacionado con el ÚLTIMO MENSAJE (mismo tema, conversación en curso o hilo que continúa), tenlo en cuenta y aprovéchalo — un callback o referencia al hilo hace el comentario más afilado y conectado. Si el contexto reciente no tiene relación con el último mensaje, ignóralo por completo y comenta solo el último mensaje."

Inline label in `build_picante_user_message`:
> "CONTEXTO RECIENTE — si está claramente relacionado con el ÚLTIMO MENSAJE, tenlo en cuenta y aprovéchalo; si no lo está, ignóralo por completo:"

## What is NOT changed

- The reply still targets the ÚLTIMO MENSAJE (messages[-1]).
- The two-section structure (CONTEXTO RECIENTE block + ÚLTIMO MENSAJE block) is unchanged.
- IDIOMA, TONO, FORMATO rules are unchanged.
- All gate functions, `maybe_reply` orchestration, RingBuffer, and listener plumbing are unchanged.
- The plumbing already passes up to `chat_buffer_size` prior messages via `buf.snapshot()` → `build_picante_user_message`.

## Tests

156/156 green (test_chat.py + test_chat_edge_cases.py). No test assertions were bound to the old wording substrings, so no Buffon updates needed.



## 2026-07-10T11:31:40+02:00: User directive — picante context usage
**By:** drdonoso (via Copilot)
**What:** El mensaje picante debe tener en cuenta la conversación reciente (CONTEXTO RECIENTE) SOLO si está claramente relacionada con el último mensaje. Cuando esté relacionada, debe usarla de forma fiable para un comentario con continuidad. Cuando NO esté relacionada (otro tema/otra conversación), debe ignorarla por completo y responder solo al último mensaje.
**Why:** User request — refina la calibración del prompt de picante. El plumbing ya pasa hasta chat_buffer_size mensajes previos; el ajuste es de prompt (la redacción actual es demasiado absoluta hacia "ignora" y descarta contexto sí relacionado).



# Micky Birthday Special — Design Decisions

**Date:** 2026-07-10  
**Author:** Kanté (Backend Developer)  
**Feature:** July-10 Micky birthday special in the daily "rich" image pipeline

---

## 1. Evolution-chain isolation — DO NOT promote into `rich_modified.png`

**Decision:** On July 10, the Micky birthday image is written to `rich_micky_birthday.png`
in the state directory. `rich_modified.png` is left **untouched**. `save_level`,
`append_history`, and `append_caption` are **skipped**.

**Rationale:**  
The daily rich pipeline is a single-person wealth-escalation chain. If July-10's
3-image Micky-protagonist scene were promoted as the new evolution base, the July-11
image would continue from a scene showing _two_ people, drifting the identity chain
away from the single "rich" character. Over subsequent days this would corrupt the
lineage. The birthday image is a one-off celebration, not a wealth step.

**Caller impact (`__main__.py:_evolve_and_send_rich_image`):**  
```python
out_path, level, caption = await run_rich_iteration(settings, winners=winners)
# out_path is returned as rich_micky_birthday.png on July 10 — still a valid readable path
with open(out_path, "rb") as photo_fh:
    await context.bot.send_photo(...)
```
The caller only needs `out_path` to be a readable file. `level` is used only for
logging and is harmlessly set to `load_level() + 1` (the would-be next level).
No evolution chain state changes, so July-11 continues from the same base as July-9.

**Alternative considered:** Simply overwrite `rich_modified.png` (same as July-8 birthday mode).  
**Rejected because:** July-8 is still a single-person scene (just birthday-themed). July-10
features *two people* (Micky as protagonist + rich alongside), making it categorically
different from the normal wealth-chain images.

---

## 2. Three-image edit call on July 10

When `micky_birthday=True`:
- Image 1 (base): `rich_modified.png` — the current evolved rich image (style reference)
- Image 2 (anchor): `rich_original.jpg` — clean original face (locks rich's identity)
- Image 3 (extra): `micky.jpg` — contains both Micky and rich; used to match Micky's face

`edit_rich_image` was generalised to accept `extra_paths: list[str] | None = None`.
All file handles are now managed via `contextlib.ExitStack` (safe close on any error).
Backward-compatible: existing 2-image and 1-image paths are unchanged when `extra_paths`
is `None` or empty.

---

## 3. Graceful fallback if `micky.jpg` is absent

If `find_micky_image(_data_dir)` raises `FileNotFoundError`, a WARNING is logged and
`micky_birthday` is reset to `False`, causing the day to run as a normal iteration.
The daily job is never crashed by a missing reference image.

---

## 4. Caption — explicit Micky greeting mandatory

`generate_rich_caption` received `micky_birthday: bool = False`. When active, an
instruction is injected that makes the felicitation to Micky **mandatory** in the
AI-generated text. Fallback caption (no-AI path): 
`f"🎂 ¡Feliz {micky_age} cumpleaños, Micky! Que los sigas cumpliendo a nuestra costa 🥂"`

---

## 5. `build_rich_prompt` — clean age separation

`build_rich_prompt` received `micky_birthday: bool = False`. On July 10,
`run_rich_iteration` calls it with `birthday=False, age=micky_age, micky_birthday=True`
so that `MICKY_BIRTHDAY_CLAUSE.format(age=micky_age)` is appended with the correct age,
and `RICH_BIRTHDAY_CLAUSE` is not touched (July 10 is not rich's birthday).

---

## 6. Test result

All **251 existing tests** pass with no changes. The July-10 3-image path is exercised
only when `_now=datetime(year, 7, 10)` — Buffon will add those tests separately.


# Decision: Rich Birthday Mode (2026-07-08 SHIPPED)

**Date:** 2026-07-08  
**Authors:** Kanté (Backend Implementation), Buffon (QA Tests)  
**Status:** ✅ SHIPPED (commit 3ff9d6a)  

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the rich-birthday feature:
1. kante-rich-birthday.md — Implementation details
2. buffon-rich-birthday-tests.md — Test coverage (14 new tests + 3 regression fixes)

---

## Summary

`run_rich_iteration` in `src/worldcup_bot/ai/rich_image.py` now supports an annual birthday mode on July 8. The character turns 42 in 2026 (born 1984, auto-incrementing yearly). Birthday is layered onto the existing wealth escalation and country-themed winners (AUGMENT, not separate image).

---

## New Public API

```python
RICH_BIRTHDAY_MONTH: int = 7
RICH_BIRTHDAY_DAY: int = 8
RICH_BIRTH_YEAR: int = 1984
RICH_BIRTHDAY_CLAUSE: str  # .format(age=...) to fill

def is_rich_birthday(now: datetime) -> bool: ...
def rich_birthday_age(now: datetime) -> int: ...

def build_rich_prompt(..., birthday: bool = False, age: int | None = None) -> str: ...
async def generate_rich_caption(..., birthday: bool = False, age: int | None = None, ...) -> tuple[str, str]: ...
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| AUGMENT wealth/themes, not separate | Birthday layered on top of existing features |
| Birth year = 1984 | Age auto-increments yearly (now.year - 1984) |
| Birthday clause before anchor clause | Anchor stays last per existing convention |
| Fallback caption is birthday-themed | 🎂 message on any rendering failure |

---

## Test Results

- `tests/test_rich_image.py` → 251 passed
- Full suite → 2379 passed
- 3 pre-existing tests fixed (pinned to non-birthday date via `_now` parameter)
- 14 new tests added: is_rich_birthday, age calculation, prompt/caption augmentation

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/ai/rich_image.py` | RICH_BIRTHDAY_* constants, is_rich_birthday, rich_birthday_age helpers, extend build_rich_prompt and generate_rich_caption, thread birthday/age through run_rich_iteration |
| `tests/test_rich_image.py` | 14 new tests (TestRichBirthdayMode) + 3 regression fixes |

---



# Decision: Suiza-Colombia Porra Scoring Investigation — NO BUG (2026-07-08)

**Date:** 2026-07-08  
**Author:** Buffon (QA Investigation)  
**Status:** ✅ NO CODE CHANGE REQUIRED  

---

## Summary

Investigation into a perceived scoring bug where Switzerland's 0-0 knockout win vs Colombia on penalties was allegedly not credited in `/porra`. After verification, the current code correctly handles the match: the bot's scoring engine and the raw football-data API both confirm the penalty winner is awarded points.

---

## Verification Steps

### 1. Raw football-data API
Fetched live match 3041850 (SUI vs COL, knockout): football-data returns `winner: "HOME_TEAM"` for penalty-decided matches. Ball data accurate.

### 2. Bot's `get_knockout_results()` (scoring.py)
Correctly parses API winner and returns `(Home team TLA, Knockout round)` tuple.

### 3. `score_knockout()` in scoring.py
Invoked with SUI-COL prediction: awarded +2 acierto points for the correct penalty winner. Score calculated correctly.

### 4. All 4 penalty knockout matches verified:
- GER vs PAR: winner correctly identified
- NED vs MAR: winner correctly identified
- AUS vs EGY: winner correctly identified
- SUI vs COL: winner correctly identified

---

## Conclusion

**NO BUG.** The code is working as designed. The user's observation was likely a misunderstanding of the match result or scoring lag (predictions not yet saved/calculated when initially checked).

User accepted: *"igual no hay bug, déjalo tal cual está"*

---

## Files Changed

None.

---



# Decision: Knockout Final Deferral Fix (2026-07-08 SHIPPED)

**Date:** 2026-07-08  
**Authors:** Kanté (Backend Implementation), Buffon (QA Tests), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit d10ef77)  

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the knockout-final deferral fix:
1. kante-ko-draw-deferral.md — Root-cause analysis and implementation
2. buffon-ko-draw-deferral-tests.md — Test coverage (8 new regression tests)
3. pirlo-ko-draw-deferral-review.md — Lead review (APPROVED)

---

## Problem

A knockout match "Switzerland 0-0 Colombia" fired a bare `🏁 Final` notification with NO penalty winner listed. The `match_result_is_final` function in formatters.py only deferred when `duration=="PENALTY_SHOOTOUT"`. When a 0-0 KO match first flips to FINISHED, football-data briefly reports:
- `duration="REGULAR"` or `"EXTRA_TIME"`
- `winner="DRAW"` or `None`
- No penalties block yet

The old gate returned `True` → announcement fired immediately with incomplete data.

---

## Root Cause

**Invariant violated:** A knockout-stage match can NEVER legitimately end in a draw. Any FINISHED KO match without `winner in ("HOME_TEAM", "AWAY_TEAM")` is still mid-processing at the API free tier.

---

## Fix (Kanté)

`src/worldcup_bot/bot/formatters.py`:

1. Added module-level constant:
   ```python
   _KNOCKOUT_STAGE_NAMES: frozenset[str] = (
       frozenset(api for api, _, _ in KNOCKOUT_STAGES) | {"THIRD_PLACE"}
   )
   ```
   Covers: LAST_32, LAST_16, QUARTER_FINALS, SEMI_FINALS, FINAL, THIRD_PLACE.

2. New check in `match_result_is_final` (after existing PENALTY_SHOOTOUT branch):
   ```python
   if match.stage in _KNOCKOUT_STAGE_NAMES and match.winner not in ("HOME_TEAM", "AWAY_TEAM"):
       return False
   ```

---

## Guarantees

- **Group draws unaffected:** `stage="GROUP_STAGE"` NOT in knockout set → returns `True` → announces normally ✓
- **Deferral mechanism unchanged:** `__main__.py` already defers non-final matches without touching `finished_announced` → match retries on next tick ✓
- **STALL RISK accepted:** If API never populates winner, match permanently defers. This is safer than announcing a corrupt knockout draw ✓

---

## Test Results

- `tests/test_formatters.py` + `tests/test_poll_finished_job.py` → 169 passed
- Full suite → 2387 passed
- Tests cover: KO draw regular/extra-time, KO settled by penalties, KO decided in regulation, group draw regression

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/bot/formatters.py` | Added _KNOCKOUT_STAGE_NAMES, new deferred-check for KO + no winner |
| `tests/test_formatters.py` | 6 new tests (TestMatchResultIsFinal) |
| `tests/test_poll_finished_job.py` | 2 new integration tests (TestKnockoutDrawDeferral) |

---

## Review (Pirlo — APPROVED)

✅ **Verdict: APPROVE**

Correctness verified. Stall risk (permanent defer if API never sends winner) is acceptable because:
1. football-data typically resolves transient state within minutes
2. Announcing a KO draw would corrupt the porra game state
3. Safest behavior when in doubt

Safe to deploy.

---



# Decision: USA-Belgium Goal/Anulado Flood — Root Cause & Cross-Source Fix (2026-07-07 SHIPPED)

**Date:** 2026-07-07  
**Authors:** Kanté (Backend Implementation), Buffon (QA Tests), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 22f4ce9)  
**Urgency:** 🔴 HIGH  

---

## MERGED DECISIONS (3 files → 1 entry)

This entry consolidates the complete USA-Belgium VAR flood fix:
1. kante-usa-belgium-goal-flood.md — Root-cause analysis and implementation
2. buffon-var-two-source-regression.md — Regression test coverage with empirical proof
3. pirlo-goal-flood-review.md — Lead review (APPROVED)

---

## Executive Summary

**Incident:** 100+ alternating "⚽ GOOOOL!" and "❌ Gol anulado" messages during USA vs Belgium match.

**Root Cause:** Cross-source score reconciliation bug. When one source (Reddit thread, fast ~25s) announces a VAR-disallowed goal before the other source (API, slow ~60s) has ever seen the goal, the lagging source's later catch-up is mistaken for a new goal → announces it → catches up to VAR → announces disallowed → repeats every tick.

**Blast Radius:** Any future match with a VAR reversal where the thread is ahead of the API will trigger the same loop.

**Proposed Fix:** After a disallowed is announced by source A, advance source B's seen baseline to the pre-VAR score using max() (never decrease). Add regression test.

---

## Root Cause Deep-Dive

The reconcile() function in score_state.py:220–241 has no guard for this scenario:
1. Source A (thread) announces goal 1-0 → seen_thread={1,0}, seen_api={0,0}
2. Source A announces disallowed → seen_thread={0,0}, announced={0,0}
3. Source B (API) reports 1-0 (delayed catch-up) → reconcile() sees _ahead(1-0, 0-0) = True
4. Treats 1-0 as a brand-new goal (indistinguishable from a genuine new goal)
5. Announces false goal → catches up to announced disallowed → announces false disallowed
6. Loop repeats every API poll (~60s) for duration of unstable VAR review

### Why existing tests missed this

test_real_var_thread_goal_then_disallowed (test_poll_thread_goals_job.py:518) sets seen_api={3,2} — meaning the API was synchronized to the PRE-GOAL score. The USA-Belgium scenario requires seen_api to be below the pre-goal score when the disallowed fires.

---

## Recommended Fix (NOT YET IMPLEMENTED)

### poll_thread_goals_job (inside if deltas: block, after save_scores):

After a thread-sourced disallowed, advance the API's seen baseline:

\\\python
if any(d.kind == "disallowed" for d in deltas):
    api_seen = seen_scores["api"]
    cur = api_seen.get(key, {"home": 0, "away": 0})
    api_seen[key] = {
        "home": max(cur["home"], ann_homeaway["home"]),
        "away": max(cur["away"], ann_homeaway["away"]),
    }
\\\

### poll_goals_job (inside elif deltas: block, after scores[match_key] = new_ann):

After an API-sourced disallowed, advance the thread's seen baseline:

\\\python
if any(d.kind == "disallowed" for d in deltas):
    thread_seen = seen_scores["thread"]
    cur = thread_seen.get(match_key, {"home": 0, "away": 0})
    thread_seen[match_key] = {
        "home": max(cur["home"], ann_homeaway["home"]),
        "away": max(cur["away"], ann_homeaway["away"]),
    }
\\\

### Test to add

**Name:** test_thread_disallowed_then_lagging_api_catchup_no_false_goal

**Scenario:** Both sources seeded at 0-0. Thread announces 1-0 (goal) → 0-0 (VAR disallowed). API stays at {0,0} throughout. Then API reports 1-0. Expected: zero goal messages. Currently fails; passes after the fix.

---

## Files Cited

- src/worldcup_bot/reddit/score_state.py (reconcile ~137, _ahead ~220–241)
- src/worldcup_bot/__main__.py (poll_thread_goals_job ~1204, poll_goals_job ~996)
- tests/test_poll_thread_goals_job.py:518 (missing coverage for seen_api={0,0})

---

## Test Coverage — Buffon (QA)

##

# Decision: VAR Two-Source Regression Test Coverage

The USA-Belgium incident exposed a gap: the existing regression test `test_real_var_thread_goal_then_disallowed` seeded `seen_api={3,2}` (already synced), but the actual precondition was `seen_api={0,0}` (lagging), which triggered the oscillation loop.

**Coverage Rule (Going Forward):**
Any regression test for goal/disallowed cross-source reconciliation MUST include a variant where the second source has `seen < pre-goal score`. This is the minimum precondition enabling the oscillation.

### Tests Added

- `tests/test_poll_thread_goals_job.py::TestVARCrossSourceRaceRegression::test_thread_fast_api_lag_var_no_false_goal` — Thread announces goal+disallowed while API lags at 0-0; API later catches up without announcing false goal.
- `tests/test_poll_thread_goals_job.py::TestVARCrossSourceRaceRegression::test_api_fast_thread_lag_var_no_false_goal` — Inverse: API announces disallowed while thread lags.
- `test_thread_fast_real_goal_after_var_not_suppressed` — After disallowed clears, a real subsequent goal IS announced (no over-suppression).
- `test_api_fast_real_goal_after_var_not_suppressed` — Inverse case.

**Empirically PROVED:** Tests fail red without the fix (phantom alternating goal/disallowed), pass green with fix. Full test suite: **2365 passed**.

---

## Lead Review — Pirlo (APPROVED)

### Verdict: ✅ APPROVE

The uncommitted fix safely addresses the USA-Belgium VAR flood bug without introducing over-suppression.

### Over-Suppression Analysis

**Primary Risk:** Would advancing a lagging source's `seen` to the high phantom score permanently swallow a subsequent legitimate goal at that same score?

**Finding:** No. The seen baseline drops back naturally:
1. After the disallowed fires, `seen_api` is advanced to the pre-VAR score (e.g. 0-0).
2. When the lagging source eventually catches up to the actual post-VAR score (0-0), `reconcile()` returns `new_seen = new`.
3. This causes the source's `seen` baseline to naturally drop back down to the correct 0-0 state.
4. When a subsequent legitimate 1-0 goal happens, `seen` is correctly situated at 0-0, and the goal is properly announced. ✓

### Other Checks

- **ann_homeaway semantics:** Holds the pre-disallowment score (cloned before `reconcile` returns post-VAR score). ✓
- **max() in multi-goal games:** Operates safely per-component. ✓
- **Concurrency:** Executed entirely inside `goal_lock` synchronously. ✓
- **Symmetry:** Properly symmetric across `poll_goals_job` and `poll_thread_goals_job`. ✓

### Implementation Location

The fix is in `src/worldcup_bot/__main__.py`:
- `poll_goals_job` (API-sourced disallowed): on a "disallowed" delta, advance thread's `seen` baseline via `max()` to the pre-VAR announced score (ann_homeaway).
- `poll_thread_goals_job` (thread-sourced disallowed): on a "disallowed" delta, advance API's `seen` baseline via `max()` to ann_homeaway.
- Both executed inside `goal_lock`.

---



# Decision: Podium Image Feature Implementation

**Author:** Kanté (backend)  
**Status:** Implemented, committed in 4343ddb

## Summary
Completed implementation of single composite podium image for ranking commands (`/porra`, `/general`), replacing plain URL album. Missing photos use initials placeholders. Falls back to old album if rendering fails.

## `render_podium` Signature
```python
def render_podium(participants: list[dict], settings) -> io.BytesIO | None
```
- **participants:** List of up to 3 dicts with `username`, `display_name`, `position` (tie-aware from `standard_competition_positions`)
- **settings:** Settings instance; only `settings.photo_base_url` used
- **Returns:** PNG BytesIO seeked to 0, or None on failure
- **Threading:** Synchronous; call with `asyncio.to_thread`

## Fallback Chain in `_send_ranking_with_top3_photos`
```
podium image (render_podium → BytesIO)
    ↓ None
album (send_media_group with valid photo URLs)
    ↓ no valid URLs or send_media_group raises
plain text (reply_text)
```

## Visual Design
| Property | Value |
|----------|-------|
| Canvas | 720 × 400 px, dark navy `(22, 27, 34)` |
| Tile shape | Circle, diameter 180 px, LANCZOS resize |
| Tile missing | Solid-color circle + initials (first + last initial) |
| Placeholder colours | Steel blue / sea green / firebrick (by index) |
| Crown | Filled gold polygon (11 vertices) + 3 jewel circles; **drawn with Pillow, no external assets** |
| Position number | 22 pt DejaVu Sans Bold, white |
| Participant name | 16 pt light grey, below tile; truncated at 14 chars |
| Classic podium | 3 participants: centre = 1st, left = 2nd, right = 3rd |
| Tie-aware heights | Position 1→205 px, 2→237 px, 3→257 px |

## Crown Drawing
Entirely drawn with Pillow `ImageDraw.polygon` + `ImageDraw.ellipse`:
- Single filled polygon: band + 3 spikes (11 vertices)
- Three jewel circles at spike tips
- Copyright-safe, requires zero new asset files

## Font Resolution
`matplotlib.font_manager.findfont(FontProperties(family="DejaVu Sans", weight="bold"))` → resolves to bundled `DejaVuSans-Bold.ttf` inside matplotlib package. Fallback: `ImageFont.load_default()`. No new deps (matplotlib already a project dependency).

## Changes
| File | Change |
|------|--------|
| `src/worldcup_bot/bot/podium_image.py` | New module with `render_podium`, `_render_podium`, `_draw_crown`, `_fetch_tile`, `_circular_crop`, `_placeholder_tile` |
| `src/worldcup_bot/bot/handlers.py` | Imports + `_send_ranking_with_top3_photos` rewrite with fallback chain |
| `tests/test_handlers.py` | `TestSendRankingWithPodium` (5 tests) + `_stub_render_podium` autouse fixture |
| `tests/test_podium_image.py` | New — 12 smoke tests for `render_podium` |

## Test Count
1968 passed (0 regressions)

---



# Decision: Podium Image Review — APPROVED

**Reviewer:** Pirlo (Lead)  
**PR Scope:** `src/worldcup_bot/bot/podium_image.py` + `handlers.py` diff  
**Test Suite:** 1968 passed ✅

## Review Checklist Results

| Criterion | Status |
|-----------|--------|
| Fallback Chain (podium → album → text) | ✅ PASS |
| Non-blocking (asyncio.to_thread) | ✅ PASS |
| Never Raises contract | ✅ PASS |
| Tie-Awareness (positions via `standard_competition_positions`) | ✅ PASS |
| Caption handling (1024 limit + overflow) | ✅ PASS |
| No new deps / no bundled art | ✅ PASS |
| Missing-photo fallback (initials placeholders) | ✅ PASS |
| Test suite green | ✅ PASS (1968 passed, 5 pre-existing warnings) |

## Verdict
✅ **APPROVE** — Clean, well-structured implementation. Fallback chain robust. Tie logic correct. No regressions. Ready to ship.

## Minor Observations (non-blocking)
1. **Serial photo fetches:** Only 3 requests, acceptable. Future `ThreadPoolExecutor` optimization not needed now.
2. **Font path cached at import:** Fine — matplotlib's font cache is fast. Fallback covers edge cases.
3. **`r.display_name` assumption:** Correct — `UserRankEntry` includes it.




---



# Decision: TVE Knockout-Round Prefix Fix

**Author:** Kanté (Backend Dev)  
**Date:** 2026-07-04  
**Author:** Buffon (QA)  
**Status:** ✅ SHIPPED (commit e832645)

---

## Problem

`revive_inactive_job` has a quiet-hours guard (default 23:00–06:00 Europe/Madrid).
Eight success-path tests asserted `send_message` was called but never froze the clock.
Running the suite between 23:00 and 06:00 caused the guard to skip the send and fail
all eight tests. Outside that window they passed — classic time-dependent flakiness.

Affected:
- `tests/test_chat_edge_cases.py::TestReviveInactiveJob` (7 tests)
- `tests/test_revive_schedule.py::TestReviveInactiveJobReschedule::test_success_path_reschedules` (1 test)

---

## Key Gotcha: Frozen Date Must Be Today, Not a Hardcoded Past Date

The existing `_frozen_datetime_cls(hour)` freezes to 2026-06-30. That works for
quiet-hours tests (which short-circuit before the inactivity check), but NOT for
success-path tests.

`_inactive_ts(5)` computes timestamps as **real_now − 5 days**.  
A frozen `now` of 2026-06-30 14:00 is only ~14 hours after that timestamp when the
test runs in July 2026 — well under `inactive_days = 3`. Alice would not appear as
a candidate and the send would never happen.

**Solution:** Freeze to **today at 14:00 Madrid** (real current date, synthetic hour):

```python
def _frozen_datetime_active_cls() -> type:
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    now_madrid = now_utc.astimezone(_TZ_MADRID)
    frozen = _TZ_MADRID.localize(
        _dt.datetime(now_madrid.year, now_madrid.month, now_madrid.day, 14, 0, 0)
    )
    class _FrozenDt(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return frozen.astimezone(tz)
            return frozen
    return _FrozenDt
```

This keeps `frozen_now − _inactive_ts(5)` ≈ 5 days > `inactive_days = 3`, while
hour 14 is always outside the 23→06 quiet window.

---

## Pattern Applied

- `tests/test_chat_edge_cases.py`: `autouse=True` fixture on `TestReviveInactiveJob`
  that patches `worldcup_bot.chat.revive.datetime` for the entire class.
- `tests/test_revive_schedule.py`: explicit `with patch(...)` block in
  `test_success_path_reschedules`.

Quiet-hours tests (frozen to 23:30) are intentionally unchanged.

---

## Rule for Future Revive Tests

> Any test that calls `revive_inactive_job` and asserts `send_message` IS called
> **must** freeze `worldcup_bot.chat.revive.datetime` to a non-quiet hour.
> Use `_frozen_datetime_active_cls()` (freezes to today at 14:00 Madrid) — not
> `_frozen_datetime_cls(hour)` (hardcoded 2026-06-30) — so that inactivity timestamps
> computed with `datetime.now()` remain > `inactive_days` from the frozen perspective.


---

# Decision — Final (Bug #2) revision + memory fixes

Author: Cannavaro (backend, escalation)
Date: 2026-07-04
Re: revision of a61757d (rejected by Pirlo). Fix-forward on `main`.
Requested by: danielrdon

## Why the previous fix was rejected (recap)
Kanté's wall-clock fallback announced a real `🏁 Final` from a still-`IN_PLAY`/
`PAUSED` football-data object and marked the match in `finished_announced`. If
that score was stale/null it persisted a WRONG final AND suppressed the later
real `FINISHED` recap. It also treated `PAUSED` >4h as final, which can be a
resumable suspension.

## Corrected FINAL design (fixes both blockers)
Two distinct announcements, two distinct dedup states:

1. Official recap — unchanged. Only `status == "FINISHED"` (and shootout-settled)
   produces the `🏁 Final` recap and consumes `finished_announced`.
2. Provisional notice — for a match the API keeps `IN_PLAY` past `MATCH_OVER_AGE`
   (4 h from kickoff), send a clearly-labelled `⏳ Resultado provisional`
   (`format_provisional_result`). It is tracked in a NEW, SEPARATE persisted set
   `provisional_announced` (`{state_dir}/provisional_announced.json`) and does
   NOT touch `finished_announced`.

Because the provisional path never consumes the final dedup state:
- The OFFICIAL `🏁 Final` recap still fires when the API eventually reports
  `FINISHED` — even 9 h later — with the API-confirmed score. That official
  message IS the correction; a stale/null provisional score is self-correcting
  and is never persisted as a final. → fixes Blocker 1.
- On the official recap the id is removed from `provisional_announced` (bounded
  set), giving exactly one provisional + one official message, each idempotent.

`PAUSED` handling → fixes Blocker 2: `PAUSED` is EXCLUDED from the provisional
path. football-data uses `PAUSED` for half-time and for weather/security/medical
suspensions that can resume; only a stuck `IN_PLAY` reliably means "match really
over" (and IN_PLAY was the actual Australia-Egypt failure mode). A PAUSED match
is announced only once it legitimately reaches `FINISHED`.

Why not reuse `finished_scores`/VAR-correction as the primary mechanism: its
window is `final_correction_window_minutes` (30 min) and entries are pruned long
before a multi-hour-late `FINISHED` flip, so it cannot carry a 9 h correction.
The provisional-then-official split is the natural, correct fit. (The existing
VAR-correction watch remains untouched and still handles genuine post-final score
changes within its window.)

Guarantees: worst-case latency for a genuinely-finished match is bounded at
`MATCH_OVER_AGE` (provisional notice); no uncorrectable wrong final is ever
emitted; no double official announcement; restart-safe (both sets persisted,
first-run seed still seeds stale matches into `finished_announced`).

## Keyboard follow-ups (Bug #1)
- Bounded retries: `keyboard_attempts` added to the clip entry schema
  (`clip_store.add_entry`). `poll_goal_clips_job` increments it on every failed
  keyboard edit (initial + retry loop) and, at `_MAX_KEYBOARD_ATTEMPTS = 5`,
  forces `keyboard_attached = True` to stop retrying a permanently-dead message
  (deleted / bot blocked) — previously it retried every 45 s until 7-day pruning.
- Preserve on text edit: `_backfill_scorer_in_clip_store` and `_mark_goal_annulled`
  now set `keyboard_attached = True` after a successful `edit_message_text` that
  re-attached the keyboard (`reply_markup=` passed for a `ready` clip), avoiding
  redundant retry edits. (`editMessageText` without `reply_markup` clears the
  keyboard — that path is unchanged and still omits it when not ready.)

## Memory fixes
1. Shared football-data client: `build_app` creates one `make_client(settings)`
   into `bot_data["football_client"]`. 19 call sites (7 in `__main__.py`, 12 in
   `bot/handlers.py`) now use `_football_client(context)`, which returns the
   shared client (single `requests.Session`, HTTP keep-alive) and only falls back
   to a one-off `make_client` when absent (unit tests). Kills ~10.4k
   session/pool objects/day — the main RSS driver. Safe to share: no per-call
   mutation on `FootballDataClient`.
2. Reddit body-cache eviction: `get_thread_body` now sweeps entries older than
   `5 × _THREAD_BODY_TTL` once the cache exceeds 40 entries; finished-match
   permalinks no longer live forever.
3. Keyboard retry give-up (as above) — bounds a runaway Telegram API loop.
4. AI httpx clients closed: `AIClient.aclose()` (wraps `AsyncOpenAI.close()`);
   per-event clients in `_enrich_scorer` and the recap job's Part B are closed in
   `try/finally`.

## Verification
- Full suite `.venv\Scripts\python.exe -m pytest -q`: 2218 passed (~63 s).
- Rewrote `TestWallClockFallback` → `TestProvisionalLateFinal` (provisional on
  stale IN_PLAY; official FINISHED still fires/corrects; PAUSED not finalized; no
  double-announce; restart persistence). Added shared-client, keyboard give-up,
  scanner-eviction and `AIClient.aclose` tests.
- `docker-compose*.yml` untouched (Maldini's memory cap left as-is).


---



# Decision: streamff goal-clip download — resolve source from page, resilient CDN fallback

**Author:** Cannavaro (backend reliability)
**Date:** 2026-07-04T21:37+02:00
**Scope:** `src/worldcup_bot/reddit/downloader.py`, `tests/test_downloader.py`
**Commit:** separate from Parts A/B/C (see hash below)

## Problem (hit live during Canada vs Morocco)

A goal clip was matched on `streamff.pro/v/92cb0999`, but the downloader:

1. Built the direct-CDN URL on a **stale hardcoded host** `cdn.streamff.one/{id}.mp4`
   → `ConnectionResetError(104, 'Connection reset by peer')` (dead host).
2. Fell through to yt-dlp with a `streamff.com/v/{id}` URL → `Unsupported URL`.

`download()` returned `None`, so `poll_goal_clips_job` never attached the
"Ver gol" inline keyboard to the goal message.

## Root cause

streamff **rotates domains** (streamff.pro / .one / .com / .link / .gg / …) and
their CDN hosts move with them. The old code hardcoded a single CDN base and
routed streamff to yt-dlp (which does not support streamff). Both assumptions
break every time the domain changes — we were chasing domains.

## Decision

**Derive the CDN host from the domain of the matched clip URL — never hardcode a TLD.**

- **Primary:** `_streamff_cdn_url(url)` builds
  `https://cdn.<matched-domain>/<id>.mp4`, taking `<matched-domain>` from the
  domain the clip was actually matched on (`streamff.pro → cdn.streamff.pro`).
  There is **no hardcoded `.one`/`.pro`/`.com`** anywhere, so a future streamff
  domain rotation works with zero code changes. `_download_file` retries a
  transient `ConnectionResetError` twice with short backoff before giving up.
- **Secondary:** `_resolve_streamff_source(url)` scrapes the matched page for the
  real `<source>`/`<video>` src (or an embedded JSON url / any `.mp4`) when the
  derived CDN host is unreachable.
- **yt-dlp:** streamff never falls through to it (unsupported). streamin/streamain
  keep their yt-dlp fallback unchanged.

**Fallback order:** derived `cdn.<matched-domain>/<id>.mp4` → page-scraped source.

## Why this fixes it for good

The durable fix is reading the source the page itself references, so a domain
change no longer requires a code change. The CDN list is only a best-effort
backstop and is derived from the matched domain, not a single frozen host.

## Verification

- `tests/test_downloader.py`: `TestDownloadStreamff` rewritten (was CDN-first);
  added JSON/bare-URL extraction, matched-domain-first CDN fallback,
  dead-host iteration, connection-reset retry, total-failure → None (no yt-dlp),
  and `TestStreamffPatterns` for the regexes. A future domain/scheme change is
  now caught by a failing unit test rather than in production.
- Full suite: **2226 passed**.
- End-to-end: once `download()` returns a path, `poll_goal_clips_job`
  (`__main__.py` ~1368–1399) attaches the keyboard and sets
  `keyboard_attached=True` — the success path is not gated by anything else.


---



# Decision: /elecciones increment 2 — groups image + tile-cache eviction + defensive text split

**Date:** 2026-07-04  
**Author:** Kanté  
**Commit:** 7a0dcfc  
**Status:** Ready for Pirlo review  
**Follows:** `pirlo-elecciones-design.md` B4, Pirlo approve-with-followups on increment 1

---

## Summary

Implements the three follow-ups from Pirlo's increment-1 review plus the deferred groups image (B4):

1. **Groups 2×2 image** — `CHOICES_TYPE=image` now renders a PIL matrix for "Fase de grupos"
2. **Tile-cache disk eviction** — `_evict_tile_cache()` caps `{state_dir}/elecciones_tiles/` at 200 files
3. **asyncio.to_thread documentation** — comments in both renderer docstrings explain the short-lived single-invocation pattern (no background loop, no runaway CPU/RAM)
4. **Defensive line-level text split** — `_split_block_at_lines()` ensures no single message ever exceeds 4090 chars, even if a single user block is oversized

---

## Groups Image Design (B4)

### Architecture

```
Handler (_generate_elecciones_artifact, "grupos" branch, image mode):
  1. client.get_standings()          → list[Standing]   (I/O, on event loop, TTL-cached)
  2. build_group_compositions(...)   → dict[letter → [tla×4]]  (pure, porra/elecciones.py)
  3. asyncio.to_thread(render_groups_matrix, compositions, participants, settings)
                                     → BytesIO | None   (CPU-bound PIL, off event loop)
  4. buf is not None → {"data": bytes}
     else            → text fallback (graceful degradation)
```

### Layout

- Canvas: `(38 + n_users × 84) × (76 + 12 × 82)` px
  - 11 participants → `970 × 1060 px`
- Header row (76 px): circular profile photos + short names (same pattern as knockout image)
- 12 group rows (82 px each): alternating dark rows
  - Left column (38 px): group letter A–L
  - Each participant column (84 px): 2×2 flag grid, centered in cell

### 2×2 Cell Rendering

Teams come from `group_compositions[letter]` in standings position order (1st in top-left, etc.).

| Alpha | Meaning |
|-------|---------|
| 255 | Participant's predicted 1st or 2nd (direct qualifier) |
| 165 | Participant's predicted 3rd (tercero, advances only if best-thirds) |
| 65  | Not picked by this participant (implicitly eliminated) |

---



# Decision: find_goal_clip Empty-JSON Fallback Fix (2026-07-06)

**Date:** 2026-07-06  
**Author:** Kanté (Backend Dev)  
**Status:** ✅ SHIPPED (commit 4766a02)

---

## Summary

`find_goal_clip` never reached the HTML search + `/new/` fallback when Reddit's JSON search endpoint returned HTTP 200 with an empty `children` list (soft-block / datacenter IP pattern). All 5 goals in yesterday's Mexico-England match were notified but received no "Ver gol" button.

---

## Root Cause

In `src/worldcup_bot/reddit/clip_finder.py`, the HTML fallback was gated on `posts is None`:

```python
posts = _fetch_search_posts(scanner, search_url)
if posts is None:               # ← only reached on hard 403 / exception
    ... HTML fallback ...
for post in posts:              # if posts == [], iterates nothing → returns None
    _match_post(...)
```

`_fetch_search_posts` returns:
- `None` on a hard 403 or exception → fallback triggered ✓
- `[]` (empty list) on HTTP 200 with `{"data":{"children":[]}}` → fallback **skipped** ✗

Reddit soft-blocks datacenter IPs by returning HTTP 200 with an empty result set rather than a hard 403. Residential IPs get a hard 403, which correctly triggers the HTML fallback. This explains why clips worked from David's machine but failed for every goal on the server.

---

## The Fix

`src/worldcup_bot/reddit/clip_finder.py` — `find_goal_clip` body replaced:

**Old logic:**
```python
posts = _fetch_search_posts(scanner, search_url)
if posts is None:
    ... HTML fallback → posts = merged ...
for post in posts:
    ...
```

**New logic:**
```python
# 1) Try JSON search results first (None on 403, [] on soft-block, or a list).
json_posts = _fetch_search_posts(scanner, search_url) or []
for post in json_posts:
    media_url = _match_post(...)
    if media_url is not None:
        return media_url          # happy path: returns without HTML fallback

# 2) JSON produced no match (None/empty/non-matching) → always consult HTML search + /new/.
if not json_posts:
    log.info("find_goal_clip: JSON search returned no posts, using HTML search + /new/ listing")
else:
    log.info("find_goal_clip: JSON search had %d post(s) but no match; consulting HTML search + /new/ listing", len(json_posts))
# ... merge + search HTML posts ...
```

Key properties:
- `or []` normalises both `None` and `[]` so they follow the same path.
- JSON match in the happy path returns immediately — HTML fetchers are **not called** (efficiency preserved).
- HTML fallback now runs whenever JSON yields no match, regardless of the reason.
- Two distinct INFO log lines distinguish "no posts at all" (None/empty) from "posts present but none matched" — future server failures are diagnosable from logs without a code change.
- All existing helper functions (`_fetch_search_posts`, `_fetch_html_search_posts`, `_fetch_html_posts`, `_match_post`, `_search_term`) are **unchanged**.

---

## Request-Volume Impact

Today from a residential IP, the JSON endpoint returns a hard 403 → `_fetch_search_posts` returns `None` → `json_posts = []` → HTML fallback already runs on every tick. **This change adds zero extra requests on the current residential-IP path.**

On the server (datacenter IP where JSON returns 200-empty), the HTML fallback was previously never reached. Now it runs — which is exactly the intended behaviour. No extra retries or loops are introduced beyond that.

---

## Tests Added (`tests/test_clip_finder.py`)

New class `TestFindGoalClipFallbackBehavior` — 5 tests:

| Test | Scenario | Assert |
|------|----------|--------|
| `test_empty_json_triggers_html_fallback_and_finds_clip` | **KEY REGRESSION**: `_fetch_search_posts` → `[]` (HTTP 200 soft-block) | HTML fallback consulted; clip URL returned |
| `test_none_json_triggers_html_fallback_and_finds_clip` | `_fetch_search_posts` → `None` (hard 403) | HTML fallback consulted; clip URL returned (existing behaviour preserved) |
| `test_nonempty_nonmatching_json_triggers_html_fallback` | `_fetch_search_posts` → `[decoy]` (no match) | HTML fallback consulted; correct clip URL returned |
| `test_matching_json_post_returned_without_html_fallback` | `_fetch_search_posts` → `[matching_post]` | Clip returned directly; `_fetch_html_search_posts` and `_fetch_html_posts` **not called** |
| `test_no_match_anywhere_returns_none` | All fetchers → `[]` | Returns `None` |

---

## Live Verification — Mexico vs England (5 goals, 2026-07-05)

Ran `find_goal_clip` via real `RedditMatchScanner` (residential IP → JSON 403 → HTML fallback path):

| Score | Scorer | Min | Result |
|-------|--------|-----|--------|
| 0-1 | J. Bellingham | 36' | `https://streamin.link/v/ebeace44` ✓ |
| 0-2 | J. Bellingham | 38' | `https://streamin.link/v/239e855d` ✓ |
| 1-2 | J. Quiñones | 42' | `https://streamin.link/v/7500acaa` ✓ |
| 1-3 | Harry Kane | 60' | `https://streamin.link/v/2a61a014` ✓ |
| 2-3 | R. Jiménez | 69' | `https://streamin.link/v/2945e1a6` ✓ |

All 5 clips found. No regression.

---

## Test Count

- Baseline: **2346**
- After fix: **2351** (+5 new)
- All green ✅

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/reddit/clip_finder.py` | `find_goal_clip`: `posts is None` gate replaced with `or []` + unconditional HTML fallback |
| `tests/test_clip_finder.py` | `TestFindGoalClipFallbackBehavior` — 5 new regression tests |
| `.squad/agents/kante/history.md` | Session entry added |

---

# Decision — FINAL seed-path fix (FINISHED-only dedup invariant)

Author: Nesta (backend, escalation)
Date: 2026-07-04 / 2026-07-06
Re: 3rd revision of the FINAL-announcement fix. Fix-forward on `main`.
Prior rejects: a61757d (Kanté), 615c34e (Cannavaro). Shipped: commit a8b9c5f.
Status: ✅ SHIPPED

## The remaining bug (Pirlo's re-review of 615c34e)

`poll_finished_matches_job` (`src/worldcup_bot/__main__.py`) has TWO code paths
that could write the real-final dedup set `finished_announced`:

1. the normal per-tick loop (Cannavaro fixed this — provisional path), and
2. the first-run / startup **SEED** path.

The seed path was still adding EVERY match over-by-wall-clock
(`kickoff > MATCH_OVER_AGE`, 4 h) into `finished_announced` regardless of status,
including stale `IN_PLAY` and `PAUSED`. Consequences:

- On a restart while football-data is still stuck `IN_PLAY` for a match that
  really ended (the production Australia–Egypt failure mode), the seed marks it
  final-deduped. When the API finally flips to `FINISHED`,
  `new_ids = finished_ids - announced` excludes it and the official 🏁 Final
  recap is **permanently suppressed**.
- `PAUSED` >4h (possibly a resumable suspension) was likewise treated as
  already-handled, suppressing its future official final.

## The fix — the FINISHED-only dedup invariant

**Invariant:** `finished_announced` (the real-final dedup) is populated ONLY for
matches whose `status == "FINISHED"`, at EVERY write site.

Audited every write to `finished_announced` in the finished job and guarded them
all on FINISHED:

- **First-run seed** — CHANGED. Now seeds only genuinely finished matches:
  `seeded = {m.id for m in all_matches if m.status == "FINISHED"}`.
  Non-FINISHED over-by-wall-clock matches (stale `IN_PLAY` / `PAUSED`) are NOT
  seeded — they stay eligible for the later official recap.
- **Main loop `announced.add(...)`** (the None-match guard and the `finally`
  block) — already compliant: both are inside `for match_id in new_ids`, and
  `new_ids ⊆ finished_ids` where `finished_ids = {m.id ... if status ==
  "FINISHED"}`. Added a comment at the `new_ids` definition documenting this.
- Not a write site: `poll_kickoff_job` uses a local `announced` bound to the
  SEPARATE `kickoff_announced` set — untouched.

Non-FINISHED "over" matches are handled by the existing, already-approved normal
path:
- stuck `IN_PLAY` >4h → ⏳ provisional notice tracked in the SEPARATE persisted
  `provisional_announced` set (never consumes `finished_announced`);
- `PAUSED` → excluded from the provisional path, announced only when it
  legitimately reaches `FINISHED`.

When the API eventually reports `FINISHED`, the official recap fires with the
API-confirmed score (self-correcting), clears the provisional marker, and the
existing VAR-correction watch still handles genuine post-final score changes
within its window.

## Restart / no-double-announce guarantees

- (over + `IN_PLAY` at startup → later `FINISHED`): NOT seeded; provisional may
  fire once (deduped via persisted `provisional_announced`); official `FINISHED`
  fires exactly once.
- (over + `PAUSED` at startup → later `FINISHED`): NOT seeded; no provisional;
  official `FINISHED` fires exactly once.
- (genuinely `FINISHED` at startup): seeded on first run, never re-announced.

## Tests

`tests/test_poll_finished_job.py`:
- `TestFirstRunSeedWithAge` — rewritten to assert FINISHED-only seeding (stale
  `IN_PLAY` and `PAUSED` NOT in `finished_announced`; disk persists only the
  FINISHED id).
- `TestStaleLaterFlip` — rewritten: an unseeded stale match that flips to
  `FINISHED` now DOES get the official recap.
- Replaced `test_stale_inplay_seeded_on_first_run_not_announced` with
  `test_stale_inplay_not_seeded_on_first_run` plus three restart regressions:
  IN_PLAY→FINISHED, PAUSED→FINISHED, and genuinely-FINISHED-seeded-not-
  reannounced — each asserting exactly-once official announcement.

Full suite `.venv\Scripts\python.exe -m pytest -q`: **2231 passed** (~64 s).

`_apply_alpha(img, alpha)` scales the existing RGBA alpha channel (`point(lambda x: x*alpha//255)`), preserving antialiasing.  TLA text fallback when flag tile is unavailable (non-standard ISO codes like GBENG).

### Terceros Strip — Not Added

Considered adding a strip below the 12 group rows showing each participant's tercero picks. Decided against it:
- The intermediate-alpha (165) 2×2 rendering already makes tercero picks clearly visible
- Fitting 12 tercero flags per participant into an 84 px column is not clean at any reasonable flag size
- Can be revisited as a separate increment if owner requests it

---

## Tile-Cache Eviction

`_evict_tile_cache(tile_dir, max_files=200)`:
- Globs `flag_*.png` in the cache dir
- If count > max_files: sorts by mtime (oldest first), unlinks surplus
- Called at the start of both `_render` (knockout) and `_render_groups` (grupos)
- No background thread — runs inline, best-effort (exceptions swallowed)
- 200-file cap is generous: the WC has 48 teams × a few sizes = ~50–100 unique tiles

---

## asyncio.to_thread Pattern

Both `render_knockout_matrix` and `render_groups_matrix` docstrings now state:

> "Always call via `asyncio.to_thread` to avoid blocking the Telegram event loop. It is a short-lived, single invocation — not a background loop or persistent thread — so it carries no risk of runaway CPU/RAM usage."

API calls (`get_standings`, `get_all_matches`, `get_stage_results`) are I/O-bound and stay on the event loop (they're behind the TTL cache, typically returning instantly on cache hits). Only the PIL rendering is offloaded.

---

## Defensive Line-Level Split

`_split_block_at_lines(block, max_len)` in `porra/elecciones.py`:
- Splits at `\n` boundaries when a block exceeds `_HARD_LIMIT = 4090`
- A single line > max_len is returned as-is (cannot split without breaking the content)
- `_split_messages` now pre-processes every block through this function before the main greedy threshold splitting

This guarantees no Telegram message exceeds 4090 chars even in edge cases (many participants with long flag sequences).

---

## Tests

18 new tests (97 total in `test_elecciones.py`):

| Class | Tests | What |
|-------|-------|------|
| `TestBuildGroupCompositions` | 4 | dict from standings, position order, empty, no-group |
| `TestDefensiveLineSplit` | 5 | short unchanged, multi-line split, single oversized line, no-message-exceeds, within-threshold |
| `TestGroupsImage` | 5 | PNG produced, None on exception, importable, image-mode sends photo (not text), render-failure → text fallback |
| `TestTileCacheEviction` | 4 | removes oldest, keeps newest, no-op under limit, no-op missing dir |

**2328 tests total, 0 failures.**

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/porra/elecciones.py` | `_HARD_LIMIT`, `_split_block_at_lines`, updated `_split_messages`, `build_group_compositions` |
| `src/worldcup_bot/bot/elecciones_image.py` | `_MAX_TILE_CACHE_FILES`, groups layout constants, `_evict_tile_cache`, `_apply_alpha`, call `_evict_tile_cache` in `_render`, `render_groups_matrix`, `_render_groups` |
| `src/worldcup_bot/bot/handlers.py` | Replace grupos-image fallback with actual image rendering; asyncio.to_thread comment |
| `tests/test_elecciones.py` | 4 new test classes (18 new tests) |


---



# Decision: /elecciones hourglass UX

**Author:** Kanté  
**Date:** 2026-07-04  
**Commit:** `8922308`  
**Status:** pending-review (Pirlo)

## Problem

When the user tapped a phase button in `/elecciones`, the bot immediately removed the keyboard (via `edit_message_reply_markup`) and sent the result as a separate message. For image mode this created a bad experience: the keyboard disappeared but nothing happened for several seconds while PIL was rendering. There was no feedback that work was in progress, and errors left silent failures.

## Decision

Implement a **tap → hourglass → delete + send** flow:

1. `query.edit_message_text("⏳ Generando…", reply_markup=None)` — edits the phase-selector message in-place to show a spinner and atomically removes the keyboard. Captures `placeholder_id = query.message.message_id`.
2. Generate the artifact (cache hit or fresh render, inside a `try/except`).
3. **Success:** `context.bot.delete_message(chat_id, placeholder_id)` then `send_photo` (image) or `send_message` (text). Text mode is also delete-then-send for consistency (the ⏳ flash is negligible).
4. **Failure (exception):** `context.bot.edit_message_text(chat_id, placeholder_id, "❌ Error…")` — placeholder becomes the error notice; no dangling hourglass.

## Implementation

- `_serve_elecciones` replaced by `_serve_after_placeholder(context, chat_id, placeholder_id, artifact)`.
- `cmd_elecciones_callback` refactored to the four-step flow above.
- All defensive paths (missing participants, invalid callback data) also edit the placeholder rather than sending a new message.

## Tests

- `test_removes_keyboard` — asserts `query.edit_message_text("⏳ Generando…", reply_markup=None)`.
- `test_sends_text_result_for_grupos` / `test_cache_hit_serves_without_regeneration` / `test_cache_invalidated_on_mtime_change` — assert `context.bot.delete_message` then `context.bot.send_message`.
- `test_grupos_image_mode_sends_photo` — assert delete + `send_photo`.
- `test_grupos_image_mode_falls_back_to_text_on_render_failure` — assert delete + `send_message`.
- `test_generation_failure_edits_placeholder_to_error` (new) — patches `_generate_elecciones_artifact` to raise; asserts `context.bot.edit_message_text` called with `❌` text and no delete/send.

Full suite: 2324 passed, 8 pre-existing failures (unrelated).


---



# Decision: /elecciones command implementation

**Date:** 2026-07-04  
**Author:** Kanté  
**Commit:** 38e00b2  
**Status:** Ready for Pirlo review

---

## Summary

Implemented the `/elecciones` command per Pirlo's locked design (`pirlo-elecciones-design.md`). Shows tournament-phase predictions per participant, via an inline keyboard phase selector, with text and image rendering modes.

---

## Files Added / Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/porra/elecciones.py` | NEW — pure data helpers |
| `src/worldcup_bot/bot/elecciones_image.py` | NEW — PIL knockout matrix renderer |
| `src/worldcup_bot/config.py` | `choices_type` field + env var |
| `src/worldcup_bot/bot/handlers.py` | 8 new functions/constants |
| `src/worldcup_bot/__main__.py` | register CommandHandler + CallbackQueryHandler |
| `docker-compose.yml` | `CHOICES_TYPE: "${CHOICES_TYPE:-text}"` |
| `docker-compose.local.yml` | same |
| `.env.example` | `# CHOICES_TYPE=text` |
| `tests/test_elecciones.py` | NEW — 79 tests |

---

## Architecture

### Phase keyboard + filtering

`cmd_elecciones` calls `active_phases(participants)` from `porra/elecciones.py`. A phase is included only if ≥1 participant has ≥1 non-`**` pick:
- grupos: any non-`**` in any group position across all users
- knockout: any non-`**` in the list for that round

With current predictions.yml (example data), quarter_finals / semi_finals / final have empty pick lists → those buttons are absent from the keyboard. Callback data: `elecciones|<yaml_key>`; pattern: `^elecciones\|`.

### Text renderers

Both in `porra/elecciones.py`; accept `team_flag_fn` arg for testability (no I/O).

- **Knockout** (`build_knockout_text`): one block per user, rows = ties in round order. Picks via `_pick_for_tie` (wraps `_side_for` from `porra/camps.py`). No-pick → `❓`. `**` in list → `❓`. TERCEROS derived via `best_qualifying_thirds` from `porra/scoring.py` for grupos phase.
- **Groups** (`build_groups_text`): one block per user, one line per group. Format: `A: 🇲🇽 🇰🇷 | 3º🇨🇿`. `**` rendered inline.
- **Splitting**: `_split_messages` greedily fills up to 3800 chars, splitting at `\n\n👤` boundaries. Single block >3800 stays as-is (can't split within a user block). Part headers `(1/N)\n` prepended when >1 message.

### Knockout image

`bot/elecciones_image.py` — PIL matrix: rows = ties from API bracket, columns = participants (yaml order) with circular profile-photo headers (initials fallback), flag cells, RESULTS column (blank until results exist). Reuses `podium_image.py` helpers (`_circular_crop`, `_fetch_tile`, `_placeholder_tile`, `_font`). Flag tiles fetched from twemoji CDN; cached on disk in `{state_dir}/elecciones_tiles/` (bounded). Non-2-char ISO codes (GBENG/GBSCT/GBWLS) → `_flag_url` returns `None` → cell shows TLA text.

**Groups image NOT in this increment.** In image mode, tapping grupos transparently falls back to the grupos text renderer (logged at INFO level). No user-facing error.

### Caching

Cache lives in `bot_data["elecciones_cache"]` — dict keyed by `(yaml_key, mtime, results_hash)`. At most 6 entries (one per phase). On tap: compute key → cache hit → serve immediately; miss → regenerate INLINE in handler (PTB event loop, no background thread) → store → serve. Eviction: stale entries for same phase deleted when new entry added; hard cap via deleting oldest when >6. `results_hash` = MD5 of sorted stage results (home_tla, away_tla, score) — artifact regenerates automatically when results change, not just when predictions.yml changes.

### CHOICES_TYPE wiring

- `config.py` `Settings`: `choices_type: str = "text"`
- `load_settings()`: `choices_type=os.getenv("CHOICES_TYPE", "text")`
- `docker-compose.yml` + `docker-compose.local.yml`: `CHOICES_TYPE: "${CHOICES_TYPE:-text}"`
- `.env.example`: `# CHOICES_TYPE=text  # Options: text, image`

---

## Tests (2310 total, 0 failures)

79 new tests across 11 classes in `tests/test_elecciones.py`:
- `TestPhaseLabel` — label mapping for all 6 phases
- `TestHasPicks` — grupos/knockout has-picks logic with wildcards
- `TestActivePhases` — keyboard buttons present/absent per data
- `TestPickForTie` — side-for tie + no-pick → ❓
- `TestBuildKnockoutText` — per-user blocks, ❓ on no-pick, multiple users
- `TestBuildGroupsText` — per-user groups, terceros shown, ** handling
- `TestSplitMessages` — threshold splitting, part numbers, single large block
- `TestChoicesTypeConfig` — default text, image from env
- `TestCmdElecciones` — keyboard present, phases filtered, error on no participants
- `TestCmdEleccionesCallback` — keyboard removed, text served, cache hit/miss/invalidation
- `TestEleccionesCache` — stale eviction, coexistence, bounded to 6, results-version invalidation
- `TestEleccionesImageImport` — importability, _flag_url, render returns BytesIO
- `TestStartHelpText` — /elecciones in /start help text

---

## Gotchas for next session

- `InlineKeyboardButton` was not in handlers.py imports — added.
- `hashlib`, `io`, `os` not in handlers.py stdlib imports — added.
- Lazy imports inside `_generate_elecciones_artifact` → patch target for tests = `worldcup_bot.porra.elecciones.*`.
- Twemoji `_flag_url` returns `None` for non-2-char ISO codes (England/Scotland/Wales) → image cells show TLA instead of flag.
- `_split_messages` threshold is soft — a single user block > 3800 chars is NOT split; it's a "best-effort" approach to keep messages under 4096.


---



# Decision: Production Bug Fixes — Keyboard Never Attached & FINAL 9h Late

**Date:** 2026-07-04  
**Author:** Kanté (Backend Developer)  
**Commit:** `a61757d` (branch: `main`)  
**Tests:** 2209 passed, 0 failures

---

## Bug #1 — "Ver gol" inline keyboard never attached (all goals, 2026-07-03)

### Symptom
Of all goals scored on 2026-07-03, none had the "Ver gol" inline keyboard button added to the goal message — clips were found and downloaded, but the button was permanently absent.

### Root Cause
`poll_goal_clips_job` sets `entry["status"] = "ready"` **before** calling `edit_message_reply_markup` (intentional: ensures `_backfill_scorer_in_clip_store` sees the completed entry). If that call then fails (e.g. a Telegram API blip), there was **no retry path**:
- The function's early-return guard (`if not searching: return`) fires before any retry code when there are no `status="searching"` entries.
- The main loop only processes `status="searching"` entries — `"ready"` entries are never revisited.
- For goals with a known scorer, `_backfill_scorer_in_clip_store` skips them too (`scorer is not None → continue`).

So a single Telegram API blip on 2026-07-03 permanently hid the button for every goal.

### Fix
**`src/worldcup_bot/reddit/clip_store.py`**
- Added `"keyboard_attached": False` to `add_entry` entry schema.

**`src/worldcup_bot/__main__.py` — `poll_goal_clips_job`**
- Set `entry["keyboard_attached"] = True` after a successful `edit_message_reply_markup`.
- Compute `pending_retry` (entries with `status="ready"` and `keyboard_attached` falsy) **before** the early-return guard, so retry runs even when there is no searching work.
- After the main searching loop, iterate `pending_retry` and re-attempt `edit_message_reply_markup` every tick until success (or until the entry is pruned after 7 days by `prune_old_entries`). Set `changed=True` on success so `save_clips` persists the update.

### Gotcha to Remember
The early-return `if not searching: return` was **above** the retry loop — the retry was dead code whenever the bot had no clips currently being searched. Always place `pending_retry` computation **before** any early-return guard.

---

## Bug #2 — Australia-Egypt FINAL announced ~9h late (match ended 22:30, announced 08:00)

### Symptom
Australia vs Egypt ended ~22:30 CEST on 2026-07-03. The bot announced the FINAL result at ~08:00 on 2026-07-04 — roughly 9.5h late.

### Root Cause
`poll_finished_matches_job` computed:
```python
finished_ids = {m.id for m in all_matches if m.status == "FINISHED"}
```
The football-data.org **free-tier API** delayed updating Australia-Egypt from `IN_PLAY` to `FINISHED` for ~9.5h (match ended ~20:30 UTC, API reported FINISHED at ~06:00 UTC next day). The bot polled correctly throughout but found nothing to announce because the API status never changed during that window. There was no wall-clock fallback.

The existing `_match_is_over(m, now_utc)` predicate (kickoff >4h ago) was already used by `poll_goals_job` to evict matches from `live_scores`, and by the seed pass to silently handle stale matches on startup — but the **main announcement loop** in `poll_finished_matches_job` never used it.

### Fix
**`src/worldcup_bot/__main__.py` — `poll_finished_matches_job` main loop**

After the seed-pass returns, compute:
```python
now_utc = datetime.now(timezone.utc)
finished_ids = {m.id for m in all_matches if m.status == "FINISHED"}
stale_live_ids = {
    m.id for m in all_matches
    if _match_is_over(m, now_utc) and m.status in ("IN_PLAY", "PAUSED")
}
new_ids = (finished_ids | stale_live_ids) - announced
```

`_match_is_over` returns True when kickoff was >4h ago (`MATCH_OVER_AGE`). This caps worst-case announcement delay at 4h from kickoff regardless of API lag. For a typical 90-min match (e.g. kickoff 18:00 UTC, FT 20:30 UTC), the wall-clock fallback fires at 22:00 UTC — ~1.5h after FT.

Only `IN_PLAY` and `PAUSED` statuses trigger the fallback — `TIMED`/`SCHEDULED`/`POSTPONED` are excluded to avoid false positives.

### Seed pass consistency
The first-run seed pass already silently seeds stale `IN_PLAY` matches (kickoff >4h ago) via the same `_match_is_over` predicate, so after a restart those matches are already in `announced` and won't be re-announced.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/__main__.py` | Bug #1: `pending_retry` guard + retry loop; Bug #2: `stale_live_ids` wall-clock fallback |
| `src/worldcup_bot/reddit/clip_store.py` | Bug #1: `keyboard_attached: False` added to entry schema |
| `tests/test_poll_goal_clips_job.py` | 8 regression tests (`TestKeyboardRetry`) |
| `tests/test_poll_finished_job.py` | 6 regression tests (`TestWallClockFallback`) |


---



# Decision: Container Memory-Limit Safeguard

**Date:** 2026-07-04  
**Author:** Maldini (DevOps)  
**Status:** Pending owner confirmation of MiB value (not committed/pushed)

## Context

The LXC hosting the bot (2 GB RAM, also running Dockge) hit 100% RAM. After restart the container idles at ~133 MiB. Root-cause (app memory leak) is being audited by Kanté separately. This is a DevOps safety net so the container can never exhaust the whole LXC again, independent of any app fix.

## Decision

Add `mem_limit` and `mem_reservation` to `docker-compose.yml` and `docker-compose.local.yml`.

### Key chosen: `mem_limit` (top-level service key)

`deploy.resources.limits.memory` is the Compose Spec / Swarm-style key. On plain `docker compose up` (non-swarm), that key has been historically ignored — Docker Compose only honours it in swarm mode or with `--compat`. The top-level `mem_limit:` key is always honoured by `docker compose up` on any Compose version, no flags required. This is the reliable, version-agnostic choice.

### Values

| Key | Value | Bytes |
|-----|-------|-------|
| `mem_limit` | `512m` | 536,870,912 |
| `mem_reservation` | `256m` | 268,435,456 |

**Justification:**
- Idle baseline: ~133 MiB → `512m` is ~3.85× headroom — enough for daily image generation (gpt-image-2 decoding), live-goal bursts, and Python GC pressure simultaneously.
- Leaves ~1.5 GB for Dockge + LXC OS overhead (well within the 2 GB budget).
- `mem_reservation: 256m` is a soft floor (scheduler hint), not enforced — it signals to the kernel that 256 MiB should be prioritised for this container, but it won't kill at that boundary.
- If the owner wants tighter protection: `384m` is the minimum safe option. If burst headroom is a concern: `768m` is the upper end before eating into Dockge's budget.

### How to change the value (one liner on the host)

```bash
sed -i 's/mem_limit: 512m/mem_limit: 768m/' docker-compose.yml
```
Or simply edit the `mem_limit:` and `mem_reservation:` lines directly in both compose files.

## Validation

`docker compose -f docker-compose.yml config --quiet` → exit 0  
`docker compose -f docker-compose.local.yml config --quiet` → exit 0  
Resolved bytes confirmed: `mem_limit: "536870912"`, `mem_reservation: "268435456"` ✓

## Files changed (not committed)

- `docker-compose.yml` — added `mem_limit: 512m` + `mem_reservation: 256m`
- `docker-compose.local.yml` — same, kept consistent

## Related

- `restart: unless-stopped` already present in both files — ensures auto-restart after a kernel OOM-kill (defense in depth while Kanté audits the leak).
- Kanté owns the app-level fix; this PR is infrastructure-only.


---

# Nesta — /elecciones increment 2 revision (fix-forward on `main`)

Owned the revision after Pirlo REJECTED Kanté's `30919a7`. Reviewer-gate lockout:
Kanté could not revise, so I took it. Fix-forward on `main`.

## What I fixed

### BLOCKER 1 — cache serving stale "unavailable" bracket
- `_elecciones_results_version` (handlers.py) now hashes the **scheduled tie
  identity** from `get_all_matches()` (stage pairings) PLUS finished winners — not
  just finished results. The cache key invalidates as soon as ties are scheduled
  or change, so a "cuadro no disponible" artifact is never re-served once the
  bracket appears.
- Defence-in-depth: transient artifacts (no-ties message, API-error messages, the
  groups-image API-failure text fallback) are tagged `cacheable: False` and the
  callback only stores `artifact.get("cacheable", True)`.
- No extra API calls: `get_stage_results` already resolves via `get_all_matches`
  (TTL-cached 60 s).

### BLOCKER 2 — messages could exceed Telegram's 4096 limit
- `porra/elecciones.py` `_split_messages` rewritten: `block_budget = 4096 −
  PREFIX_RESERVE(16) − (len(header)+2)`. Every block is pre-split to that budget;
  packing tracks `blocks_in_current` so a header+block or two blocks are never
  forced past the limit. Result: every emitted part (incl. header + `(i/n)` prefix)
  is provably ≤4096.
- `_split_block_at_lines` now hard-splits a single overlong line at a character
  boundary (previously passed through unsplit).

### FLAG 404 fix
- `_TWEMOJI_BASE` changed from the npm path (404 for every flag) to the
  GitHub-hosted `cdn.jsdelivr.net/gh/twitter/twemoji@v14.0.2/assets/72x72`
  (verified 200). Restores flags for all standard teams in knockout + groups images.

### ENG/SCO/WAL flags
- `_flag_url` extended: 5-char ISO starting "GB" → tag-sequence filename
  `1f3f4-<tags>-e007f.png`. GBNIR excluded (no asset) → None → TLA-text fallback.
  England/Scotland/Wales URLs verified 200.

### NON-BLOCKING 1 — groups image on API failure
- Standings-API failure now falls back to the TEXT renderer (no blank grid), marked
  non-cacheable so a real image regenerates when the API recovers.

### NON-BLOCKING 2 — hourglass delete failure
- `_serve_after_placeholder`: on delete failure, best-effort edit the placeholder to
  a neutral notice ("📊 Predicciones 👇") so no stale ⏳ remains; result still sent.

## Tests
14 new/updated tests in `tests/test_elecciones.py`:
- Cache: `_elecciones_results_version` invalidation when ties scheduled / winner
  finishes / grupos=none; full-callback regression (no-ties → ties appear → bracket
  regenerated, unavailable artifact not cached).
- Split: many-users, one enormous single line, header+near-limit block — every part
  ≤4096; single overlong line is hard-split.
- Flags: base is gh path; ESP resolves; ENG/SCO/WAL tag-sequences; NIR → None/text;
  ENG tile fetch (mock 200) renders; NIR fetch skipped.
- Fallbacks: groups-image API failure → text (not cached); delete-failure →
  neutral edit + result still sent.

Full suite: **2346 passed** (2332 baseline + 14), 0 failures.

## Scope
- Did NOT touch docker-compose (CHOICES_TYPE already wired). No unrelated changes.
- Files changed: `src/worldcup_bot/porra/elecciones.py`,
  `src/worldcup_bot/bot/elecciones_image.py`, `src/worldcup_bot/bot/handlers.py`,
  `tests/test_elecciones.py`.

Back to Pirlo for re-review. Lockout: next reviser (if rejected) can be neither
Kanté nor Nesta.


---

# Decision — FINAL seed-path fix (FINISHED-only dedup invariant)

Author: Nesta (backend, escalation)
Date: 2026-07-04
Re: 3rd revision of the FINAL-announcement fix. Fix-forward on `main`.
Prior rejects: a61757d (Kanté), 615c34e (Cannavaro). Requested by: danielrdon.

## The remaining bug (Pirlo's re-review of 615c34e)

`poll_finished_matches_job` (`src/worldcup_bot/__main__.py`) has TWO code paths
that could write the real-final dedup set `finished_announced`:

1. the normal per-tick loop (Cannavaro fixed this — provisional path), and
2. the first-run / startup **SEED** path.

The seed path was still adding EVERY match over-by-wall-clock
(`kickoff > MATCH_OVER_AGE`, 4 h) into `finished_announced` regardless of status,
including stale `IN_PLAY` and `PAUSED`. Consequences:

- On a restart while football-data is still stuck `IN_PLAY` for a match that
  really ended (the production Australia–Egypt failure mode), the seed marks it
  final-deduped. When the API finally flips to `FINISHED`,
  `new_ids = finished_ids - announced` excludes it and the official 🏁 Final
  recap is **permanently suppressed**.
- `PAUSED` >4h (possibly a resumable suspension) was likewise treated as
  already-handled, suppressing its future official final.

## The fix — the FINISHED-only dedup invariant

**Invariant:** `finished_announced` (the real-final dedup) is populated ONLY for
matches whose `status == "FINISHED"`, at EVERY write site.

Audited every write to `finished_announced` in the finished job and guarded them
all on FINISHED:

- **First-run seed** — CHANGED. Now seeds only genuinely finished matches:
  `seeded = {m.id for m in all_matches if m.status == "FINISHED"}`.
  Non-FINISHED over-by-wall-clock matches (stale `IN_PLAY` / `PAUSED`) are NOT
  seeded — they stay eligible for the later official recap.
- **Main loop `announced.add(...)`** (the None-match guard and the `finally`
  block) — already compliant: both are inside `for match_id in new_ids`, and
  `new_ids ⊆ finished_ids` where `finished_ids = {m.id ... if status ==
  "FINISHED"}`. Added a comment at the `new_ids` definition documenting this.
- Not a write site: `poll_kickoff_job` uses a local `announced` bound to the
  SEPARATE `kickoff_announced` set — untouched.

Non-FINISHED "over" matches are handled by the existing, already-approved normal
path:
- stuck `IN_PLAY` >4h → ⏳ provisional notice tracked in the SEPARATE persisted
  `provisional_announced` set (never consumes `finished_announced`);
- `PAUSED` → excluded from the provisional path, announced only when it
  legitimately reaches `FINISHED`.

When the API eventually reports `FINISHED`, the official recap fires with the
API-confirmed score (self-correcting), clears the provisional marker, and the
existing VAR-correction watch still handles genuine post-final score changes
within its window.

## Restart / no-double-announce guarantees

- (over + `IN_PLAY` at startup → later `FINISHED`): NOT seeded; provisional may
  fire once (deduped via persisted `provisional_announced`); official `FINISHED`
  fires exactly once.
- (over + `PAUSED` at startup → later `FINISHED`): NOT seeded; no provisional;
  official `FINISHED` fires exactly once.
- (genuinely `FINISHED` at startup): seeded on first run, never re-announced.

## Tests

`tests/test_poll_finished_job.py`:
- `TestFirstRunSeedWithAge` — rewritten to assert FINISHED-only seeding (stale
  `IN_PLAY` and `PAUSED` NOT in `finished_announced`; disk persists only the
  FINISHED id).
- `TestStaleLaterFlip` — rewritten: an unseeded stale match that flips to
  `FINISHED` now DOES get the official recap.
- Replaced `test_stale_inplay_seeded_on_first_run_not_announced` with
  `test_stale_inplay_not_seeded_on_first_run` plus three restart regressions:
  IN_PLAY→FINISHED, PAUSED→FINISHED, and genuinely-FINISHED-seeded-not-
  reannounced — each asserting exactly-once official announcement.

Full suite `.venv\Scripts\python.exe -m pytest -q`: **2231 passed** (~64 s).
`docker-compose*.yml` untouched.


---

# Design Proposal v2: `/elecciones` command

**Date:** 2026-07-04 (rev2 — owner refinements applied)
**Author:** Pirlo (Tech Lead)
**Status:** 📋 DRAFT — awaiting owner sign-off
**Requested by:** danielrdon

---

## Confirmed data model

### Groups (`data/predictions.template.yml` + `porra/predictions.py` + `porra/scoring.py`)

```yaml
groups:
  A: ["MEX", "KOR", "CZE"]   # [1st, 2nd, 3rd] — exactly QUALIFY_PER_GROUP=3 entries
  B: ["CAN", "SUI", "**"]    # "**" = wildcard/no-pick
  ...                         # groups A–L, mandatory
```

- Each participant predicts TOP-3 in finishing order per group.
- Positions 1 and 2 = **direct qualifiers** (always advance, order irrelevant for scoring).
- Position 3 = **tercero** — advances ONLY if among the 8 best third-placed teams.
- DIRECT_QUALIFY = 2, QUALIFY_PER_GROUP = 3 (defined in `scoring.py`).

### ⚠️ TERCEROS — CRITICAL FINDING

**There is NO explicit "terceros: [8 TLAs]" field** in the current YAML or loader.
The 8 qualifying third-placed teams are computed **at scoring time** by `best_qualifying_thirds()`
in `scoring.py`, from live API standings — NOT predicted by participants.

Each participant therefore has exactly **12 third-place picks** (one per group, the 3rd entry per group).
Which 8 of those 12 actually qualify is a **tournament outcome**, not a participant pick.

**Consequence for `/elecciones` GRUPOS display:**
- We CAN show each person's 3rd-place pick per group (it's in the data).
- We CAN annotate which of those 3rd-place picks are among the 8 qualifying thirds (from live API),
  once that's known.
- We CANNOT show a "picked 8 terceros" matrix column — no such data exists.
- **Open question D.1** below: does the owner want a new `terceros` YAML field, or is the current
  model (inferred from the 3rd pick per group) sufficient?

### Knockout (`predictions.template.yml`)

```yaml
knockout:
  round_of_32:   [16 TLAs]   # 16 teams predicted to ADVANCE from round of 32
  round_of_16:   [8 TLAs]
  quarter_finals:[4 TLAs]
  semi_finals:   [2 TLAs]
  final:         [1 TLA]
```

Flat lists. Tie pairings come from the football-data.org API bracket.
`camps.py:_side_for()` already resolves "which team did this person pick for this tie" — reusable.

---

## A. Phase Keyboard

### Spanish labels

| YAML key | Button label |
|---|---|
| `grupos` | Fase de grupos |
| `round_of_32` | Dieciseisavos |
| `round_of_16` | Octavos de Final |
| `quarter_finals` | Cuartos de Final |
| `semi_finals` | Semifinales |
| `final` | La Final |

Layout (2 per row, only phases with ≥1 non-`**` pick shown):
```
[ Fase de grupos ]  [ Dieciseisavos  ]
[ Octavos de Final] [Cuartos de Final]
[  Semifinales    ] [    La Final    ]
```

Callback scheme: `elecciones|<yaml_key>` → pattern `^elecciones\|`

"Phase has picks" check:
- grupos: `any(t != "**" for p in participants.values() for v in p["groups"].values() for t in v)`
- knockout: `any(any(t != "**" for t in p["knockout"].get(key, [])) for p in participants.values())`

---

## B. Display Options

### ── FRAMING ──────────────────────────────────────────────────────────────────

The owner's constraint: **per-user vertical readability, mobile-first**.

| Mode | How per-user vertical is satisfied |
|---|---|
| `CHOICES_TYPE=image` | Each **column** = one user. Read a column top-to-bottom to see all their picks. Wide image → pinch-zoom on mobile. |
| `CHOICES_TYPE=text` | Each **block** = one user. Stacked vertically. Each pick on its own line. Native mobile scroll. |

---

## B1. KNOCKOUT phases — TEXT (primary layout: per-user vertical blocks)

The API bracket gives tie pairings. For each user, one line per tie:

```
🏆 DIECISEISAVOS — ¿Quién pasa?

👤 DavidR
  🇨🇦·🇿🇦  →  🇨🇦
  🇧🇷·🇯🇵  →  🇧🇷
  🇩🇪·🇵🇾  →  🇩🇪
  🇳🇱·🇲🇦  →  🇳🇱
  🇨🇮·🇳🇴  →  ❓
  🇫🇷·🇸🇪  →  🇫🇷
  🇲🇽·🇪🇨  →  🇲🇽
  🇬🇧·🇨🇩  →  🇬🇧
  🇦🇷·🇨🇭  →  🇦🇷
  🇺🇸·🇰🇷  →  🇺🇸
  🇧🇪·🇵🇹  →  🇧🇪
  🇪🇸·🇨🇵🇻 →  🇪🇸
  🇮🇷·🇳🇿  →  ❓
  🇨🇴·🇺🇿🇧 →  🇨🇴
  🇦🇱🇬·🇯🇴 →  🇦🇱🇬
  🏴󠁧󠁢󠁳󠁣󠁴󠁿·🇭🇦 →  🏴󠁧󠁢󠁳󠁣󠁴󠁿

👤 Victor
  🇨🇦·🇿🇦  →  🇨🇦
  🇧🇷·🇯🇵  →  🇧🇷
  [... 16 lines ...]

👤 Cris
  [... 16 lines ...]
```

**Char-count estimate (flags-only compact format):**
- Header: ~40 chars
- Per-user: "👤 Name\n" (~15 chars) + 16 × "  🇽🇽·🇽🇽  →  🇽🇽\n" (~18 chars) = ~303 chars
- 11 users × 303 = ~3333 chars + header = **~3373 chars → fits in 4096 ✅**

If team names added ("  🇨🇦 CAN · 🇿🇦 RSA → 🇨🇦"): ~30 chars/line → ~3850 chars total. Still fits.
If full names ("🇨🇦 Canadá · 🇿🇦 Sudáfrica → 🇨🇦"): ~45 chars/line → ~5450 chars → **exceeds 4096**.

**Strategy:** use flags + TLA abbreviations (not full names). Fits in one message for ≤11 participants.
For 15+ participants (>4096 chars): split into 2 messages (first ~7 users, then remainder).

**Alternative secondary layout — "by tie"** (for reference):
```
🇨🇦 CAN vs 🇿🇦 RSA
  🇨🇦 (9): DavidR, Victor, Cris, Ana, Rafa, Manu, Pau, Javi, Laia
  🇿🇦 (2): María, Toni
```
This answers "who agrees per tie" but loses per-user readability. Secondary option only.

---

## B2. KNOCKOUT phases — IMAGE (matrix, exact reference replication)

```
╔══════════════════╦══════╦══════╦══════╦══════╦══════╦══════╦══════╦══════╦══════╦══════╦══════╦════════╗
║  DIECISEISAVOS   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║  👤   ║ RESULT ║
║                  ║ Dani ║ Vic  ║ Cris ║ Ana  ║ Rafa ║ Manu ║ Pau  ║ Javi ║ Laia ║ Mar  ║ Toni ║        ║
╠══════════════════╬══════╬══════╬══════╬══════╬══════╬══════╬══════╬══════╬══════╬══════╬══════╬════════╣
║ 🇨🇦 CAN vs 🇿🇦 RSA ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇨🇦   ║  🇿🇦   ║  🇿🇦   ║   🇨🇦   ║
║ 🇧🇷 BRA vs 🇯🇵 JPN ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇧🇷   ║  🇯🇵   ║   🇧🇷   ║
║ 🇩🇪 GER vs 🇵🇾 PAR ║  🇩🇪   ║  🇩🇪   ║  🇩🇪   ║  🇩🇪   ║  🇩🇪   ║  🇩🇪   ║  🇩🇪   ║  🇩🇪   ║  ❓   ║  🇵🇾   ║  🇩🇪   ║   🇩🇪   ║
║  ...             ║      ║      ║      ║      ║      ║      ║      ║      ║      ║      ║      ║        ║
╚══════════════════╩══════╩══════╩══════╩══════╩══════╩══════╩══════╩══════╩══════╩══════╩══════╩════════╝
```

Header row: circular profile photos (from `{photo_base_url}/{username}.png`) or initials placeholder.
Alternating white/light-grey row bands. Dark navy header. Flag circles in cells.
Result column initially blank, fills as matches are played.

Canvas for 16 ties × 11 people ≈ 1250×1050px. 12 participant columns → scale to ~1400px.

**Read vertically on mobile:** pinch-zoom → scroll down the user's column = all their choices.

---

## B3. GRUPOS phase — TEXT (per-user vertical blocks)

Since there is NO explicit terceros selection in the current data model, "3rd pick" = the 3rd
entry in each group (the team predicted to finish 3rd). It may qualify among the 8 best thirds.

**Compact format (flags + single-letter group key):**

```
📋 FASE DE GRUPOS — Predicciones

👤 DavidR
  A: 🇲🇽 🇰🇷 | 3º🇨🇿
  B: 🇨🇭 🇨🇦 | 3º🇶🇦
  C: 🏴󠁧󠁢󠁳󠁣󠁴󠁿 🇲🇦 | 3º🇧🇷
  D: 🇺🇸 🇦🇺 | 3º🇹🇷
  E: 🇩🇪 🇨🇮 | 3º🇪🇨
  F: 🇸🇪 🇯🇵 | 3º🇳🇱
  G: 🇪🇬 🇧🇪 | 3º🇮🇷
  H: 🇨🇻 🇸🇦 | 3º🇪🇸
  I: 🇫🇷 🇮🇶 | 3º🇳🇴
  J: 🇩🇿 🇦🇷 | 3º🇯🇴
  K: 🇨🇩 🇨🇴 | 3º🇵🇹
  L: 🇬🇧 🇬🇭 | 3º🇭🇷

👤 Victor
  A: 🇲🇽 🇰🇷 | 3º🇨🇿
  B: 🇨🇦 🇨🇭 | 3º🇧🇮
  [... 12 lines ...]

[... remaining 9 users ...]
```

Semantics: `A: 🇲🇽 🇰🇷` = predicted 1st and 2nd (direct qualifiers); `3º🇨🇿` = predicted 3rd
(potential tercero — advances only if among 8 best thirds).

**Char-count estimate (compact flags format):**
- Header: ~45 chars
- Per-user: ~15 chars header + 12 × ~20 chars = ~255 chars
- 11 users × 255 = ~2805 chars + header = **~2850 chars → fits in 4096 ✅**

If terceros qualifier status annotated live (e.g. `3º🇨🇿✅` / `3º🇨🇿❌`), add ~3 chars per group line: still fits.

**⚠️ NOTE:** This layout shows each person's TOP-2 QUALIFIERS and their 3RD-PLACE PICK per group.
It does NOT show the 4th team (the one they implicitly eliminated). It does NOT show a
"here are my 8 chosen terceros" row because no such data exists.
If the owner wants an explicit `terceros: [8 TLAs]` field, that is a data model extension — see D.1.

---

## B4. GRUPOS phase — IMAGE (matrix with highlight/fade)

Based on owner's reference: each cell shows all 4 group teams in 2×2 arrangement, with picks
highlighted and non-picks faded. Requires API for actual group compositions (4 teams per group).

```
╔══════════════╦════════════════╦════════════════╦════════════════╦══════╗
║  GRUPOS      ║     DavidR     ║     Victor     ║      Cris      ║ ...  ║
║              ║   (👤 photo)   ║   (👤 photo)   ║   (👤 photo)   ║      ║
╠══════════════╬════════════════╬════════════════╬════════════════╬══════╣
║ Grupo A      ║ 🇲🇽 🇰🇷 (bright) ║ 🇲🇽 🇰🇷 (bright) ║ 🇰🇷 🇲🇽 (bright) ║  …   ║
║ 🇲🇽🇰🇷🇨🇿🇿🇦      ║ 🇨🇿 (dim)       ║ 🇨🇿 (dim)       ║ 🇿🇦 (bright/3º) ║      ║
║  2×2 flags   ║ 🇿🇦 (faded)     ║ 🇿🇦 (faded)     ║ 🇨🇿 (faded)     ║      ║
╠══════════════╬════════════════╬════════════════╬════════════════╬══════╣
║ Grupo B      ║  [2×2 flags]   ║  [2×2 flags]   ║  [2×2 flags]   ║  …   ║
║ 🇨🇭🇨🇦🇶🇦🇧🇮      ║                ║                ║                ║      ║
╠══════════════╬════════════════╬════════════════╬════════════════╬══════╣
║  ... (×12)   ║                ║                ║                ║      ║
╚══════════════╩════════════════╩════════════════╩════════════════╩══════╝
```

Cell rendering per group:
- Draw the 4 group teams as a 2×2 flag grid (fixed group order from API).
- Picks 1 and 2 = full brightness (direct qualifiers).
- Pick 3 = intermediate brightness (tercero, may qualify).
- Non-picked team = greyed/faded (participant predicted elimination).

**Feasibility:**
- API call needed: group compositions (4 teams per group) from standings.
- PIL: existing `_circular_crop` + `_fetch_tile` from `podium_image.py` reusable.
- Flag rendering: `flag` library already in use; fading = draw flag image at reduced alpha.
- Canvas: 12 rows × ~4 cells tall + 11 participant columns. With cell ≈ 80×80px: ~1300×1080px.
- TERCEROS row (optional): if no separate YAML field exists, could show a strip below the grid
  where each person's 12 third-place picks are shown, with live-qualifier annotation (green/grey
  circles added as the tournament progresses). This is purely derived from the 3rd picks already
  stored — no new YAML field needed.

**Pros:** Visually rich; highlight/fade effect is instantly readable; no width limits.
**Cons:** Requires API for group compositions; cell layout (2×2 + alpha) is more complex
to implement than the knockout matrix (single flag per cell); PIL render ~300–600ms.

---

## C. Recommendation

| Mode | Knockout layout | Groups layout |
|---|---|---|
| `CHOICES_TYPE=text` | Per-user vertical blocks, flags+TLA, one line per tie | Per-user vertical blocks, compact 12-line format (flag pair + 3rd) |
| `CHOICES_TYPE=image` | PIL matrix — exact reference replication | PIL 2×2 cell matrix with highlight/fade |

**CHOICES_TYPE env var:**
- Values: `text` | `image`
- Default: `text`
- `Settings.choices_type: str = "text"`, `os.getenv("CHOICES_TYPE", "text")`

**Message-splitting strategy for text mode:**
- ≤11 participants: both knockout and groups fit in ONE message (compact format).
- 12–20 participants: send 2 messages (split at midpoint by user count).
- 20+ participants: strongly recommend image mode; text becomes unwieldy.
- Logic: after rendering, if `len(text) > 3800` (buffer below 4096), split at the last `\n\n👤` boundary.

**Why not TABLE/monospace?** Emoji width in monospace is platform-dependent; not recommended.

**Groups vs knockout text length:** groups compact is shorter (~2850 chars) than knockout
compact (~3373 chars) because groups has fewer items per user (12 groups vs 16 ties).

---

## D. Open Questions for Owner

1. **TERCEROS FIELD (data model extension):** The current YAML has no explicit "select 8 of 12 thirds" field — participants only predict 3rd-place per group (implicitly 12 potential terceros). Is the existing model sufficient, or do you want to add a `terceros: [8 TLAs]` field to predictions.yml? This would require updating the loader, adding a new YAML key, and potentially new scoring. **This is the biggest design decision — it affects both display AND data model.**

2. **API availability for `/elecciones`:** "By-tie" text and the knockout image both require a live API call to get the bracket (which teams play which). Is this acceptable? Should there be a fast-path fallback showing flat per-person pick lists when the API is unavailable?

3. **RESULTS column in image:** Should it always be present (blank cells until matches finish), or only appear after at least one result is available? What if a tie is still scheduled — show ⏳ or blank?

4. **Sort order of participant columns** in image (and name order in text): YAML insertion order, alphabetical by display_name, or by current ranking?

5. **"❓ / no pick" in knockout:** Can a participant have NEITHER team of a tie in their advance list? (E.g., if a wildcard was used or their list has fewer than 16 teams.) Should it show ❓ or be omitted?

6. **Groups image — terceros row:** Even without a new YAML field, a "terceros" strip could be shown below the groups matrix: all 12 third-place picks per person, annotated green (qualifying third per live API) or grey (not qualifying). Worth implementing?

7. **Profile photos:** Are photos at `{photo_base_url}/{username}.png` confirmed for ALL current participants? Initials placeholder is the automatic fallback — acceptable?

8. **Groups image — ordering of 4 teams in the 2×2:** Fixed as per API standings order (1st→4th), or a fixed canonical order (alphabetical, or by TLA)? This affects whether the "faded" team is always the same position in the grid.

9. **Groups ONLY in image, knockout in text?** Given that the groups image (highlight/fade) is significantly more complex than the knockout image, would it be acceptable to implement knockout image first, and leave groups image to a later sprint?

---

## E. Implementation Plan

### New files

1. **`src/worldcup_bot/porra/elecciones.py`** — Pure data helpers (no I/O):
   - `active_phases(predictions: dict) → list[str]`
   - `knockout_picks_by_person(predictions, yaml_key) → dict[str, list[str]]`
   - `groups_picks_by_person(predictions) → dict[str, dict[str, list[str]]]`
   - `build_knockout_text(ties, participants, picks_by_person, settings) → str`
   - `build_groups_text(participants, picks_by_person) → str`

2. **`src/worldcup_bot/bot/_image_utils.py`** — Shared PIL primitives:
   - Extract `_circular_crop`, `_fetch_tile`, `_placeholder_tile`, `_font` from `podium_image.py`
   - Both `podium_image.py` and the new matrix renderer import from here

3. **`src/worldcup_bot/bot/elecciones_image.py`** — PIL matrix renderers:
   - `render_knockout_matrix(ties, participants, picks, results, settings) → io.BytesIO | None`
   - `render_groups_matrix(participants, group_picks, group_compositions, settings) → io.BytesIO | None`

### Modified files

4. **`src/worldcup_bot/config.py`**:
   - Add `choices_type: str = "text"` to `Settings`
   - Add `choices_type=os.getenv("CHOICES_TYPE", "text")` to `load_settings()`

5. **`src/worldcup_bot/bot/handlers.py`**:
   - Add `cmd_elecciones(update, context)` — loads predictions, calls `active_phases()`, builds InlineKeyboardMarkup with phase buttons, sends with keyboard
   - Add `cmd_elecciones_callback(update, context)` — edits message to remove keyboard, dispatches to text or image path per `settings.choices_type`

6. **`src/worldcup_bot/__main__.py`**:
   - `CommandHandler("elecciones", cmd_elecciones)`
   - `CallbackQueryHandler(cmd_elecciones_callback, pattern=r"^elecciones\|")`
   - Add `/elecciones` to `cmd_start` help text

7. **`docker-compose.yml`** *(at implementation time only)*:
   - `CHOICES_TYPE: "${CHOICES_TYPE:-text}"`

### Tests (`tests/porra/test_elecciones.py`)

- `test_active_phases_template` — only grupos shows when all knockout = []
- `test_active_phases_full` — all 6 phases show with populated predictions
- `test_active_phases_wildcard_only` — knockout with only `**` entries does NOT show
- `test_build_knockout_text_fits_4096` — char limit check for 11 users × 16 ties
- `test_build_groups_text_fits_4096` — char limit check for 11 users × 12 groups

### Suggested implementation order

```
1. elecciones.py — active_phases + text builders (pure, testable, zero risk)
2. tests/porra/test_elecciones.py
3. config.py — add choices_type field
4. handlers.py — cmd_elecciones + cmd_elecciones_callback (text branch only)
5. __main__.py — register handlers + start help text
   ── MVP text mode shipped ──
6. _image_utils.py — extract PIL primitives from podium_image.py
7. elecciones_image.py — render_knockout_matrix first (simpler)
8. handlers.py — image branch for knockout
9. elecciones_image.py — render_groups_matrix (more complex, groups highlight/fade)
10. docker-compose.yml update
```

---

*Pirlo — Tech Lead — 2026-07-04 (v2)*


---

# Pirlo Third Review — commit 1b4045b

Reviewer: Pirlo (Lead / Tech Lead)  
Scope: correctness only  
Commit: 1b4045b  
Result: APPROVE

## Summary

Nesta fixed the remaining seed-path defect. `poll_finished_matches_job` now preserves the invariant that `finished_announced` is only consumed for `status == "FINISHED"` matches.

Focused tests run:

```text
python -m pytest tests\test_poll_finished_job.py::TestFirstRunSeedWithAge tests\test_poll_finished_job.py::TestStaleLaterFlip tests\test_poll_finished_job.py::TestProvisionalLateFinal -q
15 passed
```

## Verification

1. **Startup seed fixed:** first-run seed is now:

   ```python
   seeded = {m.id for m in all_matches if m.status == "FINISHED"}
   ```

   Stale `IN_PLAY` and `PAUSED` matches older than 4h are no longer written to `finished_announced`, so they remain eligible for the later official recap.

2. **All writes to `finished_announced` audited:**
   - Seed path: FINISHED-only.
   - Main loop: `new_ids = finished_ids - announced`, and `finished_ids` is FINISHED-only.
   - `match is None` guard and `finally` writes are inside `for match_id in new_ids`, so they inherit the FINISHED-only guard.
   - Provisional path writes only `provisional_announced`, never `finished_announced`.

3. **PAUSED handled:** `PAUSED` is not seeded and is not included in `stale_inplay_ids`; it only gets an official recap after it legitimately becomes `FINISHED`.

4. **Restart / exactly-once tests:** tests now cover stale IN_PLAY→FINISHED, stale PAUSED→FINISHED, and genuinely FINISHED at startup. They assert no startup final-dedup consumption for non-FINISHED matches, official recap exactly once after FINISHED, and no reannounce for truly finished-at-startup matches.

## Blocking issues

None.

## Non-blocking follow-ups

1. If either rejected revision ever ran in production, inspect `finished_announced.json` for stale non-FINISHED match ids and remove any polluted entries manually. Not a code blocker.

## Verdict

APPROVE. Ship this revision.


---

# Pirlo Re-Review — commit 615c34e

Reviewer: Pirlo (Lead / Tech Lead)  
Scope: correctness only  
Commit: 615c34e  
Result: REJECT

## Summary

Cannavaro fixed the normal running path: stale `IN_PLAY` now sends a clearly labelled `⏳ Resultado provisional`, uses separate `provisional_announced`, does not consume `finished_announced`, and `PAUSED` is excluded from that provisional path. Keyboard retry bounds and text-edit `keyboard_attached` handling are also addressed.

However, the restart / first-run seed path still has the original correctness bug: any match older than `MATCH_OVER_AGE` and not `FINISHED` is added to `finished_announced` without a send. That includes stale `IN_PLAY` and `PAUSED`. Once seeded there, the later official `FINISHED` recap is suppressed.

Focused tests run:

```text
python -m pytest tests\test_poll_finished_job.py::TestProvisionalLateFinal tests\test_poll_finished_job.py::TestFirstRunSeedWithAge tests\test_poll_goal_clips_job.py::TestKeyboardRetryGiveUp -q
13 passed, 1 warning
```

The tests pass because they still encode the rejected startup behavior (`test_stale_inplay_seeded_on_first_run_not_announced`, plus older first-run seed tests).

## Blocking issues

1. `src/worldcup_bot/__main__.py` — `poll_finished_matches_job` first-run seed still suppresses the later official final for stale `IN_PLAY`.

   Lines 1689-1710 seed every non-FINISHED match whose kickoff is older than 4h into `finished_announced`. On a container restart while football-data is still stuck `IN_PLAY` (the exact production failure mode), the match is marked final-deduped without a provisional or official recap. When the API later flips to `FINISHED`, `new_ids = finished_ids - announced` excludes it, so the official `🏁 Final` never fires. This violates the core requirement that provisional/late handling must not consume real-final dedup state.

   Fix: first-run seed must not put stale `IN_PLAY` into `finished_announced`. Route it through the provisional mechanism (or leave it unannounced until the normal provisional pass) and persist only `provisional_announced`; keep `finished_announced` for actual `FINISHED` official recaps / true historical seeding only.

2. `src/worldcup_bot/__main__.py` — first-run seed still treats `PAUSED` >4h as already-final/handled.

   The revised normal path correctly excludes `PAUSED`, but the first-run seed still adds any old non-FINISHED status to `finished_announced`, including `PAUSED` and even other delayed statuses. A resumable suspension that crosses a restart can later finish and be suppressed.

   Fix: do not seed `PAUSED` (or arbitrary non-FINISHED statuses) into `finished_announced` based only on kickoff age. Only official `FINISHED` should consume final dedup; ambiguous live/delayed states need separate provisional/ignored tracking that preserves the later official recap.

## Non-blocking follow-ups

1. Addressed: keyboard retries are bounded by `_MAX_KEYBOARD_ATTEMPTS = 5`, with persistence after failed retries.
2. Addressed: `_backfill_scorer_in_clip_store` and `_mark_goal_annulled` set `keyboard_attached=True` after successful text edits that pass `reply_markup` for ready clips.
3. Test follow-up: update/remove tests that still assert stale `IN_PLAY` / `PAUSED` first-run seeding into `finished_announced`; add a restart regression where `provisional_announced` is loaded, `finished_announced` is empty, API is still `IN_PLAY` >4h on first tick, then later `FINISHED` must send the official recap.

## Verdict

REJECT. The normal-path provisional design is right, but restart safety is still broken. The next revision must go to a different agent than Kanté or Cannavaro.


---

# Pirlo re-review — /elecciones increment 2 revision (`5df06de`)

Reviewed commit `5df06de`, Nesta's rationale, current `handlers.py`, `porra/elecciones.py`, `elecciones_image.py`, and `tests/test_elecciones.py`. Ran focused suite: `tests/test_elecciones.py` → **115 passed**.

## Verdict

**APPROVE-WITH-FOLLOWUPS**

## Blocking issues

None.

## Verification

1. **Cache staleness blocker fixed.** `_elecciones_results_version()` now hashes stage pairings from `get_all_matches()` plus finished winners, so no-ties → ties-scheduled changes the cache key before any match finishes. The no-ties artifact and API-error artifacts are marked `cacheable: False`, and the callback only stores cacheable artifacts. The full callback regression covers no-ties first tap followed by scheduled ties.

2. **4096 split blocker fixed.** `_split_messages()` reserves header/separator/prefix budget before pre-splitting blocks, and `_split_block_at_lines()` hard-splits a single overlong line. The old near-limit overflow case now emits all parts ≤4096. New tests cover many users, an enormous single line, and header+near-limit blocks.

3. **Flags fixed.** `_TWEMOJI_BASE` uses the working GitHub-hosted jsDelivr path. Standard 2-letter ISO flags resolve normally; ENG/SCO/WAL use the GB tag-sequence PNGs; NIR/GBNIR returns `None` and falls back to TLA text. Tests cover the URL mapping and mocked tile fetch/fallback.

4. **Graceful fallbacks fixed.** Groups image mode now falls back to text, not a blank image, when standings fetch fails, and that API-failure fallback is non-cacheable. Placeholder delete failure now neutralises the old hourglass and still sends the result.

## Non-blocking follow-ups

1. If `render_groups_matrix()` or `render_knockout_matrix()` returns `None`, the image-mode text fallback is still cacheable by default. That is acceptable for this revision because the concrete standings-API fallback is fixed and flag fetch failures no longer fail the whole render, but consider marking render-failure fallbacks non-cacheable too.
2. The cache version intentionally hashes pair identity/winner, not `utc_date` display order. If football-data ever reorders a stage without changing teams/winners, cached ordering could persist until another version input changes.


---

# Pirlo Review — commit a61757d

Reviewer: Pirlo (Lead / Tech Lead)  
Scope: correctness only  
Commit: a61757d  
Result: REJECT

## Summary

Bug #1 is directionally correct: happy path now sets `keyboard_attached=True` only after `edit_message_reply_markup` succeeds, and ready/unattached entries bypass the old early return and retry. Relevant tests pass.

Bug #2 is not safe enough to ship as-is. The wall-clock fallback sends a real `Final` card from the same football-data `Match` object that is still `IN_PLAY`/`PAUSED`. If that object's score is stale or null, the bot announces and persists a wrong final scoreline.

Relevant tests run:

```text
python -m pytest tests\test_poll_goal_clips_job.py tests\test_poll_finished_job.py -q
84 passed, 3 warnings
```

## Findings

### Blocking 1 — stale wall-clock fallback can announce the wrong final score

Area: `src/worldcup_bot/__main__.py`, `poll_finished_matches_job` (`stale_live_ids` + `format_final_result(match)`).

The fallback includes `IN_PLAY`/`PAUSED` matches older than 4h in `new_ids`, then formats the final using `match.home_score`, `match.away_score`, and `match.winner` from that same still-live football-data object.

There is no independent score confirmation, no check that the score has settled, and no different message type for "API status stuck but score provisional". `finished_announced` is then persisted, so when football-data later flips to `FINISHED` the real final recap is suppressed. `finished_scores` is not sufficient mitigation: its correction window is 30 minutes, it labels any later difference as VAR, and it does not fix the original Final card.

Required fix: do not send/persist a real `Final` recap from an unfinalized `IN_PLAY`/`PAUSED` football-data score unless the score is confirmed by a reliable independent/settled source. Either defer the final recap until `FINISHED`, or add a separate provisional/stuck-status path that does not consume `finished_announced`, or fetch/validate a settled score from another source before announcing.

### Blocking 2 — `PAUSED` after 4h is treated as final without distinguishing delays/suspensions

Area: `src/worldcup_bot/__main__.py`, `stale_live_ids` includes `m.status in ("IN_PLAY", "PAUSED")`.

A 4h cutoff is acceptable as a goal-spam circuit breaker, but a Final announcement is higher consequence. A weather/security/medical delay or suspended-and-resumed match can remain `PAUSED` beyond 4h and later continue. This code would announce it as final and permanently dedup it.

Required fix: exclude ambiguous delayed/suspended states from true Final recap, or route them through the same confirmed-score/provisional mechanism above.

## Non-blocking follow-ups

1. `poll_goal_clips_job`: keyboard retry is unbounded every tick until 7-day pruning. Permanent Telegram errors (deleted message/chat) will log and call the API thousands of times per entry. Add retry count/backoff/give-up or classify permanent failures.
2. `keyboard_attached` is not updated when `_backfill_scorer_in_clip_store` / `_mark_goal_annulled` successfully attach/preserve the keyboard via `edit_message_text(reply_markup=...)`. That can cause redundant retry edits. Set it true on those confirmed successes.
3. Add tests for the rejected path: stale `IN_PLAY` with a behind/null score, later `FINISHED` with a different score, and restart persistence behavior.

## Verdict

REJECT. Bug #1 can stay, but Bug #2 needs revision by a different backend agent than Kanté before this passes the reviewer gate.


---

# Pirlo Review — /elecciones commit 38e00b2

Reviewer: Pirlo (Lead / Tech Lead)  
Scope: correctness only  
Commit: 38e00b2  
Result: APPROVE-WITH-FOLLOWUPS

## Summary

The implementation matches the core `/elecciones` design: phase filtering is correct, callback flow is safe, text renderers are per-user vertical, image mode uses the shared football client path through handlers, in-memory artifact cache is bounded, `CHOICES_TYPE` is wired, and API failures degrade to user-facing text instead of crashing.

Focused tests run:

```text
python -m pytest tests\test_elecciones.py -q
79 passed
```

Current `data/predictions.yml` active phases evaluated to:

```text
['grupos', 'round_of_32', 'round_of_16']
```

So `quarter_finals`, `semi_finals`, and `final` are absent as required; `grupos` and `round_of_32` are present.

## Verification

1. **Phase keyboard filtering:** `active_phases()` only includes phases with at least one non-`**` pick. Tests cover wildcard-only and empty knockout lists.
2. **Callback:** `elecciones|<key>` parsing does not crash for malformed/unknown keys; known taps remove the inline keyboard before serving. Unknown keys degrade to “cuadro no disponible” rather than an exception.
3. **Text renderers:** knockout and groups render vertical per-user blocks. Knockout no-pick/`**` becomes `❓`; groups show top two plus `3º...`, including `3º**` for wildcard third picks. Splitting is at user boundaries and normal generated messages stay under Telegram limits.
4. **Image:** knockout image renders participant photo headers with podium helpers / initials fallback, uses shared client in the handler path, and falls back to text on image-send/render failure.
5. **Cache:** `bot_data['elecciones_cache']` key is `(yaml_key, mtime, results_hash)`, same-phase stale entries are evicted, and hard cap is 6. Results hash changes when `StageResult` winner/tie data changes. No long-lived background regeneration task exists.
6. **CHOICES_TYPE:** default `text`; present in `docker-compose.yml`, `docker-compose.local.yml`, and `.env.example`. Groups in image mode intentionally fall back to text.
7. **Robustness:** API failures during knockout generation return user-facing error text; no unhandled exception path found in the callback.

## Blocking issues

None.

## Non-blocking follow-ups

1. `elecciones_image.py` writes flag tiles under `{state_dir}/elecciones_tiles` without an explicit eviction bound. The practical footprint is small/finite for tournament flags, but add a simple max-file or age prune to match the stated bounded-cache requirement exactly.
2. Image rendering uses `await asyncio.to_thread(...)`. This is awaited and not a persistent background job, but it is not literally “no background thread”; document this or render inline if the owner wants strict no-thread behavior.
3. `_split_messages()` cannot split a single oversized user block; add a defensive line-level split if participant names/data can ever push one block over 4096.

## Verdict

APPROVE-WITH-FOLLOWUPS. Ship is acceptable; follow-ups are bounded-risk hardening, not blockers.


---

# Pirlo review — /elecciones increment 2 (`30919a7`)

Reviewed diff `38e00b2..30919a7`, current `elecciones_image.py`, `porra/elecciones.py`, handler flow, and Kanté notes. Focused `tests/test_elecciones.py` is green (`101 passed`). Existing revive quiet-hour failures are unrelated.

## Verdict

**REJECT** — the image/hourglass work is mostly sound, but two correctness defects remain.

## Blocking issues

1. **Knockout artifact cache can serve stale bracket output.**
   - Area: `src/worldcup_bot/bot/handlers.py` `_elecciones_results_version()` / cache key.
   - The cache key hashes only `client.get_stage_results(api_key)`, which returns FINISHED matches only. If a user opens a knockout phase before its bracket/ties exist, the handler caches “cuadro no disponible” under the empty-results hash. Later, when scheduled ties become available but no match has finished yet, the hash is unchanged, so the bot keeps serving the stale unavailable artifact. Same problem for tie/team changes before the first finished result.
   - Required fix: include the relevant stage tie list / bracket identity from `get_all_matches()` in the cache version, or avoid caching the “not available yet” artifact. Add a regression test: first callback no ties caches unavailable, second callback with scheduled ties but no finished results must regenerate and serve the bracket.

2. **Defensive text split does not guarantee Telegram-safe message length.**
   - Area: `src/worldcup_bot/porra/elecciones.py` `_split_block_at_lines()` / `_split_messages()`.
   - The pre-split uses `_HARD_LIMIT` for block chunks, but `_split_messages()` then adds the header/part prefix/separators. A valid block chunk near 4096 chars produces a final message >4096 (local probe produced length 4098). A single line >4096 is also emitted unsplit. This violates the stated requirement that no message exceeds Telegram’s 4096 limit.
   - Required fix: split against available payload after header/part prefix overhead, or final-validate and further split at line/character boundaries. Add tests asserting every emitted message is `<= 4096`.

## Non-blocking follow-ups

1. **Groups image API failure is misleading.** If `get_standings()` fails, current image mode renders and sends an empty groups grid instead of falling back to text. Prefer text fallback or an explicit error so users do not receive a blank-looking prediction image.
2. **Placeholder delete failure leaves stale hourglass.** `_serve_after_placeholder()` logs delete failure and still sends the result. Acceptable as a send-first fallback, but consider editing the placeholder to a neutral/error state when delete fails.

Required revision: assign to a different agent than Kanté.

---

# [PENDING USER SIGN-OFF] Spec: Perfiles per-user auto-aprendidos para Picante

**Estado:** ⏳ PENDING — requiere aprobación de drdonoso antes de que Kanté implemente  
**Autor:** Pirlo (Lead/Architect)  
**Fecha:** 2026-07-10T12:00:56+02:00  
**Solicitado por:** drdonoso  

---

## Decisiones previas asumidas (NO reabrir)

| Decisión | Valor |
|---|---|
| Fuente | AUTO-LEARNED (auto_full) — sin YAML manual; cold start aceptado |
| Campos | 6 por usuario: rasgos, equipo, motes, temas, tono, piques_recientes |
| Scope | include_others: perfil autor + otros usuarios recientes (con cap) |
| Privacidad | Texto en disco permitido — 7 días sliding window + rotación; **ruptura explícita** de la política "no text on disk" de ChatState |
| Cadencia | Batch diario (estrategia b de Kanté) |
| Modelo | Summarización en `PICANTE_PROFILE_MODEL` (barato, ej. `gpt-5.4-nano`); reply picante permanece en `OPENAI_MODEL` |

---

## 1. Nuevos módulos / ficheros y cambios por fichero

### 1.1 `src/worldcup_bot/chat/message_store.py` — **NUEVO**

**Propósito:** Almacén on-disk de mensajes de texto por usuario. Ventana deslizante de 7 días.

**Ruta de datos:** `{state_dir}/picante_messages/{username}.jsonl`  
(un fichero JSONL por usuario; una entrada JSON por línea)

**Funciones públicas:**
- `append_message(state_dir, username, text, ts: datetime) → None`  
  Best-effort; no lanza. Si `username` está vacío → no-op. Si `PICANTE_STORE_TEXT=0` → no-op.  
  Tras escribir, llama a `_rotate_messages` para descartar entradas fuera de la ventana.
- `load_messages(state_dir, username, window_days: int) → list[dict]`  
  Lee el JSONL, filtra solo entradas dentro de `window_days`, devuelve lista `[{"ts": ..., "text": ...}]`.  
  Nunca lanza — si el fichero está ausente o corrupto devuelve `[]` + WARNING log.
- `active_users(state_dir, window_days: int) → list[str]`  
  Escanea `{state_dir}/picante_messages/` buscando ficheros `*.jsonl` con mensajes recientes.  
  Devuelve lista de usernames con al menos 1 entrada dentro de la ventana.
- `_rotate_messages(path, window_days: int) → None`  
  Reescribe el fichero JSONL descartando líneas con `ts` anterior a `now - window_days`.  
  Best-effort (atómico: escribe `.tmp` → `os.replace`). Si falla → warning log, fichero sin modificar.

**Política de privacidad:** La función `append_message` comprueba el flag interno (cargado de settings) antes de escribir. El hook en `listener.py` solo llama a `append_message` si `settings.picante_store_text` es `True`.

**Nota:** Esta es la **única ruptura** de la política "no text on disk" de `ChatState` (buffer.py:1–5, state.py:3). Se documenta explícitamente como decisión deliberada.

---

### 1.2 `src/worldcup_bot/chat/profiles.py` — **NUEVO**

**Propósito:** Almacén de perfiles por usuario (resúmenes generados por AI). Carga/guarda atómico; nunca lanza.

**Ruta de datos:** `{state_dir}/picante_profiles.json`

**Funciones públicas:**
- `load_profiles(path: str) → dict[str, UserProfile]`  
  Patrón idéntico a `load_chat_state` (state.py:41–63): `try/except`, devuelve `{}` si ausente/corrupto.
- `save_profiles(path: str, profiles: dict[str, UserProfile]) → None`  
  Patrón idéntico a `save_chat_state` (state.py:66–89): temp file → `os.replace`, best-effort.
- `get_profile(profiles: dict, username: str) → UserProfile | None`  
  Simple lookup; devuelve `None` si no existe.

**Dataclass `UserProfile`** (ver Schema en §2).

---

### 1.3 `src/worldcup_bot/chat/profile_updater.py` — **NUEVO**

**Propósito:** Función de summarización que toma mensajes acumulados y devuelve un `UserProfile` actualizado.

**Función principal:**
```
async def update_user_profile(
    username: str,
    messages: list[dict],     # de load_messages
    current: UserProfile | None,
    ai: AIClient,             # instanciado con PICANTE_PROFILE_MODEL
    pinned_fields: list[str], # campos que el auto-updater NO sobreescribe
) -> UserProfile
```

- Si `messages` está vacío → devuelve `current` sin llamar a la AI.  
- Llama a `ai.complete(system_prompt, user_prompt, temperature=0.3, max_completion_tokens=400)`.  
- Parsea el JSON devuelto por el modelo → actualiza solo campos no pinned.  
- Si `AIError` o `json.JSONDecodeError` → WARNING log + devuelve `current` (o `UserProfile(username=username)` si no había perfil previo).  
- `updated_at` se fija a `datetime.now(UTC).isoformat()` solo si la llamada AI tiene éxito.

**System prompt de extracción (alto nivel):**  
El system prompt instruye al modelo a:
1. Analizar la lista de mensajes de `{username}` (últimos N días).
2. Extraer y resumir los 6 campos: `rasgos`, `equipo`, `motes`, `temas`, `tono`, `piques_recientes`.
3. Devolver EXCLUSIVAMENTE un JSON válido con esos 6 campos (sin prosa adicional).
4. Para campos sin evidencia suficiente → devolver `null` o lista vacía (no inventar).
5. `piques_recientes` en este contexto = menciones a predicciones fallidas o chistes recurrentes visibles en los mensajes, NO los piques enviados por el bot (esos se añaden por separado desde `maybe_reply`).

**User prompt:** Lista de mensajes del usuario en texto plano + perfil actual como contexto base (si existe).

---

### 1.4 `src/worldcup_bot/__main__.py` — **MODIFICADO** (solo añadir job + wiring)

**Nuevo job function:** `profile_update_job(context)` — función async en `__main__.py`.  
Lógica:
1. Lee `settings`, `state_dir`, `profiles_path` de `context.bot_data`.
2. Obtiene `active_users(state_dir, window_days=settings.picante_profiles_window_days)`.
3. Carga perfiles actuales (`load_profiles`).
4. Para cada usuario activo: `await update_user_profile(...)` con el AI client de perfiles.
5. Guarda perfiles actualizados (`save_profiles`).
6. Todo en `try/except Exception` por usuario — un fallo no interrumpe los demás.  
7. Si `picante_profiles_enabled(settings)` es False → return inmediato (best-effort guard).

**Registro del job** — justo después del bloque `if picante_enabled(settings)` (línea ~2472), siguiendo el patrón de `run_daily` de `rich_image_job` (línea 2456):
```python
if picante_profiles_enabled(settings):
    app.job_queue.run_daily(
        profile_update_job,
        time=dtime(hour=settings.picante_profiles_update_hour, minute=0, tzinfo=tz),
        name="picante_profile_update",
    )
    log.info(
        "Picante profiles update ENABLED — daily at %02d:00 %s",
        settings.picante_profiles_update_hour,
        settings.timezone,
    )
else:
    log.info(
        "Picante profiles update DISABLED — set PICANTE_PROFILES_ENABLED=1 to enable."
    )
```

**AI client de perfiles:** Instanciar un `AIClient` separado con `PICANTE_PROFILE_MODEL` en `build_app()` (o en el job callback), almacenado en `context.bot_data["profile_ai_client"]`. Usa las mismas `OPENAI_API_KEY` y `OPENAI_BASE_URL` que el cliente principal — solo cambia el campo `model`.

---

### 1.5 `src/worldcup_bot/chat/picante.py` — **MODIFICADO**

**`build_picante_user_message`** (actualmente picante.py:79–114):  
- Nueva firma: añade parámetros opcionales `profiles: dict | None = None` y `author_username: str = ""`.  
- Si `profiles` no es None y `author_username` es non-empty:  
  - Recupera `get_profile(profiles, author_username)` → bloque PERFIL AUTOR.  
  - Recupera hasta `settings.picante_profiles_others_cap` perfiles de otros usuarios activos recientes (excluyendo al autor).  
  - Construye bloque `PERFILES DEL GRUPO` con sección AUTOR primero, luego OTROS.  
  - Inserta el bloque entre el system prompt y el CONTEXTO RECIENTE (o como primera sección del user message).
- Si `profiles` es None o username vacío o no hay perfil → no añade ningún bloque; comportamiento idéntico al actual.  
- La lógica del bloque PERFIL no puede lanzar excepciones — toda ruta tiene fallback silencioso.

**Formato del bloque PERFIL en el user message:**
```
PERFILES DEL GRUPO — úsalos para personalizar el comentario:

[AUTOR: pepe]
Rasgos: ...
Equipo favorito: ...
Motes/apodos: ...
Temas/aficiones: ...
Tono a usar: ...
Piques recientes: ...

[OTROS PARTICIPANTES RECIENTES]
[juan] Equipo: ..., Tono: ...
[maria] Equipo: ..., Tono: ...
```

**`maybe_reply`** (picante.py:120–190):
- Carga `profiles = load_profiles(profiles_path)` antes de los gates (si `picante_profiles_enabled`). Si falla → `profiles = None`.  
- Extrae `author_username` de `messages[-1]` (el trigger del buffer).  
- Pasa `profiles` y `author_username` a `build_picante_user_message`.  
- Tras enviar la respuesta (`update.message.reply_text`), persiste el pique:  
  - `profiles[author_username].piques_recientes.append({"ts": now_utc, "texto": text[:200]})`.  
  - Trunca a `settings.picante_profiles_piques_cap` entradas más recientes.  
  - `save_profiles(profiles_path, profiles)` — best-effort, en `try/except`.  
- El pique persistido es el **texto generado por el bot** (no el mensaje del usuario), truncado a 200 chars.

---

### 1.6 `src/worldcup_bot/chat/listener.py` — **MODIFICADO** (on_group_text)

Tras el paso 7 (update last_seen, línea ~92–97), añadir paso 7.5:
```
# 7.5. Acumular mensaje para perfiles (si feature habilitada y store_text activo)
if picante_profiles_enabled(settings) and settings.picante_store_text:
    append_message(state_dir, username, text, now_utc)
```
Best-effort — cualquier excepción se captura y loggea como WARNING, sin romper el flujo.

---

### 1.7 `src/worldcup_bot/config.py` — **MODIFICADO**

Ver §3 para la lista completa de env vars. Seguir el patrón de `chat_picante_enabled` (config.py:50, 165).

Nueva función helper:
```python
def picante_profiles_enabled(settings: "Settings") -> bool:
    """Return True when profiles feature is enabled AND picante is enabled."""
    return settings.picante_profiles_enabled and picante_enabled(settings)
```

---

## 2. Modelo de datos — Schemas JSON concretos

### 2.1 Almacén de mensajes por usuario

**Ruta:** `{state_dir}/picante_messages/{username}.jsonl`  
**Formato:** JSONL — una entrada JSON por línea.

```json
{"ts": "2026-07-10T12:00:00+00:00", "text": "Hoy España gana 3-0"}
{"ts": "2026-07-10T14:23:11+00:00", "text": "Messi está en forma, el Barça arrasará"}
```

Campos por entrada:
- `ts`: ISO-8601 UTC (str)
- `text`: texto del mensaje (str), sin truncar al almacenar

---

### 2.2 Almacén de perfiles

**Ruta:** `{state_dir}/picante_profiles.json`  
**Formato:** JSON object keyed por username.

```json
{
  "pepe": {
    "username": "pepe",
    "rasgos": "Optimista serial. Predice goleadas épicas que nunca ocurren. Fiel a España incluso en la derrota.",
    "equipo": "España / Real Madrid",
    "motes": ["el Profeta", "el Vidente Ciego"],
    "temas": ["F1", "IA", "predicciones fallidas"],
    "tono": "banter duro centrado en predicciones erróneas; admite el chaparrón con humor",
    "piques_recientes": [
      {"ts": "2026-07-08T20:14:00+00:00", "texto": "¡Pepe predijo 4-0 y acabó 0-1! ¿Cuándo abres la academia de adivinación?"}
    ],
    "pinned_fields": [],
    "updated_at": "2026-07-10T04:12:00+00:00"
  },
  "juan": {
    "username": "juan",
    "rasgos": "Catastrofista profesional. Siempre teme lo peor, acierta raramente, y lo celebra el doble.",
    "equipo": "Argentina",
    "motes": ["el Cenizo"],
    "temas": ["fútbol", "quejarse del árbitro"],
    "tono": "ironía suave; recordarle sus predicciones pesimistas que se cumplieron",
    "piques_recientes": [],
    "pinned_fields": ["tono"],
    "updated_at": "2026-07-10T04:13:00+00:00"
  }
}
```

Campos por `UserProfile`:
| Campo | Tipo | Descripción |
|---|---|---|
| `username` | str | Telegram username (lowercase, sin @) |
| `rasgos` | str \| null | Descripción libre de personalidad/carácter |
| `equipo` | str \| null | Equipo/selección favorita |
| `motes` | list[str] | Apodos y chistes recurrentes |
| `temas` | list[str] | Aficiones y temas recurrentes |
| `tono` | str \| null | Instrucción de tono a usar con esta persona |
| `piques_recientes` | list[{ts, texto}] | Últimos N piques enviados por el bot (texto del bot, truncado 200 chars) |
| `pinned_fields` | list[str] | Campos que el auto-updater NO sobreescribe |
| `updated_at` | str \| null | ISO-8601 UTC de última actualización AI |

---

## 3. Config / Env Vars nuevas

| Env var | Dataclass field | Default | Tipo | Propósito |
|---|---|---|---|---|
| `PICANTE_PROFILES_ENABLED` | `picante_profiles_enabled` | `False` | bool | Feature flag maestro. Requerido para activar todo lo demás. |
| `PICANTE_STORE_TEXT` | `picante_store_text` | `True` | bool | Si False, `append_message` es no-op. Opt-out de privacidad. Sólo relevante si `PICANTE_PROFILES_ENABLED=1`. |
| `PICANTE_PROFILE_MODEL` | `picante_profile_model` | `"gpt-5.4-nano"` | str | Modelo barato para el job de summarización. NUNCA usar gpt-5.6-luna/sol/terra. |
| `PICANTE_PROFILES_WINDOW_DAYS` | `picante_profiles_window_days` | `7` | int | Ventana de mensajes a acumular/rotar (días). |
| `PICANTE_PROFILES_OTHERS_CAP` | `picante_profiles_others_cap` | `3` | int | Máximo de perfiles "otros" inyectados en el bloque PERFIL. |
| `PICANTE_PROFILES_PIQUES_CAP` | `picante_profiles_piques_cap` | `5` | int | Máximo de entradas en `piques_recientes` por usuario. |
| `PICANTE_PROFILES_UPDATE_HOUR` | `picante_profiles_update_hour` | `4` | int | Hora local (tz = TIMEZONE) del job batch diario. |

**Helper en `config.py`:**
```python
def picante_profiles_enabled(settings: "Settings") -> bool:
    return settings.picante_profiles_enabled and picante_enabled(settings)
```

---

## 4. Resiliencia / Edge cases

| Escenario | Comportamiento |
|---|---|
| `profiles` None / vacío | `build_picante_user_message` funciona idéntico al estado actual; sin bloque PERFIL |
| `username` vacío en el trigger | No se inyecta perfil del autor; otros perfiles tampoco (política conservadora) |
| `picante_profiles.json` corrupto / ausente | `load_profiles` devuelve `{}` + WARNING; picante dispara sin perfil |
| `load_messages` falla o fichero corrupto | Devuelve `[]` + WARNING; job batch salta ese usuario |
| `update_user_profile` → AIError | WARNING log; conserva perfil anterior (`UserProfile` sin `updated_at` nuevo) |
| `update_user_profile` → JSON malformado | WARNING log; conserva perfil anterior |
| Job batch: error en usuario individual | `try/except Exception` por usuario; continúa con los demás |
| `append_message` falla (disco lleno, permisos) | WARNING log; no rompe `on_group_text` ni picante |
| `save_profiles` falla (disco lleno, etc.) | WARNING log (mismo patrón que `save_chat_state`) |
| `picante_profiles_enabled=False` | Cero código de perfiles ejecutado; zero overhead |
| Usuario sin Telegram username | `username` vacío → `append_message` es no-op → sin perfil → no se inyecta |

**Regla de oro:** La respuesta picante NUNCA falla por la capa de perfiles. Toda excepción en la capa de perfiles se captura localmente. "Fail loud in logs, degrade gracefully" — mismo principio que el resto del codebase (picante.py:187–190).

---

## 5. Privacidad

### Cambio de política explícito

La implementación actual almacena en disco **solo** metadatos/contadores (state.py:3: "Stores ONLY timing/counter metadata to disk (no message text)"). Esta feature **rompe deliberadamente esa política** para los usuarios que tienen perfiles activados.

**Qué se almacena en disco:**
- `{state_dir}/picante_messages/{username}.jsonl`: texto completo de los mensajes del usuario en el grupo, durante un máximo de `PICANTE_PROFILES_WINDOW_DAYS` días (default 7).
- `{state_dir}/picante_profiles.json`: **resúmenes** generados por AI — no texto libre. Incluye `piques_recientes` que son fragmentos del texto generado por el bot (≤200 chars), no texto del usuario.

**Rotación:** Al escribir un nuevo mensaje, `_rotate_messages` descarta automáticamente las entradas fuera de la ventana (patrón trim-on-write, no job separado).

**Control:**
- `PICANTE_STORE_TEXT=0` desactiva el almacenamiento de texto completamente. Con este flag, `append_message` es no-op y el job diario no acumula nuevos mensajes (los perfiles dejan de actualizarse).
- `PICANTE_PROFILES_ENABLED=0` desactiva toda la feature.

**Contexto:** El grupo es privado, entre amigos. El riesgo es bajo. Sin embargo, el control explícito (flags, rotación, resúmenes vs. texto) es la práctica correcta.

---

## 6. Superficie de tests para Buffon

### `tests/test_message_store.py` (nuevo)
- `append_message` escribe correctamente en JSONL con ts + text
- `load_messages` filtra por ventana (entradas viejas excluidas)
- `_rotate_messages` descarta entradas fuera de ventana; mantiene las recientes
- `PICANTE_STORE_TEXT=False` → `append_message` es no-op (no crea fichero)
- `active_users`: detecta usuarios con mensajes recientes, ignora vacíos/expirados
- Fichero JSONL corrupto (línea inválida) → `load_messages` devuelve sólo líneas válidas (o `[]` si todo inválido) + WARNING
- Username vacío → no-op

### `tests/test_profiles.py` (nuevo)
- `load_profiles`: fichero ausente → `{}`
- `load_profiles`: JSON corrupto → `{}` + WARNING (nunca lanza)
- `save_profiles`: escritura atómica (usa `.tmp` → `os.replace`)
- `get_profile`: usuario existente devuelve `UserProfile`; usuario inexistente devuelve `None`
- Round-trip: save → load → igualdad de datos

### `tests/test_profile_updater.py` (nuevo)
- `update_user_profile` con AI mock → devuelve `UserProfile` con campos actualizados
- `AIError` → devuelve perfil anterior sin cambios; `updated_at` no modificado
- JSON malformado del LLM → devuelve perfil anterior sin cambios
- `pinned_fields` no se sobreescriben por el auto-updater
- `messages` vacío → devuelve `current` sin llamar a la AI
- Cold start (sin perfil previo) + AIError → devuelve `UserProfile` vacío (no lanza)

### `tests/test_chat.py` o `tests/test_chat_edge_cases.py` (extensión)
- `build_picante_user_message` con `profiles` válidos → bloque PERFIL inyectado (autor primero)
- `build_picante_user_message` sin `profiles` (None) → idéntico al comportamiento actual
- `build_picante_user_message` con `profiles_others_cap=2` → máximo 2 perfiles "otros"
- `build_picante_user_message` con autor sin perfil + otros con perfil → solo sección OTROS
- `maybe_reply`: `load_profiles` falla → dispara picante sin perfil (no excepción)
- `maybe_reply`: tras enviar, persiste pique en `piques_recientes` (mock save_profiles)
- `maybe_reply`: `piques_recientes` truncado a `PICANTE_PROFILES_PIQUES_CAP`

### `tests/test_config.py` (extensión)
- Nuevas env vars parseadas con valores correctos
- Defaults correctos cuando las vars están ausentes
- `picante_profiles_enabled`: False si `CHAT_PICANTE_ENABLED=0`; False si `PICANTE_PROFILES_ENABLED=0`; True solo si ambos activos + AI configurado

---

## 7. Orden de construcción por fases

### Fase 1 — Config + Message Store (sin AI, sin perfil injection)
**Ficheros:** `config.py` (env vars) + `message_store.py` (nuevo) + `listener.py` (hook) + tests  
**Verificación:** El bot acumula mensajes en disco bajo feature flag; cero impacto en picante existente.  
**Entregable testeable:** `test_message_store.py` verde; `PICANTE_STORE_TEXT=0` funciona.

### Fase 2 — Profiles Store (sin AI)
**Ficheros:** `profiles.py` (nuevo) + tests  
**Verificación:** Almacén listo para lectura/escritura; load/save atómico; graceful degradation.  
**Entregable testeable:** `test_profiles.py` verde; round-trip OK.

### Fase 3 — Profile Updater + Job Batch
**Ficheros:** `profile_updater.py` (nuevo) + wiring en `__main__.py` (job + AI client de perfiles)  
**Verificación:** Job se registra y ejecuta; perfiles actualizados diariamente en disco; AI mock en tests.  
**Entregable testeable:** `test_profile_updater.py` verde; job registrado con `run_daily` en `__main__`.

### Fase 4 — Inyección en Picante + Persistencia de Piques
**Ficheros:** `picante.py` (modificado: inyección + piques) + tests de integración  
**Verificación:** Bloque PERFIL aparece en los prompts; `piques_recientes` se actualiza tras cada disparo; degradación elegante si no hay perfiles.  
**Entregable testeable:** Suite completa verde (incluyendo tests de `test_chat.py`); feature end-to-end funcional.

---

## 8. Riesgos / Decisiones abiertas (requieren confirmación de drdonoso)

| # | Decisión abierta | Recomendación Pirlo | Motivo |
|---|---|---|---|
| 1 | `PICANTE_PROFILES_OTHERS_CAP` — ¿3 o 5? | **3** | Kanté estimó +~300 tokens por perfil; con 5 perfiles se añaden ~1500 tokens extra al prompt; 3 es el equilibrio calidad/coste |
| 2 | Hora del job batch — ¿04:00? | **04:00** local | Mínima actividad del grupo (madrugada Madrid); no compite con `DAILY_UPDATE_HOUR=09:00` |
| 3 | ¿Token cap duro en el bloque PERFIL? | **Soft cap (log warning)** | El modelo gestiona su propio límite; un hard-truncate de texto a mitad de campo es confuso |
| 4 | `PICANTE_STORE_TEXT` default — ¿activado? | **`True` (default 1)** | La feature no tiene valor sin acumulación; el grupo es privado y es el comportamiento esperado |
| 5 | Rotation strategy — ¿trim-on-write o job de limpieza? | **Trim-on-write** | Simple, sin dependencias adicionales; el fichero nunca crece más de 7 días sin que el usuario envíe un nuevo mensaje |
| 6 | Usuarios sin Telegram username — ¿no-op o usar user_id? | **No-op si username vacío** | Política conservadora; `user_id` como clave alternativa añade complejidad en el UI del perfil |
| 7 | `piques_recientes` en el summarization prompt — ¿incluir o solo de `maybe_reply`? | **Solo de `maybe_reply`** | El summarizer extrae piques del historial de mensajes del usuario; los piques del bot se añaden por separado. Sin solapamiento. |
| 8 | ¿`PICANTE_PROFILE_MODEL` fallback si vacío? | **Usar `OPENAI_MODEL`** | Si no se configura, usar el modelo principal evita un error; loggear WARNING recomendando el modelo barato |

---

*Spec generado por Pirlo — 2026-07-10T12:00:56+02:00*  
*Basado en: Kanté's design (kante/history.md:37–91), picante.py:79–114, state.py:41–89, listener.py:77–104, __main__.py:2427–2500, config.py:49–92*


---

# Decisión: Picante per-user profiles — implementación (Kanté)

**Estado:** ✅ IMPLEMENTADO  
**Autor:** Kanté (Backend Developer)  
**Fecha:** 2026-07-10T12:00:56+02:00  
**Solicitado por:** drdonoso  
**Basado en spec:** `.squad/decisions/inbox/pirlo-picante-profiles-spec.md`

---

## Resumen ejecutivo

Implementación completa en 4 fases del sistema de perfiles auto-aprendidos para picante, con 3 refinements aprobados por drdonoso que divergen del spec original de Pirlo.

---

## Ficheros entregados

### Nuevos
| Fichero | Propósito |
|---|---|
| `src/worldcup_bot/chat/timeline_store.py` | Timeline cronológico único de mensajes del grupo (JSONL); append, trim-on-write, load_since, last_run |
| `src/worldcup_bot/chat/profiles.py` | `UserProfile` dataclass; load/save atómico; `get_profile` |
| `src/worldcup_bot/chat/profile_updater.py` | `update_profiles_from_conversation` — pase único de conversación grupal a la AI |

### Modificados
| Fichero | Cambio |
|---|---|
| `src/worldcup_bot/config.py` | 7 nuevas Settings fields + `picante_profiles_enabled()` helper |
| `src/worldcup_bot/chat/listener.py` | Paso 7.5: best-effort timeline append |
| `src/worldcup_bot/chat/picante.py` | Inyección de perfiles en `build_picante_user_message`; persistencia de piques en `maybe_reply` |
| `src/worldcup_bot/__main__.py` | `profile_update_job`, profile AI client, registro `run_daily`, `bot_data` paths |

---

## Los 3 refinements vs spec original de Pirlo

### Refinement 1 — Summarización INCREMENTAL (no re-lectura de 7 días)
**Spec Pirlo:** Re-summarizar todos los mensajes de la ventana completa cada día.  
**Implementado:** El job lee **solo mensajes nuevos desde `last_run`** (via `load_since(state_dir, last_run)`). El perfil existente se pasa como contexto base al modelo, que lo enriquece sin partir de cero.  
**Por qué mejor:** Elimina lecturas y tokens redundantes en arranques sucesivos. El conocimiento acumula de manera genuinamente incremental.

### Refinement 2 — Ventana de retención = 2 días (no 7)
**Spec Pirlo:** `PICANTE_PROFILES_WINDOW_DAYS=7`  
**Implementado:** Default = 2 días (buffer de seguridad ante runs perdidos). Trim-on-write en `_trim_timeline`.  
**Por qué mejor:** Para perfiles que ya acumulan conocimiento, no es necesario conservar el texto raw durante 7 días. 2 días es suficiente para capturar actividad reciente y cubre un run diario perdido.

### Refinement 3 — TIMELINE GRUPAL con contexto (no ficheros per-usuario)
**Spec Pirlo:** `{state_dir}/picante_messages/{username}.jsonl` por usuario. Un AI call por usuario en el job.  
**Implementado:** Un único `picante_timeline.jsonl` con `{"ts","username","text"}` por línea. **Un solo AI call por ejecución del job**, pasando la conversación completa atribuida (`[username] texto`).  
**Por qué mejor:**
- El modelo lee a los usuarios EN CONTEXTO — captura hilos, chistes entre usuarios, dinámicas de grupo
- Más barato: N usuarios × 1 call → 1 call
- Captura el "quién-bromea-con-quién" que los ficheros per-usuario no pueden capturar

---

## Diseño del job incremental (Refinements 1+3 combinados)

```
profile_update_job():
  last_run = load_last_run(state_dir)          # None en primera ejecución
  messages = load_since(state_dir, last_run)   # solo mensajes nuevos
  if not messages: save_last_run; return       # no AI call en días sin actividad
  
  current_profiles = load_profiles(path)
  updated = await update_profiles_from_conversation(
      messages,           # conversación reciente atribuida
      current_profiles,   # perfiles existentes como contexto base
      profile_ai,         # modelo barato (PICANTE_PROFILE_MODEL)
  )
  save_profiles(path, updated)
  save_last_run(state_dir, now)
```

---

## Diseño del profile_updater

System prompt: instruye al modelo a analizar la conversación atribuida + perfiles actuales como base, y devolver **SOLO** un JSON `{username: {rasgos, equipo, motes, temas, tono}}`.

User prompt: `[username] texto` (chrono) + perfiles compactos actuales.

Post-procesado:
- Campos string: `nuevo OR existente` (conserva si AI devuelve null)
- Listas (motes, temas): unión acumulativa (no elimina)
- `pinned_fields`: nunca sobreescrito
- `piques_recientes`: NO tocado por el updater (solo por `maybe_reply`)
- `updated_at`: seteado al timestamp del run solo si AI tiene éxito

---

## Inyección en picante

`build_picante_user_message(messages, *, profiles=None, author_username="", others_cap=3)`:
- Si `profiles` es None o `author_username` vacío → comportamiento idéntico al actual
- Si ambos presentes: prepend bloque "PERFILES DEL GRUPO" con AUTOR primero, luego hasta `others_cap` otros usuarios del buffer
- Toda la lógica de perfiles en try/except — nunca rompe el prompt base

`maybe_reply` tras enviar respuesta:
- Re-lee los perfiles frescos
- Appends `{ts, texto[:200]}` a `piques_recientes` del autor
- Trunca a `PICANTE_PROFILES_PIQUES_CAP`
- `save_profiles` best-effort

---

## Env vars nuevas (todos con defaults conservadores)

| Var | Default | Tipo |
|---|---|---|
| `PICANTE_PROFILES_ENABLED` | `0` (False) | bool |
| `PICANTE_STORE_TEXT` | `1` (True) | bool |
| `PICANTE_PROFILE_MODEL` | `gpt-5.4-nano` | str |
| `PICANTE_PROFILES_WINDOW_DAYS` | `2` | int |
| `PICANTE_PROFILES_OTHERS_CAP` | `3` | int |
| `PICANTE_PROFILES_PIQUES_CAP` | `5` | int |
| `PICANTE_PROFILES_UPDATE_HOUR` | `4` | int |

---

## Resiliencia (non-negotiable)

- `PICANTE_PROFILES_ENABLED=0` → **cero** código de perfiles ejecutado
- Perfil corrupto/ausente → `load_profiles` devuelve `{}` + WARNING → picante dispara sin perfil
- Error en timeline append → WARNING en listener, `on_group_text` continúa
- AIError en updater → WARNING + perfiles sin cambios
- JSON malformado del modelo → WARNING + perfiles sin cambios
- Error en persistir pique → WARNING, respuesta ya enviada
- Job batch error total → try/except, log.exception, nunca fatal

---

## Tests

**2419 tests pasan, 0 regresiones.** Feature flag OFF by default — el comportamiento existente de picante es completamente inalterado cuando `PICANTE_PROFILES_ENABLED=0`.

Los test files nuevos (test_timeline_store, test_profiles, test_profile_updater + extensiones de test_chat, test_config) son responsabilidad de Buffon para la siguiente sesión.

---

*Kanté — 2026-07-10T12:00:56+02:00*



# Decision: /calcularperfiles hidden admin command

**Date:** 2026-07-10  
**Author:** Kanté (backend)  
**Status:** Implemented

## Context

The daily 04:00 `profile_update_job` processes the picante timeline and updates per-user profiles. There was no way to trigger this on demand (e.g. after adding new messages to the timeline, or after enabling the feature mid-day). The only option was waiting until 04:00 or restarting the bot.

## Decision

Add a hidden admin command `/calcularperfiles` that fires the same profile-update pipeline immediately, following the same job/command split pattern as `/evilsanchez` → `rich_image_job`.

## Pattern applied: shared-helper split

```
_run_profile_update(context) -> int   ← RAISES, returns participant count
       ↑                    ↑
profile_update_job      cmd_calcularperfiles
  (swallows errors)       (reports errors to invoker)
```

This mirrors `_evolve_and_send_rich_image` / `rich_image_job` / `cmd_evil_sanchez` exactly. The rule is:
- The **shared helper raises** — so the manual command can catch and report failures.
- The **scheduled job swallows** — so a transient error never kills the bot's job queue.
- The **command checks the feature flag first** — replies in Spanish if `PICANTE_PROFILES_ENABLED=0`.

## Key design choices

1. **Return value is participant count, not message count.** The helper returns `len({username for m in messages})` — 0 means "no new messages, no AI call". This is sufficient for the command reply and for the job's log.

2. **`profile_ai is None` guard stays in the job, not the helper.** The job logs a WARNING and returns cleanly; the helper raises RuntimeError if called without an AI client. This preserves the original job's observable log behaviour.

3. **`last_run` advances on every call** — including the manual one. A later 04:00 run will only process messages after the manual trigger. This is intentional: the manual command is a full incremental pass, not a preview.

4. **No feature-flag check in the helper.** The caller (job or command) is responsible for the feature-enabled guard. The helper assumes it is called only when the feature is on.

5. **Hidden by omission.** Not listed in `_HELP_COMMANDS` or `/start`. Registration is in the hidden-commands block alongside `/evilsanchez` and `/perfil`.

## Files changed

- `src/worldcup_bot/__main__.py`:
  - `_run_profile_update` extracted at line 222
  - `profile_update_job` refactored at line 267 (behaviour unchanged)
  - `cmd_calcularperfiles` added at line 377
  - `CommandHandler("calcularperfiles", cmd_calcularperfiles)` registered at line 2488

## Test result

2586 passed, 0 failures (full suite).


