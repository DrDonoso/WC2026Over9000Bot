# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 2684 (as of 2026-07-17)

## TEAM UPDATE — 2026-07-17

**Both features shipped on `feat/final-weekend`:**
- Feature 1 (THIRD_PLACE scoring) — gap-filled 3 tests, full approval ✅
- Feature 2 (Final ceremony) — gap-filled 4 tests, full approval ✅
- **Both on track for merge to main post-weekend**

---

## Current Session: 2026-07-17 — Feature 2: Final Ceremony QA Gate (✅ APPROVE)

**Branch:** `feat/final-weekend`  
**Kanté's commit:** `00520cd` — `final_ceremony.py` + `poll_final_ceremony_job` + `cmd_granfinal` + 43 tests.

**Suite on arrival:** 2680 passed ✓ (matches Kanté's reported count).

**Review findings:**

1. **`test_api_error_is_handled_gracefully` was a stub** — the test set up mocks, configured a `FootballAPIError` side_effect, but never called `poll_final_ceremony_job` and contained zero assertions. Dead test, zero coverage value.

2. **`cmd_granfinal` `_send_pre_final` failure path untested** — when `_send_pre_final` raises after API succeeds, the handler should report `❌` to the user and leave `pre_final_sent=False`. No test existed for this.

3. **`cmd_granfinal` `_send_campeon_and_podio` failure path untested** — same gap on the campeon path: error reply + `campeon_sent` stays False.

**Coverage gaps filled (4 tests added, commit `13fdcca`):**

- `TestPollFinalCeremonyJobAPIErrorComplete::test_football_api_error_does_not_raise_and_sends_nothing` — actually calls `poll_final_ceremony_job`, asserts no send functions called, flags stay False.
- `TestPollFinalCeremonyJobAPIErrorComplete::test_football_api_error_does_not_persist_state` — asserts state file is NOT created on API error.
- `TestCmdGranfinalSendFailures::test_send_pre_final_failure_reports_error_flag_not_set` — `_send_pre_final` raises → error reply + `pre_final_sent=False`.
- `TestCmdGranfinalSendFailures::test_send_campeon_failure_reports_error_flag_not_set` — `_send_campeon_and_podio` raises → error reply + `campeon_sent=False`.

**Note on admin-gating:** Charter mentioned `/granfinal` should be admin-gated; the source has no such guard. Since I cannot touch source files, this is flagged for Pirlo/DrDonoso to address if desired — it does not block approval as the design doc doesn't explicitly require it.

**Final suite:** 2684 passed, 3 warnings, 0 regressions. APPROVE ✅

**Learnings:**
- Always check async test stubs that have `@pytest.mark.asyncio` but never `await` the function under test — they pass vacuously.
- Error-handling paths in command handlers (after a successful API call but a failing send) are a systematic gap: always add them explicitly.
- `_football_client(context)` reads from `bot_data["football_client"]` first, falls back to `make_client()`. Tests that need the fallback path just need to patch `make_client`.

---

## Previous Session: 2026-07-17 — THIRD_PLACE (3.º/4.º puesto) QA Gate (✅ APPROVE)

**Branch:** `feat/final-weekend`  
**Current test count (pre-session):** 2637 (as of 2026-07-17)

## Current Session: 2026-07-17 — THIRD_PLACE (3.º/4.º puesto) QA Gate (✅ APPROVE)

**Branch:** `feat/final-weekend`  
**Kanté's change:** Added `THIRD_PLACE` knockout stage (5 pts), tolerant KO validation (missing keys default to `[]`, unknown keys still skip), and `third_place` entry in elecciones display order (between `semi_finals` and `final`).

**Suite result on arrival:** 2634 passed (Kanté's reported count ✓).

**Coverage gaps found and filled:**

1. **`test_empty_third_place_pick_no_crash_and_zero_pts`** (in `TestScoreKnockoutThirdPlace`): `third_place: []` — the stored default value — produces 0 pts and empty detail with no exception. The design explicitly calls out EMPTY pick as a required case; none of Kanté's tests covered `{"third_place": []}` directly.

2. **`test_all_six_stages_correct_sums_to_24`** (in `TestScoreKnockoutAllStagesIntegration`): All 6 stages correct → 1+2+3+5+5+8=24 pts. Verifies no double-count between SEMI_FINALS and THIRD_PLACE and confirms FINAL=8 holds in the integration path. The existing `test_all_stages_correct_sums_correctly` only covered 5 stages (19 pts, third_place absent).

3. **`test_missing_and_unknown_key_user_skipped`** (in `TestLoadKnockoutTolerantValidation`): `round_of_16` missing + `typo_key` unknown → user SKIPPED. The design spec says "missing + unknown together → SKIPPED (unknown dominates)"; Kanté only tested unknown-alone.

**Final count:** 2637 passed, 3 warnings, 0 regressions. APPROVE ✅

**Commit:** `be72151` — `tests: fill THIRD_PLACE coverage gaps (empty pick, 6-stage sum, missing+unknown)`

---

## Previous Session: 2026-07-13 — /perfil inline keyboard + cb_perfil_select QA Gate (✅ APPROVE)

**Kanté's change:** `/perfil` no-args branch now shows an `InlineKeyboardMarkup` (one button per profile sorted alphabetically, 2 per row) with text `@{username}` and `callback_data="perfil:{username}"` instead of a plain text list. No-args + empty profiles now replies with the same "No hay perfiles todavía…" hint. New `cb_perfil_select` callback (pattern `r"^perfil:"`) answers the query, loads the selected profile, and edits the message with `_format_profile(profile)` (no `reply_markup` → keyboard removed); not-found → "Ese perfil (@{username}) ya no existe."; malformed/error → graceful with "💥" reply.

**Tests updated (2 broken → green):**
- `test_no_args_empty_profiles_replies_simple_usage` → renamed `test_no_args_empty_profiles_replies_no_profiles_hint`: asserts `"No hay perfiles todavía"` + `"PICANTE_PROFILES_ENABLED"` + `"04:00"` (was asserting `"Uso: /perfil @usuario"`).
- `test_no_args_with_existing_profiles_lists_them`: now asserts `text == "Elige un perfil:"` + `isinstance(markup, InlineKeyboardMarkup)` + buttons contain `"@pepe"` / `"perfil:pepe"` (was asserting plain text list).

**Tests added: 9 new tests in `tests/test_handlers.py` → new class `TestCbPerfilSelect`:**
- `test_found_profile_answer_is_awaited`: `query.answer()` awaited on success.
- `test_found_profile_edits_message_with_profile_text`: `edit_message_text` called with `"🕵️ Perfil de @pepe"` + key fields.
- `test_found_profile_no_reply_markup_keyboard_removed`: `reply_markup` absent from `edit_message_text` kwargs (keyboard removed).
- `test_not_found_edits_with_ya_no_existe`: ghost user → `"ya no existe"` + `"@ghost"` in text.
- `test_malformed_data_empty_username_sends_hint`: `"perfil:"` → `"vacío"` in reply.
- `test_malformed_data_no_colon_sends_hint`: `"perfil-bad"` → `"inesperados"` in reply.
- `test_load_profiles_raises_no_exception_propagates`: RuntimeError → no exception escapes.
- `test_load_profiles_raises_sends_error_edit`: RuntimeError → `"💥"` + `"Error mostrando el perfil"` in edit.
- `test_uses_picante_profiles_path_from_bot_data`: `bot_data["picante_profiles_path"]` passed to `load_profiles`.

**Imports added to `tests/test_handlers.py`:** `from telegram import InlineKeyboardMarkup`; `cb_perfil_select` added to handlers import block.

**Outcome:** 2618 passed, 3 warnings, 0 regressions (+9 vs prior 2609). APPROVE ✅

---

## Learnings

- `InlineKeyboardMarkup` instances are real objects (not MagicMock) even in handler tests — import from `telegram` and use `isinstance()` to assert type.
- To assert keyboard is REMOVED after `edit_message_text(text)` (no kwargs): check `"reply_markup" not in call.kwargs`.
- `call.kwargs["reply_markup"]` (not `call_args[1]["reply_markup"]`) is the idiomatic way to access keyword args via pytest-style call inspection.
- Tolerant KO validation (missing keys default to `[]`, unknown keys skip) must be tested both for the happy path (missing key → loaded) and the rejection path (unknown key → skipped, missing+unknown combo → skipped). Kanté consistently covered the individual cases but skipped the combination.
- The design spec "EMPTY pick → 0/no crash" is a distinct test case from "missing key → 0/no crash"; the first validates the stored `[]` default is handled gracefully, the second validates the validator correctly fills in the default.
- Always add a 6-stage integration test whenever a new stage is added — the old N-stage sum test becomes stale and doesn't prove the new total is correct.

---



**Kanté's change:** `/perfil` no-args branch now shows an `InlineKeyboardMarkup` (one button per profile sorted alphabetically, 2 per row) with text `@{username}` and `callback_data="perfil:{username}"` instead of a plain text list. No-args + empty profiles now replies with the same "No hay perfiles todavía…" hint. New `cb_perfil_select` callback (pattern `r"^perfil:"`) answers the query, loads the selected profile, and edits the message with `_format_profile(profile)` (no `reply_markup` → keyboard removed); not-found → "Ese perfil (@{username}) ya no existe."; malformed/error → graceful with "💥" reply.

**Tests updated (2 broken → green):**
- `test_no_args_empty_profiles_replies_simple_usage` → renamed `test_no_args_empty_profiles_replies_no_profiles_hint`: asserts `"No hay perfiles todavía"` + `"PICANTE_PROFILES_ENABLED"` + `"04:00"` (was asserting `"Uso: /perfil @usuario"`).
- `test_no_args_with_existing_profiles_lists_them`: now asserts `text == "Elige un perfil:"` + `isinstance(markup, InlineKeyboardMarkup)` + buttons contain `"@pepe"` / `"perfil:pepe"` (was asserting plain text list).

**Tests added: 9 new tests in `tests/test_handlers.py` → new class `TestCbPerfilSelect`:**
- `test_found_profile_answer_is_awaited`: `query.answer()` awaited on success.
- `test_found_profile_edits_message_with_profile_text`: `edit_message_text` called with `"🕵️ Perfil de @pepe"` + key fields.
- `test_found_profile_no_reply_markup_keyboard_removed`: `reply_markup` absent from `edit_message_text` kwargs (keyboard removed).
- `test_not_found_edits_with_ya_no_existe`: ghost user → `"ya no existe"` + `"@ghost"` in text.
- `test_malformed_data_empty_username_sends_hint`: `"perfil:"` → `"vacío"` in reply.
- `test_malformed_data_no_colon_sends_hint`: `"perfil-bad"` → `"inesperados"` in reply.
- `test_load_profiles_raises_no_exception_propagates`: RuntimeError → no exception escapes.
- `test_load_profiles_raises_sends_error_edit`: RuntimeError → `"💥"` + `"Error mostrando el perfil"` in edit.
- `test_uses_picante_profiles_path_from_bot_data`: `bot_data["picante_profiles_path"]` passed to `load_profiles`.

**Imports added to `tests/test_handlers.py`:** `from telegram import InlineKeyboardMarkup`; `cb_perfil_select` added to handlers import block.

**Outcome:** 2618 passed, 3 warnings, 0 regressions (+9 vs prior 2609). APPROVE ✅

---

## Learnings

- `InlineKeyboardMarkup` instances are real objects (not MagicMock) even in handler tests — import from `telegram` and use `isinstance()` to assert type.
- To assert keyboard is REMOVED after `edit_message_text(text)` (no kwargs): check `"reply_markup" not in call.kwargs`.
- `call.kwargs["reply_markup"]` (not `call_args[1]["reply_markup"]`) is the idiomatic way to access keyword args via pytest-style call inspection.

---



**Kanté's change:** New hidden command `cmd_calcularperfiles` in `src/worldcup_bot/__main__.py` (~line 377), backed by the extracted shared helper `_run_profile_update` (~line 222). The helper is the core AI pipeline (load_since → AI pass → save_profiles → advance last_run); the job wraps it best-effort; the command exposes it on-demand with user feedback.

**Tests added:** 23 new tests in `tests/test_main_calcularperfiles.py` → 3 new classes:

- `TestCmdCalcularPerfiles` (+11):
  - `test_feature_off_replies_disabled_message`: OFF → reply has `PICANTE_PROFILES_ENABLED` + `No hay nada que calcular`; `_run_profile_update` not called.
  - `test_feature_off_full_reply_text`: exact substring `La función de perfiles está desactivada`.
  - `test_feature_on_n_gt_0_sends_progress_message`: N>0 → reply list contains `⏳ Calculando perfiles`.
  - `test_feature_on_n_gt_0_sends_success_with_count`: N=3 → `✅ Perfiles actualizados: 3 usuario(s) procesado(s).` exact.
  - `test_feature_on_n_gt_0_two_replies_sent`: exactly 2 replies (progress + result).
  - `test_feature_on_zero_sends_no_new_messages_reply`: 0 → `ℹ️ No hay mensajes nuevos desde la última actualización; perfiles sin cambios.` exact.
  - `test_feature_on_zero_sends_progress_before_no_new_msg`: still sends `⏳` even when 0.
  - `test_helper_raises_sends_friendly_error_reply`: raises → `💥 Error calculando los perfiles, revisa los logs.` exact.
  - `test_helper_raises_does_not_propagate`: no exception escapes.
  - `test_calcularperfiles_not_in_help_commands`: `calcularperfiles` not in `_HELP_COMMANDS.lower()`.
  - `test_calcularperfiles_registered_in_main`: `CommandHandler("calcularperfiles", cmd_calcularperfiles)` in source.

- `TestRunProfileUpdateHelper` (+8):
  - `test_no_messages_returns_0`: empty timeline → returns 0.
  - `test_no_messages_ai_not_called`: `update_profiles_from_conversation` NOT called.
  - `test_no_messages_last_run_advanced`: `save_last_run` called even with 0 messages.
  - `test_with_messages_calls_ai`: messages present → AI called once.
  - `test_with_messages_returns_distinct_participant_count`: 3 messages from 2 users → result=2.
  - `test_messages_without_username_excluded_from_count`: missing/empty username → not counted.
  - `test_no_profile_ai_client_raises_runtime_error`: absent client → `RuntimeError("no profile_ai_client")` raised (not swallowed).

- `TestProfileUpdateJobRegression` (+5):
  - `test_job_swallows_run_helper_exception`: RuntimeError from helper → job silent.
  - `test_job_swallows_arbitrary_exception`: ValueError from helper → job silent.
  - `test_job_skips_when_feature_off`: OFF → helper not called.
  - `test_job_skips_when_no_profile_ai_client`: no client → helper not called.
  - `test_job_calls_helper_when_feature_on_and_ai_configured`: ON + client → helper awaited.

**Outcome:** 2609 passed, 3 warnings, 0 regressions (+23 vs prior 2586). APPROVE ✅

---



**Kanté's change:** New hidden admin command `cmd_perfil` in `src/worldcup_bot/bot/handlers.py` (~line 1373). Loads `picante_profiles.json` via `load_profiles`, parses `context.args[0].strip().lstrip("@").lower()`, and renders all UserProfile fields as plain text. Not listed in `/start` or `/help`.

**Tests added:** 13 new tests in `tests/test_handlers.py` → new class `TestCmdPerfil`:

- `test_found_profile_reply_contains_key_fields`: Full fixture profile; asserts 🕵️ header + rasgos/equipo/motes/temas/tono/pique texto all present.
- `test_at_prefix_and_mixed_case_resolved_to_lowercase_key`: `@Pepe` → finds `"pepe"`.
- `test_username_without_at_also_resolves`: `PEPE` (no `@`) → finds `"pepe"`.
- `test_not_found_sends_not_found_message_with_available_list`: `@nobody` → exact prefix `"No hay perfil para @nobody"` + `@pepe` in available list.
- `test_no_args_empty_profiles_replies_simple_usage`: Empty profiles + no args → `"Uso: /perfil @usuario"` without `"Perfiles disponibles"`.
- `test_no_args_with_existing_profiles_lists_them`: Profiles present + no args → usage + `"Perfiles disponibles"` + `"@pepe"`.
- `test_empty_profiles_with_arg_sends_config_hint`: Arg given + empty profiles → `"No hay perfiles todavía"` + `"PICANTE_PROFILES_ENABLED"` + `"04:00"`.
- `test_unexpected_error_sends_friendly_reply`: `load_profiles` raises → `"❌"` + `"Error inesperado"` + `"logs"` in reply; no exception propagates.
- `test_perfil_not_in_start_help`: `/start` help text does not contain `"perfil"` (hidden guard).
- `test_empty_fields_shown_as_dash`: UserProfile with no rasgos/equipo/tono → each line shows `"—"`.
- `test_updated_at_shown_in_reply`: `updated_at` value appears verbatim in footer.
- `test_piques_recientes_block_rendered`: `"Piques recientes:"` block present with ts + texto.
- `test_uses_picante_profiles_path_from_bot_data`: `bot_data["picante_profiles_path"]` is the path passed to `load_profiles`.

**Outcome:** 2586 passed, 3 warnings, 0 regressions (+13 vs prior 2573). APPROVE ✅

---

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



_See history-archive.md for prior sessions (2026-07-01 to 2026-07-09)._

