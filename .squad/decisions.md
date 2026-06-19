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



# Decision: Add Czech Republic → Czechia team alias

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-18
**Status:** IMPLEMENTED — 1336 tests green, not yet committed (coordinator verifies first)

---

## Problem

The "Ver gol" button never appeared for Czechia's goal (Michal Sadílek, 6') vs South Africa.
The r/soccer clip post existed with title `"Czech Republic [1] - 0 South Africa - M. Sadílek 6'"` and URL `https://streamin.link/v/9801698f`, but `find_goal_clip` returned `None`.

Root cause: `_teams_match("Czech Republic", "Czechia")` was `False`.
`WC_TEAM_ALIASES` had no Czech Republic↔Czechia entry.
football-data.org uses `"Czechia"` as the canonical name; r/soccer and ESPN clip titles use `"Czech Republic"`.

---

## Decision

Added to `WC_TEAM_ALIASES` in `src/worldcup_bot/reddit/scanner.py`:

```python
"czech republic": "czechia",
"czech rep": "czechia",   # covers "Czech Rep" and "Czech Rep." (dot stripped before lookup)
```

`_normalize_team` lowercases, strips accents, replaces `.` with space, then looks up the alias map.
After normalization: `"Czech Republic"` → `"czech republic"` → `"czechia"`;
`"Czechia"` → `"czechia"` (not in map, stays as-is). Both canonicalize to `"czechia"` → `_teams_match` returns `True`.

Same pattern as the earlier D.R. Congo↔Congo DR fix.

---

## Tests added

- `TestCzechiaAlias` (5 tests) in `tests/test_reddit_scanner.py`:
  - `_normalize_team("Czech Republic") == _normalize_team("Czechia")`
  - `_normalize_team("Czech Rep.") == _normalize_team("Czechia")`
  - `_teams_match("Czech Republic", "Czechia")` is True (both orders)
  - `_teams_match("Czech Rep.", "Czechia")` is True
- `TestMatchPost.test_czech_republic_clip_title_matches_czechia_fixture` in `tests/test_clip_finder.py`
- `TestFindGoalClip.test_czechia_czech_republic_clip_title_integration` in `tests/test_clip_finder.py` (exact live clip title + streamin.link URL)

**Total tests: 1336 (was 1329 before this session's start; +7 new tests)**


# Decision: /endirecto 429 fix — shared scanner + TTL cache + find_thread_permalink

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-18
**Status:** IMPLEMENTED — 1357 tests green, not yet committed (coordinator verifies first)

---

## Problem

`/endirecto` showed NO inline keyboard in production.

Root cause (verified live):
- `cmd_en_directo` created a **fresh** `RedditMatchScanner` on every call → hit Reddit with
  a cold session (no cache).
- `find_match_thread` calls `old.reddit.com/r/soccer/search` → Reddit returned **HTTP 429
  Too Many Requests** → returned `None` → handler fell back to plain `format_match`
  (score only, no inline keyboard).
- The goal-poller job (25s), clip-finder job, and on-demand `/endirecto` all created
  **independent** scanner instances, each hitting Reddit separately → rate limit breached.

---

## Decision

### 1. TTL in-memory cache on `RedditMatchScanner` (scanner.py)

Added module-level constants:
```python
_MATCH_THREADS_TTL = 30   # seconds
_THREAD_BODY_TTL   = 90   # seconds per permalink
```

Per-instance cache fields (`_match_threads_cache`, `_thread_body_cache`):
- `get_match_threads()` returns cached list if age < 30s; on 429/error returns stale cache
  if available, else `[]`. **Never raises.**
- `get_thread_body(permalink)` returns cached body if age < 90s per-permalink; on 429/error
  returns stale cache if available, else `""`. **Never raises.**

### 2. New method `find_thread_permalink(home_name, away_name) → str | None`

Scans the *cached* `get_match_threads()` result using `_parse_thread_teams` + `_teams_match`
(both orderings accepted). Uses the reliable `/new/` listing instead of the 429-prone
`/search` endpoint. Returns the first matching thread's permalink, or `None`.

### 3. `cmd_en_directo` — reuse shared scanner + new lookup order (handlers.py)

Before (broken):
```python
scanner = RedditMatchScanner(user_agent=settings.reddit_user_agent)  # fresh each call
permalink = await asyncio.to_thread(scanner.find_match_thread, ...)  # hits /search → 429
```

After (fixed):
```python
scanner = context.bot_data.get("reddit_scanner")
if scanner is None:
    scanner = RedditMatchScanner(user_agent=settings.reddit_user_agent)
    context.bot_data["reddit_scanner"] = scanner

permalink = await asyncio.to_thread(scanner.find_thread_permalink, ...)  # cached /new/
if permalink is None:
    permalink = await asyncio.to_thread(scanner.find_match_thread, ...)  # search fallback
```

Net effect: when the 25s goal poller has recently fetched threads/bodies, `/endirecto`
reuses the cache → no new Reddit hit → no 429 → inline keyboard shown.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/reddit/scanner.py` | `import time`; TTL constants; cache fields in `__init__`; wrap `get_match_threads`/`get_thread_body` with cache+error handling; add `find_thread_permalink` |
| `src/worldcup_bot/bot/handlers.py` | `cmd_en_directo`: lazy-init shared scanner; use `find_thread_permalink` first, then `find_match_thread` fallback |
| `tests/test_reddit_scanner.py` | Add `TestFindThreadPermalink` (6), `TestScannerMatchThreadsCache` (4), `TestScannerThreadBodyCache` (5) |
| `tests/test_handlers.py` | Update 2 existing tests; add `TestCmdEnDirectoSharedScanner` (6 tests) |

---

## Why this is safe

- All existing scanner tests still pass — each creates a fresh instance with a cold cache,
  so caching is transparent to them.
- `scan_live_matches` has a try/except around `get_match_threads()` that is now dead code
  but harmless.
- `find_thread_permalink` is purely additive; it delegates to the already-tested
  `get_match_threads` + `_parse_thread_teams` + `_teams_match`.
- The `find_match_thread` (search) fallback is preserved for matches not yet in the /new/ listing.
- Stale-cache-on-error ensures the bot degrades gracefully even under sustained 429 pressure.

---

# Decision: daily-update _SYSTEM now requires full participant names

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-19
**Status:** IMPLEMENTED — 1358 tests green, not yet committed (coordinator verifies first)

---

## Problem

In the AI daily update, participants were only bolded when their **full** `display_name` appeared in the AI-generated `standings_comment`. The AI was shortening names to first-name only ("Miquel", "Cristina", "Patri"), which never matched the full names in `participant_names`, so `bold_person_names()` silently left those mentions unbolded.

Root cause: the _SYSTEM prompt had no explicit instruction to use full names. The AI naturally defaults to first names in conversational prose.

---

## Decision

### 1. Strengthen `_SYSTEM` in `src/worldcup_bot/ai/daily_update.py`

Added within the `standings_comment` rule block (after scenario descriptions, before the JSON format line):

```
IMPORTANTE — nombres de participantes: cuando menciones a un participante de la porra,
escribe SIEMPRE su nombre COMPLETO (nombre y apellidos) EXACTAMENTE como aparece en la
clasificación que te paso (por ejemplo 'Miquel Apellido', nunca solo 'Miquel').
No uses solo el nombre de pila, no abrevies y no inventes apellidos: copia el nombre tal cual aparece.
```

### 2. Optional inline reminder in `build_ai_user_message`

The ranking block now ends with:
```
(usa el nombre completo tal cual al mencionarlos)
```
This secondary reinforcement appears in the user message itself, immediately after the ranking list where full names are already visible.

### 3. No changes to rendering pipeline

`render_message`, `bold_person_names`, and the data plumbing in `generate_daily_update` are untouched — they already pass correct full `display_name` values.

---

## Why bolding was broken

`bold_person_names(text, names)` does exact-substring matching against `participant_names = [r.display_name for r in ranking]`. If the AI writes "Miquel" instead of "Miquel Apellido", the regex `\bMiquel Apellido\b` never matches, so no `<b>` tag is injected.

The fix is entirely on the prompt side: force the AI to copy names verbatim from the classification it receives.

---

## Tests

- Added `test_system_prompt_requires_full_participant_names` to `TestSystemPromptContract` in `tests/test_ai.py`.
- All 1358 tests green (1357 baseline + 1 new).


# Decision: /tongo Templated Phrases from TongoPhrases.txt

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-19
**Status:** IMPLEMENTED — 1408 tests green

---

## Problem

`/tongo` had all phrases hardcoded in `src/worldcup_bot/data/tongo.py`. There was no way to add
or edit phrases without rebuilding the Docker image. The user also wanted phrases that could
target a specific person when `/tongo` is sent as a reply to their message.

---

## Decision

### File format

- File: `data/TongoPhrases.txt` (committed; mounted read-only at `/app/data`)
- Plain UTF-8, one phrase per line
- Lines starting with `#` are comments (ignored); blank lines are ignored
- Hot-reloaded on mtime change — no restart needed
- Missing file / empty result / OSError → fall back to built-in `FRASES` silently
- Optional env var `TONGO_PHRASES_PATH` overrides the default path

### Template variables (10 total)

Sender (always available):
- `{{first_name}}`, `{{last_name}}`, `{{full_name}}`, `{{username}}`, `{{id}}`

Reply target (only when user replied to a message):
- `{{reply_to_first_name}}`, `{{reply_to_last_name}}`, `{{reply_to_full_name}}`, `{{reply_to_username}}`, `{{reply_to_id}}`

Whitespace-tolerant: `{{ first_name }}` works the same as `{{first_name}}`.
Unknown placeholders → `""`. Missing/None values → `""`.

### Explicit exclusions (per user request)

- NO `{{display_name}}` or `{{mention}}` variables
- NO cross-reference with `predictions.yml`

### Reply-targeting behavior

If the phrase uses any `{{reply_to_*}}` variable AND the user sent `/tongo` as a reply to
another message → **reply path**: pool = rendered reply phrases + gifs. No SANCHEZ check.

If the user did NOT reply, or the phrase file has no reply phrases → **default path**:
`random.random() < 1/3` → "Sanchez ens roba" (invariant preserved), otherwise
pool = rendered sender phrases + `frase_argentino(gender)` + gifs.

`is_bot` check skipped: reply vars are populated even when the replied-to user is a bot
(user explicitly tested `/tongo` replying to the bot as a wanted use case).

### Files changed

| File | Change |
|---|---|
| `data/TongoPhrases.txt` | NEW — 16 seeded phrases + header comment listing all 10 variables |
| `src/worldcup_bot/data/tongo.py` | Added `load_tongo_phrases`, `TongoContext`, `build_tongo_context`, `render_tongo`, `phrase_uses_reply`, `phrase_eligible` |
| `src/worldcup_bot/config.py` | Added `tongo_phrases_path: str = ""` + `TONGO_PHRASES_PATH` env var |
| `src/worldcup_bot/bot/handlers.py` | Rewrote `cmd_tongo` with reply-targeted and default paths |
| `tests/test_tongo_phrases.py` | NEW — 50 tests (loader, render, context, eligibility, handler paths) |
| `README.md` | Added TongoPhrases.txt section with variable table and reply-targeting explanation |

### Why this is safe

- Built-in `FRASES` fallback means out-of-the-box behavior is unchanged if file is absent.
- SANCHEZ 1/3 invariant is strictly preserved on the default (no-reply) path.
- All 16 seed phrases in `TongoPhrases.txt` are plain strings with no template vars — identical to the previous hardcoded behavior.
- `isinstance(val, str)` guard in `_extract_user_fields` makes context extraction safe against both real PTB User objects and MagicMock attributes in tests.
- 1408 tests green (1357 before).


# Design Proposal: Per-User `/tongo` Configuration

**Author:** Pirlo (Tech Lead)  
**Date:** 2026-06-19  
**Status:** PROPOSAL — awaiting DrDonoso confirmation

---

## Problem Statement

DrDonoso wants `/tongo` behavior to vary per user:
- **User X scenario:** Override SANCHEZ probability (e.g., 2/3 instead of 1/3).
- **User Y scenario:** Pull from a completely different phrase pool (skip/alter SANCHEZ behavior).

Current behavior: global 1/3 SANCHEZ probability, single shared phrase pool for all users.

---

## 1. Where Per-User Config Lives — Options Evaluated

### Option A: Extend `predictions.yml` with `tongo:` block
```yaml
participants:
  drdonoso:
    display_name: "David"
    groups: {...}
    knockout: {...}
    tongo:  # NEW optional block
      sanchez_ratio: 0.66
      phrases_mode: replace
      phrases:
        - "Custom phrase for David {{first_name}}"
```

| Pro | Con |
|-----|-----|
| Single source of truth (already keyed by username) | Couples porra data with easter-egg config |
| Already hot-reloads | `predictions.yml` is git-ignored — no version control for tongo config |
| No new file/env needed | Validation complexity increases |

### Option B: Dedicated `data/TongoUsers.yml` (RECOMMENDED)
```yaml
# data/TongoUsers.yml
drdonoso:
  sanchez_ratio: 0.66
  phrases_mode: append
  phrases:
    - "Otra queja de David..."

raona:
  sanchez_ratio: 0.0
  phrases_mode: replace
  phrases_file: "tongo/raona.txt"  # OR inline phrases
```

| Pro | Con |
|-----|-----|
| Separation of concerns — tongo config is independent of porra | One more file to manage |
| Can be committed (version-controlled) or git-ignored (operator choice) | New loader + hot-reload (minor, pattern exists) |
| Clean validation — fails independently of predictions | — |
| `data/` already mounted — no infra change | — |

### Option C: In-band syntax in `TongoPhrases.txt`
```
# default section
Per robos el de Javi a Raona.
...

[user:drdonoso ratio=0.66]
Frase exclusiva para David.

[user:raona ratio=0 mode=replace]
Frase solo para Raona.
```

| Pro | Con |
|-----|-----|
| Single file | Messy parsing; error-prone |
| — | Hard to read/maintain for humans |
| — | Breaks current "one phrase per line" simplicity |

### ✅ Recommendation: **Option B** — `data/TongoUsers.yml`

Cleanest separation, familiar YAML, operator can decide commit vs git-ignore. Pattern mirrors `predictions.yml` loader.

---

## 2. Identification & Fallback

- **Key by `username.lower()`** — consistent with `predictions.py` (`get_participant` already does this).
- **No username?** → Fall back to default global behavior. (Some Telegram users have no @username — ~5% edge case.)
- **Match by `id`?** Not recommended for v1. Adds complexity, operator can't easily configure (they know usernames, not numeric IDs). Revisit only if real need arises.

---

## 3. Semantics — Recommended Defaults

| Setting | Type | Default | Meaning |
|---------|------|---------|---------|
| `sanchez_ratio` | float 0..1 | (absent = global 1/3) | Probability of SANCHEZ_ENS_ROBA on non-reply path. `0.0` = never, `1.0` = always. |
| `phrases_mode` | `append` \| `replace` | `append` | `append` = user phrases + global pool; `replace` = ONLY user phrases. |
| `phrases` | list[str] | `[]` | Inline phrases (templating applies). |
| `phrases_file` | str (path relative to `data/`) | `null` | Alternative: load from `data/{path}`. Mutually exclusive with inline `phrases`. |

**Edge-case behaviors:**
- If `phrases_mode: replace` and user has 0 phrases → fall back to global pool (fail-safe).
- Per-user phrases still support `{{...}}` templating.
- GIFs stay global (simplest; no ask for per-user GIFs).
- Reply-targeted path unchanged — per-user config only affects the non-reply path's SANCHEZ ratio and phrase pool. (If user X replies to a message, reply phrases still work as today.)

**Case X (e.g., 2/3 SANCHEZ):**
```yaml
userx:
  sanchez_ratio: 0.66
```
Everything else defaults — phrases from global pool.

**Case Y (dedicated pool, no SANCHEZ):**
```yaml
usery:
  sanchez_ratio: 0.0
  phrases_mode: replace
  phrases:
    - "Frase especial 1 para Y"
    - "Frase especial 2 para Y"
```

---

## 4. Backward Compatibility

- **Unconfigured users** must get **exact current behavior**: 1/3 SANCHEZ, global TongoPhrases.txt pool, reply-targeted path.
- The global `"SANCHEZ 1/3"` invariant test must pass for any user NOT in `TongoUsers.yml`.
- If `TongoUsers.yml` is missing entirely → all users get global behavior (no error).

---

## 5. Module Boundaries

### Extract pure selection logic
Move the random selection into a **pure, unit-testable function** in `data/tongo.py`:

```python
def choose_tongo_response(
    username: str | None,
    ctx: TongoContext,
    user_cfg: TongoUserConfig | None,  # from loader
    global_phrases: list[str],
    gifs: list[Path],
    gender: str,
    rng: random.Random = random,  # injectable for tests
) -> str | Path:
    """Return the selected tongo response (rendered phrase or GIF path)."""
```

- **`cmd_tongo` becomes thin**: build context, load configs, call `choose_tongo_response`, send result.
- **Pure function** = trivial to unit-test all edge cases (user with custom ratio, user with replace mode, unconfigured user, no-username user).

### New types
```python
@dataclass
class TongoUserConfig:
    sanchez_ratio: float | None  # None = use global
    phrases_mode: Literal["append", "replace"]
    phrases: list[str]  # already rendered? No — raw, render at call time.
```

### Hot-reload
`load_tongo_users(path: str) -> dict[str, TongoUserConfig]` — mtime-based, same pattern as `load_tongo_phrases` and `predictions.load`.

---

## 6. Implementation Sequence

| Phase | Who | What |
|-------|-----|------|
| 1. Loader | Kanté | `load_tongo_users(path)` in `data/tongo.py` — mtime hot-reload, returns `dict[str, TongoUserConfig]`. |
| 2. Pure selector | Kanté | `choose_tongo_response(...)` — all logic extracted from `cmd_tongo`. |
| 3. Wire handler | Kanté | Slim `cmd_tongo` calls loader + selector. Add `TONGO_USERS_PATH` env var (default `data/TongoUsers.yml`). |
| 4. Tests | Kanté | Unit tests for loader + selector; parametrize: unconfigured, ratio override, replace mode, edge cases. |
| 5. Config (opt.) | Maldini | Only if new env var needs documenting in `docker-compose.yml` or README — minor. |

**Out of scope for v1:**
- Per-user GIFs.
- Per-user reply-targeted phrase pools.
- Matching by Telegram numeric ID.

---

## 7. Open Decisions for DrDonoso

Before Kanté implements, please confirm:

1. **File location & versioning:** `data/TongoUsers.yml` committed (version-controlled) or git-ignored (runtime-only like `predictions.yml`)? I recommend **committed** so you can track changes, but your call.

2. **Inline phrases vs. per-user file:** Support both `phrases: [...]` inline AND `phrases_file: "tongo/raona.txt"`, or only one? I recommend **both** — inline for short lists, file for long lists.

3. **Default phrases_mode:** `append` (merge with global) or `replace` (only user's phrases)? I recommend **`append`** as default.

Once confirmed, Kanté can start immediately — this is a ~2-3 hour implementation with tests.

---

**End of proposal.**


# Decision: Per-User /tongo Config (TongoUsers.yml)

**Author:** Kanté  
**Date:** 2026-06-19T09:41:34Z  
**Status:** Implemented  

---

## Summary

Implemented per-user `/tongo` configuration via a committed `data/TongoUsers.yml` file. Each participant can now have an overridden Sanchez probability and/or their own phrase pool, while all unconfigured users keep exactly the original behavior.

---

## Problem

- DrDonoso wanted two use cases:
  1. **Person X:** a higher Sanchez probability (e.g. 2/3 instead of 1/3).
  2. **Person Y:** their own phrase list (replacing or appending to the global pool), optionally with no Sanchez at all.
- Pirlo's approved design: `data/TongoUsers.yml`, keyed by lowercased Telegram username, `phrases_mode: append` default, support both inline `phrases` and `phrases_file`.

---

## Design Decisions

### Config file committed and empty by default

`data/TongoUsers.yml` is committed (not git-ignored) and ships with all example entries commented out. `yaml.safe_load` returns `{}` for a comment-only file → zero behavioral change on first deploy. This mirrors the `TongoPhrases.txt` pattern.

### `TongoUserConfig` dataclass in `tongo.py`

Kept in the same module as `TongoContext` for cohesion. Fields match the YAML schema exactly, all optional.

### `load_tongo_users`: mtime hot-reload, graceful degradation

Mirrors the `predictions.py` / `load_tongo_phrases` cache pattern:
- Module-level `_cached_users_path`, `_cached_users_mtime`, `_cached_users_data`
- Returns `{}` (not raises) on any error: missing file, YAML parse error, OSError
- Per-field validation: invalid value → log warning + skip that field (never skip the whole entry)

### `read_tongo_phrase_file`: path-keyed dict cache

The existing `load_tongo_phrases` uses a single-path module-level cache. Reusing it for per-user files would thrash (cache invalidated on every alternating path). Solution: `_phrase_file_cache: dict[str, tuple[float, list[str]]]` — each path gets its own mtime entry. Files are tiny and `/tongo` is low-frequency, so memory is negligible.

### `choose_tongo_response`: pure, injectable rng

Extracted the reply-path / SANCHEZ-gate / sender-pool logic into a pure function with `rng` as a keyword argument (defaulting to the `random` module). The handler passes `rng=random` explicitly so existing tests that patch `worldcup_bot.bot.handlers.random` still control the selection without modification. New unit tests pass a `_FakeRNG` instance directly.

### Effective phrases composition

```
per_user_phrases = user_cfg.phrases + read_tongo_phrase_file(phrases_file_abs)
if mode == "replace" AND per_user_phrases non-empty:
    effective = per_user_phrases
else:
    effective = global_phrases + per_user_phrases  # covers append + replace-empty guard
```

The "replace + empty" fallback to global prevents an empty pool (would crash `random.choice`).

### GIF error fallback

Computed inside the `except` block (not before the `try`) to avoid consuming a mock `side_effect` slot in tests that don't trigger the error path. Uses `global_phrases` (non-reply phrases rendered) or `FRASES` — never per-user phrases — to guarantee a safe fallback regardless of user config.

---

## Files Changed

| File | Change |
|---|---|
| `data/TongoUsers.yml` | **NEW** — committed, comment-only (loads to `{}`) |
| `src/worldcup_bot/data/tongo.py` | Added: `import random`, `from pathlib import Path`, `import yaml`; `TongoUserConfig` dataclass; `load_tongo_users`; `_phrase_file_cache` + `read_tongo_phrase_file`; `choose_tongo_response` |
| `src/worldcup_bot/config.py` | Added `tongo_users_path: str = ""` field + `TONGO_USERS_PATH` env var in `load_settings()` |
| `src/worldcup_bot/bot/handlers.py` | Updated imports (removed unused `SANCHEZ_ENS_ROBA`, `frase_argentino`, `phrase_eligible`; added `choose_tongo_response`, `load_tongo_users`, `read_tongo_phrase_file`); rewrote `cmd_tongo` |
| `tests/test_tongo_users.py` | **NEW** — 55 tests |
| `README.md` | Added per-user config section |
| `.squad/agents/kante/history.md` | Appended session record |

---

## Test Count

- Baseline: 1408
- After: **1463** (+55)
- All existing tests green — unconfigured-user SANCHEZ 1/3 invariant preserved.


# Decision: Wire TONGO_USERS_PATH Environment Variable

**Date:** 2026-06-19  
**Agent:** Maldini (DevOps)  
**Scope:** Infrastructure (environment variables, docker-compose files)

## Context

Kanté is adding a new per-user `/tongo` configuration file (`data/TongoUsers.yml`) that will store per-user settings (sanchez_ratio + custom phrases). For consistency with existing env-var patterns (`PREDICTIONS_PATH`, `TONGO_PHRASES_PATH`), we need to wire an optional env var to allow the file path to be overridden at runtime.

## Changes Made

1. **docker-compose.yml** (prod)
   - Added `TONGO_USERS_PATH: "${TONGO_USERS_PATH:-/app/data/TongoUsers.yml}"` to the `environment:` block.
   - Placed immediately after `TONGO_PHRASES_PATH` block.
   - Comment: `# --- Config por persona de /tongo (fichero montado en data/, hot-reload) ---`

2. **docker-compose.local.yml** (dev)
   - Identical entry to prod.
   - Ensures parity between local and production environments.

3. **.env.example**
   - Added commented documentation line: `# TONGO_USERS_PATH=/app/data/TongoUsers.yml   # config por persona de /tongo (sanchez_ratio + frases propias; default: data/TongoUsers.yml)`
   - Placed immediately after `TONGO_PHRASES_PATH` line.
   - Describes the file purpose and documents the default path.

## Validation

- **No new volumes needed:** The `data/` directory is already mounted read-only at `/app/data:ro` in both compose files.
- **Gitignore check:** Verified that `data/TongoUsers.yml` is **not ignored** by `.gitignore` (exit code 1 from `git check-ignore`), so the file is committable.
- **Parity:** Matches the env-var convention used for `PREDICTIONS_PATH` and `TONGO_PHRASES_PATH`:
  - Form: `${VAR_NAME:-/app/data/filename}`
  - Both compose files use identical entries.
  - `.env.example` documents the optional nature and default.
- **No code/test changes:** Dockerfile remains untouched; Kanté owns the application config logic in `config.py`.

## Why This Matters

- **Consistency:** Users (and Kanté's code) can now customize the path to `data/TongoUsers.yml` the same way they customize `predictions.yml` and `TongoPhrases.txt`.
- **Hot-reload:** File is mounted read-only, supporting hot-reload workflows without container rebuild.
- **Same image everywhere:** Prod and local use the same image; only env vars differ, maintaining the "single image" contract.

## Next Steps

- Kanté adds logic to `config.py` to read `TONGO_USERS_PATH` and load the file (defaulting to `/app/data/TongoUsers.yml` if unset).
- File `data/TongoUsers.yml` can be committed to the repository.
