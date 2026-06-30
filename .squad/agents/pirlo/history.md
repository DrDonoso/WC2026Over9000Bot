# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-06-15 — Initial Architecture Decision

- **Package:** `worldcup_bot`, image `drdonoso/worldcup2026`, entry `python -m worldcup_bot`
- **Layout:** src-layout mirroring RedditSoccerGoals. Modules: `bot/`, `api/`, `porra/`, `storage/`, `config.py`.
- **Deps:** httpx, aiosqlite, python-telegram-bot (same stack as sibling repo minus yt-dlp).
- **football-data.org:** Free tier, 10 req/min, competition code `WC` (id 2000). Poll results every 2 min during matches, daily fixture sync.
- **Scoring default:** 3 exact / 1 outcome / 0 wrong. Locks at kickoff.
- **Env vars:** TELEGRAM_BOT_TOKEN, FOOTBALL_DATA_API_KEY, TELEGRAM_GROUP_ID, ADMIN_TELEGRAM_IDS, POLL_INTERVAL_SECONDS, FIXTURE_SYNC_HOUR_UTC, DB_PATH.
- **CI:** CalVer tags, Buildx, Docker Hub push (:latest + :calver), GH release. Mirrors sibling exactly.
- **Key seam:** `porra/scoring.py` is pure (no I/O) — trivially testable and mockable.

### 2026-06-26 — TVE 📺 Label Fix — Review Gate (APPROVED)

**Session:** TVE daily-update fix, kante-2 implementation  
**Status:** APPROVED — no required code changes

**Decisions reviewed:**
1. Same-day TLA-pair fallback — SAFE (unique pairing per UTC date in tournament)
2. Cache redesign (no-cache-on-all-fail, 30-min TTL for empty, 6h for populated) — SOUND
3. Residual timing issue (09:00 fires before RTVE publishes ~10:40) — RECOMMENDED: move `daily_update_hour` to 11:00

**Recommendation:** Move `DAILY_UPDATE_HOUR` to 11:00 (env-configurable, no code change needed). Owner discretionary.

**Test count:** 1629 passed (1618 baseline + 11 new from Kanté/Buffon)
- **Scoring:** Groups = 3pts exact position, 1pt off-by-one. Knockout = per-stage configurable points per correct qualifier (1/1/2/3/5). General = base_score + groups + all knockout stages.
- **WC2026:** 48 teams, 12 groups (A–L), 5 knockout rounds (Round of 32, R16, QF, SF, Final).
- **All legacy commands preserved.** Added `/ronda32`, `/semis`, `/final`. Renamed `/euroPorraDiaria` → `/porra`.
- **`/listaaciertos` now auto-detects caller** by Telegram username (no arg needed for own predictions).
- **Key learning:** User wants simplicity — YAML file editable live on host, no DB, no complex flows. The bot is a *reader* of pre-submitted predictions, not a prediction submission system.

### 2026-06-15 — Consolidation + Cross-Agent Learnings

- **Contract clarity enabled parallel work:** Public API signatures locked early (section 3 of decisions.md) allowed Buffon to write tests before Kanté finished implementation. Zero API mismatches.
- **Architecture decisions locked:** All meaningful choices documented in `.squad/decisions.md` (merged from 5 inbox docs). Future changes require team consensus.
- **Silent failures are dangerous:** Group normalization bug (API "Group A" → "GROUP_A") was invisible in unit tests (fixtures used canonical form) but caused all users to score 0 in production. Only Buffon's end-to-end testing caught it. Lesson: **mock third-party APIs with real response shapes**.
- **Module decoupling worked:** Pure scoring function + separate API client normalization layer + data-driven configuration = easy testing, high confidence, maintainability.
- **Team operated autonomously:** Pirlo specified contract → Maldini scaffolded → Kanté implemented → Buffon tested → bugs found and fixed pre-ship. No blocking; clear handoffs.
- **Lesson for future sessions:** Architectural contracts (defining public APIs, dependencies, error handling) are worth the upfront effort.

### 2026-06-19 — Per-User Tongo Config Design

- **Feature request:** Make `/tongo` SANCHEZ ratio and phrase pool configurable per user (identified by Telegram username).
- **Recommended approach:** Dedicated `data/TongoUsers.yml` file (Option B) over extending `predictions.yml` or in-band syntax. Clean separation, familiar pattern, operator-controlled commit/ignore.
- **Key design choice:** Extract selection logic into a pure `choose_tongo_response()` function — keeps handler thin, enables comprehensive unit testing.
- **Backward compat:** Unconfigured users must get exact current 1/3 SANCHEZ behavior. Missing config file = all global.
- **Learning:** Easter-egg config should not couple with core porra data. Separate files allow independent versioning decisions.

### 2026-06-26 — Architecture Review: WC2026 Best-Thirds Qualifying Scoring

**Role:** Lead reviewer for Kanté's best-thirds implementation.

**Key decisions locked:**
1. Scoring model coherence — all 7 cases correctly implement STRICT policy (non-qualifying exact-3rd → 0.0).
2. Provisional handling KEEP AS-IS — code already computes best-8-of-available once ≥9 thirds exist (better than doc describes).
3. Tiebreaker fallback acceptable — stable alphabetical (group+TLA) with WARNING for FIFA disciplinary/drawing-of-lots unavailability.
4. Backward-compat seam low-risk — all callers explicitly build and pass `qualifying_thirds`.

**Outcome:** APPROVE. Ready for Buffon QA gate.

**Buffon added 5 regression tests** (TestQualifyingThirdsCallerRegression) to guard against callers dropping `qualifying_thirds` param. Coverage gap closed.

### 2026-06-27 — Catch-Up Recovery + FINISHED-Eviction Fix — Design & Review Gates

**Session:** kante-4 (investigation) → pirlo-4 (design) → kante-5 (implementation) → pirlo-5 (review) → buffon-4 (QA)  
**Status:** GATES PASSED (Pirlo-5 APPROVE, Buffon-4 PASS WITH ADDED TESTS +4)

**Pirlo-4 Design Role:**
- Reviewed Kanté's investigation of three production symptoms (A: missed goals, B: Spain double-notify, C: 4-goal catch-up)
- Issued two key design decisions:
  1. **Goal recovery from thread (revises 2026-06-26 Decision 1):** Attempt to extract real goal events from Reddit match thread and emit proper per-goal notifications (scorer + "Ver gol" keyboard). Fallback to neutral "Me perdí N goles" only if thread unavailable or goals can't be matched. Rule: ALL-proper or ALL-neutral, never mixed.
  2. **Seed at 0-0 + FINISHED two-tick eviction:** Seed `live_scores` at 0-0 when kickoff fires (poll_kickoff_job). Evict FINISHED matches after first processed tick with no delta (two-tick minimum, prevents post-FT oscillation).

**Pirlo-5 Review (Implementation Gate):**
- Verified deduplication safety: first-seen recovery + concurrent thread job = no duplicate-announce window
- Verified two-tick eviction correct: first FINISHED (status update), second FINISHED (evict if no delta)
- Verified recovery fallback strict (ALL-proper or ALL-neutral)
- Verified hang safety bounded (~35s worst-case, acceptable for one-time event per match)
- Confirmed no regression with recap job or real in-play VAR

**Outcome:** APPROVE — Implementation is correct, matches design spec, well-tested.

---

### 2026-06-27 — Finished-Match Goal Loop Fix (Egypt-Iran) — Review Gate

**Session:** kante-3 implementation + pirlo-3 review  
**Status:** APPROVED — no required code changes

**Reviewed:** Kanté's `_match_is_over` wall-clock guard for stuck goal-polling loop.

**Key approvals:**
1. 4h threshold is correct (ET+penalties fit comfortably, margin safe)
2. Prune safety verified (no interaction with recap job)
3. Concurrency atomic (no interleaving on single-threaded asyncio)
4. Error path safe (date parse failure → match stays live)

**Verdict:** APPROVE — fix is correct, minimal, safe. Ship it.

### 2026-06-30 — LLM Chat Features Design (Picante + Revive Inactive)

**Session:** pirlo design/refinement for two new LLM-powered chat features  
**Status:** PROPOSED — awaiting David's decisions

**Key architectural decisions:**
1. New `src/worldcup_bot/chat/` package with clean separation: `listener.py` (Telegram), `picante.py` / `revive.py` (LLM orchestration), `buffer.py` / `state.py` (pure state).
2. **Privacy stance:** In-memory ring buffer ONLY for message text. NO message bodies persisted to disk. Only `last_seen`, `last_mentioned`, and cooldown metadata saved as JSON.
3. Both features independently toggleable via `CHAT_PICANTE_ENABLED` / `CHAT_REVIVE_ENABLED` env vars (default: False).
4. Reuses existing `AIClient` and `OPENAI_*` config — no new API credentials needed.
5. **Blocking infra requirement:** Bot privacy mode must be DISABLED in BotFather + bot re-added to group.
6. MessageHandler with `TEXT & ~COMMAND & GROUPS` filter, registered after existing CommandHandlers in `build_app()`.
7. Rate limiting: per-message probability + cooldown timestamp + daily counter (picante); periodic job + per-user mention cooldown + rotation (revive).

**Open decisions document:** `.squad/decisions/inbox/pirlo-llm-chat-features.md`

### 2026-06-30 — LLM Chat Features Implementation Review (APPROVED)

**Session:** Kanté implementation review (pirlo reviewer gate)  
**Status:** APPROVED — no blocking issues

**Reviewed files:** `chat/__init__.py`, `buffer.py`, `state.py`, `listener.py`, `picante.py`, `revive.py`, `config.py` additions, `__main__.py` wiring.

**Key verification points:**
1. All 10 checklist items PASS — filtering, rate limiting, privacy, candidate set, concurrency, resilience, zero-overhead when disabled, guardrails, mention construction, param fidelity.
2. Gate function purity enables comprehensive unit testing without mocks.
3. AIError/Exception catch-all in both features prevents LLM flakiness from crashing message processing.
4. Daily cap reset uses local timezone (`pytz.timezone(settings.timezone)`) for calendar day — correct for the Madrid-based group.
5. Revive candidate rotation wraps correctly with modulo; seeding at startup prevents day-1 spam.

**Learning:** Pure gate functions (probability, cooldown, daily_cap, min_buffer) separated from Telegram I/O orchestrators is an effective pattern — makes correctness obvious at review time and testable without PTB mocks.

### 2026-06-30 — LLM Chat Features Shipped (Picante + Revive)

**Event:** Successful team delivery of two LLM-driven group-chat features.

**Role:** Lead coordination + design gate + implementation review gate.

**Deliverables:**
- ✅ Design spec locked (13 open Qs → David's approval)
- ✅ Implementation review gate (Kanté) — APPROVED (all 10 checklist items PASS)
- ✅ QA gate (Buffon) — PASS WITH ADDED TESTS (+107 edge-case tests, 0 bugs)
- ✅ DevOps coordination (Maldini) — 12 env vars wired, README privacy-mode section

**Final status:** All 4 agent deliverables complete. Test suite: 1875 total (1768 + 107 new). Ready for deployment (if privacy mode disabled first).

**Key leadership decision locked:** Candidate set = PORRA PARTICIPANTS ONLY (override of initial "anyone who spoke" recommendation). Rationale: keeps porra-internal data off Revive targeting; participants are the intended audience.

**Blocking pre-deployment requirement documented:** BotFather privacy mode MUST be disabled. Failure mode obvious: features ship in code but produce zero group messages received because API gating blocks them. This requirement now lives in README with step-by-step setup instructions.
