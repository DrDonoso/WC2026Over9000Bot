# Buffon — QA / Tester

**Project:** WorldCup2026Over9000TelegramBot  
**Current test count:** 2013 (as of 2026-07-01)

## Latest Session: 2026-07-01 — Podium Image Feature — QA Gate (PASS)

**Kanté's change:** New `src/worldcup_bot/bot/podium_image.py` module — `render_podium` (sync, never raises),
`_render_podium`, `_draw_crown`, `_fetch_tile`, `_circular_crop`, `_placeholder_tile`, `_initials`.
`_send_ranking_with_top3_photos` reworked with podium → album → plain-text fallback chain.
Kanté delivered +17 smoke tests (1968 baseline). ✅

**New file:** `tests/test_podium_image_edge_cases.py` — 45 tests added.

**Coverage added (+45):**

*`_initials` (7):* two-word ("DS"), single-word ("M"), empty ("?"), whitespace-only ("?"),
three-word uses first+last ("JN"), lowercase uppercased, single-char words ("AB").

*`_circular_crop` (4):* output RGBA mode, output size matches diameter, center pixel alpha=255,
all four corners alpha=0 (outside circle).

*`_draw_crown` (3):* polygon has exactly 11 vertices (band + 3 spikes), ellipse called exactly 3 times
(one jewel per spike), polygon filled with `_CROWN_GOLD` constant.

*Name truncation (4):* via `_text_centered` spy — 14-char name unchanged, 15-char truncated to
13+"…", 30-char truncated correctly, 50-char name no crash.

*Font fallback (3):* `_FONT_PATH=None` still returns valid PNG; `_font()` returns object when path None;
`_font()` falls back on non-existent truetype path.

*Mixed photo failures (3):* all three failure modes in one render (404 + wrong CT + OSError) →
all placeholders + valid PNG; 200 OK with `application/json` CT → placeholder; first photo OK,
rest 404 → valid PNG.

*Total-failure variants (4):* `Image.new` raises MemoryError → None; `_draw_crown` raises ValueError
mid-render → None; `canvas.save` raises OSError → None; never raises regardless of exception type.

*`_text_centered` (2):* no crash with real ImageDraw; AttributeError fallback still calls `draw.text`.

*Tie-aware positions (5):* `[10,10,8]→[1,1,3]`, `[10,8,8]→[1,2,2]`, `[5,5,5]→[1,1,1]`,
`[10,8,6]→[1,2,3]`, participant dicts include username+display_name.

*send_photo kwargs (6):* photo kwarg is the exact BytesIO returned; chat_id matches effective_chat.id;
parse_mode="HTML"; exactly 1024 chars → no reply_text; 1025 chars → truncated caption + overflow
reply_text; send_media_group not called when podium succeeds.

*cmd_actual podium path (2):* send_photo called, send_media_group not called; caption contains
"provisional" + parse_mode HTML.

*cmd_general podium path (2):* send_photo called, send_media_group not called; caption contains
"Grupos cerrados: 1/12" footer + parse_mode HTML.

**New patterns discovered:**
- `patch.object(Image.Image, "save", side_effect=...)` — patches PIL save on the class to test save
  failures without touching any other image operations.
- `_text_centered` spy pattern — replace the drawing helper with a list-appending no-op to verify
  what text values were computed (truncated names, position labels) without pixel inspection.
- `MagicMock()` as `draw` parameter to `_draw_crown` — cleanly intercepts polygon/ellipse calls
  for geometry verification without needing a real PIL canvas.

**Bugs found:** None. Kanté's implementation is solid against all edge cases including mixed photo
failures, font fallback, inner-render exceptions, and tie-aware position derivation.

**Full suite:** 1968 + 45 = 2013 passed, 5 pre-existing warnings. PASS (+45). ✅

---

## Previous Session: 2026-06-30 — Revive Quiet Hours + Jitter Scheduling — QA Gate (PASS)

**Kanté's change:** Added quiet-hours window + randomized jitter to revive scheduling.
Three new pure helpers in `chat/revive.py`: `is_quiet_hours`, `next_revive_delay`, `schedule_next_revive`.
`revive_inactive_job` reworked to self-reschedule via a `finally` block on every exit path.
Kanté delivered +8 smoke tests (1883 baseline). ✅

**New file:** `tests/test_revive_schedule.py` — 53 tests added.

**Coverage added (+53):**

*is_quiet_hours (16 + sweeps):* All 16 spec vectors — wrap window (23→6): 23, 0, 3, 5 True; 6, 7, 12,
22 False. Non-wrap (1→5): 1, 4 True; 0, 5, 6 False. start==end (0,0): always False. Plus exhaustive
boundary sweeps: every hour [0–23] against both wrap and non-wrap windows; exact quiet_end hour always
False (exclusive boundary).

*next_revive_delay (16):* deterministic via injectable `rand` kwarg.
- Clamp: tiny base + large negative jitter → ≥ 60.0.
- Daytime no-push (10:00, 4 h base, rand→min): delay == base, target not in quiet.
- Midnight-wrap push from evening (23:30 → pushed to 06:00+ next day): assert
  `is_quiet_hours(target.hour, 23, 6) is False` and target lands in [06:00, 06:45].
- Past-midnight push (01:00 → target 03:30 inside quiet → pushed to same-day 06:xx).
- Same-day push (08:00, base 1 h, quiet 9→10 → target 09:xx → pushed to 10:xx).
- Target exactly at quiet_end (10:00, 1 h, quiet 9→10 → target == 10:00, not quiet → no push).
- Cross-midnight date: next-day date correct when pushed from late evening.
- Spread-additive proof (rand=0, mid, max): pushed target ≥ quiet_end, never before quiet_end.

*schedule_next_revive (4):* `run_once` called with correct callable, `when` ≥ 60 s, `name` matches
pattern, called exactly once.

*revive_inactive_job rescheduling (17):* using frozen `datetime` subclass for time control.
- Quiet-skip: now in quiet hours → no `send_message`, but `run_once` called exactly once (reschedule).
- ALWAYS-RESCHEDULE on 4 paths: success (sends mention), no-candidates, `AIError`, generic `Exception`.
- Exactly-one-run-once per execution on all paths.
- Disabled (revive off): no send, no reschedule.
- `settings` missing from bot_data: no reschedule (settings=None guard in finally).
- `ai_client=None` with revive enabled: reschedules but does not send.
- `ai_enabled=False` (no API keys): `revive_enabled=False` → no reschedule.

**New pattern discovered:** `_frozen_datetime_cls(hour, minute)` — factory that returns a
`datetime.datetime` subclass with `.now()` overridden to return a fixed local time.
Patches `worldcup_bot.chat.revive.datetime` to control both the quiet-hours check and the
delay calculation inside `revive_inactive_job` and `schedule_next_revive`.

**Bugs found:** None. All `is_quiet_hours`/`next_revive_delay` edge cases pass correctly.

**Full suite:** 1883 + 53 = 1936 passed, 5 pre-existing warnings. PASS (+53). ✅

---

## Previous Session: 2026-06-30 — Chat LLM Features (Picante + Revive) — QA Gate (PASS)

**Team ship:** Pirlo (Design) + Kanté (Implementation) + Buffon (Testing) + Maldini (DevOps).

**Kanté's scope:** Two LLM-driven group-chat features in `src/worldcup_bot/chat/` package (buffer, state, listener, picante, revive + config wiring).

**Buffon's scope:** Comprehensive edge-case coverage — 107 new tests for gates, filtering, concurrency, privacy, fallbacks, candidate selection, rotation logic.

**Full suite:** 1768 baseline + 107 new = 1875 passed, 5 pre-existing deprecation warnings (unrelated).

**Quality:** 0 bugs found. All edge cases covered: rate limits, PORRA-participant filtering, concurrency scenarios, resilience to AI errors, privacy (no message text on disk).

**Artifact created:** `.squad/skills/ptb-async-testing.md` — PTB async testing best practices.

**Ready for deployment:** Yes (if privacy mode is disabled first).

---

## Skills Updated

- `.squad/skills/ptb-async-testing.md` — added patterns for testing podium image with `asyncio.to_thread` and mocked HTTP requests; consolidated frozen-datetime pattern for time control in async tests.

---

For historical sessions (2026-06-27, 2026-06-26, 2026-06-15), see `.squad/agents/buffon/history-archive.md`.

