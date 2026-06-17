# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **CI reference:** Workflow structure mirrors `../RedditSoccerGoals`.
- **Created:** 2026-06-15

## Key Implementation Patterns (Maldini DevOps)

### Phase 1 Scaffold (2026-06-15)
- `Dockerfile`: python:3.12-slim, non-root `app` user (uid 1000), two-stage pip install, `/app/data` writable.
- `docker-compose.yml` (prod): pulls `drdonoso/worldcup2026` from Docker Hub.
- `docker-compose.local.yml` (dev): local `build: .`.
- **Image name:** `drdonoso/worldcup2026`; **Docker Hub secrets:** `DOCKER_USERNAME` / `DOCKER_PASSWORD`.
- **Env contract:** `TELEGRAM_BOT_TOKEN`, `FOOTBALL_DATA_API_KEY`, `PREDICTIONS_PATH`, `COMPETITION_CODE`, `TIMEZONE`, `TELEGRAM_GROUP_ID`.

### Volume Mounting & Hot-Reload (2026-06-15)
- Directory mount (`./data:/app/data:ro`) prevents inode-swap breakage on file edits; hot-reload by mtime works reliably.
- Bind-mounts are read-only `:ro`; persistent state requires writable named volumes.

### Corporate SSL Remediation (2026-06-15)
- Container (python:3.12-slim) lacks corporate SSL-inspection CAs; container crash on startup without fix.
- Solution: Extract corporate CAs from Windows trust store (`Cert:\LocalMachine\Root`) → `certs/combined-ca-bundle.pem` (234 KB).
- Add to `docker-compose.local.yml`: volume mount `./certs:/certs:ro` + env `SSL_CERT_FILE=/certs/combined-ca-bundle.pem` + `REQUESTS_CA_BUNDLE=/certs/combined-ca-bundle.pem`.
- Prod (`docker-compose.yml`) needs no cert remediation (non-inspected networks).
- Pre-flight: kill lingering host Python pollers (Telegram returns HTTP 409 Conflict if two clients poll same token).

### ffmpeg for Goal-Clip Feature (2026-06-16)
- `RUN apt-get install -y --no-install-recommends ffmpeg` (early layer before COPY/pip for independent cache).
- Provides `ffmpeg` + `ffprobe` binaries to non-root `app` user.
- Temp video downloads use Python `tempfile` (default `/tmp`, world-writable) — no extra perms needed.

### Environment Variable Wiring (2026-06-16)
- OpenAI/LiteLLM: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `DAILY_UPDATE_HOUR` → optional pass-through style (`${VAR:-}`).
- Feature self-disables in-app when vars unset (Kanté owns logic in `config.py`).
- Both compose files use identical blocks; `.env.example` documents which vars are required vs optional.
- Pre-verified: `docker compose -f <file> config --quiet` → exit 0.

### Required Environment Variables (2026-06-16)
- `TELEGRAM_GROUP_ID` promoted to **REQUIRED**: dropped `:-}` empty-default so Compose emits warning if unset.
- `.env.example`: moved to own `# Required` block after `FOOTBALL_DATA_API_KEY`.
- Hard validation in Kanté's `load_settings()` fails fast at startup.

### Named-Volume Ownership Pattern (2026-06-16)
- **Issue:** Docker named volumes inherit ownership from the image's directory at mount path. Root-owned directories → root-owned volumes → Permission denied for non-root user writes.
- **Solution:** Create mount directories in Dockerfile with `chown -R app:app` **before** `USER app` line.
- **Pattern:** `RUN mkdir -p /app/data /app/state && chown -R app:app /app/data /app/state` (single layer for footprint).
- **Cannot be retroactively fixed:** Existing root-owned volumes must be manually removed (`docker volume rm <name>`) and recreated.
- **Ownership inheritance is locked at image build time** — permissions are baked into the image layer, applied when the volume is first mounted.

### Daily Update State Volume (2026-06-16)
- Phase 23: Added writable Docker named volume `bot_state:/app/state` for Kanté's porra-standings snapshot.
- `STATE_DIR=/app/state` env var; `Settings.state_dir` config field reads it.
- Both compose files: identical `volumes: { bot_state: }` declaration + bot service volume mount + environment var.
- `.env.example`: brief comment explaining STATE_DIR is compose-managed (not user-configurable secret).

## Key Learnings

- **Dependency precision:** Wrong package names or version constraints block entire build. Check before commit.
- **Infrastructure as contract:** docker-compose.yml and Dockerfile are executable spec of deployment. Prod (pull) vs dev (build) consistency matters.
- **Volume persistence:** Named volumes survive `docker compose down && up`; bind-mounts do not (require explicit -v flag to remove). Use named volumes for persistent state.
- **Non-root user permissions:** Always create directories in Dockerfile with correct ownership before `USER` line. Retroactive chmod on volumes doesn't work.
- **Docker caching:** Stable layers (system deps like ffmpeg) go early; frequently-changing layers (Python deps/code) go late. Independent caching of system deps.
- **Telegram polling conflict:** Only one client per token; kill lingering host pollers before container startup.

## Learnings

### CI Trigger Optimization (2026-06-17)
- Added `paths-ignore` filter to `docker-deploy.yml` workflow `push` trigger: `.squad/**` and `CHANGELOG.md` no longer trigger build+release.
- Rationale: Team memory commits (Scribe) and auto-changelog commits are infrastructure-only, never affect bot image; skipping them reduces wasted Docker Hub builds and empty GitHub Releases.
- Complementary to existing `[skip ci]` on auto-changelog commits (belt-and-suspenders pattern for defense-in-depth).
- GitHub Actions runs workflow only if at least one changed file is NOT in `paths-ignore` — pure `.squad/**` or `CHANGELOG.md` pushes are skipped entirely.
- Code/config changes (src, tests, Dockerfile, compose, workflow itself, etc.) still trigger normally because they fall outside the ignore list.

### Auto-Changelog Mechanism (2026-06-17)
- Commit-derived notes via `git log "$RANGE" --no-merges --pretty=format:'%s'`; range from previous release tag to HEAD (`git describe --tags --abbrev=0`).
- Internal-commit filtering: drop `.squad:` (Scribe memory commits), `docs: update changelog` (auto-commit loop prevention), `Merge ` (merge commits), `chore:` (non-user-facing). Pattern `'^\.squad:'` matches literal leading dot via BRE `\.`.
- Conventional-commit prefix stripping with `sed -E 's/^(feat|fix|perf|refactor|docs)(\([^)]+\))?: //'` for readability; plain imperative subjects pass through unchanged.
- Marker-based insertion: `sed -i "/<!-- releases -->/r new_entry.md"` reliably inserts newest entry first after the `<!-- releases -->` marker, avoids shell-quoting pain of awk `-v` with multiline values.
- Loop prevention: `[skip ci]` in the auto-commit message prevents GitHub Actions from re-triggering on the changelog push.
- Notes-file vs generate-notes fallback: when all commits are internal, fallback to `--generate-notes` so the release still has content.
- Pipefail safety: `{ pipeline } > file || true` wraps the grep/sed chain — `set -eo pipefail` (GitHub Actions default) would abort if any `grep -v` sees empty input; the `|| true` absorbs the non-zero exit code.
- Race-condition resilience: non-fast-forward push retried once with `git pull --rebase --autostash`; second failure emits a warning and exits 0 rather than failing the entire deploy workflow.

## Session Summary (2026-06-16T13:46:51Z)

Maldini's daily-update rework (Phases 23–24) verified live on Telegram test group (message #446). All work integrated with Kanté's max_completion_tokens fix and HTML snapshot feature. Docker ownership fix applied; state volume working correctly. Code pending user approval for commit.

### Body-Bullet Changelog Extraction (2026-06-17)
- Replaced the `git log --pretty='%s'` + grep/sed chain in the "Generate release notes from commits" step with a `python3 - <<'PYEOF'` quoted heredoc.
- Logic: enumerate SHAs via `--format=%H`; for each, parse full `%B` message; extract bullet lines (`- ` prefix after optional indent) from the body; fold wrapped continuation lines (2+ leading spaces) into one line; stop at `Co-authored-by:` trailer; skip internal commits (`.squad:`, `chore:`, `docs: update changelog`, `merge `); fall back to `- {subject}` if no bullets found.
- Prefixes (`feat:`, `fix:`, etc.) are kept verbatim in bullets — no stripping.
- Quoted heredoc (`<<'PYEOF'`) prevents shell from expanding `$` or backticks in the Python source.
- Verified locally: range `20260617.04^..48edda9` (commit 48edda9) → 4 elaborate single-line bullets covering goal detection, clip flow, match-finish, and /estadisticas. YAML: `python -c "import yaml; yaml.safe_load(...)"` → exit 0.

## Session Summary (2026-06-17 06:34:32Z — Scribe)

Auto-changelog mechanism (Decision #36) merged into decisions ledger. Inbox file deleted. Feature verified live: CI run 27670280717 succeeded, GitHub Release 20260617 created, CHANGELOG.md auto-updated via commit 59cbad3 with no loop. Gotcha recorded: literal `[skip ci]` token in commit BODY was skipped; workaround = amend + reword. Decisions.md flagged 104KB → manual compaction urgent when entries age past 7 days.

