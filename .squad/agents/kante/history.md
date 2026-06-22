# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot  
**Stack:** Python, python-telegram-bot, football-data.org, Reddit scanner, LLM  
**Test count:** 1552 (as of 2026-06-22T13:52:04Z, kickoff-notifications spawn)

## Current Session: 2026-06-22 — Kickoff-Start Notifications

**Feature:** Match-start kickoff notices when scheduled UTC time arrives.

## Latest Implementation

### 2026-06-22 — Kickoff-start notice (`poll_kickoff_job`)

**Feature:** The bot posts `🟢 ¡Empieza el partido! {home_flag} <b>Home</b> vs <b>Away</b> {away_flag}` to the Telegram group within ~30 s of each match's scheduled kickoff time.  Time-based (the `utc_date` field from the football-data API), does NOT wait for the status to flip to IN_PLAY.

**Job:** `poll_kickoff_job(context)` in `__main__.py`.  Runs every 30 s (hardcoded; no new env var). Registered inside the existing `if settings.telegram_group_id:` block alongside `poll_finished_matches_job` and `poll_goal_clips_job`.

**State:** Persisted to `{state_dir}/kickoff_announced.json` as a sorted JSON array of match ids. Reuses `load_finished` / `save_finished` from `finished_state.py` (same generic helpers used by the finished-recap job) — no new module needed, stays DRY.  Wired in `build_app` as `app.bot_data["kickoff_announced"]` (loaded from disk) and `app.bot_data["kickoff_seeded"] = False`.

**Restart safety — seed pass (first run only):** On the first tick (`kickoff_seeded == False`), every match whose kickoff `<= now_utc` OR whose status is IN_PLAY / PAUSED / FINISHED is added to `announced`, the state is persisted, and the job returns immediately (no sends).  Container restarts therefore never re-announce matches that already kicked off before the restart.

**Grace window:** After the seed pass, the normal pass announces a match only when `kickoff <= now_utc AND elapsed <= 30 min`.  Matches that escaped the seed (e.g. a race between seed and the API) and are already > 30 min in the past are silently marked in `announced` without sending.

**Formatter:** `format_match_start(match) -> str` added to `bot/formatters.py` (pure function, testable without imports from `api/` or `porra/`). Returns HTML-safe text with bold team names and flag emojis.  Sent with `parse_mode="HTML"`.

**Silent hour:** `_is_silent_hour` reused — messages between 00:00–09:00 local time use `disable_notification=True`.

**Tests:** `tests/test_poll_kickoff_job.py` — 21 tests across TestSeedPass (5), TestNormalPass (6), TestRestartSafety (1), TestSilentHour (2), TestAPIError (1), TestFormatMatchStart (6).  All using real relative-time fixtures (no datetime mocking needed — offsets are computed at module load against `datetime.now(UTC)`).
**Test count:** 1531 → 1552.
