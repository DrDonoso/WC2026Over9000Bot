# Pirlo — Historical Archive

## Learnings (Archived 2026-07-01)

### 2026-06-15 — Initial Architecture Decision

- **Package:** `worldcup_bot`, image `drdonoso/worldcup2026`, entry `python -m worldcup_bot`
- **Layout:** src-layout mirroring RedditSoccerGoals. Modules: `bot/`, `api/`, `porra/`, `storage/`, `config.py`.
- **Deps:** httpx, aiosqlite, python-telegram-bot (same stack as sibling repo minus yt-dlp).
- **football-data.org:** Free tier, 10 req/min, competition code `WC` (id 2000). Poll results every 2 min during matches, daily fixture sync.
- **Scoring default:** 3 exact / 1 outcome / 0 wrong. Locks at kickoff.
- **Env vars:** TELEGRAM_BOT_TOKEN, FOOTBALL_DATA_API_KEY, TELEGRAM_GROUP_ID, ADMIN_TELEGRAM_IDS, POLL_INTERVAL_SECONDS, FIXTURE_SYNC_HOUR_UTC, DB_PATH.
- **CI:** CalVer tags, Buildx, Docker Hub push (:latest + :calver), GH release. Mirrors sibling exactly.
- **Key seam:** `porra/scoring.py` is pure (no I/O) — trivially testable and mockable.

### 2026-06-19 — Per-User Tongo Config Design

- **Feature request:** Make `/tongo` SANCHEZ ratio and phrase pool configurable per user (identified by Telegram username).
- **Recommended approach:** Dedicated `data/TongoUsers.yml` file (Option B) over extending `predictions.yml` or in-band syntax. Clean separation, familiar pattern, operator-controlled commit/ignore.
- **Key design choice:** Extract selection logic into a pure `choose_tongo_response()` function — keeps handler thin, enables comprehensive unit testing.
- **Backward compat:** Unconfigured users must get exact current 1/3 SANCHEZ behavior. Missing config file = all global.
- **Learning:** Easter-egg config should not couple with core porra data. Separate files allow independent versioning decisions.

### 2026-06-15 — Consolidation + Cross-Agent Learnings

- **Contract clarity enabled parallel work:** Public API signatures locked early (section 3 of decisions.md) allowed Buffon to write tests before Kanté finished implementation. Zero API mismatches.
- **Architecture decisions locked:** All meaningful choices documented in `.squad/decisions.md` (merged from 5 inbox docs). Future changes require team consensus.
- **Silent failures are dangerous:** Group normalization bug (API "Group A" → "GROUP_A") was invisible in unit tests (fixtures used canonical form) but caused all users to score 0 in production. Only Buffon's end-to-end testing caught it. Lesson: **mock third-party APIs with real response shapes**.
- **Module decoupling worked:** Pure scoring function + separate API client normalization layer + data-driven configuration = easy testing, high confidence, maintainability.
- **Team operated autonomously:** Pirlo specified contract → Maldini scaffolded → Kanté implemented → Buffon tested → bugs found and fixed pre-ship. No blocking; clear handoffs.
- **Lesson for future sessions:** Architectural contracts (defining public APIs, dependencies, error handling) are worth the upfront effort.
