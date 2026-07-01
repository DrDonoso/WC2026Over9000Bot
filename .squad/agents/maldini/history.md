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



Earlier sessions (2026-06-15 through 2026-06-26): Phase 1 scaffold, SSL remediation, ffmpeg, named-volume ownership, auto-changelog, tongo env wiring, TVE feature, clip disk investigation. See `history-archive.md`.



