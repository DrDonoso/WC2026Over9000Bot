# Squad Decisions

✅ **COMPACTION COMPLETE** — 2026-06-15 entries moved to decisions-archive.md. File reduced from 172 KB to 135 KB. Current entries: 2026-06-16, 2026-06-17, + 3 inbox decisions merged (kante-32, kante-33, kante-34).

## 11. Decision: "Ver gol" inline button — clip finder + multi-host downloader

**Date:** 2026-06-16T09:45+02:00  
**Author:** Kanté  
**Status:** Implemented  

### Context

Users requested that the "Ver gol" inline button (shown on each goal notification) actually
fetches and sends the goal video clip instead of showing a placeholder toast.

### Design

#### A — Clip finder (`reddit/clip_finder.py`)

- `find_goal_clip(scanner, home_team, away_team, home_score, away_score, scorer, minute) -> str | None`
- Searches r/soccer via JSON endpoint (q=`home away`, restrict_sr, sort=new, t=day, limit=100) with HTML fallback.
- Parses each post title with `GOAL_TITLE_PATTERN` (ported from the proven RedditSoccerGoals repo).
- Match criteria: fuzzy team names (reuses `_teams_match` from scanner.py) + exact scoreline + (scorer fuzzy OR minute ±2).
- Returns the first matching post's external media URL, or `None`.
- **Synchronous** — callers wrap in `await asyncio.to_thread(find_goal_clip, ...)`.

#### B — Downloader (`reddit/downloader.py`)

`MediaDownloader` with host-specific resolvers, all using `requests` (sync) in `asyncio.to_thread`:

| Host | Strategy |
|------|----------|
| streamff.link / streamff.com | CDN id → `cdn.streamff.one/{id}.mp4`, else page scrape |
| streamin.link / streamin.me | CDN id → `c-cdn.streamin.top/uploads/{id}.mp4`, else embed scrape |
| streamain.com | Embed page scrape → `cdn.streamain.com/*.mp4` |
| v.redd.it, streamable.com, dubz.link, unknown | **yt-dlp subprocess fallback** |

Writes to system temp dir (`tempfile.gettempdir()`).

#### C — Video helpers (`reddit/video.py`)

- `probe_video(path) -> dict` — ffprobe JSON → `{width, height, duration}`.  
  **Without width/height Telegram renders video square.** This is the key fix.
- `compress_if_needed(path) -> Path` — returns original if ≤ 50 MB; ffmpeg two-pass bitrate re-encode otherwise.  
  Raises `VideoTooLargeError` if duration unknown, required bitrate < 200 kbps, ffmpeg fails, or ffmpeg times out.

#### D — Callback data / token

- `build_goal_keyboard(token: str)` — token = `hashlib.sha1(event.key)[:12]` (12 hex chars; well within 64-byte limit).
- Token → `bot_data["goal_clips"][token]` dict (in-memory, lost on restart — **acceptable for v1**).
  A future v2 could persist to SQLite.

#### E — Handler flow (`cmd_ver_gol_callback`)

1. Parse token from `query.data`.
2. Look up goal context; unknown token → alert, return.
3. Concurrency guard: "sending" → toast; "sent" → toast; else set "sending".
4. `query.answer("⏳ Buscando…")` (single answer call allowed by Telegram).
5. `find_goal_clip` via `asyncio.to_thread`.
6. `MediaDownloader.download(media_url)`.
7. `compress_if_needed(path)`.
8. `probe_video(send_path)` → `bot.send_video(**meta)`.
9. On success: `status="sent"`, `query.edit_message_reply_markup(None)` removes keyboard.
10. On any failure: `status="pending"` (allow retry), send error message, keep keyboard.
11. `finally`: unlink temp files.

### Dependencies introduced

| Dependency | Rationale |
|-----------|-----------|
| `yt-dlp>=2024.0` (added to `pyproject.toml`) | Subprocess fallback downloader for unsupported hosts |
| `ffprobe` (system binary) | Video dimension probe — prevents square video in Telegram |
| `ffmpeg` (system binary) | Video compression for files > 50 MB |

### Tests

72 new tests (407 total, all green):
- `tests/test_clip_finder.py` — GOAL_TITLE_PATTERN, URL extraction, _match_post (7 cases), find_goal_clip (6 cases), _parse_clip_posts_html.
- `tests/test_downloader.py` — CDN URL resolution for streamff + streamin, streamain embed scrape, yt-dlp fallback paths.
- `tests/test_video.py` — probe_video (5 cases), compress_if_needed (6 cases).
- `tests/test_handlers.py` — TestGoalToken (3), TestCmdVerGolCallback (8 cases: unknown token, concurrency guards, clip not found, download failure, happy path with correct meta, reply_to_message_id).

---

## 12. Decision: Reddit HTML Fallback Hardening (JSON 403 from Datacenter IPs)

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-16T10:05+02:00
**Status:** IMPLEMENTED

### Context

The "Ver gol" download pipeline was confirmed working (17 MB, 1920×1080, ffprobe dims correct). However the Reddit READ path was fragile: `old.reddit.com` JSON endpoints (`/.../.json`, `/r/soccer/search.json`) return **HTTP 403** from datacenter/corporate IPs including the user's production LXC. The existing HTML fallback in `get_thread_body` returned only 1363 chars (0 goals parsed) and `find_goal_clip` had no HTML search fallback at all.

### Diagnosis

Measured inside the running Docker container:

| Endpoint | Status | Notes |
|---|---|---|
| `old.reddit.com/.../.json` | **403** | Blocked from datacenter IPs |
| `old.reddit.com/r/soccer/search.json` | **403** | Blocked from datacenter IPs |
| `old.reddit.com/...thread.../` (HTML) | **200** | 681 KB, contains goals |
| `old.reddit.com/r/soccer/search?q=...` (HTML) | **200** | Contains clip posts |

The match-thread HTML has **no `data-selftext`** attribute. Goals are rendered as:
```html
<p><strong>7&#39;</strong> ⚽ <strong>Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) right footed shot...</strong></p>
```

The old `_MD_DIV_RE` (non-greedy `.*?`) stopped at the first `</div>` inside the post body, capturing only 1363 chars. There are 181 `class="md"` divs (post + every comment).

The search results HTML (`/r/soccer/search?q=...`) uses a completely different structure from `/new/` listing pages: the external clip URL is in a footer anchor `<a class="search-link" href="https://streamin.link/v/...">` — there is **no `data-url` attribute**.

### Decisions

#### 1. `get_thread_body` HTML fallback (`scanner.py`)

**Remove** `_MD_DIV_RE`. **Add** `_html_to_goaltext(html)`:
- `<strong>`/`</strong>`/`<b>`/`</b>` → `**` (bold markers for parse_goal_events)
- `</p>`/`<br>`/`</tr>`/`</li>` → `\n` (one event per line)
- Strip all remaining HTML tags
- `html.unescape()` (converts `&#39;` → `'`, `&amp;` → `&`, etc.)
- Collapse 3+ newlines to 2

**Update** `_fetch_thread_body_html`:
1. Try `data-selftext` attribute first (legacy/non-match threads may have it)
2. Cut HTML at `<div class="commentarea"` → excludes comment-section Goal! lines
3. Apply `_html_to_goaltext` to pre-commentarea HTML

Result: `**7'** ⚽ **Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) right footed shot...**` which `parse_goal_events` handles normally.

#### 2. `find_goal_clip` HTML search fallback (`clip_finder.py`)

**Add** `_REDDIT_SEARCH_HTML` endpoint: `https://old.reddit.com/r/soccer/search?q={query}&restrict_sr=on&sort=new&include_over_18=on`

**Add** `_parse_search_results_html(html)`:
- Splits by `data-fullname="t3_"` blocks
- Extracts title from `<a class="search-title ...">Title</a>`
- Extracts external media URL from `<a class="search-link ..." href="https://streamin.link/v/...">` footer anchor
- Skips blocks without `search-title` (to avoid false positives on listing-format pages)

**Updated fallback chain** in `find_goal_clip`:
1. JSON search (`search.json?q=...`) — skip on 403
2. **HTML search** (`search?q=...`) — new, parses `search-link` footer URLs
3. `/new/` HTML listing — existing last resort

### Results

E2E inside container: **10 OK | 0 fallos | 0 sin clip**
- **Sweden vs Tunisia** (1u62p01): 6 goals parsed from HTML; 6 clips downloaded (streamin.link, 1920×1080, 17–20 MB)
- **Netherlands vs Japan** (1u5uc8w): 4 goals parsed; 4 clips downloaded (streamin.link + streamff.link)

Unit tests: 420 total, all green (+13 new).

---

## 13. Decision: ffmpeg shipped in the drdonoso/worldcup2026 image

**Date:** 2026-06-16  
**Author:** Maldini (DevOps agent)  
**Status:** Applied

### Context

The "Ver gol" feature (goal-clip download + Telegram delivery) requires `ffmpeg` and `ffprobe` as system binaries inside the container. `ffmpeg` is available in Debian's package repos (`ffmpeg` package ships both binaries). The Python `yt-dlp` library (which calls `ffmpeg`/`ffprobe` internally) is added to `pyproject.toml` by Kanté and installed via the existing `pip install .` layer.

### Decision

Add a single `RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*` layer to the Dockerfile, placed immediately after `FROM python:3.12-slim AS base` and before any user-creation or `COPY`/pip steps.

### Rationale

- **Cache efficiency:** System deps (apt) change far less often than Python deps. Placing the apt layer first means Python dep changes (e.g., adding `yt-dlp` to `pyproject.toml`) do not invalidate the apt cache layer.
- **Minimal image surface:** `--no-install-recommends` keeps image size small; cleanup of apt lists reclaims ~20 MB.
- **No new mounts or env vars:** `/tmp` is world-writable in debian-slim by default, so the non-root `app` user can write temporary video files without any extra Docker configuration.
- **Mirrors sibling repo:** `Z:/Repos/Personal/RedditSoccerGoals/Dockerfile` uses the identical pattern (ffmpeg via apt, yt-dlp via pip/pyproject).

### Verification

```
ffmpeg version 7.1.4-0+deb13u1 Copyright (c) 2000-2026 the FFmpeg developers
ffprobe version 7.1.4-0+deb13u1 Copyright (c) 2007-2026 the FFmpeg developers
yt-dlp: not yet in image (pending Kanté's pyproject.toml change)
```

Build: `docker compose -f docker-compose.local.yml build` → exit 0.

---

---

## 14. Decision: OpenAI-Compatible AI Integration + Daily 9 AM Spanish Recap

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T13:45+02:00  
**Status:** IMPLEMENTED  
**Phase:** 21

### Summary

Added an optional OpenAI-compatible AI integration that calls a self-hosted LiteLLM instance. When configured, a daily job at 9:00 AM local time posts a short Spanish recap to the Telegram group: yesterday's results, today's fixtures, plus historical/armed-conflict curiosities between the competing nations. A hidden `/updatediario` command allows manual testing without waiting for 9 AM.

### Env Vars for Maldini (wire into compose + .env.example)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | When feature enabled | — | API key for LiteLLM/OpenAI endpoint |
| `OPENAI_BASE_URL` | When feature enabled | — | Base URL of the LiteLLM OpenAI-compatible endpoint (e.g. `https://litellm.example/v1`) |
| `OPENAI_MODEL` | When feature enabled | — | Model name to pass to the completions API |
| `DAILY_UPDATE_HOUR` | No | `9` | Local hour (0–23) for the daily recap post |

**Feature self-disables** when any of the three OPENAI_* vars is absent/empty — the bot still starts and logs: `Daily AI update DISABLED — set OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL to enable.`

### Architecture Notes

- Uses official `openai>=1.40` SDK with `AsyncOpenAI(api_key=..., base_url=...)` — LiteLLM is OpenAI-compatible so pointing `base_url` at it is the standard pattern.
- `src/worldcup_bot/ai/` package — **NOT** named `openai` (would clash with SDK import).
  - `ai/client.py` — `AIClient` wraps `AsyncOpenAI`; injectable `_client` param for tests; raises `AIError` on failure.
  - `ai/daily_update.py` — `build_messages()` (pure function, testable), `generate_daily_update()` (orchestrator).
- `ai_enabled(settings) -> bool` in `config.py` — checks all three OPENAI_* non-empty.
- `daily_update_job` in `__main__.py` — swallows exceptions (never crashes the process, never spams the group).
- `/updatediario` in `handlers.py` — hidden from `/start` help, like `/simulagol`.

### Dependency Added

```toml
"openai>=1.40"
```
added to `pyproject.toml` `dependencies`.

### Files Changed

- `pyproject.toml` — `openai>=1.40` dependency
- `src/worldcup_bot/config.py` — 4 new fields + `ai_enabled()` function
- `src/worldcup_bot/ai/__init__.py` *(new)*
- `src/worldcup_bot/ai/client.py` *(new)*
- `src/worldcup_bot/ai/daily_update.py` *(new)*
- `src/worldcup_bot/bot/handlers.py` — `cmd_update_diario` + imports
- `src/worldcup_bot/__main__.py` — `daily_update_job` + scheduling + handler registration
- `tests/test_ai.py` *(new)* — 36 tests, all mocked

---

## 15. Decision: /simulagol picks a random WC goal from finished fixtures

**Date:** 2026-06-16T11:01+02:00  
**Agent:** Kanté  
**Status:** Implemented

### Context

`/simulagol` previously always fired the exact same fixed goal (Sweden 3-1 Tunisia, Gyökeres 60'). Useful for E2E testing, but limited: it always tested the same clip/scoreline and gave no variety.

### Decision

Make `/simulagol` pick a **random goal from any FINISHED WC match**. Keep the fixed Sweden-Tunisia goal as an infallible fallback.

### Implementation

#### New: `RedditMatchScanner.find_match_thread(home_name, away_name) -> str | None`

Queries `old.reddit.com/r/soccer/search?q=match+thread+{home}+{away}&t=week` via the existing session (browser headers + over18 cookie). Parses results using **`_SEARCH_RESULT_LINK_RE`** — a regex targeting `class="search-title"` links — because search-results pages use a completely different HTML structure from `/r/soccer/new/` (no `data-fullname`/`data-timestamp`/`data-permalink` attributes, no `class="title"` links). Filters by `_is_match_thread` (excludes Pre/Post) and `_teams_match` (both team-order directions). Resilient: wrapped in try/except, returns None on any failure.

#### New: `_pick_random_goal(client, scanner, max_candidates=6) -> (GoalEvent, str, str) | None`

Sync helper called from `cmd_simula_gol` via `asyncio.to_thread`. Algorithm:
1. `client.get_all_matches()` → filter `status == "FINISHED"` → shuffle
2. For each of up to 6 candidates: `scanner.find_match_thread(...)` → `scanner.get_thread_body(...)` → `parse_goal_events(...)` → `random.choice(goals)`
3. Align TLAs to the API fixture (handles title home/away reversal)
4. Return first `(goal, home_tla, away_tla)` or None

#### Updated: `cmd_simula_gol`

- Sends `"⏳ Eligiendo un gol al azar del Mundial…"` first (UX)
- Runs `_pick_random_goal` in a thread
- Falls back to fixed Sweden-Tunisia goal if pick fails
- Stores in `bot_data["goal_clips"]` with identical shape — `cmd_ver_gol_callback` unchanged

### Key Discovery

Reddit's **search results page** (`/r/soccer/search?...`) returns HTML with links structured as:
```html
<a href="https://old.reddit.com/r/soccer/comments/[id]/[slug]/" class="search-title may-blank">Title</a>
```
This is **completely different** from `/r/soccer/new/` which uses `data-fullname`, `data-timestamp`, `data-permalink` attributes and `class="title"` links. The existing `_parse_html_posts` function only works for listing pages, not search pages. New `_SEARCH_RESULT_LINK_RE` constant added to handle this.

### Alternatives Considered

- **Use Reddit JSON search**: 403 in datacenter (known issue; already worked around elsewhere)
- **Hardcode thread IDs**: Brittle, doesn't scale
- **Use football-data match IDs for lookup**: football-data doesn't include Reddit links

### Tests Added (17 new, all green — 443 total)

- `TestFindMatchThread` (7 tests): canned search-result HTML, pre/post exclusion, None on error, reversed team order, different fixture
- `TestCmdSimulaGolRandomPath` (5 tests): mock client + scanner, correct goal stored, TLA alignment, fallback on missing thread/no goals/no finished matches
- `TestPickRandomGoal` (4 tests): unit tests for the sync helper

### Live Verification

3 different random WC goals from real Reddit threads (inside container, real Reddit 403 env):
- Côte d'Ivoire 1-0 Ecuador | Amad Diallo 90' | TLA: CIV/ECU  
- Saudi Arabia 1-1 Uruguay | Maxi Araújo 80' | TLA: KSA/URY  
- Sweden 2-0 Tunisia | Alexander Isak 30' | TLA: SWE/TUN

---

## 16. Decision: TELEGRAM_GROUP_ID is now a required setting

**Author:** Kante (Backend)  
**Date:** 2026-06-16T12:24+02:00  
**Status:** IMPLEMENTED  

### Context

The goal notifier (`poll_goals_job` in `__main__.py`) calls `context.bot.send_message(chat_id=settings.telegram_group_id, ...)` on every goal event. If `TELEGRAM_GROUP_ID` is not set the bot starts without error but silently fails to send any notifications — a confusing silent failure mode.

### Decision

`load_settings()` now validates `TELEGRAM_GROUP_ID` with the same fail-fast pattern used for `TELEGRAM_BOT_TOKEN` and `FOOTBALL_DATA_API_KEY`:

```python
group_id = os.getenv("TELEGRAM_GROUP_ID", "")
if not group_id:
    raise RuntimeError(
        "❌ TELEGRAM_GROUP_ID is not set. "
        "It is required for live goal notifications. "
        "Set it in the environment or in .env before starting the bot."
    )
```

The `Settings` dataclass field default (`telegram_group_id: str | None = None`) is **intentionally kept** to avoid breaking the many unit tests that construct `Settings(...)` directly without a group id.

### Consequences

- `__main__.py`: The `if settings.telegram_group_id` / `else` conditional around `job_queue.run_repeating` is removed — the job is always scheduled because the group id is guaranteed by the time `main()` runs.
- The "Goal notifier DISABLED" warning branch is dead code and has been removed.
- Operators must set `TELEGRAM_GROUP_ID` before starting the bot. Maldini is updating `docker-compose.yml` and `.env.example` in parallel.
- 473 tests green.

---

## 17. Decision: /simulagol test command

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T10:48+02:00  
**Status:** IMPLEMENTED  
**Requested by:** DrDonoso

### Context

There are no live WC2026 matches right now, so `poll_goals_job` never fires a goal notification. This makes it impossible to test the "Ver gol" inline button flow end-to-end in the real Telegram group.

### Decision

Added `/simulagol` — a small utility command that fires a **real goal notification** with a known-good clip (Sweden 3-1 Tunisia, Viktor Gyökeres 60') and stores full goal context in `bot_data["goal_clips"]`, so the "Ver gol" button can be tapped and the full flow (find clip → download → send video → remove keyboard) is exercised without any live match.

### Implementation

- `cmd_simula_gol` in `src/worldcup_bot/bot/handlers.py`:
  - Builds a `GoalEvent` with fixed data (home=Sweden, away=Tunisia, hs=3, as=1, scorer=Viktor Gyökeres, minute=60').
  - Token = `_goal_token("SIM:sweden-tunisia-3-1-60-gyokeres")` — stable across restarts.
  - Stores EXACTLY the same dict shape that `poll_goals_job` stores (home_team, away_team, home_score, away_score, scorer, minute_text, scoring_team, home_tla, away_tla, status="pending").
  - Calls `format_goal_notification` + `build_goal_keyboard` and replies with `🧪 [SIMULACIÓN]\n<text>` + inline keyboard in the CURRENT chat.
  - Logs at INFO.
- `src/worldcup_bot/__main__.py`: `CommandHandler("simulagol", cmd_simula_gol)` registered.
- `/start` help text updated.
- 6 new tests in `tests/test_handlers.py` (`TestCmdSimulaGol`). 426 total, all green.

### Future Options

- **Make admin-only**: add a check `update.effective_user.id in settings.admin_ids` and reply with an error for non-admins. Useful if deployed in a public group.
- **Remove**: once live WC matches are happening regularly and the flow has been validated in production.
- **Parameterise**: accept optional team/scorer/minute args to test different scenarios.

The command is intentionally left without an admin gate for now (harmless test utility in a private group context), but this should be revisited if the bot is ever opened to a larger audience.

---

## 18. Decision: Gender-aware /tongo phrase via gender-guesser

**Date:** 2026-06-16T12:54+02:00
**Author:** Kante (Backend)
**Status:** Implemented

### Context

The `/tongo` command returns a random sarcastic phrase (2/3 chance) or "Sanchez ens roba" (1/3 chance). DrDonoso requested a new phrase that adapts its grammatical gender to the user who triggers the command: *"Que tongo ni que tongo, eres mas pesad_ que un_ argentin_."*

### Problem

Telegram's `User` object does **not** include a gender field. The only available name data is `first_name`, `last_name`, and `username`. To infer gender from `first_name` we need an external name database.

### Decision

**Use `gender-guesser` (PyPI, pure Python, offline name database).** Added as a production dependency (`gender-guesser>=0.4`).

- Inference is done in `worldcup_bot.data.gender.infer_gender(first_name)`.
- Returns `'f'` for `female` / `mostly_female`; `'m'` for everything else (male, mostly_male, andy, unknown, None, empty).
- Default to male (`'m'`) is intentional: it minimises misgendering in the unknown/ambiguous case for a bot where the user base is mostly male.
- The dynamic phrase is added to the 2/3 random candidate pool at runtime (`candidatas = FRASES + [frase_argentino(gender)]`). It is NOT a static string in `FRASES`, so it never inflates the static list count.

### Alternatives Considered

| Option | Rejected because |
|--------|-----------------|
| Ask user to set their gender in bot | Unnecessary friction for a joke command |
| Use Telegram username heuristics | Usernames are often handles, not names; low accuracy |
| External gender API (e.g., genderize.io) | Network dependency; privacy concern; offline DB is sufficient |
| Hard-code gender per known participant | Not scalable; bot can run for unknown users |

### Consequences

- New production dependency: `gender-guesser>=0.4` (pure Python, ~200 KB, offline). Added to `pyproject.toml` and rebuilt Docker image.
- Inference accuracy is "good enough" for a joke command. Ambiguous/unknown names → male (silent fallback, no error).
- `gender.py` module is independent and unit-tested; easy to swap the backend if needed.
- The 1/3 `SANCHEZ_ENS_ROBA` guarantee is fully preserved (dynamic phrase is only in the 2/3 pool).

---

## 19. Decision: /tongo GIF pool (mounted hot-reload)

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T13:05+02:00  
**Status:** IMPLEMENTED

### Context

DrDonoso requested that `/tongo` be able to send GIFs (and short MP4s) mixed into the same random pool as the existing phrases, so that taunting responses can be animated. Storage must reuse the existing `./data:/app/data:ro` Docker volume so files can be dropped on the server without a rebuild.

### Decision

#### Storage
GIFs live in `data/tongo_gifs/` on the host, mounted at `/app/data/tongo_gifs/` in the container via the existing `./data:/app/data:ro` bind-mount. The folder is committed with a `.gitkeep` so the mount target exists in the image even when empty. The folder is **not** git-ignored so users can optionally version "factory" GIFs.

#### Directory resolution (in order)
1. If `Settings.tongo_gifs_dir` is set (env `TONGO_GIFS_DIR`), use it directly.
2. Otherwise derive `Path(settings.predictions_path).parent / "tongo_gifs"` — mirrors predictions.yml location in both local (`data/`) and container (`/app/data/`) contexts.

#### Pool mixing
```
pool = FRASES + [frase_argentino(gender)] + gifs   # gifs = list[Path]
choice = random.choice(pool)
isinstance(choice, Path) → send_animation   else → reply_text
```
Each GIF has the same individual probability weight as each phrase. Adding more GIFs increases the GIF fraction of the 2/3 block proportionally. `SANCHEZ_ENS_ROBA` is unaffected (early-return at 1/3).

#### Hot-reload
`list_tongo_gifs(gifs_dir)` is called fresh on every `/tongo`. Adding or removing a file on the server is reflected on the next invocation without restart.

#### Graceful degradation
If `send_animation` raises (bad file, Telegram error), a warning is logged and a fallback `random.choice(FRASES)` phrase is sent via `reply_text` so the command never silently fails.

#### Supported formats
`.gif`, `.mp4`, `.webp` (lowercased suffix check). Non-existent or unreadable directory → `[]` (never raises).

### Alternatives considered

| Option | Rejected because |
|---|---|
| Store GIFs in the image (Dockerfile COPY) | Requires rebuild to add/change GIFs |
| Separate Docker volume for GIFs | Extra infrastructure; existing `./data` mount already covers it |
| Weighted pool (different weight per GIF) | Over-engineering; equal weight is the simplest correct model |

### Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/data/gifs.py` | New — `list_tongo_gifs` helper |
| `src/worldcup_bot/config.py` | Added `tongo_gifs_dir: str = ""` + `TONGO_GIFS_DIR` env |
| `src/worldcup_bot/bot/handlers.py` | `cmd_tongo` rewritten; added `Path`, `list_tongo_gifs` imports |
| `data/tongo_gifs/.gitkeep` | New — seeds the mounted folder |
| `.gitignore` | Note that `data/tongo_gifs/` is NOT ignored |
| `tests/test_tongo.py` | `TestListTongoGifs` (6 tests) |
| `tests/test_handlers.py` | `TestCmdTongoGifs` (6 tests), `Path` import, `send_animation` in `_make_context` |
| `README.md` | Documents GIF hot-reload + `TONGO_GIFS_DIR` |
| `.env.example` | Commented `TONGO_GIFS_DIR` line |

---

## 20. Decision: /simulagol hidden from /start help + /tongo probability rework

**Author:** Kante (Backend Developer)
**Date:** 2026-06-16T12:08+02:00
**Status:** IMPLEMENTED

### Context

Two small UX/logic changes requested by DrDonoso:

1. `/simulagol` is a test command used to exercise the "Ver gol" button flow. It should remain functional but not be advertised in `/start` help text (it clutters the menu for real users).

2. `/tongo` previously weighted "Sanchez ens roba" by repeating it 25 times in `FRASES` — a quick hack from the legacy Euro 2024 bot. The desired probability is exactly 1/3, which is better expressed explicitly.

### Decisions

#### 1. `/simulagol` removed from `/start` help (command kept)

- Deleted only the `/simulagol — (test) …` line from `cmd_start`'s reply string.
- The `CommandHandler("simulagol", cmd_simula_gol)` registration in `__main__.py` is untouched.
- No behaviour change — the command still works when typed manually.

#### 2. `/tongo` explicit 1/3 probability

- Introduced `SANCHEZ_ENS_ROBA = "Sanchez ens roba"` constant in `tongo.py`.
- `FRASES` now contains ONLY the 15 original sarcasm phrases + 13 new Spanish/Catalan phrases (28 total). Zero "Sanchez ens roba" entries.
- `cmd_tongo` logic: `if random.random() < 1/3 → SANCHEZ_ENS_ROBA; else → random.choice(FRASES)`.
- Rationale: explicit probability is readable, testable, and not fragile to future list edits. The 25-duplicate approach would silently break if someone added more phrases.

### Files Changed

- `src/worldcup_bot/data/tongo.py` — full rewrite of FRASES, new SANCHEZ_ENS_ROBA constant, updated docstring.
- `src/worldcup_bot/bot/handlers.py` — import update, cmd_start line removed, cmd_tongo logic replaced.
- `tests/test_tongo.py` — new file: data integrity tests.
- `tests/test_handlers.py` — added TestCmdTongo, extended TestCmdStart.

### Verification

- 471 pytest tests passing.
- Smoke: `sanchez not in FRASES: True`, `frases count: 28`, `new phrase present: True`.
- Container rebuilt (`drdonoso/worldcup2026`), State=running, RestartCount=0.

---

## 21. Decision: Ver-gol Concurrency Hardening + file_id Cache

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T11:43+02:00  
**Status:** DONE — implemented, 449 tests green, container running.

### Context

`cmd_ver_gol_callback` already had a status-based guard (`"sending"` / `"sent"`) that was effectively atomic on PTB's single-threaded event loop (no await between check and set). However:
1. The mutual-exclusion was implicit — a future edit adding an `await` between the status check and status set would silently break it.
2. Every call to "Ver gol" re-downloaded and re-uploaded the same video file, even if Telegram had already stored a permanent `file_id` for it.

### Decisions

#### A — Explicit non-blocking in-flight lock per goal token

A `vergol_inflight: set` in `bot_data` provides an explicit, self-documenting guard:

```python
inflight: set = context.bot_data.setdefault("vergol_inflight", set())
if token in inflight:
    await query.answer("Ya estoy enviando el vídeo…")
    return
inflight.add(token)
info["status"] = "sending"   # both lines before the first await — atomic
```

`inflight.discard(token)` always runs in `finally`, so the lock is never stuck. The existing `status` field is kept as belt-and-suspenders; the inflight set is the suspenders that make the intent explicit even if future edits add awaits.

**Rejected alternative:** asyncio.Lock per token — would block the 2nd click for ~15s (Telegram spins a loading indicator on the button). Non-blocking fast-fail (toast answer + immediate return) is significantly better UX.

#### B — Two-level Telegram file_id cache

Telegram video file_ids are effectively permanent for the same bot. Once a video is uploaded, all future sends can use the file_id directly — no re-download, no re-upload, instant delivery.

**Level 1 — per-goal shortcut (`info["file_id"]`):**
If the same goal button is pressed again (unlikely but possible), skip everything including `find_goal_clip`.

**Level 2 — per-media-url cache (`bot_data["clip_file_ids"][url]`):**
If two different goals share the same clip URL (same highlight used for two notifications), the second send re-uses the file_id without downloading.

**Fresh-send capture:**
```python
sent_msg = await context.bot.send_video(...)
if sent_msg and sent_msg.video:
    fid = sent_msg.video.file_id
    info["file_id"] = fid
    clip_file_ids[media_url] = fid
```

**Stale file_id handling:**
If a fast-path `send_video(video=file_id)` raises (very rare — Telegram file_ids for videos are effectively permanent), the file_id is evicted from both caches, `status` is reset to `"pending"`, and the exception propagates through the outer `except` block so the user sees the standard error toast and can retry.

#### Initialisation

`build_app` now eagerly creates both new dicts/sets so they always exist and tests/handlers can rely on them without `.setdefault` races:

```python
app.bot_data["vergol_inflight"] = set()
app.bot_data["clip_file_ids"] = {}
```

### Trade-offs considered

| Option | Pro | Con | Decision |
|--------|-----|-----|----------|
| asyncio.Lock per token | True async safety | Blocks 2nd click ~15s (bad UX) | Rejected |
| Status field only | Already works today | Implicit; breaks if await added | Keep as belt |
| Inflight set (chosen) | Explicit; non-blocking; easy to audit | Slightly more code | ✅ |
| Persistent file_id (DB/Redis) | Survives restart | Overkill for in-memory bot | Rejected |
| In-memory file_id cache (chosen) | Zero extra deps; instant repeat sends | Lost on restart | ✅ |

### Tests added (6 new)

- `test_inflight_guard_answers_immediately_no_download` — pre-add token, assert toast + no find/send
- `test_inflight_token_discarded_after_successful_run` — token removed from inflight in finally
- `test_cached_file_id_on_info_resends_instantly_no_download` — fast path A
- `test_cached_file_id_per_media_url_resends_instantly` — fast path B
- `test_fresh_send_stores_file_id_in_cache` — capture + store after real upload
- `test_bad_file_id_evicted_and_status_reset` — stale fid evicted, status pending

---

## 22. Decision: OpenAI / LiteLLM env vars wired into compose files

**Date:** 2026-06-16T13:45+02:00  
**Author:** Maldini (DevOps)  
**Requested by:** DrDonoso

### Context

Kanté added an OpenAI-compatible AI integration (daily 9AM update via the user's self-hosted LiteLLM proxy). The feature reads four env vars (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `DAILY_UPDATE_HOUR`) and self-disables in-app when any of the three key vars are unset.

### Decision

Wire the four vars into the Compose infra layer as **optional pass-throughs** so:
1. The production image can receive them at runtime without a code change.
2. The feature stays dormant until the operator explicitly sets all three enable vars.

### Changes Made

| File | Change |
|------|--------|
| `docker-compose.yml` | Added 4-var block under `# --- OpenAI-compatible AI ---`, after `TELEGRAM_GROUP_ID` |
| `docker-compose.local.yml` | Same 4-var block (same position, same style) |
| `.env.example` | New commented-out section at the end; notes that ALL THREE (key/base_url/model) must be set |

**Style used** (mirrors existing optional vars like `TIMEZONE`):
```yaml
OPENAI_API_KEY: "${OPENAI_API_KEY:-}"
OPENAI_BASE_URL: "${OPENAI_BASE_URL:-}"
OPENAI_MODEL: "${OPENAI_MODEL:-}"
DAILY_UPDATE_HOUR: "${DAILY_UPDATE_HOUR:-9}"
```

### Files NOT modified

- `config.py` — Kanté owns the in-app feature-flag logic.
- `.env` — user's real secrets; git-ignored; never touched by infra changes.
- `Dockerfile` — no build-time changes needed; all vars are runtime env.

### Verification

```powershell
$env:TELEGRAM_GROUP_ID='-100123'; $env:TELEGRAM_BOT_TOKEN='fake'; $env:FOOTBALL_DATA_API_KEY='fake'
docker compose -f docker-compose.yml config --quiet       # exit 0
docker compose -f docker-compose.local.yml config --quiet # exit 0
```

Both parsed with exit code 0 and no YAML errors.

---

## 23. Decision: Promote TELEGRAM_GROUP_ID to Required

**Date:** 2026-06-16T12:24+02:00
**Author:** Maldini (DevOps)
**Status:** Implemented

### Context

The live goal notifier feature requires a Telegram group/channel ID to post goal alerts. Without it the feature is silently broken. Kanté is updating `load_settings()` to fail fast (hard validation) if the variable is missing.

### Decision

`TELEGRAM_GROUP_ID` is now a **required** environment variable across the entire stack:

| File | Change |
|------|--------|
| `docker-compose.yml` | Comment → "REQUIRED for live goal notifications"; value `"${TELEGRAM_GROUP_ID:-}"` → `"${TELEGRAM_GROUP_ID}"` |
| `docker-compose.local.yml` | Same change |
| `.env.example` | Moved from `# Optional — Override defaults` (commented) to its own `# Required` block (uncommented), after `FOOTBALL_DATA_API_KEY` |

### Rationale

- Dropping the `:-}` empty-default causes Compose to emit a **warning** when the variable is unset, giving operators an early signal before the container even starts.
- Hard enforcement (startup failure) is delegated to the application layer (`load_settings()` — Kanté's responsibility).
- `.env` (git-ignored, holds real values) was **not** modified.

### Files Changed

- `docker-compose.yml`
- `docker-compose.local.yml`
- `.env.example`

### Files NOT Changed

- `config.py` (Kanté's ownership — not touched)
- `.env` (user data — not touched)

---

## 24. Decision: Daily Update HTML Format + Snapshot

**Author:** Kanté (Backend)  
**Date:** 2026-06-16  
**Status:** IMPLEMENTED — 594 tests green.

### Context

The daily AI update posted at 09:00 and via `/updatediario` was sending raw Markdown-like text without `parse_mode`, causing `**bold**` to appear literally, results jammed into one paragraph, no flag emojis, and filler notes even when no interesting match context existed.

### Decisions

#### 1. Message format — HTML, built deterministically

The final message is now assembled **in code** (pure `render_message()` function) and sent with `parse_mode="HTML"`.  Layout:

```
📅 <b>Resultados de ayer</b>
{home_flag} {home_bold?} {hs}-{as} {away_bold?} {away_flag}

⚽ <b>Partidos de hoy</b>
{home_flag} <b>{home}</b> vs <b>{away}</b> {away_flag} — {HH:MM}
   <i>{note}</i>   ← only if non-empty

📊 <b>La porra</b>
{standings_comment}
```

All AI-provided and team-name strings pass through `html.escape(s, quote=False)` before insertion.

#### 2. AI contract — JSON only

The model must return **strict JSON** (no markdown fences):
```json
{"today_notes": {"TLA1-TLA2": "nota o vacía"}, "standings_comment": "texto"}
```
- `today_notes` keys: `"{home_tla}-{away_tla}"` for each today match.
- Note is non-empty **only** for matches with a genuine rivalry, conflict, or interesting fact.  If nothing, empty string (no filler).
- `parse_ai_json()` strips fences and calls `json.loads()`; on failure → `({}, "")` + `log.warning`.

#### 3. Snapshot module — `src/worldcup_bot/ai/snapshot.py`

Tracks provisional ranking positions day-by-day.  
File: `{state_dir}/porra_snapshot.json`.  
Schema: `{"YYYY-MM-DD": {username: position(int)}}`.  
Prunes to 7 dates.  All I/O is best-effort (swallow+log, never crash).  
On first run: `baseline=None` → AI notified → writes intro instead of movement recap.

#### 4. `state_dir` config field

`Settings.state_dir` added (default `/app/state`, env `STATE_DIR`).  
Maldini owns the Docker volume at `/app/state` (writable bind-mount).

#### 5. `parse_mode="HTML"` on both senders

- `__main__.py` `daily_update_job` → `send_message(..., parse_mode="HTML")`
- `bot/handlers.py` `cmd_update_diario` → `send_message(..., parse_mode="HTML")`

### Impact

- `build_messages()` (old) removed; replaced by `build_ai_user_message()`, `parse_ai_json()`, `render_message()`.
- `generate_daily_update()` now also loads porra ranking + snapshot before calling AI.
- 56 new tests; 594 total green.

---

## 25. Decision: Raise AI max_tokens to 1500 + bound standings_comment length

**Date:** 2026-06-16  
**Author:** Kanté (Backend Developer)  
**File:** `src/worldcup_bot/ai/daily_update.py`

### Context

Live E2E revealed that `generate_daily_update()` called `ai.complete()` with `max_tokens=800`. With 12 porra participants + today's match notes + standings narrative, the model's JSON response was truncated → `parse_ai_json` failed with "Unterminated string" → the "La porra" section and today-match notes were silently empty (graceful degradation worked, but AI content was lost).

### Decision

1. **`max_tokens` raised from 800 → 1500** in the `ai.complete(...)` call.  
2. **`_SYSTEM` prompt updated**: `standings_comment` is now explicitly bounded to "máximo 4-5 frases cortas" to reduce the token footprint of the narrative and further lower truncation risk.  
3. Everything else unchanged: HTML render, snapshot, parse fallback, team names in English.

### Tests

- New test `test_complete_called_with_max_tokens_1500` asserts the `complete()` call uses `max_tokens=1500`.  
- Full suite: **595 passed** (was 594).

---

## 26. Decision: Use `max_completion_tokens` instead of `max_tokens` for AI calls

**Date:** 2026-06-16  
**Author:** Kante (Backend)  
**Status:** Implemented

### Context

Live diagnostics against the user's LiteLLM endpoint revealed that the proxy silently clamps the legacy `max_tokens` parameter to 100 tokens (`finish_reason="length"`, `completion_tokens=100`, `reasoning_tokens=0`). This caused the daily-update JSON response to be truncated, breaking `parse_ai_json` and producing an empty "La porra" section.

### Decision

Replace all uses of `max_tokens` in `AIClient.complete` (signature + `chat.completions.create` call) with `max_completion_tokens`, which the OpenAI SDK ≥1.x and modern OpenAI-compatible backends honour correctly. Do **not** send both params simultaneously — some backends reject duplicate token limit fields.

### Changes

- `src/worldcup_bot/ai/client.py` — `AIClient.complete` signature: `max_tokens: int = 600` → `max_completion_tokens: int = 600`; pass `max_completion_tokens=max_completion_tokens` to `create()`.
- `src/worldcup_bot/ai/daily_update.py` — `generate_daily_update`: call site updated to `max_completion_tokens=1500`.
- `tests/test_ai.py` — renamed `test_passes_temperature_and_max_tokens` → `test_passes_temperature_and_max_completion_tokens`; renamed `test_complete_called_with_max_tokens_1500` → `test_complete_called_with_max_completion_tokens_1500`; both now assert `max_completion_tokens` is present and `max_tokens` is **absent** from the SDK call kwargs.

### Outcome

595 tests pass (no regressions). `finish_reason` will be `"stop"` with full JSON output instead of `"length"` truncated at 100 tokens.

### Rule going forward

Every future `AIClient.complete` call — and any direct `chat.completions.create` call added later — **must** use `max_completion_tokens`, never `max_tokens`.

---

## 27. Decision: Persistent State Volume for Porra Snapshot (Phase 23)

**Date:** 2026-06-16  
**Owner:** Maldini (DevOps)  
**Status:** ✅ Implemented

### Problem

Kanté's new porra-standings feature requires persisting a daily JSON snapshot (`porra_snapshot.json`) that survives container restarts and recreations. The existing `/app/data` mount is **read-only** (`:ro`), so a new writable location is needed.

### Solution

Introduced a **Docker named volume** at `/app/state` to hold persistent bot state, independent of container lifecycle or host filesystem paths.

#### Changes

##### docker-compose.yml (production)
- Added `STATE_DIR: /app/state` to bot service environment
- Added `- bot_state:/app/state` to bot service volumes (kept `./data:/app/data:ro` unchanged)
- Added top-level `volumes: { bot_state: }` declaration

##### docker-compose.local.yml (local dev)
- Identical STATE_DIR and volume mount as production
- Kept existing SSL cert mount (`./certs:/certs:ro`) and data mount

##### .env.example
- Added explanatory comment: STATE_DIR is set in compose files, not a user-configurable secret
- No secrets, no mandatory new keys

### Verification

Both compose files validated:
```
docker compose -f docker-compose.local.yml config -q  → exit 0 ✅
docker compose -f docker-compose.yml config -q        → exit 0 ✅
```

### Why Named Volume?

- **Persistence across restarts:** State survives `docker compose restart`
- **Persistence across recreations:** State survives `docker compose down && up`
- **Environment-agnostic:** Works on Docker Desktop, Swarm, cloud (Compose abstractly manages volume backend)
- **No host filesystem coupling:** No need for ./state directory on host; Docker manages lifecycle

### Contracts

- **Kanté reads `STATE_DIR` env var** (default: `/app/state`)
- **Kanté writes `{STATE_DIR}/porra_snapshot.json`** on daily update
- **No user intervention needed:** Volume auto-creates on first container start
- **Cleanup:** `docker volume rm bot_state` if the project is removed

### References

- `.squad/agents/maldini/history.md`: Learning entry Phase 23

---

## 28. Decision: Docker Named-Volume Ownership Fix for /app/state

**Date:** 2026-06-16T15:26+02:00  
**Owner:** Maldini (DevOps)  
**Status:** Implemented  

### Problem
The Docker named volume `bot_state` (mounted at `/app/state`) was owned by `root:root` at creation time. When the non-root `app` user (uid 1000) tried to write the daily porra snapshot (`porra_snapshot.json`), the container crashed with:
```
[Errno 13] Permission denied: '/app/state/porra_snapshot.json'
```

### Root Cause
Docker initializes a fresh named volume's directory ownership from the **image's directory state** at that mount path. Because the Dockerfile never explicitly created `/app/state`, the mountpoint inherited root ownership when the volume was first created.

### Solution
**Dockerfile change (line 24–25):** Extended the existing directory setup to also create and chown `/app/state` before `USER app`:

```dockerfile
# Create writable directories for the data mount + persistent state volume
RUN mkdir -p /app/data /app/state && chown -R app:app /app/data /app/state
```

This ensures both `/app/data` and `/app/state` are created with `app:app` (uid 1000, gid 1000) ownership **before** the `USER app` line, so any named volumes mounted at these paths will inherit the correct permissions.

### Pattern (for future reference)
Docker's named-volume ownership inheritance:
- Happens at **image build time** (directory permissions are baked into the image layers)
- Applies when the volume is **first mounted** (if the image's directory already exists with specific ownership, the volume inherits it)
- Cannot be fixed retroactively on existing volumes (must be recreated)

### Verification Checklist
- ✅ Dockerfile creates `/app/state` and chowns it to `app:app`
- ✅ Creation and chown happen **before** `USER app` line
- ✅ Single combined `RUN` line for smaller layer footprint
- ✅ Existing `/app/data` handling unchanged

### Coordinator Handoff
**After rebuilding the image:** The existing `bot_state` volume on development machines was created with root ownership and must be recreated. Run:
```bash
docker volume rm bot_state
```
Then the next `docker compose up` will create a fresh `bot_state` volume that inherits `app:app` ownership from the updated image.

### Impact
- **Scope:** Dockerfile only (no changes to compose files, env vars, or Python code)
- **Backward compat:** Yes — existing `/app/data` behavior unchanged; `/app/state` now properly permissioned
- **Image size:** Negligible (one additional `mkdir -p`)

---

## Governance

- All meaningful changes require team consensus
- Architectural decisions locked as of 2026-06-15 (Phase 5 - Ship)
- API format normalization enforced at client layer (never in scoring logic)
- TLA mapping is the single source of truth for team identification

---

## 29. Decision: Scenario-Aware Daily Update

# Decision: Scenario-Aware Daily Update

**Date:** 2026-06-16  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented  

## Context

The AI daily update (`generate_daily_update`) previously always produced a full HTML message regardless of whether there were matches. This led to confusing or empty posts on rest days.

## Decision

`generate_daily_update` now returns `str | None` and follows 4 scenarios based on whether yesterday had FINISHED matches and whether today has any matches (any status):

| has_yesterday | has_today | Scenario       | Result                                      |
|:---:|:---:|:---:|:---|
| ✗ | ✗ | — | **Return `None`** — callers skip post entirely |
| ✓ | ✗ | `"pausa"`      | Recap yesterday + standings frozen notice; `get_next_match` used for resume date |
| ✗ | ✓ | `"reanudacion"` | Competition resumes framing; no ayer section rendered |
| ✓ | ✓ | `"normal"`     | Unchanged full recap + preview |

## Key Implementation Details

### `generate_daily_update` → `str | None`
- Calls `get_football_day_matches` for both days before checking (both calls always made).
- Returns `None` early if both empty.
- For `"pausa"`: calls `client.get_next_match(settings.timezone)` and formats a Spanish date via `format_spanish_date()`.
- Passes `scenario`, `next_match`, `next_date_str` to `build_ai_user_message` and `render_message`.

### `render_message` section omission rules
- **Ayer section**: included only when `yesterday` is non-empty (never prints "Sin partidos ayer.").
- **Today section**: if `today` non-empty → fixtures; elif `scenario == "pausa"` → `⏸️ Hoy no hay partidos` with standings-frozen text and optional date; else → section omitted.
- **Porra section**: always present.

### Spanish date helper — `format_spanish_date(utc_date, tz_name) → str | None`
- Uses constant lists `_DIAS_ES` / `_MESES_ES` (no locale dependency).
- Returns `None` on any exception (graceful degradation).
- Example output: `"el sábado 20 de junio"`.

### Callers
- `daily_update_job` (`__main__.py`): `if text is None → log.info + return` (no `send_message`).
- `cmd_update_diario` (`handlers.py`): `if text is None → reply_text("🤷 No hay partidos ni ayer ni hoy…")`.

### AI system prompt (`_SYSTEM`)
Extended with per-scenario `standings_comment` guidance: `"normal"` / `"pausa"` / `"reanudacion"` instructions. User message now includes `ESCENARIO: {scenario}` line and, for `"pausa"`, a `PROXIMOS PARTIDOS:` line.

## Tests Added
19 new tests across: `TestFormatSpanishDate` (4), `TestRenderMessageScenarios` (7), `TestGenerateDailyUpdateScenarios` (5), `TestCmdUpdateDiarioNoneResult` (2), `TestDailyUpdateJob.test_does_not_send_when_result_is_none` (1).

**Final test count: 614 passing.**


## Decision: Strengthen today_notes to name armed conflicts concretely

# Decision: Strengthen today_notes to name armed conflicts concretely

**Author:** Kanté  
**Date:** 2026-06-16  
**Status:** Implemented

## Problem

Live diagnostics revealed that the `today_notes` AI field produced soft, vague notes for historically sensitive matchups:
- England vs Argentina → "rivalidad futbolera / mucha historia" — did NOT name the Falklands/Malvinas War.
- Israel vs Palestine → "partido sensible por el conflicto, mejor con respeto" — unnamed, unanchored.

The root cause was the `_SYSTEM` prompt treating armed conflicts as one optional item in a loose "notable rivalry or interesting fact" bucket, with no explicit priority ordering.

## Decision

Rewrote `_SYSTEM` in `src/worldcup_bot/ai/daily_update.py` with a **three-tier explicit priority**:

1. **ARMED CONFLICT (PRIORITY):** If the two nations share a current or historical armed conflict, war, military confrontation, or serious military-political tension → name it concisely and factually (e.g. "se enfrentaron en la Guerra de las Malvinas (1982)"). Informative and concrete, not euphemistic.
2. **OTHER GENUINE CURIOSITY:** Colonial history, notable territorial dispute, memorable past World Cup meeting — only if genuinely documented.
3. **EMPTY STRING:** If nothing genuine exists → return `""`. Forbidden: inventing facts, stretching weak connections, generic filler like "es un partido bonito".

### Structural change

The `today_notes` rule is now stated **up-front and unconditionally** before the scenario-specific `standings_comment` guidance. This prevents scenario branches (`reanudacion`, `pausa`) from causing the model to skip or dilute the notes.

## What did NOT change

- JSON-only output contract (`{"today_notes": {…}, "standings_comment": "…"}`)
- `today_notes` keyed by `HOME_TLA-AWAY_TLA`
- `standings_comment` ≤ 4–5 short sentences
- `max_completion_tokens=1500` usage
- `parse_ai_json` fallback behaviour
- Empty-string = no rendered note (correct, preserved)

## Tests

Added `TestSystemPromptContract` (5 tests) asserting:
- `_SYSTEM` contains "conflicto armado"
- `_SYSTEM` cites "Malvinas" as example
- `_SYSTEM` states the empty-string / "CADENA VACÍA" rule
- `today_notes` rule appears before `standings_comment` rule
- `_SYSTEM` explicitly forbids filler

**Final test count: 619 passing** (614 existing + 5 new).




## Decision: Match-Finish Stats Card + Porra Commentary

**Author:** Kanté (Backend)
**Date:** 2026-06-16
**Status:** COMPLETE — 702 tests green.

### Context

When a WC match finishes, the Telegram group should automatically receive:
- **Part A** — A rich match-stats card sourced from ESPN's public summary API, translated to Spanish.
- **Part B** — A short AI commentary (≤4 lines) about porra ranking changes, delivered in the voice of a randomly chosen Spanish football commentator.

### Decisions

#### 1. ESPN Stats API

- Endpoint: `GET https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={gameId}`
- League slug `fifa.world` works for WC2026 events; configurable via `ESPN_LEAGUE_SLUG`.
- `ESPNClient` is a thin sync `requests` wrapper; callers use `asyncio.to_thread` in the async job.
- `get_match_stats()` returns `None` on any error (log warning); callers degrade gracefully.
- Stat units: `possessionPct` already a %; `passPct` is a fraction 0-1 (×100 for display).
- Formatter omits rows whose stat is absent in both sides; omits red-cards row if both are 0.

#### 2. ESPN game ID via Reddit thread

- `RedditMatchScanner.get_espn_game_id(home, away)` reuses the existing `find_match_thread()` search, fetches the full thread HTML, and regexes `gameId=(\d+)` from the ESPN link embedded in the thread body.
- Returns `None` on any failure; job continues with Part B even if Part A has no game ID.

#### 3. Commentators pool

- `COMMENTATORS = ["Manolo Lama", "Julio Maldini", "Andrés Montes"]` — easily extensible list.
- Per-persona style hints embedded in the system prompt so the model mimics the persona's recognisable voice.
- `max_completion_tokens=400` (follows codebase rule: never `max_tokens`).

#### 4. Live ranking tracker (`porra/live.py`)

- State file: `{state_dir}/porra_live.json` — **different from** `porra_snapshot.json` (daily).
- Schema: `{username: {"pos": int, "pts": float, "name": str}}`.
- `diff_live(old, new)` returns a `LiveDiff` dataclass with `changed` bool, `movements` list, and `new_entries` list.
- Pts delta threshold for change detection: `> 0.001` (avoids float noise).
- Always `save_live()` after processing a finished match, even when AI is disabled, so the next match diffs against the latest state.

#### 5. `poll_finished_matches_job` dedup pattern

- On **first run**: seed `finished_seen` = all currently-finished IDs → return without sending. Mirrors goal-notifier seeding pattern.
- On **subsequent runs**: set diff (`current_finished - finished_seen`) yields newly-finished IDs.
- Each match is try/except isolated — one failure never breaks others.
- `espn_client` and `reddit_scanner` lazily initialised in `bot_data` (same pattern as goal notifier scanner).

#### 6. Config changes

Both new env vars have safe defaults so prod works without `docker-compose` changes (Maldini's domain):
- `ESPN_LEAGUE_SLUG` → default `"fifa.world"`
- `FINISHED_POLL_INTERVAL_SECONDS` → default `120`

### Files Changed / Created

| File | Change |
|------|--------|
| `src/worldcup_bot/espn/__init__.py` | New package |
| `src/worldcup_bot/espn/client.py` | New — ESPN HTTP client |
| `src/worldcup_bot/espn/formatter.py` | New — HTML stats card builder |
| `src/worldcup_bot/ai/commentators.py` | New — commentators pool + prompt builder |
| `src/worldcup_bot/porra/live.py` | New — live ranking tracker |
| `src/worldcup_bot/reddit/scanner.py` | Added `get_espn_game_id()` |
| `src/worldcup_bot/__main__.py` | Added `poll_finished_matches_job` + scheduling |
| `src/worldcup_bot/config.py` | Added `espn_league_slug`, `finished_poll_interval_seconds` |
| `tests/test_espn_client.py` | New — 11 tests |
| `tests/test_espn_formatter.py` | New — 18 tests |
| `tests/test_espn_scanner.py` | New — 6 tests |
| `tests/test_commentators.py` | New — 13 tests |
| `tests/test_porra_live.py` | New — 20 tests |
| `tests/test_poll_finished_job.py` | New — 15 tests |

**Final test count: 702 passing (619 baseline + 83 new).**

---

## Decision: Combined match-finish message, persona hidden, bold_person_names

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-16  
**Status:** IMPLEMENTED  

### Context

Three UX improvements requested for the porra bot's match-finish notification and participant-name display:

1. ESPN stats card and porra commentary were sent as two separate Telegram messages; user wants one combined message.
2. The `🎙️ Manolo Lama:` prefix was exposing which AI persona narrated the commentary; user wants the style to be hidden.
3. Participant display_names appear in multiple views (commentary, daily standings, ranking/detail commands) without visual emphasis; user wants them in bold across all outputs.

### Decisions

#### 1. Combined match-finish message

`poll_finished_matches_job` collects `stats_text` (Part A, from ESPN) and `commentary_text` (Part B, from AI) separately, then sends **one** `send_message(parse_mode="HTML")` call with:

```
{stats_text}

----

{commentary_text}
```

If only one part is available, send it alone (no separator). If neither is available, send nothing.

**Rationale:** Keeps the chat cleaner (one notification per match instead of two) and makes the `----` separator visually group the two sections as a single atomic post.

#### 2. Persona hidden — style-only

- Removed the `🎙️ {persona}:` prefix from the sent message.
- Added `"No firmes ni menciones tu propio nombre."` to `build_commentary_messages` system prompt so the model doesn't self-identify either.
- `pick_commentator()` is still called: the selected persona drives the **style** of generation but its name is never surfaced.

**Rationale:** The persona is an internal style directive, not content the user needs to see; hiding it removes clutter and avoids confusion about imaginary commentators.

#### 3. `bold_person_names` helper + HTML everywhere

Added `bold_person_names(text: str, names: Iterable[str]) -> str` to `bot/formatters.py`:
- HTML-escapes the input text.
- Sorts names by length descending (longest-first, prevents partial overlaps).
- Matches with `(?<!\w)…(?!\w)` Unicode word boundaries to handle accented names (Peñalver, Tarragó) and multi-word names ("Maria Tarrago") correctly.
- Single regex pass → no double-wrapping.

Applied to:
- `poll_finished_matches_job`: commentary bolded before combining.
- `render_message` (daily update): `standings_comment` bolded; `participant_names` passed in from `generate_daily_update`.
- `format_general_ranking`: display_names in `<b>…</b>` directly in the formatter.
- `format_user_detail`: display_name header in `<b>…</b>`; Markdown `*…*` replaced with HTML `<b>…</b>`.
- `cmd_participantes`: display_names wrapped in `<b>…</b>`, `parse_mode="HTML"`.
- `_send_ranking_with_top3_photos`: all `reply_text` calls and `InputMediaPhoto` captions use `parse_mode="HTML"`.
- `_send_user_detail`: changed `parse_mode="Markdown"` → `parse_mode="HTML"`.

**Rationale:** HTML is already used by the daily update; unifying all user-facing messages to HTML simplifies the mental model and enables safe name bolding without the ambiguity of Telegram's Markdown V1 escaping rules.

### Test impact

- 702 baseline → **733 passing** after adding 31 new tests.
- New file: `tests/test_formatters.py` (25 `bold_person_names` tests).
- Updated: `test_poll_finished_job.py`, `test_handlers.py`, `test_ai.py`, `test_commentators.py`.

---

