# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 2419 (as of 2026-07-10)

## Current Session: 2026-07-10 — Picante Context Recalibration — QA Gate (✅ APPROVE)

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
