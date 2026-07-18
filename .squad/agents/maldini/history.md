# Maldini — DevOps

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Docker, Python, GitHub Actions | **Current:** Docker image `drdonoso/worldcup2026`

## Current Sessions (2026-06-30)

### ✅ Chat Features Environment Wiring (2026-06-30)
Wired 12 new environment variables (CHAT_PICANTE_ENABLED, CHAT_REVIVE_ENABLED, PICANTE_PROBABILITY, PICANTE_COOLDOWN_SECONDS, REVIVE_CHECK_INTERVAL_SECONDS, etc.) across `.env.example`, `docker-compose.yml`, `docker-compose.local.yml`. Added privacy-mode docs to README.md. Revive quiet-hours + jitter (REVIVE_QUIET_START_HOUR, REVIVE_QUIET_END_HOUR, REVIVE_JITTER_SECONDS) wired. Both compose files validated (`docker compose config --quiet` ✓). Status: Complete.

### ✅ Revive Quiet Hours + Jitter (SHIPPED, commit 31f1a89)
Three new REVIVE env vars: REVIVE_JITTER_SECONDS (±45 min randomization), REVIVE_QUIET_START_HOUR (23), REVIVE_QUIET_END_HOUR (6). Jitter prevents thundering herd; quiet window respects TIMEZONE. Self-rescheduling loop, at most 1 pending job. Updated `docker-compose.yml`, `docker-compose.local.yml`, `.env.example`, README.md.

---

## Key Infrastructure Patterns

- **Docker:** python:3.12-slim, non-root app user, two-stage pip install. Image: `drdonoso/worldcup2026`
- **Volume management:** Named volumes for persistent state; read-only bind-mounts for data. Named-volume ownership set in Dockerfile before `USER` directive.
- **Environment:** All optional vars use `${VAR:-default}` pattern; both compose files identical (prod/dev parity).
- **Telegram:** Privacy mode MUST be disabled for chat features. Bot removed + re-added after setting.
- **CI:** `paths-ignore` filter skips `.squad/**` and `CHANGELOG.md` (no bot image impact).
- **Package data (assets):** Use `[tool.setuptools.package-data]` + `include-package-data = true` to bundle non-Python files (images, markdown) in wheels. Verified with `pip wheel . --no-deps` + zip inspection. `COPY src/` in Dockerfile is sufficient; pip unpacks the assets at install time.

---

## Learnings

### Crown Asset Packaging (2026-07-01)
- **Issue:** `pip install --no-deps .` with default setuptools.packages.find does NOT include non-Python files (e.g., crown.png) in the installed package/wheel. Podium feature would silently fail in production.
- **Fix:** Added `[tool.setuptools]` section with `include-package-data = true` + `[tool.setuptools.package-data]` block specifying `worldcup_bot = ["assets/*.png", "assets/*.md"]`.
- **Verification:** Built wheel with `pip wheel . --no-deps`, inspected .whl (zip format) contents: ✓ `worldcup_bot/assets/crown.png` and `worldcup_bot/assets/ATTRIBUTION.md` both present.
- **Attribution:** Created `src/worldcup_bot/assets/ATTRIBUTION.md` crediting crown.png to Noto Emoji (Google, Apache 2.0), U+1F451 glyph.
- **Dockerfile:** No changes needed. `COPY src/ ./src/` + `pip install .` now includes assets via setuptools config.



### ✅ Merge feat/final-weekend → main (2026-07-17)
- **Branch merged:** `feat/final-weekend` (5 commits: THIRD_PLACE scoring + Final ceremony + tests + docs)
- **Merge type:** `--no-ff` merge commit (main had advanced 1 commit beyond branch point: `0435a2c` docs CHANGELOG)
- **New main HEAD:** `a73f12e` — _Merge feat/final-weekend: 3.o/4.o puesto + ceremonia final_
- **Push:** `git push origin main` — accepted, no force needed
- **CI triggered:** Run #29576019606 "Build and Deploy Docker Image" — `in_progress` at push time
  - URL: https://github.com/DrDonoso/WC2026Over9000Bot/actions/runs/29576019606
- **Auth:** DrDonoso (active), `gh auth status` confirmed before push.
- **Feature branch:** `feat/final-weekend` left intact (not deleted).

### ✅ Merge feat/rich-apex-death → main (2026-07-17)
- **Branch:** `feat/rich-apex-death` (4 commits: Apex July-20 + Death July-21 rich image; approved by Pirlo & Buffon; 2753 tests green)
- **Merge type:** Fast-forward locally, then **rebase** (Option B, David approved) — origin/main had received `159e65a` (bot CHANGELOG commit) during the window; rebased cleanly, no conflicts.
- **Push range:** `159e65a..cba7fae  main -> main` — accepted, no force needed.
- **New origin/main HEAD:** `cba7fae` (rebased tip of `3a58983`)
- **CI triggered:** Run #29584668354 "Build and Deploy Docker Image" — **in_progress**
  - URL: https://github.com/DrDonoso/WC2026Over9000Bot/actions/runs/29584668354
  - Awaiting completion; if successful, feature live in production
- **Feature branch `feat/rich-apex-death`:** left intact (not deleted).

Earlier sessions (2026-06-15 through 2026-06-26): Phase 1 scaffold, SSL remediation, ffmpeg, named-volume ownership, auto-changelog, tongo env wiring, TVE feature, clip disk investigation. See `history-archive.md`.

### ✅ Merge feat/elecciones-nudge → main (2026-07-17)
- **Branch merged:** `feat/elecciones-nudge` (3 commits: elecciones.py + handlers.py + test_elecciones.py; approved by Pirlo & Buffon)
- **Rebase needed:** origin/main had one bot CHANGELOG commit (`367cb4e`) ahead of branch — rebased cleanly; unstaged `.squad/agents/kante/history.md` required `git stash`/`pop` to clear the working tree before rebase.
- **Merge type:** Fast-forward (`367cb4e..7f444b6 main -> main`); no force, no conflicts.
- **New origin/main HEAD:** `7f444b6` — _refactor(elecciones): drop unused participants param from build_nudge_text_
- **CI triggered:** Run #29652587787 "Build and Deploy Docker Image" — `in_progress` at push time
  - URL: https://github.com/DrDonoso/WC2026Over9000Bot/actions/runs/29652587787



