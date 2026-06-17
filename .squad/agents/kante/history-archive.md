# Kante History Archive

**Archive date:** 2026-06-17  
**Purpose:** Preserve key learnings from Phases 1–25 for future reference  

## Condensed Key Learnings (Phases 1–25)

### Block 1: Goal Detection Architecture (2026-06-17)

**Root cause:** Reddit match threads use human-narrated format (`66': [](#icon-ball-big)**GOAL FRANCE!!**`) not ESPN-structured lines. Old `parse_goal_events` found 0 goals. Re-parsing also caused VAR flip-flops (score 1-0 → 1-1 → 1-0).

**Fix:** Use football-data score changes as authoritative source; enrich with LLM scorer/minute extraction. Persistent `live_scores.json` prevents flip-flops. `extract_scorer` handles any thread format via natural-language LLM processing.

**Files:** `src/worldcup_bot/reddit/score_state.py`, `src/worldcup_bot/ai/goal_extractor.py`, rewrote `__main__.py::poll_goals_job`.

### LiteLLM/OpenAI Token Parameter Fix (2026-06-16)

**Problem:** User's LiteLLM backend ignores/clamps legacy `max_tokens` to 100 tokens (`finish_reason="length"`). Switching to `max_completion_tokens=1500` yields full natural responses (`finish_reason="stop"`).

**Rule for future:** Always use `max_completion_tokens` (not `max_tokens`) for every `chat.completions.create` call via `AIClient.complete`. Never send both params — some backends error on duplicates.

### Football-day Rolling Window Pattern (9am→9am, configurable)

The same 9am→9am window is used consistently across:
- `get_football_day_matches` (live command matching)
- `football_day_of(match, tz, anchor_hour)` (history jornada labeling)
- Config: `settings.football_day_start_hour` (env `FOOTBALL_DAY_START_HOUR`, default 9)

Handles UTC/local boundary: a 02:00 local match on June 14 belongs to June 13's matchday for a 9am Madrid viewer.

### Persistent State Volume Ownership (Dockerfile fix)

Docker named volumes inherit directory ownership from the **image state** at the mount path. Must create and chown directories in Dockerfile BEFORE the `USER app` directive, so volumes inherit app user ownership on first creation.

**Fix:** Extended Dockerfile RUN to create both `/app/data` and `/app/state` with `chown app:app`.

### Porra Evolution: Jornada-keyed Reconstruction

`porra/history.py` reconstructs standings from match results (not API `?date=` calls) because consecutive football-days can share UTC calendar dates, breaking `?date=` semantics. 

**Key functions:** `football_day_of`, `build_jornadas`, `reconstruct_group_standings` (W=3/D=1/L=0, GD, GF, TLA tie-break), `compute_ranking_at_jornada`.

**Hybrid approach:** Past jornadas use reconstruction (acceptable for trend). Latest jornada uses exact live ranking `engine.compute_general_ranking(predictions, client, official=False)` to avoid tie-break mismatch at chart tip.

### Changelog from Commit-Body Bullets

Python heredoc in `.github/workflows/docker-deploy.yml` preserves body bullets from squash commits, not just commit subjects. Parses indent-based bullet continuation, excludes trailers, falls back to subject-only when no bullets exist.

### Daily AI Update: Always Use HTML parse_mode

All participant names rendered in `<b>…</b>` HTML; all team names bold; AI-provided text HTML-escaped. Helper: `bold_person_names(text, names)` — longest-name-first regex, single pass, handles Unicode word boundaries.

### Design Constraints to Preserve

1. **Module decoupling:** `api/client.py` ← config + cache; never imports bot/ or porra/. `porra/scoring.py` pure functions. `porra/engine.py` orchestrates scoring but no I/O.
2. **Shared TTLCache singleton:** Fixes HTTP 429 rate limit. Lazily initialised in `api/cache.py`, injected into each `FootballDataClient`.
3. **Goal tokens:** SHA1[:12] hex — 12 bytes fits in 64-byte callback data limit.
4. **Non-blocking in-flight guard:** Set of tokens in bot_data prevents multiple concurrent downloads. Status field is belt-and-suspenders.
5. **Two-level file_id cache:** Per-goal shortcut + per-media-url cache layer. Stale file_id evicted on TelegramError, falls through to fresh disk send.

## Test Count History

- Phase 1–5 (Arch + Infra): 156 tests
- Phase 15 (Ver gol E2E): 426 tests
- Phase 20 (OpenAI daily): 538 tests
- Phase 23–25 (Finished match round): 702–733 tests
- Block 1–4 (Goal detection to stats): 836–882 tests
- Porra evolution (jornada + startup backfill): **962 tests**
