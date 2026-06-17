# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (python-telegram-bot), football-data.org API, Docker + compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15
- **Status:** 962 tests green, awaiting coordinator trigger for git commit + image rebuild.

## Current Session: Multi-Block Porra Evolution Completion (2026-06-17)

**2026-06-17 (BLOCK 4c — porra-evolution exact latest + startup backfill):** `ensure_history` latest jornada now uses exact live ranking; history auto-backfilled at startup + refreshed daily. 962 tests green (+12 from 950 baseline).

Key changes:
- `porra/history.py` — `ensure_history` now calls `engine.compute_general_ranking(predictions, client, official=False)` for the **latest** jornada instead of `compute_ranking_at_jornada`. Past jornadas keep using reconstruction (fine for trend). Removed `_check_reconstruction_vs_api` and `_safe_jornada_le` (no longer needed; latest is exact by construction). Single `log.info` at end reports jornada count.
- `__main__.py` — added `history_backfill_job` (async, try/except around everything). Imported `ensure_history` at top level. In `main()`: `app.job_queue.run_once(history_backfill_job, when=15)` (always, not gated on telegram_group_id) + `app.job_queue.run_daily(history_backfill_job, time=dtime(9,5,tzinfo=tz))`. Logs "Porra history refresh enabled — startup (15s) + daily 09:05 {tz}".
- `tests/test_history.py` — updated all `TestEnsureHistory` tests to patch `worldcup_bot.porra.engine.compute_general_ranking` instead of `compute_ranking_at_jornada` for cases where the jornada tested is the latest. Added `TestEnsureHistoryLatestUsesLiveRanking` (3 tests).
- `tests/test_history_backfill.py` (NEW) — `TestHistoryBackfillJob` (5 tests: calls ensure_history, skips on no predictions, swallows API error, swallows predictions load error, logs jornada count). `TestHistoryBackfillScheduling` (4 tests: source-code inspection of `main()` verifying `run_once(when=15)`, `run_daily`, log message, importability).

Pattern: When patching `ensure_history` behavior in tests, always patch `worldcup_bot.porra.engine.compute_general_ranking` (the exact path the function resolves to after `from worldcup_bot.porra import engine` inside `ensure_history`). Patch path `worldcup_bot.porra.history.compute_ranking_at_jornada` still works for past jornadas.



Key changes:
- `porra/history.py` fully rewritten: `build_checkpoint_dates` removed; replaced with `football_day_of(match, tz, anchor_hour)` (same 9am→9am windowing as `/hoy`/`/ayer`), `build_jornadas(matches, tz, anchor_hour)`, `reconstruct_group_standings(finished_group_matches)` (points→GD→GF→TLA ordering, no head-to-head needed for chart), `compute_ranking_at_jornada(predictions, all_matches, jornada, tz, anchor_hour)`. `ensure_history` now calls `get_all_matches()` once and reconstructs all rankings from match data — zero per-jornada API calls. Sanity check added: `_check_reconstruction_vs_api` compares reconstructed top-3 vs live API standings for latest jornada (logs warnings for mismatches, acceptable for tie-break differences).
- `porra/engine.py`: removed dead `compute_ranking_at_date` (was the old `?date=` path).
- `porra/chart.py`: removed 📈 emoji from matplotlib title (DejaVu Sans has no emoji glyph); x-axis labels changed from `YYYY-MM-DD` to `DD/MM` (short, rotated); x-axis label now "Jornada" instead of "Fecha". Telegram caption in `cmd_evolucion` keeps the emoji.

Pattern for reconstruction validation: `ensure_history` calls `_check_reconstruction_vs_api(rec, client.get_standings())` after computing the latest jornada — logs INFO on PASS, WARNING with per-group diff on mismatch.

**2026-06-17 (BLOCK 4 — /evolucion):** Added `/evolucion` command — bump chart image of porra ranking evolution since first match. 936 tests green (+54 from 882 baseline).

Key additions:
- `api/client.py`: `get_standings(date=...)` optional param + params-aware `_get()` with deterministic cache key (`url?key=val`).
- `porra/engine.py`: `compute_general_ranking_from(predictions, actual_standings, actual_winners)` — pure scoring loop with DI. `compute_ranking_at_date(predictions, client, date)` — historical standings via `?date=` + knockout matches filtered by `utc_date <= {date}T23:59:59Z`. Refactored `compute_general_ranking` to call `compute_general_ranking_from` (no behaviour change).
- `porra/history.py`: `load_history`/`save_history` (JSON, best-effort). `build_checkpoint_dates(matches, tz)` → sorted distinct local FINISHED-match dates. `ensure_history(client, predictions, settings, path)` — computes missing + always refreshes latest date.
- `porra/chart.py`: `render_evolution_png(history, out_path)` — matplotlib Agg bump chart (rank=y inverted, dates=x rotated, tab20 colormap, legend outside right). Handles 0/1/N checkpoints.
- `pyproject.toml`: `matplotlib>=3.8` added to deps.
- `bot/handlers.py`: `cmd_evolucion` — load predictions → ensure_history (asyncio.to_thread) → render PNG → send_photo. Friendly errors on all branches.
- `__main__.py`: registered `CommandHandler("evolucion", cmd_evolucion)`. `/start` help updated.

**2026-06-17 (BLOCK 3 refinement):** Always-porra-commentary — removed `live_diff.changed` gate from `poll_finished_matches_job`. Commentary now generated whenever `ai_enabled(settings)` AND `bool(ranking)`, regardless of ranking movement. Added `render_porra_context(diff, ranking)` to `porra/live.py` — always returns meaningful text with "CLASIFICACIÓN ACTUAL" (top-5) and "CAMBIOS CON ESTE RESULTADO" (movements or "Ninguno…" note). Updated `build_commentary_messages` system prompt to handle no-change case gracefully: instructs commentator to acknowledge "Ninguno" text and remind leader, never invent movements. `render_changes_text` preserved unchanged for any other callers. 882 tests green (+16 from 866 baseline).

**2026-06-17:** BLOCK 2 clip-store rework — decoupled goal message from clip search. New `reddit/clip_store.py` (goal_token, load_clips, save_clips, add_entry, prune_old_entries). `_process_goal_delta` now captures message_id and writes searching entry. New `poll_goal_clips_job` (45s interval): finds clip via Reddit, downloads to `{state_dir}/clips/{token}.mp4`, edits original message to add keyboard, prunes 7-day-old entries. Reworked `cmd_ver_gol_callback`: serves pre-downloaded clip from disk, file_id cache in clip-store entry, inflight guard. Reworked `cmd_simula_gol`: sends no keyboard immediately, registers clip-store entry with status "searching". Removed old `goal_clips`/`clip_file_ids` bot_data dicts. 826 tests green.

**2026-06-17:** BLOCK 1 goal-detection rework — football-data score-change detection + persistent live_scores.json + OpenAI scorer extractor + new HTML goal messages (no keyboard). Old Reddit-parse detection path removed. 789 tests green.

**2026-06-16:** Match-finish stats + porra commentary feature (ESPN API client, Reddit gameId extraction, commentators pool, live ranking tracker, poll_finished_matches_job with dedup) — 702 tests green. Refinement: combined message (stats + "----" + commentary), persona hidden (style-only via system prompt), bold_person_names helper applied to all participant displays — 733 tests green. Verified live in container with combined message to test group.

**2026-06-16 (earlier):** OpenAI daily update feature verified live (real LiteLLM instance). All 10 inbox decisions merged. 538 tests green.

**Core features:** YAML-driven predictions (hot-reload), official/provisional rankings, football-day rolling window (/hoy/ayer, 09:00→09:00 local), Reddit live goal notifier with "Ver gol" button (multi-host downloader + ffmpeg compression + ffprobe dimension fix), gender-aware /tongo phrases (gender-guesser), /tongo GIF pool (hot-reload), /simulagol random goals (E2E testing), OpenAI-compatible daily 9 AM Spanish recap (self-disables gracefully when vars unset), match-finish ESPN stats card + porra commentary with combined messaging and bold names, score-based goal detection (block 1), persistent clip storage + background clip search + deferred keyboard editing (block 2).

**Architecture:** Shared process-wide TTLCache (fixes HTTP 429), goal tokens (SHA1[:12]), non-blocking inflight set, two-level file_id cache, SSL remediation for corporate networks, photo album rankings (top-3 URLs), ESPN integration (thin client + formatter), live porra state tracking (separate from daily snapshot), persistent live_scores.json for score-change goal detection, persistent goal_clips.json (clip-store) with in-memory bot_data["clip_store"] as authoritative cache, clips/ volume dir for downloaded videos.

**Test status:** 826 passing (block 2 adds 37 new tests). Docker container running, State=healthy, RestartCount=0.

**Block 2 key patterns:**
- clip_store.py is pure/sync — no async, no Telegram; safe from anywhere
- bot_data["clip_store"] is authoritative; JSON is persistence layer loaded at startup
- poll_goal_clips_job: each entry wrapped in try/except so one error doesn't kill others
- Stale file_id: evict on TelegramError, fall through to fresh disk send
- prune_old_entries called every tick (7-day retention)
- Tests patch `_cs_save_clips` in handlers tests to avoid real I/O on /app/state

## Learnings

### Block 1 — football-data score-change detection + OpenAI goal_extractor (2026-06-17)

**Root cause of goal-notifier failures:**
- Reddit match threads use human-narrated format (`66': [](#icon-ball-big)**GOAL FRANCE!!**`), not ESPN-structured lines with ⚽ and `Goal! H hs, A as. Scorer (Team)`. The old `parse_goal_events` found 0 goals.
- Re-parsing Reddit also caused VAR flip-flops (score 1-0 → 1-1 → 1-0) when ESPN reordered events.

**Fix — detect from football-data score changes:**
- `src/worldcup_bot/reddit/score_state.py` — `GoalDelta` dataclass + `load_scores` / `save_scores` / `diff_scores` (pure). Persistent state in `{state_dir}/live_scores.json`.
- `src/worldcup_bot/ai/goal_extractor.py` — `extract_scorer(ai, thread_text, scoring_team, home_team, away_team, new_home, new_away) → (scorer|None, minute|None)`. Handles BOTH thread formats (LLM reads natural language). `_parse_extractor_json` handles clean / fenced / garbage JSON.
- `src/worldcup_bot/reddit/notifier.py` — added `format_new_goal_message` and `format_disallowed_message` (HTML, escape all variables, scoring team bold). Old `format_goal_notification` / `build_goal_keyboard` kept for cmd_simula_gol / block-2 flow.
- `src/worldcup_bot/__main__.py` — `poll_goals_job` completely rewritten. `_enrich_scorer` (Reddit → OpenAI → parse_goal_events fallback). `_process_goal_delta` sends goal/disallowed messages. No keyboard in block 1. `compute_new_goals` / `notified_goal_keys` / `seeded_threads` removed.

**Importable enrichment functions for E2E testing:**
- `worldcup_bot.ai.goal_extractor.extract_scorer` — call with `(ai, thread_text, scoring_team, home_team, away_team, new_home, new_away)` using real France-Senegal thread 1u7ltq6.
- `worldcup_bot.ai.goal_extractor._parse_extractor_json` — standalone JSON parser for testing LLM output.
- `worldcup_bot.reddit.score_state.diff_scores` — pure function, no I/O.

**Key files changed/added:**
- NEW: `src/worldcup_bot/reddit/score_state.py`
- NEW: `src/worldcup_bot/ai/goal_extractor.py`
- MODIFIED: `src/worldcup_bot/reddit/notifier.py` (added new formatters)
- MODIFIED: `src/worldcup_bot/reddit/parser.py` (removed `compute_new_goals`)
- MODIFIED: `src/worldcup_bot/__main__.py` (rewrote poll_goals_job)
- NEW TESTS: `test_score_state.py`, `test_goal_extractor.py`, `test_goal_formatter.py`, `test_poll_goals_job.py`
- MODIFIED TESTS: `test_reddit_parser.py` (removed TestComputeNewGoals)



**2026-06-16 (earlier):** OpenAI daily update feature verified live (real LiteLLM instance). All 10 inbox decisions merged. 538 tests green.

**Core features:** YAML-driven predictions (hot-reload), official/provisional rankings, football-day rolling window (/hoy/ayer, 09:00→09:00 local), Reddit live goal notifier with "Ver gol" button (multi-host downloader + ffmpeg compression + ffprobe dimension fix), gender-aware /tongo phrases (gender-guesser), /tongo GIF pool (hot-reload), /simulagol random goals (E2E testing), OpenAI-compatible daily 9 AM Spanish recap (self-disables gracefully when vars unset), match-finish ESPN stats card + porra commentary with combined messaging and bold names.

**Architecture:** Shared process-wide TTLCache (fixes HTTP 429), goal tokens (SHA1[:12]), non-blocking inflight set, two-level file_id cache, SSL remediation for corporate networks, photo album rankings (top-3 URLs), ESPN integration (thin client + formatter), live porra state tracking (separate from daily snapshot).

**Test status:** 733 passing (702 match-finish round A + 31 bold-names round B). Docker container running, State=healthy, RestartCount=0.

## Summary of Recent Work (Condensed)

### Daily Update: 4 Scenarios + None=skip contract (2026-06-16)

`generate_daily_update` now returns `str | None`.  Four scenarios driven by `has_yesterday` (FINISHED matches) + `has_today` (any status):
- **None return**: both empty → caller skips posting entirely (`daily_update_job` logs + returns; `cmd_update_diario` replies "🤷 No hay partidos…").
- **"pausa"**: yesterday ✓, today ✗ → recap + standings-frozen notice; `client.get_next_match()` consulted for resume date.
- **"reanudacion"**: yesterday ✗, today ✓ → competition-resumes framing; ayer section OMITTED from HTML.
- **"normal"**: both ✓ → unchanged full recap + preview.

`render_message` section omission rules: ayer section only rendered when `yesterday` non-empty; today section shows fixtures or (if `scenario=="pausa"`) a ⏸️ pause note; porra section always present.

`format_spanish_date(utc_date, tz_name) → str | None`: constant `_DIAS_ES`/`_MESES_ES` lists (no locale), returns None on any error. Example: `"el sábado 20 de junio"`.

AI user message now includes `ESCENARIO: {scenario}` and (for pausa) `PROXIMOS PARTIDOS:` lines. `_SYSTEM` prompt extended with per-scenario `standings_comment` guidance.

**Final test count: 614 passing.**

### LiteLLM clamps legacy `max_tokens` to 100 — must use `max_completion_tokens` (2026-06-16)

Live diagnostics confirmed the user's LiteLLM proxy ignores/clamps the legacy `max_tokens` param to 100 tokens (`finish_reason="length"`, `completion_tokens=100`). Switching to `max_completion_tokens=4000` yields a full natural completion (`finish_reason="stop"`). **Rule: always use `max_completion_tokens` (not `max_tokens`) for every `chat.completions.create` call via `AIClient.complete`.** openai SDK ≥1.x supports this. Never send both params — some backends error on duplicates.

### JSON truncation at max_tokens=800 with 12 participants (2026-06-16)

With 12 porra participants + match notes + standings narrative, the AI JSON response was truncated at 800 tokens → `parse_ai_json` failed with "Unterminated string" → empty "La porra" section. Fixed by raising `max_tokens` to 1500 and bounding `standings_comment` to ≤ 4–5 short sentences in the `_SYSTEM` prompt.

### Daily Update HTML Format (2026-06-16)

**HTML message format** — daily update now returns `parse_mode="HTML"` markup.  Three sections separated by blank lines:
- `📅 <b>Resultados de ayer</b>` — one FINISHED match per line; winner's name in `<b></b>`, DRAW/None → no bold.  Flag placement: `{home_flag} {home} {score} {away} {away_flag}`.
- `⚽ <b>Partidos de hoy</b>` — both team names in `<b></b>`, flag placement same.  Optional `   <i>{note}</i>` indented line ONLY when AI note is non-empty.
- `📊 <b>La porra</b>` — AI standings comment (HTML-escaped).
Always escape user/AI-provided strings with `html.escape(s, quote=False)` before inserting into the template.

### Combined match-finish message, persona hidden, bold_person_names (2026-06-16)

**Combined match-finish message** — `poll_finished_matches_job` now sends **one** `parse_mode="HTML"` message per finished match, combining ESPN stats card (Part A) and porra commentary (Part B) with a `\n\n----\n\n` separator.  Logic:
- Both available → `stats_text + "\n\n----\n\n" + commentary_text`
- Only stats → `stats_text` (no separator)
- Only commentary → `commentary_text` (no separator)
- Neither → no `send_message` call at all

**Persona style-only, name hidden** — `pick_commentator()` still selects a random persona to drive the generation style, but its name is never shown in the sent message.  The `🎙️ {persona}:` prefix is gone.  Added to `build_commentary_messages` system prompt: *"No firmes ni menciones tu propio nombre."* so the model also suppresses self-identification.

**`bold_person_names(text, names)` helper** — added to `bot/formatters.py`.  HTML-escapes `text` then wraps each known participant display_name in `<b>…</b>`.  Matching rules: longest-name-first alternation (prevents partial overlap), Unicode word boundaries `(?<!\w)…(?!\w)`, single regex pass (no double-wrap).  Applied in:
- `poll_finished_matches_job`: `bold_person_names(raw_commentary, participant_names)` before combining.
- `render_message` (daily update): `bold_person_names(standings_comment, participant_names)` — `render_message` receives an optional `participant_names` list from `generate_daily_update`.

**Ranking/detail formatters now return HTML** — `format_general_ranking` and `format_user_detail` in `bot/formatters.py` use `<b>…</b>` for display_names and section headers (replaces `*bold*` Markdown).  All `reply_text` / `InputMediaPhoto` calls in handlers that use these formatters now pass `parse_mode="HTML"`.  `cmd_participantes` also sends with `parse_mode="HTML"` and wraps display_names in `<b>`.

**Final test count: 733 passing.**

**JSON AI contract** — `ai.complete()` now returns STRICT JSON (no markdown):
```json
{"today_notes": {"TLA1-TLA2": "nota o vacía"}, "standings_comment": "texto"}
```
`parse_ai_json(raw)` strips ` ```json ` fences then `json.loads()`; on any failure → `({}, "")` + `log.warning` — message always renders.

**Snapshot module** (`src/worldcup_bot/ai/snapshot.py`) — tracks provisional porra positions per YYYY-MM-DD local date.  File: `{state_dir}/porra_snapshot.json`.  Schema: `{"YYYY-MM-DD": {username: position}}`.  Prunes to 7 most-recent dates.  All I/O is best-effort (swallow+log); bot never crashes on state ops.  Key functions: `load_snapshots`, `save_snapshots`, `compute_movements`, `update_and_diff`.

**state_dir** — `Settings.state_dir` (default `/app/state`, env `STATE_DIR`) added to config.  Maldini wires the writable `/app/state` Docker volume.

**parse_mode="HTML"** — added to BOTH `send_message` calls:
- `__main__.py` `daily_update_job`
- `bot/handlers.py` `cmd_update_diario`

**Key file paths:**
- `src/worldcup_bot/ai/daily_update.py` — orchestrator + pure helpers (`render_message`, `build_ai_user_message`, `parse_ai_json`)
- `src/worldcup_bot/ai/snapshot.py` — new snapshot module
- `src/worldcup_bot/config.py` — `state_dir` field
- `tests/test_ai.py` — updated AI tests (594 total)
- `tests/test_snapshot.py` — new snapshot tests

### Daily Update HTML Format + Porra Movement Verified Live (2026-06-16)

**Status:** Feature complete & verified live (Telegram test group message #446). Pending user approval for commit.

**Summary:** Reworked daily AI update from raw Markdown to deterministic HTML-formatted messages with team flags, smart bolding, and porra standings movement tracking.

**Key implementation notes:**
- `render_message()` (pure function) builds three-section layout: yesterday's FINISHED match (winner bolded, draw no bold), today's matches (both teams bolded, flags), La porra standings comment.
- `parse_ai_json()` handles JSON truncation gracefully: strict JSON input from AI, strips ` ```json ` fences, `json.loads()` with fallback to `({}, "")` + `log.warning` on any parse error.
- `snapshot.py` module (new): tracks provisional porra positions per YYYY-MM-DD local date; file `{state_dir}/porra_snapshot.json`; prunes to 7 most-recent dates; all I/O best-effort (never crashes).
- `state_dir` config field (default `/app/state`, env `STATE_DIR`) — Maldini owns the Docker volume.
- `parse_mode="HTML"` added to BOTH send_message calls (daily_update_job + cmd_update_diario).
- All AI-provided strings escaped with `html.escape(s, quote=False)`.

**Critical fix — max_tokens vs max_completion_tokens:**
- User's LiteLLM backend clamps legacy `max_tokens` to 100 tokens (`finish_reason="length"`).
- Switched entire codebase to `max_completion_tokens` (OpenAI SDK ≥1.x, LiteLLM-compatible).
- Never send both params simultaneously (some backends error on duplicates).
- **PERMANENT RULE for future sessions:** Always use `max_completion_tokens`, never `max_tokens`.

**Token budget tuning:**
- Raised from 800 → 1500 tokens to accommodate 12 porra participants + match notes + standings narrative.
- Bounded `standings_comment` to "máximo 4-5 frases cortas" in system prompt to reduce token footprint.

**E2E verification (Coordinator):**
- Rebuilt Docker image, recreated `bot_state` volume with correct ownership.
- Seeded synthetic 'yesterday' snapshot (France-Senegal highlighted as rivalry/armed-conflict context).
- Posted rendered HTML update to Telegram test group.
- Verified: full JSON received (no truncation), France-Senegal note present, other 3 matches noteless (no filler), porra movement narrative rendered, flags + HTML bold formatting rendered correctly.
- 595 tests passing (56 new tests for snapshot + format + max_completion_tokens).

### today_notes prioritises naming armed conflicts concretely (2026-06-16)

`_SYSTEM` in `ai/daily_update.py` now instructs the model with an explicit three-tier priority for `today_notes`:
1. **Armed conflict first:** if the two nations share a current/historical armed conflict → name it factually (e.g. "se enfrentaron en la Guerra de las Malvinas (1982)"). The word "conflicto armado" appears in the prompt, Malvinas cited as example.
2. **Other genuine curiosity** (colonial history, territorial dispute, memorable WC match) if no conflict.
3. **Empty string** if nothing genuine — filler explicitly forbidden ("NUNCA inventes", "nunca pongas relleno genérico").

The `today_notes` rule is stated up-front and unconditionally before scenario-specific `standings_comment` guidance, so it fires in ALL scenarios (`normal`, `reanudacion`, `pausa`).

`empty-string = no rendered note` behaviour preserved unchanged.

Added `TestSystemPromptContract` (5 tests). **Final test count: 619 passing.**

### Scenario-Aware Daily Update — Live Verification (2026-06-16)

**Status:** Implementation verified live; pending commit.

**Summary:** `generate_daily_update()` now returns `str | None` with three active scenarios (plus None skip) based on match presence:
1. **No matches (yesterday ✗, today ✗)** → returns `None` → caller skips post entirely.
2. **Pausa (yesterday ✓, today ✗)** → recap + standings-frozen notice with Spanish next-match date (Msg 452).
3. **Reanudación (yesterday ✗, today ✓)** → competition-resumes framing; ayer section omitted (Msg 453).
4. **Normal (both ✓)** → unchanged full recap + preview.

**Implementation details:**
- `format_spanish_date(utc_date, tz_name)` helper: constant `_DIAS_ES`/`_MESES_ES` lists (no locale), returns `None` on error.
- `render_message()` omission rules: ayer section rendered only when non-empty; today section shows fixtures or (pausa) a ⏸️ pause notice.
- AI `_SYSTEM` prompt extended with per-scenario `standings_comment` guidance.
- Callers: `daily_update_job` skips send when `None`; `cmd_update_diario` replies "🤷 No hay partidos…".
- **Final test count: 614 passing** (19 new tests for scenarios).

**Verification (Coordinator):**
- Forced empty match-days in test container.
- SKIP: returned `None` (nothing posted).
- PAUSA: posted msg 452 with recap + frozen-standings notice + Spanish date + porra narration.
- REANUDACION: posted msg 453 with resume framing, no ayer section.

**Files:** `src/worldcup_bot/ai/daily_update.py`, `__main__.py`, `bot/handlers.py` + tests.

### Condensed: Match-Finish Rounds A & B (2026-06-16)

**Scope:** When a WC match finishes, automatically post (A) an ESPN stats card and (B) an AI-generated porra-commentary in the voice of a random Spanish football commentator.

**ESPN Summary API** — reachable from the container. Endpoint:
`GET https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={gameId}`
Send `User-Agent: Mozilla/5.0` header. Response: `boxscore.teams[].{homeAway, team.displayName, statistics[{name, displayValue}]}`. Key stat names: `possessionPct` (already a %), `totalShots`, `shotsOnTarget`, `wonCorners`, `foulsCommitted`, `yellowCards`, `redCards`, `offsides`, `saves`, `passPct` (fraction 0-1 → ×100), `accuratePasses/totalPasses` (fallback for pass %).

**gameId from Reddit match thread** — `find_match_thread(home, away)` returns a permalink; fetch full thread HTML from `old.reddit.com{permalink}`; regex `gameId=(\d+)` extracts the ESPN game ID.

**poll_finished_matches_job** — repeating job (default 120s interval). Dedup: on first run, seed `finished_seen` = current finished IDs and return (no sends). On each subsequent run, newly-finished IDs (set diff) trigger Part A (ESPN stats) and Part B (porra diff + AI commentary). Each match wrapped in try/except — one failure never breaks others. Always `save_live` after Part B regardless of whether AI ran.

**porra/live.py** — separate from daily `porra_snapshot.json`. State file: `{state_dir}/porra_live.json`. Schema: `{username: {pos, pts, name}}`. Functions: `load_live`, `save_live`, `build_state(ranking)`, `diff_live(old, new) → LiveDiff`, `render_changes_text(diff) → str`. `LiveDiff.changed=False` when nothing meaningful changed (pts delta < 0.001 and no pos change and no new users).

**Commentators pool** (`ai/commentators.py`) — `COMMENTATORS = ["Manolo Lama", "Julio Maldini", "Andrés Montes"]`. Per-persona style hints. `pick_commentator(rng=None)`, `build_commentary_messages(persona, changes_text) → (system, user)`, `async generate_porra_commentary(ai, persona, changes_text) → str`. Uses `max_completion_tokens=400`.

**Config additions** — `espn_league_slug` (env `ESPN_LEAGUE_SLUG`, default `"fifa.world"`), `finished_poll_interval_seconds` (env `FINISHED_POLL_INTERVAL_SECONDS`, default `120`). Both have safe defaults — no compose changes needed.

**Key file paths:**
- `src/worldcup_bot/espn/__init__.py`, `espn/client.py`, `espn/formatter.py` — new ESPN package
- `src/worldcup_bot/ai/commentators.py` — new commentators module
- `src/worldcup_bot/porra/live.py` — new live tracker
- `src/worldcup_bot/reddit/scanner.py` — added `get_espn_game_id()`
- `src/worldcup_bot/__main__.py` — added `poll_finished_matches_job` + scheduling
- `src/worldcup_bot/config.py` — added `espn_league_slug`, `finished_poll_interval_seconds`
- `tests/test_espn_client.py`, `test_espn_formatter.py`, `test_espn_scanner.py`, `test_commentators.py`, `test_porra_live.py`, `test_poll_finished_job.py` — 83 new tests

**Final test count: 702 passing (619 + 83 new).**

### Block 3 — always-send final-result, 3-dash separator, simplified stats header (2026-06-17)

**Problem:** When matches finished yesterday, no stats were sent and only the porra commentary appeared (when present). When neither ESPN stats nor porra change existed, nothing was sent at all — the user had no signal that a match had ended.

**Fix:** `poll_finished_matches_job` now ALWAYS sends one message per finished match. Message is assembled from up to 3 sections joined by `"\n\n---\n\n"`:
1. **Section 1 (always):** `🏁 <b>Final</b>\n{home_flag} {h_name} {hs}-{as_} {a_name} {away_flag}` — winner's team name wrapped in `<b>…</b>` (HOME_TEAM → home bolded, AWAY_TEAM → away bolded, DRAW/None → neither).
2. **Section 2 (if ESPN stats found):** `format_match_stats` card — header simplified from `"📊 <b>Estadísticas — {flag} {home} {hs}-{as} {away} {flag}</b>"` to just `"📊 <b>Estadísticas</b>"` to avoid duplicating the scoreline already in section 1.
3. **Section 3 (if porra changed AND ai_enabled):** AI commentary with `bold_person_names` applied — unchanged logic.

**Key implementation details:**
- `import html` added to `__main__.py` stdlib imports; `team_flag` added to `bot.formatters` import.
- `espn/formatter.py` — removed `import html`, `from worldcup_bot.bot.formatters import team_flag`, and the 6 header-only variables (`home_name`, `away_name`, `home_flag`, `away_flag`, `h_score`, `a_score`). Header is now a plain string literal.
- The old `if combined: await ...` guard is gone — `send_message` is called unconditionally after building sections.
- Old 4-dash `"\n\n----\n\n"` separator replaced by 3-dash `"\n\n---\n\n"` per user spec.

**Key files changed:**
- MODIFIED: `src/worldcup_bot/__main__.py` (reworked assembly + always-send in `poll_finished_matches_job`)
- MODIFIED: `src/worldcup_bot/espn/formatter.py` (simplified header, removed unused imports/vars)
- MODIFIED: `tests/test_espn_formatter.py` (updated 3 tests: `test_header_present`, `test_none_score_defaults_to_zero` → `test_none_score_still_renders`, `test_html_escape_team_name` → `test_special_chars_in_team_name_no_crash`)
- MODIFIED: `tests/test_poll_finished_job.py` (`_make_match` gets `winner` param; new `TestFinalResultSection` class with 9 tests; `TestCombinedMessage` fully updated; `test_no_send_when_game_id_none` → `test_no_stats_in_message_when_game_id_none`)

**Final test count: 835 passing (826 block-2 baseline + 9 new Block-3 tests).**

---

### Block 4 — Persistent vergol stats counter + /estadisticas command (2026-06-17)

**What was built:**
- `src/worldcup_bot/reddit/vergol_stats.py` — pure/sync module. Schema: `{str(user_id): {"name": str, "tokens": [...]}}`. Four public functions:
  - `load_stats(path) -> dict` — returns {} on missing/corrupt
  - `save_stats(path, data)` — best-effort, swallows+logs errors
  - `record_view(data, user_id, name, token) -> bool` — dedupes per (user, token), updates name, returns True only if new view
  - `leaderboard(data) -> list[tuple[str, int]]` — sorted by count desc, name asc; excludes users with empty token lists
- `bot/handlers.py` — added `_record_vergol_view(settings, query, token)` helper (best-effort, never raises). Called in `cmd_ver_gol_callback` after BOTH delivery paths (cached file_id and fresh disk send). Uses load/save on each tap — simple and consistent.
- `bot/handlers.py` — new `cmd_estadisticas` command: HTML leaderboard with `<b>name</b>` and `html.escape`; empty-data fallback message.
- `cmd_start` help updated to list `/estadisticas`.
- `__main__.py` — imports + `CommandHandler("estadisticas", cmd_estadisticas)` registered.
- **NEW TESTS:** `tests/test_vergol_stats.py` (31 tests) + new classes in `test_handlers.py` (`TestCmdVerGolCallbackStats`, `TestCmdEstadisticas`).

**Key patterns:**
- vergol_stats.py is pure/sync — no async, no Telegram; safe from anywhere (same as clip_store.py).
- No new bot_data keys — stats are always loaded fresh from disk on each tap (low-frequency operation).
- Patch targets in handlers tests: `worldcup_bot.bot.handlers._vs_record_view`, `_vs_load_stats`, `_vs_save_stats`.
- Counter failure isolation: the try/except in `_record_vergol_view` is the sole safety net — no additional nesting required in the callback.

**E2E importable functions (for coordinator):**
- `worldcup_bot.reddit.vergol_stats.record_view(data, user_id, name, token) -> bool`
- `worldcup_bot.reddit.vergol_stats.leaderboard(data) -> list[tuple[str, int]]`
- `worldcup_bot.reddit.vergol_stats.load_stats(path) -> dict`
- `worldcup_bot.reddit.vergol_stats.save_stats(path, data)`
- `worldcup_bot.bot.handlers.cmd_estadisticas` — send `/estadisticas` to test group after recording a few views.

**Key files changed/added:**
- NEW: `src/worldcup_bot/reddit/vergol_stats.py`
- NEW: `tests/test_vergol_stats.py`
- MODIFIED: `src/worldcup_bot/bot/handlers.py` (imports, _record_vergol_view, cmd_ver_gol_callback wiring, cmd_estadisticas, cmd_start help)
- MODIFIED: `src/worldcup_bot/__main__.py` (import cmd_estadisticas, CommandHandler registration)
- MODIFIED: `tests/test_handlers.py` (import cmd_estadisticas, TestCmdVerGolCallbackStats, TestCmdEstadisticas)

**Final test count: 866 passing (835 block-3 baseline + 31 new tests).**

### Block 3 refinement — always-porra-commentary (2026-06-17)

**Problem:** Commentary only fired when `live_diff.changed` was True — so if a match finished without moving the porra standings, the user got no narration (or nothing at all when ESPN was also absent). David wanted commentary after every match when AI is enabled, even if no one moved.

**Fix — three-part change:**
1. **`porra/live.py`** — added `render_porra_context(diff: LiveDiff, ranking: list) -> str`. Always returns meaningful text with two blocks:
   - `CLASIFICACIÓN ACTUAL:` — top-5 entries as `{pos}. {display_name} — {pts} pts`
   - `CAMBIOS CON ESTE RESULTADO:` — movement wording from `render_changes_text` if any, else `"Ninguno — la clasificación no se ha movido con este resultado."`
   `render_changes_text` left unchanged for any other callers (daily update may use it later).

2. **`__main__.py` `poll_finished_matches_job`** — removed `live_diff.changed` gate. New condition: `ai_enabled(settings) and bool(ranking)`. Uses `render_porra_context(live_diff, ranking)` instead of `render_changes_text(live_diff)`.

3. **`ai/commentators.py` `build_commentary_messages`** — updated system prompt:
   - Context description updated: explains the input contains standings + change block.
   - Adds: if `"Ninguno"` in text → say so briefly and remind who leads; never invent movements.

**Net result for the message:**
- Section 1 (🏁 Final result): always
- Section 2 (ESPN stats): when stats found
- Section 3 (porra narration): when `ai_enabled` AND `bool(ranking)` — independent of stats and independent of movement

**Tests:**
- `test_porra_live.py` — new `TestRenderPorraContext` class (9 tests): always non-empty, includes both headers, "Ninguno" when no movement, lists movements when changed, top-5 cap, etc.
- `test_commentators.py` — added `test_no_change_instruction_in_system` and `test_no_invent_movements_instruction_in_system`.
- `test_poll_finished_job.py` — updated `test_only_stats_when_no_porra_change` (now expects 3 sections, mocked commentary); added `TestAlwaysCommentary` class (5 tests): no-change+no-stats, no-change+stats, empty-ranking suppresses, AI-disabled suppresses, context text verified.

**Key pattern:**
- Always generate commentary for any match finish when AI + participants exist, so users always get a porra update — even when no one moved.
- The "CLASIFICACIÓN ACTUAL" block gives the commentator context to narrate who leads even in no-change case.
- `render_porra_context` is the only caller-side change; `render_changes_text` is preserved for daily update or other future callers.

**Final test count: 882 passing (866 baseline + 16 new).**

### Block 4 — Ver-gol stats (persistent per-user counter) (2026-06-17)

**Requirement:** Track who taps "Ver gol" per user, persist across restarts, show leaderboard via `/estadisticas` command.

**Implementation — new module `src/worldcup_bot/reddit/vergol_stats.py`:**
- Pure sync helper (like `clip_store.py`) — no async, no Telegram
- File: `{state_dir}/vergol_stats.json` schema: `{str(user_id): {"name": display_name, "tokens": [goal_tokens]}}`
- User ID stringified for JSON key (int keys unsupported)
- Token-based dedup: append token only if not already in list (prevents double-count on multiple taps)
- `load_stats(path)` / `save_stats(path, data)` — graceful on missing file or corrupt JSON
- `record_view(stats, user_id, goal_token, display_name_fn)` — update name (handles username changes), append token
- `leaderboard(stats) -> list` — sorted by token count desc, name asc

**Integration into `cmd_ver_gol_callback`:**
- Hook marked with `[Block 4]` in sources is now active
- After successful `send_video`, call `_record_vergol_view(goal_token, user_id, ...)`
- Best-effort isolation: wrap stats logic in try/except, log warning on any error, never raise

**New command `/estadisticas`:**
- `cmd_estadisticas` handler (new in `bot/handlers.py`)
- Calls `leaderboard(load_stats(...))` on every invocation (stats loaded fresh, not cached in bot_data)
- HTML output: trophy emoji header, numbered list, bold names, empty-state message in Spanish
- Registered in `build_app` and listed in `/start` help text

**Low-frequency I/O pattern:**
- Stats loaded fresh on every `/estadisticas` command invocation
- Avoids extra bot_data key and keeps the model simple
- Per-tap I/O cost is negligible (views are low-frequency events)

**Consequences:**
- `vergol_stats.json` created on first tap in `{settings.state_dir}/`
- Pure functions importable for E2E verification (no Telegram context needed)
- No migration needed — missing file gracefully returns `{}`

**Tests:**
- `tests/test_vergol_stats.py` — 24 tests: load/save round-trip, dedup token logic, display name updates, leaderboard sorting
- `tests/test_handlers.py` — 7 new tests: _record_vergol_view behavior, cmd_estadisticas output formatting, empty leaderboard, integration with cmd_ver_gol_callback

**Final test count: 882 passing (final for Block 4 itself — no new tests added, just verified integration).**

