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

---

# Decision: Merge /tongo into a single YAML file

**Date:** 2026-06-19  
**Agent:** Kanté (Backend Developer)  
**Requested by:** DrDonoso  
**Status:** Implemented

---

## Summary

Merged the two-file `/tongo` configuration (`data/TongoPhrases.txt` + `data/TongoUsers.yml`) into a single YAML file (`data/TongoUsers.yml`) with a `phrases:` global pool and a `users:` per-user overrides map.

## Problem

Two separate files created unnecessary friction:
- `TongoPhrases.txt` was a plain-text format that couldn't be edited alongside `TongoUsers.yml`.
- `phrases_file` per-user feature added a third type of file reference.
- The config/settings had two separate path env vars (`TONGO_PHRASES_PATH`, `TONGO_USERS_PATH`).

## Decision

One file, one schema:

```yaml
phrases:            # Global phrase pool (replaces TongoPhrases.txt)
  - "..."

users:              # Per-user overrides (keyed by @username lowercase)
  nombredeusuario:
    sanchez_ratio: 0.66
    phrases_mode: append   # or "replace"
    phrases:
      - "{{first_name}}, ..."
```

## Changes

**`src/worldcup_bot/data/tongo.py`**
- Removed: `load_tongo_phrases`, `read_tongo_phrase_file`, their module-level caches, and the `phrases_file` field on `TongoUserConfig`.
- Added: `TongoConfig` dataclass (`phrases: list[str]`, `users: dict[str, TongoUserConfig]`).
- Added: `load_tongo_config(path)` — single-file YAML loader with mtime hot-reload, mirrors `porra/predictions.py` cache pattern.

**`src/worldcup_bot/config.py`**
- Removed `tongo_phrases_path` field and `TONGO_PHRASES_PATH` env var.
- `tongo_users_path` / `TONGO_USERS_PATH` now points to the merged file.

**`src/worldcup_bot/bot/handlers.py`**
- `cmd_tongo` resolves a single path, calls `load_tongo_config`, derives `global_phrases` and `users` from the result. No `phrases_file` resolution.

**Data files**
- `data/TongoUsers.template.yml` — committed template (Spanish comments, 16 default phrases, 2 commented fake user examples).
- `data/predictions.template.yml` — committed template for `predictions.yml` (2 fake users, fake TLAs).
- `data/TongoUsers.yml` — git-ignored runtime file, pre-populated with 22 phrases migrated from `TongoPhrases.txt` and 12 participant keys as commented blocks.

**Tests**
- Removed: `TestLoadTongoPhrases` (9), `TestReadTongoPhraseFile` (6), `test_phrases_file_resolved_relative_to_yaml_dir` (1).
- Added: `TestLoadTongoConfig` (26 tests) covering merged schema validation, hot-reload, graceful degradation.
- All integration tests updated to use merged YAML.
- Final count: **1452 tests, all passing**.

## Notes for Maldini

- `data/TongoUsers.yml` must be added to `.gitignore` (already ignored by `data/*.yml` pattern if present, otherwise add it explicitly).
- `data/TongoPhrases.txt` can be removed from git tracking (data is now in `TongoUsers.yml`).
- `data/TongoUsers.template.yml` and `data/predictions.template.yml` must be tracked.
- No changes required to `docker-compose.yml`, `.env.example`, or any CI config (the `TONGO_USERS_PATH` env var is unchanged).

---

# Decision: /tongo YAML Merge — Infrastructure Consolidation

**Date:** 2026-06-19  
**Owner:** Maldini (DevOps)  
**Context:** Kanté consolidated `/tongo` customizable phrases from two files (`data/TongoPhrases.txt` + `data/TongoUsers.yml`) into one merged runtime file (`data/TongoUsers.yml` with `phrases:` + `users:` sections). Two committed templates now guide users on setup.

## Changes Made

### 1. `.gitignore`
- **Added:** `data/TongoUsers.yml` runtime-file ignore rule with comment "Runtime /tongo config (merged phrases + per-user settings) — git-ignored; generated from template".
- **Placement:** Right after the existing `data/predictions.yml` ignore rule (both are runtime outputs, not committed).
- **Templates safe:** Pattern `data/TongoUsers.yml` does not match committed templates `data/TongoUsers.template.yml` or `data/predictions.template.yml`. No negation exceptions needed.

### 2. `docker-compose.yml` (prod)
- **Removed:** `TONGO_PHRASES_PATH` env-var block (2-line comment + variable line). Rationale: single merged file eliminates the need for a separate phrases path.
- **Updated:** `TONGO_USERS_PATH` Spanish comment changed from "Config por persona de /tongo..." to "Config de /tongo: frases globales + overrides por persona (data/TongoUsers.yml, hot-reload)---" to reflect the merged structure.
- **Kept:** The `TONGO_USERS_PATH` variable itself (no change to the binding).

### 3. `docker-compose.local.yml` (dev)
- **Removed:** `TONGO_PHRASES_PATH` env-var block (identical to prod).
- **Updated:** `TONGO_USERS_PATH` comment (identical to prod).
- **Kept:** The `TONGO_USERS_PATH` variable itself.

### 4. `.env.example`
- **Removed:** The commented example `# TONGO_PHRASES_PATH=/app/data/TongoPhrases.txt...` line.
- **Updated:** The commented example `# TONGO_USERS_PATH=...` now documents the merged structure: "config de /tongo: frases globales (phrases:) + por persona (users:); default: data/TongoUsers.yml".

## Validation

✅ **Prod compose file (`docker-compose.yml`):** `docker compose config -q` → exit 0  
✅ **Local compose file (`docker-compose.local.yml`):** `docker compose config -q` → exit 0

## Rationale

- **Single image everywhere:** No changes to Dockerfile, volume mounts, or image naming. Same `drdonoso/worldcup2026` image used in both prod and local; only env var bindings differ per environment.
- **Runtime file protection:** Runtime `data/TongoUsers.yml` is gitignored (contains real usernames + phrases). Users copy the committed template and edit locally.
- **Environment variable consolidation:** Eliminates `TONGO_PHRASES_PATH` (merged into the single `data/TongoUsers.yml`), simplifying the env contract.
- **Backward compatibility:** If users have `.env` files with the old `TONGO_PHRASES_PATH` variable, Docker Compose will silently ignore it (no error). Kanté's `config.py` will read from the new consolidated `TONGO_USERS_PATH` only.

## References

- App code changes: Kanté (consolidation in `config.py`)
- History entry: `.squad/agents/maldini/history.md` → "## Learnings" → "/tongo YAML Merge"

---

# Decision: Corrected Group-Stage Scoring Rule + /recalcular Admin Command

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-22  
**Status:** IMPLEMENTED — 1480 tests green

---

## Problem

The `score_groups` function in `src/worldcup_bot/porra/scoring.py` used a
flawed rule: any team that qualified to the top-3 (but at the wrong position)
earned 0.5 points.  This meant a user who predicted a team **1st** and it
finished **2nd** (or vice-versa) — both still in the top-2 direct-qualifying
zone — wrongly received 0.5 instead of 1.0.

DrDonoso's real-data sanity check confirmed: five swap teams (SUI, EGY, FRA,
COL, ENG) each went from 0.5 → 1.0, moving his group total from 16.5 → 19.0.

---

## Corrected Scoring Rule

Per predicted team (`pred_pos ∈ {1,2,3}`, `actual_pos` = 1-indexed real position):

| pred_pos | actual_pos | points | note |
|---|---|---|---|
| 1 or 2 | 1 or 2 | **1.0** | `exacto` — both in direct top-2 qualifying zone |
| 3 | 3 | **1.0** | `exacto` — exact 3rd |
| 1 or 2 | 3 | **0.5** | `clasifica` — boundary near-miss |
| 3 | 1 or 2 | **0.5** | `clasifica` — boundary near-miss |
| any | 4+ | **0.0** | `fallo` |

Key invariant: **order within the top-2 direct-qualifying zone is irrelevant.**
The 3rd-place boundary remains a near-miss (0.5) in either direction.

---

## Implementation

### `src/worldcup_bot/porra/scoring.py`
- Introduced `DIRECT_QUALIFY = 2` module-level constant (separate from
  `QUALIFY_PER_GROUP = 3` which means "3 picks per group" — left unchanged).
- Replaced the old `if actual_pos == pred_pos / elif actual_pos <= QUALIFY_PER_GROUP`
  block with the three-branch logic above.
- Notes remain `"exacto"` / `"clasifica"` / `"fallo"` — the formatter's
  `note_map` in `formatters.py` continues to render ✅/🔶/❌ correctly.

### `src/worldcup_bot/porra/history.py`
- Added `force: bool = False` parameter to `ensure_history`.
- When `force=True`: initialises `history = {}` (ignores disk cache) and runs
  reconstruction for **every** past jornada, not just the uncached ones.
- Both existing call sites (scheduler job, `/evolucion`) pass no `force`
  argument → unchanged behaviour.

### `src/worldcup_bot/bot/handlers.py`
- Added `cmd_recalcular` — a hidden admin command (`/recalcular`) that calls
  `ensure_history(..., force=True)` in a background thread.
- Replies `⏳` while working, then `✅ Histórico recalculado: N jornadas.
  /evolucion ya refleja la nueva puntuación.` on success, or `❌ …` on error.
- Pattern mirrors `cmd_update_diario` (same visibility: not listed in `/start`).

### `src/worldcup_bot/__main__.py`
- Imported `cmd_recalcular`; registered `CommandHandler("recalcular", cmd_recalcular)`.

---

## Tests

- `tests/test_scoring.py`: full truth table (12 cases), regression for DrDonoso's
  5-swap scenario, updated `TestScoreGroupsOffByOne` and
  `TestScoreGroupsQualifiesWrongPosition` tests that asserted the old 0.5 behaviour.
- `tests/test_history.py`: `TestEnsureHistoryForce` — 4 tests for `force=True`
  recompute semantics and `force=False` cache-preservation.
- `tests/test_evolucion_handler.py`: `TestCmdRecalcular` — 5 handler tests
  (force=True called, reply count, no-predictions guard, error path, hidden from /start);
  `TestCmdRecalcularRegistered` — build_app registration check.

**Total: 1452 → 1480 tests (all pass).**

---

## Why this approach

- Pure function (`score_groups`) → single fix propagates to all consumers:
  live ranking, /evolucion history, /listaaciertos, /listaaciertosactual.
- History is fully reconstructable from match results — no date-parameterised
  API calls needed.  `force=True` is safe to call anytime; it just costs one
  `get_all_matches()` call.
- Hidden command pattern keeps /recalcular off the public BotFather menu.

# Goal-Notification Pipeline: Four Live Bug Fixes

**Date:** 2026-06-22  
**Author:** Kanté (Backend Developer)  
**Incident:** Four bugs observed in production during Spain–Saudi Arabia match and New Zealand–Egypt match.

---

## Bug 1 — Duplicate goal (Spain 5-0 sent TWICE, ~8:03 PM)

**Root cause:** `poll_goals_job` (API, ~60 s interval) and `poll_thread_goals_job`
(thread, 25 s) both read `scores[key]` as the announced score, then updated it only
*after* the slow `await` (Reddit+OpenAI enrichment or Telegram send).  PTB's JobQueue
runs jobs concurrently; while job A was awaiting, job B read the stale announced (4-0),
reconciled new=5-0, and announced again → duplicate.

**Fix:** `context.bot_data.setdefault("goal_lock", asyncio.Lock())` — shared by both
jobs.  Inside the lock: read announced → reconcile → **immediately** write
`scores[key] = new_ann`.  Lock released; slow enrichment + send happen outside.  Any
concurrent job that acquires the lock next finds the updated announced and produces no
delta.  Send failures are logged without re-announcing (score was already claimed).

**Files:** `src/worldcup_bot/__main__.py` — `poll_goals_job`, `poll_thread_goals_job`.

---

## Bug 2 — Goal sent with no scorer and no "Ver gol" button (Spain 4-0, ~7:19 PM)

**Root cause:** API detected the 4-0 goal before the thread had the scorer.
`_enrich_scorer` returned `(None, None)` (thread not ready / 429 / OpenAI miss).
`_notify_goal` stored a clip-store entry with `scorer=None`; the clip finder requires a
scorer to match video titles, so `poll_goal_clips_job` never found the clip and the
"Ver gol" button was never added.  Later, when the thread saw 4-0, reconcile returned
no deltas (already announced) → the scorer was never applied retroactively.

**Fix:** New helper `_backfill_scorer_in_clip_store(match, events, settings, context)`
— called in `poll_thread_goals_job` after every match (even when there are no new
deltas).  For each thread event with a known scorer it looks up the clip-store entry by
token key `{match.id}:{team}:{h}-{w}`, skips if `scorer is not None` (idempotent),
then: (a) sets `entry["scorer"]` so `poll_goal_clips_job` can find the clip, and
(b) calls `context.bot.edit_message_text` to add the `🎯 scorer (min')` line to the
original goal message.

**Files:** `src/worldcup_bot/__main__.py` — new `_backfill_scorer_in_clip_store`,
`poll_thread_goals_job` now calls it unconditionally per match.

---

## Bug 3 — Disallowed message showed WRONG score (Spain 3-0 shown, post-VAR was 4-0, ~8:00 PM)

**Root cause:** Goal 5 was VAR'd.  After the VAR, the thread momentarily under-read
the score as 3-0 (a parse glitch that missed event 4).  `reconcile` saw
`seen=5 → new=3`, correctly identified a real disallowed (source's own value dropped),
and emitted a delta with `new_home=3`.  The message said "Spain 3-0" instead of the
correct post-VAR "Spain 4-0".  Worse, `announced` was updated to 3-0, so the API
next tick would re-announce goal 4 as a new goal.

**Fix:** In `poll_thread_goals_job`, after reconcile, for each disallowed delta:
```python
clamped = max(d.new_home, ann_homeaway["home"] - 1)  # never below announced-1
d.new_home = clamped
new_ann["home"] = clamped
```
A single VAR can only reverse one goal per side; the authoritative post-VAR score is
always `announced − 1` on the affected side.  A thread that correctly reads the drop
(e.g. 4-0 after goal 5 VAR'd from 5-0) is unchanged: `max(4, 5-1) = 4`.

**Files:** `src/worldcup_bot/__main__.py` — `poll_thread_goals_job` lock block.

---

## Bug 4 — Missing goals (NZ–EGY 1-2 Salah / 1-3 Trezeguet not sent, ~4:30 AM)

**Root cause:** The cross-job race described in Bug 1.  One job updating announced
past an intermediate score while the other had already read the stale announced could
skip announcing that score.  (Silent hour only sets `disable_notification=True`; goals
are still sent — expected behavior, not a bug.)

**Analysis:** The per-target expansion in `poll_thread_goals_job` iterates
`range(ann+1, new_ann+1)` and produces one notification per intermediate running
score — this is correct.  The API path creates N deltas for an N-goal jump, all
showing the final score (pre-existing behaviour, not a drop), but no goals are
omitted.

**Fix:** Bug 1's `goal_lock` covers Bug 4.  Once the first job claims the score inside
the lock, the other job reads the updated announced and produces no delta — no
intermediate goals are skipped.

**Files:** Covered by Bug 1 fix.

---

## Regression tests added (`tests/test_poll_thread_goals_job.py`)

| Class | Tests | Covers |
|---|---|---|
| `TestCrossJobRace` | 2 | Bug 1: concurrent gather + sequential ordering |
| `TestScorerBackfill` | 5 | Bug 2: edit message, idempotency, skip-if-known, keyboard preserved (ready), keyboard absent (searching) |
| `TestDisallowedAuthoritativeScore` | 2 | Bug 3: under-read clamped; correct read unchanged |
| `TestMultiGoalExpansion` | 2 | Bug 4: 3-goal jump → 3 messages; API catchup → 0 extras |

**Test count:** 1480 → **1489** (all green).

---

## Follow-up fix (code review, 2026-06-22) — Bug 2 regression: Ver gol keyboard stripped by backfill

**Root cause:** `_backfill_scorer_in_clip_store` called `context.bot.edit_message_text`
without `reply_markup`.  Telegram's `editMessageText` API removes the inline keyboard
when the field is absent (PTB omits `None` kwargs → keyboard silently cleared).  If the
clip was already found and `edit_message_reply_markup` had attached the "Ver gol" button
before the backfill ran, that button was permanently lost.

**Race sequence that triggered it:**
1. API announces goal with `scorer=None` → clip-store entry created (`status="searching"`).
2. `poll_goal_clips_job` finds the clip → calls `edit_message_reply_markup` → sets
   `status="ready"`.
3. Thread reports scorer → `_backfill_scorer_in_clip_store` runs, edits the same
   `message_id` text WITHOUT `reply_markup` → keyboard cleared, button gone forever.
   (`poll_goal_clips_job` skips `ready` entries and won't re-add the keyboard.)

**Fix:** Determine keyboard attachment state from `entry["status"]`.  When
`entry.get("status") == "ready"`, pass `reply_markup=build_goal_keyboard(tok)` to
`edit_message_text`; otherwise `reply_markup=None`.  `build_goal_keyboard` was already
imported in `__main__.py`.  No schema change needed.

**Files:** `src/worldcup_bot/__main__.py` — `_backfill_scorer_in_clip_store`.

**New tests:** `TestScorerBackfill.test_backfill_preserves_keyboard_when_clip_ready` and
`test_backfill_no_keyboard_when_clip_not_ready` in `tests/test_poll_thread_goals_job.py`.

**Test count:** 1489 → **1491** (all green).

---

# Decision: TVE broadcast markers (📺) via RTVE schedule API

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-22
**Status:** IMPLEMENTED — 1545 tests green

---

## Problem

DrDonoso wanted `/hoy`, `/siguiente`, and the daily AI update to show which World
Cup fixtures are broadcast on Spanish public TV (La 1 / Teledeporte), marked with a
📺 emoji.  The detection must be automatic (no manual override file) via RTVE's
public schedule API.

---

## Decision

### New module: `src/worldcup_bot/tve.py`

Single-file module; no sub-package needed.  Owns:
- `TveBroadcast` dataclass (kickoff_utc, home_tla, away_tla, channel).
- `ES_NAME_TO_TLA`: static dict of Spanish team name → FIFA TLA for all WC 2026
  nations.  Keys are accent-stripped, lowercased via `_norm()` (unicodedata NFKD),
  so "Túnez", "Tunez", "TUNEZ" all hit the same key.
- `fetch_rtve_schedule(slug)`: thin `requests.get` wrapper, returns JSON or None on
  any error (logs warning, never raises).
- `parse_wc_broadcasts(schedule_json, channel_label)`: filters `idPrograma == 1030562`,
  excludes "resumen" items, parses kickoff via description `(HH:MM)` for La 1 /
  `begintime` for Teledeporte, converts Madrid-local → UTC via `pytz.localize()` (DST-
  correct; do NOT hardcode UTC offset).
- `tve_channel_for(match, broadcasts)`: ±20 min window + unordered TLA pair; time-only
  fallback only when exactly one broadcast is in the window (defensive against
  simultaneous games).  La 1 wins over Teledeporte.
- `load_tve_broadcasts(*, ttl_seconds=21600, tve_enabled=True)`: module-level TTL
  cache (~6 h), fetches tv1 + dep, returns `[]` on total failure.

### RTVE API details

| Property | Value |
|---|---|
| Base URL | `https://www.rtve.es/api/schedule/{slug}.json` |
| **Dead URL (do NOT use)** | `api.rtve.es` (404) |
| Slugs | `tv1` (La 1), `dep` (Teledeporte) |
| WC `idPrograma` | `1030562` |
| Resumen exclusion | `"resumen"` in `name` / `original_episode_name` / `original_event_name` (case-insensitive) |
| Time coverage | Current broadcast week (~10 days); no date param works |
| Time format | `begintime`: YYYYMMDDHHMMSS, Europe/Madrid local |
| La 1 kickoff | Prefer `(HH:MM)` in `description` (actual kickoff) over `begintime` |

### Config change

`tve_enabled: bool = True` added to `Settings`; read from `TVE_ENABLED` env var
(parse `"0"/"false"/"no"` → False).  Maldini wires it in docker-compose.

### Formatter changes

`format_match(match, tz_name, *, tve_label=None)` and `format_match_with_date(...)`
accept an optional `tve_label` kwarg.  When set AND match status is `SCHEDULED`, the
text gains ` 📺 {tve_label}`.  Finished/in-play lines are unchanged.

### Handler changes

`cmd_hoy` and `cmd_siguiente`: `await asyncio.to_thread(load_tve_broadcasts, ...)`
inside a `try/except` — on any error, `broadcasts = []` and the command proceeds
normally without 📺.

### Daily AI update changes

`build_ai_user_message` gains `tve_by_key: dict[str, str] | None = None`.  Today
fixture lines get ` 📺 {label}` appended so the AI model sees which matches are on
TVE.  `_SYSTEM` gains one sentence: "Si algún partido de hoy lleva el emoji 📺,
consérvalo en la nota de ese partido y menciona brevemente que se emite en TVE."
`generate_daily_update` fetches TVE broadcasts (to_thread, graceful degrade) and
builds `tve_by_key` before the AI call.

---

## Why no manual override file

User chose automatic-only mode.  The RTVE API is free, no-auth, and publicly
accessible.  A `TVE_ENABLED` toggle covers the "turn it off" use case without
a file.

---

## Graceful degrade rule

**A flaky RTVE API must NEVER break a command.**  Every call to `load_tve_broadcasts`
is wrapped in `try/except`; on any failure the result is `[]` (no 📺, no crash).
The TTL cache means a transient failure within a 6-hour window still serves stale
data from the last successful fetch.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/tve.py` | New module |
| `src/worldcup_bot/config.py` | `tve_enabled` field + `_parse_bool` + `load_settings` wiring |
| `src/worldcup_bot/bot/formatters.py` | `tve_label` kwarg in `format_match` / `format_match_with_date` |
| `src/worldcup_bot/bot/handlers.py` | `cmd_hoy`, `cmd_siguiente` TVE integration + import |
| `src/worldcup_bot/ai/daily_update.py` | `asyncio` import, `build_ai_user_message` `tve_by_key`, `_SYSTEM` rule, `generate_daily_update` TVE step |
| `tests/conftest.py` | `reset_tve_cache` autouse fixture |
| `tests/test_tve.py` | 54 new tests (all network mocked) |
| `README.md` | 📺 note in bot commands table + Notes section |
| `.squad/agents/kante/history.md` | Learnings appended |

---

# Decision: TVE_ENABLED Optional Environment Variable

**Date:** 2026-06-22  
**Owner:** Maldini (DevOps)  
**Status:** Implemented ✅

## Decision

Wire optional environment variable `TVE_ENABLED` (default: **1**) to allow quick runtime toggle of the "📺 partido en TVE" feature.

## Rationale

Kanté is adding a new feature that marks matches broadcast on TVE (La1/Teledeporte) in `/hoy`, `/siguiente`, and the daily update. The RTVE API is undocumented — if it breaks mid-tournament, we need a quick kill-switch **without a code change or container rebuild**.

## Changes

**1. `docker-compose.yml` (prod)**  
Added after `BELOVED_TEAMS`:
```yaml
# --- Marca con 📺 los partidos que da TVE (vía API de RTVE). "0" para desactivar. ---
TVE_ENABLED: "${TVE_ENABLED:-1}"
```

**2. `docker-compose.local.yml` (dev)**  
Identical entry (parity).

**3. `.env.example`**  
Added commented example:
```bash
# TVE_ENABLED=1   # marca con 📺 los partidos en TVE; 0 para desactivar
```

## Validation

- Both compose files parse cleanly: `docker compose config -q` → exit 0 ✅
- No volume or Dockerfile changes needed
- Env-var follows established pattern: `${VAR:-default}` (same as `PREDICTIONS_PATH`, `BELOVED_TEAMS`, etc.)

## Usage

To disable the TVE feature if the RTVE API breaks:
```bash
export TVE_ENABLED=0
docker compose up -d
```

Or set in `.env`:
```
TVE_ENABLED=0
```

## Future

- Kanté reads `TVE_ENABLED` from `config.py` and self-disables the feature if unset/0.
- If RTVE API stabilizes, feature can stay enabled by default (1).
- If RTVE API is fundamentally broken, feature can be removed in a future release without urgent code-push + rebuild.


---

# Decision: 📺 TVE on match line (deterministic) + `/tongocheck` admin validator

**Date:** 2026-06-22  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented

---

## Context

Two small follow-up improvements after the TVE feature ship (2026-06-22):

1. **📺 position in `/updatediario`** — The channel label was being fed to the AI
   via `build_ai_user_message` and a `_SYSTEM` rule asking the model to repeat it
   in the note.  This was fragile: the AI could paraphrase, omit, or double it.
   `/hoy` already shows the label deterministically after the kickoff time.

2. **Silent YAML failures in TongoUsers.yml** — `load_tongo_config` swallows all
   YAML errors and falls back to built-in `FRASES`.  A stray character breaks the
   whole file with no visible feedback.  A real incident: a stray `.` after a closing
   quote dropped all custom phrases silently.

---

## Decisions

### Task A — 📺 on the match line, not in the AI note

**Decision:** Move the 📺 channel label from the AI path to `render_message` (purely
deterministic HTML builder), matching `/hoy`'s format exactly.

**Changes:**
- `render_message` gains `tve_by_key: dict[str, str] | None = None`.  In Section 2
  (today fixtures), the match line is extended with ` 📺 {label}` (no bold) when
  the `home_tla-away_tla` key is present.
- `build_ai_user_message` loses its `tve_by_key` parameter entirely.  The AI prompt
  no longer contains TVE information; the AI note is purely about curiosity/conflict.
- `_SYSTEM` loses the two-line TVE rule ("Si algún partido de hoy lleva el emoji 📺…").
- `generate_daily_update` passes `tve_by_key` to `render_message` instead of to
  `build_ai_user_message`.

**Rationale:** Deterministic > probabilistic for factual data.  The channel label is
a fact (either on TVE or not); the AI should focus on the curiosity/conflict note.

### Task B — `/tongocheck` hidden admin command

**Decision:** Add a `check_tongo_config(path) → (bool, str)` pure validator in
`tongo.py` and expose it as hidden `/tongocheck` in Telegram (same visibility class
as `/recalcular` / `/updatediario`).

**check_tongo_config contract:**
- Missing file → `(False, "no encontrado en {path}")`.
- YAML parse error → `(False, "Error de YAML: {exc}")` — includes PyYAML line/col.
- Non-mapping structure → `(False, "El fichero no es un mapping YAML válido")`.
- Empty/comment-only file (parses to None) → treated as empty dict → success.
- Success → `(True, "{N} frases globales, {M} usuarios configurados: alice, bob")`
  or `"sin overrides por persona"` when no users.
- Never modifies the hot-reload cache (`_cached_config_*`).
- Never raises.

**cmd_tongocheck** replies:
- `✅ TongoUsers.yml OK — {summary}` on success.
- `❌ TongoUsers.yml: {detail}` on failure.

**Rationale:** Makes YAML typos diagnosable from Telegram without needing to read
logs or restart the bot.  Zero risk to production: it's read-only, hidden, admin-only.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/ai/daily_update.py` | Remove TVE from AI path; add to `render_message` |
| `src/worldcup_bot/data/tongo.py` | Add `check_tongo_config` |
| `src/worldcup_bot/bot/handlers.py` | Add `cmd_tongocheck`; import `check_tongo_config` |
| `src/worldcup_bot/__main__.py` | Register `CommandHandler("tongocheck", cmd_tongocheck)` |
| `tests/test_ai.py` | Add TVE render_message tests, _SYSTEM contract, generate_daily_update TVE |
| `tests/test_tve.py` | Update `TestBuildAiUserMessageTve` (removed `tve_by_key` kwarg tests) |
| `tests/test_tongo_users.py` | Add `TestCheckTongoConfig` (7 tests) + `TestCmdTongocheck` (5 tests) |

**Test count:** 1545 → 1565 (+20 net).

---

# Decision: TongoUsers.yml is REQUIRED for /tongo

**Date:** 2026-06-22  
**Author:** Kanté (Backend Developer)  
**Requested by:** DrDonoso

## Context

`/tongo` previously shipped with a built-in `FRASES` list constant that acted as a
fallback whenever `data/TongoUsers.yml` was missing, empty, or unparseable. This
meant a silently misconfigured file went unnoticed — the bot kept firing the same
stale phrases with no indication anything was wrong.

## Decision

`data/TongoUsers.yml` is now the **single, mandatory** source of truth for `/tongo`
phrases. If it cannot be loaded for any reason (missing file, YAML parse error,
unreadable, top-level-not-a-mapping), `/tongo` **fails visibly** with a Spanish error
message and does nothing else. The rest of the bot keeps running.

## What changed

### `src/worldcup_bot/data/tongo.py`
- Added `class TongoConfigError(Exception): pass`
- `load_tongo_config(path)`: raises `TongoConfigError` on missing file, `yaml.YAMLError`,
  OSError on stat/read, or top-level not-a-mapping. Per-field validation
  (bad `sanchez_ratio`, `phrases_mode`, `phrases`) stays graceful (log + skip).
  The mtime hot-reload cache is only written on a successful parse.
- Removed `FRASES: list[str]` constant (16 built-in phrases)
- Removed `frase_argentino(gender: str) -> str` function
- `choose_tongo_response(...)`: removed `gender` parameter; removed
  `if not sender: use FRASES` fallback; pool is now `sender + gifs`; guard:
  `if not pool: return SANCHEZ_ENS_ROBA` (empty pool never crashes `random.choice`).

### `src/worldcup_bot/bot/handlers.py` — `cmd_tongo`
- Removed `FRASES` and `infer_gender` imports
- Added `TongoConfigError`, `SANCHEZ_ENS_ROBA` to tongo imports
- Config load wrapped in `try/except TongoConfigError`: on failure, logs warning
  and replies `❌ No puedo cargar las frases de /tongo (TongoUsers.yml). Revísalo o
  usa /tongocheck.` then returns.
- `global_phrases = cfg.phrases` (no more `if cfg.phrases else FRASES`)
- Removed `gender = infer_gender(...)` call
- Removed `gender` arg from `choose_tongo_response(...)` call
- GIF fallback: `fallback = random.choice(fb_pool) if fb_pool else SANCHEZ_ENS_ROBA`
  (no FRASES dependency)

### Dead code deleted
- `src/worldcup_bot/data/gender.py` — `infer_gender` / `gender_guesser` wrapper
- `tests/test_gender.py` — 8 tests
- `gender-guesser>=0.4` removed from `pyproject.toml` dependencies

### Tests
- Removed `TestTongoData`, `TestFraseArgentino`, `TestInferGender`, argentino handler
  tests, `test_female/male_gender_phrase_in_pool`
- `load_tongo_config` error tests now assert `raises TongoConfigError` (not empty return)
- `choose_tongo_response` calls updated to drop `gender` parameter
- `test_empty_pool_returns_sanchez` replaces `test_empty_effective_phrases_falls_back_to_frases`
- `TestCmdTongoConfigError` added: error message sent, `random.choice` not called
- `TestCmdTongo` / `TestCmdTongoGifs` use autouse fixture to patch `load_tongo_config`

## What is kept

- `SANCHEZ_ENS_ROBA` and the 1/3 probability gate (unchanged)
- Per-user `sanchez_ratio` overrides (unchanged)
- Reply-targeted path (`{{reply_to_*}}` phrases) (unchanged)
- `check_tongo_config` / `/tongocheck` (graceful, never raises)
- `render_tongo`, `build_tongo_context`, `phrase_eligible`, `phrase_uses_reply`
- Hot-reload mtime cache on the success path

## Rationale

A missing or broken YAML is a configuration error that the operator must fix. Silent
fallback to built-in phrases hides this error and provides a bad UX (phrases the
operator might have overridden). Failing loudly with `/tongocheck` guidance is
strictly better. `SANCHEZ_ENS_ROBA` is a signature phrase, not a fallback — it stays.

---

# Decision: Kickoff-start notice at scheduled kickoff time

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-22  
**Status:** Implemented

---

## Context

The bot already notifies the group for goals (API + thread paths) and match-finish recaps.  Users asked for a notice when a match *starts*, so nobody misses the opening whistle while the bot is running.

---

## Decision

Add `poll_kickoff_job` — a 30-second repeating job that posts a `🟢 ¡Empieza el partido!` HTML message to the group when a match's scheduled `utc_date` arrives.

---

## Key choices

### Time-based, not status-based
The job fires when `kickoff <= now_utc`, regardless of the football-data.org status field (which can lag by several minutes for IN_PLAY).  This gives the most responsive notice at the cost of occasionally firing for a match delayed at the stadium — acceptable for a porra group.

### Reuse `load_finished` / `save_finished`
The existing helpers in `reddit/finished_state.py` are already generic `set[int] ↔ JSON` utilities.  A new `kickoff_state.py` module would have been identical boilerplate; reusing the existing ones keeps the codebase DRY.

### 30-minute grace window
Any match not caught by the seed pass (edge case) and with a kickoff > 30 min in the past is silently marked in `announced` without sending.  Prevents stale announcements after an unexpected restart mid-game.

### Seed pass mirrors `poll_finished_matches_job`
On first run (`kickoff_seeded == False`), all currently live or past-kickoff matches are bulk-inserted into `announced` and the job returns immediately.  This is the same restart-safe pattern used for finished recaps and is well understood by the team.

### Hardcoded 30-second interval
No new env var was added.  A 30-second polling interval is sufficient (notice within ~30 s of kickoff), mirrors the existing goal jobs, and avoids config sprawl.

### `format_match_start` in `formatters.py`
Pure function with no external dependencies — testable in isolation.  Consistent with the existing `format_match`, `format_match_with_date`, etc.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/bot/formatters.py` | Added `format_match_start(match) -> str` |
| `src/worldcup_bot/__main__.py` | Added `poll_kickoff_job`, `_KICKOFF_GRACE` constant; wired `kickoff_announced` + `kickoff_seeded` in `build_app`; registered job; imported `format_match_start` + `timezone` |
| `tests/test_poll_kickoff_job.py` | 21 new tests (seed, normal, restart safety, grace window, silent hour, API error, formatter) |
| `README.md` | Added match-start notice bullet to Notes section |

---

## Test count

1531 → 1552 (+21)
