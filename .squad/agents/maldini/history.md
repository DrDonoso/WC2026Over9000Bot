# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **CI reference:** Workflow structure mirrors `../RedditSoccerGoals`.
- **Created:** 2026-06-15

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-06-15 — Real participant predictions loaded (group stage)

- `data/predictions.yml` now holds the 12 real participants (group stage only, knockout empty lists).
- Participant order in file: crispavon, dsantosmerino, vansid, patri, javipege, pilarfreixas, amalia, vicsaez, mariatarrago, josunefon, drdonoso, sialau.
- All `display_name` values are `@handle` placeholders; owner will fill real names later.
- All knockout stages are explicit empty lists `[]` (bare keys parse as null and fail validation).
- Loader verification one-liner (run from repo root with venv):
  ```
  .venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from worldcup_bot.porra.predictions import load; d=load('data/predictions.yml'); ps=d['participants']; print('participants loaded:', len(ps)); [print(u, 'thirds=', sum(1 for g in v['groups'].values() if g[2]!='**')) for u,v in ps.items()]"
  ```
  Expected output: `participants loaded: 12` and every user `thirds= 8`.

### 2026-06-15 — Real WC2026 groups seeded; truststore added

- `predictions.example.yml` and `data/predictions.yml` rewritten with verified football-data.org TLA codes for all 12 WC2026 groups (A–L). Participants `drdonoso`, `vicsaez`, `cris_username` now use real teams; `drdonoso` picks match current standings order to guarantee non-zero scores on live runs. `cris_username` demonstrates `"**"` wildcard (groups H, J).
- `src/worldcup_bot/data/tla_map.py` extended: added `CPV` (Cape Verde, CAF), `URY` (Uruguay alias, football-data.org API code), `CUW` (Curaçao, CONCACAF) — all three appear in the real WC2026 groups but were missing from the validator.
- `pyproject.toml`: added `truststore>=0.9` to `dependencies` so the bot uses the OS/container trust store for corporate SSL inspection.

### 2026-06-15 — Phase 1 scaffold complete
- `pyproject.toml` — package name `worldcup_bot`, setuptools src-layout, python>=3.12.
- `Dockerfile` — python:3.12-slim, non-root `app` user (uid/gid 1000), cache-friendly two-stage pip install (placeholder `__init__.py` trick), `/app/data` writable, entrypoint `python -m worldcup_bot`.
- `docker-compose.yml` — production: pulls `drdonoso/worldcup2026`, mounts `./data/predictions.yml:/app/data/predictions.yml:ro`.
- `docker-compose.local.yml` — dev: `build: .` + same env/volume.
- `.env.example` — committed, no real secrets; `.env` — git-ignored, empty placeholders for user to fill.
- `predictions.example.yml` — committed template; `data/predictions.yml` — git-ignored (real data).
- `data/.gitkeep` — keeps `data/` tracked in git.
- `.github/workflows/docker-deploy.yml` — push to main → CalVer tag → Buildx → Docker Hub push → GitHub Release.

**Image name:** `drdonoso/worldcup2026`

**Docker Hub secret names:** `DOCKER_USERNAME` / `DOCKER_PASSWORD` (same as sibling RedditSoccerGoals repo).

**Env var contract (final):** `TELEGRAM_BOT_TOKEN`, `FOOTBALL_DATA_API_KEY`, `PREDICTIONS_PATH`, `COMPETITION_CODE`, `TIMEZONE`, `TELEGRAM_GROUP_ID`.

### 2026-06-15 — Consolidation + Cross-Agent Learnings

- **Dependency precision matters:** Wrong package name in pyproject.toml (`flag` instead of `emoji-country-flag`) blocks entire build. Version constraints are equally critical — checked before commit.
- **Infrastructure as contract:** docker-compose.yml and Dockerfile serve as executable specification of deployment. Both prod (pull from Docker Hub) and dev (local build) configs ensure consistency.
- **Scaffold timing:** Phase 1 (Maldini infra) completed before Phase 2 (Kanté implementation) allowed parallel work with no blocking. Clear hand-off: "code goes in src/worldcup_bot/" + "entry is python -m worldcup_bot".
- **Predictions example = gold standard:** Regenerating `predictions.example.yml` with real WC2026 groups and valid TLAs meant the example file was actually runnable and could serve as a test fixture.
- **Lesson for future sessions:** Scaffolding agents should define clear boundaries (what goes where, what format) so implementation agents can proceed autonomously.

### 2026-06-15 — Directory mount + README (server workflow)

- Both `docker-compose.yml` and `docker-compose.local.yml`: predictions volume changed from single-file mount (`./data/predictions.yml:/app/data/predictions.yml:ro`) to directory mount (`./data:/app/data:ro`) — prevents inode-swap breakage when editors replace the file; hot-reload by mtime now works reliably.
- `README.md` added to repo root: covers quick-start (local), server deploy workflow (hot-reload predictions without restart, image update via `docker compose pull`), bot commands table, predictions YAML format, and SSL-inspection note.

### 2026-06-15 — Local stack brought up; corporate SSL remediation

**Bring-up command:**
```powershell
docker compose -f docker-compose.local.yml up -d --build
```
Run from repo root. On first run it builds the image locally (uses two-stage Dockerfile cache: deps layer cached until pyproject.toml changes, code layer is small rebuild). Subsequent runs without `--build` reuse the existing image.

**Pre-flight check — stop lingering host pollers:**
```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Select ProcessId,CommandLine
Stop-Process -Id <PID> -Force   # for each worldcup_bot process found
```
The bot uses long-polling (getUpdates). If a host Python process is also polling the same token, Telegram returns HTTP 409 Conflict and the container crashes immediately. Always kill host pollers before `up -d`.

**SSL remediation needed? YES — corporate SSL-inspecting network.**
The container (python:3.12-slim) does not have the corporate SSL-inspection CAs, so the first `up -d` crashed with:
```
httpcore.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain
```
Note: `truststore.inject_into_ssl()` does NOT help inside the container — it reads the OS (Linux) trust store, which has no corporate CAs.

**Fix applied:**
1. Identified the corporate SSL-inspection CAs in `Cert:\LocalMachine\Root` (the proxy's root + intermediate CAs).
2. Exported them to `certs/corp-ca-bundle.pem` via PowerShell (`Export-Certificate` + Base64).
3. Extracted the container's system CA bundle: `docker run --rm --entrypoint sh drdonoso/worldcup2026 -c "cat /etc/ssl/certs/ca-certificates.crt"` → `certs/system-ca-bundle.pem`.
4. Concatenated both into `certs/combined-ca-bundle.pem` (234 KB).
5. Added to `docker-compose.local.yml`: volume mount `./certs:/certs:ro` and env vars `SSL_CERT_FILE=/certs/combined-ca-bundle.pem` + `REQUESTS_CA_BUNDLE=/certs/combined-ca-bundle.pem`.
6. Added `certs/` to `.gitignore` (corporate certs must never be committed).
7. Cleaned up intermediate files, keeping only `certs/combined-ca-bundle.pem`.

**Verification:**
- `docker compose -f docker-compose.local.yml ps` → STATUS `Up` (not Restarting)
- `docker inspect ... --format "RestartCount={{.RestartCount}}"` → `0`
- Container logs showed: `[INFO] __main__: Starting WorldCup2026 bot | competition=WC | predictions=/app/data/predictions.yml` followed by `[INFO] telegram.ext.Application: Application started` and periodic `getUpdates` calls returning `HTTP/1.1 200 OK`.
- `docker exec ... python -c "from worldcup_bot.porra.predictions import load; ..."` → `participants loaded: 12`

**On a non-inspected network (CI, production server):** no cert remediation needed; `docker-compose.yml` (prod) has no `certs/` mount and no `SSL_CERT_FILE` override — it works as-is.

### 2026-06-16 — ffmpeg added to image for goal-clip ("Ver gol") feature

## Learnings

### 2026-06-16T12:24+02:00 — TELEGRAM_GROUP_ID promoted to REQUIRED

- `TELEGRAM_GROUP_ID` promoted to REQUIRED in both `docker-compose.yml` and `docker-compose.local.yml`: dropped `:-}` empty-default so Compose passes through whatever is set (and emits a warning if unset — desired signal). Comment updated to "Telegram group/channel ID for live goal notifications (REQUIRED)".
- `.env.example`: moved `TELEGRAM_GROUP_ID` out of the `# Optional — Override defaults` block, uncommented it, and placed it in its own `# Required` block after `FOOTBALL_DATA_API_KEY`. Hard validation lives in Kanté's `load_settings()`.
- `.env` (git-ignored, user's real values) was NOT modified.
- Rationale: the live goal notifier depends on the group ID being present; the app will fail fast at startup without it (Kanté's responsibility). Compose-level signal (warning on unset var) reinforces the contract for operators.

- `apt-get install -y --no-install-recommends ffmpeg` added as first `RUN` layer in Dockerfile (right after `FROM python:3.12-slim AS base`, before user creation). This gives both `ffmpeg` and `ffprobe` binaries to the `app` non-root user.
- Layer is placed early (before any `COPY`/pip steps) so it's cached independently — system deps rarely change, Python deps change often.
- yt-dlp comes via `pyproject.toml` (Kanté's responsibility); it is NOT installed via apt or a separate pip call in the Dockerfile.
- Temporary video downloads use Python's `tempfile` (default `/tmp`). `/tmp` is world-writable in debian-slim by default — no extra `chmod` or dedicated mount needed for the non-root `app` user.
- docker-compose files unchanged; no new mounts or env vars required for this feature.
- Verified build (`docker compose -f docker-compose.local.yml build`) and binary presence: `ffmpeg version 7.1.4-0+deb13u1`, `ffprobe version 7.1.4-0+deb13u1`. yt-dlp not yet present (Kanté's pyproject change pending).

