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

**Both features shipped on `feat/final-weekend`:**
- Feature 1 (THIRD_PLACE scoring) ✅ — Pirlo approved, full suite green (2634→2637→2680→2684 as Feature 2 added)
- Feature 2 (Final ceremony) ✅ — Pirlo approved, Buffon verified coverage (4 gap-filling tests added)
- **Ready for merge to main post-weekend**

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