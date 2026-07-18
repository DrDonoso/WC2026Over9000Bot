### 2026-07-17T15:13:00+02:00: Architecture & Correctness Review — feat/rich-apex-death

**By:** Pirlo (Lead / Tech Lead)  
**Branch:** `feat/rich-apex-death`  
**Commits reviewed:** `a76e222`, `7680612`, `79a0253` (3 commits vs main)  
**Author:** Kanté  
**Requested by:** DrDonoso

---

## VERDICT: ✅ APPROVED

The implementation is clean, correct, and follows the existing patterns precisely.

---

## Review by Focus Area

### 1. Date detection ✅

- `is_rich_apex`: `month==7 and day==20` — fires only on July 20.
- `is_rich_death`: `month==7 and day==21` — fires only on July 21.
- No collision: Rich birthday is 7/8, Micky birthday is 7/10. All four dates are mutually exclusive.
- Precedence in `run_rich_iteration` is clean: `if micky_birthday → elif death → else (normal+apex)`. Output chain: `if micky_birthday: return → if death: return → normal/apex path`. Since the dates never overlap, precedence is academic but correctly ordered.

### 2. Chain handling ✅ (critical)

- **APEX (7/20)**: falls through to the normal promote path — writes `rich_modified.png`, calls `save_level()`, `append_history()`, `append_caption()`. Correct as the culmination of the daily escalation arc.
- **DEATH (7/21)**: writes to `rich_death.png` (separate file), returns early BEFORE the normal path. Does NOT call `save_level` / `append_history` / `append_caption`. `rich_modified.png` is untouched — the evolution chain is preserved for any hypothetical next-day continuation. Mirrors the Micky birthday pattern exactly. Confirmed: death truly leaves the chain untouched.

### 3. Winner/loser plumbing ✅

- `apex_country = winners[0] if (apex and winners) else ""` — safe on empty/None lists (`and winners` short-circuits). ✓
- `apex_loser = losers[0] if (apex and losers) else ""` — same pattern. ✓
- `_fetch_yesterday_losers`: correctly inverts the winner logic (`home_name` when `AWAY_TEAM` wins, `away_name` when `HOME_TEAM` wins, skips draws/None). Mirrors `_fetch_yesterday_winners` structure. Best-effort (never raises). ✓
- On July 20, `day_offset=-1` fetches July 19 matches (the Final day). The match will be FINISHED by 10:00 the next morning — no real risk.

### 4. Graceful degradation ✅

- Empty country → `RICH_APEX_CLAUSE.format(country="the champion nation")` — no dangling `{country}`.
- Empty loser → trample sentence guarded by `if apex_loser:` — omitted entirely, no dangling `{loser}`.
- Caption generation has `try/except` fallbacks for both apex (`"🌍 El ser más rico del universo. Todo es mío."`) and death (`"🕊️ Me marcho... os quiero a todos. Gracias por tanto. ❤️"`).
- Failed AI caption never breaks the image send.
- `generate_rich_caption` constructs `country_sentence`/`loser_sentence` as empty strings when inputs are empty — no dangling text.

### 5. __main__ auto-behaviour ✅

- `_evolve_and_send_rich_image` calls both `_fetch_yesterday_winners` and `_fetch_yesterday_losers`, passes both to `run_rich_iteration`. ✓
- Sends `out_path` as-is: apex → `rich_modified.png`, death → `rich_death.png`. ✓
- No new commands added. No interference with `rich_image_job`, `cmd_evil_sanchez`, or any other job/handler.
- Seam is clean: Telegram layer (`__main__`) handles fetch + send; football client stays in `__main__` via `_fetch_yesterday_*`; rich-image logic stays in `rich_image.py`.

### 6. Cost/behaviour ✅

- `generate_wealth_themes` skipped on both apex and death (`and not apex and not death`). No redundant AI calls.
- Single image generation + single caption generation per iteration. No double-generation.

### 7. Production risk on 7/20–7/21 ✅

- **Timezone**: `now` uses `pytz.timezone(settings.timezone)` — respects the configured group timezone. The 10:00 job will fire with the correct date.
- **Match availability**: The Final (July 19 evening) will be FINISHED in the Football Data API well before 10:00 on July 20. No real risk.
- **Death day (7/21)**: `_fetch_yesterday_losers` looks at July 20 (no matches) → returns `[]`. Death doesn't use winners/losers, so this is irrelevant.

---

## Non-blocking nits

1. **`using_anchor or True` is always `True`** (line ~917 in the death prompt branch). The expression is redundant — `anchor=True` would be clearer. Not a bug, just noise. The comment already says "always try to anchor face for death", so intent is correct.

---

## Tests (skim)

~985 lines added across `TestRichApexMode` and `TestRichDeathMode`. Coverage looks solid:
- Date predicates (true/false, boundary days, month-transposition guards)
- `build_rich_prompt` with all flag combinations (apex/death on/off, country/loser empty/present, clause ordering)
- `generate_rich_caption` system prompt swap (death uses `RICH_DEATH_CAPTION_PROMPT`, apex keeps cocky default)
- `run_rich_iteration` end-to-end: output file identity, level increment/no-increment, history/captions append/no-append, prompt content, theme skipping, fallback captions
- Buffon owns test depth; from an architecture perspective, the test contracts match the code contracts.

---

### 2026-07-17T13:54:00+02:00: QA Verdict — feat/rich-apex-death (Apex & Death special days)

**Reviewer:** Buffon (QA)  
**Branch:** `feat/rich-apex-death`  
**Date:** 2026-07-17  
**Verdict:** ✅ **APPROVE** (with tests added by reviewer)

---

## Summary

Kanté's implementation of the Apex (July 20) and Death (July 21) special days is
solid and well-covered.  The code logic is correct: Apex uses the normal promote
path; Death mirrors Micky (separate file, chain untouched).

One gap was found and filled by QA (Buffon): `_fetch_yesterday_losers` in
`__main__.py` had zero test coverage.  13 focused unit tests were added to
`tests/test_main_calcularperfiles.py`.

---

## Coverage Audit

### ✅ Covered by Kanté's tests (tests/test_rich_image.py)

| Area | Tests | Status |
|------|-------|--------|
| `is_rich_apex` boundaries (true 7/20, false 7/19, 7/21, 7/8, 1/20) | 6 | ✅ |
| `is_rich_death` boundaries (true 7/21, false 7/20, 7/22, 7/8, 1/21) | 6 | ✅ |
| `build_rich_prompt(apex=True)` — language, country, loser, order, no-dangling-braces | 10 | ✅ |
| `build_rich_prompt(death=True)` — language, non-gory, clause-before-anchor | 6 | ✅ |
| `generate_rich_caption(apex=True)` — system prompt, country, loser, no-loser | 5 | ✅ |
| `generate_rich_caption(death=True)` — system prompt swap, farewell instruction | 3 | ✅ |
| `run_rich_iteration` Apex (July 20): promotes to `rich_modified.png`, level++, no themes, losers in prompt, no dangling braces, empty-winners/losers | 9 | ✅ |
| `run_rich_iteration` Death (July 21): `rich_death.png`, NOT `rich_modified.png`, level unchanged, history/captions untouched, death system prompt, fallback caption, no themes | 8 | ✅ |
| `RICH_DEATH_CAPTION_PROMPT` constant content checks | 4 | ✅ |

### ❌ Gap found (filled by QA)

| Area | Tests added | File |
|------|-------------|------|
| `_fetch_yesterday_losers` — home/away wins, draw excluded, None winner excluded, IN_PLAY excluded, SCHEDULED excluded, empty list, multiple matches, all-draws, API exception (never raises), unexpected exception, day_offset=-1, return type | 13 | `tests/test_main_calcularperfiles.py` |

---

## Test Counts

| Point | Count |
|-------|-------|
| Before this feature (main) | 2684 |
| After Kanté's tests (branch, before QA) | 2740 |
| After QA additions | **2753** |

All 2753 tests pass (`python -m pytest -q`: `2753 passed, 3 warnings`).

---

## No Code Defects Found

The implementation is correct:
- Apex uses normal promote path (level++, `rich_modified.png`, history/captions appended)
- Death mirrors Micky exactly (separate `rich_death.png`, chain untouched)
- `RICH_DEATH_CAPTION_PROMPT` is swapped in as system message for death captions
- Apex clause correctly formats `{country}` / `{loser}` (no dangling braces on empty inputs)
- `_fetch_yesterday_losers` is best-effort and never raises
- `winners` and `losers` are correctly wired into `run_rich_iteration` in `__main__`

No lockout required.  No DIFFERENT agent revision needed.

---

## Commit

Tests committed on `feat/rich-apex-death` — see commit for SHA.

---

### 2026-07-17T14:27:00+02:00: Maldini — Deploy Decision: feat/rich-apex-death → main
**Date:** 2026-07-17  
**Status:** ✅ COMPLETE — rebased + pushed + CI triggered

---

## Merge Performed (local)

- **Merge type:** `--ff-only` (fast-forward) — succeeded cleanly
- **Pre-merge main HEAD:** `f268574`
- **Post-merge main HEAD (local):** `3a58983` ← new tip
- **Commits merged:** `a76e222`, `7680612`, `79a0253`, `3a58983`
- **Files changed:** `src/worldcup_bot/__main__.py`, `src/worldcup_bot/ai/rich_image.py`, `tests/test_main_calcularperfiles.py`, `tests/test_rich_image.py` (+1435 / −14)

---

## Push Result: REJECTED

```
! [rejected]   main -> main (fetch first)
error: failed to push some refs to 'https://github.com/DrDonoso/WC2026Over9000Bot.git'
hint: Updates were rejected because the remote contains work that you do not have locally.
```

### Root cause

After the local `f268574` bookkeeping commit was added, `github-actions[bot]` landed an automated changelog commit on `origin/main`:

```
159e65a  docs: update changelog for 20260717 [skip ci]
         CHANGELOG.md  +10 lines, 1 file changed
         Author: github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>
         Date:   Fri Jul 17 11:13:31 2026 +0000
```

**Divergence diagram:**

```
origin/main:  a73f12e → 159e65a
local  main:  a73f12e → f268574 → a76e222 → 7680612 → 79a0253 → 3a58983
```

---

## Safe Options (no force-push)

**Option A — `git pull --no-rebase origin main` then push**  
Creates a merge commit absorbing `159e65a` into local main, then pushes normally.  
Pros: Preserves full history. Cons: Adds a trivial merge commit for a bot changelog entry.

**Option B — `git rebase origin/main` then push**  
Rebases local commits (`f268574`..`3a58983`) on top of `159e65a`.  
Pros: Linear history, no merge commit. Cons: rewrites local SHAs (safe since none were pushed yet).

**Option C — Coordinate with David**  
Pause and await explicit approval of Option A or B before proceeding.

---

## Auth / CI

- **GitHub auth:** DrDonoso (active) ✓ — `gh auth status` confirmed before push attempt.
- **Feature branch:** `feat/rich-apex-death` left intact per instructions.
- **CI run:** None triggered yet (push was rejected before CI could fire).
- **No force-push was attempted.** 

---

## Resolution (David approved Option B)

- **Action:** `git rebase origin/main` — clean, no conflicts (bot only touched `CHANGELOG.md`)
- **Rebased HEAD (new main tip):** `cba7fae` (rebased `3a58983`)
- **Push range:** `159e65a..cba7fae  main -> main` — accepted, no force needed
- **CI run:** `Build and Deploy Docker Image` — `in_progress` (run #29584668354)
  - URL: https://github.com/DrDonoso/WC2026Over9000Bot/actions/runs/29584668354
  - Triggered by `push` event on `main`, headSha `cba7fae`
- **Feature branch `feat/rich-apex-death`:** left intact (not deleted).

---

### 2026-07-17T13:11:00Z: Deploy — feat/final-weekend → main

**By:** Maldini (DevOps)  
**Requested by:** DrDonoso  
**Merge commit:** `a73f12e`

---

## Summary

Merged `feat/final-weekend` into `main` via `--no-ff` merge. 5 commits integrated (THIRD_PLACE scoring + final ceremony + tests). Full test suite: 2684 green. CI/CD workflow 29576019606 completed successfully.

---

### 2026-07-17T12:40:03+02:00: QA Verdict — Feature 2 Final Ceremony

**By:** Buffon (QA/Tester)  
**Branch:** `feat/final-weekend`  
**Commit reviewed:** `00520cd`  
**Requested by:** DrDonoso

---

## VERDICT: ✅ APPROVED

Coverage is adequate after filling 3 meaningful gaps.

---

## Suite Results

| Point in time | Count |
|---|---|
| On arrival (Kanté's commit `00520cd`) | **2680 passed** ✓ |
| After Buffon additions (commit `13fdcca`) | **2684 passed** |

---

## What Was Verified

### ✅ ONCE-ONLY / Restart-safety
- `pre_final_sent` and `campeon_sent` flags prevent re-sends on re-trigger (idempotent).
- State persisted to `final_ceremony_state.json` after each piece fires — verified by reading the file in tests.
- On failure, flag is NOT set (retry next tick / next command invocation).
- `test_restart_safety_loads_from_disk`: load from disk with both flags True → no API call, no send.

### ✅ State Machine
- PRE-FINAL fires: `SCHEDULED + past kickoff`, `IN_PLAY`, `PAUSED`.
- PRE-FINAL does NOT fire: `SCHEDULED + future kickoff`.
- CAMPEÓN fires: `FINISHED + winner` (HOME_TEAM or AWAY_TEAM).
- CAMPEÓN does NOT fire: `IN_PLAY`, `FINISHED + winner=None`.
- Catch-up: match already FINISHED when both flags are False → both pieces fire in one tick.
- All-done early exit: no API call when both flags True.

### ✅ Winner Edge Cases
- `winner=None` with FINISHED → no campeon, no crash.
- HOME_TEAM and AWAY_TEAM winner both covered.

### ✅ /granfinal
- Fires pre-final for non-FINISHED match.
- Fires campeón+podio for FINISHED+winner.
- No final match found → warning sent.
- No `TELEGRAM_GROUP_ID` → warning, no group message.
- `FootballAPIError` → error reply.
- Not in `_HELP_COMMANDS` (hidden command confirmed).

### ✅ Builders (pure functions)
- `build_pre_final_text`: header, ranking, optional camps block.
- `build_campeon_text`: name, flag, CAMPEÓN marker.
- `build_podium_participants`: top-3, positions 1/2/3, ties (1/1/3), empty list, fewer than 3.

### ✅ State Helpers
- Load missing file → defaults.
- Save + load round-trip.
- Corrupt file → defaults.
- Partial state → missing keys default.
- Best-effort save on bad path (no raise).

### ✅ API Mocking
All tests mock `make_client` via `patch("worldcup_bot.__main__.make_client", ...)`. Network is never hit.

---

## Gaps Found & Filled (commit `13fdcca`)

| # | Gap | Test Added |
|---|-----|-----------|
| 1 | `test_api_error_is_handled_gracefully` was a stub — `poll_final_ceremony_job` never called, zero assertions | `TestPollFinalCeremonyJobAPIErrorComplete::test_football_api_error_does_not_raise_and_sends_nothing` |
| 2 | API error must not write state file | `TestPollFinalCeremonyJobAPIErrorComplete::test_football_api_error_does_not_persist_state` |
| 3 | `cmd_granfinal`: `_send_pre_final` failure → error reply + flag stays False | `TestCmdGranfinalSendFailures::test_send_pre_final_failure_reports_error_flag_not_set` |
| 4 | `cmd_granfinal`: `_send_campeon_and_podio` failure → error reply + flag stays False | `TestCmdGranfinalSendFailures::test_send_campeon_failure_reports_error_flag_not_set` |

---

## Minor Note (non-blocking)

The charter mentioned `/granfinal` should be "admin-gated". The source has no admin guard — any user who knows the command name can invoke it. This is flagged for DrDonoso / Pirlo to decide. It does not block approval as the design document does not explicitly require it, and the command is hidden (not listed in help).


---

# Buffon QA Verdict — THIRD_PLACE Coverage Review
**Date:** 2026-07-17  
**Branch:** `feat/final-weekend`  
**Commit under review:** `c5840fc` (Kanté — "feat: puntuar el 3.º y 4.º puesto")  
**Buffon commit:** `be72151` (3 gap-filling tests)

---

## ✅ APPROVED

**Final test count: 2637 passed, 3 warnings, 0 failures.**

---

## Suite Verification

Full `python -m pytest -q` ran clean in ~105 s. Kanté's reported count of 2634 was confirmed on arrival; no hidden failures.

---

## Coverage Assessment

### ✅ Confirmed adequate by Kanté's tests

| Behaviour | Test |
|---|---|
| `third_place` correct winner → 5 pts | `TestScoreKnockoutThirdPlace::test_correct_winner_scores_5` |
| Wrong pick → 0 | `TestScoreKnockoutThirdPlace::test_wrong_pick_scores_0` |
| Pending (match not finished) → `pending` | `TestScoreKnockoutThirdPlace::test_pending_when_match_not_finished` |
| YAML key mapping `THIRD_PLACE → third_place` | `TestScoreKnockoutThirdPlace::test_yaml_key_mapping` |
| Point value is 5 | `TestScoreKnockoutThirdPlace::test_point_value_is_5` |
| Position in KNOCKOUT_STAGES (semi < tp < final) | `TestScoreKnockoutThirdPlace::test_third_place_in_knockout_stages_between_semi_and_final` |
| Missing `third_place` key → user loaded with `[]` | `TestLoadKnockoutTolerantValidation::test_missing_third_place_key_user_loaded_not_skipped` |
| Missing any key → user loaded | `TestLoadKnockoutTolerantValidation::test_missing_any_knockout_key_user_loaded` |
| Stored knockout always has all expected keys | `TestLoadKnockoutTolerantValidation::test_missing_key_stored_knockout_has_all_yaml_keys` |
| Unknown key → user skipped | `TestLoadKnockoutTolerantValidation::test_unknown_knockout_key_still_skips_user` |
| `phase_label("third_place")` | `TestPhaseLabel::test_third_place` |
| `third_place` active when pick present | `TestActivePhases::test_third_place_active_when_pick_present` |
| `third_place` absent when picks empty | `TestActivePhases::test_third_place_absent_when_no_picks` |
| `third_place` between `semi_finals` and `final` in order | `TestActivePhases::test_third_place_between_semi_finals_and_final` |
| `🥉` header rendered | `TestBuildKnockoutText::test_third_place_header_rendered` |
| GROUP validation still strict | `TestLoadInvalidCases::test_wrong_number_of_groups_user_skipped`, `test_wrong_picks_per_group_user_skipped`, `test_invalid_tla_user_skipped` |
| TLA validation still strict | `TestLoadInvalidCases::test_invalid_tla_user_skipped` |

### ❌ Gaps found — filled by Buffon

| Gap | Test Added |
|---|---|
| `third_place: []` (stored default) → 0 pts, no crash | `TestScoreKnockoutThirdPlace::test_empty_third_place_pick_no_crash_and_zero_pts` |
| All 6 stages correct = 24 pts (no double-count, FINAL=8) | `TestScoreKnockoutAllStagesIntegration::test_all_six_stages_correct_sums_to_24` |
| Missing valid key + unknown key → SKIPPED (combo per spec) | `TestLoadKnockoutTolerantValidation::test_missing_and_unknown_key_user_skipped` |

---

## Notes / Observations

- `test_pending_semantics` has a misleading docstring ("pending, not fallo") but the body correctly tests a *decided* match where the user's pick lost → `fallo`. The actual pending path is covered by `test_pending_when_match_not_finished`. Not a bug, just a confusing name.
- `test_phase_order_respected` in `TestActivePhases` is stale (hardcodes the 6-phase order without `third_place`), but it uses a knockout dict without `third_place` so it passes. The new `test_third_place_between_semi_finals_and_final` provides the correct ordering assertion.
- `_KNOCKOUT_YAML_KEYS` is derived from `STAGE_YAML_KEYS.values()` at import time, so adding `THIRD_PLACE` to `stages.py` automatically updated the set — a clean design choice.

---

## Verdict

The implementation is correct and the test suite is now adequate for a live event. **APPROVED.**


---

# kante: Feature 2 — Final Ceremony

**Date:** 2026-07-17  
**Branch:** `feat/final-weekend`  
**Author:** Kanté (backend)

---

## What shipped

### New module: `src/worldcup_bot/bot/final_ceremony.py`
Pure builder functions + state helpers. All Spanish copy in module-level `COPY_*` constants (single block to edit). No I/O or Telegram imports.

- `load_ceremony_state(path)` / `save_ceremony_state(path, state)` — JSON dict with `{"pre_final_sent": false, "campeon_sent": false}`, defaults on missing/corrupt file.
- `build_pre_final_text(ranking_text, camps_block)` — combines header + ranking snapshot + face-off block.
- `build_campeon_text(winner_tla, winner_name, flag)` — champion announcement.
- `build_podium_participants(rows)` — top-3 with standard competition positions for `render_podium`.

### Modified: `src/worldcup_bot/__main__.py`
- New shared helpers `_send_pre_final` / `_send_campeon_and_podio` (reuse by both job and command).
- `poll_final_ceremony_job` (60 s interval, restart-safe, each piece fires exactly once).
- `cmd_granfinal` (hidden, not in /start help; fires pre-final or campeón+podio based on FINAL status).
- `bot_data["final_ceremony_state"]` initialized from `load_ceremony_state` in `build_app()`.
- State file: `{state_dir}/final_ceremony_state.json`.

### New tests: `tests/test_final_ceremony.py`
43 tests: pure builders, state helpers, job state machine (pre-final trigger, campeón trigger, idempotency, persistence, restart-safety, edge cases), cmd_granfinal, and absence from /start help.

---

## Ceremony pieces

| Piece | Trigger | Content |
|-------|---------|---------|
| A PRE-FINAL | `now >= kickoff_utc` OR status IN_PLAY/PAUSED/FINISHED | Hype header + porra ranking snapshot + ⚔️ champion-picks face-off |
| B CAMPEÓN | status FINISHED AND winner set | World champion announcement (flag + name) |
| C PODIO | same as B, immediately after | Official porra classification + podium image via `render_podium` |

---

## Test count

| Before Feature 2 | After Feature 2 |
|---|---|
| 2637 | 2680 |

---

## Owner action items

1. **Fill `final: [TLA]` picks** in the live `data/predictions.yml` for participants who have empty final picks — the podium classification will not reflect the champion bonus until those are filled.
2. **Test manually** with `/granfinal` before the match (sends pre-final to group) and after the match ends (sends campeón + podio).
3. **Edit copy** if needed: all Spanish strings are in `COPY_*` constants at the top of `src/worldcup_bot/bot/final_ceremony.py`.

---

## Spanish copy (for owner review)

```
COPY_PRE_FINAL_HEADER:
  "🌍⚽ ¡Arranca la GRAN FINAL del Mundial 2026!

   Noventa minutos (o más) para decidir quién es el mejor del mundo.
   Así llega la porra al partido más importante:"

COPY_PRE_FINAL_RANKING_TITLE:
  "📊 Clasificación antes de la Final:"

COPY_CAMPEON_TEMPLATE:
  "🏆 {flag} {name} 🏆

   ¡CAMPEÓN DEL MUNDO 2026! 🎊"

COPY_PODIO_RANKING_TITLE:
  "🏆 CLASIFICACIÓN FINAL DE LA PORRA 🏆"
```


---

### 2026-07-17T10:43:21+02:00: Feature 1 shipped — THIRD_PLACE stage scoring

**By:** Kanté
**Branch:** `feat/final-weekend`
**Status:** Complete, ready for Buffon verification

---

## What shipped

### Files changed

| File | Change |
|------|--------|
| `src/worldcup_bot/data/stages.py` | Added `("THIRD_PLACE", "3.º y 4.º Puesto", 5)` to `KNOCKOUT_STAGES` between `SEMI_FINALS` and `FINAL`; added `"THIRD_PLACE": "third_place"` to `STAGE_YAML_KEYS` |
| `src/worldcup_bot/porra/predictions.py` | Tolerant knockout validation (see below) |
| `src/worldcup_bot/porra/elecciones.py` | `third_place` in `_PHASE_LABELS`, `_PHASE_ORDER` (between `semi_finals` and `final`), `_KNOCKOUT_HEADERS` (`🥉 3.º Y 4.º PUESTO — ¿Quién gana?`) |
| `src/worldcup_bot/bot/formatters.py` | Simplified `_KNOCKOUT_STAGE_NAMES` — `THIRD_PLACE` now in `KNOCKOUT_STAGES` so manual `| {"THIRD_PLACE"}` removed |
| `data/predictions.template.yml` | `third_place: []` added to both example participants and ESQUEMA comment |
| `tests/test_scoring.py` | Fixed `test_knockout_stages_config_point_values`; added `TestScoreKnockoutThirdPlace` (7 tests) |
| `tests/test_predictions_loader.py` | Updated VALID_YAML_1/2 and `_KO_BLOCK`; fixed `test_valid_yaml_knockout_structure`; added `TestLoadKnockoutTolerantValidation` (4 tests) |
| `tests/test_elecciones.py` | Added `test_third_place` in `TestPhaseLabel`; added 4 new `TestActivePhases` tests; added `test_third_place_header_rendered` |

### Points: 5 (same as SEMI_FINALS)

### Tolerant validation semantics (predictions.py)

- **Unknown/extra knockout keys** → user IS skipped (typo-guard preserved)
- **Missing knockout keys** → user NOT skipped; missing key defaulted to `[]` in stored knockout
- **All `_KNOCKOUT_YAML_KEYS` guaranteed** in every loaded participant's `knockout` dict
- **GROUP validation unchanged** — must be exactly `GROUPS`, no tolerance there

### Downstream propagation (no other code changed)

All of the following iterate `KNOCKOUT_STAGES` or `STAGE_YAML_KEYS` and pick up THIRD_PLACE automatically:
- `porra/scoring.py` (`score_knockout`)
- `api/client.py` (`get_knockout_results`, `get_knockout_decided`, `get_finished_stages`)
- `porra/engine.py`, `porra/history.py`

The `⚔️` kickoff face-off block in the bot will show for the third-place match (FRA vs ENG) — this comes for free via `STAGE_YAML_KEYS`.

### Test counts

| | Tests |
|---|---|
| Baseline (before) | 2618 |
| After (new + fixed) | 2634 |
| Delta | +16 |

---

## Action required from owner (@DrDonoso)

**Before FRA vs ENG kickoff (18/07 23:00 Madrid):** add `third_place: [TLA]` picks to the live `data/predictions.yml` for each participant. The bot will auto-reload on next command.


---

### 2026-07-17T10:43:21+02:00: Review — Feature 2 "Ceremonia especial de la Final"

**Reviewer:** Pirlo (Lead / Tech Lead)
**Commit:** `00520cd` on `feat/final-weekend`
**Files:** `final_ceremony.py` (new, 112 lines), `__main__.py` (+232), `test_final_ceremony.py` (new, 43 tests)

---

## VERDICT: ✅ APPROVED

---

## Analysis by focus area

### 1. Restart-safety / once-only

**Correct.** State is loaded from `final_ceremony_state.json` at startup via `load_ceremony_state()` and kept in `bot_data["final_ceremony_state"]`. Each piece (`pre_final_sent`, `campeon_sent`) is persisted ONLY after a successful send — a failed send returns without marking, so the next 60 s tick retries. `load_ceremony_state` handles missing/corrupt files gracefully. Pattern is consistent with (and slightly better than) the `poll_kickoff_job`/`save_finished` pattern, which marks in `finally` even on send failure.

Mid-ceremony restart: if the process dies between a successful send and the `save_ceremony_state()` call, the piece re-sends on restart. Acceptable — the window is sub-millisecond (synchronous JSON write, no await between send completion and save), and a duplicate ceremony message is strictly better than a missing one.

No asyncio race: both the job and `/granfinal` run in the single event loop. Theoretical interleave at await points could cause a double-send if an admin fires `/granfinal` at the exact moment the job is mid-send, but this matches every other hidden-command + job pair in the bot and is not a real-world risk.

### 2. Final detection & winner derivation

**Correct.** Final found via `m.stage == "FINAL"` — safe `None` return if absent. Pre-final triggers on `now >= kickoff` OR `status in (IN_PLAY, PAUSED, FINISHED)`. Campeón triggers on `status == "FINISHED" and final_match.winner` — guards against null/unset winner. Winner derivation uses `HOME_TEAM` / else (away), consistent with `client.py:153-156`. `DRAW` is impossible for a FINISHED Final (penalties decide), so the else-branch is safe.

### 3. /granfinal

**Correct.** Not listed in `_HELP_COMMANDS`. Calls the same `_send_pre_final()` / `_send_campeon_and_podio()` helpers as the job — zero logic duplication. Chooses the right piece based on current match status. No admin gate — but this is CONSISTENT with every other hidden command (`/evilsanchez`, `/recalcular`, `/tongocheck`, `/calcularperfiles`); they all rely on not being published.

### 4. Seams

**Clean.** `final_ceremony.py` contains only pure functions (state load/save + message builders) — no Telegram, no API, no I/O. Telegram orchestration (`_send_pre_final`, `_send_campeon_and_podio`) lives in `__main__.py`. Ranking computed via `compute_general_ranking` (porra engine), podium via `render_podium` (existing), positions via `standard_competition_positions` (existing). No scoring re-implementation. The Telegram / football-data / porra-engine separation is respected.

### 5. Non-interference

**No conflicts.** New `bot_data` key `final_ceremony_state` doesn't clash with any existing key. New state file `final_ceremony_state.json` is unique. Job `poll_final_ceremony` runs independently every 60 s — no `goal_lock` interaction, no shared mutable state with goal/kickoff/finished jobs. `render_podium` correctly offloaded to `asyncio.to_thread()`. Top-level `try/except` prevents exceptions from propagating to the JobQueue.

### 6. Failure modes

**Well-handled.** Outer `except Exception` in the job logs and swallows — JobQueue survives. Failed sends don't mark the piece as sent → automatic retry on next tick. `_send_campeon_and_podio` sends two messages (champion + podium); if the first succeeds but the second fails, champion re-sends on retry — acceptable tradeoff for simplicity over splitting into a third state flag. `render_podium` failure is non-fatal (falls back to text-only ranking). `cmd_granfinal` checks `telegram_group_id` explicitly and reports errors to the invoker.

### Design compliance

Matches the validated design in `squad-final-weekend-design.md`:
- ✅ Three pieces: A (pre-final hype + porra snapshot + ⚔️ face-off), B (campeón), C (official ranking + podium image)
- ✅ B and C fire together ("with the champion piece")
- ✅ Automatic restart-safe job + hidden manual `/granfinal`
- ✅ Deterministic copy (no AI), no mentions/superlatives
- ✅ 43 tests covering builders, state, job state-machine, restart-safety, cmd_granfinal, and `/start` absence

### Test coverage

Thorough: 43 tests across 6 test classes covering pure builders, state round-trips, corrupt/missing state files, job triggers (kickoff, IN_PLAY, PAUSED, FINISHED, future-scheduled), idempotency, disk persistence, send-failure retry, both-pieces-at-once, restart-from-disk, `/granfinal` pre/post paths, and edge cases (no final, no group ID, API errors).

---

**No blocking issues. Ship it.** 🚀


---

# Review: feat/final-weekend — "puntuar el 3.º y 4.º puesto"

**Reviewer:** Pirlo (Lead / Tech Lead)
**Date:** 2026-07-17T11:41+02:00
**Branch:** `feat/final-weekend` (1 commit: `c5840fc`)
**Files reviewed:** 9

---

## Verdict: ✅ APPROVED

The implementation is correct, matches the validated design, and introduces no regressions (263 tests pass).

---

## Key Findings

### 1. `predictions.py` — Tolerant validation ✅

- **Extra keys → skip:** `extra_keys = set(knockout_raw.keys()) - _KNOCKOUT_YAML_KEYS; if extra_keys: continue` — typo protection preserved.
- **Missing keys → `[]`:** After processing provided keys, `stored_knockout.setdefault(key, [])` fills every expected YAML key — guarantees downstream `score_knockout` / `.get()` never KeyErrors.
- **Group/TLA strictness untouched:** The group-validation loop, TLA-list check, and duplicate/size checks are not modified.
- **Ordering:** `stored_knockout` is built from `knockout_raw` first, then `setdefault` fills gaps. Correct.

### 2. `stages.py` ✅

- `("THIRD_PLACE", "3.º y 4.º Puesto", 5)` — correct tuple shape, 5 points, positioned between SEMI_FINALS and FINAL.
- `STAGE_YAML_KEYS["THIRD_PLACE"] = "third_place"` — consistent.

### 3. Downstream callers ✅

- **`scoring.py score_knockout`:** Iterates `KNOCKOUT_STAGES`, resolves `yaml_key` via `STAGE_YAML_KEYS.get()`, retrieves user picks via `.get(yaml_key, [])`. Adding THIRD_PLACE flows through without any special-casing needed. No double-counting.
- **`api/client.py get_knockout_results / get_knockout_decided`:** Both iterate `KNOCKOUT_STAGES` — THIRD_PLACE automatically included. API returns `stage=THIRD_PLACE` (verified live per design doc).
- **`camps.py compute_match_camps`:** Uses `STAGE_YAML_KEYS.get(stage)` → returns `"third_place"` → face-off block for FRA-ENG will work.
- **`history.py`:** Uses `{api for api, _, _ in KNOCKOUT_STAGES}` — includes THIRD_PLACE.
- **`engine.py`:** Delegates to `client.get_knockout_results()` / `get_knockout_decided()` — no change needed.

### 4. `formatters.py` ✅

Old code: `frozenset(api for api, _, _ in KNOCKOUT_STAGES) | {"THIRD_PLACE"}` (explicit union because THIRD_PLACE wasn't in the list).
New code: `frozenset(api for api, _, _ in KNOCKOUT_STAGES)` — since THIRD_PLACE is now IN the list, the resulting frozenset is identical. Behaviour unchanged.

### 5. `elecciones.py` ✅

- `_PHASE_LABELS`, `_PHASE_ORDER`, `_KNOCKOUT_HEADERS` all include `third_place` between `semi_finals` and `final`. Correct ordering.

### 6. `predictions.template.yml` ✅

- `third_place: []` added between `semi_finals` and `final` in both example participants and the schema comment.

### 7. Tests ✅

- `TestScoreKnockoutThirdPlace`: 7 focused tests cover correct/wrong/pending semantics, point value, ordering, and YAML key mapping.
- `TestLoadKnockoutTolerantValidation`: 4 tests verify missing-key tolerance, all-keys guarantee, and unknown-key rejection.
- `TestActivePhases` / `TestBuildKnockoutText`: third_place ordering and header rendering verified.
- All 263 tests pass.

---

## Minor notes (NOT blocking)

- The `_make_knockout()` test helper in `test_elecciones.py` doesn't include `third_place` in its base dict — acceptable because overrides handle it and downstream code uses `.get()`. Not a bug.
- The `test_all_stages_correct_sums_correctly` test comment says `# 1 + 2 + 3 + 5 + 8 = 19 (third_place missing from user → 0)` — accurate, since the user fixture doesn't include `third_place` in its picks so that stage contributes 0.

**Ship it. Ready for tomorrow's match.**


---

### 2026-07-17T10:43:21+02:00: Diseño validado — "Final weekend" (3.º/4.º puesto + ceremonia de la Final)

**By:** DrDonoso (via Copilot / Squad)
**Contexto:** WC2026 en fase final. 3.º/4.º puesto: 18/07 21:00Z (FRA vs ENG). Final: 19/07 19:00Z (ESP vs ARG). API football-data.org devuelve `stage=THIRD_PLACE` y `stage=FINAL` (verificado en vivo).

**Feature 1 — Puntuar el 3.º y 4.º puesto (ganador del partido):**
- **Puntos: 5** (igual que semifinales).
- Nueva fase `THIRD_PLACE` en `data/stages.py` → `KNOCKOUT_STAGES` **entre `SEMI_FINALS` y `FINAL`** (orden cronológico); `STAGE_YAML_KEYS["THIRD_PLACE"] = "third_place"`.
- Nuevo campo por participante: `knockout.third_place: [TLA]` (1 equipo).
- **Validación tolerante** en `porra/predictions.py`: una clave de knockout ausente se rellena con `[]` (NO se descarta al participante); se siguen rechazando claves DESCONOCIDAS (protección anti-typo).
- `/elecciones`: `third_place` en `_PHASE_LABELS` / `_PHASE_ORDER` (entre semis y final) / `_KNOCKOUT_HEADERS`.
- El bloque ⚔️ "¿Con quién va la porra?" en el saque de FRA-ENG **sí** se mostrará (viene gratis vía `STAGE_YAML_KEYS`).
- `predictions.yml` se edita a mano (sin flujo de escritura). El owner rellena las picks antes del saque (18/07 23:00 Madrid).

**Feature 2 — Ceremonia de la Final:**
- Piezas: **pre-final** (hype + snapshot de la porra), **post-final campeón** (anuncio campeón del mundo), **post-final podio** (clasificación FINAL oficial + `render_podium`). SIN menciones/superlativos.
- Disparo: **automático** (detectar FINAL FINISHED) **+ comando manual oculto** de respaldo (p.ej. `/granfinal`).

**Ejecución:** Secuenciada. Kanté hace Feature 1 (deadline mañana) → Buffon verifica → Pirlo revisa → luego Feature 2. Rama `feat/final-weekend`.


---

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



---

### 2026-07-18T16:48:00Z: Decision — feat/elecciones-nudge (Knockout pre-display nudge)

**Date:** 2026-07-18
**Author:** Kanté (Backend Dev)  
**Feature:** Pre-display nudge for missing picks in knockout phases

## Decisions

### 1. "Has not chosen" = nothing_picked semantics
A participant is nudged ONLY if they have NO valid pick for ANY tie in the round
(`_pick_for_tie` returns None for every tie). Picking at least one valid team for
any tie means they are NOT nudged. This is the "nothing_picked" threshold — not
"has any missing tie".

### 2. Time reference = first match of the round (round-wide deadline)
We sort the round's matches by `utc_date` and use `round_matches[0].utc_date`.
For single-match rounds (third_place, final) this is naturally the only match.

### 3. Threshold = 2.0 hours (NUDGE_THRESHOLD_HOURS)
Named constant in `elecciones.py`; compared as `hours_until > 2.0`.
Strict greater-than (not ≥), so exactly 2h remaining shows the matrix.

### 4. Nudge is cacheable=False
Time-sensitive: the nudge window changes as kickoff approaches. Must regenerate
on every tap within the nudge window.

### 5. _utcnow() as testable hook
Module-level `def _utcnow() -> datetime` in handlers.py so tests can patch
`worldcup_bot.bot.handlers._utcnow` without patching `datetime.now` globally.

### 6. Grupos excluded
The nudge logic sits inside the knockout branch of `_generate_elecciones_artifact`,
after the `if yaml_key == "grupos": ... return` early-exit. Grupos is structurally
excluded.

### 7. parse_mode=None for nudge messages
Plain-text `@username` notifies correctly in PTB with parse_mode=None (default).
Consistent with revive.py pattern.

---

### 2026-07-18T18:23:32+02:00: QA Review — feat/elecciones-nudge (commit 7c1a8de → 1104873)

**By:** Buffon (Tester / QA)
**Branch:** `feat/elecciones-nudge`
**Requested by:** DrDonoso

---

## ✅ APPROVED

The nudge feature is correctly implemented and the test suite adequately covers
all required edge cases after two gap-fill additions.

---

## Baseline

- **Before:** 2777 passing (144 in test_elecciones.py)
- **After:**  2779 passing (146 in test_elecciones.py) — all green, no regressions

---

## Audit by coverage area

### `pickers_missing_all` (TestPickersMissingAll) ✅
All required semantics covered:
- Empty ties → `[]` ✓
- Zero-valid-pick participant IS missing ✓
- Participant with ≥1 valid pick is NOT missing (partial-pick semantics) ✓
- Picks for eliminated teams (not in any tie) → missing ✓
- Insertion order preserved ✓
- Missing `knockout` key altogether → missing ✓

### `build_nudge_text` (TestBuildNudgeText) ✅
- `@mention` for each username ✓
- `pasa` verb for all non-final knockout rounds ✓
- `gana` verb for `final` and `third_place` ✓
- Phase label present in all tested rounds ✓
- Matrix content (❓, 👤, "¿Quién pasa?") is absent — verified by integration
  tests in TestGenerateEleccionesArtifactNudge ✓

### `_generate_elecciones_artifact` nudge branch (TestGenerateEleccionesArtifactNudge) ✅

| Scenario | Before QA | After QA |
|---|---|---|
| missing + >2h → nudge + cacheable=False | ✓ (3.5h) | ✓ |
| everyone picked → matrix | ✓ | ✓ + cacheability asserted |
| missing + ≤2h → matrix | ✓ (1.5h) | ✓ |
| past match (negative hours) → matrix | ✓ | ✓ |
| unparseable utc_date → matrix, no crash | ✓ | ✓ |
| grupos phase → never nudges | ✓ | ✓ |
| **exactly 2h → matrix (strict >, not >=)** | ❌ MISSING | ✅ ADDED |
| **2h + 1s → nudge (strict > boundary)** | ❌ MISSING | ✅ ADDED |
| normal path does NOT set cacheable=False | ❌ WEAK | ✅ STRENGTHENED |

---

## Changes committed

**Commit:** `1104873` on `feat/elecciones-nudge`
**File:** `tests/test_elecciones.py` (+55 lines, 0 removals)

1. **`test_exactly_2h_returns_normal_matrix`** — pins the strict `>` semantics:
   `hours_until = 2.0`, `2.0 > 2.0 == False` → normal matrix returned, no nudge.
   Also asserts `❓` present (confirming matrix, not empty).

2. **`test_just_over_2h_returns_nudge`** — at 2h+1s (`hours_until ≈ 2.000278`),
   the condition fires: nudge returned with `cacheable=False`, `@alice`/`@bob`
   present, `❓` and `👤` absent.

3. **`test_everyone_picked_returns_normal_matrix` (strengthened)** — added
   `assert result.get("cacheable") is not False` to guard the contract that the
   normal (everyone-picked) path does not disable caching.

---

## Non-blocking observations

- The `FIRST_MATCH_FAR = "2026-07-01T15:30:00Z"` constant (3.5h) covers ">2h →
  nudge" but is not "just over 2h"; the new `test_just_over_2h_returns_nudge` now
  pins the exact boundary.
- All existing tests were correct; no false positives or incorrect assertions
  found.
- The feature implementation itself is clean: `_parse_match_utc` returns `None`
  on bad input, guarding the `if missing and first_utc is not None:` check; the
  nudge path only fires when `first_utc` is valid **and** `hours_until > 2.0`.

---

### 2026-07-18T16:48:00Z: Review — feat/elecciones-nudge (commit 7c1a8de)

**Reviewer:** Pirlo (Lead / Tech Lead)
**Date:** 2026-07-18
**Branch:** `feat/elecciones-nudge` on top of `main` @ `04fbac0`

---

## Focus-area findings

### 1. Correctness of the time branch ✅

`hours_until = (first_utc - _utcnow()).total_seconds() / 3600.0`

- Both operands are tz-aware UTC (`_utcnow()` returns `datetime.now(timezone.utc)`; `_parse_match_utc` does `.replace(tzinfo=timezone.utc)`). Subtraction is safe — no naive-vs-aware mismatch.
- Boundary: uses `>` (strict), so exactly 2.0 h falls through to the matrix. Correct per spec.
- Past match → `hours_until` is negative → `> 2.0` is `False` → falls through to the normal matrix. Correct.

### 2. Caching ✅

Nudge returns `{"cacheable": False}`. The caller in `cmd_elecciones_callback` (line 1941) checks `artifact.get("cacheable", True)` before storing — `False` prevents caching. Time-sensitive artifact will never be stashed and re-served after the window flips.

Normal branches (text, image, "no bracket yet") are unaffected — they either omit `cacheable` (defaults to `True` → cached) or explicitly set `False` for transient states. No regression.

### 3. nothing_picked semantics ✅

`pickers_missing_all` returns keys where `_pick_for_tie` is `None` for **every** tie (via `all(…)`). Empty `ties` → early `return []`. Order preserved (iterates `participants.items()` which is insertion-ordered in Python 3.7+). Correct.

### 4. utc_date handling ✅

`sorted(round_matches, key=lambda m: m.utc_date)` sorts by the **string** `utc_date`. Since the football-data API always returns ISO 8601 strings in the fixed format `YYYY-MM-DDTHH:MM:SSZ` (all same length, zero-padded, Zulu suffix), lexicographic order equals chronological order. `round_matches[0]` is the earliest.

**Risk if mixed offsets (e.g. `+02:00` vs `Z`):** lex sort would be wrong. In practice the API contract is always `Z`-terminated; `_parse_match_utc` enforces `%Y-%m-%dT%H:%M:%SZ` and returns `None` on non-Z strings, which makes the nudge fall through harmlessly. Acceptable.

### 5. Module purity ✅

`porra/elecciones.py` remains pure — no `datetime`, no I/O, no network. Only `NUDGE_THRESHOLD_HOURS` (a constant float), `pickers_missing_all`, and `build_nudge_text` were added; all are pure functions. Time/now lives exclusively in `handlers.py` (`_utcnow`, `_parse_match_utc`), both patchable.

### 6. Mentions & message ✅

`build_nudge_text` produces `@{uname}` for each username. "gana" for `final`/`third_place`, "pasa" otherwise. No HTML entities, no markdown syntax (no `<b>`, no `*`, no `_`). `_serve_after_placeholder` sends via `send_message(chat_id=…, text=msg)` with **no `parse_mode` argument** → defaults to `None` → Telegram treats the text as plain, so `@username` triggers a mention notification. Correct.

### 7. No regression ✅

- Grupos path: entirely separate `if yaml_key == "grupos"` branch, untouched.
- Normal knockout matrix path: the refactor `ties → round_matches` produces the same `ties` list — just extracts the sorted match objects first. The image and text rendering code below is identical.
- The nudge branch is additive: it returns early **only** when `missing and first_utc and hours_until > 2.0`. All other paths fall through to existing behaviour.

---

## Test coverage

144 tests pass. New tests cover:
- `pickers_missing_all`: empty ties, no picks, valid pick, eliminated-only picks, partial pick, insertion order, all picked, missing key entirely.
- `build_nudge_text`: @mentions, pasa/gana verb selection for all phases, phase labels.
- Integration (`_generate_elecciones_artifact`): missing + far → nudge; everyone picked → matrix; missing + near deadline → matrix with ❓; past match → matrix; unparseable date → no crash; grupos → never nudges.

Comprehensive and correct.

---

## Non-blocking nits

_(No blocking issues found. Listing minor observations only — none require action.)_

1. `build_nudge_text` accepts `participants` but doesn't use it. Harmless (may be useful later for display_name), but the unused parameter is a small API smell.

---

## Verdict

# ✅ APPROVED

Clean, minimal, correct. The time logic is sound, caching is safe, module purity is preserved, and test coverage is thorough. Ship it.

---

### 2026-07-18T16:48:00Z: Deploy — feat/elecciones-nudge

**Date:** 2026-07-18
**Merged by:** Maldini (DevOps)
**Approved by:** Pirlo + Buffon

## Merge Details

- **Feature branch:** `feat/elecciones-nudge`
- **Commits merged:** 3 (elecciones.py nudge logic, handlers.py wiring, test_elecciones.py coverage)
- **Rebase:** origin/main had 1 bot CHANGELOG commit ahead (`367cb4e`); rebased cleanly over it.
- **Merge type:** Fast-forward — no merge commit, clean linear history.
- **Final origin/main HEAD:** `7f444b6` — _refactor(elecciones): drop unused participants param from build_nudge_text_

## CI Run

- **Workflow:** Build and Deploy Docker Image
- **Run ID:** 29652587787
- **Status at push time:** `in_progress`
- **URL:** https://github.com/DrDonoso/WC2026Over9000Bot/actions/runs/29652587787

## Notes

- Feature branch `feat/elecciones-nudge` is safe to delete once CI confirms success.
- Unstaged `.squad/agents/kante/history.md` was temporarily stashed (`git stash`/`pop`) to allow the rebase; all .squad files left uncommitted per policy.
