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
