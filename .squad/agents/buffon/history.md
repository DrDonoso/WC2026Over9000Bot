# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 2609 (as of 2026-07-10)

## Current Session: 2026-07-10 — /calcularperfiles + _run_profile_update QA Gate (✅ APPROVE)

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
