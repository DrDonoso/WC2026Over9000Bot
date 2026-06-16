# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (python-telegram-bot), football-data.org API, Docker + compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Recent Accomplishments (Phases 1–21)

**2026-06-16:** OpenAI daily update feature verified live (real LiteLLM instance). All 10 inbox decisions merged. 538 tests green.

**Core features:** YAML-driven predictions (hot-reload), official/provisional rankings, football-day rolling window (/hoy/ayer, 09:00→09:00 local), Reddit live goal notifier with "Ver gol" button (multi-host downloader + ffmpeg compression + ffprobe dimension fix), gender-aware /tongo phrases (gender-guesser), /tongo GIF pool (hot-reload), /simulagol random goals (E2E testing), OpenAI-compatible daily 9 AM Spanish recap (self-disables gracefully when vars unset).

**Architecture:** Shared process-wide TTLCache (fixes HTTP 429), goal tokens (SHA1[:12]), non-blocking inflight set, two-level file_id cache, SSL remediation for corporate networks, photo album rankings (top-3 URLs).

**Test status:** 594 passing (538 original + 56 new). Docker container running, State=healthy, RestartCount=0.

## Learnings

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

