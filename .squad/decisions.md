# Decision: BELOVED_TEAMS get ❤️ in team_flag + AI daily-update love instruction

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-18
**Status:** IMPLEMENTED — 1313 tests green, not yet committed (coordinator verifies first)

---

## Problem

David wanted the bot to show extra love ❤️ for Panamá 🇵🇦 and Uzbekistán 🇺🇿 whenever they appear
in any message, and for the AI daily summary to show warmth and encouragement whenever it mentions
those teams.

---

## Decision

### BELOVED_TEAMS constant + team_flag chokepoint

```python
# src/worldcup_bot/bot/formatters.py
BELOVED_TEAMS = {"PAN", "UZB"}   # Panamá, Uzbekistán — el cariño del bot
_LOVE = "❤️"
```

`team_flag(tla)` now appends `_LOVE` to the flag when:
1. The flag is non-empty (unknown TLAs still return `""`), AND
2. `tla.strip().upper()` is in `BELOVED_TEAMS`.

Result: `team_flag("PAN")` → `"🇵🇦❤️"`, `team_flag("UZB")` → `"🇺🇿❤️"`.
Case-insensitive: `team_flag("pan")` also returns `"🇵🇦❤️"`.

Because every message renderer (format_match, format_standings, render_endirecto,
render_message in daily_update, format_live_match_detail, format_user_detail) calls
`team_flag`, the love propagates to goal notifications, /hoy, /endirecto,
standings/clasificación, finished recaps, and daily AI summaries — automatically,
with no per-renderer changes needed.

### AI daily-update love instruction

Appended to `_SYSTEM` in `src/worldcup_bot/ai/daily_update.py`:

> "Cariño especial: Panamá 🇵🇦 y Uzbekistán 🇺🇿 son las selecciones favoritas de esta porra.
> Siempre que las menciones, muéstrales un poco de amor y ánimo (con naturalidad, sin pasarte
> ni romper el formato): un emoji de corazón, una palabra de apoyo o un guiño cariñoso."

Only the AI prose guidance changes; the deterministic HTML builder (`render_message`) is untouched.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/bot/formatters.py` | Add `BELOVED_TEAMS`, `_LOVE`; modify `team_flag` |
| `src/worldcup_bot/ai/daily_update.py` | Append love instruction to `_SYSTEM` |
| `tests/test_formatters.py` | Add `TestTeamFlagBelovedTeams` (6 tests) |
| `tests/test_ai.py` | Add 3 tests to `TestSystemPromptContract` |

---

## Why this is safe

- `team_flag` is the single canonical flag renderer — no risk of missing a spot.
- Unknown TLAs return `""` (no heart on empty string), so the guard is tight.
- `team_label` inherits the heart automatically (it calls `team_flag`).
- Appending to `_SYSTEM` doesn't shift `today_notes` before `standings_comment`, so
  the existing `test_system_prompt_today_notes_rule_stated_unconditionally` test still passes.
- No existing tests hard-code PAN or UZB flag strings, so zero test fixes were needed.

---

# Decision: /hoy rolls forward to the next jornada when today's matches are all done

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-18
**Status:** IMPLEMENTED — 1304 tests green, not yet committed (coordinator verifies first)

---

## Problem

`/hoy` always showed the current 9am→9am football-day window (`offset 0`).  At 07:00 that window is `[yesterday 9am → today 9am]` — last night's matches, all FINISHED.  The user wanted to see the next jornada's upcoming matches, not old results.

---

## Decision

`/hoy` now shows the **first 9am→9am window from today forward that still has a non-finished match**.

### Algorithm

1. Walk `offset in range(0, 15)` (today .. +14 days).
2. For each offset call `client.get_football_day_matches(tz, offset, h)`.
3. First window where `any(m.status != "FINISHED")` is `selected`; break immediately.
4. If no such window found → fall back to `offset 0` as today's finished results.
5. If `offset 0` is also empty → reply `"No hay partidos programados."`.

### Headers

| Case | Header | Formatter |
|---|---|---|
| `selected_offset == 0` | `"⚽️ Partidos de hoy (09:00–09:00):"` | `format_match` (time only) |
| `selected_offset > 0` | `"⚽️ Ya han acabado los partidos de hoy. Estos son los próximos:"` | `format_match_with_date` (date + time) |

### Error handling

`FootballAPIError` at any loop iteration → reply api-error message and return immediately (same as before).

---

## Why this is safe

- `get_football_day_matches` filters an in-memory cached response from a single `get_all_matches()` call — the loop adds no extra HTTP calls.
- `format_match_with_date` already existed in `formatters.py`; only the import in `handlers.py` was missing.
- `cmd_ayer` is unchanged.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/bot/handlers.py` | Add `format_match_with_date` import; rewrite `cmd_hoy` with rollover loop |
| `tests/test_handlers.py` | Add `TestCmdHoy` (7 tests) covering normal day, 07:00 rollover, empty offset 0, no-upcoming fallback, truly empty, API error, loop-stops-early |

---

# Decision: per-source `seen` + single `announced` + pure `reconcile()` fixes goal-detector flip-flop

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-18  
**Status:** IMPLEMENTED — 1283 tests green, not yet committed (coordinator verifies first)

---

## Problem

England 4-2 Croatia (Rashford 85'): the Reddit match thread reported 4-2 while
football-data.org still showed 3-2.  Both detectors shared a single
`bot_data["live_scores"]` dict.

Flip-flop loop:
1. Thread sees 4-2 → updates shared dict to 4-2 → announces GOOOL.
2. API reports 3-2 → sees shared dict at 4-2 → 4→3 is a DECREASE → announces "Gol anulado (VAR)".
3. Thread sees shared dict at 3-2 → 3→4 is an INCREASE → re-announces GOOOL.
4. Loop forever.

---

## Decision

Introduce **per-source `seen`** alongside the existing **single `announced`** score:

| Key | Location | Persisted? | Purpose |
|---|---|---|---|
| `bot_data["live_scores"][match_id]` | existing | ✅ JSON | Single official announced score |
| `bot_data["seen_scores"]["api"][match_id]` | new | ❌ in-memory | API source's own last-known score |
| `bot_data["seen_scores"]["thread"][match_id]` | new | ❌ in-memory | Thread source's own last-known score |

A **pure `reconcile(seen, announced, new_home, new_away)` function** in
`src/worldcup_bot/reddit/score_state.py` decides what to announce:

```python
def reconcile(seen, announced, new_home, new_away) -> (deltas, new_seen, new_announced)
```

Rules (in order):
1. **First-seen** (`seen is None`): seed source's baseline to `new`, announce nothing.
2. **No change** (`new == seen`): nothing.
3. **`new` ahead of `announced`**: emit goal delta(s), set `new_announced = new`.
4. **`announced` ahead of `new`** (potential disallowed):
   - If `ahead(seen, new)` — the SOURCE'S OWN prior value dropped → real VAR → emit disallowed, `new_announced = new`.
   - Else (source was behind announced — pure lag) → announce nothing, `new_announced = announced` (unchanged).
5. **Equal or mixed**: announce nothing.

The `_ahead(a, b)` helper: `a["home"] >= b["home"] and a["away"] >= b["away"] and (a["home"] > b["home"] or a["away"] > b["away"])`.

---

## Why this fixes the bug

**API lag scenario** (the screenshot):
- announced = 4-2 (thread already told users), api_seen = 3-2 (api was lagging)
- API reports 3-2: `reconcile(seen={3,2}, ann={4,2}, 3, 2)`
  - `ahead(new={3,2}, ann={4,2})`? No.
  - `ahead(ann={4,2}, new={3,2})`? Yes (potential disallowed).
  - `ahead(seen={3,2}, new={3,2})`? No — source was NOT ahead, just lagging. **Lag branch → no disallowed.**
- Result: `([], {3,2}, {4,2})` — announced stays 4-2, no false "anulado". ✅

**Real VAR scenario**:
- thread_seen = 4-2, announced = 4-2, thread now reports 3-2:
  - `ahead(seen={4,2}, new={3,2})`? Yes — source's own value dropped → real disallowed. ✅

**Restart safety**:
- `seen_scores` is in-memory only. On restart it's empty.
- First tick: `reconcile(None, announced_from_disk, curr, curr)` → seed, no replay. ✅

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/reddit/score_state.py` | Added `_ahead()` helper + `reconcile()` pure function |
| `src/worldcup_bot/__main__.py` | `build_app`: init `seen_scores`; `poll_goals_job`: use `reconcile(source="api")`; `poll_thread_goals_job`: use `reconcile(source="thread")`, handle disallowed deltas |
| `tests/test_score_state.py` | Added `TestReconcile` (13 tests) |
| `tests/test_poll_goals_job.py` | Updated `_make_context` + 10 tests to supply `seen_api` |
| `tests/test_poll_thread_goals_job.py` | Updated `_make_context` + 7 tests; added `TestFlipFlopFix` (3 tests) |

**Test count: 1283 (up from 1267)**

---

## 36. Decision: Auto-Changelog via GitHub Release Workflow

**Author:** Maldini
**Date:** 2026-06-17
**Status:** IMPLEMENTED

### Context

The repo had no CHANGELOG.md and the CI workflow used `--generate-notes` (GitHub-generated release notes). The team wanted a human-readable CHANGELOG.md that auto-updates from real commit subjects on every release, with internal Scribe commits filtered out.

### Decision

Added automated CHANGELOG.md maintenance to `.github/workflows/docker-deploy.yml`. A new `CHANGELOG.md` file is created at the repo root with a `<!-- releases -->` marker where entries are inserted newest-first.

### Mechanism

1. **Range detection:** After CalVer (which already runs `git fetch --tags`), `git describe --tags --abbrev=0` finds the previous release tag. Range is `$PREV_TAG..HEAD`; falls back to `HEAD` on first release (no previous tag).
2. **Commit filtering:** `git log "$RANGE" --no-merges --pretty=format:'%s'` is piped through four `grep -v -i` filters:
   - `^\.squad:` — Scribe memory commits
   - `^docs: update changelog` — the auto-commit itself (loop prevention)
   - `^Merge ` — merge commits
   - `^chore:` — non-user-facing housekeeping
3. **Prefix stripping:** `sed -E 's/^(feat|fix|perf|refactor|docs)(\([^)]+\))?: //'` removes conventional-commit prefixes for readability; plain imperative subjects are left unchanged.
4. **Bullet list:** `sed 's/^/- /'` prefixes each surviving line. Written to `release_notes.md` on disk to avoid multiline-output escaping in `$GITHUB_OUTPUT`.
5. **Release creation:** `has_notes=true` → `--notes-file release_notes.md`; `has_notes=false` (all commits internal) → fallback `--generate-notes`.
6. **CHANGELOG insertion:** `sed -i "/<!-- releases -->/r new_entry.md"` appends the `## [VERSION] - DATE` block right after the marker (newest-first). Avoids awk `-v` multiline quoting issues.
7. **Loop prevention:** Auto-commit uses `[skip ci]` suffix so GitHub Actions skips the push.
8. **Race resilience:** Non-fast-forward push retried once with `git pull --rebase --autostash`; second failure logs a warning and exits 0 — deploy never fails over the changelog.

### Constraints Honored

- Docker image build/push and CalVer logic untouched.
- No Python application code or Dockerfile modified.
- `permissions: contents: write` was already present.
- `fetch-depth: 0` was already present on checkout.

---

## 37. Decision: Goal Detection Rework — Block 1

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 789 tests green, not yet committed (coordinator commits at end of multi-block goal).

### Problem

The previous goal notifier detected goals by **parsing Reddit match threads** via `parse_goal_events`, which required the ESPN-structured format:
```
⚽ Goal! France 1, Senegal 0. Mbappé (France)
```

The France-Senegal thread (1u7ltq6) used a **human-narrated format** with no `⚽` emoji and no structured `Goal!` line:
```
66': [](#icon-ball-big)**GOAL FRANCE!! ...narrative... _Kylian Mbappé_ ...**
```

Result: `parse_goal_events` found 0 goals → nothing notified (bug #1).

Additionally, re-parsing Reddit on each tick caused flip-flops (1-0 → 1-1 → 1-0) when ESPN reordered events mid-game (bug #5).

### Decision

**Use football-data.org score changes as the AUTHORITATIVE goal detection source.** Reddit/OpenAI is used ONLY for scorer enrichment.

#### Rationale
- football-data.org free tier reliably reports `home_score`/`away_score` on `IN_PLAY`/`PAUSED` matches, even though it does not provide scorer or minute.
- Score changes are monotonic and unambiguous: increase = goal, decrease = VAR disallowed.
- LLM reads natural language — handles ANY Reddit thread format, not just ESPN-structured.
- Persistent state survives bot restarts; seed-on-first-sight prevents false positives.

### Implementation

#### New modules

**`src/worldcup_bot/reddit/score_state.py`**
- `GoalDelta` dataclass: `{side, scoring_team, new_home, new_away, kind: "goal"|"disallowed"}`
- `load_scores(path) → dict` — reads `{state_dir}/live_scores.json`, returns `{}` on any error (graceful)
- `save_scores(path, data)` — best-effort, swallows/logs failures
- `diff_scores(stored, match) → list[GoalDelta]` — pure: `None` stored → seed (return `[]`); increase → goal(s); decrease → disallowed

**`src/worldcup_bot/ai/goal_extractor.py`**
- `extract_scorer(ai, thread_text, scoring_team, home_team, away_team, new_home, new_away) → (scorer|None, minute|None)`
- Strict information extractor prompt: "Devuelve ÚNICAMENTE JSON {\"scorer\": ..., \"minute\": ...}". No invention. `null` if not found.
- `_parse_extractor_json(raw)` — strips ``` fences; returns `(None, None)` on garbage
- Thread text trimmed to last 6000 chars; uses `max_completion_tokens=100` (not `max_tokens`)

#### Modified modules

**`src/worldcup_bot/reddit/notifier.py`** — added:
- `format_new_goal_message(scoring_team, home_name, away_name, home_score, away_score, ...)` → HTML, scoring team bold, flag emojis, optional scorer + minute line
- `format_disallowed_message(home_name, away_name, home_score, away_score, ...)` → HTML VAR message
- Kept: `format_goal_notification`, `build_goal_keyboard` (used by cmd_simula_gol + block-2 flow)

**`src/worldcup_bot/reddit/parser.py`** — REMOVED `compute_new_goals` (Reddit-parse detection mechanism). Kept `parse_goal_events` as fallback enrichment helper.

**`src/worldcup_bot/__main__.py`** — rewrote `poll_goals_job`:
- `load_scores(state_path)` each tick (persistent across restarts)
- `get_all_matches()` (cached); relevant = IN_PLAY/PAUSED or FINISHED-already-tracked
- First-seen → SEED (no notify)
- Score change → `_process_goal_delta` → sends HTML message WITHOUT keyboard
- Enrichment via `_enrich_scorer`: `find_match_thread` → `get_thread_body` → OpenAI `extract_scorer` → `parse_goal_events` fallback → `(None, None)`
- `save_scores` after any state change
- Removed: `notified_goal_keys`, `seeded_threads`, `compute_new_goals`, `build_goal_keyboard` usage

### NOT in block 1 (block 2)
- "Ver gol" inline keyboard on goal messages
- Clip download / video sending
- `goal_clips` population from new job

### Tests added (56 new, 789 total)
- `tests/test_score_state.py` — diff_scores (seed, home goal, away goal, double increase, decrease→disallowed, no change, None scores), load/save round-trip, error handling
- `tests/test_goal_extractor.py` — `_parse_extractor_json` (clean, fenced, garbage, nulls, empty strings), `extract_scorer` (AI success, AI failure, garbage, trim, temperature, system prompt content)
- `tests/test_goal_formatter.py` — `format_new_goal_message` (scorer present/absent, flags, bold team, HTML escaping, score, both team names), `format_disallowed_message` (VAR text, score, flags, escaping)
- `tests/test_poll_goals_job.py` — seed-on-first-sight (no sends), score increase → goal message (no keyboard), state updated, FINISHED-already-tracked catches final goal, FINISHED-not-tracked ignored, VAR disallowed message, persistence called/not-called on changes/no-changes, API error → no save
- `tests/test_reddit_parser.py` — removed `TestComputeNewGoals` (function deleted)

---

## 38. Decision: Block 2 — Decoupled Clip Search & Persistent Clip Store

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** Implemented, 826 tests green

### Context

Block 1 sent goal messages without a "Ver gol" button. Block 2 decouples the clip search from the goal notification: the goal message fires immediately, then a background job searches Reddit and edits the message to add the button only when the clip is ready.

### Decisions

#### 1. Persistent clip state: `reddit/clip_store.py`
- File: `{state_dir}/goal_clips.json`. One entry per `token` (SHA1[:12] of a goal key).
- Entry fields: `chat_id`, `message_id`, `home_name`, `away_name`, `home_tla`, `away_tla`, `home_score`, `away_score`, `scoring_team`, `scorer`, `minute`, `status` ("searching"|"ready"|"timeout"), `clip_path`, `file_id`, `attempts`, `created_at`.
- `load_clips` / `save_clips` are best-effort (swallow + log on error).
- `add_entry` initialises status="searching", attempts=0, timestamps.
- `prune_old_entries` removes entries older than 7 days (prevents volume bloat).
- **Rationale:** Pure sync module, no async, no Telegram → safe to call anywhere.

#### 2. `bot_data["clip_store"]` as authoritative in-memory dict
- `build_app` loads `goal_clips.json` into `bot_data["clip_store"]` at startup.
- Callbacks and jobs mutate this dict; JSON file is persisted after each write.
- Old `bot_data["goal_clips"]` and `bot_data["clip_file_ids"]` removed entirely.
- **Rationale:** Single source of truth, survives restart: "ready" entries work immediately (clip_path on disk, file_id cached), "searching" entries resume in background.

#### 3. `_process_goal_delta` captures `message_id`
- After `send_message` for a goal, captures `sent.message_id` and calls `add_entry` + `save_clips`.
- Disallowed (VAR) branch returns early — no clip-store entry created.

#### 4. `poll_goal_clips_job` (run_repeating, 45s, first=20s)
- Iterates "searching" entries. Per entry: `attempts += 1`. If > 25 → "timeout".
- `find_goal_clip` via `asyncio.to_thread`; `MediaDownloader.download` awaited directly.
- Downloads to temp file → `compress_if_needed` → `shutil.move` to `{clips_dir}/{token}.mp4`.
- `probe_video` for dims. Sets `status="ready"`, `clip_path`.
- `edit_message_reply_markup` to add `build_goal_keyboard(token)`.
- Each entry wrapped in `try/except` for isolation.
- `prune_old_entries` called every tick.
- Scheduled only when `telegram_group_id` is set.

#### 5. Reworked `cmd_ver_gol_callback`
- Reads from `bot_data["clip_store"]` (not `goal_clips`).
- Guards: unknown token → show_alert; status != "ready" or no clip_path → "no listo".
- Inflight guard: `vergol_inflight` set keyed by token.
- Fast path: `entry["file_id"]` → send by file_id (skip disk read + probe).
- Stale file_id → evict, fall through to fresh disk send.
- Fresh send: open `Path(clip_path)`, `probe_video`, `send_video` with `reply_to_message_id`.
- Cache returned file_id in entry + `save_clips`.
- TODO [Block 4]: click counter hook marked in source.

#### 6. Reworked `cmd_simula_gol`
- Sends goal message WITHOUT keyboard.
- Registers clip-store entry (status="searching") so `poll_goal_clips_job` picks it up.
- `_cs_save_clips` persists immediately.

#### 7. Clips directory
- `{state_dir}/clips/` created by `build_app` if missing.
- Clip files named `{token}.mp4`.

### Key function names (for coordinator E2E)
- `poll_goal_clips_job` — background job in `__main__.py`
- `add_entry` / `load_clips` / `save_clips` / `prune_old_entries` — in `reddit/clip_store.py`
- `cmd_ver_gol_callback` — reworked in `bot/handlers.py`
- `cmd_simula_gol` — reworked in `bot/handlers.py`

### Test count
- Baseline (Block 1): 789
- Block 2 adds: 37 new tests (clip_store: 14, poll_goal_clips_job: 13, poll_goals integration: 2, handlers: 8)
- **Total: 826 passing**

---

## 39. Decision: Match-finish message always contains a 🏁 Final result section

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 835 tests green, no commit yet.

### Context

`poll_finished_matches_job` previously sent nothing when ESPN stats were unavailable and the porra ranking did not change. Users reported that finished matches went completely silent — no confirmation that a match had ended.

### Decision

The match-finish message is now assembled from up to **3 sections** joined by `"\n\n---\n\n"` (3-dash separator):

1. **Final result** *(always present)*
   ```
   🏁 <b>Final</b>
   {home_flag} {h_name} {hs}-{as_} {a_name} {away_flag}
   ```
   The winning team's name is wrapped in `<b>…</b>` (`match.winner == "HOME_TEAM"` → bold home; `"AWAY_TEAM"` → bold away; `"DRAW"` or `None` → neither). Team names are `html.escape`d.

2. **ESPN stats card** *(only if stats were found)*  
   Unchanged stat rows. Header simplified from  
   `"📊 <b>Estadísticas — {flag} {home} {hs}-{as} {away} {flag}</b>"` → `"📊 <b>Estadísticas</b>"`  
   to avoid duplicating the scoreline already in section 1.

3. **Porra commentary** *(only if `live_diff.changed` AND `ai_enabled`)*  
   AI-generated text with `bold_person_names` applied — unchanged logic.

`send_message` is called unconditionally (section 1 guarantees a non-empty message).

### Rationale

- Users need immediate feedback that a match has ended, regardless of API availability.
- The scoreline was duplicated in section 1 (final result) and in the old stats-card header; removing it from the header keeps the card focused on statistics.
- 3-dash `---` aligns with the separator used in goal notifications; the old 4-dash `----` was inconsistent.

### Files changed

| File | Change |
|------|--------|
| `src/worldcup_bot/__main__.py` | Added `import html`, `team_flag` import; replaced combine+send logic with section-builder + unconditional send |
| `src/worldcup_bot/espn/formatter.py` | Simplified header to `"📊 <b>Estadísticas</b>"`; removed unused `html`, `team_flag` imports and 6 header-only variables |
| `tests/test_espn_formatter.py` | Updated 3 tests to reflect header no longer contains scoreline or team names |
| `tests/test_poll_finished_job.py` | `_make_match` gains `winner` param; new `TestFinalResultSection` (9 tests); `TestCombinedMessage` fully updated; `test_no_send_when_game_id_none` renamed and inverted |

---

## 40. Decision: Always generate porra commentary on match finish (Block 3 refinement)

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 882 tests green, not yet committed.

### Problem

`poll_finished_matches_job` only generated porra commentary when `live_diff.changed` was `True`. If a match finished without moving the ranking (or with no ESPN stats), users received either a bare `🏁 Final` result line with no context, or nothing.

### Decision

**Commentary is generated whenever `ai_enabled(settings)` AND `bool(ranking)` — regardless of whether the ranking changed and regardless of whether ESPN stats are available.**

The `live_diff.changed` gate is removed from Part B of `poll_finished_matches_job`.

### Implementation

#### `porra/live.py` — new `render_porra_context`

```python
def render_porra_context(diff: LiveDiff, ranking: list) -> str:
    """Always non-empty when ranking exists.
    Returns CLASIFICACIÓN ACTUAL (top-5) + CAMBIOS CON ESTE RESULTADO blocks.
    """
```

- Top-5 standings: `{pos}. {display_name} — {pts:.1f} pts`
- Changes block: movement wording if `diff.changed`, else `"Ninguno — la clasificación no se ha movido con este resultado."`
- `render_changes_text` unchanged — preserved for any other callers.

#### `__main__.py` — `poll_finished_matches_job` Part B

Before:
```python
if live_diff.changed and ai_enabled(settings):
    ...
```

After:
```python
if ai_enabled(settings) and bool(ranking):
    ...
    context_text = render_porra_context(live_diff, ranking)
```

#### `ai/commentators.py` — updated system prompt

Extended with per-scenario instructions: explains input always contains current standings + change block; if "Ninguno" appears → acknowledge no change, remind who leads; never invent movements not in the text.

### Net message structure

| Condition | Sections |
|---|---|
| No stats, no participants | `🏁 Final` only |
| No stats, AI disabled | `🏁 Final` only |
| No stats, AI enabled + participants | `🏁 Final` --- `commentary` |
| No stats, AI disabled | `🏁 Final` only |
| Stats, AI enabled + participants | `🏁 Final` --- `stats` --- `commentary` |

### Tests added / changed

- `test_porra_live.py`: `TestRenderPorraContext` (9 tests)
- `test_commentators.py`: new system-prompt tests (2)
- `test_poll_finished_job.py`: `TestAlwaysCommentary` (5 tests)

**Test count: 882 (up from 866 baseline).**

---

## 41. Decision: vergol-stats-block4 — Persistent per-user "Ver gol" counter

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Block:** 4 (final)

### Context

User requirement #6: a persistent counter of who taps "Ver gol", survived bot restarts, with a `/estadisticas` command showing the leaderboard.

### Decision

#### Module placement
New file `src/worldcup_bot/reddit/vergol_stats.py` (alongside `clip_store.py`). Both are pure/sync persistence helpers for the goal-notifier subsystem.

#### Schema
```json
{
  "<str(user_id)>": {
    "name": "<display name>",
    "tokens": ["<goal token>", ...]
  }
}
```
Keyed by `str(user_id)` (Telegram user IDs are ints; stringified for JSON key consistency). `tokens` is a list of *distinct* goal tokens. `len(tokens)` = the count shown in `/estadisticas`.

#### Deduplication
`record_view` only appends a token if it is not already in the list. Multiple taps on the same goal clip by the same user do not inflate the count. Display name is always updated to the latest value (handles username changes).

#### Load-on-tap vs. in-memory cache
Stats are loaded fresh from disk on every `cmd_ver_gol_callback` invocation. This avoids needing a new `bot_data` key and keeps the data model simple. View events are low-frequency.

#### Best-effort isolation
`_record_vergol_view` wraps all stats logic in a `try/except Exception`. A disk error, corrupt JSON, or any unexpected failure writes a warning log and returns without raising.

#### `/estadisticas` output
HTML parse_mode; names wrapped in `<b>` with `html.escape` applied; trophy header; empty-state fallback message in Spanish; numbered leaderboard sorted by count desc, name asc.

#### Registration
`CommandHandler("estadisticas", cmd_estadisticas)` added to `build_app`. Listed in `/start` help text (normal user command).

### Consequences

- `vergol_stats.json` is created on first tap in `{settings.state_dir}/`.
- Pure functions (`load_stats`, `save_stats`, `record_view`, `leaderboard`) are importable for E2E verification.
- No migration needed — missing file returns `{}` gracefully.
- Test count: 866 passing (31 new tests: 24 in `test_vergol_stats.py` + 7 in `test_handlers.py`).

---

## 42. Decision: CI Trigger Optimization via paths-ignore

**Timestamp:** 2026-06-17T08:35:56Z  
**Agent:** Maldini (DevOps)  
**Owner:** DrDonoso  
**Status:** Applied  

### Summary

Added `paths-ignore` filter to `.github/workflows/docker-deploy.yml` `push` trigger to prevent team memory (`.squad/**`) and auto-changelog (`CHANGELOG.md`) commits from triggering unnecessary Docker builds and GitHub Releases.

### Implementation

**File:** `.github/workflows/docker-deploy.yml`

**Before:**
```yaml
on:
  push:
    branches:
      - main
```

**After:**
```yaml
on:
  push:
    branches:
      - main
    paths-ignore:
      - '.squad/**'
      - 'CHANGELOG.md'
```

### Rationale

- **`.squad/**`:** Team memory (Scribe's decision ledger, agent history, etc.) never affects the bot image; commits here should not trigger CI.
- **`CHANGELOG.md`:** Auto-generated by the workflow itself on release; the commit is infrastructure-only and already protected by `[skip ci]` flag.
- **GitHub Actions behavior:** Workflow runs only if ≥1 changed file is NOT in `paths-ignore`. A push touching ONLY these paths is skipped entirely, reducing wasted Docker Hub builds and empty releases.
- **Code/config changes still trigger:** Any push touching `src/`, `tests/`, `Dockerfile`, `docker-compose*.yml`, `.github/workflows/`, or other infrastructure code will still run the workflow normally.

### Verification

- ✅ Workflow YAML is syntactically valid
- ✅ `paths-ignore` is correctly nested
- ✅ No other workflow sections modified

---

# Decision: porra-evolution checkpoints by jornada (football-day reconstruction)

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** DONE — 950 tests green

---

## Context

The original `/evolucion` feature (BLOCK 4) computed ranking history keyed by local
calendar date and reconstructed group standings via the `?date=` query parameter of the
football-data.org standings endpoint. That approach had a fundamental flaw: consecutive
football-days share UTC calendar dates (a match at 02:00 local on June 14 is still
June 13 UTC), so the `?date=` param cannot represent the 9am→9am football-day window
that `/hoy` and `/ayer` use.

## Decision

**Rebuild checkpoints entirely from match results, keyed by football-day label.**

The "football-day" is the same 9am→9am window (configurable via `settings.football_day_start_hour`)
already used by `get_football_day_matches`. A match's football-day label is:
- local date if `local_hour >= anchor_hour`
- local date minus 1 day otherwise

Group standings are **reconstructed** from the match results directly (points W=3/D=1/L=0,
GD, GF, then TLA alpha for remaining ties). Knockout winners come from finished knockout
matches in the same pass. No `?date=` API calls are made during history construction.

## Key new functions (`porra/history.py`)

| Function | Purpose |
|---|---|
| `football_day_of(match, tz, anchor_hour)` | Football-day label for a match (YYYY-MM-DD) |
| `build_jornadas(matches, tz, anchor_hour)` | Sorted distinct jornadas with ≥1 finished match |
| `reconstruct_group_standings(finished_group_matches)` | Points/GD/GF ordering per group |
| `compute_ranking_at_jornada(predictions, all_matches, jornada, tz, anchor_hour)` | Full ranking as of a jornada |
| `_check_reconstruction_vs_api(reconstructed, api_standings_raw)` | Sanity-log top-3 match vs live API |

`ensure_history` calls `get_all_matches()` once, derives all jornadas, reconstructs all
rankings from that single batch. The sanity check logs `INFO` on full match, `WARNING`
with per-group diffs on any top-3 mismatch (tie-break differences are acceptable).

## Removed dead code

- `build_checkpoint_dates` (replaced by `build_jornadas`)
- `engine.compute_ranking_at_date` (used `?date=` param, now unused)

`get_standings(date=...)` is **kept** in `api/client.py` (harmless, tested separately).

## Chart fixes

- matplotlib title: removed `📈` emoji → "Evolución de la porra" (DejaVu Sans has no emoji glyph, causing missing-box rendering)
- x-axis: labels changed from `YYYY-MM-DD` to `DD/MM` short form; axis label "Jornada" instead of "Fecha"
- Telegram caption in `cmd_evolucion` keeps `📈` (Telegram renders emoji fine)

## Test count

936 → **950** (+14). Removed `TestBuildCheckpointDates` (6) + `TestComputeRankingAtDate` (7);
added `TestFootballDayOf` (5) + `TestBuildJornadas` (7) + `TestReconstructGroupStandings` (9)
+ `TestComputeRankingAtJornada` (4) + updated `TestEnsureHistory` (7) + chart tests (2).


---

# Decision: porra-evolution exact latest jornada + startup/daily backfill

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 962 tests green.

## Context

`porra/history.py ensure_history` was building per-jornada ranking history by reconstructing group standings from match results for ALL jornadas, including the latest. The reconstruction approximates FIFA tie-breaks (no head-to-head), so the latest data point could differ ±1–2 positions from the live `/actual` ranking. Additionally, history was only populated when a user ran `/evolucion`.

## Decisions

### 1. Latest jornada uses exact live ranking

**Decision:** For the latest (most recent) jornada only, `ensure_history` now calls `engine.compute_general_ranking(predictions, client, official=False)` instead of `compute_ranking_at_jornada`. Past jornadas keep using reconstruction (acceptable approximation for a trend chart).

**Rationale:** The newest data point in the chart is the most visible and most compared against `/actual`. Using the exact live ranking eliminates the tie-break mismatch at the tip of the chart. The reconstruction is still accurate enough for the trend shape of all past jornadas.

**Implementation:**
- Inside the `for jornada in jornadas` loop, branch on `if jornada == latest`.
- Import `engine` lazily inside `ensure_history` (already the pattern for `compute_ranking_at_jornada`).
- Removed `_check_reconstruction_vs_api` and `_safe_jornada_le` helpers — they were only used by the now-removed sanity check. The sanity check was comparing reconstruction to API; it's no longer needed since the latest is exact.

### 2. Auto-backfill at startup + daily refresh

**Decision:** `history_backfill_job` is scheduled unconditionally (not gated on `telegram_group_id`) in `main()`:
- `run_once(history_backfill_job, when=15)` — 15 seconds after startup, to populate the volume on first launch.
- `run_daily(history_backfill_job, time=dtime(9,5,tzinfo=tz))` — 09:05 local time daily, just after the typical football-day close window (09:00).

**Rationale:** Users should not have to run `/evolucion` to trigger history generation. The volume should be pre-populated so the command is fast (only latest jornada recomputed). The daily refresh at 09:05 catches newly-completed jornadas automatically.

**Implementation note:** `history_backfill_job` wraps everything in `try/except` so it can never crash other jobs. Skips early if predictions file has no participants.

### 3. `/evolucion` command unchanged

`cmd_evolucion` still calls `ensure_history` (incremental) on demand. Since past jornadas are cached in the JSON file and only the latest is recomputed, the command is fast.

## Files changed

- `src/worldcup_bot/porra/history.py` — modified `ensure_history`; removed `_check_reconstruction_vs_api`, `_safe_jornada_le`
- `src/worldcup_bot/__main__.py` — added `history_backfill_job`; added `run_once` + `run_daily` scheduling in `main()`; added `from worldcup_bot.porra.history import ensure_history` import
- `tests/test_history.py` — updated `TestEnsureHistory` to patch `worldcup_bot.porra.engine.compute_general_ranking` for latest-jornada tests; added `TestEnsureHistoryLatestUsesLiveRanking` (3 tests)
- `tests/test_history_backfill.py` (NEW) — 9 tests covering job behaviour + scheduling wiring


---

# Decision: Porra Evolution Chart — /evolucion command

**Author:** Kanté (Backend)
**Date:** 2026-06-17
**Status:** READY — 936 tests green, awaiting coordinator commit + container rebuild.

---

## Summary

Adds `/evolucion` — a Telegram photo command that renders a **bump chart** showing how the porra (prediction-pool) ranking has evolved over the tournament, one line per participant.

---

## Architecture Decisions

### 1. `get_standings(date=...)` — backward-compatible param extension
- Added optional `date: str | None = None` to `FootballDataClient.get_standings()`.
- Extended `_get(url, params=None)` to accept optional query-params dict; cache key is deterministically built as `url?key=val` (sorted), so `no-date` and `with-date` have distinct cache entries.
- No existing callers need changes — `date=None` produces identical behaviour to the old signature.

### 2. Dependency-injection refactor in `engine.py`
- Extracted `compute_general_ranking_from(predictions, actual_standings, actual_winners)` — the pure scoring loop with no client dependency.
- `compute_general_ranking` retains its current signature and delegates to it (zero behaviour change; all existing tests pass).
- `compute_ranking_at_date(predictions, client, date)`:
  - Calls `client.get_standings(date=date)` for historical group standings.
  - Filters to groups with `played > 0` (safe for partially-started days).
  - Derives knockout winners from `client.get_all_matches()` filtered by `status=FINISHED` and `utc_date <= {date}T23:59:59Z` — string comparison works because format is ISO UTC.
  - Returns `compute_general_ranking_from(...)`.

### 3. History module (`porra/history.py`)
- Persistence file: `{state_dir}/porra_history.json` — dict keyed by `"YYYY-MM-DD"`, values `{username: {pos, pts, name}}`.
- `build_checkpoint_dates`: converts FINISHED match UTC timestamps → local dates via pytz (settings.timezone), deduplicates, returns sorted list.
- `ensure_history`: for each checkpoint NOT in stored history → compute; **always recompute the latest date** so it stays fresh. Best-effort save. API errors return existing history unchanged.

### 4. Chart (`porra/chart.py`)
- `matplotlib.use("Agg")` set at module import time (before pyplot) — no display/GUI required in container.
- Bump chart: x = dates (sorted), y = rank (1 at top, `ax.invert_yaxis()`), one line+markers per participant, `tab20` colormap for up to 20 users, legend outside right panel.
- Degenerate cases (0 dates, 0 users, 1 date) all handled — always write a valid PNG.
- Font warning for 📈 glyph is cosmetic only (DejaVu Sans fallback); PNG is valid.

### 5. `matplotlib>=3.8` in `pyproject.toml`
- Wheels are self-contained on `python:3.12-slim`; no additional system libs needed for the Agg backend.

---

## Public API for E2E (coordinator)

```python
from worldcup_bot.porra.history import ensure_history
from worldcup_bot.porra.chart import render_evolution_png
```

- `ensure_history(client, predictions, settings, path)` — build history from live API, returns dict.
- `render_evolution_png(history, out_path)` — render PNG, returns out_path.

---

## Caveats

- The emoji `📈` in the chart title renders as a missing-glyph box on the default matplotlib font (DejaVu Sans). This is cosmetic — the PNG is valid and the chart is readable. A font upgrade in the container could fix it but is not required.
- `ensure_history` re-fetches the latest checkpoint date on every invocation of `/evolucion`. With the shared TTL cache this is a cache hit most of the time.


---

# Decision: Changelog from Commit-Body Bullets

**Author:** Maldini (DevOps)  
**Date:** 2026-06-17  
**Status:** DONE — workflow updated, verified locally.

## Context

The `docker-deploy.yml` "Generate release notes from commits" step previously used `git log --pretty='%s'` to generate one bullet per commit subject line. For a squash-merge commit this yields a single generic bullet even when the body contains detailed, itemised bullet points.

## Decision

Replace the shell grep/sed chain with a `python3 - <<'PYEOF'` quoted heredoc. The Python script:

1. Determines range: `prev = git describe --tags --abbrev=0`; `rng = "{prev}..HEAD"` if prev else `"HEAD"`.
2. Enumerates commit SHAs via `git log rng --no-merges --format=%H`.
3. For each SHA: fetches full message via `git log -1 --format=%B`; skips commits whose subject starts with `.squad:`, `chore:`, `docs: update changelog`, or `merge ` (case-insensitive).
4. Scans the body for bullet blocks: lines starting with `- ` (after optional indent) begin a bullet; lines with 2+ leading spaces that follow a bullet are continuations (folded with a single space); any blank or non-bullet non-indented line ends the block; scanning stops at `Co-authored-by:` trailer.
5. Emits body bullets verbatim (prefixes kept). Falls back to `- {subject}` when no body bullets exist.
6. Writes to stdout; redirected to `release_notes.md`.

## Rationale

Squash commits produced by the team contain rich bullet-per-change bodies. The old approach discarded that information. The Python heredoc handles multi-line folding, trailer exclusion, and internal-commit filtering reliably without requiring extra shell tools.

## Verification

Local test against range `20260617.04^..48edda9` (single commit `48edda9`) produced 4 elaborate folded bullets:

```
- Detect goals from football-data SCORE CHANGES (reliable; ends the Reddit-parse flip-flop) with persistent per-match score state. Enrich scorer/minute via an OpenAI information extractor that handles any r/soccer thread format (ESPN-structured or human-narrated). VAR score decreases post a Gol anulado.
- Send the goal message immediately WITHOUT a button; a 45s job polls for the clip, downloads it to the state volume, then edits the message to add the Ver gol button; the tap replies with the video. Survives restarts.
- Match-finish ALWAYS posts a Final result; ESPN stats card when available; and ALWAYS a /porra recap by a random commentator (acknowledges when nothing moved), sections separated by ---.
- New /estadisticas command: a persistent per-user Ver gol view counter.
```

YAML parse: `python -c "import yaml; yaml.safe_load(open('.github/workflows/docker-deploy.yml'))"` → exit 0.

## Files Changed

- `.github/workflows/docker-deploy.yml` — "Generate release notes from commits" step `run:` block replaced.

---

## 43. Decision: Clip-match fix — D.R. Congo dotted-name normalization + dropr.co host + generic media-URL fallback

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — awaiting coordinator commit

### Context

Live production failure: `find_goal_clip` returned `None` for the goal "Portugal 1-0 D.R. Congo, João Neves 6'" even though the r/soccer clip post was found. Post title: `"Portugal [1] - 0 D.R. Congo - Neves J. goal 5'"`, post URL: `https://dropr.co/v/3ba063ff`. Two independent bugs caused the failure.

---

### Bug 1 — Team normalization dropped dotted abbreviations ("D.R. Congo")

**File:** `src/worldcup_bot/reddit/scanner.py`  
**Function:** `_normalize_team`

#### Root cause
`_normalize_team("D.R. Congo")` lowercased to `"d.r. congo"`, which is not a key in `WC_TEAM_ALIASES` (the existing key is `"dr congo"`), so the function returned `"d.r. congo"` unchanged. `_teams_match("D.R. Congo", "Congo DR")` therefore returned `False`.

#### Fix
In `_normalize_team`, after lowercase + accent-strip, add:
```python
key = key.replace(".", " ")
key = re.sub(r"\s+", " ", key).strip()
```
This transforms:
- `"D.R. Congo"` → `"d.r. congo"` → `"d r congo"` → alias → `"congo dr"` ✓
- `"D.R.Congo"` → `"d.r.congo"` → `"d r congo"` → alias → `"congo dr"` ✓

Two new alias entries added to `WC_TEAM_ALIASES`:
- `"d r congo": "congo dr"` — handles dotted "D.R. Congo" and "D.R.Congo"
- `"dem rep congo": "congo dr"` — handles "Dem. Rep. Congo" through the same transform (existing `"dem. rep. congo"` entry kept for backward compat)

---

### Bug 2 — Media URL host allowlist missed dropr.co (and was brittle)

**File:** `src/worldcup_bot/reddit/clip_finder.py`  
**Function:** `_extract_media_url`

#### Root cause
`VIDEO_URL_RE` listed only `streamable.com`, `v.redd.it`, `streamin.(me|link)`, `streamain.com`, `dubz.link`. `dropr.co` was not included, so `_extract_media_url("https://dropr.co/v/3ba063ff")` returned `None`. The "Ver gol" button was therefore never emitted even though the clip was there.

#### Fix (a) — Add dropr.co to known hosts
`dropr\.co` added to `VIDEO_URL_RE` alternation.

#### Fix (b) — Generic HTTPS fallback for future host rotation
After the known-host checks, `_extract_media_url` now applies a conservative fallback: if the URL is `http(s)` and:
- does NOT contain `reddit.com`, `redd.it`, or `imgur.com`
- path does NOT end in `.jpg/.jpeg/.png/.gif/.webp` (case-insensitive, query string ignored)

…then the URL is returned as-is as the media URL.

**Rationale:** `_match_post` only calls `_extract_media_url` after the post title has already been validated by `GOAL_TITLE_PATTERN` + team/score/scorer-or-minute checks. A title-matched post's external URL is the clip, regardless of host. The downloader's yt-dlp fallback handles playback from unknown hosts. This prevents future clip-host rotations from silently killing the "Ver gol" button again.

---

### Tests added

#### `tests/test_reddit_scanner.py` — `TestNormalizeTeam` (7 assertions)
- `_normalize_team("D.R. Congo") == "congo dr"`
- `_normalize_team("D.R.Congo") == "congo dr"`
- `_normalize_team("DR Congo") == "congo dr"` (existing alias still works)
- `_normalize_team("Democratic Republic of Congo") == "congo dr"` (existing alias still works)
- `_normalize_team("Portugal") == "portugal"` (no alias, unchanged)
- `_teams_match("D.R. Congo", "Congo DR") is True`
- `_teams_match("D.R.Congo", "Congo DR") is True`

#### `tests/test_clip_finder.py` — `TestExtractMediaUrl` (10 cases extended)
- `dropr.co` → returned as-is (known host)
- novel host `newcliphost.xyz` → returned as-is (generic fallback)
- `i.redd.it/abc.jpg` → `None` (redd.it excluded)
- `www.reddit.com/r/soccer/…` → `None` (reddit excluded)
- `imgur.com/a/x` → `None` (imgur excluded)
- `host.com/pic.PNG` → `None` (static image, case-insensitive)
- `cdn.example.com/image.jpeg` → `None` (static image)
- `newcliphost.xyz/v/clip?thumb=preview.jpg` → returned (`.jpg` only in query string, path is clean)

#### `tests/test_clip_finder.py` — `TestMatchPost`
- `test_portugal_dr_congo_dotted_name_dropr_url`: exact live-failure scenario — `_match_post` for the "Portugal [1] - 0 D.R. Congo - Neves J. goal 5'" post returns `"https://dropr.co/v/3ba063ff"`.

#### `tests/test_clip_finder.py` — `TestFindGoalClip`
- `test_portugal_dr_congo_dropr_integration`: full `find_goal_clip` with injected fake scanner returns the dropr.co URL.

---

### Result

**1152 tests green** (baseline was 1135).


---



## 43. Decision: Remove dead date= parameter from get_standings

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Status:** Applied (not committed)

### Context

The porra-evolution feature (BLOCK 4b) rewrote history reconstruction to use match results directly — zero ?date= API calls. An earlier prototype had added an optional date: str | None = None parameter to FootballDataClient.get_standings() that built a ?date=YYYY-MM-DD query string. No production caller ever passed a date (both ngine.py and handlers.py call get_standings() with no args), making it dead code.

### Decision

Remove the date parameter and all supporting code. Specifically:

1. **pi/client.py** — get_standings() signature simplified; params = {"date": date} if date else None branch removed; docstring updated.
2. **	ests/test_api_client_date_param.py** — deleted (6 tests, all specific to the dead param).
3. **	ests/test_history.py** — 	est_no_get_standings_with_date_called renamed to 	est_get_standings_not_called_from_ensure_history; replaced per-call kwargs.get("date") is None loop with ssert_not_called().

### Rationale

- The ?date= path was never wired to any live feature; keeping it creates a misleading API surface and unnecessary test burden.
- Removing it makes the signature honest: get_standings() always returns current live standings.
- The replacement assertion (ssert_not_called) is a stronger and clearer guard than the old loop.

### Test result

956 passed (was 962; −6 = deleted date-param tests). All other tests green, no behavior change.

---

## 44. Decision: Rich Image Daily Evolution

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — pending live test once gpt-image-2 key access is granted in LiteLLM.

### Feature

Every day at 11:00 Europe/Madrid, the bot takes a "rich" person image and asks
gpt-image-2 to edit it: keep the exact same face/identity, but make them progressively
wealthier. Each iteration overwrites the previous evolved image, so changes accumulate
over days.

### Key Decisions

#### 1. Data is read-only → iterated image lives in state volume
./data is mounted :ro (confirmed by Maldini). The base original is
/app/data/rich/rich_original.jpg. The iteratively-evolved image MUST live in the
writable state volume at {settings.state_dir}/rich_modified.png. On the first run, the
base original is used as source; on every subsequent run, the previously-written
ich_modified.png is used, chaining naturally.

#### 2. Level persistence via small JSON
A tiny {state_dir}/rich_state.json → {"level": int} tracks the current wealth level.
load_level returns 0 on missing/corrupt file (safe default). save_level creates the
directory if needed.

#### 3. Prompt constant lives in i/rich_image.py — easy to find and tweak
RICH_EDIT_PROMPT (module-level str) holds the base identity-preservation mandate. An
_ESCALATION_CLAUSES list (indexed by level, 0–9) provides the per-level craziness
clause. uild_rich_prompt(level) concatenates them. The user only needs to touch
ich_image.py to adjust the creative direction.

#### 4. Image-specific API credentials with fallback to chat credentials
Three new env vars: OPENAI_IMAGE_API_KEY, OPENAI_IMAGE_BASE_URL, OPENAI_IMAGE_MODEL.
If the image-specific key/url are empty, _effective_image_api_key /
_effective_image_base_url fall back to the chat key/url. This means no new env vars are
strictly required if both chat and image share the same LiteLLM endpoint.

#### 5. Soft opt-in via image_ai_enabled(settings)
The job only runs (and is only scheduled) if image_ai_enabled returns True. The job
never raises — any error is logged and swallowed.

#### 6. ich_image_chat_id — separate from 	elegram_group_id
Sending the evolved image goes to RICH_IMAGE_CHAT_ID, defaulting to empty (job still
generates and saves but doesn't send). The porra group and the image recipient can be
different. For testing, the user sets it to 3041850.

### Blocker (at time of writing)

LiteLLM key access to gpt-image-2 not yet granted — **user is fixing this in LiteLLM**.
This is NOT a max_tokens issue (images.edit has no token limit). The code is complete;
the coordinator will run a live 5-iteration test once access is confirmed.

### Files

| File | Change |
|------|--------|
| src/worldcup_bot/config.py | +5 settings fields, +3 helpers (image_ai_enabled, _effective_image_api_key, _effective_image_base_url) |
| src/worldcup_bot/ai/rich_image.py | NEW — RICH_EDIT_PROMPT, uild_rich_prompt, select_base_image, load_level, save_level, dit_rich_image, un_rich_iteration |
| src/worldcup_bot/__main__.py | +import, +ich_image_job, +scheduling in main() |
| 	ests/test_rich_image.py | NEW — 52 tests, all green |

---

## 45. Decision: Rich Image Daily Feature — Environment Variable Wiring

**Date:** 2026-06-17 13:55:52Z  
**Owner:** Maldini (DevOps)  
**Status:** ✅ COMPLETED  
**Requester:** David (@DrDonoso)  

### Summary

Wired up five environment variables across docker-compose.yml, docker-compose.local.yml, and .env.example to support Kanté's daily image-generation feature (gpt-image-2 via LiteLLM at 11:00).

### Changes

#### 1. docker-compose.yml (Production)

Added to worldcup-bot service nvironment: block (after DAILY_UPDATE_HOUR):

`yaml
      # --- Daily 'rich' image evolution (gpt-image-2 via LiteLLM) ---
      OPENAI_IMAGE_MODEL: "${OPENAI_IMAGE_MODEL:-gpt-image-2}"
      OPENAI_IMAGE_API_KEY: "${OPENAI_IMAGE_API_KEY:-}"
      OPENAI_IMAGE_BASE_URL: "${OPENAI_IMAGE_BASE_URL:-}"
      RICH_IMAGE_HOUR: "${RICH_IMAGE_HOUR:-11}"
      RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"
`

#### 2. docker-compose.local.yml (Local Development)

Identical 5 vars added to worldcup-bot service nvironment: block.

#### 3. .env.example

Added documentation block:

`ash
# Optional — Daily 'rich' image evolution via gpt-image-2 (LiteLLM at 11:00 by default).
# OPENAI_IMAGE_MODEL=gpt-image-2
# OPENAI_IMAGE_API_KEY=your-litellm-key (if empty, falls back to OPENAI_API_KEY)
# OPENAI_IMAGE_BASE_URL=https://your-litellm-host/v1 (if empty, falls back to OPENAI_BASE_URL)
# RICH_IMAGE_HOUR=11 (24h local time; default 11)
# RICH_IMAGE_CHAT_ID=3041850 (chat ID where the daily image is sent; if empty, image is generated+saved but not sent)
`

### Implementation Notes

- **Defaults:** OPENAI_IMAGE_MODEL defaults to gpt-image-2; RICH_IMAGE_HOUR defaults to 11 (24h local time).
- **Optional fallbacks:** OPENAI_IMAGE_API_KEY and OPENAI_IMAGE_BASE_URL fall back to OPENAI_API_KEY and OPENAI_BASE_URL respectively if unset (in-app logic, Kanté owns this).
- **Test value:** RICH_IMAGE_CHAT_ID example uses 3041850 (David's test chat); empty disables send (image still generated and saved to state volume).
- **Storage:** Iterated image written to existing ot_state:/app/state named volume. Base image at ./data/rich/rich_original.jpg (existing read-only mount). No new volumes.

### Validation

Both compose files validated cleanly:

`ash
$ docker compose -f docker-compose.local.yml config -q
# exit 0

$ docker compose -f docker-compose.yml config -q
# exit 0 (unset vars produce warnings only; no YAML syntax errors)
`

### Next Steps

Kanté will add logic to config.py to:
1. Read these five vars via environment.
2. Provide safe defaults (already specified above).
3. Enable the daily image generation job at the specified hour.

**Decision ID:** maldini-rich-image-env  
**Related:** Kanté's daily image feature (in progress)  
**Blocked by:** None  
**Blocking:** Kanté's config.py integration (will receive these via environment)

---

## 18. Decision: Rich-image caption + pose iteration

**Date:** 2026-06-17T15:04:47+02:00  
**Author:** Kanté (Backend Developer)

### Context

Extended the daily rich-image evolution feature built earlier today.

### Decisions

#### 1. Caption uses the main chat model (multimodal), not the image model key

`generate_rich_caption` uses `settings.openai_api_key` / `settings.openai_base_url` / `settings.openai_model` — not the image-specific variants. Rationale: the caption is a text-generation task sent to a multimodal chat endpoint (GPT-5.4 / LiteLLM). The image model key is for `images.edit` only.

#### 2. Temp-rename pattern preserves OLD image for before/after comparison

`run_rich_iteration` writes new PNG bytes to `{state_dir}/rich_modified.new.png` **before** replacing the old `rich_modified.png`. This keeps the OLD image alive so it can be base64-encoded and sent to the caption model. Only after the caption is generated is the temp atomically renamed via `os.replace`. If the old final exists it is removed first (Windows `os.replace` compatibility).

#### 3. Destination is `telegram_group_id` — `RICH_IMAGE_CHAT_ID` removed entirely

`rich_image_chat_id` setting and `RICH_IMAGE_CHAT_ID` env var removed. The photo is sent to `settings.telegram_group_id` (the same group used for goal notifications and daily updates). Sending to a separate chat_id was an unnecessary surface area.

#### 4. LiteLLM rejects legacy `max_tokens` — use `max_completion_tokens`

`generate_rich_caption` uses `max_completion_tokens=300` (not `max_tokens`). The user's LiteLLM proxy rejects the legacy parameter.

#### 5. Caption is best-effort — never fatal

If the main chat is not configured (any of `openai_api_key`, `openai_base_url`, `openai_model` is empty) or if the caption API call fails, `run_rich_iteration` falls back silently to `🤑 Nivel de riqueza {level}` (with a `log.warning` on API failure). The image is always written.

#### 6. `_caption_client` and `_client` are independent injectables

Tests can mock image editing and caption generation independently. This keeps unit tests fast and reliable without network calls.

---

## 19. Decision: Rich Image — Bounded Text History, JSON Caption+Memo, History in Both Generators

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 1052 tests green (+26)

### Context

The live E2E confirmed that rich-image captions and images work, but after a few days items started repeating (Rolls, yacht, same vacations). The user requested a persisted text history fed to both generators to avoid repetition, plus richer image composition variation.

### Decisions

#### 1. Bounded plain-text history — `rich_history.txt`, cap 20 lines

A plain-text file at `{state_dir}/rich_history.txt` accumulates one line per successful iteration:
```
{date_str} | nivel {level} | {memo}
```
After every append, the file is truncated to keep only the **last 20 lines** (`RICH_HISTORY_MAX_LINES = 20`). This bounds the token cost injected into prompts while preserving enough context to avoid repetition across several weeks.

- `append_history(state_dir, date_str, level, memo)` — appends + truncates; skips if memo is empty/whitespace.
- `load_history_lines(state_dir) -> list[str]` — returns stripped non-blank lines, [] if missing/corrupt.
- `format_history_for_prompt(state_dir) -> str` — bullet-list with "- " prefix, or "" if empty.

#### 2. Caption returns JSON `{"caption": "...", "memo": "..."}`

`generate_rich_caption(...)` now returns `tuple[str, str]` = (caption, memo):

- The model is instructed to return **only** a JSON object.
- On successful parse: returns (caption, memo).
- On any JSON parse failure: returns (raw_stripped_text, "") — feature never breaks.
- Code-fence stripping handles ` ```json ... ``` ` wrapper the model may add.
- `max_completion_tokens` raised from 300 → 500 to accommodate JSON overhead.
- API/transport errors still raise RuntimeError (caller handles fallback).

#### 3. Context: person rigs our porra

`RICH_CAPTION_PROMPT` updated to make explicit that:
- The person is getting rich by **rigging the group's porra** (amañando la porra del grupo).
- Tone stays chulesco/prepotente/burlón but from the position of cheating-the-group superiority.

#### 4. History fed to BOTH generators

In `run_rich_iteration`:
1. `history = format_history_for_prompt(settings.state_dir)` (previous days).
2. `build_rich_prompt(level, history)` — when history non-empty, appends "Previously shown across past days (introduce NEW, different luxuries/scenes/people; do NOT repeat these): {history}".
3. `generate_rich_caption(..., history=history)` — when history non-empty, user message includes "YA HAS PRESUMIDO DE ESTO ANTES — NO lo repitas:\n{history}".
4. `append_history(state_dir, date_str, level, memo)` persists the new memo after caption.

#### 5. Image composition variation — CHANGE A

`RICH_EDIT_PROMPT` updated to explicitly ENCOURAGE:
- Freely changing the person's **POSTURE and POSE**.
- Bringing **HANDS** into view with gestures (holding objects, arms open, pointing, etc.).
- **INCLUDING OTHER PEOPLE** around the main subject (entourage, friends, staff, models, guests, bodyguards) — only the MAIN subject's identity must be preserved.

### Files Changed

- `src/worldcup_bot/ai/rich_image.py` — all changes above
- `tests/test_rich_image.py` — +26 tests (1052 total, up from 1026)

---

## 20. Consolidate Rich Image Destination to TELEGRAM_GROUP_ID

**Decision ID:** maldini-remove-rich-chat-id  
**Date:** 2026-06-17T15:07:58Z  
**Agent:** Maldini (DevOps)  
**Requested by:** David (@DrDonoso)

### Problem

The rich-image daily feature had previously been wired to send images to a separate `RICH_IMAGE_CHAT_ID`. The destination is now consolidated: images go to the existing `TELEGRAM_GROUP_ID` (the shared group). The `RICH_IMAGE_CHAT_ID` env var is no longer needed.

### Decision

Remove `RICH_IMAGE_CHAT_ID` from environment configuration entirely. Keep the other 4 image-generation vars (`OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_API_KEY`, `OPENAI_IMAGE_BASE_URL`, `RICH_IMAGE_HOUR`).

### Changes

#### Files Modified

1. **docker-compose.yml** (prod)
   - Removed `RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"` from `worldcup-bot` service environment block.
   - Kept 4 image vars: `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_API_KEY`, `OPENAI_IMAGE_BASE_URL`, `RICH_IMAGE_HOUR`.

2. **docker-compose.local.yml** (dev)
   - Removed `RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"` from `worldcup-bot` service environment block.
   - Kept 4 image vars (same as prod).

3. **.env.example**
   - Removed `RICH_IMAGE_CHAT_ID=3041850` line.
   - Removed explanatory comment: "chat ID where the daily image is sent; if empty, image is generated+saved but not sent".
   - Updated section comment from "Daily 'rich' image evolution" to clarify: "Image is sent to TELEGRAM_GROUP_ID."

### Validation

Both compose files parse cleanly after changes:
```
docker compose -f docker-compose.local.yml config -q   # exit 0
docker compose -f docker-compose.yml config -q          # exit 0
```

### Rationale

- Simplifies configuration: one group ID instead of two.
- Reduces env-var surface: fewer optional vars to document and manage.
- Aligns with Kanté's code logic: image destination is now hardcoded to the group.

### Impact

- ✅ **Dev/test:** No image regression; local compose still builds and validates.
- ✅ **Prod:** No change in deployment model; Kanté owns runtime logic.
- ⚠️ **Existing containers:** If `RICH_IMAGE_CHAT_ID` was set in production, it will be ignored (not an issue since feature is new).

### Notes

- No code changes (`config.py` / `src/**` owned by Kanté).
- No git commit (as requested).
- History logged in `.squad/agents/maldini/history.md`.

---


---

# Decision: Rich Caption Newline Normalization + Escalate Opulence Emphasis

**Date:** 2026-06-17
**Author:** Kanté (Backend Developer)
**Status:** Implemented

## Context

Two issues surfaced after the hybrid face-anchor feature went live:

1. **Literal `\n` in captions**: The caption model occasionally returns the two characters `\` and `n` (backslash-n) instead of a real line break — e.g. `"...humor.\\nMe he fugado..."`. Telegram renders these as literal text rather than line breaks, breaking the visual layout.

2. **Opulence not escalating visibly**: The prompt did not emphasize that each iteration MUST look *more* luxurious than the one before. Users reported the richness plateau-ing or varying randomly rather than clearly escalating. An optional accessories angle (sunglasses/hat) was also requested to add visual variety.

## Decision

### 1. `_normalize_caption(text: str) -> str`

New private helper in `rich_image.py`:
- Replaces literal `\\r\\n` and `\\n` sequences with real newlines (handles the backslash-n quirk).
- Normalizes real `\r\n` → `\n`.
- Collapses 3+ consecutive newlines to exactly 2.
- Strips trailing spaces on each line and strips the whole string.

Applied to the `caption` return value in `generate_rich_caption` (both the JSON `data["caption"]` path and the non-JSON fallback `raw` path). The `memo` is trimmed (`.strip()`) but not run through the multi-line normalizer — it is intentionally single-line.

### 2. `RICH_EDIT_PROMPT` — escalation emphasis + accessories

Added a CRITICAL-labelled sentence as the leading instruction:

> "CRITICAL: the result MUST look clearly and NOTICEABLY richer and more luxurious than the input image — escalate the opulence visibly each iteration: a more expensive outfit, a grander setting, more lavish props and wealth signals than before."

Added optional accessories line:

> "You MAY occasionally add tasteful accessories such as elegant sunglasses or a stylish hat (vary it; not every time)."

All moderation-safe framing is preserved: positive dressing language ("dress in a fully-clothed luxury outfit", "tasteful", "elegant"), no "change/remove/alter clothing" phrasing.

### 3. `RICH_FACE_ANCHOR_CLAUSE` — surpass framing

Updated to reinforce escalation in the anchor path:

> "Use the first image for the wealthy style, but SURPASS it — the new image must look clearly richer and more luxurious than the first, not merely match its opulence."

The face-anchor-to-original instruction (EXACTLY/original) is fully preserved.

## Consequences

- Captions sent to Telegram always have clean, real newlines regardless of how the model encoded them.
- Each iteration is explicitly instructed to beat the previous one in opulence — the main user request.
- Accessories (sunglasses/hat) are available as an occasional stylistic variation without becoming repetitive.
- 1123 tests green (+27 from 1096 baseline). All pre-existing tests unchanged.


---

# Decision: Rich-Image Captions — No Slash Separators

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented

## Problem

Rich-image captions sent to users were containing literal `" / "` separators between sentences (e.g. `"Me he comprado un yate. / Me fui de Mónaco. / Pringados."`).

## Root Cause

`append_caption` stored each multi-line caption as a single line by replacing `\n` with `" / "`. Those stored lines were fed back to the language model as `recent_captions` (examples of prior captions for variety). The model imitated the `" / "` style and produced new captions with literal slash separators instead of real line breaks.

## Fixes Applied

### 1. `append_caption` — store with spaces, not slashes
Replace `caption.replace("\n", " / ")` with `re.sub(r'\s+', ' ', caption).strip()`.  
Stored examples no longer contain slashes, so the model has no reason to imitate them.

### 2. `_normalize_caption` — convert slash separators to newlines
Add `re.sub(r'\s+/\s+', '\n', text)` after CRLF normalisation.  
Any `" / "`, `" /\n"`, or `"\n/ "` pattern becomes a clean `\n`.  
Non-separator slashes (`24/7`, `and/or`) are unaffected — they have no surrounding whitespace.

### 3. `RICH_CAPTION_PROMPT` — explicit instruction in Spanish
Added: `"Separa las frases con SALTOS DE LÍNEA, NUNCA con barras \"/\" ni con \" / \"."`  
Tells the model up-front to use line breaks, never slash separators.

## Test Impact

12 new tests added in `tests/test_rich_image.py`. Total: 1135 (was 1123). All green.


---

# Decision: Hybrid Multi-Image Face-Anchor for Rich Image Edit

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented

## Context

The rich-image feature runs daily, progressively making a person look wealthier. Each iteration feeds the previous output as input. Over time the face and identity drifted (the model quietly altered appearance while only changing the background). Additionally, the output kept the same pose and clothing unchanged — only the background swapped.

## Decision

### 1. HYBRID multi-image edit [previous, original]

Each iteration now passes **two images** to `client.images.edit`:
- Image 1 (first): the evolved `rich_modified.png` from the state dir (continuity of wealthy style).
- Image 2 (second / anchor): the original `{data_dir}/rich/rich_original.*` (face reference).

This is activated only when an evolved image exists (`using_anchor = abspath(base) != abspath(original)`). First run is always single-image (base IS the original). Confirmed working on the user's LiteLLM/Azure gpt-image-2 deployment (api_version 2025-04-01-preview).

### 2. RICH_FACE_ANCHOR_CLAUSE

A constant appended to the prompt when `anchor=True`:
> "A second reference image (the ORIGINAL photo of this person) is provided. The face, head, skin tone and facial features in your result MUST be an EXACT match to that ORIGINAL reference. Do NOT copy the clothing, outfit, pose or background from any reference image — invent NEW luxury clothing and a NEW pose. Use the FIRST image only for continuity of the wealthy style you are building on."

### 3. RICH_EDIT_PROMPT: mandatory clothing + pose changes

Rewrote the prompt to include a **MANDATORY CHANGES** section that explicitly requires:
1. CLOTHING/OUTFIT: design completely NEW luxury attire every iteration — do NOT keep same clothes.
2. POSTURE/POSE: choose a fresh body positioning each time.
3. SETTING/BACKGROUND: evolve the scene.

Identity preservation is now scoped to face/head/skin tone/facial features/build only — not clothing.

## Consequences

- Face identity is locked to the original from run 2 onwards, stopping multi-day drift.
- Clothing, pose and scene change every iteration as required.
- `build_rich_prompt(anchor=bool)` exposes the anchor toggle cleanly.
- `edit_rich_image(anchor_path=...)` handles both single and dual-image calls transparently.
- `find_original_image(data_dir)` always resolves the original independently of the state dir.
- If the original is missing at runtime, graceful fallback to single-image mode (no crash).
- 1096 tests green (+28 new tests).


---

# Decision: Rich Image — Model-Driven Escalation + Caption Variety

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 1068 tests green  

---

## Context

The previous rich-image feature used a hardcoded `_ESCALATION_CLAUSES` list indexed by a `level` counter. Each run picked a clause (ático→club→jet→Rolls→yacht→...) that told the image model exactly what wealth marker to add. Two problems emerged:
1. The model was constrained to fixed escalation steps rather than naturally evolving the photo.
2. Captions were repeating the same coletillas ("seguid poniendo pasta", "currelas", "muertos de hambre", "a vuestra salud", "pringados") because no caption history was fed back.

---

## Decisions

### 1. Removed level escalation — richness is model-driven and implicit

`_ESCALATION_CLAUSES` deleted. `build_rich_prompt` no longer takes a `level` parameter.

`RICH_EDIT_PROMPT` now:
- Asks the model to make the person look **SOMEWHAT richer** (a few notches up, not a leap).
- States that richness grows **gradually and implicitly** because each run feeds the previous output as input.
- Mandates: pick only **a FEW NEW touches per iteration** and **VARY them** — do NOT add everything at once.
- Explicitly encourages: changing POSTURE/POSE, bringing HANDS into view, adding OTHER PEOPLE (entourage, bodyguards, etc.), adding luxury VEHICLES (sports car, Rolls-Royce, private plane, yacht, helicopter), or moving to a different SETTING (pool, rooftop terrace, private-jet cabin, tropical private island, mansion, casino, ski chalet, designer boutique).
- Maintains STRICT IDENTITY PRESERVATION (same face, skin tone, body, hair, distinguishing traits).

`load_level` / `save_level` are kept as an **iteration counter** (no longer content-selection).

### 2. rich_history cap raised to 30

`RICH_HISTORY_MAX_LINES` was 20, now **30**.  
History line label changed from `"nivel"` to `"iter"`: format is now `"{date_str} | iter {n} | {memo}"`.

`format_history_for_prompt` gained a `max_items=None` parameter. The image prompt uses `max_items=12` (concise); the caption call uses the full 30.

### 3. Added rich_captions.txt — cap 6

New bounded store: `rich_captions.txt`, `RICH_CAPTIONS_MAX = 6`.

- `append_caption(state_dir, caption)` — collapses newlines to `" / "`, caps at 6 lines.
- `load_captions(state_dir) -> list[str]`
- `format_captions_for_prompt(state_dir) -> str` — `""` if empty, newline-joined block otherwise.

`generate_rich_caption` now accepts `recent_captions: str = ""`. When non-empty, injects:
> `TEXTOS ANTERIORES (NO repitas su estructura, aperturas, insultos ni despedidas — usa vocabulario y coletillas DISTINTAS):\n{recent_captions}`

`RICH_CAPTION_PROMPT` updated to explicitly instruct the model to **VARY** daily: no fixed openings, no fixed insults, invent fresh vocabulary each time.

### 4. run_rich_iteration wiring

Order:
1. Read `image_history` (last 12 memos), `full_history` (all 30), `recent_captions` (last 6 captions) **before editing**.
2. Edit image using `image_history`.
3. Generate caption using `full_history` + `recent_captions` (best-effort).
4. On caption **success**: `append_history(memo, cap=30)` + `append_caption(caption, cap=6)`.
5. On caption **failure**: fallback `"🤑 Cada día más rico a vuestra costa"`, nothing appended.
6. Rename temp → final, save iteration counter.

---

## Test Count

1068 tests pass (+16 new). New: `TestRichCaptions` (9), `TestBuildRichPrompt` rewritten, new `TestRichEditPromptContent` assertions, `format_history_for_prompt` max_items, `TestGenerateRichCaption` recent_captions, `TestRunRichIteration` new integration tests.


---

# Decision: Azure Image Moderation — Safe Prompt Framing for Rich-Image

**Date:** 2026-06-17  
**Agent:** Kanté (Backend Developer)  
**Files:** `src/worldcup_bot/ai/rich_image.py`, `tests/test_rich_image.py`

## Problem

`gpt-image-2` returned `400 moderation_blocked safety_violations=[sexual]` on the FIRST (single-image) rich-iteration call. Root cause: the `RICH_EDIT_PROMPT` contained the phrase "MANDATORY CHANGES — CLOTHING and OUTFIT: design completely NEW luxury attire — do NOT keep the same clothes or outfit from the input image." Azure's image safety moderator interprets "change the clothing / change the outfit" on a real person's photo as an undressing instruction and flags it as sexual content.

## Decision

Replace all "change/remove/swap/alter clothing/outfit" language with **positive luxury-dressing framing**: instruct the model to *dress* the person in a brand-new, elegant, fully-clothed outfit, never to *remove or change* what they are wearing.

## Verified-Safe Wording (live-tested by coordinator, msgs 523/524)

**`RICH_EDIT_PROMPT`**  
> "Transform this photo into a photorealistic image where the person looks wealthier and more glamorous. Keep the EXACT same face, head, skin tone and facial features — the same identity. Dress them in a brand-new, elegant, fully-clothed luxury outfit (for example a tailored designer suit, a tuxedo, a smart blazer or a refined formal coat) — always tasteful and fully clothed. Give them a new confident pose with hands in view. Place them in a new opulent setting and add a few varied signs of wealth (an elegant entourage, a luxury car, a yacht, a private jet, fine jewellery) — a few new touches each time, growing gradually. Classy, elegant, photorealistic."

**`RICH_FACE_ANCHOR_CLAUSE`** (appended when `anchor=True`)  
> " A second reference image (the ORIGINAL photo) is provided; match the face, skin tone and features EXACTLY to that original. Use the first image only for the wealthy style. Invent a new elegant outfit and a new pose; keep the person fully and tastefully clothed."

## Rules for Future Prompt Edits

1. **Never** use the words "change", "alter", "remove", "swap" in conjunction with "clothing", "outfit", "clothes", or "attire" in a prompt sent to an image-generation model. Azure moderation reads this as undressing on a real person.
2. **Always** frame the clothing instruction as positive dressing: "dress them in…", "wear…", "outfit them with…", always followed by "fully clothed", "tasteful", "elegant".
3. Preserve face/skin/features language is safe and required.
4. Luxury items (entourage, car, yacht, private jet, jewellery) are safe and encouraged.


---

# Decision: Rich Photo Folder Gitignore Pattern

**Date:** 2026-06-17T17:05:00+02:00  
**Agent:** Maldini (DevOps)  
**Requested by:** David (@DrDonoso)

## Problem Statement

The rich-image feature (daily image generation with base photo) reads `data/rich/rich_original.jpg` at runtime. This is a PERSONAL photo, and the repo is PUBLIC on GitHub, so the photo must NEVER be committed. However, the `data/rich/` folder must exist in the repo structure (it's mounted via `./data:/app/data:ro` in docker-compose) so that deployment can locate the photo on the production server.

## Solution

Mirror the existing `data/tongo_gifs/` pattern in `.gitignore`:

1. **Edit `.gitignore`:** Added a two-line commented block after the tongo_gifs section:
   ```
   # Personal base image for the daily 'rich' feature — drop rich_original.jpg into data/rich/ on the server (mounted, not committed).
   data/rich/*
   !data/rich/.gitkeep
   ```

2. **Create `data/rich/.gitkeep`:** Empty file ensures the folder is tracked by git without tracking the photo itself.

## Verification

- `git status --porcelain data/rich` → Shows `?? data/rich/` (untracked folder; only .gitkeep is present).
- `git check-ignore -v data/rich/rich_original.jpg` → Returns `.gitignore:33:data/rich/*	data/rich/rich_original.jpg`, confirming the photo is correctly ignored.

## Rationale

- **Consistency:** Identical pattern to `data/tongo_gifs/` (runtime media, git-ignored, folder tracked via .gitkeep).
- **Deployment:** Folder structure is preserved in the repo; ops mount it read-only and populate `rich_original.jpg` on the server.
- **Security:** Personal photo stays off the public GitHub repo.

## Status

✅ Complete. Not committed (as instructed).




---

## 46. Decision: Robust clip scorer matching for r/soccer title formats

# Decision: Robust clip scorer matching for r/soccer title formats

**Date:** 2026-06-17  
**Agent:** Kanté (Backend Developer)  
**File:** `src/worldcup_bot/reddit/clip_finder.py`  
**Trigger:** LIVE bug — Yoane Wissa goal (Portugal 1-1 D.R. Congo, 45') failed to match
r/soccer clip "Portugal 1 - [1] D.R. Congo - Wissa Y. goal 49'"

---

## Problem

r/soccer clip post titles mix at least two scorer formats:
1. **"Surname Initial. goal"** — e.g. `Wissa Y. goal`, `Neves J. goal`, `R. Leão goal`
2. **"Firstname Lastname"** — e.g. `João Cancelo`, `Viktor Gyökeres`

In addition, accented characters appear in both target names (from football-data.org)
and clip titles (e.g. `Gyökeres`, `João`).

Added-time goals cause **minute drift**: the internal event fires at the regulation
minute (e.g. 45') but the clip post title uses the real clock minute (e.g. 49').

The old `_scorer_matches` relied on `str.lower()` substring/last-token equality.
It failed when the last token of the clip scorer was `"goal"` rather than the surname.
The old ±2 minute tolerance was too tight for added-time drift (diff=4 for Wissa).

---

## Decision

### Fix 1 — Accent-folded token-intersection scorer matching

Rewrote `_scorer_matches(clip_scorer, target_scorer)` in `clip_finder.py`:

- **Accent-fold both** using `unicodedata.normalize("NFKD", s)` + drop combining marks
  (`unicodedata.category(c) != "Mn"`) + lowercase. Added `_fold()` helper.
- **Tokenise** via `re.findall(r"[a-z0-9]+", folded)`.
- **Drop noise**: `_SCORER_NOISE = {"goal","goals","penalty","pen","og","owngoal","own"}`
  and any single-character token (initials like `"y"`, `"j"`).
- If **both sides** yield tokens: True if `set(ct) & set(tt)` is non-empty (shared
  surname/name token), OR cleaned joined strings are substrings of each other.
- If **either side** is emptied by cleaning: fallback to plain accent-folded string
  equality / substring / last-token equality (so noise-only clip sides return False).

Examples now correct:
| clip_scorer | target_scorer | result |
|---|---|---|
| `"Wissa Y. goal"` | `"Yoane Wissa"` | True ✓ |
| `"Neves J. goal"` | `"João Neves"` | True ✓ |
| `"João Cancelo"` | `"João Cancelo"` | True ✓ |
| `"Gyökeres"` | `"Viktor Gyökeres"` | True ✓ |
| `"R. Leão goal"` | `"Rafael Leão"` | True ✓ |
| `"Messi"` | `"Cristiano Ronaldo"` | False ✓ |
| `"goal"` | `"Ronaldo"` | False ✓ |
| `""` | `"Ronaldo"` | False ✓ |

### Fix 2 — Minute tolerance widened to ±3

Changed `minute_ok = abs(clip_minute - minute) <= 2` → `<= 3` in `_match_post`.

Rationale: added-time goals can drift by 3–4 minutes between event detection and
clip post title. The scorer fix is the primary mechanism; ±3 is defense-in-depth.
Do **not** widen further — ±4+ risks matching neighbouring goals in the same match.

The condition remains `scorer_ok OR minute_ok` (either signal suffices).

---

## Tests added (`tests/test_clip_finder.py`)

- `TestScorerMatches`: 8 new cases covering all formats above + `test_partial_last_name_accent_stripped` (accent-fold makes "Gyokeres" == "Gyökeres" → True)
- `TestMatchPost.test_wissa_scorer_format_minute_off_by_four`: verifies dropr.co URL returned for Wissa with minute diff=4 (scorer carries the match)
- `TestMatchPost.test_guard_wrong_scorer_and_minute_far_off_returns_none`: different scorer + minute far off → None

Final suite: **1161 passed**.


---

## 47. Decision: Always merge HTML search + /new/ listing for clip lookup

# Decision: Always merge HTML search + /new/ listing for clip lookup

**Author:** Kante (Backend)  
**Date:** 2026-06-17  
**Status:** PROPOSED — awaiting coordinator merge

## Problem

r/soccer HTML search index lags behind real time. Very recent clips (posted seconds-to-minutes ago) appear in the `/new/` listing before the search index includes them. The previous `find_goal_clip` logic only fell back to `/new/` when HTML search returned **zero** results. When HTML search returned non-empty results (other posts for the same match) but was missing the just-posted clip, the clip was never found.

LIVE example: `"Portugal [2] - 1 D.R. Congo - João Cancelo 55'"` (url `https://streamin.link/v/f5eabdf2`) existed in r/soccer `/new/` but not in the HTML search window. HTML search returned Wissa + Neves posts (so it was non-empty), so `/new/` was never consulted.

## Decision

When JSON search returns None (403/failure), **always** fetch both `_fetch_html_search_posts` AND `_fetch_html_posts` (/new/ listing) and merge them deduplicated by post id, preserving order (HTML search results first, then /new/ entries not already seen).

The JSON-success path is unchanged.

## Implementation

`src/worldcup_bot/reddit/clip_finder.py` — `find_goal_clip`:

```python
posts = _fetch_search_posts(scanner, search_url)
if posts is None:
    log.info("find_goal_clip: JSON search 403/failed, using HTML search + /new/ listing")
    merged: list[dict] = []
    seen: set[str] = set()
    for p in (
        _fetch_html_search_posts(scanner, home_team, away_team)
        + _fetch_html_posts(scanner)
    ):
        pid = p.get("id") or p.get("permalink") or p.get("url")
        if pid in seen:
            continue
        seen.add(pid)
        merged.append(p)
    posts = merged
```

## Tests

2 new tests added (`tests/test_clip_finder.py`, class `TestFindGoalClipMergeNewListing`):
- Clip only in `/new/`, HTML search has unrelated posts → clip found (Cancelo scenario)
- Same post id in both sources → no duplication/crash

Final suite: **1163 passed**.


---

## 48. Decision: /endirecto Live Match Detail via Reddit + OpenAI Extractor

# Decision: /endirecto Live Match Detail via Reddit + OpenAI Extractor

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — awaiting coordinator live E2E test before commit.

## Problem

`/endirecto` previously showed only the score and status of live matches (from football-data.org).  
The football-data.org free tier (`/matches/{id}`) returns only `score` and `status` for live matches — the `goals`, `bookings`, and `substitutions` arrays are absent. There is no way to obtain minute, scorers, cards or substitutions from the API on this tier.

## Decision

Enrich `/endirecto` with live match detail by:
1. Finding the r/soccer Match Thread for the fixture via `RedditMatchScanner.find_match_thread`.
2. Fetching the thread body via `RedditMatchScanner.get_thread_body`.
3. Passing the trimmed "MATCH EVENTS" section to a new OpenAI extractor (`ai/match_events.py`).
4. Formatting the enriched output with a new formatter (`format_live_match_detail`).
5. Falling back to the existing `format_match` (score-only) when AI is disabled, no thread is found, or any step fails.

## Why Reddit Thread

The r/soccer Match Thread body is updated live by a bot (via ESPN) and contains a structured "MATCH EVENTS" section with goals (⚽), yellow cards (🟨), red cards (🟥) and substitutions (🔄) in a highly parseable format. This is the same data source already used by the goal-polling job — reusing `RedditMatchScanner` (already in the codebase) is consistent and requires no new external dependencies.

## Implementation

### New module: `src/worldcup_bot/ai/match_events.py`
- `_trim_events_region(thread_text)` — anchors on "MATCH EVENTS", truncates at "MATCH STATS", caps at 6000 chars.
- `_parse_events_json(raw)` — strips ``` fences, json.loads, returns `{}` on any failure.
- `_coerce_events(raw)` — normalises parsed dict (string values, drops malformed entries).
- `extract_match_events(ai, thread_text, home_team, away_team) -> dict` — async, temperature=0.0, max_completion_tokens=900. Returns `{"minute": None, "goals": [], "cards": [], "subs": []}` on any error. Never raises.

### Updated formatter: `src/worldcup_bot/bot/formatters.py`
- `format_live_match_detail(match, events, tz_name)` — plain-text block: `🔴 EN DIRECTO · {minute}'`, score line, then optional `⚽ Goles`, `🟨 Tarjetas`, `🔄 Cambios` sections.

### Updated handler: `src/worldcup_bot/bot/handlers.py` — `cmd_en_directo`
- Processes up to 4 live matches (latency cap).
- Enrichment per-match wrapped in `try/except` → fallback to `format_match` on any error.
- Multiple matches joined by `"\n\n———\n\n"`.
- AI disabled (no OpenAI keys) → score-only fallback for all matches.

## Graceful Fallback

All failure modes degrade gracefully to `format_match` (score + status):
- AI not configured (`ai_enabled(settings)` is False).
- No r/soccer match thread found for the fixture.
- Reddit request fails (network, 403, etc.).
- OpenAI call fails (API error, timeout, etc.).
- Malformed/empty JSON response from the AI.
- Any unexpected exception in the enrichment pipeline.

## Tests

42 new tests:
- `tests/test_match_events.py` — 21 tests covering all helpers and `extract_match_events`.
- `tests/test_formatters.py` — 15 new tests in `TestFormatLiveMatchDetail`.
- `tests/test_handlers.py` — 6 new tests in `TestCmdEnDirecto`.

Suite: **1205 passed** (baseline: 1163).




## 49. Decision: /endirecto — Inline Reveal Buttons (header+goles + tarjetas/alineación/cambios on demand)

**Date:** 2026-06-17T21:14:19+02:00
**Author:** Kanté (Backend Developer)
**Status:** IMPLEMENTED

## Context

`/endirecto` previously dumped everything (goals, cards, subs, lineup) inline in one wall of text. David requested a cleaner design: send only the header + goals, with inline buttons to reveal the extra sections on demand.

## Design

### 1. Snapshot store — `src/worldcup_bot/bot/endirecto_store.py`

Persists per-match snapshots to `{state_dir}/endirecto.json` (JSON dict, keyed by 8-hex token). Survives bot restarts. Schema: `{token, match_id, minute, home_name, away_name, home_tla, away_tla, home_score, away_score, goals, cards, subs, lineup, revealed, created}`. All functions best-effort, never raise. Pruned at ~6 h (`max_age_secs=21600`).

### 2. AI extractor extended — `src/worldcup_bot/ai/match_events.py`

- `_MAX_THREAD_CHARS` raised to 8000; `_trim_events_region` now anchors on the EARLIER of "Starting XI" or "MATCH EVENTS" so the LLM sees the lineup section.
- `lineup` field added to JSON schema: current XI per team (starting XI with substitutions applied).
- `_EMPTY_EVENTS` updated to include `"lineup": {"home": [], "away": []}`.
- `max_completion_tokens` raised to 1200.

### 3. Renderer — `render_endirecto` in `src/worldcup_bot/bot/formatters.py`

Returns `(text, keyboard_rows)`. Text built in FIXED order regardless of click order:
1. Header: `🔴 EN DIRECTO [· {minute}']` + score line
2. `⚽ Goles` — ALWAYS shown
3. `🟨 Tarjetas` — only if `"tarjetas"` in `snap["revealed"]`
4. `👥 Alineación actual` — only if `"alineacion"` in `snap["revealed"]`
5. `🔄 Cambios` — only if `"cambios"` in `snap["revealed"]`

Keyboard: one button per non-revealed section (up to 3 in one row). `callback_data = f"ed|{token}|{code}"` (code: t/l/c). All revealed → empty keyboard.

### 4. Handler changes — `src/worldcup_bot/bot/handlers.py`

- `cmd_en_directo`: one message per live match (not joined). AI enabled + thread found → snapshot + buttons. Fallback (AI disabled / no thread / exception) → plain `format_match`.
- New `cmd_endirecto_callback`: parses `"ed|{token}|{code}"`, calls `set_revealed`, edits message. Expired/missing token → alert. Never raises.

### 5. Registration — `src/worldcup_bot/__main__.py`

```python
CallbackQueryHandler(cmd_endirecto_callback, pattern=r"^ed\|")
```

Does NOT collide with existing `^vergol:` pattern.

## Coordinator contract (for live Telegram test)

The coordinator can write a snapshot directly into `{state_dir}/endirecto.json` using the exact schema above, then send a message to a test chat with `InlineKeyboardMarkup` built from 3 buttons (`callback_data="ed|{token}|t"`, `"ed|{token}|l"`, `"ed|{token}|c"`). The running bot handles the callbacks. Field names are the contract — do not rename.

## Tests

43 new tests: store (14), match_events (5 new + 5 updated), formatters (17), handlers (7). Final count: 1248 (from 1205).



## 38. # Decision: Streamff Mirror Fix + Thread-Based Early Goal Detection

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-17
**Status:** IMPLEMENTED — 1267 tests green, not yet committed (coordinator live-tests first).

---

## Fix A — streamff.* all route to cdn.streamff.one/{id}.mp4

### Problem

`download()` in `reddit/downloader.py` only matched `streamff.link` and `streamff.com`. Any
other TLD (`.pro`, `.gg`, `.one`, `.top`, etc.) fell through to yt-dlp, which errors
"Unsupported URL" because yt-dlp does not support streamff front-ends.

Confirmed LIVE: `https://streamff.pro/v/89b5d5c1` returned 200 + 27 MB video/mp4 from
`https://cdn.streamff.one/89b5d5c1.mp4` — the id is the same across ALL mirror front-ends.

### Decision

- `STREAMFF_CDN_ID_RE`: `streamff\.(?:com|link)/v/...` → `streamff\.[a-z]+/v/...` — any TLD.
- Host check in `download()`: explicit `.link`/`.com` OR → `"streamff." in media_url`.
- CDN URL construction unchanged: `https://cdn.streamff.one/{id}.mp4`.

### Invariant

Any `streamff.*/v/{id}` URL produces the same CDN URL regardless of mirror TLD.

---

## Fix B — Thread-based early goal detection with shared dedup state

### Problem

`poll_goals_job` polls football-data.org every 60 s, introducing lag. The r/soccer match
thread posts goals in the MATCH EVENTS section sooner. Previous architecture had no way to
use thread events for notification without risking double-notification when football-data
later confirmed the same score.

### Decision

#### 1. Shared in-memory score state

`build_app()` pre-loads `live_scores.json` into `app.bot_data["live_scores"]` at startup.
Both `poll_goals_job` and `poll_thread_goals_job` read/write this SAME dict. When the thread
job notifies a goal and advances `scores[key]["home"]` to the new value, `poll_goals_job` on
its next tick computes `diff_scores(stored, match)` against the already-updated value and
gets `[]` → no second notification.

`poll_goals_job` uses `setdefault` as a backward-compat safety net (for test isolation and
edge cases where `build_app` didn't run).

#### 2. `_notify_goal` shared helper

Extracted from `_process_goal_delta`'s goal branch:
```
async def _notify_goal(match, new_home, new_away, scoring_team, scorer, minute,
                        settings, context, silent)
```
Sends the HTML goal message AND registers the clip-store entry (same token_key formula:
`f"{match.id}:{scoring_team}:{new_home}-{new_away}"`). Both the football-data path and the
thread path call this helper.

#### 3. `poll_thread_goals_job` (interval=25s, first=25s)

- Calls `client.get_live_matches()` (IN_PLAY/PAUSED only).
- `scanner.scan_live_matches(live_matches)` in `asyncio.to_thread`.
- Matches result to fixture via `(home_tla, away_tla)` lookup.
- Skips unseeded matches (key absent from shared scores) — avoids startup backlog.
- Computes thread score as `max(e.home_score)` / `max(e.away_score)` across all events.
- Only notifies INCREASES strictly above stored score.
- Passes `event.scorer` directly (no OpenAI call — speed win and simpler).
- Sorts pending goals by `minute_sort` before notifying.
- Does NOT handle disallowed goals (leaves those to the football-data poll).
- Per-match `try/except` + whole-job `try/except` — never crashes.

### Dedup guarantee

Thread updates `scores[key]["home/away"]` in-place before returning. On the next
`poll_goals_job` tick, `diff_scores(scores[key], match)` returns `[]` because the stored
value already equals the reported score → no duplicate message.

### Thread scorer advantage

Reddit MATCH EVENTS lines already contain the scorer name (e.g. `Harry Kane 60'`).
`GoalEvent.scorer` is populated by `parse_goal_events`. The thread path passes this directly
to `_notify_goal` — no OpenAI call needed. If `event.scorer` is empty, `None` is passed and
the message still sends (score-only format).

### Files changed

- `src/worldcup_bot/reddit/downloader.py` — Fix A regex + routing
- `src/worldcup_bot/__main__.py` — `_notify_goal` helper, `poll_goals_job` setdefault,
  `poll_thread_goals_job` new job, `build_app` live_scores preload, `main()` job registration
- `tests/test_downloader.py` — 4 new tests
- `tests/test_poll_thread_goals_job.py` — new file, 11 tests
- `tests/test_poll_goals_job.py` — 4 new tests

### Test count

- Baseline: 1248
- Added: 19
- **Total: 1267 passing**

---

## 42. Decision: Persistent finished-match dedup + kickoff-age seed prevents restart re-fires

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-18  
**Status:** IMPLEMENTED — 1297 tests green, not yet committed (coordinator verifies first)

---

## Problem

After a container restart, the "🏁 Final" recap was re-sent for a match that ended hours earlier.

**Root cause — two compounding bugs:**

1. `bot_data["finished_seen"]` was in-memory only → wiped on every restart.
2. The startup seed only included matches whose `status == "FINISHED"` at that moment. football-data.org's status lags: a match that ended hours ago can still show `IN_PLAY` or `PAUSED`. Such a match is not seeded. When football-data eventually flips it to `FINISHED`, the job treats it as newly-finished and sends the recap — for a match that ended long ago.

---

## Decision

### 1. New module: `src/worldcup_bot/reddit/finished_state.py`

Two best-effort helpers that never raise:

```python
load_finished(path: str) -> set[int]   # returns empty set if missing/corrupt
save_finished(path: str, ids: set[int]) -> None  # sorted JSON list
```

### 2. Persistent state in `build_app`

```python
finished_path = f"{settings.state_dir}/finished_announced.json"
app.bot_data["finished_announced"] = load_finished(finished_path)
app.bot_data["finished_seeded"] = False
```

State is loaded from `{state_dir}/finished_announced.json` at startup so announced ids survive restarts.

### 3. Reworked `poll_finished_matches_job`

| Key | Location | Persisted? | Purpose |
|---|---|---|---|
| `bot_data["finished_announced"]` | set | ✅ JSON | Match ids already recapped or seeded as over |
| `bot_data["finished_seeded"]` | bool | ❌ in-memory | First-run gate flag |

**Module-level constant:**
```python
MATCH_OVER_AGE = timedelta(hours=4)
```

**First run** (gate: `not finished_seeded`): seed every match where:
- `m.status == "FINISHED"`, OR
- `now_utc - kickoff > MATCH_OVER_AGE` (4 h)

This seeds both currently-FINISHED matches AND stale IN_PLAY/PAUSED matches whose football-data status hasn't caught up yet. Persist immediately, set flag, return (no sends).

**Subsequent runs:** for each match with `status == "FINISHED"` not in `finished_announced`: send recap (Part A ESPN + Part B porra commentary — unchanged), then `announced.add(id)` + `save_finished(...)` immediately (per-match persist so a crash mid-batch doesn't replay the match).

---

## Why this fixes both bugs

**Bug 1 (restart):** `finished_announced.json` is loaded at startup → ids survive restarts → no re-fire.

**Bug 2 (status lag):** A match that ended 5 h ago but still shows IN_PLAY at startup: its kickoff is >4 h ago → seeded as over → when football-data eventually flips to FINISHED, the id is already in `announced` → no recap.

**Genuinely live match:** Kickoff was 30 min ago → not seeded (kickoff < 4 h) → when it finishes while the bot is running → id not in announced → recap fires exactly once.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/reddit/finished_state.py` | **NEW** — `load_finished`, `save_finished` |
| `src/worldcup_bot/__main__.py` | Import `timedelta`, `load_finished`, `save_finished`; add `MATCH_OVER_AGE`; update `build_app`; rework `poll_finished_matches_job` |
| `tests/test_poll_finished_job.py` | Update all `finished_seen` refs to `finished_announced`/`finished_seeded`; add 14 new tests |

**Test count: 1297 (up from 1283)**

---

# Decision: BELOVED_TEAMS env-configurable + Curaçao (CUW)

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-18
**Status:** IMPLEMENTED — 1329 tests green, not yet committed (coordinator verifies first)

---

## Problem

David wanted to add Curaçao 🇨🇼 to the bot's beloved teams AND make the full list
configurable at runtime via an environment variable, without importing `config` into
the pure `formatters.py` module.

---

## Decision

### BELOVED_TEAMS now env-configurable

```
BELOVED_TEAMS=PAN,UZB,CUW   # default; override via env at startup
```

`config.py` gains:
- `_parse_tla_list(raw)` helper: split on comma, strip, uppercase, drop empties → `tuple[str, ...]`
- `Settings.beloved_teams: tuple[str, ...] = ("PAN", "UZB", "CUW")`
- `load_settings()` reads `os.getenv("BELOVED_TEAMS", "PAN,UZB,CUW")` through the parser

### formatters.py: configurable default + setter

```python
# src/worldcup_bot/bot/formatters.py
BELOVED_TEAMS: set[str] = {"PAN", "UZB", "CUW"}   # works even before setter runs
_LOVE = "❤️"

def set_beloved_teams(tlas) -> None:
    global BELOVED_TEAMS
    BELOVED_TEAMS = {t.strip().upper() for t in tlas if t and t.strip()}
```

`team_flag` is unchanged (still checks module global). The module stays **pure**
(no `config` import) — the coupling is one-way: `__main__` pushes the list into
`formatters` at startup.

### __main__.py: apply at startup

```python
def build_app(settings: Settings) -> Application:
    from worldcup_bot.bot import formatters
    formatters.set_beloved_teams(settings.beloved_teams)
    ...
```

Called once before any handler or job runs, so all renderers see the configured list.

### daily_update.py: Curaçao added

Updated "cariño especial" instruction in `_SYSTEM`:

> "Cariño especial: Panamá 🇵🇦, Uzbekistán 🇺🇿 y Curaçao 🇨🇼 son las selecciones
> favoritas de esta porra. Siempre que las menciones, muéstrales un poco de amor y
> ánimo (con naturalidad, sin pasarte ni romper el formato): un emoji de corazón,
> una palabra de apoyo o un guiño cariñoso."

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/config.py` | `_parse_tla_list` helper + `beloved_teams` field + `load_settings` parse |
| `src/worldcup_bot/bot/formatters.py` | Default includes CUW; `set_beloved_teams` setter added |
| `src/worldcup_bot/__main__.py` | `build_app` calls `formatters.set_beloved_teams(settings.beloved_teams)` |
| `src/worldcup_bot/ai/daily_update.py` | "cariño especial" line extended to name Curaçao |
| `tests/test_config.py` | 6 new tests (default + env parse + trim + empties) |
| `tests/test_formatters.py` | CUW tests + `TestSetBelovedTeams` (5 tests) |
| `tests/test_ai.py` | 2 new tests (Curaçao mention + all-three check) |
| `tests/test_handlers.py` | 1 new test (spy on `set_beloved_teams` called from `build_app`) |

---

## Key facts

- Curaçao football-data TLA: **CUW** (ISO CW → 🇨🇼). "CUR" maps to nothing.
- Default beloved set: `{"PAN", "UZB", "CUW"}`.
- `formatters.py` remains pure — never imports `api/` or `porra/` or `config/`.
- `set_beloved_teams` is test-isolation-safe: tests teardown by restoring the default.
- Test count: 1313 → **1329** (+16 tests).

---

# Decision: BELOVED_TEAMS Env Var — Configurable Favourite Teams

**Requested by:** David (@DrDonoso)  
**Assigned to:** Maldini (DevOps)  
**Date:** 2026-06-18T13:04:17Z  
**Status:** ✅ Resolved

---

## Context

The bot displays a ❤️ next to favourite teams' flags in all outputs (standings, match previews, daily updates). The list was hardcoded in code; it is now configurable via the `BELOVED_TEAMS` environment variable (comma-separated football-data TLAs).

---

## Changes

### 1. `docker-compose.yml` (Production)
Added to `worldcup-bot` service `environment:` block (right after `RICH_IMAGE_HOUR`):
```yaml
# --- Selecciones 'favoritas' (❤️ junto a la bandera) — TLAs separadas por comas ---
BELOVED_TEAMS: "${BELOVED_TEAMS:-PAN,UZB,CUW}"
```

### 2. `docker-compose.local.yml` (Local Development)
Added to `worldcup-bot` service `environment:` block (same position for consistency):
```yaml
# --- Selecciones 'favoritas' (❤️ junto a la bandera) — TLAs separadas por comas ---
BELOVED_TEAMS: "${BELOVED_TEAMS:-PAN,UZB,CUW}"
```

### 3. `.env.example`
Added:
```bash
# Optional — Beloved teams (comma-separated football-data TLAs).
# The bot displays a ❤️ next to these teams' flags in all outputs (standings, match previews, etc).
# Default: Panamá (PAN), Uzbekistán (UZB), Curaçao (CUW).
# BELOVED_TEAMS=PAN,UZB,CUW
```

---

## Validation

Both compose files validated successfully:
- `docker compose -f docker-compose.yml config -q` → **exit 0** ✓
- `docker compose -f docker-compose.local.yml config -q` → **exit 0** ✓

---

## Next Steps

**Kanté** (Code owner) to:
1. Update `config.py` to read `BELOVED_TEAMS` from environment with safe CSV parsing.
2. Default to `"PAN,UZB,CUW"` (Panamá, Uzbekistán, Curaçao).
3. Consume the parsed list in `formatters.py::team_flag()` to render ❤️ suffix.

---

## Notes

- **Style consistency:** Variable naming, env-var wiring, and `.env.example` comment format mirror existing patterns (e.g., `OPENAI_IMAGE_MODEL`, `RICH_IMAGE_HOUR`).
- **No code changes:** This decision is **DevOps-only**; no `src/**` or `config.py` modifications.
- **Defaults:** The three default favourite teams (Panamá, Uzbekistán, Curaçao) reflect the bot's origin and heart. Users can override via `BELOVED_TEAMS=ARG,BRA,URU` (or any comma-separated TLA list) when deploying.

