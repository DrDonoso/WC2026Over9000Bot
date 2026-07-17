# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2634 tests ✅

## Current Session: 2026-07-17 — Feature 1: THIRD_PLACE stage scoring

**Feature:** Added `THIRD_PLACE` as a scored knockout stage (5 pts), plus tolerant knockout validation.

**Key changes:**
- `src/worldcup_bot/data/stages.py`: Added `("THIRD_PLACE", "3.º y 4.º Puesto", 5)` to `KNOCKOUT_STAGES` between `SEMI_FINALS` and `FINAL`; added `"THIRD_PLACE": "third_place"` to `STAGE_YAML_KEYS`.
- `src/worldcup_bot/porra/predictions.py`: Tolerant knockout validation — UNKNOWN/extra keys → skip user (typo guard preserved); MISSING keys → default to `[]` (user NOT skipped). All `_KNOCKOUT_YAML_KEYS` guaranteed in stored knockout dict.
- `src/worldcup_bot/porra/elecciones.py`: Added `"third_place": "3.º y 4.º Puesto"` to `_PHASE_LABELS`; inserted `"third_place"` between `"semi_finals"` and `"final"` in `_PHASE_ORDER`; added `"third_place": "🥉 3.º Y 4.º PUESTO — ¿Quién gana?"` to `_KNOCKOUT_HEADERS`.
- `src/worldcup_bot/bot/formatters.py`: Simplified `_KNOCKOUT_STAGE_NAMES` — removed redundant `| {"THIRD_PLACE"}` since THIRD_PLACE is now in `KNOCKOUT_STAGES`.
- `data/predictions.template.yml`: Added `third_place: []` to both example participants and schema comment block.
- Tests: Fixed 2 broken tests; added 16 new tests covering THIRD_PLACE scoring, tolerant validation, and phase order.

**Tolerant validation semantics (exact):**
- `extra_keys = set(knockout_raw.keys()) - _KNOCKOUT_YAML_KEYS` → if non-empty → skip user
- `stored_knockout.setdefault(key, [])` for all `_KNOCKOUT_YAML_KEYS` → fills missing keys
- GROUP validation unchanged: must be exactly `GROUPS`, no tolerance

**Branch:** `feat/final-weekend`
**Test result:** 2634 passed (baseline: 2618; +16 new tests)

**Owner action required:** Fill `third_place: [TLA]` picks in live `data/predictions.yml` before FRA vs ENG kickoff (18/07 23:00 Madrid time).

---

## Learnings

- Tolerant-validation pattern: reject unknown extra keys, silently fill missing keys. Keeps typo-guard while allowing incremental YAML authoring.
- KNOCKOUT_STAGES / STAGE_YAML_KEYS are the single source of truth; adding a stage there propagates automatically to scoring, API client, engine, history.
- The `_KNOCKOUT_STAGE_NAMES` frozenset in formatters.py now derives purely from KNOCKOUT_STAGES (no manual extras needed).
- Final ceremony pattern: new module `src/worldcup_bot/bot/final_ceremony.py` with pure builder functions + all copy constants + state helpers (`load_ceremony_state`/`save_ceremony_state`). Job/command logic in `__main__.py`. State file: `final_ceremony_state.json` with `{"pre_final_sent": false, "campeon_sent": false}`. Job name: `poll_final_ceremony_job` (60s interval). Command: `/granfinal` (hidden, not in /start help). PRE-FINAL trigger: `now_utc >= kickoff_utc` OR status IN_PLAY/PAUSED/FINISHED. CAMPEÓN trigger: status FINISHED AND winner set. Helpers `_send_pre_final` / `_send_campeon_and_podio` shared between job and command.

---

## TEAM UPDATE — 2026-07-17

**Three features shipped and deployed:**
- Feature 1 (THIRD_PLACE scoring) ✅ — `feat/final-weekend` merged to main, deployed CI #29576019606
- Feature 2 (Final ceremony) ✅ — `feat/final-weekend` merged to main, deployed CI #29576019606
- Feature 3 (Rich Apex + Death) ✅ — `feat/rich-apex-death` rebased + pushed to origin/main, deployed CI #29584668354 in_progress

**All approvals complete (Pirlo + Buffon). CI deploys automated.**

---

## Prior Sessions

### 2026-07-13 — /perfil Inline Keyboard

**Feature:** /perfil (no-args) now shows an InlineKeyboardMarkup with profile buttons instead of plain text list.

**Key changes:**
- Extracted _format_profile() helper for shared rendering
- Added InlineKeyboardMarkup with buttons (2 per row, alphabetically sorted)
- New cb_perfil_select() callback removes keyboard via dit_message_text without eply_markup
- Backward compatible: /perfil @usuario unchanged

**Files:** handlers.py, __main__.py
**Test result:** 2618 passed, 0 regressions

---

See .squad/agents/kante/history-archive.md for detailed Micky Birthday Special, Picante profile system, and related entries (2026-07-10 onwards).

---

## Learnings (appended 2026-07-17)

**Apex / Death special-day pattern:**
- Both use date constants (MONTH/DAY), a detection function (`is_rich_apex` / `is_rich_death`), and a CLAUSE constant appended to `build_rich_prompt`.
- `RICH_APEX_CLAUSE` contains a `{country}` placeholder formatted at call time with `apex_country or "the champion nation"` — always safe even with empty winners.
- **Death uses a separate file** (`rich_death.png`) and does NOT promote into the evolution chain (no `save_level`/`append_history`/`append_caption`), mirroring the Micky birthday pattern exactly.
- **Apex uses the NORMAL promote path** (rich_modified.png, save_level, append_history, append_caption) — it is the culmination of the escalation, not a side-branch.
- **Death caption system-prompt swap:** `generate_rich_caption` now accepts `death: bool`; when True, uses `RICH_DEATH_CAPTION_PROMPT` instead of `RICH_CAPTION_PROMPT` (sincere farewell tone replaces the cocky persona entirely).
- **Themes generation is skipped** for both apex (the apex clause handles the winning country directly) and death (a lying-in-state scene needs no party props). Guard: `not apex and not death` in the `if winners and ...` condition.
- `anchor_arg` is forced to `original` for apex and death (same as Micky birthday), ensuring face consistency on the special days.
- Azure content moderation blocks the death caption if the system prompt uses "has fallecido / desde el más allá / último mensaje / afterlife / from beyond" — this reads as a jailbreak/roleplay bypass. Fix: reframe as a heartfelt despedida (farewell) with no death/afterlife wording. The image already shows the scene; the caption only needs to be a love message. Softening the user instruction the same way ("Despídete del grupo..." not "desde el más allá") is equally important.
- Windows console requires `sys.stdout.reconfigure(encoding='utf-8')` to print emojis in throwaway scripts.

**Apex loser-trampling refinement (2026-07-17):**
- `RICH_APEX_TRAMPLE_SENTENCE` is a separate constant with a `{loser}` placeholder. It is appended in `build_rich_prompt` ONLY when `apex_loser` is non-empty — entirely omitted otherwise (no dangling `{loser}`).
- `apex_loser` flows through `build_rich_prompt`, `generate_rich_caption`, and `run_rich_iteration(losers=)`. Derived as `losers[0] if (apex and losers) else ""`.
- `_fetch_yesterday_losers` in `__main__.py` mirrors `_fetch_yesterday_winners` (home_name when winner==AWAY_TEAM, away_name when winner==HOME_TEAM, skips draws/None).
- Azure content moderation blocks violent language like "TRAMPLING and STOMPING … grinding into the ground". Softer phrasing ("lies discarded beneath his feet as a trophy") passes the filter successfully.