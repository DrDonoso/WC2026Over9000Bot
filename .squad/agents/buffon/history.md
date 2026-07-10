# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 2419 (as of 2026-07-10)

## Current Session: 2026-07-10 — Profile Updater M3/M4/M5 Regression Lock-in (✅ APPROVE)

**Kanté's changes (Pirlo minors M3/M4/M5) locked in `src/worldcup_bot/chat/profile_updater.py`:**
- M3: `list(dict.fromkeys([*existing, *new]))` — insertion-order preserved, existing first, dedup keeps first occurrence.
- M4: `MOTES_CAP = 8`, `TEMAS_CAP = 10`, `[-CAP:]` → keep-most-recent (oldest dropped when over cap).
- M5: `max_completion_tokens = max(200, 200 * len(participants))` (was 120×N).

**Tests added:** 12 new tests in `tests/test_profile_updater.py` (4 new classes):

- `TestMotesTemasInsertionOrder` (+4): existing items precede new; dup keeps first-occurrence (existing) position; exact order `[A,B] + [B,C_new] → [A,B,C_new]` for both motes and temas.
- `TestMotesCapKeepMostRecent` (+2): exactly-at-cap keeps all; over-cap (5+6=11 unique) → 8, oldest 3 dropped, all new + in-range old survive.
- `TestTemasCapKeepMostRecent` (+2): same shape for temas (7+6=13 unique) → 10, oldest 3 dropped.
- `TestMaxCompletionTokens` (+4): N=1→200, N=2→400, N=5→1000 asserted via `call_args[1]`; same-user multi-msg counts once (N=1→200).

Import updated: `MOTES_CAP`, `TEMAS_CAP` imported alongside `update_profiles_from_conversation` for constant-name robustness.

**Outcome:** 2573 passed, 3 warnings, 0 regressions. (+12 vs prior 2561). APPROVE ✅

---

## Current Session: 2026-07-10 — Picante Per-User Profiles — QA Gate (✅ APPROVE)

**Kanté's change:** Full per-user auto-learned profiles system for picante. 3 new modules (`timeline_store.py`, `profiles.py`, `profile_updater.py`) + modifications to `picante.py`, `listener.py`, `config.py`, `__main__.py`. Feature flag OFF by default; 3 refinements vs. Pirlo's spec (incremental summarization, 2-day window, single group-timeline JSONL).

**Tests added:** 142 new tests across 5 files:

- `tests/test_timeline_store.py` (29 tests): append writes line; no-op on empty username / store_text=False; trim-on-write discards old/keeps recent; load_since filters by ts / boundary exclusive / corrupt lines skipped; last_run round-trip.
- `tests/test_profiles.py` (26 tests): load missing/corrupt/array/null → {}; valid round-trip all fields; save atomic; get_profile present/absent; UserProfile defaults and factory isolation.
- `tests/test_profile_updater.py` (33 tests): empty timeline → no AI call; AIError/malformed JSON → current unchanged; markdown fence stripped; profiles updated from multi-user conversation; updated_at set to _now; piques_recientes NOT touched; pinned_fields (all 5 scalar+list) never overwritten; motes/temas union no dupes; new user created; prompt has [username] texto lines + current profiles context; system prompt in first arg; temperature=0.3.
- `tests/test_chat.py` (+13 tests, TestPicanteUserMessageWithProfiles): no PERFILES block when profiles=None/empty/no username; PERFILES block present with author profile; [AUTOR:] label; rasgos/equipo/motes/piques_recientes in block; OTROS section with equipo; others_cap respected; author profile before OTROS; author absent but OTROS shown; exception falls back gracefully; PERFILES→CONTEXTO→ÚLTIMO order.
- `tests/test_chat_edge_cases.py` (+8 tests, TestMaybeReplyWithProfiles): flag OFF → no PERFILES in prompt; pique persisted after reply; texto truncated to 200 chars; piques truncated to cap; corrupt profiles → reply still sent; empty profiles_path → no persistence; reply uses main AI client; pique persistence failure doesn't prevent reply.
- `tests/test_config.py` (+33 tests): 7 new Settings defaults; all 7 overridable; picante_profiles_enabled helper (flag/picante/AI conditions); load_settings reads all 7 vars from env with correct defaults.

**Outcome:** 2561 passed, 3 warnings, 0 regressions. Full suite green. APPROVE ✅

---



**Kanté's change:** Prompt-only recalibration of `_SYSTEM` and the inline CONTEXTO label in `src/worldcup_bot/chat/picante.py`. Replaced the over-suppressing "EXCLUSIVAMENTE / solo de apoyo / IGNÓRALOS por completo" wording with a balanced conditional: if CONTEXTO RECIENTE is clearly related to the ÚLTIMO MENSAJE → use it (`tenlo en cuenta y aprovéchalo`); if not → ignore it completely. No logic, no gate functions, no structure changed.

**Tests added:** `tests/test_chat.py` → new class `TestPicanteSystemPrompt` (+2 tests):
- `test_system_prompt_has_conditional_context_rule`: tolerant keyword checks on `build_picante_system_prompt().lower()` — asserts "relacionado" (conditional pivot), "tenlo en cuenta"/"aprovéch" (use-it branch), "ignóralo"/"ignora" (ignore-it branch).
- `test_user_message_context_label_has_conditional_rule`: same tolerant checks on the CONTEXTO label returned by `build_picante_user_message` with prior messages present.

Guard catches: revert to "always ignore" (old EXCLUSIVAMENTE/IGNÓRALOS wording) AND drift to "always use context" (removing the ignore branch).

**Outcome:** tests/test_chat.py + tests/test_chat_edge_cases.py: 158 passed (was 156). Full suite: 2419 passed, 3 warnings, 0 regressions. APPROVE ✅

---

## Current Session: 2026-07-10 — Micky Birthday Special — QA Gate (✅ PASS)

**Kanté's change:** Micky birthday special in `src/worldcup_bot/ai/rich_image.py`.
On July 10 (every year), `run_rich_iteration` generates a 3-image celebration scene with Micky as the protagonist but does NOT promote the result into the evolution chain — `rich_modified.png`, `save_level`, `append_history`, and `append_caption` are all skipped. Output goes to `rich_micky_birthday.png`. If `micky.jpg` is absent → WARNING + graceful fallback.

**Tests added:** `tests/test_rich_image.py` → new class `TestMickyBirthdayMode` (+30 tests).

Coverage includes:
- is_micky_birthday: 6 tests (True on July 10, False on other days/months)
- micky_birthday_age: 2 tests (42 in 2026, 43 in 2027)
- find_micky_image: 2 tests (present/absent scenarios)
- edit_rich_image extra_paths: 3 tests (3-image list, ExitStack file handle closure, backward compatibility)
- build_rich_prompt micky_birthday: 4 tests (age injection, flag independence, augmentation)
- generate_rich_caption micky_birthday: 2 tests (felicitation injection, absence)
- run_rich_iteration July 10 end-to-end: 7 tests (3 images, separate output file, rich_modified untouched, level unchanged, caption greeting)
- run_rich_iteration July 10 micky.jpg absent: 2 tests (fallback to 2-image edit, no crash)
- Regressions: 2 tests (July 8 birthday unchanged, normal day unaffected)

**Outcome:** All 30 new tests PASS. test_rich_image.py: 281 passed (was 251). Full suite: 2417 passed, 3 warnings, no regressions. PASS ✅

**Key invariant guarded:** On July 10, rich_modified.png byte-content is UNCHANGED (direct filesystem assertion), load_level returns seeded value. Edge case: fresh install requires pre-seeded rich_modified.png for 3-image path to fully activate (production ready).

---

## Prior Sessions Summary (2026-07-01 to 2026-07-09)

- **2026-07-08:** KO Draw Deferral Regression Tests. 8 new tests for Kanté's match_result_is_final fix. Tests: ko_finished_draw_regular_is_not_final, ko_finished_extra_time_no_winner_is_not_final, group_stage_draw_regular_is_final, plus integration tests. All green.

- **2026-07-08:** Rich Birthday Mode — QA Gate. 14 tests in TestRichBirthdayMode for July-8 annual birthday feature. Fixed 3 pre-existing tests that broke on July 8 (injected _now to non-birthday date). Result: 251 tests passed.

- **2026-07-07:** USA-Belgium Goal Flood — Post-Mortem. 4 tests in TestVARCrossSourceRaceRegression to prevent oscillation when thread reports goal+VAR before API. Critical coverage gap: precondition requires seen_api BELOW pre-goal score (not synced). All green.

- **2026-07-01–2026-07-05:** /elecciones feature testing. 30+ tests for phase selector keyboard, knockout matrix image (PIL, twemoji CDN flags), groups text renderer, cache + message-split fixes. Multiple rework cycles by Nesta; all guarded.

- **2026-07-01–2026-07-03:** Podium image feature testing. 45 edge-case tests for initials, circular crop, crown drawing, name truncation, font fallback, photo failures, total-failure variants, text centering, tie-aware positioning, emoji selection.

---

## Key Testing Learnings (across sessions)

- **Birthday fallback date rule:** Any test asserting generic fallback caption must inject _now to non-birthday date (neither July 8 nor July 10). Without _now, datetime.now() is called; on a birthday, birthday-aware fallback is returned instead.

- **3-image path prerequisite:** edit_rich_image sets use_anchor = anchor_path is not None and paths differ. On first-ever run base==original, so use_anchor=False even with anchor passed. To assert 3 images reliably, pre-seed state_dir/rich_modified.png.

- **Cross-source VAR regression coverage gap:** Two-source tests must vary seen_api to be BELOW pre-goal score. Oscillation triggers only when lagging source is behind at disallowed time. Tests seeding seen_api at pre-VAR score miss the bug.

- **KO-draw deferral stages:** Covers LAST_32, LAST_16, QUARTER_FINALS, SEMI_FINALS, FINAL, THIRD_PLACE. Group-stage draws remain valid finals.

- **timeline_store._now injection:** Module-level `_now` callable must be patched via `patch("worldcup_bot.chat.timeline_store._now", new=lambda: _FIXED_DT)`. The trim cutoff depends on it; tests that don't care about trim must use large window_days or patch _now to a datetime far enough from the entries' timestamps.

- **profile_updater _now injection:** Unlike timeline_store, profile_updater's `_now` is a keyword parameter `_now=lambda: dt`. Pass directly when calling `update_profiles_from_conversation(...)`.

- **maybe_reply pique persistence guard:** To trigger pique persistence, three conditions must all hold: `picante_profiles_enabled(settings)=True`, `profiles is not None`, `author_username != ""`. Profiles is None when profiles_path is empty string (guard in code: `if profiles_path: profiles = load_profiles(...)`).

- **others_cap in build_picante_user_message:** The OTROS section only renders users with `equipo` OR `tono` set; users with only `rasgos`/`motes` are collected in seen_in_buffer but produce no `others_lines` entry. Always give others at least one of equipo/tono to verify cap behavior.

- **M4 cap drop order:** `[-CAP:]` on `list(dict.fromkeys([*existing, *new]))` drops the OLDEST (leftmost/existing) entries first. To test the drop, use existing(E) + new(N) where E+N > CAP with zero overlap; oldest E items beyond (E+N-CAP) are absent, all new items survive. (e.g. MOTES_CAP=8: 5 old + 6 new = 11 → drops old1..old3, keeps old4,old5,new1..new6).

- **M5 participant count:** `participants = list({m["username"] for m in timeline_messages if m.get("username")})` — unique non-empty usernames only. Same user sending 3 messages counts as N=1 → max_tokens=200.
