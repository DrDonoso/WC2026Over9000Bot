# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (python-telegram-bot), football-data.org API, Docker + compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15
- **Status:** 1205 tests green (/endirecto live enrichment via Reddit + OpenAI — 2026-06-17).

## Latest Session: /endirecto Live Detail Enrichment (2026-06-17)

football-data.org on the free tier returns only score+status for live matches — no minute, scorers, cards or substitutions in `/matches/{id}`. The `/endirecto` command was enriched using the r/soccer Match Thread + an OpenAI extractor.

### New Module: `src/worldcup_bot/ai/match_events.py`

Mirrors `ai/goal_extractor.py` style. Key functions:
- `_trim_events_region(thread_text)`: anchors on "MATCH EVENTS", truncates at "MATCH STATS" (to drop the stats table), caps at 6000 chars. Falls back to head if no marker.
- `_parse_events_json(raw)`: strips ``` fences, `json.loads`, returns `{}` on any failure.
- `_coerce_events(raw)`: normalises the parsed dict (lists of dicts with string values; drops malformed entries; minute to str|None).
- `extract_match_events(ai, thread_text, home_team, away_team) -> dict`: async, calls `ai.complete(temperature=0.0, max_completion_tokens=900)`. Returns `{minute, goals, cards, subs}` empty structure on any error. Never raises.

### New Formatter: `format_live_match_detail` in `src/worldcup_bot/bot/formatters.py`

Plain-text (no HTML) message block:
- Line 1: `🔴 EN DIRECTO · {minute}'` (minute omitted if null)
- Line 2: `{flag} {home} {hs}-{as} {away} {flag}`
- Optional sections: `⚽ Goles`, `🟨 Tarjetas` (🟨/🟥 per type), `🔄 Cambios` (in ▶ out)
- Sections omitted when empty. Resilient to missing/malformed event dict keys.

### Handler: `cmd_en_directo` in `src/worldcup_bot/bot/handlers.py`

- Builds `RedditMatchScanner(user_agent=...)` and `AIClient(...)` if `ai_enabled(settings)`.
- For each live match (cap 4): if AI enabled → `find_match_thread` → `get_thread_body` → `extract_match_events` → `format_live_match_detail`; else fallback to `format_match`.
- Per-match enrichment wrapped in `try/except` → fallback to `format_match` on any error (never crashes the command).
- Multiple matches joined by `"\n\n———\n\n"`.
- New imports: `extract_match_events`, `format_live_match_detail`.

### Key learnings

- football-data.org free tier `/matches/{id}` returns only score+status. The `goals`, `bookings`, `substitutions` arrays are absent. Must use external source (Reddit thread) for live detail.
- The r/soccer MATCH EVENTS section is ESPN-structured and highly LLM-parseable: `**6'** ⚽ **Goal! Portugal 1, Congo DR 0. João Neves...**`, `🟨 card`, `🔄 sub`.
- Trim MUST end at "MATCH STATS" (not just cap at chars) — otherwise the stats table bleeds in and confuses the extractor.
- `asyncio.to_thread` is the correct way to call synchronous scanner methods (requests-based) from async handlers without blocking the event loop.

### Tests

42 new tests across 3 new/updated test files:
- `tests/test_match_events.py` (new, 21 tests): `_trim_events_region`, `_parse_events_json`, `extract_match_events` — includes real MATCH EVENTS sample, fenced JSON, garbage, ai raises, never-raises, token params, coercion.
- `tests/test_formatters.py` (15 new tests in `TestFormatLiveMatchDetail`): header, minute, score, goals/cards/subs shown/omitted, flag emojis, resilience to empty dict.
- `tests/test_handlers.py` (6 new tests in `TestCmdEnDirecto`): no-live-matches, AI-disabled fallback, AI-enabled no-thread fallback, AI-enabled enriched block, per-match exception fallback, multi-match separator.

Final count: **1205 passed** (up from 1163).



LIVE bug reported: goal "Portugal 2-1 D.R. Congo, João Cancelo 55'" failed to match because:
- r/soccer HTML search index lags: clip post `"Portugal [2] - 1 D.R. Congo - João Cancelo 55'"` existed in `/new/` listing but NOT in HTML search results window.
- Old logic only consulted `/new/` when HTML search returned EMPTY. Since HTML search returned other Portugal/Congo posts (Wissa, Neves), the `/new/` listing was never consulted, and the Cancelo clip was missed.

### Fix — Always merge HTML search + /new/ listing

In `find_goal_clip` (`src/worldcup_bot/reddit/clip_finder.py`), when `_fetch_search_posts` (JSON) returns None, now fetch BOTH `_fetch_html_search_posts` AND `_fetch_html_posts` (/new/ listing) and match against the deduplicated union (search results first, then /new/ entries not already seen, keyed by post id/permalink/url).

Log line updated to: `"find_goal_clip: JSON search 403/failed, using HTML search + /new/ listing"`.

JSON-success path unchanged.

### Key learning

r/soccer HTML search index lags by minutes. Very recent clips appear in `/new/` before the search index picks them up. Always merging HTML search + `/new/` (deduplicated) is the correct approach — it catches both indexed and brand-new clips.

### Tests

Added 2 new tests in `TestFindGoalClipMergeNewListing` (`tests/test_clip_finder.py`):
- `test_clip_only_in_new_listing_found_when_html_search_has_unrelated_posts`: patches fetchers; HTML search returns unrelated posts only; Cancelo post is in /new/ → returns `https://streamin.link/v/f5eabdf2`.
- `test_dedupe_same_post_id_in_html_search_and_new_listing`: same post id in both sources → matched once, no crash.

All 7 existing `TestFindGoalClipHtmlSearch` tests remain green (including `test_html_search_falls_through_to_new_listing_when_empty`).

Final count: **1163 passed** (up from 1161).

## Latest Session: Clip Scorer Robust Match (2026-06-17)

LIVE bug reported: goal "Portugal 1-1 D.R. Congo, Yoane Wissa 45'" failed to match
r/soccer post "Portugal 1 - [1] D.R. Congo - Wissa Y. goal 49'" because:
- `_scorer_matches("Wissa Y. goal", "Yoane Wissa")` returned False — last token was "goal" not "wissa"
- minute diff 49-45=4 exceeded old ±2 tolerance

### Fix 1 — Robust `_scorer_matches`

Rewrote `_scorer_matches` in `src/worldcup_bot/reddit/clip_finder.py`:
- Added `import unicodedata`; added `_fold()` helper (NFKD + drop combining marks + lowercase)
- Added `_SCORER_NOISE` set: `{"goal","goals","penalty","pen","og","owngoal","own"}`
- Tokenise both sides via `re.findall(r"[a-z0-9]+", folded_str)`
- Drop noise tokens and single-character tokens (initials like "y", "j")
- If both sides non-empty: True if set intersection non-empty OR cleaned strings are substrings
- If either side empties: fallback to plain accent-folded string equality/substring/last-token equality
- Handles: "Wissa Y. goal"→True, "Neves J. goal"→True, "João Cancelo"→True, "Gyökeres"→True, "R. Leão goal"→True, "goal"→False, ""→False

### Fix 2 — Minute tolerance ±3

Changed `minute_ok = abs(clip_minute - minute) <= 2` to `<= 3` in `_match_post`.
Defense-in-depth for added-time discrepancies; scorer fix is primary mechanism.

### Test suite

Added 11 new tests in `tests/test_clip_finder.py`:
- 8 new `TestScorerMatches` cases covering all specified examples + truly different names
- Updated `test_partial_last_name` → `test_partial_last_name_accent_stripped` (accent-fold makes "Gyokeres" match "Gyökeres")
- `test_wissa_scorer_format_minute_off_by_four`: verifies Wissa now matches via scorer even with minute diff=4
- `test_guard_wrong_scorer_and_minute_far_off_returns_none`: guard test

Final count: 1161 passed (baseline was 1152 before this session's clip-finder tests existed; 59 clip_finder tests now, 1161 total).

### Previous Session: Rich-Image Finalization (2026-06-17)

Coordinator verified 5-iteration rich-image E2Es to personal chat 3041850:
- Face anchored to original (run 2+), stops drift
- Clothing/pose/scene vary per iteration
- Captions escalate in luxury + non-repeating + clean line breaks (no slashes)
- Final suite: 1135 tests green
- Published: commit a8c773a + pushed to origin/main

Key refinements completed:
- Hybrid multi-image anchor (kante-25)
- Azure moderation-safe framing (kante-26)
- Caption newline normalization + richer emphasis (kante-27)
- No slash separators in captions (kante-29)

Detailed decisions archived in .squad/decisions.md (inbox merged 2026-06-17).
Detailed history archived in history-archive.md (58534 bytes → summarized).
