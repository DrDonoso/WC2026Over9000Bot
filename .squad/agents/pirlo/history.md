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

### 2026-06-15 — REVISED Architecture (Migration from Legacy Euro 2024 Bot)

- **BREAKING CHANGE:** Porra model is NOT exact-score. It is group-standings predictions (top-3 per group) + knockout qualifiers (which teams advance). Migrated directly from legacy Euro 2024 monolithic bot.
- **No SQLite.** Predictions stored in a mounted YAML file (`/app/data/predictions.yml`). No database needed — results fetched live from API, scored on-the-fly.
- **YAML keyed by Telegram @username** (user's explicit requirement). Hot-reloaded on each command.
- **Sync requests over async httpx.** Simpler migration, fewer bugs. python-telegram-bot handles its own async; API calls are brief sync blocks.
- **Deps changed to:** python-telegram-bot, requests, pyyaml, flag, pytz. Dropped httpx, aiosqlite.
- **Removed:** `storage/` module, `bot/conversations.py`, polling loop. Added: `porra/predictions.py` (YAML loader), `api/cache.py` (TTL cache), `data/stages.py` (config-driven stages).
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
