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


# Decision: porra-evolution checkpoints by jornada (football-day reconstruction)

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** DONE — 950 tests green

---

## Context

The original `/evolucion` feature (BLOCK 4) computed ranking history keyed by local
calendar date and reconstructed group standings via the `?date=` query parameter of the
football-data.org standings endpoint. That approach had a fundamental flaw: consecutive
football-days share UTC calendar dates (a match at 02:00 local on June 14 is still
June 13 UTC), so the `?date=` param cannot represent the 9am→9am football-day window
that `/hoy` and `/ayer` use.

## Decision

**Rebuild checkpoints entirely from match results, keyed by football-day label.**

The "football-day" is the same 9am→9am window (configurable via `settings.football_day_start_hour`)
already used by `get_football_day_matches`. A match's football-day label is:
- local date if `local_hour >= anchor_hour`
- local date minus 1 day otherwise

Group standings are **reconstructed** from the match results directly (points W=3/D=1/L=0,
GD, GF, then TLA alpha for remaining ties). Knockout winners come from finished knockout
matches in the same pass. No `?date=` API calls are made during history construction.

## Key new functions (`porra/history.py`)

| Function | Purpose |
|---|---|
| `football_day_of(match, tz, anchor_hour)` | Football-day label for a match (YYYY-MM-DD) |
| `build_jornadas(matches, tz, anchor_hour)` | Sorted distinct jornadas with ≥1 finished match |
| `reconstruct_group_standings(finished_group_matches)` | Points/GD/GF ordering per group |
| `compute_ranking_at_jornada(predictions, all_matches, jornada, tz, anchor_hour)` | Full ranking as of a jornada |
| `_check_reconstruction_vs_api(reconstructed, api_standings_raw)` | Sanity-log top-3 match vs live API |

`ensure_history` calls `get_all_matches()` once, derives all jornadas, reconstructs all
rankings from that single batch. The sanity check logs `INFO` on full match, `WARNING`
with per-group diffs on any top-3 mismatch (tie-break differences are acceptable).

## Removed dead code

- `build_checkpoint_dates` (replaced by `build_jornadas`)
- `engine.compute_ranking_at_date` (used `?date=` param, now unused)

`get_standings(date=...)` is **kept** in `api/client.py` (harmless, tested separately).

## Chart fixes

- matplotlib title: removed `📈` emoji → "Evolución de la porra" (DejaVu Sans has no emoji glyph, causing missing-box rendering)
- x-axis: labels changed from `YYYY-MM-DD` to `DD/MM` short form; axis label "Jornada" instead of "Fecha"
- Telegram caption in `cmd_evolucion` keeps `📈` (Telegram renders emoji fine)

## Test count

936 → **950** (+14). Removed `TestBuildCheckpointDates` (6) + `TestComputeRankingAtDate` (7);
added `TestFootballDayOf` (5) + `TestBuildJornadas` (7) + `TestReconstructGroupStandings` (9)
+ `TestComputeRankingAtJornada` (4) + updated `TestEnsureHistory` (7) + chart tests (2).


---

# Decision: porra-evolution exact latest jornada + startup/daily backfill

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 962 tests green.

## Context

`porra/history.py ensure_history` was building per-jornada ranking history by reconstructing group standings from match results for ALL jornadas, including the latest. The reconstruction approximates FIFA tie-breaks (no head-to-head), so the latest data point could differ ±1–2 positions from the live `/actual` ranking. Additionally, history was only populated when a user ran `/evolucion`.

## Decisions

### 1. Latest jornada uses exact live ranking

**Decision:** For the latest (most recent) jornada only, `ensure_history` now calls `engine.compute_general_ranking(predictions, client, official=False)` instead of `compute_ranking_at_jornada`. Past jornadas keep using reconstruction (acceptable approximation for a trend chart).

**Rationale:** The newest data point in the chart is the most visible and most compared against `/actual`. Using the exact live ranking eliminates the tie-break mismatch at the tip of the chart. The reconstruction is still accurate enough for the trend shape of all past jornadas.

**Implementation:**
- Inside the `for jornada in jornadas` loop, branch on `if jornada == latest`.
- Import `engine` lazily inside `ensure_history` (already the pattern for `compute_ranking_at_jornada`).
- Removed `_check_reconstruction_vs_api` and `_safe_jornada_le` helpers — they were only used by the now-removed sanity check. The sanity check was comparing reconstruction to API; it's no longer needed since the latest is exact.

### 2. Auto-backfill at startup + daily refresh

**Decision:** `history_backfill_job` is scheduled unconditionally (not gated on `telegram_group_id`) in `main()`:
- `run_once(history_backfill_job, when=15)` — 15 seconds after startup, to populate the volume on first launch.
- `run_daily(history_backfill_job, time=dtime(9,5,tzinfo=tz))` — 09:05 local time daily, just after the typical football-day close window (09:00).

**Rationale:** Users should not have to run `/evolucion` to trigger history generation. The volume should be pre-populated so the command is fast (only latest jornada recomputed). The daily refresh at 09:05 catches newly-completed jornadas automatically.

**Implementation note:** `history_backfill_job` wraps everything in `try/except` so it can never crash other jobs. Skips early if predictions file has no participants.

### 3. `/evolucion` command unchanged

`cmd_evolucion` still calls `ensure_history` (incremental) on demand. Since past jornadas are cached in the JSON file and only the latest is recomputed, the command is fast.

## Files changed

- `src/worldcup_bot/porra/history.py` — modified `ensure_history`; removed `_check_reconstruction_vs_api`, `_safe_jornada_le`
- `src/worldcup_bot/__main__.py` — added `history_backfill_job`; added `run_once` + `run_daily` scheduling in `main()`; added `from worldcup_bot.porra.history import ensure_history` import
- `tests/test_history.py` — updated `TestEnsureHistory` to patch `worldcup_bot.porra.engine.compute_general_ranking` for latest-jornada tests; added `TestEnsureHistoryLatestUsesLiveRanking` (3 tests)
- `tests/test_history_backfill.py` (NEW) — 9 tests covering job behaviour + scheduling wiring


---

# Decision: Porra Evolution Chart — /evolucion command

**Author:** Kanté (Backend)
**Date:** 2026-06-17
**Status:** READY — 936 tests green, awaiting coordinator commit + container rebuild.

---

## Summary

Adds `/evolucion` — a Telegram photo command that renders a **bump chart** showing how the porra (prediction-pool) ranking has evolved over the tournament, one line per participant.

---

## Architecture Decisions

### 1. `get_standings(date=...)` — backward-compatible param extension
- Added optional `date: str | None = None` to `FootballDataClient.get_standings()`.
- Extended `_get(url, params=None)` to accept optional query-params dict; cache key is deterministically built as `url?key=val` (sorted), so `no-date` and `with-date` have distinct cache entries.
- No existing callers need changes — `date=None` produces identical behaviour to the old signature.

### 2. Dependency-injection refactor in `engine.py`
- Extracted `compute_general_ranking_from(predictions, actual_standings, actual_winners)` — the pure scoring loop with no client dependency.
- `compute_general_ranking` retains its current signature and delegates to it (zero behaviour change; all existing tests pass).
- `compute_ranking_at_date(predictions, client, date)`:
  - Calls `client.get_standings(date=date)` for historical group standings.
  - Filters to groups with `played > 0` (safe for partially-started days).
  - Derives knockout winners from `client.get_all_matches()` filtered by `status=FINISHED` and `utc_date <= {date}T23:59:59Z` — string comparison works because format is ISO UTC.
  - Returns `compute_general_ranking_from(...)`.

### 3. History module (`porra/history.py`)
- Persistence file: `{state_dir}/porra_history.json` — dict keyed by `"YYYY-MM-DD"`, values `{username: {pos, pts, name}}`.
- `build_checkpoint_dates`: converts FINISHED match UTC timestamps → local dates via pytz (settings.timezone), deduplicates, returns sorted list.
- `ensure_history`: for each checkpoint NOT in stored history → compute; **always recompute the latest date** so it stays fresh. Best-effort save. API errors return existing history unchanged.

### 4. Chart (`porra/chart.py`)
- `matplotlib.use("Agg")` set at module import time (before pyplot) — no display/GUI required in container.
- Bump chart: x = dates (sorted), y = rank (1 at top, `ax.invert_yaxis()`), one line+markers per participant, `tab20` colormap for up to 20 users, legend outside right panel.
- Degenerate cases (0 dates, 0 users, 1 date) all handled — always write a valid PNG.
- Font warning for 📈 glyph is cosmetic only (DejaVu Sans fallback); PNG is valid.

### 5. `matplotlib>=3.8` in `pyproject.toml`
- Wheels are self-contained on `python:3.12-slim`; no additional system libs needed for the Agg backend.

---

## Public API for E2E (coordinator)

```python
from worldcup_bot.porra.history import ensure_history
from worldcup_bot.porra.chart import render_evolution_png
```

- `ensure_history(client, predictions, settings, path)` — build history from live API, returns dict.
- `render_evolution_png(history, out_path)` — render PNG, returns out_path.

---

## Caveats

- The emoji `📈` in the chart title renders as a missing-glyph box on the default matplotlib font (DejaVu Sans). This is cosmetic — the PNG is valid and the chart is readable. A font upgrade in the container could fix it but is not required.
- `ensure_history` re-fetches the latest checkpoint date on every invocation of `/evolucion`. With the shared TTL cache this is a cache hit most of the time.


---

# Decision: Changelog from Commit-Body Bullets

**Author:** Maldini (DevOps)  
**Date:** 2026-06-17  
**Status:** DONE — workflow updated, verified locally.

## Context

The `docker-deploy.yml` "Generate release notes from commits" step previously used `git log --pretty='%s'` to generate one bullet per commit subject line. For a squash-merge commit this yields a single generic bullet even when the body contains detailed, itemised bullet points.

## Decision

Replace the shell grep/sed chain with a `python3 - <<'PYEOF'` quoted heredoc. The Python script:

1. Determines range: `prev = git describe --tags --abbrev=0`; `rng = "{prev}..HEAD"` if prev else `"HEAD"`.
2. Enumerates commit SHAs via `git log rng --no-merges --format=%H`.
3. For each SHA: fetches full message via `git log -1 --format=%B`; skips commits whose subject starts with `.squad:`, `chore:`, `docs: update changelog`, or `merge ` (case-insensitive).
4. Scans the body for bullet blocks: lines starting with `- ` (after optional indent) begin a bullet; lines with 2+ leading spaces that follow a bullet are continuations (folded with a single space); any blank or non-bullet non-indented line ends the block; scanning stops at `Co-authored-by:` trailer.
5. Emits body bullets verbatim (prefixes kept). Falls back to `- {subject}` when no body bullets exist.
6. Writes to stdout; redirected to `release_notes.md`.

## Rationale

Squash commits produced by the team contain rich bullet-per-change bodies. The old approach discarded that information. The Python heredoc handles multi-line folding, trailer exclusion, and internal-commit filtering reliably without requiring extra shell tools.

## Verification

Local test against range `20260617.04^..48edda9` (single commit `48edda9`) produced 4 elaborate folded bullets:

```
- Detect goals from football-data SCORE CHANGES (reliable; ends the Reddit-parse flip-flop) with persistent per-match score state. Enrich scorer/minute via an OpenAI information extractor that handles any r/soccer thread format (ESPN-structured or human-narrated). VAR score decreases post a Gol anulado.
- Send the goal message immediately WITHOUT a button; a 45s job polls for the clip, downloads it to the state volume, then edits the message to add the Ver gol button; the tap replies with the video. Survives restarts.
- Match-finish ALWAYS posts a Final result; ESPN stats card when available; and ALWAYS a /porra recap by a random commentator (acknowledges when nothing moved), sections separated by ---.
- New /estadisticas command: a persistent per-user Ver gol view counter.
```

YAML parse: `python -c "import yaml; yaml.safe_load(open('.github/workflows/docker-deploy.yml'))"` → exit 0.

## Files Changed

- `.github/workflows/docker-deploy.yml` — "Generate release notes from commits" step `run:` block replaced.

---

## 43. Decision: Clip-match fix — D.R. Congo dotted-name normalization + dropr.co host + generic media-URL fallback

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — awaiting coordinator commit

### Context

Live production failure: `find_goal_clip` returned `None` for the goal "Portugal 1-0 D.R. Congo, João Neves 6'" even though the r/soccer clip post was found. Post title: `"Portugal [1] - 0 D.R. Congo - Neves J. goal 5'"`, post URL: `https://dropr.co/v/3ba063ff`. Two independent bugs caused the failure.

---

### Bug 1 — Team normalization dropped dotted abbreviations ("D.R. Congo")

**File:** `src/worldcup_bot/reddit/scanner.py`  
**Function:** `_normalize_team`

#### Root cause
`_normalize_team("D.R. Congo")` lowercased to `"d.r. congo"`, which is not a key in `WC_TEAM_ALIASES` (the existing key is `"dr congo"`), so the function returned `"d.r. congo"` unchanged. `_teams_match("D.R. Congo", "Congo DR")` therefore returned `False`.

#### Fix
In `_normalize_team`, after lowercase + accent-strip, add:
```python
key = key.replace(".", " ")
key = re.sub(r"\s+", " ", key).strip()
```
This transforms:
- `"D.R. Congo"` → `"d.r. congo"` → `"d r congo"` → alias → `"congo dr"` ✓
- `"D.R.Congo"` → `"d.r.congo"` → `"d r congo"` → alias → `"congo dr"` ✓

Two new alias entries added to `WC_TEAM_ALIASES`:
- `"d r congo": "congo dr"` — handles dotted "D.R. Congo" and "D.R.Congo"
- `"dem rep congo": "congo dr"` — handles "Dem. Rep. Congo" through the same transform (existing `"dem. rep. congo"` entry kept for backward compat)

---

### Bug 2 — Media URL host allowlist missed dropr.co (and was brittle)

**File:** `src/worldcup_bot/reddit/clip_finder.py`  
**Function:** `_extract_media_url`

#### Root cause
`VIDEO_URL_RE` listed only `streamable.com`, `v.redd.it`, `streamin.(me|link)`, `streamain.com`, `dubz.link`. `dropr.co` was not included, so `_extract_media_url("https://dropr.co/v/3ba063ff")` returned `None`. The "Ver gol" button was therefore never emitted even though the clip was there.

#### Fix (a) — Add dropr.co to known hosts
`dropr\.co` added to `VIDEO_URL_RE` alternation.

#### Fix (b) — Generic HTTPS fallback for future host rotation
After the known-host checks, `_extract_media_url` now applies a conservative fallback: if the URL is `http(s)` and:
- does NOT contain `reddit.com`, `redd.it`, or `imgur.com`
- path does NOT end in `.jpg/.jpeg/.png/.gif/.webp` (case-insensitive, query string ignored)

…then the URL is returned as-is as the media URL.

**Rationale:** `_match_post` only calls `_extract_media_url` after the post title has already been validated by `GOAL_TITLE_PATTERN` + team/score/scorer-or-minute checks. A title-matched post's external URL is the clip, regardless of host. The downloader's yt-dlp fallback handles playback from unknown hosts. This prevents future clip-host rotations from silently killing the "Ver gol" button again.

---

### Tests added

#### `tests/test_reddit_scanner.py` — `TestNormalizeTeam` (7 assertions)
- `_normalize_team("D.R. Congo") == "congo dr"`
- `_normalize_team("D.R.Congo") == "congo dr"`
- `_normalize_team("DR Congo") == "congo dr"` (existing alias still works)
- `_normalize_team("Democratic Republic of Congo") == "congo dr"` (existing alias still works)
- `_normalize_team("Portugal") == "portugal"` (no alias, unchanged)
- `_teams_match("D.R. Congo", "Congo DR") is True`
- `_teams_match("D.R.Congo", "Congo DR") is True`

#### `tests/test_clip_finder.py` — `TestExtractMediaUrl` (10 cases extended)
- `dropr.co` → returned as-is (known host)
- novel host `newcliphost.xyz` → returned as-is (generic fallback)
- `i.redd.it/abc.jpg` → `None` (redd.it excluded)
- `www.reddit.com/r/soccer/…` → `None` (reddit excluded)
- `imgur.com/a/x` → `None` (imgur excluded)
- `host.com/pic.PNG` → `None` (static image, case-insensitive)
- `cdn.example.com/image.jpeg` → `None` (static image)
- `newcliphost.xyz/v/clip?thumb=preview.jpg` → returned (`.jpg` only in query string, path is clean)

#### `tests/test_clip_finder.py` — `TestMatchPost`
- `test_portugal_dr_congo_dotted_name_dropr_url`: exact live-failure scenario — `_match_post` for the "Portugal [1] - 0 D.R. Congo - Neves J. goal 5'" post returns `"https://dropr.co/v/3ba063ff"`.

#### `tests/test_clip_finder.py` — `TestFindGoalClip`
- `test_portugal_dr_congo_dropr_integration`: full `find_goal_clip` with injected fake scanner returns the dropr.co URL.

---

### Result

**1152 tests green** (baseline was 1135).


---



## 43. Decision: Remove dead date= parameter from get_standings

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Status:** Applied (not committed)

### Context

The porra-evolution feature (BLOCK 4b) rewrote history reconstruction to use match results directly — zero ?date= API calls. An earlier prototype had added an optional date: str | None = None parameter to FootballDataClient.get_standings() that built a ?date=YYYY-MM-DD query string. No production caller ever passed a date (both ngine.py and handlers.py call get_standings() with no args), making it dead code.

### Decision

Remove the date parameter and all supporting code. Specifically:

1. **pi/client.py** — get_standings() signature simplified; params = {"date": date} if date else None branch removed; docstring updated.
2. **	ests/test_api_client_date_param.py** — deleted (6 tests, all specific to the dead param).
3. **	ests/test_history.py** — 	est_no_get_standings_with_date_called renamed to 	est_get_standings_not_called_from_ensure_history; replaced per-call kwargs.get("date") is None loop with ssert_not_called().

### Rationale

- The ?date= path was never wired to any live feature; keeping it creates a misleading API surface and unnecessary test burden.
- Removing it makes the signature honest: get_standings() always returns current live standings.
- The replacement assertion (ssert_not_called) is a stronger and clearer guard than the old loop.

### Test result

956 passed (was 962; −6 = deleted date-param tests). All other tests green, no behavior change.

---

## 44. Decision: Rich Image Daily Evolution

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — pending live test once gpt-image-2 key access is granted in LiteLLM.

### Feature

Every day at 11:00 Europe/Madrid, the bot takes a "rich" person image and asks
gpt-image-2 to edit it: keep the exact same face/identity, but make them progressively
wealthier. Each iteration overwrites the previous evolved image, so changes accumulate
over days.

### Key Decisions

#### 1. Data is read-only → iterated image lives in state volume
./data is mounted :ro (confirmed by Maldini). The base original is
/app/data/rich/rich_original.jpg. The iteratively-evolved image MUST live in the
writable state volume at {settings.state_dir}/rich_modified.png. On the first run, the
base original is used as source; on every subsequent run, the previously-written
ich_modified.png is used, chaining naturally.

#### 2. Level persistence via small JSON
A tiny {state_dir}/rich_state.json → {"level": int} tracks the current wealth level.
load_level returns 0 on missing/corrupt file (safe default). save_level creates the
directory if needed.

#### 3. Prompt constant lives in i/rich_image.py — easy to find and tweak
RICH_EDIT_PROMPT (module-level str) holds the base identity-preservation mandate. An
_ESCALATION_CLAUSES list (indexed by level, 0–9) provides the per-level craziness
clause. uild_rich_prompt(level) concatenates them. The user only needs to touch
ich_image.py to adjust the creative direction.

#### 4. Image-specific API credentials with fallback to chat credentials
Three new env vars: OPENAI_IMAGE_API_KEY, OPENAI_IMAGE_BASE_URL, OPENAI_IMAGE_MODEL.
If the image-specific key/url are empty, _effective_image_api_key /
_effective_image_base_url fall back to the chat key/url. This means no new env vars are
strictly required if both chat and image share the same LiteLLM endpoint.

#### 5. Soft opt-in via image_ai_enabled(settings)
The job only runs (and is only scheduled) if image_ai_enabled returns True. The job
never raises — any error is logged and swallowed.

#### 6. ich_image_chat_id — separate from 	elegram_group_id
Sending the evolved image goes to RICH_IMAGE_CHAT_ID, defaulting to empty (job still
generates and saves but doesn't send). The porra group and the image recipient can be
different. For testing, the user sets it to 3041850.

### Blocker (at time of writing)

LiteLLM key access to gpt-image-2 not yet granted — **user is fixing this in LiteLLM**.
This is NOT a max_tokens issue (images.edit has no token limit). The code is complete;
the coordinator will run a live 5-iteration test once access is confirmed.

### Files

| File | Change |
|------|--------|
| src/worldcup_bot/config.py | +5 settings fields, +3 helpers (image_ai_enabled, _effective_image_api_key, _effective_image_base_url) |
| src/worldcup_bot/ai/rich_image.py | NEW — RICH_EDIT_PROMPT, uild_rich_prompt, select_base_image, load_level, save_level, dit_rich_image, un_rich_iteration |
| src/worldcup_bot/__main__.py | +import, +ich_image_job, +scheduling in main() |
| 	ests/test_rich_image.py | NEW — 52 tests, all green |

---

## 45. Decision: Rich Image Daily Feature — Environment Variable Wiring

**Date:** 2026-06-17 13:55:52Z  
**Owner:** Maldini (DevOps)  
**Status:** ✅ COMPLETED  
**Requester:** David (@DrDonoso)  

### Summary

Wired up five environment variables across docker-compose.yml, docker-compose.local.yml, and .env.example to support Kanté's daily image-generation feature (gpt-image-2 via LiteLLM at 11:00).

### Changes

#### 1. docker-compose.yml (Production)

Added to worldcup-bot service nvironment: block (after DAILY_UPDATE_HOUR):

`yaml
      # --- Daily 'rich' image evolution (gpt-image-2 via LiteLLM) ---
      OPENAI_IMAGE_MODEL: "${OPENAI_IMAGE_MODEL:-gpt-image-2}"
      OPENAI_IMAGE_API_KEY: "${OPENAI_IMAGE_API_KEY:-}"
      OPENAI_IMAGE_BASE_URL: "${OPENAI_IMAGE_BASE_URL:-}"
      RICH_IMAGE_HOUR: "${RICH_IMAGE_HOUR:-11}"
      RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"
`

#### 2. docker-compose.local.yml (Local Development)

Identical 5 vars added to worldcup-bot service nvironment: block.

#### 3. .env.example

Added documentation block:

`ash
# Optional — Daily 'rich' image evolution via gpt-image-2 (LiteLLM at 11:00 by default).
# OPENAI_IMAGE_MODEL=gpt-image-2
# OPENAI_IMAGE_API_KEY=your-litellm-key (if empty, falls back to OPENAI_API_KEY)
# OPENAI_IMAGE_BASE_URL=https://your-litellm-host/v1 (if empty, falls back to OPENAI_BASE_URL)
# RICH_IMAGE_HOUR=11 (24h local time; default 11)
# RICH_IMAGE_CHAT_ID=3041850 (chat ID where the daily image is sent; if empty, image is generated+saved but not sent)
`

### Implementation Notes

- **Defaults:** OPENAI_IMAGE_MODEL defaults to gpt-image-2; RICH_IMAGE_HOUR defaults to 11 (24h local time).
- **Optional fallbacks:** OPENAI_IMAGE_API_KEY and OPENAI_IMAGE_BASE_URL fall back to OPENAI_API_KEY and OPENAI_BASE_URL respectively if unset (in-app logic, Kanté owns this).
- **Test value:** RICH_IMAGE_CHAT_ID example uses 3041850 (David's test chat); empty disables send (image still generated and saved to state volume).
- **Storage:** Iterated image written to existing ot_state:/app/state named volume. Base image at ./data/rich/rich_original.jpg (existing read-only mount). No new volumes.

### Validation

Both compose files validated cleanly:

`ash
$ docker compose -f docker-compose.local.yml config -q
# exit 0

$ docker compose -f docker-compose.yml config -q
# exit 0 (unset vars produce warnings only; no YAML syntax errors)
`

### Next Steps

Kanté will add logic to config.py to:
1. Read these five vars via environment.
2. Provide safe defaults (already specified above).
3. Enable the daily image generation job at the specified hour.

**Decision ID:** maldini-rich-image-env  
**Related:** Kanté's daily image feature (in progress)  
**Blocked by:** None  
**Blocking:** Kanté's config.py integration (will receive these via environment)

---

## 18. Decision: Rich-image caption + pose iteration

**Date:** 2026-06-17T15:04:47+02:00  
**Author:** Kanté (Backend Developer)

### Context

Extended the daily rich-image evolution feature built earlier today.

### Decisions

#### 1. Caption uses the main chat model (multimodal), not the image model key

`generate_rich_caption` uses `settings.openai_api_key` / `settings.openai_base_url` / `settings.openai_model` — not the image-specific variants. Rationale: the caption is a text-generation task sent to a multimodal chat endpoint (GPT-5.4 / LiteLLM). The image model key is for `images.edit` only.

#### 2. Temp-rename pattern preserves OLD image for before/after comparison

`run_rich_iteration` writes new PNG bytes to `{state_dir}/rich_modified.new.png` **before** replacing the old `rich_modified.png`. This keeps the OLD image alive so it can be base64-encoded and sent to the caption model. Only after the caption is generated is the temp atomically renamed via `os.replace`. If the old final exists it is removed first (Windows `os.replace` compatibility).

#### 3. Destination is `telegram_group_id` — `RICH_IMAGE_CHAT_ID` removed entirely

`rich_image_chat_id` setting and `RICH_IMAGE_CHAT_ID` env var removed. The photo is sent to `settings.telegram_group_id` (the same group used for goal notifications and daily updates). Sending to a separate chat_id was an unnecessary surface area.

#### 4. LiteLLM rejects legacy `max_tokens` — use `max_completion_tokens`

`generate_rich_caption` uses `max_completion_tokens=300` (not `max_tokens`). The user's LiteLLM proxy rejects the legacy parameter.

#### 5. Caption is best-effort — never fatal

If the main chat is not configured (any of `openai_api_key`, `openai_base_url`, `openai_model` is empty) or if the caption API call fails, `run_rich_iteration` falls back silently to `🤑 Nivel de riqueza {level}` (with a `log.warning` on API failure). The image is always written.

#### 6. `_caption_client` and `_client` are independent injectables

Tests can mock image editing and caption generation independently. This keeps unit tests fast and reliable without network calls.

---

## 19. Decision: Rich Image — Bounded Text History, JSON Caption+Memo, History in Both Generators

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 1052 tests green (+26)

### Context

The live E2E confirmed that rich-image captions and images work, but after a few days items started repeating (Rolls, yacht, same vacations). The user requested a persisted text history fed to both generators to avoid repetition, plus richer image composition variation.

### Decisions

#### 1. Bounded plain-text history — `rich_history.txt`, cap 20 lines

A plain-text file at `{state_dir}/rich_history.txt` accumulates one line per successful iteration:
```
{date_str} | nivel {level} | {memo}
```
After every append, the file is truncated to keep only the **last 20 lines** (`RICH_HISTORY_MAX_LINES = 20`). This bounds the token cost injected into prompts while preserving enough context to avoid repetition across several weeks.

- `append_history(state_dir, date_str, level, memo)` — appends + truncates; skips if memo is empty/whitespace.
- `load_history_lines(state_dir) -> list[str]` — returns stripped non-blank lines, [] if missing/corrupt.
- `format_history_for_prompt(state_dir) -> str` — bullet-list with "- " prefix, or "" if empty.

#### 2. Caption returns JSON `{"caption": "...", "memo": "..."}`

`generate_rich_caption(...)` now returns `tuple[str, str]` = (caption, memo):

- The model is instructed to return **only** a JSON object.
- On successful parse: returns (caption, memo).
- On any JSON parse failure: returns (raw_stripped_text, "") — feature never breaks.
- Code-fence stripping handles ` ```json ... ``` ` wrapper the model may add.
- `max_completion_tokens` raised from 300 → 500 to accommodate JSON overhead.
- API/transport errors still raise RuntimeError (caller handles fallback).

#### 3. Context: person rigs our porra

`RICH_CAPTION_PROMPT` updated to make explicit that:
- The person is getting rich by **rigging the group's porra** (amañando la porra del grupo).
- Tone stays chulesco/prepotente/burlón but from the position of cheating-the-group superiority.

#### 4. History fed to BOTH generators

In `run_rich_iteration`:
1. `history = format_history_for_prompt(settings.state_dir)` (previous days).
2. `build_rich_prompt(level, history)` — when history non-empty, appends "Previously shown across past days (introduce NEW, different luxuries/scenes/people; do NOT repeat these): {history}".
3. `generate_rich_caption(..., history=history)` — when history non-empty, user message includes "YA HAS PRESUMIDO DE ESTO ANTES — NO lo repitas:\n{history}".
4. `append_history(state_dir, date_str, level, memo)` persists the new memo after caption.

#### 5. Image composition variation — CHANGE A

`RICH_EDIT_PROMPT` updated to explicitly ENCOURAGE:
- Freely changing the person's **POSTURE and POSE**.
- Bringing **HANDS** into view with gestures (holding objects, arms open, pointing, etc.).
- **INCLUDING OTHER PEOPLE** around the main subject (entourage, friends, staff, models, guests, bodyguards) — only the MAIN subject's identity must be preserved.

### Files Changed

- `src/worldcup_bot/ai/rich_image.py` — all changes above
- `tests/test_rich_image.py` — +26 tests (1052 total, up from 1026)

---

## 20. Consolidate Rich Image Destination to TELEGRAM_GROUP_ID

**Decision ID:** maldini-remove-rich-chat-id  
**Date:** 2026-06-17T15:07:58Z  
**Agent:** Maldini (DevOps)  
**Requested by:** David (@DrDonoso)

### Problem

The rich-image daily feature had previously been wired to send images to a separate `RICH_IMAGE_CHAT_ID`. The destination is now consolidated: images go to the existing `TELEGRAM_GROUP_ID` (the shared group). The `RICH_IMAGE_CHAT_ID` env var is no longer needed.

### Decision

Remove `RICH_IMAGE_CHAT_ID` from environment configuration entirely. Keep the other 4 image-generation vars (`OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_API_KEY`, `OPENAI_IMAGE_BASE_URL`, `RICH_IMAGE_HOUR`).

### Changes

#### Files Modified

1. **docker-compose.yml** (prod)
   - Removed `RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"` from `worldcup-bot` service environment block.
   - Kept 4 image vars: `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_API_KEY`, `OPENAI_IMAGE_BASE_URL`, `RICH_IMAGE_HOUR`.

2. **docker-compose.local.yml** (dev)
   - Removed `RICH_IMAGE_CHAT_ID: "${RICH_IMAGE_CHAT_ID:-}"` from `worldcup-bot` service environment block.
   - Kept 4 image vars (same as prod).

3. **.env.example**
   - Removed `RICH_IMAGE_CHAT_ID=3041850` line.
   - Removed explanatory comment: "chat ID where the daily image is sent; if empty, image is generated+saved but not sent".
   - Updated section comment from "Daily 'rich' image evolution" to clarify: "Image is sent to TELEGRAM_GROUP_ID."

### Validation

Both compose files parse cleanly after changes:
```
docker compose -f docker-compose.local.yml config -q   # exit 0
docker compose -f docker-compose.yml config -q          # exit 0
```

### Rationale

- Simplifies configuration: one group ID instead of two.
- Reduces env-var surface: fewer optional vars to document and manage.
- Aligns with Kanté's code logic: image destination is now hardcoded to the group.

### Impact

- ✅ **Dev/test:** No image regression; local compose still builds and validates.
- ✅ **Prod:** No change in deployment model; Kanté owns runtime logic.
- ⚠️ **Existing containers:** If `RICH_IMAGE_CHAT_ID` was set in production, it will be ignored (not an issue since feature is new).

### Notes

- No code changes (`config.py` / `src/**` owned by Kanté).
- No git commit (as requested).
- History logged in `.squad/agents/maldini/history.md`.

---


---

# Decision: Rich Caption Newline Normalization + Escalate Opulence Emphasis

**Date:** 2026-06-17
**Author:** Kanté (Backend Developer)
**Status:** Implemented

## Context

Two issues surfaced after the hybrid face-anchor feature went live:

1. **Literal `\n` in captions**: The caption model occasionally returns the two characters `\` and `n` (backslash-n) instead of a real line break — e.g. `"...humor.\\nMe he fugado..."`. Telegram renders these as literal text rather than line breaks, breaking the visual layout.

2. **Opulence not escalating visibly**: The prompt did not emphasize that each iteration MUST look *more* luxurious than the one before. Users reported the richness plateau-ing or varying randomly rather than clearly escalating. An optional accessories angle (sunglasses/hat) was also requested to add visual variety.

## Decision

### 1. `_normalize_caption(text: str) -> str`

New private helper in `rich_image.py`:
- Replaces literal `\\r\\n` and `\\n` sequences with real newlines (handles the backslash-n quirk).
- Normalizes real `\r\n` → `\n`.
- Collapses 3+ consecutive newlines to exactly 2.
- Strips trailing spaces on each line and strips the whole string.

Applied to the `caption` return value in `generate_rich_caption` (both the JSON `data["caption"]` path and the non-JSON fallback `raw` path). The `memo` is trimmed (`.strip()`) but not run through the multi-line normalizer — it is intentionally single-line.

### 2. `RICH_EDIT_PROMPT` — escalation emphasis + accessories

Added a CRITICAL-labelled sentence as the leading instruction:

> "CRITICAL: the result MUST look clearly and NOTICEABLY richer and more luxurious than the input image — escalate the opulence visibly each iteration: a more expensive outfit, a grander setting, more lavish props and wealth signals than before."

Added optional accessories line:

> "You MAY occasionally add tasteful accessories such as elegant sunglasses or a stylish hat (vary it; not every time)."

All moderation-safe framing is preserved: positive dressing language ("dress in a fully-clothed luxury outfit", "tasteful", "elegant"), no "change/remove/alter clothing" phrasing.

### 3. `RICH_FACE_ANCHOR_CLAUSE` — surpass framing

Updated to reinforce escalation in the anchor path:

> "Use the first image for the wealthy style, but SURPASS it — the new image must look clearly richer and more luxurious than the first, not merely match its opulence."

The face-anchor-to-original instruction (EXACTLY/original) is fully preserved.

## Consequences

- Captions sent to Telegram always have clean, real newlines regardless of how the model encoded them.
- Each iteration is explicitly instructed to beat the previous one in opulence — the main user request.
- Accessories (sunglasses/hat) are available as an occasional stylistic variation without becoming repetitive.
- 1123 tests green (+27 from 1096 baseline). All pre-existing tests unchanged.


---

# Decision: Rich-Image Captions — No Slash Separators

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented

## Problem

Rich-image captions sent to users were containing literal `" / "` separators between sentences (e.g. `"Me he comprado un yate. / Me fui de Mónaco. / Pringados."`).

## Root Cause

`append_caption` stored each multi-line caption as a single line by replacing `\n` with `" / "`. Those stored lines were fed back to the language model as `recent_captions` (examples of prior captions for variety). The model imitated the `" / "` style and produced new captions with literal slash separators instead of real line breaks.

## Fixes Applied

### 1. `append_caption` — store with spaces, not slashes
Replace `caption.replace("\n", " / ")` with `re.sub(r'\s+', ' ', caption).strip()`.  
Stored examples no longer contain slashes, so the model has no reason to imitate them.

### 2. `_normalize_caption` — convert slash separators to newlines
Add `re.sub(r'\s+/\s+', '\n', text)` after CRLF normalisation.  
Any `" / "`, `" /\n"`, or `"\n/ "` pattern becomes a clean `\n`.  
Non-separator slashes (`24/7`, `and/or`) are unaffected — they have no surrounding whitespace.

### 3. `RICH_CAPTION_PROMPT` — explicit instruction in Spanish
Added: `"Separa las frases con SALTOS DE LÍNEA, NUNCA con barras \"/\" ni con \" / \"."`  
Tells the model up-front to use line breaks, never slash separators.

## Test Impact

12 new tests added in `tests/test_rich_image.py`. Total: 1135 (was 1123). All green.


---

# Decision: Hybrid Multi-Image Face-Anchor for Rich Image Edit

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented

## Context

The rich-image feature runs daily, progressively making a person look wealthier. Each iteration feeds the previous output as input. Over time the face and identity drifted (the model quietly altered appearance while only changing the background). Additionally, the output kept the same pose and clothing unchanged — only the background swapped.

## Decision

### 1. HYBRID multi-image edit [previous, original]

Each iteration now passes **two images** to `client.images.edit`:
- Image 1 (first): the evolved `rich_modified.png` from the state dir (continuity of wealthy style).
- Image 2 (second / anchor): the original `{data_dir}/rich/rich_original.*` (face reference).

This is activated only when an evolved image exists (`using_anchor = abspath(base) != abspath(original)`). First run is always single-image (base IS the original). Confirmed working on the user's LiteLLM/Azure gpt-image-2 deployment (api_version 2025-04-01-preview).

### 2. RICH_FACE_ANCHOR_CLAUSE

A constant appended to the prompt when `anchor=True`:
> "A second reference image (the ORIGINAL photo of this person) is provided. The face, head, skin tone and facial features in your result MUST be an EXACT match to that ORIGINAL reference. Do NOT copy the clothing, outfit, pose or background from any reference image — invent NEW luxury clothing and a NEW pose. Use the FIRST image only for continuity of the wealthy style you are building on."

### 3. RICH_EDIT_PROMPT: mandatory clothing + pose changes

Rewrote the prompt to include a **MANDATORY CHANGES** section that explicitly requires:
1. CLOTHING/OUTFIT: design completely NEW luxury attire every iteration — do NOT keep same clothes.
2. POSTURE/POSE: choose a fresh body positioning each time.
3. SETTING/BACKGROUND: evolve the scene.

Identity preservation is now scoped to face/head/skin tone/facial features/build only — not clothing.

## Consequences

- Face identity is locked to the original from run 2 onwards, stopping multi-day drift.
- Clothing, pose and scene change every iteration as required.
- `build_rich_prompt(anchor=bool)` exposes the anchor toggle cleanly.
- `edit_rich_image(anchor_path=...)` handles both single and dual-image calls transparently.
- `find_original_image(data_dir)` always resolves the original independently of the state dir.
- If the original is missing at runtime, graceful fallback to single-image mode (no crash).
- 1096 tests green (+28 new tests).


---

# Decision: Rich Image — Model-Driven Escalation + Caption Variety

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 1068 tests green  

---

## Context

The previous rich-image feature used a hardcoded `_ESCALATION_CLAUSES` list indexed by a `level` counter. Each run picked a clause (ático→club→jet→Rolls→yacht→...) that told the image model exactly what wealth marker to add. Two problems emerged:
1. The model was constrained to fixed escalation steps rather than naturally evolving the photo.
2. Captions were repeating the same coletillas ("seguid poniendo pasta", "currelas", "muertos de hambre", "a vuestra salud", "pringados") because no caption history was fed back.

---

## Decisions

### 1. Removed level escalation — richness is model-driven and implicit

`_ESCALATION_CLAUSES` deleted. `build_rich_prompt` no longer takes a `level` parameter.

`RICH_EDIT_PROMPT` now:
- Asks the model to make the person look **SOMEWHAT richer** (a few notches up, not a leap).
- States that richness grows **gradually and implicitly** because each run feeds the previous output as input.
- Mandates: pick only **a FEW NEW touches per iteration** and **VARY them** — do NOT add everything at once.
- Explicitly encourages: changing POSTURE/POSE, bringing HANDS into view, adding OTHER PEOPLE (entourage, bodyguards, etc.), adding luxury VEHICLES (sports car, Rolls-Royce, private plane, yacht, helicopter), or moving to a different SETTING (pool, rooftop terrace, private-jet cabin, tropical private island, mansion, casino, ski chalet, designer boutique).
- Maintains STRICT IDENTITY PRESERVATION (same face, skin tone, body, hair, distinguishing traits).

`load_level` / `save_level` are kept as an **iteration counter** (no longer content-selection).

### 2. rich_history cap raised to 30

`RICH_HISTORY_MAX_LINES` was 20, now **30**.  
History line label changed from `"nivel"` to `"iter"`: format is now `"{date_str} | iter {n} | {memo}"`.

`format_history_for_prompt` gained a `max_items=None` parameter. The image prompt uses `max_items=12` (concise); the caption call uses the full 30.

### 3. Added rich_captions.txt — cap 6

New bounded store: `rich_captions.txt`, `RICH_CAPTIONS_MAX = 6`.

- `append_caption(state_dir, caption)` — collapses newlines to `" / "`, caps at 6 lines.
- `load_captions(state_dir) -> list[str]`
- `format_captions_for_prompt(state_dir) -> str` — `""` if empty, newline-joined block otherwise.

`generate_rich_caption` now accepts `recent_captions: str = ""`. When non-empty, injects:
> `TEXTOS ANTERIORES (NO repitas su estructura, aperturas, insultos ni despedidas — usa vocabulario y coletillas DISTINTAS):\n{recent_captions}`

`RICH_CAPTION_PROMPT` updated to explicitly instruct the model to **VARY** daily: no fixed openings, no fixed insults, invent fresh vocabulary each time.

### 4. run_rich_iteration wiring

Order:
1. Read `image_history` (last 12 memos), `full_history` (all 30), `recent_captions` (last 6 captions) **before editing**.
2. Edit image using `image_history`.
3. Generate caption using `full_history` + `recent_captions` (best-effort).
4. On caption **success**: `append_history(memo, cap=30)` + `append_caption(caption, cap=6)`.
5. On caption **failure**: fallback `"🤑 Cada día más rico a vuestra costa"`, nothing appended.
6. Rename temp → final, save iteration counter.

---

## Test Count

1068 tests pass (+16 new). New: `TestRichCaptions` (9), `TestBuildRichPrompt` rewritten, new `TestRichEditPromptContent` assertions, `format_history_for_prompt` max_items, `TestGenerateRichCaption` recent_captions, `TestRunRichIteration` new integration tests.


---

# Decision: Azure Image Moderation — Safe Prompt Framing for Rich-Image

**Date:** 2026-06-17  
**Agent:** Kanté (Backend Developer)  
**Files:** `src/worldcup_bot/ai/rich_image.py`, `tests/test_rich_image.py`

## Problem

`gpt-image-2` returned `400 moderation_blocked safety_violations=[sexual]` on the FIRST (single-image) rich-iteration call. Root cause: the `RICH_EDIT_PROMPT` contained the phrase "MANDATORY CHANGES — CLOTHING and OUTFIT: design completely NEW luxury attire — do NOT keep the same clothes or outfit from the input image." Azure's image safety moderator interprets "change the clothing / change the outfit" on a real person's photo as an undressing instruction and flags it as sexual content.

## Decision

Replace all "change/remove/swap/alter clothing/outfit" language with **positive luxury-dressing framing**: instruct the model to *dress* the person in a brand-new, elegant, fully-clothed outfit, never to *remove or change* what they are wearing.

## Verified-Safe Wording (live-tested by coordinator, msgs 523/524)

**`RICH_EDIT_PROMPT`**  
> "Transform this photo into a photorealistic image where the person looks wealthier and more glamorous. Keep the EXACT same face, head, skin tone and facial features — the same identity. Dress them in a brand-new, elegant, fully-clothed luxury outfit (for example a tailored designer suit, a tuxedo, a smart blazer or a refined formal coat) — always tasteful and fully clothed. Give them a new confident pose with hands in view. Place them in a new opulent setting and add a few varied signs of wealth (an elegant entourage, a luxury car, a yacht, a private jet, fine jewellery) — a few new touches each time, growing gradually. Classy, elegant, photorealistic."

**`RICH_FACE_ANCHOR_CLAUSE`** (appended when `anchor=True`)  
> " A second reference image (the ORIGINAL photo) is provided; match the face, skin tone and features EXACTLY to that original. Use the first image only for the wealthy style. Invent a new elegant outfit and a new pose; keep the person fully and tastefully clothed."

## Rules for Future Prompt Edits

1. **Never** use the words "change", "alter", "remove", "swap" in conjunction with "clothing", "outfit", "clothes", or "attire" in a prompt sent to an image-generation model. Azure moderation reads this as undressing on a real person.
2. **Always** frame the clothing instruction as positive dressing: "dress them in…", "wear…", "outfit them with…", always followed by "fully clothed", "tasteful", "elegant".
3. Preserve face/skin/features language is safe and required.
4. Luxury items (entourage, car, yacht, private jet, jewellery) are safe and encouraged.


---

# Decision: Rich Photo Folder Gitignore Pattern

**Date:** 2026-06-17T17:05:00+02:00  
**Agent:** Maldini (DevOps)  
**Requested by:** David (@DrDonoso)

## Problem Statement

The rich-image feature (daily image generation with base photo) reads `data/rich/rich_original.jpg` at runtime. This is a PERSONAL photo, and the repo is PUBLIC on GitHub, so the photo must NEVER be committed. However, the `data/rich/` folder must exist in the repo structure (it's mounted via `./data:/app/data:ro` in docker-compose) so that deployment can locate the photo on the production server.

## Solution

Mirror the existing `data/tongo_gifs/` pattern in `.gitignore`:

1. **Edit `.gitignore`:** Added a two-line commented block after the tongo_gifs section:
   ```
   # Personal base image for the daily 'rich' feature — drop rich_original.jpg into data/rich/ on the server (mounted, not committed).
   data/rich/*
   !data/rich/.gitkeep
   ```

2. **Create `data/rich/.gitkeep`:** Empty file ensures the folder is tracked by git without tracking the photo itself.

## Verification

- `git status --porcelain data/rich` → Shows `?? data/rich/` (untracked folder; only .gitkeep is present).
- `git check-ignore -v data/rich/rich_original.jpg` → Returns `.gitignore:33:data/rich/*	data/rich/rich_original.jpg`, confirming the photo is correctly ignored.

## Rationale

- **Consistency:** Identical pattern to `data/tongo_gifs/` (runtime media, git-ignored, folder tracked via .gitkeep).
- **Deployment:** Folder structure is preserved in the repo; ops mount it read-only and populate `rich_original.jpg` on the server.
- **Security:** Personal photo stays off the public GitHub repo.

## Status

✅ Complete. Not committed (as instructed).




---

## 46. Decision: Robust clip scorer matching for r/soccer title formats

# Decision: Robust clip scorer matching for r/soccer title formats

**Date:** 2026-06-17  
**Agent:** Kanté (Backend Developer)  
**File:** `src/worldcup_bot/reddit/clip_finder.py`  
**Trigger:** LIVE bug — Yoane Wissa goal (Portugal 1-1 D.R. Congo, 45') failed to match
r/soccer clip "Portugal 1 - [1] D.R. Congo - Wissa Y. goal 49'"

---

## Problem

r/soccer clip post titles mix at least two scorer formats:
1. **"Surname Initial. goal"** — e.g. `Wissa Y. goal`, `Neves J. goal`, `R. Leão goal`
2. **"Firstname Lastname"** — e.g. `João Cancelo`, `Viktor Gyökeres`

In addition, accented characters appear in both target names (from football-data.org)
and clip titles (e.g. `Gyökeres`, `João`).

Added-time goals cause **minute drift**: the internal event fires at the regulation
minute (e.g. 45') but the clip post title uses the real clock minute (e.g. 49').

The old `_scorer_matches` relied on `str.lower()` substring/last-token equality.
It failed when the last token of the clip scorer was `"goal"` rather than the surname.
The old ±2 minute tolerance was too tight for added-time drift (diff=4 for Wissa).

---

## Decision

### Fix 1 — Accent-folded token-intersection scorer matching

Rewrote `_scorer_matches(clip_scorer, target_scorer)` in `clip_finder.py`:

- **Accent-fold both** using `unicodedata.normalize("NFKD", s)` + drop combining marks
  (`unicodedata.category(c) != "Mn"`) + lowercase. Added `_fold()` helper.
- **Tokenise** via `re.findall(r"[a-z0-9]+", folded)`.
- **Drop noise**: `_SCORER_NOISE = {"goal","goals","penalty","pen","og","owngoal","own"}`
  and any single-character token (initials like `"y"`, `"j"`).
- If **both sides** yield tokens: True if `set(ct) & set(tt)` is non-empty (shared
  surname/name token), OR cleaned joined strings are substrings of each other.
- If **either side** is emptied by cleaning: fallback to plain accent-folded string
  equality / substring / last-token equality (so noise-only clip sides return False).

Examples now correct:
| clip_scorer | target_scorer | result |
|---|---|---|
| `"Wissa Y. goal"` | `"Yoane Wissa"` | True ✓ |
| `"Neves J. goal"` | `"João Neves"` | True ✓ |
| `"João Cancelo"` | `"João Cancelo"` | True ✓ |
| `"Gyökeres"` | `"Viktor Gyökeres"` | True ✓ |
| `"R. Leão goal"` | `"Rafael Leão"` | True ✓ |
| `"Messi"` | `"Cristiano Ronaldo"` | False ✓ |
| `"goal"` | `"Ronaldo"` | False ✓ |
| `""` | `"Ronaldo"` | False ✓ |

### Fix 2 — Minute tolerance widened to ±3

Changed `minute_ok = abs(clip_minute - minute) <= 2` → `<= 3` in `_match_post`.

Rationale: added-time goals can drift by 3–4 minutes between event detection and
clip post title. The scorer fix is the primary mechanism; ±3 is defense-in-depth.
Do **not** widen further — ±4+ risks matching neighbouring goals in the same match.

The condition remains `scorer_ok OR minute_ok` (either signal suffices).

---

## Tests added (`tests/test_clip_finder.py`)

- `TestScorerMatches`: 8 new cases covering all formats above + `test_partial_last_name_accent_stripped` (accent-fold makes "Gyokeres" == "Gyökeres" → True)
- `TestMatchPost.test_wissa_scorer_format_minute_off_by_four`: verifies dropr.co URL returned for Wissa with minute diff=4 (scorer carries the match)
- `TestMatchPost.test_guard_wrong_scorer_and_minute_far_off_returns_none`: different scorer + minute far off → None

Final suite: **1161 passed**.


---

## 47. Decision: Always merge HTML search + /new/ listing for clip lookup

# Decision: Always merge HTML search + /new/ listing for clip lookup

**Author:** Kante (Backend)  
**Date:** 2026-06-17  
**Status:** PROPOSED — awaiting coordinator merge

## Problem

r/soccer HTML search index lags behind real time. Very recent clips (posted seconds-to-minutes ago) appear in the `/new/` listing before the search index includes them. The previous `find_goal_clip` logic only fell back to `/new/` when HTML search returned **zero** results. When HTML search returned non-empty results (other posts for the same match) but was missing the just-posted clip, the clip was never found.

LIVE example: `"Portugal [2] - 1 D.R. Congo - João Cancelo 55'"` (url `https://streamin.link/v/f5eabdf2`) existed in r/soccer `/new/` but not in the HTML search window. HTML search returned Wissa + Neves posts (so it was non-empty), so `/new/` was never consulted.

## Decision

When JSON search returns None (403/failure), **always** fetch both `_fetch_html_search_posts` AND `_fetch_html_posts` (/new/ listing) and merge them deduplicated by post id, preserving order (HTML search results first, then /new/ entries not already seen).

The JSON-success path is unchanged.

## Implementation

`src/worldcup_bot/reddit/clip_finder.py` — `find_goal_clip`:

```python
posts = _fetch_search_posts(scanner, search_url)
if posts is None:
    log.info("find_goal_clip: JSON search 403/failed, using HTML search + /new/ listing")
    merged: list[dict] = []
    seen: set[str] = set()
    for p in (
        _fetch_html_search_posts(scanner, home_team, away_team)
        + _fetch_html_posts(scanner)
    ):
        pid = p.get("id") or p.get("permalink") or p.get("url")
        if pid in seen:
            continue
        seen.add(pid)
        merged.append(p)
    posts = merged
```

## Tests

2 new tests added (`tests/test_clip_finder.py`, class `TestFindGoalClipMergeNewListing`):
- Clip only in `/new/`, HTML search has unrelated posts → clip found (Cancelo scenario)
- Same post id in both sources → no duplication/crash

Final suite: **1163 passed**.


---

## 48. Decision: /endirecto Live Match Detail via Reddit + OpenAI Extractor

# Decision: /endirecto Live Match Detail via Reddit + OpenAI Extractor

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — awaiting coordinator live E2E test before commit.

## Problem

`/endirecto` previously showed only the score and status of live matches (from football-data.org).  
The football-data.org free tier (`/matches/{id}`) returns only `score` and `status` for live matches — the `goals`, `bookings`, and `substitutions` arrays are absent. There is no way to obtain minute, scorers, cards or substitutions from the API on this tier.

## Decision

Enrich `/endirecto` with live match detail by:
1. Finding the r/soccer Match Thread for the fixture via `RedditMatchScanner.find_match_thread`.
2. Fetching the thread body via `RedditMatchScanner.get_thread_body`.
3. Passing the trimmed "MATCH EVENTS" section to a new OpenAI extractor (`ai/match_events.py`).
4. Formatting the enriched output with a new formatter (`format_live_match_detail`).
5. Falling back to the existing `format_match` (score-only) when AI is disabled, no thread is found, or any step fails.

## Why Reddit Thread

The r/soccer Match Thread body is updated live by a bot (via ESPN) and contains a structured "MATCH EVENTS" section with goals (⚽), yellow cards (🟨), red cards (🟥) and substitutions (🔄) in a highly parseable format. This is the same data source already used by the goal-polling job — reusing `RedditMatchScanner` (already in the codebase) is consistent and requires no new external dependencies.

## Implementation

### New module: `src/worldcup_bot/ai/match_events.py`
- `_trim_events_region(thread_text)` — anchors on "MATCH EVENTS", truncates at "MATCH STATS", caps at 6000 chars.
- `_parse_events_json(raw)` — strips ``` fences, json.loads, returns `{}` on any failure.
- `_coerce_events(raw)` — normalises parsed dict (string values, drops malformed entries).
- `extract_match_events(ai, thread_text, home_team, away_team) -> dict` — async, temperature=0.0, max_completion_tokens=900. Returns `{"minute": None, "goals": [], "cards": [], "subs": []}` on any error. Never raises.

### Updated formatter: `src/worldcup_bot/bot/formatters.py`
- `format_live_match_detail(match, events, tz_name)` — plain-text block: `🔴 EN DIRECTO · {minute}'`, score line, then optional `⚽ Goles`, `🟨 Tarjetas`, `🔄 Cambios` sections.

### Updated handler: `src/worldcup_bot/bot/handlers.py` — `cmd_en_directo`
- Processes up to 4 live matches (latency cap).
- Enrichment per-match wrapped in `try/except` → fallback to `format_match` on any error.
- Multiple matches joined by `"\n\n———\n\n"`.
- AI disabled (no OpenAI keys) → score-only fallback for all matches.

## Graceful Fallback

All failure modes degrade gracefully to `format_match` (score + status):
- AI not configured (`ai_enabled(settings)` is False).
- No r/soccer match thread found for the fixture.
- Reddit request fails (network, 403, etc.).
- OpenAI call fails (API error, timeout, etc.).
- Malformed/empty JSON response from the AI.
- Any unexpected exception in the enrichment pipeline.

## Tests

42 new tests:
- `tests/test_match_events.py` — 21 tests covering all helpers and `extract_match_events`.
- `tests/test_formatters.py` — 15 new tests in `TestFormatLiveMatchDetail`.
- `tests/test_handlers.py` — 6 new tests in `TestCmdEnDirecto`.

Suite: **1205 passed** (baseline: 1163).




## 49. Decision: /endirecto — Inline Reveal Buttons (header+goles + tarjetas/alineación/cambios on demand)

**Date:** 2026-06-17T21:14:19+02:00
**Author:** Kanté (Backend Developer)
**Status:** IMPLEMENTED

## Context

`/endirecto` previously dumped everything (goals, cards, subs, lineup) inline in one wall of text. David requested a cleaner design: send only the header + goals, with inline buttons to reveal the extra sections on demand.

## Design

### 1. Snapshot store — `src/worldcup_bot/bot/endirecto_store.py`

Persists per-match snapshots to `{state_dir}/endirecto.json` (JSON dict, keyed by 8-hex token). Survives bot restarts. Schema: `{token, match_id, minute, home_name, away_name, home_tla, away_tla, home_score, away_score, goals, cards, subs, lineup, revealed, created}`. All functions best-effort, never raise. Pruned at ~6 h (`max_age_secs=21600`).

### 2. AI extractor extended — `src/worldcup_bot/ai/match_events.py`

- `_MAX_THREAD_CHARS` raised to 8000; `_trim_events_region` now anchors on the EARLIER of "Starting XI" or "MATCH EVENTS" so the LLM sees the lineup section.
- `lineup` field added to JSON schema: current XI per team (starting XI with substitutions applied).
- `_EMPTY_EVENTS` updated to include `"lineup": {"home": [], "away": []}`.
- `max_completion_tokens` raised to 1200.

### 3. Renderer — `render_endirecto` in `src/worldcup_bot/bot/formatters.py`

Returns `(text, keyboard_rows)`. Text built in FIXED order regardless of click order:
1. Header: `🔴 EN DIRECTO [· {minute}']` + score line
2. `⚽ Goles` — ALWAYS shown
3. `🟨 Tarjetas` — only if `"tarjetas"` in `snap["revealed"]`
4. `👥 Alineación actual` — only if `"alineacion"` in `snap["revealed"]`
5. `🔄 Cambios` — only if `"cambios"` in `snap["revealed"]`

Keyboard: one button per non-revealed section (up to 3 in one row). `callback_data = f"ed|{token}|{code}"` (code: t/l/c). All revealed → empty keyboard.

### 4. Handler changes — `src/worldcup_bot/bot/handlers.py`

- `cmd_en_directo`: one message per live match (not joined). AI enabled + thread found → snapshot + buttons. Fallback (AI disabled / no thread / exception) → plain `format_match`.
- New `cmd_endirecto_callback`: parses `"ed|{token}|{code}"`, calls `set_revealed`, edits message. Expired/missing token → alert. Never raises.

### 5. Registration — `src/worldcup_bot/__main__.py`

```python
CallbackQueryHandler(cmd_endirecto_callback, pattern=r"^ed\|")
```

Does NOT collide with existing `^vergol:` pattern.

## Coordinator contract (for live Telegram test)

The coordinator can write a snapshot directly into `{state_dir}/endirecto.json` using the exact schema above, then send a message to a test chat with `InlineKeyboardMarkup` built from 3 buttons (`callback_data="ed|{token}|t"`, `"ed|{token}|l"`, `"ed|{token}|c"`). The running bot handles the callbacks. Field names are the contract — do not rename.

## Tests

43 new tests: store (14), match_events (5 new + 5 updated), formatters (17), handlers (7). Final count: 1248 (from 1205).



## 38. # Decision: Streamff Mirror Fix + Thread-Based Early Goal Detection

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-17
**Status:** IMPLEMENTED — 1267 tests green, not yet committed (coordinator live-tests first).

---

## Fix A — streamff.* all route to cdn.streamff.one/{id}.mp4

### Problem

`download()` in `reddit/downloader.py` only matched `streamff.link` and `streamff.com`. Any
other TLD (`.pro`, `.gg`, `.one`, `.top`, etc.) fell through to yt-dlp, which errors
"Unsupported URL" because yt-dlp does not support streamff front-ends.

Confirmed LIVE: `https://streamff.pro/v/89b5d5c1` returned 200 + 27 MB video/mp4 from
`https://cdn.streamff.one/89b5d5c1.mp4` — the id is the same across ALL mirror front-ends.

### Decision

- `STREAMFF_CDN_ID_RE`: `streamff\.(?:com|link)/v/...` → `streamff\.[a-z]+/v/...` — any TLD.
- Host check in `download()`: explicit `.link`/`.com` OR → `"streamff." in media_url`.
- CDN URL construction unchanged: `https://cdn.streamff.one/{id}.mp4`.

### Invariant

Any `streamff.*/v/{id}` URL produces the same CDN URL regardless of mirror TLD.

---

## Fix B — Thread-based early goal detection with shared dedup state

### Problem

`poll_goals_job` polls football-data.org every 60 s, introducing lag. The r/soccer match
thread posts goals in the MATCH EVENTS section sooner. Previous architecture had no way to
use thread events for notification without risking double-notification when football-data
later confirmed the same score.

### Decision

#### 1. Shared in-memory score state

`build_app()` pre-loads `live_scores.json` into `app.bot_data["live_scores"]` at startup.
Both `poll_goals_job` and `poll_thread_goals_job` read/write this SAME dict. When the thread
job notifies a goal and advances `scores[key]["home"]` to the new value, `poll_goals_job` on
its next tick computes `diff_scores(stored, match)` against the already-updated value and
gets `[]` → no second notification.

`poll_goals_job` uses `setdefault` as a backward-compat safety net (for test isolation and
edge cases where `build_app` didn't run).

#### 2. `_notify_goal` shared helper

Extracted from `_process_goal_delta`'s goal branch:
```
async def _notify_goal(match, new_home, new_away, scoring_team, scorer, minute,
                        settings, context, silent)
```
Sends the HTML goal message AND registers the clip-store entry (same token_key formula:
`f"{match.id}:{scoring_team}:{new_home}-{new_away}"`). Both the football-data path and the
thread path call this helper.

#### 3. `poll_thread_goals_job` (interval=25s, first=25s)

- Calls `client.get_live_matches()` (IN_PLAY/PAUSED only).
- `scanner.scan_live_matches(live_matches)` in `asyncio.to_thread`.
- Matches result to fixture via `(home_tla, away_tla)` lookup.
- Skips unseeded matches (key absent from shared scores) — avoids startup backlog.
- Computes thread score as `max(e.home_score)` / `max(e.away_score)` across all events.
- Only notifies INCREASES strictly above stored score.
- Passes `event.scorer` directly (no OpenAI call — speed win and simpler).
- Sorts pending goals by `minute_sort` before notifying.
- Does NOT handle disallowed goals (leaves those to the football-data poll).
- Per-match `try/except` + whole-job `try/except` — never crashes.

### Dedup guarantee

Thread updates `scores[key]["home/away"]` in-place before returning. On the next
`poll_goals_job` tick, `diff_scores(scores[key], match)` returns `[]` because the stored
value already equals the reported score → no duplicate message.

### Thread scorer advantage

Reddit MATCH EVENTS lines already contain the scorer name (e.g. `Harry Kane 60'`).
`GoalEvent.scorer` is populated by `parse_goal_events`. The thread path passes this directly
to `_notify_goal` — no OpenAI call needed. If `event.scorer` is empty, `None` is passed and
the message still sends (score-only format).

### Files changed

- `src/worldcup_bot/reddit/downloader.py` — Fix A regex + routing
- `src/worldcup_bot/__main__.py` — `_notify_goal` helper, `poll_goals_job` setdefault,
  `poll_thread_goals_job` new job, `build_app` live_scores preload, `main()` job registration
- `tests/test_downloader.py` — 4 new tests
- `tests/test_poll_thread_goals_job.py` — new file, 11 tests
- `tests/test_poll_goals_job.py` — 4 new tests

### Test count

- Baseline: 1248
- Added: 19
- **Total: 1267 passing**

---

## 42. Decision: Persistent finished-match dedup + kickoff-age seed prevents restart re-fires

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-18  
**Status:** IMPLEMENTED — 1297 tests green, not yet committed (coordinator verifies first)

---

## Problem

After a container restart, the "🏁 Final" recap was re-sent for a match that ended hours earlier.

**Root cause — two compounding bugs:**

1. `bot_data["finished_seen"]` was in-memory only → wiped on every restart.
2. The startup seed only included matches whose `status == "FINISHED"` at that moment. football-data.org's status lags: a match that ended hours ago can still show `IN_PLAY` or `PAUSED`. Such a match is not seeded. When football-data eventually flips it to `FINISHED`, the job treats it as newly-finished and sends the recap — for a match that ended long ago.

---

## Decision

### 1. New module: `src/worldcup_bot/reddit/finished_state.py`

Two best-effort helpers that never raise:

```python
load_finished(path: str) -> set[int]   # returns empty set if missing/corrupt
save_finished(path: str, ids: set[int]) -> None  # sorted JSON list
```

### 2. Persistent state in `build_app`

```python
finished_path = f"{settings.state_dir}/finished_announced.json"
app.bot_data["finished_announced"] = load_finished(finished_path)
app.bot_data["finished_seeded"] = False
```

State is loaded from `{state_dir}/finished_announced.json` at startup so announced ids survive restarts.

### 3. Reworked `poll_finished_matches_job`

| Key | Location | Persisted? | Purpose |
|---|---|---|---|
| `bot_data["finished_announced"]` | set | ✅ JSON | Match ids already recapped or seeded as over |
| `bot_data["finished_seeded"]` | bool | ❌ in-memory | First-run gate flag |

**Module-level constant:**
```python
MATCH_OVER_AGE = timedelta(hours=4)
```

**First run** (gate: `not finished_seeded`): seed every match where:
- `m.status == "FINISHED"`, OR
- `now_utc - kickoff > MATCH_OVER_AGE` (4 h)

This seeds both currently-FINISHED matches AND stale IN_PLAY/PAUSED matches whose football-data status hasn't caught up yet. Persist immediately, set flag, return (no sends).

**Subsequent runs:** for each match with `status == "FINISHED"` not in `finished_announced`: send recap (Part A ESPN + Part B porra commentary — unchanged), then `announced.add(id)` + `save_finished(...)` immediately (per-match persist so a crash mid-batch doesn't replay the match).

---

## Why this fixes both bugs

**Bug 1 (restart):** `finished_announced.json` is loaded at startup → ids survive restarts → no re-fire.

**Bug 2 (status lag):** A match that ended 5 h ago but still shows IN_PLAY at startup: its kickoff is >4 h ago → seeded as over → when football-data eventually flips to FINISHED, the id is already in `announced` → no recap.

**Genuinely live match:** Kickoff was 30 min ago → not seeded (kickoff < 4 h) → when it finishes while the bot is running → id not in announced → recap fires exactly once.

---

## Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/reddit/finished_state.py` | **NEW** — `load_finished`, `save_finished` |
| `src/worldcup_bot/__main__.py` | Import `timedelta`, `load_finished`, `save_finished`; add `MATCH_OVER_AGE`; update `build_app`; rework `poll_finished_matches_job` |
| `tests/test_poll_finished_job.py` | Update all `finished_seen` refs to `finished_announced`/`finished_seeded`; add 14 new tests |

**Test count: 1297 (up from 1283)**

---

