# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **CI reference:** Workflow structure mirrors `../RedditSoccerGoals`.
- **Created:** 2026-06-15

### Phase 2 Wiring (2026-06-30) — Chat Features Environment

**Task:** Wire 12 new environment variables across all surfaces for LLM-driven chat features (Picante + Revive).

**Deliverables:**
- `.env.example` — 12 new env vars with defaults (both features disabled by default)
- `docker-compose.yml` — 12 new env vars with `${VAR:-default}` pattern
- `docker-compose.local.yml` — identical 12 env vars
- `README.md` — new "Telegram privacy mode (required for chat features)" section

**Key decision:** Privacy mode MUST be disabled in BotFather (`/setprivacy` → Disable). Bot must be removed from group and re-added after disabling (setting only applies to new memberships).

**Validation:** Both compose files validate with `docker compose config --quiet` → exit 0.

**Status:** Complete and shipping (2026-06-30).

---

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

### Tongo Phrases Optional Environment Variable (2026-06-19)
- Wired `TONGO_PHRASES_PATH` optional env var for Kanté's new `/tongo` customizable phrases file (`data/TongoPhrases.txt`).
- **Changes:** (1) `docker-compose.yml`: added `TONGO_PHRASES_PATH: "${TONGO_PHRASES_PATH:-/app/data/TongoPhrases.txt}"` with Spanish comment, right after `PREDICTIONS_PATH` block (line ~15). (2) `docker-compose.local.yml`: identical entry. (3) `.env.example`: added commented example with default path and description.
- **No volume changes:** `data/` directory already mounted read-only at `/app/data:ro` in both compose files; no new mount needed.
- **Gitignore:** `data/TongoPhrases.txt` is **committed** (not ignored). Verified via `git check-ignore` exit 1 (not matching any ignore rules). File follows pattern of other committed data files (e.g., `predictions.example.yml`).
- **Parity with PREDICTIONS_PATH:** Same env-var convention (`${VAR:-default}`) for consistency across compose files and local/prod symmetry.

### Tongo Users Per-Person Config Optional Environment Variable (2026-06-19)
- Wired `TONGO_USERS_PATH` optional env var for Kanté's new per-user `/tongo` config file (`data/TongoUsers.yml`).
- **Changes:** (1) `docker-compose.yml`: added `TONGO_USERS_PATH: "${TONGO_USERS_PATH:-/app/data/TongoUsers.yml}"` with Spanish comment, right after `TONGO_PHRASES_PATH` block. (2) `docker-compose.local.yml`: identical entry. (3) `.env.example`: added commented example with default path and description (sanchez_ratio + custom phrases per user).
- **No volume changes:** `data/` directory already mounted read-only at `/app/data:ro` in both compose files; no new mount needed.
- **Gitignore:** `data/TongoUsers.yml` is **committable** (not ignored). Verified via `git check-ignore` exit 1 (not matching any ignore rules).
- **Parity with PREDICTIONS_PATH and TONGO_PHRASES_PATH:** Same env-var convention (`${VAR:-default}`) for consistency.

**Archived to history-archive.md:** Session summaries from 2026-06-16 through 2026-06-17 (4 sessions covering daily-update rework, changelog extraction, rich image feature, and gitignore patterns).

## Learnings

### /tongo YAML Merge — Single-File Consolidation (2026-06-19)
- Kanté consolidated `data/TongoPhrases.txt` (global phrases) + `data/TongoUsers.yml` (per-user overrides) into ONE runtime file `data/TongoUsers.yml` with two root sections: `phrases:` (global list) + `users:` (per-person dict).
- Two committed templates introduced: `data/TongoUsers.template.yml` and `data/predictions.template.yml` — users copy templates and hand-edit with real usernames/phrases.
- **Maldini infra changes:** (1) `.gitignore`: added `data/TongoUsers.yml` runtime-file rule + comment. (2) `docker-compose.yml` + `docker-compose.local.yml`: **removed** `TONGO_PHRASES_PATH` env-var block (2-line comment + var line); updated `TONGO_USERS_PATH` Spanish comment to "Config de /tongo: frases globales + overrides por persona...". (3) `.env.example`: removed `TONGO_PHRASES_PATH=...` line; updated `TONGO_USERS_PATH` comment to document the merged structure. (4) **Both compose files validated cleanly** via `docker compose config -q` exit 0.
- **No template negation needed:** The merged file pattern `data/TongoUsers.yml` doesn't accidentally catch the committed templates (`data/TongoUsers.template.yml`, `data/predictions.template.yml`); they don't match the runtime path rule.
- **Parity:** Same image everywhere (prod/local); only env var binding differs. Runtime file must NOT be committed (private usernames).

### TVE_ENABLED Optional Environment Variable (2026-06-22)
- Wired `TVE_ENABLED` optional env var (default 1) to toggle Kanté's new "📺 partido en TVE" feature (RTVE-API lookup for match broadcasts on TVE/La1/Teledeporte).
- **Changes:** (1) `docker-compose.yml`: added `TVE_ENABLED: "${TVE_ENABLED:-1}"` with Spanish comment "Marca con 📺 los partidos que da TVE (vía API de RTVE). '0' para desactivar.", right after `BELOVED_TEAMS` block (line ~43). (2) `docker-compose.local.yml`: identical entry. (3) `.env.example`: added commented line with description ("Mark matches that are broadcast on TVE... Set to 0 to disable if the undocumented RTVE API breaks mid-tournament"). (4) **Both compose files validated cleanly** via `docker compose config -q` exit 0.
- **No volume changes:** Feature uses existing data/code bindings. Runtime toggle allows quick disabling of RTVE lookup without code change if the undocumented API breaks during tournament.
- **Parity:** Same optional env-var pattern (`${VAR:-default}`) as PREDICTIONS_PATH, TONGO_USERS_PATH, BELOVED_TEAMS, etc.

### Clip Disk Investigation (2026-06-26)
- **Issue:** Yesterday matches produced some goals with no keyboard and missing notifications. Volume had ~4GB free. Investigation: is disk-full the cause?
- **Storage location:** Clips stored at `{STATE_DIR}/clips/` (named volume `bot_state:/app/state` in both compose files). Per-goal metadata in `{STATE_DIR}/goal_clips.json`.
- **Retention:** `prune_old_entries()` called every 45s in `poll_goal_clips_job`, deletes entries + files older than **7 days**. **No total-size cap** — only age-based cleanup today.
- **Clips NOT deleted on send:** `cmd_ver_gol_callback()` keeps clips persistent so multiple users can tap the same button. Unclicked clips accumulate until pruning.
- **Disk pressure estimate:** 80–110 clips stored at any time (7-day retention) = 800 MB–3.3 GB. A busy day adds 240–320 MB. **4GB free is sufficient** for normal ops.
- **Conclusion:** Disk-full unlikely direct cause, but possible if `prune_old_entries` silently failed (corrupt JSON, permissions). More likely: clip finder miss, download failure, or slow poll job. Recommended: add volume healthcheck + soft-limit LRU eviction.
- **Deliverable:** `.squad/decisions/inbox/maldini-clip-disk-investigation-2026-06-26.md` (full analysis + infra recommendations for healthcheck, LRU, Kanté coordination).

### Group Chat Features — Environment Wiring & Privacy-Mode Docs (2026-06-30)
- **Privacy-mode requirement:** For picante (spicy random replies) + revive (inactive-user engagement) features to work, bot must receive ALL group messages, not just `/commands` + replies. Telegram privacy mode must be **DISABLED** in BotFather (`/setprivacy` → **Disable**) and bot must be **removed + re-added** to the group (privacy change only applies to new memberships). Documented in README.md under new subsection "### Telegram privacy mode (required for chat features)" with clear pre-deployment step.
- **Environment wiring:** Added 12 new env vars to `.env.example` (documented with comments), `docker-compose.yml`, and `docker-compose.local.yml`:
  - `CHAT_PICANTE_ENABLED=0` (master toggle; default OFF)
  - `CHAT_REVIVE_ENABLED=0` (master toggle; default OFF)
  - `CHAT_BUFFER_SIZE=30` (recent messages for AI context)
  - `PICANTE_PROBABILITY=0.20` (~1 in 5 eligible messages)
  - `PICANTE_COOLDOWN_SECONDS=300` (min secs between spicy replies)
  - `PICANTE_MAX_PER_DAY=30` (hard daily cap)
  - `PICANTE_MIN_BUFFER=5` (buffer threshold)
  - `PICANTE_TEMPERATURE=0.9` (LLM temperature)
  - `REVIVE_CHECK_INTERVAL_SECONDS=14400` (4-hour checks)
  - `REVIVE_INACTIVE_DAYS=3` (inactivity threshold)
  - `REVIVE_MENTION_COOLDOWN_DAYS=2` (per-user cooldown)
  - `REVIVE_TEMPERATURE=0.8` (LLM temperature)
- **Notes in `.env.example`:** Added comment noting both features require OPENAI_* vars (OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL) to be fully set.
- **Compose style:** Matched existing pattern (`${VAR:-default}`) for consistency; added comment block before the new vars explaining dependency on OPENAI_* and privacy mode.
- **Validation:** Both `docker-compose.yml` and `docker-compose.local.yml` validated cleanly with `docker compose config --quiet`.



