# Maldini History Archive

**Archived:** 2026-06-19T10:43:59Z  
**Sessions:** 4 old session summaries (2026-06-16 through 2026-06-17)

---

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

## Session Summary (2026-06-17 13:55:52Z — Maldini)

### Rich Image Daily Feature — Environment Variable Wiring

Wired up five new env vars for the daily image-generation job (Kanté's feature):
- `OPENAI_IMAGE_MODEL` (default `gpt-image-2`)
- `OPENAI_IMAGE_API_KEY` (optional; falls back to `OPENAI_API_KEY`)
- `OPENAI_IMAGE_BASE_URL` (optional; falls back to `OPENAI_BASE_URL`)
- `RICH_IMAGE_HOUR` (default `11`, 24h local time)
- `RICH_IMAGE_CHAT_ID` (optional; testing value `3041850`)

**Changes:**
1. `docker-compose.yml` (prod): Added 5 vars to `worldcup-bot` service `environment:` block with defaults, right after `DAILY_UPDATE_HOUR`.
2. `docker-compose.local.yml` (dev): Same 5 vars + existing SSL-cert block.
3. `.env.example`: Added explanatory comments for all 5 vars; notes that `OPENAI_IMAGE_API_KEY` and `OPENAI_IMAGE_BASE_URL` are optional overrides.

**No new volumes:** Image written to existing `bot_state:/app/state` named volume (already mounted); base image at `./data/rich/rich_original.jpg` (already mounted read-only).

**Validation:** Both compose files parse cleanly (`docker compose config -q` → exit 0).

**Next:** Kanté adds logic to `config.py` to read these vars with safe defaults.

## Session Summary (2026-06-17 15:07:58Z — Maldini)

### Rich Image Destination Consolidation — Remove RICH_IMAGE_CHAT_ID

Image destination now consolidated to existing `TELEGRAM_GROUP_ID` (the shared group). Removed `RICH_IMAGE_CHAT_ID` env var entirely.

**Changes:**
1. `docker-compose.yml`: Removed `RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"` from `worldcup-bot` environment block. Kept other 4 image vars.
2. `docker-compose.local.yml`: Same removal. Kept other 4 image vars.
3. `.env.example`: Removed `RICH_IMAGE_CHAT_ID=3041850` line and its comment. Updated section comment to say "Image is sent to TELEGRAM_GROUP_ID."

**Validation:** Both compose files parse cleanly (`docker compose config -q` exit 0 on both local and prod).

**Decision:** See `.squad/decisions/inbox/maldini-remove-rich-chat-id.md`.

## Session Summary (2026-06-17 17:05:00Z — Maldini)

### Rich Photo Folder Gitignore Pattern — Personal Photo Protection

Secured the `data/rich/` folder to prevent the personal base image from being committed to the public repo.

**Changes:**
1. `.gitignore`: Added two-line block after `data/tongo_gifs/*` rules:
   - `data/rich/*` (ignore all contents)
   - `!data/rich/.gitkeep` (track the folder via .gitkeep)
   - Mirrored the existing `data/tongo_gifs/` pattern with matching comment style.
2. Created `data/rich/.gitkeep` empty file to ensure the folder is tracked.

**Verification:**
- `git status --porcelain data/rich` → `?? data/rich/` (folder untracked; only .gitkeep present)
- `git check-ignore -v data/rich/rich_original.jpg` → `.gitignore:33:data/rich/*	data/rich/rich_original.jpg` (photo would be correctly ignored)

**Decision:** See `.squad/decisions/inbox/maldini-gitignore-rich-photo.md`.
