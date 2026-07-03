# Decision: "Ver gol" Button Missing — Clip-Pipeline Fix (2026-07-02 SHIPPED)

**Date:** 2026-07-02  
**Authors:** Kanté (Backend Implementation), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 522ba6d)

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the "Ver gol" button clip-search fix:
1. kante-vergol-button-fix.md — Root cause analysis and implementation
2. pirlo-vergol-button-review.md — Lead review (APPROVED)

---

## Summary

Two goals lacked the "Ver gol" clip button in the live match thread; reproduced ind_goal_clip LIVE for both:

**(A) Belgium 3-2 Senegal — Tielemans 120+5' ET penalty**
- Root cause: Search timeout (18.75 min window vs. 20–30 min for ET clip posting)
- Fix: _MAX_CLIP_ATTEMPTS 25 → 40 (~30 min window)

**(B) USA 1-0 Bosnia-Herzegovina — Balogun 45'**
- Root cause: Reddit search miss ("United States" query doesn't match "USA" posts) + timeout
- Fix: Added search-term normalization (_TEAM_SEARCH_SHORT + _search_term() for "usa" alias and hyphen stripping); applied to both JSON and HTML search paths; post-fetch matching unchanged

---

## Root Cause per Goal

### Goal A — Timeout (ET / match-ending penalty)

_MAX_CLIP_ATTEMPTS = 25 × 45 s = ~18.75 min window.

The Tielemans goal was scored at 120+5'—literally the last playable moment. After an ET penalty that clinches the match, the clip poster typically watches the final whistle + celebrations before clipping and posting. This takes 20–30 min, exceeding the 18.75 min window.

### Goal B — Search Miss + Timeout (first-half stoppage goal)

Two compounding issues:
1. **Search miss:** _fetch_html_search_posts built query from raw football-data names: "United States Bosnia-Herzegovina". Reddit's index does NOT match "USA" for "United States". The clip title uses USA [1] - 0 Bosnia & Herzegovina—"United States" appears nowhere. Result: 25 HTML search results contained no goal clips.
2. **Timeout:** A 45' goal clip posted during/after half-time may appear >18.75 min after detection.

---

## Fixes

### 1. Extend clip search window — __main__.py

\\\
_MAX_CLIP_ATTEMPTS: 25 → 40   (~18.75 min → ~30 min)
\\\

Rationale: "clips rarely appear >30–40 min after" (David's constraint). 40 attempts × 45 s = 30 min covers ET goals, halftime goals, and late-posted clips. Well within sane bounds.

### 2. Search-query normalisation — clip_finder.py

Added:
\\\python
_TEAM_SEARCH_SHORT: dict[str, str] = {"united states": "usa"}

def _search_term(team: str) -> str:
    norm = _normalize_team(team)          # WC alias applied, lowercased
    short = _TEAM_SEARCH_SHORT.get(norm, team)
    return short.replace("-", " ")        # strips hyphens for broader Reddit search
\\\

Applied in:
- _fetch_html_search_posts: query now \"{_search_term(home)} {_search_term(away)}"\
- ind_goal_clip JSON path: same query construction

Effect on Goal B:
- \_search_term("United States")\ → \"usa"\ (via alias)
- \_search_term("Bosnia-Herzegovina")\ → \"Bosnia Herzegovina"\ (hyphen stripped)
- Search query: \"usa+Bosnia+Herzegovina"\ → finds \USA [1] - 0 Bosnia & Herzegovina\ ✓

---

## Invariants Preserved

- \_match_post\ is unchanged — all matching logic (exact score, fuzzy teams, scorer/minute) is unaffected.
- \_teams_match\ is unchanged — post-fetch title matching works as before.
- Dedup in merged /new + HTML search posts is unchanged.
- Goal A's \120+5'\ regex already worked.
- No changes to \poll_goal_clips_job\, \_cs_add_entry\, or clip store — only search window and query strings.

---

## Tests Added (13 new → 2134 total)

All tests pass ✅. Coverage includes:
- ET penalty regex parsing (\120+5'\ → minute 120)
- Full \_match_post\ for both goals with actual titles
- Search-term alias ("United States" → "usa")
- Hyphen stripping ("Bosnia-Herzegovina" → "Bosnia Herzegovina")
- End-to-end search URL normalization
- Regression: non-aliased teams unaffected

---

## Review: APPROVED ✅

**Reviewer:** Pirlo (Lead)

Surgical, safe changes:
1. \_search_term\ only affects Reddit search QUERY (both paths); never post-matching logic.
2. USA alias narrowly scoped to one entry in \_TEAM_SEARCH_SHORT\.
3. Timeout bump (25→40) is bounded and reasonable (30 min < sane upper bound).
4. Post-fetch matching uses original team names via \_teams_match\ fuzzy logic — no regression.
5. Best-effort / non-fatal behavior preserved.
6. **2134 tests pass, 0 failures.**

---

## Files Changed

| File | Change |
|------|--------|
| \src/worldcup_bot/reddit/clip_finder.py\ | Added \_TEAM_SEARCH_SHORT\, \_search_term()\; patched \_fetch_html_search_posts\ + \ind_goal_clip\ |
| \src/worldcup_bot/__main__.py\ | \_MAX_CLIP_ATTEMPTS\ 25 → 40 |
| \	ests/test_clip_finder.py\ | 13 new tests (2134 total) |
| \.squad/agents/kante/history.md\ | Session entry added |

---


---

# Decision: Schedule-Live Decoupling — Live Match / Goal Notification Bug Fix (2026-07-01 SHIPPED)

**Date:** 2026-07-01
**Authors:** Kanté (Backend Implementation), Pirlo (Lead Review)
**Status:** ✅ SHIPPED (commit b2e9a71)

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the schedule-live seeding fix:
1. kante-live-seeding-fix.md — Implementation details
2. pirlo-live-seeding-review.md — Lead review (APPROVED)

---

# Decision: Schedule-Live Decoupling — Live Match / Goal Notification Bug Fix

**Author:** Kanté  
**Date:** 2026-07-01  
**Status:** Implemented, awaiting commit

---

## Root Cause

football-data.org free tier updates live match status/scores with a **~1 h delay**. During that window a match that is already playing is still reported as `TIMED`. The entire goal pipeline was gated behind `IN_PLAY/PAUSED`:

- `get_live_matches()` → `[m for m in ... if m.status in ("IN_PLAY","PAUSED")]`
- `poll_goals_job` `relevant` filter → only `IN_PLAY/PAUSED` or `FINISHED+in scores`
- `poll_thread_goals_job` calls `get_live_matches()` and only processes seeded matches

Net effect: during the ~1 h API lag, nothing seeds `live_scores`, the Reddit real-time poller never looks at the thread, and `/endirecto` returns "No hay partidos en directo". Goals are announced ~1 h late when the API finally catches up.

---

## The Fix

### 1. Schedule-Live Predicate

New function `match_is_schedule_live(match: Match, now_utc: datetime) -> bool` added to **`api/client.py`** (module-level, importable with no circular-import risk).

Returns `True` when **all** of:
- `match.status` not in `_TERMINAL_STATUSES = {"FINISHED","POSTPONED","SUSPENDED","CANCELLED","AWARDED"}`
- `kickoff <= now_utc` (match has started per schedule)
- `now_utc - kickoff <= MATCH_LIVE_WINDOW` (4 h — same ceiling as `MATCH_OVER_AGE` in `__main__.py`)

New constants also in `api/client.py`:
```python
MATCH_LIVE_WINDOW = timedelta(hours=4)
_TERMINAL_STATUSES = frozenset({"FINISHED", "POSTPONED", "SUSPENDED", "CANCELLED", "AWARDED"})
```

**Cross-reference:** `MATCH_LIVE_WINDOW` (4 h) must stay in sync with `MATCH_OVER_AGE` (4 h) in `__main__.py`. Both define the same ceiling for "could still be live".

### 2. `get_live_matches()` Fix (`api/client.py`)

```python
def get_live_matches(self) -> list[Match]:
    matches = self.get_all_matches()
    now_utc = datetime.now(timezone.utc)
    return [
        m for m in matches
        if m.status in ("IN_PLAY", "PAUSED") or match_is_schedule_live(m, now_utc)
    ]
```

Fixes `/endirecto` (cmd_en_directo) and the standings live-highlight (cmd_clasificacion) with no changes to handlers.

### 3. `poll_goals_job` Relevant Filter (`__main__.py`)

Added `or match_is_schedule_live(m, now_utc)` to the `relevant` filter:

```python
relevant = [
    m for m in all_matches
    if not _match_is_over(m, now_utc)
    and not m.in_penalty_shootout
    and (
        m.status in ("IN_PLAY", "PAUSED")
        or (m.status == "FINISHED" and str(m.id) in scores)
        or match_is_schedule_live(m, now_utc)   # NEW: catches API-lagged TIMED
    )
]
```

**Seeding TIMED at 0-0:** When a TIMED match has null API scores (`home_score=None`, `away_score=None`):
- `curr_home = curr_away = 0`
- `reconcile(None, None, 0, 0)` → `([], {"home":0,"away":0}, {"home":0,"away":0})`
- `stored is None` → enters seeding branch
- `curr_home > 0 or curr_away > 0` → `False` → **no catch-up delta, no announce**
- Seeds `live_scores[match_key] = {"home":0,"away":0,"status":"TIMED"}` ✓

**Invariants preserved:**
- `goal_lock` atomic claim: unchanged
- `reconcile()`/per-source `seen` dedup: unchanged
- No-double-announce guarantee: seed is at 0-0; subsequent delta uses same reconcile path
- Disallowed/VAR handling: unchanged (only triggered when same source's own value drops)
- POSTPONED/SUSPENDED eviction: executed before `relevant` filter, evicts even newly-seeded TIMED entries
- Over-match (4h) prune: still runs first; TIMED match >4h is evicted AND not schedule-live

### 4. Reddit Thread Matching (`reddit/scanner.py`)

**Findings:** `WC_TEAM_ALIASES` already handled the key Congo DR variants:
- `"dr congo"` → `"congo dr"` ✓
- `"d r congo"` → `"congo dr"` (D.R.Congo after dot→space) ✓
- `"democratic republic of congo"` → `"congo dr"` ✓
- `"dem rep congo"` → `"congo dr"` ✓

**Gap found:** `"democratic republic of the congo"` (official UN name, includes "the") was missing.

**Fix:** Added one alias:
```python
"democratic republic of the congo": "congo dr",  # official UN name variant
```

The `_normalize_team` / `_teams_match` / `_find_matching_fixture` / `scan_live_matches` pipeline was already robust. No structural changes needed.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/api/client.py` | Added `MATCH_LIVE_WINDOW`, `_TERMINAL_STATUSES`, `match_is_schedule_live()`; updated `get_live_matches()` |
| `src/worldcup_bot/__main__.py` | Imported `match_is_schedule_live`; extended `relevant` filter in `poll_goals_job` |
| `src/worldcup_bot/reddit/scanner.py` | Added `"democratic republic of the congo"` alias |
| `tests/test_api_client.py` | Added `TestScheduleLivePredicate` (13 tests) + `TestGetLiveMatchesScheduleLive` (5 tests) |
| `tests/test_poll_goals_job.py` | Added `TestScheduleLiveSeeding` (4 tests); fixed `test_no_relevant_matches_returns_early` (future kickoff) |
| `tests/test_poll_thread_goals_job.py` | Added `TestPollThreadGoalsJobScheduleLive` (2 tests) |
| `tests/test_handlers.py` | Added `TestCmdEnDirectoScheduleLive` (2 tests) |
| `tests/test_reddit_scanner.py` | Added `TestCongoDRAlias` (6 tests) |

**Full suite: 2102 passed, 0 failures.**


---

## Lead Review — Pirlo (APPROVED)

# Review: Schedule-Live Seeding Fix (Goal Pipeline)

**Reviewer:** Pirlo (Lead)  
**Date:** 2026-07-01  
**Scope:** `api/client.py` (new predicate + get_live_matches), `__main__.py` (relevant filter), `reddit/scanner.py` (alias)  
**Test suite:** 2102 passed ✅  

---

## Checklist

### 1. No Double Announce ✅ PASS

Traced both orderings through `reconcile()` + `goal_lock`:

**Thread-first-then-API-catchup (primary real-world path):**

1. `poll_goals_job` seeds match at 0-0 (API scores are None → 0):  
   `reconcile(None, None, 0, 0)` → `([], {0,0}, {0,0})` — seeds `scores[key]={0,0}`, no announce.  
   Sets `seen_api[key] = {0,0}`.

2. `poll_thread_goals_job` reads 0-1 from Reddit thread:  
   `reconcile(None, {0,0}, 0, 1)` — seen=None, announced≠None, `_ahead({0,1},{0,0})` → True → emits ONE catchup delta.  
   Claims `scores[key] = {0,1}` under `goal_lock`. Announces. ✓

3. `poll_goals_job` ~1h later, API now reports 0-1:  
   `reconcile({0,0}, {0,1}, 0, 1)` — new={0,1} != seen={0,0} → proceed.  
   `_ahead({0,1}, {0,1})` → False (equal, not strictly ahead).  
   Step 5: `([], {0,1}, {0,1})`. **No delta, no announce.** ✓

**API-first (rare — API catches up before thread):**

1. API reports 1-0: `reconcile({0,0}, {0,0}, 1, 0)` → `_ahead({1,0},{0,0})` → True → goal delta. Claims `scores[key]={1,0}`. Announces. ✓

2. Thread later reads 1-0: `reconcile(None, {1,0}, 1, 0)` — seen=None, `_ahead({1,0},{1,0})` → False → `([], {1,0}, {1,0})`. **No delta.** ✓

The `goal_lock` ensures the "read announced → reconcile → claim" is atomic between
both pollers. The per-source `seen` baselines prevent a lagging source from interpreting
the other source's already-announced delta as new.

### 2. No False Disallowed ✅ PASS

The disallowed path in `reconcile` (line 243–266) only fires when:
- `_ahead(ann, new)` (announced > new) — announced is strictly higher
- AND `_ahead(seen, new)` (source's own prior > new) — this source itself dropped

With a 0-0 seed baseline:
- Thread reads 0-1: `_ahead({0,0}, {0,1})` → False (ann not ahead of new) → disallowed branch NEVER entered.
- API reads 0-1 after thread claimed {0,1}: `_ahead({0,1}, {0,1})` → False → not entered.

The only way to trigger disallowed is if the SAME source's own `seen` was higher than
its current reading — which is genuine VAR/goal reversal. The 0-0 seed cannot produce
a false disallowed because any forward movement from 0-0 is strictly "ahead" by definition.

### 3. Window Consistency ✅ PASS — No Oscillation

| Elapsed | `match_is_schedule_live` | `_match_is_over` | Net status |
|---------|--------------------------|-------------------|-----------|
| < 4h    | True (`<=`)              | False (`>`)       | Live ✓    |
| = 4h    | True (`<=`)              | False (`>`)       | Live ✓    |
| > 4h    | False                    | True              | Evicted ✓ |

The operators are complementary: `<=` (schedule-live) and `>` (over). At the exact
boundary (4h), the match is still considered live. At 4h+ε it transitions to "over"
and is both evicted AND excluded from `relevant`. No gap, no overlap, no thrash.

Both constants are 4h: `MATCH_LIVE_WINDOW = timedelta(hours=4)` in `client.py` and
`MATCH_OVER_AGE = timedelta(hours=4)` in `__main__.py`. The comment on `MATCH_LIVE_WINDOW`
explicitly notes "Must match MATCH_OVER_AGE in __main__.py".

### 4. Over-Inclusion Prevention ✅ PASS

`match_is_schedule_live` returns False when:
- Status is FINISHED/POSTPONED/SUSPENDED/CANCELLED/AWARDED (checked first, line 48)
- Kickoff is in the future (`elapsed < 0`)
- Kickoff was >4h ago (`elapsed > MATCH_LIVE_WINDOW`)
- `utc_date` parsing fails (returns False on any Exception)

POSTPONED/SUSPENDED eviction (lines 794-808) runs BEFORE the `relevant` filter and
evicts seeded entries. A re-seeding is impossible because `match_is_schedule_live`
returns False for terminal statuses → the match is NOT in `relevant`.

Order of operations in `poll_goals_job`:
1. Over-match eviction (>4h)
2. POSTPONED/SUSPENDED eviction  
3. Build `relevant` list (won't include evicted or terminal matches)

No stale match can re-seed after eviction. ✓

### 5. Null Scores ✅ PASS

```python
curr_home = int(match.home_score) if match.home_score is not None else 0
curr_away = int(match.away_score) if match.away_score is not None else 0
```

None → 0 (no crash). Then `reconcile(None, None, 0, 0)` → seeds at 0-0, announces
nothing. Subsequent ticks with still-null scores: `reconcile({0,0}, {0,0}, 0, 0)` →
`new == seen` → no-op (step 2). Correct and safe.

### 6. No Regression ✅ PASS

- Normal IN_PLAY matches: still hit the `m.status in ("IN_PLAY", "PAUSED")` branch
  first — unchanged logic path.
- VAR/disallowed: reconcile logic untouched; disallowed tests still pass.
- FINISHED catch-up: `m.status == "FINISHED" and str(m.id) in scores` branch untouched.
- FT recap (`poll_finished_job`): uses its own `finished_announced` set — completely
  independent of this change.
- `get_live_matches()`: OR-expanded, not replaced. IN_PLAY/PAUSED matches are still
  included unconditionally.

Full suite: **2102 passed**, 5 warnings (pre-existing deprecation).

---

## Additional Notes

- The Congo alias addition (`"democratic republic of the congo": "congo dr"`) is a
  trivial dictionary entry with 6 passing tests. No risk.
- The `match_is_schedule_live` function is conservative by design: it returns False on
  any parsing error, uses a try/except, and is gated by terminal-status exclusion. It
  cannot widen the pipeline dangerously even with malformed API data.

---

## VERDICT: ✅ APPROVE

The fix is sound. The concurrency guarantees (no double announce, no false disallowed)
are preserved by the unchanged `reconcile` + `goal_lock` mechanism — the change only
widens WHICH matches enter the pipeline, not HOW goals are detected/claimed. The window
arithmetic is tight with no oscillation risk. 2102 tests pass. Ship it.


---

# Decision: Podium Drawn-Base Layout Rewrite (2026-07-01 SHIPPED)

**Date:** 2026-07-01  
**Authors:** Kanté (Backend), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 277ae2e)

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the podium layout rewrite:
1. \kante-podium-drawn-base.md\ — Drawn podium base implementation
2. \pirlo-podium-drawn-review.md\ — Lead review (APPROVED)

---

## Summary

Rewrote \src/worldcup_bot/bot/podium_image.py\ to render a drawn 3-block podium (gold/silver/bronze) with tie-aware heights, position numbers on block fronts, circular photos as "heads" standing on each block, and crown asset (or drawn fallback) worn on top. Canvas 760×560 px. All 2018 tests green; David visually verified rendered output.

---

## Layout Description

Each participant is rendered as a vertical stack from top to bottom:

1. **Crown** — asset (\crown.png\) or drawn fallback — sits on the photo head
2. **Circular photo** ("head") — rests on top of the block with a slight overlap
3. **Podium block** ("feet/pedestal") — anchored to the floor, height varies by rank

Classic left/center/right arrangement for n=3:
- **Center** = participants[0] (1st ranked) — tallest block
- **Left** = participants[1] (2nd ranked)
- **Right** = participants[2] (3rd ranked)

Column display order for n=3: \[1, 0, 2]\ (index into participants list).

---

## Module-Level Constants (all in \podium_image.py\, easy to tune)

\\\python
_CANVAS_W       = 760          # canvas total width (px)
_CANVAS_H       = 560          # canvas total height (px)
_BG             = (22, 27, 34) # background color (dark navy)

_FLOOR_Y        = 420          # y-coordinate of the floor (all blocks end here)
_BLOCK_W        = 200          # width of each podium block (px)
_BLOCK_GAP      = 8            # gap between blocks (px)
_BLOCK_HEIGHT   = {1: 175, 2: 120, 3: 85}  # height by tie-aware position
_BLOCK_COLORS   = {            # flat fill color by position
    1: (230, 184,   0),        # gold
    2: (192, 192, 192),        # silver
    3: (205, 127,  50),        # bronze
}
_BLOCK_TOP_DARKEN = 20         # how much to darken the top edge for depth

_PHOTO_D        = 150          # photo circle diameter (px)
_PHOTO_OVERLAP  = 10           # px the photo overlaps down into the block top

_CROWN_ASSET_SIZE = 105        # width to scale the crown asset to (px)
_CROWN_OVERLAP    = 30         # px the crown asset overlaps down into the photo top
_DRAWN_CROWN_W    = 70         # width of the drawn (fallback) crown (px)
_DRAWN_CROWN_H    = 40         # height of the drawn crown (px)
_DRAWN_CROWN_OVERLAP = 10      # px the drawn crown overlaps into the photo top

_FONT_SIZE_NUM  = 52           # font size for position number on block face
_FONT_SIZE_NAME = 18           # font size for participant name label (below block)
_NAME_Y_OFFSET  = 28           # px below block bottom for name label
\\\

---

## Tie-Height Mapping

Ties share the **same** block height (determined by \participant["position"]\):

| Positions | Block heights              |
|-----------|---------------------------|
| 1, 2, 3   | 175 / 120 / 85            |
| 1, 1, 3   | 175 / 175 / 85            |
| 1, 2, 2   | 175 / 120 / 120           |
| 1, 1, 1   | 175 / 175 / 175           |

The \position\ field comes from \standard_competition_positions()\ in \ormatters.py\, passed through \_send_ranking_with_top3_photos\ → \
ender_podium\.

---

## Crown Placement

- **Asset (\_CROWN_IMG\ is not None):** scale to \_CROWN_ASSET_SIZE\ wide (preserve aspect ratio), alpha-composite centered on the photo column, with the crown's bottom overlapping \_CROWN_OVERLAP\ px into the photo top.
- **Drawn fallback (\_CROWN_IMG is None\):** \_draw_crown(draw, cx, crown_top)\ draws a gold polygon crown of size \_DRAWN_CROWN_W × _DRAWN_CROWN_H\ above the photo, overlapping \_DRAWN_CROWN_OVERLAP\ px.
- The **position number** is drawn on the **block face**, not on the crown.

---

## Fallback Chain (unchanged)

\
ender_podium\ → \syncio.to_thread\ in \_send_ranking_with_top3_photos\:

1. **Podium image** (\
ender_podium\) → if \None\, falls back to:
2. **Album** (existing \send_media_group\ photo strip) → if that fails, falls back to:
3. **Plain text** (existing reply_text)

\
ender_podium\ **never raises** — wraps the entire \_render_podium\ call in \	ry/except\, returns \None\ on any error.

---

## Tests Changed

File: \	ests/test_podium_image.py\
- \	est_canvas_dimensions_720x400\ → renamed \	est_canvas_dimensions_760x560\, assertion updated from \(720, 400)\ to \(760, 560)\
- \	est_asset_crown_pastes_non_background_pixels\: parameter renamed \	ile_y=115\ → \photo_top_y=115\ to match new \_paste_crown_asset\ signature
- \TestCrownAsset::test_fallback_drawn_crown_when_asset_missing\: size assertion updated \(720, 400)\ → \(760, 560)\

All other tests remain unchanged; 2018 pass.

---

## Pirlo Lead Review (2026-07-01 APPROVED)

✅ **Verdict: APPROVE**

**Checklist results:**
- ✅ Never raises — full try/except around internal renderer, returns None on any failure
- ✅ Tie-awareness — block height, color, position number keyed by \p.get("position", ...)\
- ✅ Robustness — n=1 and n=2 handled; missing photo → placeholder; crown fallback works
- ✅ No dead code — 350-line module with 13 functions, all called
- ✅ Constants tunable — all layout magic numbers at module top as named constants
- ✅ Suite green + tests retargeted — 2018 passed, new dimensions correctly asserted

The rewrite is clean: 350-line module with no dead code, all correctness invariants preserved (never-raises, tie-aware, robust for edge cases), constants fully tunable, and tests correctly retargeted. David visually confirmed the output. Ship it.

---


# Decision: Crown Asset Integration (2026-07-01 SHIPPED)

**Date:** 2026-07-01  
**Authors:** Kanté (Backend), Maldini (DevOps), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit e53b8a5)

---

## MERGED DECISIONS (3 files → 1 entry)

This entry consolidates the crown asset integration:
1. `kante-crown-asset.md` — Asset loader implementation
2. `maldini-crown-packaging.md` — Packaging & attribution
3. `pirlo-crown-asset-review.md` — Lead review (APPROVED)

---

## Summary

Swapped hand-drawn gold crown for Noto Emoji crown asset (128×128 RGBA, Apache-2.0). Asset loader prefers bundled PNG; falls back to drawn crown if missing. Packaging fix ensures asset ships in wheel/Docker image.

---

## Asset Loader

```python
# src/worldcup_bot/bot/podium_image.py

from importlib.resources import files

def _load_crown_asset() -> Image.Image | None:
    try:
        resource = files("worldcup_bot") / "assets" / "crown.png"
        return Image.open(io.BytesIO(resource.read_bytes())).convert("RGBA")
    except Exception:
        return None

_CROWN_IMG: Image.Image | None = _load_crown_asset()
```

**Why `importlib.resources.files`?**  
Works identically from source checkout and pip-installed package in Docker, as long as `pyproject.toml` ships the PNG via `package-data`. PEP 451-compliant for Python 3.9+.

---

## Crown Rendering

```python
def _paste_crown_asset(canvas: Image.Image, cx: int, tile_y: int) -> None:
    crown = _CROWN_IMG.resize((_CROWN_ASSET_SIZE, _CROWN_ASSET_SIZE), Image.LANCZOS)
    x = cx - _CROWN_ASSET_SIZE // 2
    y = tile_y - _CROWN_GAP - _CROWN_ASSET_SIZE
    canvas.paste(crown, (x, y), crown)  # uses RGBA alpha channel as mask
```

- `_CROWN_ASSET_SIZE = 56` px
- Crown bottom edge = `tile_y - _CROWN_GAP` = 22 px above tile top
- Alpha-composite via RGBA mask

**Fallback dispatch in `_render_podium`:**

```python
if _CROWN_IMG is not None:
    _paste_crown_asset(canvas, cx, tile_y)
else:
    crown_top = tile_y - _CROWN_H - _CROWN_GAP
    _draw_crown(draw, cx, crown_top)
```

Original 11-vertex drawn crown remains as fallback.

---

## Packaging (Maldini)

**pyproject.toml changes:**

```toml
[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
worldcup_bot = ["assets/*.png", "assets/*.md"]
```

**Attribution:** `src/worldcup_bot/assets/ATTRIBUTION.md` created (Noto Emoji, Google, Apache 2.0)

**Verification:** Wheel built successfully; `worldcup_bot/assets/crown.png` confirmed present in wheel zip.

---

## Testing

- 5 new tests in `TestCrownAsset`: asset loaded; fallback with asset=None; fallback tie case; draw_crown and paste mutate canvas
- 12 smoke tests in `TestRenderPodiumSmoke` pass unchanged
- **Total: 2018 tests passed** ✅

---

## Pirlo Lead Review (2026-07-01 APPROVED)

✅ **Verdict: APPROVE**

**Checklist results:**
- ✅ Asset loading correct (`importlib.resources.files` PEP 451)
- ✅ Fallback dispatch works (asset preferred, drawn as silent backup)
- ✅ Packaging verified (wheel inspection confirms PNG + ATTRIBUTION.md present)
- ✅ Attribution satisfies Apache 2.0
- ✅ No regression (2018 tests passed)

---

# Decision: Picante Prompt Refinement (2026-06-30 SHIPPED)

**Date:** 2026-06-30
**Author:** Kanté (Backend Developer)
**Status:** ✅ SHIPPED (commit d964fbf)

---

## Summary

Refined the picante prompt and uild_picante_user_message function to reply exclusively to the LAST (triggering) message, use recent context only when clearly related, and mirror the language of the last message (Catalan→Catalan, else Castilian). Updated tests; suite 1939 green.

---

## Problem

Picante was passing ALL buffered messages as a flat list to the AI. The model force-wove unrelated topics and people into replies, producing incoherent outputs.

---

## Changes

### New _SYSTEM prompt

Eres el asistente gamberro del grupo de Telegram de una porra del Mundial 2026 entre amigos.
MISIÓN: Suelta UN comentario pícaro e ingenioso dirigido EXCLUSIVAMENTE al ÚLTIMO MENSAJE.
REGLA DE CONTEXTO: El bloque 'CONTEXTO RECIENTE' es solo de apoyo. Úsalo ÚNICAMENTE si está claramente relacionado con el ÚLTIMO MENSAJE.
IDIOMA: Responde SIEMPRE en el mismo idioma del ÚLTIMO MENSAJE. Si el último mensaje está en catalán → responde en catalán.
TONO: Banter amigable con picardía — con chispa, pero nunca cruel.
FORMATO: 1-2 frases cortas, directas. Sin saludos ni presentaciones.

### Modified uild_picante_user_message(messages)

- messages[-1] is always the triggering message
- messages[:-1] is prior context (only included if present)
- Sections separated by double newline
- Empty case: "(sin contexto)"

### Tests Updated

All three tests in TestPicanteUserMessage pass:
- 	est_last_message_is_trigger_prior_in_context ✅
- 	est_empty_returns_placeholder ✅
- 	est_single_message_no_context_block_username_fallback ✅

---

# Decision: ChatState Eager Persistence — Startup + Live Sync (2026-06-30 MERGED)

**Date:** 2026-06-30  
**Authors:** Kanté (Backend Implementation), Pirlo (Lead Review)  
**Status:** ✅ APPROVED

---

## MERGED DECISIONS (2 files → 1 entry)

This entry consolidates the chatstate eager persistence feature:
1. `kante-chatstate-eager-persist.md` — Implementation details
2. `pirlo-chatstate-eager-persist-review.md` — Lead review (APPROVED)

---

## Summary

Two-point change to persist `chat_state.json` from startup and after every qualifying group message, ensuring `last_seen` timestamps survive bot restarts independently of picante/revive feature activity.

1. **Startup save** — In `build_app()`, immediately after seeding `chat_state.last_seen` for all porra participants, call `save_chat_state(chat_state_path, chat_state)`. File exists from minute 0 with all known participants.

2. **Per-message save** — In `on_group_text` step 7 (after `state.last_seen[username] = now_utc.isoformat()`), call `save_chat_state(state_path, state)` if path is truthy. Runs on every qualifying message, independent of picante enabled.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/__main__.py` | Import `save_chat_state`; call it after seeding loop in `build_app()` |
| `src/worldcup_bot/chat/listener.py` | Import `save_chat_state`; call it in step 7 of `on_group_text` |
| `tests/test_chat.py` | `TestChatStateEagerPersist` (3 new tests using `tmp_path`) |

---

## Design Decisions

- **Best-effort, never raises** — `save_chat_state` wraps everything in `except Exception → log.warning`. Disk failure logs warning, continues.
- **Guard: `if state_path:`** — Uses `.get()` on `bot_data` (safe if key absent in tests) and truthiness check (empty-string path is falsy). Existing tests with `chat_state_path: ""` → no save, no warning.
- **Scope: step 7 only, before picante (step 8)** — Save runs even in revive-only mode so `last_seen` is always up-to-date on disk.
- **Per-message atomic write acceptable** — Low-volume private group; `save_chat_state` atomic temp-file-replace pattern ensures no torn writes.

---

## Test Coverage

### `TestChatStateEagerPersist` (3 tests in `tests/test_chat.py`)

**`test_qualifying_message_writes_state_file(tmp_path)`**
- Sends qualifying message through `on_group_text` with real `tmp_path` state file.
- Asserts file exists and `load_chat_state` finds sender in `last_seen`.

**`test_missing_state_path_key_does_not_raise(tmp_path)`**
- Removes `chat_state_path` from `bot_data` entirely.
- Calls `on_group_text` — must not raise.
- Asserts `last_seen` updated in-memory.

**`test_startup_save_writes_seeded_participants(tmp_path)`**
- Directly calls `save_chat_state` with seeded state (simulating startup).
- Asserts `load_chat_state` returns both participants.

---

## Pirlo Lead Review (2026-06-30 APPROVED)

✅ **Verdict: APPROVE** — Minimal, correct, well-guarded change. All checklist items pass.

**Checklist results:**
- ✅ Startup save placement (after seeding loop in `build_app()`, line 1784)
- ✅ Per-message save placement (step 7 of `on_group_text`, before picante step 8)
- ✅ Resilience (wrapped in try/except, logs warning on failure)
- ✅ Privacy unchanged (still only metadata, zero message text on disk)
- ✅ Performance (one atomic write per qualifying message, negligible for low-volume group)
- ✅ Suite green (1939 passed, 5 warnings)

---

# Decision: Revive Feature Enhancement — Quiet Hours + Jitter Self-Rescheduling (2026-06-30 MERGED)

**Date:** 2026-06-30  
**Authors:** Kanté (Backend Implementation), Maldini (DevOps), Pirlo (Lead Review)  
**Status:** ✅ SHIPPED (commit 31f1a89)

---

## MERGED DECISIONS (3 files → 1 entry)

This entry consolidates the revive feature enhancement follow-up:
1. `kante-revive-quiet-jitter.md` — Backend implementation details
2. `maldini-revive-quiet-jitter.md` — DevOps/environment configuration
3. `pirlo-revive-quiet-jitter-review.md` — Lead review (APPROVED)

---

## Summary

Two behavioral enhancements to the **Revive** chat feature (quiet hours + jitter scheduling):

1. **Quiet Hours** — `revive_inactive_job` never sends mentions between `REVIVE_QUIET_START_HOUR:00` and `REVIVE_QUIET_END_HOUR:00` local time (respecting bot `TIMEZONE`). Default: 23:00–06:00 (7-hour nightly window).

2. **Self-Rescheduling with Jitter** — Replaced fixed `run_repeating(interval=4h)` with adaptive `run_once` loop where each next interval = base ± randomized jitter (clamped ≥60s). If computed target lands in quiet window, pushed to `quiet_end:00 + rand(0, jitter)` to cluster runs just after quiet ends, preventing thundering herd.

**Scope:** Revive only. Picante remains untouched.

---

## New Configuration

### Environment Variables (3 new)

| Var | Settings Field | Type | Default | Purpose |
|-----|----------------|------|---------|---------|
| `REVIVE_QUIET_START_HOUR` | `revive_quiet_start_hour` | int | `23` | Hour (0-23) local time, inclusive start of quiet window |
| `REVIVE_QUIET_END_HOUR` | `revive_quiet_end_hour` | int | `6` | Hour (0-23) local time, exclusive end (wake hour) |
| `REVIVE_JITTER_SECONDS` | `revive_jitter_seconds` | int | `2700` | ±45 min; applied symmetrically to base interval + as spread post quiet_end |

**Wiring:** `.env.example`, `docker-compose.yml`, `docker-compose.local.yml` (Maldini)

---

## Implementation Details

### New Functions in `src/worldcup_bot/chat/revive.py`

#### `is_quiet_hours(hour: int, quiet_start: int, quiet_end: int) -> bool`

Returns `True` when hour (0-23) falls inside configured quiet window.

**Rules:**
- `quiet_start == quiet_end` → no window, always False
- `quiet_start > quiet_end` (midnight wrap, e.g. 23→06): `hour >= quiet_start OR hour < quiet_end`
- `quiet_start < quiet_end` (same-day, e.g. 01→06): `quiet_start <= hour < quiet_end`

#### `next_revive_delay(base_seconds, jitter_seconds, now_local, quiet_start, quiet_end, rand=random.uniform) -> float`

Returns seconds (float) until next revive run, with quiet-hours awareness.

**Algorithm:**
1. `delay = base_seconds + rand(-jitter_seconds, +jitter_seconds)` (clamped to ≥60s)
2. `target = now_local + timedelta(seconds=delay)`
3. If target falls in quiet hours:
   - `wake = target.replace(hour=quiet_end, minute=0, second=0, microsecond=0)`
   - If `wake <= target`: add 1 day (push to next day)
   - Add `rand(0, jitter_seconds)` to spread (avoid pile-ups)
   - `delay = (wake - now_local).total_seconds()`
4. Return delay

**Key:** `rand` is injectable for deterministic testing. Pass `lambda a, b: 0.0` for fixed values.

#### `schedule_next_revive(job_queue, settings: Settings) -> None`

Schedules exactly one `run_once` job for the next revive run.

- Computes `now_local = datetime.now(pytz.timezone(settings.timezone))`
- Calls `next_revive_delay(...)` with all settings
- Calls `job_queue.run_once(revive_inactive_job, when=delay, name="revive_inactive")`

### `revive_inactive_job` Changes

**Quiet-hours guard** (inside try, before AI/Telegram work):
```python
now_local = datetime.now(pytz.timezone(settings.timezone))
if is_quiet_hours(now_local.hour, settings.revive_quiet_start_hour, settings.revive_quiet_end_hour):
    log.info("revive_inactive_job: quiet hours (%02d:00) — skipping mention", now_local.hour)
    return   # still rescheduled via finally
```

**Self-rescheduling `finally` block:**
```python
settings: Settings | None = None
try:
    settings = context.bot_data["settings"]
    ...
finally:
    if settings is not None and revive_enabled(settings):
        schedule_next_revive(context.job_queue, settings)
```

- Rescheduling happens on EVERY exit: success, quiet-skip, no-candidates, AIError, unexpected Exception
- When revive_enabled is False, finally guard prevents scheduling (no orphan jobs)

### `__main__.py` Changes

**Initial scheduling** (replaces `run_repeating`):
```python
if revive_enabled(settings):
    schedule_next_revive(app.job_queue, settings)
    log.info(
        "Revive inactive users ENABLED — base %ds ±%ds, quiet %02d:00–%02d:00 %s, group %s",
        settings.revive_check_interval_seconds,
        settings.revive_jitter_seconds,
        settings.revive_quiet_start_hour,
        settings.revive_quiet_end_hour,
        settings.timezone,
        settings.telegram_group_id,
    )
```

First run is also randomized + quiet-aware.

---

## Test Coverage

**New tests in `tests/test_revive_schedule.py`:** 53 tests added

- `is_quiet_hours` — all boundary conditions (wrap, same-day, no-window)
- `next_revive_delay` — jitter range, clamp, quiet-push, rand injection
- `schedule_next_revive` — mock job_queue, verify run_once call args
- `revive_inactive_job` — quiet-hours skip, self-reschedule via finally, settings-is-None path
- Regression: all existing revive tests pass with new finally block

**Result:** Full test suite: 1936 passed, 0 failed

---

## Design Rationale

1. **Quiet window:** Suppresses nightly mentions (default 23:00–06:00 local) for better UX. Respects bot timezone + DST.

2. **Randomized jitter:** Base interval 14400s (4h) ± 2700s (45m) = actual 11700s–17100s (3.25h–4.75h). Prevents thundering herd if bot is ever scaled or multiple instances deployed.

3. **Self-rescheduling loop:** Single `run_once` per execution, replacing old `run_repeating`. Exactly 1 pending "revive_inactive" job at any time. Robust exit handling: quiet-skip, no-candidates, AIError, Exception all reschedule safely.

4. **Spread after quiet_end:** Not exact boundary (prevents pile-ups during multi-instance deployments).

---

## Verification (Pirlo Review)

✅ **Checklist Results:**
- is_quiet_hours midnight wrap logic: correct
- next_revive_delay correctness: next run never in quiet hours
- Self-reschedule robustness: all exit paths handled
- JobQueue hygiene: at most 1 pending job at any time
- Initial schedule in __main__: first run randomized + quiet-aware
- Picante untouched: no changes to other features
- David's spec fidelity: quiet 23-06, jitter ±45m, base 4h
- Test suite: 1883 passed, 5 warnings (all new smoke tests pass)

**Verdict:** ✅ APPROVE — Ship it.

---

# Decision: LLM Chat Features Ship — Picante + Revive (2026-06-30 MERGED)

**Date:** 2026-06-30  
**Authors:** Pirlo (Design), Kanté (Implementation), Maldini (DevOps), Buffon (Testing)  
**Status:** ✅ SHIPPED  

---

## MERGED DECISIONS (4 files → 1 entry)

This entry consolidates the complete chat-features feature ship:
1. `pirlo-llm-chat-features.md` — Design spec + open decisions  
2. `kante-chat-features-impl.md` — Implementation details  
3. `pirlo-chat-features-review.md` — Lead review (APPROVED)  
4. `maldini-chat-features-ops.md` — DevOps/infrastructure  

---

## Overview

Two new LLM-driven group-chat features shipped in `src/worldcup_bot/chat/` package:
- **Picante**: Random spicy replies to group messages (~1-in-5 probability, 5-min cooldown, 30/day cap)
- **Revive**: Periodic @mentions of inactive users (4h check interval, 3-day threshold, 2-day mention cooldown)

Both features:
- **Disabled by default** (`CHAT_PICANTE_ENABLED=0`, `CHAT_REVIVE_ENABLED=0`)
- Share in-memory ring buffer (30 messages), JSON-persisted state (last_seen/last_mentioned only, no message text on disk)
- Reuse existing AIClient + OPENAI_* config (no new API key required)
- Require **BotFather privacy mode to be DISABLED** (blocking pre-deployment step — documented in README)

---

## Architecture

```
src/worldcup_bot/chat/  (NEW package)
├── __init__.py
├── buffer.py          # RingBuffer class (in-memory, N messages)
├── state.py           # ChatState dataclass + load/save (last_seen, last_mentioned, cooldowns)
├── listener.py        # MessageHandler + filtering + buffer recording
├── picante.py         # Probability gate, cooldown, prompt build, reply
└── revive.py          # Candidate selection, rotation, prompt build, send
```

**Existing files touched:**
- `src/worldcup_bot/config.py` — 12 new Settings fields
- `src/worldcup_bot/__main__.py` — MessageHandler registration, chat_state + chat_buffer seeding, revive job scheduling
- `README.md` — Privacy mode section (Maldini)
- `.env.example`, `docker-compose.yml`, `docker-compose.local.yml` — 12 env vars (Maldini)

---

## Locked Parameters (David approved 2026-06-30)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Picante probability | 0.20 | 1-in-5 eligible messages |
| Picante cooldown | 300s | 5 min minimum between replies |
| Picante daily cap | 30 | Hard cap per day |
| Buffer size | 30 | Recent messages kept in RAM |
| Min buffer | 5 | Don't fire until buffer has ≥5 |
| Inactive threshold | 3 days | Days silent = considered inactive |
| Revive check interval | 14400s | Every 4 hours |
| Mention cooldown | 2 days | Don't re-mention same user within 2 days |
| Picante temperature | 0.9 | LLM temperature for spicy replies |
| Revive temperature | 0.8 | LLM temperature for revive messages |
| Candidate set | PORRA PARTICIPANTS ONLY | (override of Pirlo's "anyone who spoke") |
| Language | ES + CAT | Spanish primary, Catalan when natural |

---

## Environment Variables (Maldini wired across all surfaces)

12 new env vars in `.env.example`, `docker-compose.yml`, `docker-compose.local.yml`:

```
CHAT_PICANTE_ENABLED=0
CHAT_REVIVE_ENABLED=0
CHAT_BUFFER_SIZE=30
PICANTE_PROBABILITY=0.20
PICANTE_COOLDOWN_SECONDS=300
PICANTE_MAX_PER_DAY=30
PICANTE_MIN_BUFFER=5
PICANTE_TEMPERATURE=0.9
REVIVE_CHECK_INTERVAL_SECONDS=14400
REVIVE_INACTIVE_DAYS=3
REVIVE_MENTION_COOLDOWN_DAYS=2
REVIVE_TEMPERATURE=0.8
```

---

## Privacy & Data Design

- **Message text**: In-memory only (lost on restart; buffer refills in minutes)
- **Persisted to disk** (JSON): only `last_seen`, `last_mentioned`, `picante_daily_count`, `picante_last_date`, `rotate_index` — ZERO message text on disk
- **GDPR compliant**: No message history disk footprint
- **Picante prompt guardrails**: "Prohibido: insultos reales, contenido sexual, información personal sensible, discursos de odio" (no real insults, no sexual content, no personal info, no hate speech)
- **Revive prompt guardrails**: "Tono: cálido, con gracia, sin agresividad" (warm, graceful, non-aggressive)

---

## Testing

**1768 tests total** (baseline 1730 + 38 new tests added by Buffon for edge cases):
- `tests/test_chat_edge_cases.py` — 107 edge-case tests covering all gates, fallbacks, concurrency, and PORRA-only filtering
- All tests green, 0 bugs found

---

## Deployment Checklist (Maldini)

**BLOCKING PRE-STEP** (must be done before deployment):

1. In BotFather: `/setprivacy` → **DISABLE** (bot needs to receive ALL group messages, not just /commands + replies)
2. **Remove bot from group and re-add** — privacy mode setting only applies to new memberships
3. Deploy bot (environment vars default to disabled)
4. To enable: set `CHAT_PICANTE_ENABLED=1` and/or `CHAT_REVIVE_ENABLED=1` when ready

---

## Pirlo Lead Review (2026-06-30 APPROVED)

✅ **Verdict: APPROVE** — Implementation is correct, well-structured, faithfully follows spec.

**Checklist results:**
- ✅ Filtering completeness (all media types rejected, commands rejected, text length checked)
- ✅ Rate limiting correctness (probability gate, cooldown via Unix time, daily cap with timezone-aware reset)
- ✅ Privacy (ZERO message text on disk)
- ✅ Candidate set = PORRA ONLY (sourced from predictions.yml participant keys)
- ✅ Concurrency (handlers sequential, state fields non-overlapping, no data loss possible)
- ✅ Resilience (both orchestrators wrapped in try/except, AI errors logged and swallowed)
- ✅ Disabled = zero overhead (handler only registered if feature enabled, job only scheduled if enabled)
- ✅ Guardrails (clear prohibitions on insults, sexual content, personal info, hate speech)
- ✅ Mention construction (plain text @username, Telegram resolves natively)
- ✅ Fidelity to locked params (all 10 params verified 1:1)

---

## Optional Nits (non-blocking, shipped as-is)

1. Could add explicit `parse_mode=None` to picante reply (defensive coding, low risk)
2. Inline import in listener.py:101 to avoid circular dep (acceptable)
3. Buffer allocated unconditionally even when both features disabled (negligible cost)

---

## Buffon QA Gate (107 edge-case tests, all green, 0 bugs)

**1875 tests total passed** (1768 baseline + 107 new edge-case tests).

Edge cases covered:
- All rate-limit gates (probability, cooldown, daily cap, min buffer)
- PORRA participant filtering (candidate set correctness)
- Timezone-aware daily reset
- Message filtering (media rejection, command rejection, length check)
- Inactive calculation (3-day threshold, mention cooldown)
- Rotation logic (round-robin, wrap-around)
- AI error resilience
- Concurrency scenarios

---

## Delivery Artifacts

**Code:**
- ✅ `src/worldcup_bot/chat/` package (5 modules: buffer, state, listener, picante, revive)
- ✅ `src/worldcup_bot/config.py` — 12 new Settings fields
- ✅ `src/worldcup_bot/__main__.py` — handler registration, state seeding, job scheduling

**Configuration:**
- ✅ `README.md` — Privacy mode section + setup instructions
- ✅ `.env.example` — 12 new env vars with defaults
- ✅ `docker-compose.yml` — 12 env vars wired
- ✅ `docker-compose.local.yml` — 12 env vars wired

**Tests:**
- ✅ `tests/test_chat_edge_cases.py` — 107 comprehensive edge-case tests
- ✅ All 1875 tests passing

---

## Known Limitations (Deferred to v2)

- Opt-out per user (`/norevive` command) — deferred to v2
- No disciplinary/drawing-of-lots for mention candidate ties — uses deterministic rotation as fallback
- No explicit Markdown safety on generated messages (LLM system prompt provides guardrails instead)

---

# Decision: Fix TVE 📺 label missing from 09:00 daily update

**Date:** 2026-06-27  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented  
**Triggered by:** Production loop — Egypt-Iran goal/disallowed spam after match ended

---

## Problem

football-data.org can stay stuck at `IN_PLAY` or `PAUSED` long after full time (hours, sometimes days). When this happens AND the Reddit match thread oscillates on a VAR-disallowed goal, the bot emits an endless alternating "⚽ gol" / "🚫 gol anulado" every ~25s with no termination condition.

The existing `MATCH_OVER_AGE = timedelta(hours=4)` constant was only used by `poll_finished_matches_job` (first-run seeding). The two goal-polling jobs had no wall-clock cutoff.

## Decision

Add a shared `_match_is_over(match, now_utc) -> bool` predicate to `__main__.py`:
- Returns `True` when `kickoff > MATCH_OVER_AGE (4h) ago` — pure wall-clock, API status ignored.
- FINISHED matches within 4h are NOT excluded (they remain eligible for final-goal catch-up).
- ET + penalties comfortably fit within 4h of kickoff.

Apply it in both goal-polling jobs:

1. **`poll_goals_job`**: prune over-matches from `live_scores` / `seen_api` / `seen_thread` (evict stuck entries, persist), then exclude from `relevant` with `not _match_is_over(m, now_utc)`.
2. **`poll_thread_goals_job`**: filter `live_matches` before scanning Reddit.

## Rationale

- Wall-clock is the only reliable signal — API status cannot be trusted.
- 4h is a generous ceiling that accommodates any realistic match (regular time + ET + penalties + any broadcast delay).
- Prune + filter together are idempotent: once evicted, the match is structurally impossible to re-enter the goal pipeline without a bot restart.
- Self-healing on next tick after deploy: no manual `live_scores.json` deletion required.

## Alternatives considered

- **Trust FINISHED status**: Too fragile — API lag means FINISHED can arrive minutes or hours after FT.  
- **Gate on Reddit thread age**: Reddit threads stay active for days. Not reliable.
- **Rate-limit disallowed**: Treats the symptom, not the cause. Would still loop.

## Impact

- All existing tests pass (+10 new regression tests added).
- Genuinely live matches (within 4h), including ET and penalties, are unaffected.
- FINISHED matches that just ended (within 4h) still receive final-goal catch-up.
- Prune is logged at INFO level for observability.
# Review: Hard-exclude matches >4h past kickoff from goal-polling jobs

**Date:** 2026-06-27  
**Reviewer:** Pirlo (Lead / Tech Lead)  
**Author:** Kanté  
**Status:** APPROVED  
**Triggered by:** Production loop — Egypt-Iran goal/disallowed spam

---

## Review Summary

### 1) THRESHOLD — 4h is the right call ✅

Regulation ~2h, ET+penalties ~3h max. A 4h ceiling gives a full hour of margin beyond the longest realistic match. The only scenario exceeding 4h is an abandoned-and-resumed-next-day match — an extraordinary event that would require manual intervention regardless and has never occurred at a World Cup. The risk of silencing a genuinely live match is negligible vs. the proven production harm of the spam loop. Reuses the established `MATCH_OVER_AGE` constant already proven safe for the recap seeding job. **Confirmed: no adjustment needed.**

### 2) PRUNE SAFETY — no regression with recap job ✅

`poll_finished_matches_job` operates on its own state:
- `finished_announced` (bot_data set + `finished_announced.json`)
- Fetches matches directly from `client.get_all_matches()`
- Checks `m.status == "FINISHED"` against the API response

It **never reads** `live_scores`, `seen_api`, or `seen_thread`. Pruning those dicts has zero interaction with the recap pipeline. A late FT recap is driven entirely by `finished_announced.json` and the API's status flip — both untouched by this change. **No regression.**

### 3) CONCURRENCY — atomic, no interleaving hazard ✅

Verified: `save_scores` (score_state.py:53) is synchronous (`open` + `json.dump`). The entire eviction block (build `over_ids` set → `scores.pop` → `seen_api.pop` → `seen_thread.pop` → `save_scores`) contains **zero `await` points**. On the single-threaded asyncio event loop, this runs atomically — no coroutine can interleave.

The eviction runs **before** the `goal_lock`-protected reconcile section, which is correct: it removes entries that should never reach reconcile. `poll_thread_goals_job` filters its own `live_matches` list independently (also no `await` in the filter). The two jobs cannot observe each other's mid-mutation state. **Safe.**

### 4) Overall — simplest correct fix ✅

**Wall-clock is the only signal that can't lie.** API status lies (stuck IN_PLAY). Reddit thread status lies (oscillating VAR). Wall-clock from kickoff is monotonic and deterministic. This is the correct primitive for a circuit breaker.

**Date parse failure path:** `_match_is_over` catches all exceptions and returns `False` — the match stays in polling. This is the safe direction (over-poll, never silence). A persistently malformed `utc_date` would prevent eviction, but: (a) the same format string is used everywhere in the codebase (`%Y-%m-%dT%H:%M:%SZ`), so a parse failure would break many features, not just this guard; (b) it cannot cause the spam loop, which requires *both* stuck status AND oscillating thread scores.

**No slip-through path identified.** Once `_match_is_over` returns `True`:
- `poll_goals_job`: evicts from all three dicts + excludes from `relevant`
- `poll_thread_goals_job`: excludes from `live_matches` before Reddit scan
- Re-entry is impossible without a bot restart (eviction is idempotent and persisted)

---

## VERDICT: APPROVE

No required changes. Fix is correct, minimal, and safe. Ship it.

---


---

# QA Gate Verdict: Finished-match loop fix (Egypt-Iran)

**Date:** 2026-06-27  
**QA Agent:** Buffon (Tester / QA)  
**Reviewed:** Kanté's `_match_is_over` wall-clock cutoff for goal-polling jobs  
**Requested by:** drdonoso (live production loop on Egypt-Iran)

---

## VERDICT: PASS WITH ADDED TESTS (+5)

**Test count: 1629 → 1639 (Kanté +10) → 1644 (Buffon +5). All 1644 pass.**

---

## Step 1 — Full Suite

`pytest -q`: **1639 passed** immediately after Kanté's changes, matching his stated count. ✅

---

## Step 2 — Kanté's +10 Tests Are Real

### `test_egypt_iran_oscillation_produces_zero_sends` (poll_goals_job)

Correctly reproduces the production loop:
- Seeds `seen_api["99"] = {home:0, away:1}` with kickoff 20h ago.
- Oscillates `stale_match.away_score` through [1, 0, 1, 0] across 4 ticks in the same `ctx`.
- **WITHOUT fix**: tick 2 → DISALLOWED sent, tick 3 → GOAL sent, tick 4 → DISALLOWED sent (3 sends, traced through `reconcile()` + persisted `seen_api` state).
- **WITH fix**: match pruned on tick 1 (removed from `scores`, `seen_api`, `seen_thread`), then excluded from `relevant` → 0 sends. ✅ Real regression guard.

### `test_stale_match_oscillation_zero_sends_thread_job` (poll_thread_goals_job)

Same scenario on the thread job:
- Stale match filtered from `live_matches` before scanner is called.
- Even with scanner returning events for each oscillating tick, they're never processed.
- WITHOUT fix: scanner would fire, events reconciled, alternating sends. ✅ Real guard.

### Prune assertions ✅

- `test_stale_inplay_match_excluded_from_relevant`: `save_scores` called with "1" absent → disk write confirmed.
- `test_stale_match_pruned_from_live_scores_and_seen`: `live_scores`, `seen_scores["api"]`, `seen_scores["thread"]` all cleared in-memory. ✅

### Live path preserved ✅

| Scenario | Test | Result |
|---|---|---|
| Recent match 30min (kickoff) | `test_recent_match_within_4h_goals_still_announced` | ⚽ announced |
| FINISHED match 2h past kickoff | `test_recently_finished_match_in_state_still_polled` | ⚽ final goal |
| Real VAR during live match 45min | `test_real_var_during_live_match_still_works` | ❌ VAR fires |
| Recent thread job match 30min | `test_recent_match_still_processed_by_thread_job` | ⚽ announced |

---

## Step 3 — `_make_match` Default Date Change

Old default `"2026-06-17T18:00:00Z"` (10 days ago = >4h) would silently exclude ALL existing tests' matches via `_match_is_over`, causing widespread `send_message` assertion failures. Kanté correctly replaced it with a dynamic "30min ago" default. No existing test was silently weakened. All other test files that use hard-coded dates do not call `poll_goals_job` / `poll_thread_goals_job` → unaffected. ✅

---

## Step 4 — Edge Cases Added by Buffon (+5)

**Gap:** No tests for `_match_is_over`'s safe fallback or exact boundary direction.

**Class `TestMatchIsOverUnit` added to `test_poll_goals_job.py`:**

| Test | Scenario | Result |
|---|---|---|
| `test_invalid_utc_date_returns_false` | `"not-a-valid-date"` → `except Exception: return False` | Match stays live ✅ |
| `test_empty_utc_date_returns_false` | `""` → same safe path | Match stays live ✅ |
| `test_3h59m_kickoff_is_not_over` | 239min ago → `< 240min` → False | NOT excluded ✅ |
| `test_4h2m_kickoff_is_over` | 4h2m ago → True | IS excluded ✅ |
| `test_et_penalties_match_3h50m_still_announced` | IN_PLAY 3h50m, home scores → integration | ⚽ announced ✅ |

**Boundary direction:** `>` (strict), not `>=`. A match at exactly 4h to-the-second is marginally excluded (due to microseconds in `now_utc`), but this is a non-issue since 4h past kickoff is well beyond any real match. ET+PKs fully covered at 3h50m.

**"Prune then re-seed" scenario:** Structurally impossible — a re-appearing match >4h old is still excluded from `relevant` by `_match_is_over`. No test needed.

---

## Hazards / Findings

**None blocking.** One observation:

- `_match_is_over` on invalid/None utc_date returns **False** (keeps match live). This is the safe choice — an API anomaly on `utc_date` won't silently kill a live match. However, if a match has a permanently malformed date AND is stuck IN_PLAY, the 4h wall-clock guard won't fire. This is an extreme edge case and is now documented via the two safe-default tests.

---

**VERDICT: PASS WITH ADDED TESTS (+5)**  
**Final count: 1644 passed, 5 warnings.**

---

# Investigation: Missed Goals (A/C) + España Duplicate (B)

**Date:** 2026-06-27  
**Author:** Kanté (Backend Developer)  
**Status:** INVESTIGATION COMPLETE — awaiting Pirlo/owner decisions before coding

---

## Context

Three live symptoms reported by drdonoso:

- **A** — Single missed goal: `⚠️ Me perdí 1 gol / 🇳🇿 New Zealand 0-1 Belgium 🇧🇪`
- **B** — España goal announced twice: once live (correct, scorer/video), again at/after FT
- **C** — 4-goal catch-up: `⚠️ Me perdí 4 goles / 🇳🇴 Norway 1-3 France 🇫🇷`

---

## Investigation Results

### SYMPTOM A — "Me perdí 1 gol" for NZL 0-1 BEL

**Confirmed root cause: football-data.org status-flip delay.**

`poll_goals_job` only includes matches in `IN_PLAY`, `PAUSED`, or `FINISHED-already-in-scores` in its `relevant` filter (`__main__.py:589-596`). SCHEDULED/TIMED matches are ignored entirely.

football-data.org typically takes 5–15 minutes to flip a match from `SCHEDULED` → `IN_PLAY` after kickoff. Belgium scored in those minutes. When the API finally flipped, it reported `IN_PLAY` at 0-1 — the match had never been at 0-0 in the bot's view.

The `stored is None` branch (`__main__.py:630-660`) seeds the match and, because `curr_away > 0`, appends a neutral `GoalDelta(kind="catchup", goals_missed=1)`. `_notify_catchup` formats the ⚠️ message.

`poll_thread_goals_job` cannot rescue this because it has an explicit guard at `__main__.py:800-805`: the thread job only processes matches already seeded by `poll_goals_job`.

`poll_kickoff_job` fires the "match starting" notice but does NOT write to `live_scores`. So even with the kickoff notice in the chat, there is no 0-0 entry for the thread job to track against.

**Why "so slow to notify":** The delay equals the football-data status-flip lag (5–15 min) plus the time to the next `poll_goals_job` tick (up to `goal_poll_interval_seconds`).

### SYMPTOM C — "Me perdí 4 goles" for NOR 1-3 FRA

**Confirmed root cause: bot restart mid-match** (bot restarted while Norway–France was already in progress at 1-3).

On restart, `live_scores` is loaded from disk. If `live_scores.json` did not contain the Norway-France entry, `scores[key]` is `None` → `stored is None`. First `poll_goals_job` tick sees the match as `IN_PLAY` at 1-3 → seeds at 1-3 → emits ONE catch-up for 4 goals. The catch-up text shows the final seeded score (1-3), not the 0-0 origin.

For a **live part of C** (bot was running but API flip was late): if the API flipped to `IN_PLAY` at 1-3 in a single step, the same seed-at-nonzero path fires.

### SYMPTOM B — España Goal Announced Twice

**Confirmed code paths; exact trigger open.**

Three candidate explanations, in descending likelihood:

**Candidate B1 — Two separate goals, perceived as one duplicate (most likely):** España scored TWICE. Thread job announced goal 1 with scorer/video. At FINISHED, the thread showed goal 2 (post-FT update), and `poll_goals_job` announced goal 2 via the FINISHED-in-scores catch-the-last-goal feature. This is **not a bug** — it's correct behaviour on a different goal.

**Candidate B2 — Restart in the save-window (rare):** `poll_thread_goals_job` claims `scores[key]` in memory but `save_scores` is deferred to after all matches are processed. If a crash occurs between claim and save, the disk is stale. On restart, FINISHED tick emits a catch-up notification that appears to be a duplicate.

**Candidate B3 — FINISHED-first-time sees goal:** Specific timing where API flip to FINISHED happens in the same tick as the goal confirmation. The API path notifies once; no duplicate in this sub-case.

**Confirmed open:** requires ACTUAL LOG inspection to confirm which candidate fired.

---

## Question 3 — Feasibility: Recover Scorer+Video for Missed Goals

**Verdict: FEASIBLE — high confidence. Recommend implementing.**

At seed-at-nonzero time, all of the following are available:

- `match` object with `home_name`, `away_name`, `home_tla`, `away_tla`
- `scanner` (RedditMatchScanner)
- `scanner.find_thread_permalink(match.home_name, match.away_name)` — uses the cached r/soccer listing
- `scanner.get_thread_body(permalink)` — returns the full selftext
- `parse_goal_events(selftext)` — returns `GoalEvent` objects with `scorer`, `scoring_team`, `home_score`, `away_score`, `minute_text`

The Reddit match thread is created at kickoff and updated in real-time. By the time the bot seeds the match (even with a 5-15 minute status-flip lag), the thread already has all goal events.

**This REVISES Pirlo's Decision 1** from the 2026-06-26 "Live Goal Bug Fixes" session. The revision is NOT fabrication — we use REAL Reddit goal events.

---

## Question 4 — Prevention: Seed at 0-0 at Kickoff

**Verdict: YES, this eliminates most "first-goal missed" cases (Symptom A and the live-onset part of C). Recommend implementing alongside the recovery fix.**

`poll_kickoff_job` already detects imminent/just-past kickoffs but does NOT write to `live_scores`. If it also seeded `live_scores` at 0-0 at that moment, the thread job would detect any goal scored in the status-flip lag window as a normal goal delta.

---

# Decision: Catch-Up Pipeline Redesign — Recover Goals from Thread

**Date:** 2026-06-27  
**Author:** Pirlo (Lead / Tech Lead)  
**Status:** DIRECTIVE (for Kanté implementation)  
**Revises:** 2026-06-26 Decision 1 ("Neutral Summary" — `format_catchup_message()`)

---

## Context

The 2026-06-26 Decision 1 mandated a neutral catch-up ("⚠️ Me perdí N gol(es)") because at that time the bot had NO source for the goal sequence. Kanté's 2026-06-27 investigation confirms this is now SOLVABLE.

The owner explicitly wants PROPER per-goal notifications — scorer + video button — for missed goals. This does NOT fabricate data; it uses real thread data.

---

## DECISION 1 — Goal Recovery from Thread (revises 2026-06-26 Decision 1)

### Policy

When the bot encounters a catch-up situation (first-seen at non-zero score OR restart-ahead), it MUST attempt to **recover per-goal events from the Reddit match thread** and emit proper `_notify_goal` notifications (scorer + minute + "Ver gol" keyboard) — identical to the live path.

The neutral "Me perdí N gol(es)" message becomes a **FALLBACK only**.

### Recovery Flow (new function: `_attempt_goal_recovery`)

Location: inside poll_goals_job, replacing lines 647-660 logic. Also callable from the reconcile restart-ahead path in _process_goal_delta for kind="catchup".

1. Compute goals_missed = curr_home + curr_away (first-seen) or home_diff + away_diff (restart).
2. Attempt thread lookup:
   a. permalink = scanner.find_thread_permalink(match.home_name, match.away_name)
   b. If None: permalink = scanner.find_match_thread(match.home_name, match.away_name) (uses search — handles FINISHED/old threads)
3. If permalink found:
   a. selftext = scanner.get_thread_body(permalink)
   b. events = parse_goal_events(selftext, post_id=extract_post_id(permalink))
   c. Filter events to only those representing goals up to the current score
4. Build goals_to_notify list using the SAME pattern as poll_thread_goals_job
5. Validate: len(goals_to_notify) == goals_missed.
6. If validation passes → emit per-goal via _notify_goal (scorer, minute, clip-store entry each).
7. If validation fails → FALLBACK (see below).

### Fallback Conditions (emit neutral catch-up)

Send the existing `_notify_catchup()` (neutral "⚠️ Me perdí N gol(es)") in ANY of these cases:

| Condition | Rationale |
|-----------|-----------|
| `find_thread_permalink` AND `find_match_thread` both return `None` | No thread available |
| `get_thread_body` raises or returns empty | Thread body inaccessible |
| `parse_goal_events` returns `[]` (no parseable events) | Thread format unrecognised |
| `len(recovered_goals) < goals_missed` | Thread has fewer events than expected — partial data |
| `len(recovered_goals) > goals_missed` | Score mismatch |
| Thread event's `scoring_team` cannot be matched | Data integrity failure |

**NEVER** emit partial proper notifications + partial neutral. It's ALL-proper or ALL-neutral.

### Deduplication (CRITICAL)

After recovery (proper or neutral), the goals MUST be claimed in all relevant state so `poll_thread_goals_job` does NOT re-announce them:

1. **`seen_thread[match_key]`** — set to `{"home": curr_home, "away": curr_away}` immediately after recovery.
2. **`seen_api[match_key]`** — already handled by existing seed flow.
3. **`scores[match_key]`** — already set.
4. **Clip-store tokens** — each `_notify_goal` call creates its own token.

---

## DECISION 2 — Seed at 0-0 at Kickoff + FINISHED Eviction

### 2A: Seed `live_scores` at 0-0 When Kickoff Fires

**APPROVED with guard.**

When `poll_kickoff_job` sends a kickoff notice, it MUST ALSO seed:

```python
scores = context.bot_data["live_scores"]
match_key = str(mid)
if match_key not in scores:
    scores[match_key] = {"home": 0, "away": 0, "status": "IN_PLAY"}
    save_scores(state_path, scores)
```

This ensures the first API tick with score 0-1 triggers a normal `reconcile(seen={0,0}, ann={0,0}, curr=0, 1)` → proper goal delta instead of the first-seen catch-up path.

**Stale-0-0 guard (postponed/suspended):**
- The existing `_match_is_over` (4h wall-clock) handles this: if a match is postponed after kickoff time, the 0-0 entry self-heals when the prune pass fires.
- **Additional guard (NEW, REQUIRED):** In `poll_goals_job`'s relevant filter, if a match has `status == "POSTPONED"` or `status == "SUSPENDED"` AND `match_key in scores`, evict it from `scores`/`seen_api`/`seen_thread` immediately and log a warning.
- **4h is acceptable** for the normal case (no match plays >3.5h including ET+pens).

### 2B: FINISHED-Match Eviction Policy

**APPROVED — evict after FIRST fully-processed FINISHED tick with no new delta.**

Current policy keeps FINISHED matches in `live_scores` until 4h prune. This creates repeated FINISHED-tick processing (candidate cause of Symptom B).

**New policy:**

```
In poll_goals_job, after processing a match where:
  - stored["status"] was already "FINISHED" (i.e., this is NOT the first FINISHED tick)
  - AND no new deltas were produced this tick
  - AND match is in scores
→ Evict: del scores[match_key], del seen_api[match_key] (if present),
         del seen_thread[match_key] (if present)
→ Save immediately.
```

**Safeguards:**

1. **First FINISHED tick still processes normally** — a goal that arrives exactly at FT (API reports FINISHED + score increment in same response) fires via normal `elif deltas` path BEFORE eviction is considered.
2. **FT recap not affected** — `poll_finished_matches_job` uses its own `finished_announced` set, NOT `live_scores`.
3. **Thread-job guard** — `poll_thread_goals_job` already skips matches not in `scores`.
4. **Timing: TWO-tick minimum** — The match must have been seen as FINISHED for at least one prior tick before eviction.

---

## DECISION 3 — Assessment of Kanté's Fix Plan

### Verdict: SOUND and MINIMAL. Approve with refinements above.

| Fix | Assessment |
|-----|-----------|
| **1. Seed at 0-0 at kickoff** | ✅ Correct root-cause fix for Symptom A. Low-risk. Added POSTPONED/SUSPENDED eviction guard. |
| **2. Recover scorer+video** | ✅ Correct — the data IS available, we're not fabricating. Specified precise fallback rules and dedup contract. |
| **3. Immediate save after thread-job goal claim** | ✅ Correct fix for save-window race (Symptom B candidate 2). Minimal — one `save_scores()` call inside the existing goal loop. |
| **4. FINISHED-match eviction** | ✅ Approved with two-tick-minimum safeguard above. Closes repeated FINISHED processing. |

---

# Kanté — Catch-Up / Double-Notify Bug Fix: Implementation Report

**Date:** 2026-06-27  
**Author:** Kanté (Backend Developer)  
**Requested by:** drdonoso (repo owner)  
**Based on:** Pirlo's design spec, confirmed B root cause from owner

---

## Status: IMPLEMENTED ✅

All 4 parts implemented. Full test suite: **1661 passed** (baseline 1644, +17 new tests).

---

## Confirmed Root Cause — Symptom B

Owner provided the actual Uruguay-Spain post-FT timeline:
- ~04:07 — Final recap sent (match over)
- 04:10 — "❌ Gol anulado (VAR) Uruguay 0-0 Spain" (spurious, post-FT)
- 04:11 — "⚽ ¡GOOOL! Spain 0-1, Álex Baena (42')" (same goal re-announced)

This is the Egypt-Iran oscillation but in the **post-FT, <4h window**. The Reddit thread parse flickered the VAR-disallowed event after FT → score dropped to 0-0, then restored to 0-1 → DISALLOWED then GOAL. The two-tick FINISHED eviction (Part 3) is the fix.

---

## Changes by Part

### Part 1 — 0-0 seed at kickoff
`poll_kickoff_job` now seeds `live_scores[str(mid)] = {home:0, away:0, status:IN_PLAY}` in its `finally:` block, immediately after announcing kickoff. Added POSTPONED/SUSPENDED eviction guard in `poll_goals_job`.

### Part 2 — Catch-up recovery from Reddit thread
New `_attempt_goal_recovery` async function. Called by `_process_goal_delta` when `delta.kind == "catchup"`:

1. Tries `scanner.find_thread_permalink(home, away)` (cached, no HTTP) → fallback to `scanner.find_match_thread` (HTTP, 5s timeout)
2. Calls `scanner.get_thread_body(permalink)` and `parse_goal_events(selftext)`
3. For each missed home/away goal target, finds the matching `GoalEvent`
4. If ALL matched: sends proper `_notify_goal` per goal, sets `seen_thread[match_key] = {home:curr, away:curr}`, returns `True`
5. If ANY goal can't be matched: returns `False` → falls through to `_notify_catchup`

Rule: ALL-proper or ALL-neutral, never mixed.

### Part 3 — FINISHED two-tick eviction
Inside `goal_lock`, before processing deltas, track `was_already_finished = (stored is not None and stored.get("status") == "FINISHED")`.

In the `else:` (no-delta) branch, if `was_already_finished` → evict: `scores.pop`, `seen_api.pop`, `seen_thread.pop`, `changed = True`.

Timeline:
- Tick N: stored = IN_PLAY → API = FINISHED, no delta → status updated to FINISHED, `was_already_finished=False` (no eviction)
- Tick N+1: stored = FINISHED → API = FINISHED, no delta → `was_already_finished=True` → evicted

### Part 4 — Immediate save in poll_thread_goals_job
`save_scores(state_path, scores)` moved INSIDE the `goal_lock`, immediately after score claim. Removed the deferred `if changed: save_scores(...)` at end of results loop.

### Part 5 — 5s timeout on find_match_thread
`find_match_thread` HTTP timeout reduced from 15s to 5s so `_attempt_goal_recovery` never hangs the poll job.

---

## Tests Added (+17)

**1644 baseline → 1661 final**

| Class | File | Count | What it covers |
|-------|------|-------|----------------|
| `TestFinishedEviction` | test_poll_goals_job.py | 5 | Eviction logic and Uruguay-Spain timeline |
| `TestCatchupRecovery` | test_poll_goals_job.py | 4 | Per-goal sends and fallback scenarios |
| `TestPostponedEviction` | test_poll_goals_job.py | 2 | POSTPONED/SUSPENDED eviction guards |
| `TestKickoffSeedLiveScores` | test_poll_kickoff_job.py | 3 | 0-0 seed and integration tests |
| `TestImmediateSave` | test_poll_thread_goals_job.py | 2 | Immediate save assertions |
| `TestPostFTEvictionDedup` | test_poll_thread_goals_job.py | 1 | Evicted match skipped by thread job |

---

# Review: Catch-Up / Double-Notify Fix (Parts 1–4)

**Date:** 2026-06-27  
**Reviewer:** Pirlo (Lead / Tech Lead)  
**Author:** Kanté  
**Status:** APPROVED  

---

## Summary

Implementation of the 4-part fix for catch-up (missed goals) and double-notify (post-FT oscillation) bugs. All 1661 tests pass. +17 new tests.

---

## 1. DEDUP — No Duplicate Announcement Window

**SAFE — no dedup hole found.**

Critical scenario: first-seen at non-zero (no kickoff seed), recovery sends proper notifications outside the lock while `poll_thread_goals_job` could concurrently run.

- `scores[key]` is claimed at the final score INSIDE the lock. When `poll_thread_goals_job` later acquires the lock, it reads the already-final score.
- Thread reads same score → `reconcile()` → no deltas.
- After recovery completes: `seen_thread[key]` is set → subsequent thread ticks at same score produce no delta.
- `seen_api[key]` is set → next API tick at same score: no delta.

## 2. TWO-TICK EVICTION — Correct

**Verified all scenarios:**

- **First FINISHED tick (IN_PLAY→FINISHED, no score change):** `was_already_finished=False` → updates status to FINISHED, no eviction
- **First FINISHED tick (IN_PLAY→FINISHED, with goal):** Goes to `elif deltas:` → goal announced, score claimed
- **Second FINISHED tick (FINISHED, no delta):** `was_already_finished=True` → **evicts**

## 3. RECOVERY FALLBACK — ALL-Proper or ALL-Neutral

**Rule strictly enforced:** Each target goal must find a matching event. If ANY target fails → immediate fallback. Only on full match: all goals notified.

## 4. HANG SAFETY — Bounded, Acceptable

**Worst case:** `find_thread_permalink` (0s, cached) + `find_match_thread` (5s) + `get_thread_body` (15s) = ~35s.

Why this is acceptable:
1. One-time event per match (first-seen with missed goals only).
2. Runs OUTSIDE the lock and via `asyncio.to_thread` — does not block event loop.
3. Outer `try/except Exception` catches any timeout → returns False → neutral fallback.
4. Same timeout profile as existing `_enrich_scorer` path.

---

## VERDICT: APPROVE

No required changes. Implementation is correct, matches the design spec, handles all edge cases, and is well-tested. Ship it.

---

# Buffon QA Gate — Catch-Up / Goal Pipeline Fix

**Date:** 2026-06-27  
**Reviewer:** Buffon (QA / Tester)  
**Author:** Kanté  
**Based on:** `kante-catchup-fix-impl-20260627.md`  
**VERDICT: PASS WITH ADDED TESTS (+4)**  
**Final pytest count: 1665 passed, 5 warnings**

---

## Summary

All 1661 tests pass on Kanté's baseline. All 5 warnings are pre-existing deprecation warnings unrelated to this change. ✅

Scrutiny of +17 new tests: all are real regressions. One initially-weak test `test_uruguay_spain_full_timeline_zero_post_ft_sends` used simplified oscillation that passed without the fix.

Added 4 edge-case tests by Buffon:
1. `test_var_flip_oscillation_post_ft_zero_sends` — true B regression (VAR-flip oscillation)
2. `test_age_prune_and_finished_eviction_no_crash` — age-prune + two-tick coexistence
3. `test_recovery_dedup_no_resend_on_next_thread_tick` — recovery dedup race
4. `test_neutral_fallback_no_loop_on_next_thread_tick` — neutral fallback loop prevention

---

## VERDICT

**PASS WITH ADDED TESTS (+4)**  
1665 passed, 5 warnings (all pre-existing)

---

# Decision: Standard Competition Ranking (1224 style)

**Date:** 2026-07-01  
**Author:** Kanté (backend)  
**Status:** Implemented, committed in 8987262

## Summary
Added `standard_competition_positions` helper to formatters.py that implements "1224 style" tie-aware ranking: tied participants share the same position and the next position skips accordingly. E.g., scores [31, 31, 30] → positions [1, 1, 3].

## Key Details
- **Input:** Pre-sorted list of ranking rows with `.total_score` attribute
- **Output:** List of 1-based competition positions
- **Tie rule:** Two rows are tied if `round(score_a, 1) == round(score_b, 1)`
- **Used by:** `/porra`, `/general`, `/clasificacion` commands and podium image feature
- **Test count:** 1951 passed (added 12 new tests)

## Files Changed
- `src/worldcup_bot/bot/formatters.py`: Added `standard_competition_positions` helper; updated `format_general_ranking`
- `tests/test_formatters.py`: Added `TestStandardCompetitionPositions` (9 cases) + `TestFormatGeneralRankingTieAwareNumbering` (3 cases)

---

# Decision: Podium Photo Compositing Feasibility & Approach

**Author:** Pirlo (Lead)  
**Date:** 2026-07-01  
**Status:** Proposal approved, implementation completed

## Feasibility Verdict
✅ **Merging tied photos into one combined image:** Fully feasible with Pillow 12.2.0  
✅ **Single podium image with crowns + position numbers:** Fully feasible with Pillow canvas + ImageDraw

## Recommended Approach (Option B — Single Podium Image)
- **Canvas:** Fixed 700 × 350 px, dark background
- **Tiles:** Uniform 200×200 px, circular crop optional, LANCZOS resize
- **Crown:** Single overlay per tile with position number inside/below
- **Placeholders:** Missing photos render as solid-color circles + initials (first letter of display name)
- **Layout:** Tie-aware positioning — tied positions share same y-height on canvas
- **Fallback chain:** Podium image → album (old code) → plain text

## Assets Needed
- `crown.png`: ~5 KB, 64×64 px, transparent background (or hand-drawn)
- `podium_font.ttf`: DejaVu Sans Bold (~700 KB, SIL OFL licensed) — required for Docker consistency

## Key Decisions
- **Missing photos:** Always generate placeholder (ensures podium always renders)
- **Crown rendering:** Bundle PNG asset (cleanest option)
- **Font:** Bundle TTF in assets (Docker slim images don't have system fonts reliably)
- **Layout adaptability:** Use `standard_competition_positions` to determine tie-aware heights
- **Always-on mode:** Replace album with podium image always (no branching on ties)

## Risk Level
Low — graceful fallback to text if anything fails. Effort estimate: ~1 working day.

## Prerequisite
`standard_competition_positions` helper must land first.

---

# Decision: Rich Image — Country-Themed Winners (2026-07-01 SHIPPED)

**Date:** 2026-07-01  
**Author:** Kanté (Backend)  
**Status:** ✅ SHIPPED (commit 47b7e41)

---

## Summary

Extended the daily `rich_image` feature: each day's image now incorporates opulent, country-themed luxury props inspired by yesterday's football-day winners — while the day-over-day wealth escalation continues unchanged.

---

## New / Changed Signatures

### `RICH_THEME_PROMPT` (module-level constant in `rich_image.py`)
A tunable prompt string instructing the chat model to return one opulent/funny/specific luxury visual element per winning country — comma-separated, no extra text. Bakes in David's vibe examples: Norway→golden Viking helmet; France→jewel-encrusted baguette; Mexico→gourmet nachos with truffle; England→tea in a solid gold cup; Belgium→a parliament building they bought outright; USA→surrounded by piles of US dollar bills.

### `generate_wealth_themes`
```python
async def generate_wealth_themes(
    api_key: str,
    base_url: str,
    model: str,
    winners: list[str],
    *,
    _client: object | None = None,   # inject for tests
) -> str
```
- Returns `""` immediately when `winners` is empty.
- Calls `client.chat.completions.create` with `RICH_THEME_PROMPT + " " + ", ".join(winners)`.
- **Best-effort / never raises**: on any exception returns `", ".join(f"opulent luxury {c}-themed elements" for c in winners)`.
- `_client` injectable (same pattern as `generate_rich_caption`).

### `build_rich_prompt`
```python
def build_rich_prompt(
    history: str = "",
    anchor: bool = False,
    themes: str = "",   # NEW — comma-sep opulent props
    pose: str = "",     # NEW — random activity
) -> str
```
When `themes` is non-empty appends:  
`" ALSO incorporate a few of these opulent, country-themed luxury elements into the scene, worked in tastefully (inspired by yesterday's winning countries): {themes}."`  

When `pose` is non-empty appends:  
`" In THIS image, show the person {pose}. VARY the pose and activity each time — do NOT default to sitting and toasting with champagne."`  

Insertion order: `history clause → themes clause → pose clause → anchor clause`.

### `POSE_ACTIVITIES` (module-level list, 14 entries)
Covering: dancing, standing on red carpet, lounging on a chaise longue, spa massage, partying with a crowd, napping in opulent bed, embracing a companion, walking a red carpet, posing with entourage, relaxing in infinity pool, being served by staff, laughing mid-celebration, striding through a luxury penthouse, being pampered at a private salon.

### `run_rich_iteration`
```python
async def run_rich_iteration(
    settings: Settings,
    *,
    _client: object | None = None,
    _caption_client: object | None = None,
    _data_dir: str = "/app/data",
    _now: datetime | None = None,
    winners: list[str] | None = None,   # NEW
) -> tuple[str, int, str]
```
- Computes themes: calls `generate_wealth_themes(... _client=_caption_client)` when `winners` is truthy and all three chat-model settings are non-empty; otherwise `themes = ""`.
- Picks random pose from `POSE_ACTIVITIES`.
- Passes `themes` and `pose` to `build_rich_prompt`.
- Does NOT pass `themes` to `generate_rich_caption` (caption uses original rude tone only).
- Logs `winners` and `themes`.

---

## Winners → Themes → Pose Flow

```
rich_image_job
    │
    ├─ make_client(settings)
    │       ↓
    │   client.get_football_day_matches(timezone, day_offset=-1, anchor_hour=...)
    │       ↓
    │   [FINISHED matches only; HOME_TEAM / AWAY_TEAM winners; DRAW skipped]
    │       ↓
    │   winners = ["Norway", "France", ...]   (or [] on error)
    │
    └─ run_rich_iteration(settings, winners=winners)
            │
            ├─ generate_wealth_themes(api_key, base_url, model, winners, _client=_caption_client)
            │       → "golden Viking helmet, jewel-encrusted baguette"  (or fallback)
            │
            ├─ random.choice(POSE_ACTIVITIES)
            │       → "dancing with champagne"
            │
            ├─ build_rich_prompt(history, anchor, themes=..., pose=...)
            │       → image-edit prompt with themes + pose clauses woven in
            │
            ├─ edit_rich_image(... prompt=prompt ...)
            │
            └─ generate_rich_caption(...)
                    → caption (themes NOT mentioned; original rude tone only)
```

Error-handling at every level:
- `get_football_day_matches` failure → `winners = []`, job continues.
- `generate_wealth_themes` exception → fallback string, never propagates.
- `generate_rich_caption` exception → default fallback caption, never propagates.

---

## Refinements Applied (2026-07-01, live-test feedback)

### 1. Too Much Gold → Varied Luxury

`RICH_THEME_PROMPT` now explicitly instructs the model NOT to default to gold/golden for every element and lists varied luxury materials: diamonds, platinum, marble, silk, crystal, caviar, designer furs, exotic woods, haute couture, precious jewels, rare materials. Examples reworked:
- Norway → a diamond-encrusted Viking longship
- France → a caviar-topped artisan baguette on a marble tray
- Mexico → a crystal platter of truffle nachos
- England → a silk-lined tea set with hand-painted porcelain cups
- Belgium → a private parliament building filled with Belgian chocolate sculptures
- USA → surrounded by piles of platinum-banded US dollar bills

### 2. Repeated Pose → Random Pose/Activity

`POSE_ACTIVITIES` list added with 14 varied entries. `build_rich_prompt` gained `pose` parameter. `run_rich_iteration` picks with `random.choice(POSE_ACTIVITIES)` each iteration. `RICH_EDIT_PROMPT` softened to encourage variation.

### 3. Caption Reverted (Themes OUT of Caption)

The rude/chulesco caption (`RICH_CAPTION_PROMPT`) is UNCHANGED and does NOT mention themes. Themes appear only in the image prompt (`build_rich_prompt`).

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/ai/rich_image.py` | `RICH_THEME_PROMPT`, `POSE_ACTIVITIES` consts; `generate_wealth_themes` func; extended `build_rich_prompt`, `run_rich_iteration` |
| `src/worldcup_bot/__main__.py` | `rich_image_job`: fetch yesterday's winners before calling `run_rich_iteration(settings, winners=winners)` |
| `tests/test_rich_image.py` | 53 new tests (35 initial + 18 refinements) |

---

## Test Count

**2071 passed** (+53 new tests, up from 2018). All green. Live-tested by coordinator: 2 runs of 5 iterations each sent to Telegram chat 3041850; David reviewed and approved.

---

# Decision: Podium Image Feature Implementation

**Author:** Kanté (backend)  
**Status:** Implemented, committed in 4343ddb

## Summary
Completed implementation of single composite podium image for ranking commands (`/porra`, `/general`), replacing plain URL album. Missing photos use initials placeholders. Falls back to old album if rendering fails.

## `render_podium` Signature
```python
def render_podium(participants: list[dict], settings) -> io.BytesIO | None
```
- **participants:** List of up to 3 dicts with `username`, `display_name`, `position` (tie-aware from `standard_competition_positions`)
- **settings:** Settings instance; only `settings.photo_base_url` used
- **Returns:** PNG BytesIO seeked to 0, or None on failure
- **Threading:** Synchronous; call with `asyncio.to_thread`

## Fallback Chain in `_send_ranking_with_top3_photos`
```
podium image (render_podium → BytesIO)
    ↓ None
album (send_media_group with valid photo URLs)
    ↓ no valid URLs or send_media_group raises
plain text (reply_text)
```

## Visual Design
| Property | Value |
|----------|-------|
| Canvas | 720 × 400 px, dark navy `(22, 27, 34)` |
| Tile shape | Circle, diameter 180 px, LANCZOS resize |
| Tile missing | Solid-color circle + initials (first + last initial) |
| Placeholder colours | Steel blue / sea green / firebrick (by index) |
| Crown | Filled gold polygon (11 vertices) + 3 jewel circles; **drawn with Pillow, no external assets** |
| Position number | 22 pt DejaVu Sans Bold, white |
| Participant name | 16 pt light grey, below tile; truncated at 14 chars |
| Classic podium | 3 participants: centre = 1st, left = 2nd, right = 3rd |
| Tie-aware heights | Position 1→205 px, 2→237 px, 3→257 px |

## Crown Drawing
Entirely drawn with Pillow `ImageDraw.polygon` + `ImageDraw.ellipse`:
- Single filled polygon: band + 3 spikes (11 vertices)
- Three jewel circles at spike tips
- Copyright-safe, requires zero new asset files

## Font Resolution
`matplotlib.font_manager.findfont(FontProperties(family="DejaVu Sans", weight="bold"))` → resolves to bundled `DejaVuSans-Bold.ttf` inside matplotlib package. Fallback: `ImageFont.load_default()`. No new deps (matplotlib already a project dependency).

## Changes
| File | Change |
|------|--------|
| `src/worldcup_bot/bot/podium_image.py` | New module with `render_podium`, `_render_podium`, `_draw_crown`, `_fetch_tile`, `_circular_crop`, `_placeholder_tile` |
| `src/worldcup_bot/bot/handlers.py` | Imports + `_send_ranking_with_top3_photos` rewrite with fallback chain |
| `tests/test_handlers.py` | `TestSendRankingWithPodium` (5 tests) + `_stub_render_podium` autouse fixture |
| `tests/test_podium_image.py` | New — 12 smoke tests for `render_podium` |

## Test Count
1968 passed (0 regressions)

---

# Decision: Podium Image Review — APPROVED

**Reviewer:** Pirlo (Lead)  
**PR Scope:** `src/worldcup_bot/bot/podium_image.py` + `handlers.py` diff  
**Test Suite:** 1968 passed ✅

## Review Checklist Results

| Criterion | Status |
|-----------|--------|
| Fallback Chain (podium → album → text) | ✅ PASS |
| Non-blocking (asyncio.to_thread) | ✅ PASS |
| Never Raises contract | ✅ PASS |
| Tie-Awareness (positions via `standard_competition_positions`) | ✅ PASS |
| Caption handling (1024 limit + overflow) | ✅ PASS |
| No new deps / no bundled art | ✅ PASS |
| Missing-photo fallback (initials placeholders) | ✅ PASS |
| Test suite green | ✅ PASS (1968 passed, 5 pre-existing warnings) |

## Verdict
✅ **APPROVE** — Clean, well-structured implementation. Fallback chain robust. Tie logic correct. No regressions. Ready to ship.

## Minor Observations (non-blocking)
1. **Serial photo fetches:** Only 3 requests, acceptable. Future `ThreadPoolExecutor` optimization not needed now.
2. **Font path cached at import:** Fine — matplotlib's font cache is fast. Fallback covers edge cases.
3. **`r.display_name` assumption:** Correct — `UserRankEntry` includes it.




---

# Decision: TVE Knockout-Round Prefix Fix

**Author:** Kanté (Backend Dev)  
**Date:** 2026-07-03  
**Status:** Implemented — awaiting quick review, then commit by David

---

## Bug Summary

Every knockout-stage match was missing the 📺 TVE label in `/hoy` and `/siguiente`. Group-stage matches were fine. Reported live by David (Argentina vs Cabo Verde at 00:00).

---

## Root Cause

RTVE names **knockout** episode items with a leading round token:

```
"Futbol Copa Mundo Fifa 1/16 Argentina - Cabo Verde"
                       ^^^^ round token
```

Group-stage items have no such token:

```
"Futbol Copa Mundo Fifa Argentina - Austria"
```

`_parse_teams` in `tve.py` only stripped `_WC_EPISODE_PREFIX` (`"Futbol Copa Mundo Fifa "`), leaving:

```
"1/16 Argentina - Cabo Verde"
```

Split on `" - "` → `home_raw = "1/16 Argentina"`, `away_raw = "Cabo Verde"`.  
`ES_NAME_TO_TLA.get(_norm("1/16 argentina"))` → **None** (no entry for the token-prefixed form).

Result: `home_tla = None`, `away_tla = CPV`.

`tve_channel_for` same-day TLA fallback requires **both TLAs to be known** (to prevent ambiguous cross-matching for simultaneous same-day fixtures). With `home_tla = None`, the fallback was skipped → returned `None` → no 📺 label.

### Live Evidence (from David's pre-fix diagnostic)

All knockout broadcasts had `home_tla = None`:

```
None-CPV, None-CAN, None-JPN, None-SWE, None-AUT, None-FRA, None-NOR
```

Group-stage broadcasts parsed correctly (no round token):

```
URY-ESP, COL-POR, ECU-GER  ← these were fine
```

---

## The Fix — `src/worldcup_bot/tve.py`

Added `_ROUND_PREFIX_RE` constant after `_WC_EPISODE_PREFIX`:

```python
_ROUND_PREFIX_RE = re.compile(
    r"^(?:"
    r"\d+/\d+"                          # fraction form: 1/16, 1/8, 1/4
    r"|octavos?(?:\s+de\s+final)?"      # Octavos (de final)
    r"|cuartos?(?:\s+de\s+final)?"      # Cuartos (de final)
    r"|semifinal(?:es)?"                # Semifinal, Semifinales
    r"|final"                           # Final
    r"|tercer\s+puesto"                 # Tercer puesto
    r"|3[^\s]*(?:\s*y\s*4[^\s]*)?\s*puesto"  # 3º y 4º puesto variants
    r")\s+",
    re.IGNORECASE,
)
```

Applied in `_parse_teams`, after the existing episode-prefix strip:

```python
stripped = _WC_EPISODE_PREFIX.sub("", raw).strip()
# NEW: strip leading knockout-round token
stripped = _ROUND_PREFIX_RE.sub("", stripped)
```

### Why it's safe

- The regex is anchored at `^` — only matches at the very start of the stripped name.
- Real team names never start with `\d+/\d+` or the named round words.
- Group-stage names have no round token → `_ROUND_PREFIX_RE.sub("", s) == s` (unchanged).
- All round forms covered: fraction (1/16, 1/8, 1/4), named in Spanish (Octavos, Cuartos, Semifinal/es, Final, Tercer puesto, 3º y 4º puesto variants).
- `_match_is_over`, `reconcile`, and all existing invariants are unaffected — this is purely a name-parsing fix in `tve.py`.

---

## Live Before/After (verified via venv + `.env`)

```
Input: "Futbol Copa Mundo Fifa 1/16 Argentina - Cabo Verde"

BEFORE fix:
  After prefix-only strip: "1/16 Argentina - Cabo Verde"
  home_raw = "1/16 Argentina", away_raw = "Cabo Verde"
  → (None, 'CPV')

AFTER fix:
  After round-prefix strip: "Argentina - Cabo Verde"
  home_raw = "Argentina", away_raw = "Cabo Verde"
  → ('ARG', 'CPV')

tve_channel_for(ARG vs CPV, broadcasts):
  BEFORE: None
  AFTER:  'Teledeporte'
```

Today's schedule showed one ARG-CPV broadcast on Teledeporte at 21:00 UTC (60 min before the 22:00Z kickoff). The ±20 min primary window doesn't catch it, but the same-day TLA fallback does — and now that both TLAs are known, it fires correctly.

---

## Tests Added (17 new → 2151 total)

### `tests/test_tve.py`

| Class | Test | Coverage |
|-------|------|----------|
| `TestParseTeamsRoundPrefix` | `test_1_16_argentina_cabo_verde` | Live bug |
| | `test_1_8_fraction_form` | 1/8 form |
| | `test_1_4_fraction_form` | 1/4 form |
| | `test_semifinal_singular` | "Semifinal" (without 'es') |
| | `test_semifinales_plural` | "Semifinales" |
| | `test_final` | "Final" |
| | `test_cuartos_de_final` | "Cuartos de final" |
| | `test_cuartos_without_de_final` | "Cuartos" (short form) |
| | `test_group_stage_no_round_token_unchanged` | Regression guard |
| | `test_group_stage_espana_unchanged` | Regression guard (accented) |
| | `test_original_event_name_field_also_works` | Both name fields |
| `TestParseWcBroadcastsKnockout` | `test_1_16_arg_cpv_both_tlas_parsed` | End-to-end parse |
| | `test_1_8_fra_nor_both_tlas_parsed` | End-to-end parse |
| | `test_semifinal_arg_fra_both_tlas_parsed` | End-to-end parse |
| `TestTveChannelForKnockout` | `test_knockout_1_16_arg_cpv_same_day_tla_fallback` | Fallback now fires |
| | `test_knockout_none_home_tla_returns_none` | Pre-fix regression guard |
| | `test_knockout_la1_preferred_over_teledeporte` | La 1 preference |

Full suite: **2151 passed, 0 failures**.

---

## Files Changed

| File | Change |
|------|--------|
| `src/worldcup_bot/tve.py` | Added `_ROUND_PREFIX_RE`; applied in `_parse_teams`; fixed `_parse_kickoff_utc` for over-midnight hours |
| `tests/test_tve.py` | Added `_parse_kickoff_utc` + `_parse_teams` to imports; 3 new test classes for round prefix (17 tests); 1 new class for midnight notation (6 tests) |
| `.squad/agents/kante/history.md` | Session entry added |

---

## Fix 2 — `_parse_kickoff_utc`: RTVE Over-Midnight Notation (24:00 / 25:xx)

**Date:** 2026-07-03 (same session, second root cause)

### Root Cause

The round-prefix fix surfaced a second root cause: La 1 was still being **dropped** by `parse_wc_broadcasts`.

For the Argentina-Cabo Verde midnight match, the La 1 item's description is:

```
'Incluye:Nº 23 Previo\r(24:00) ARGENTINA / CABO VERDE \rNº 23 Post\r'
```

RTVE uses **Spanish TV convention**: midnight = `24:00`, and after-midnight = `25:00`, `25:30`, `26:00`, etc.

`_parse_kickoff_utc` (La 1 path) extracts `"24:00"` from `_KICKOFF_RE`, then calls:

```python
datetime.strptime(f"{date_str} 24:00", "%Y%m%d %H:%M")
```

Python's `datetime.strptime` rejects hour 24 with `ValueError` → the `except` returns `None` → `parse_wc_broadcasts` logs "skipping item with unparseable kickoff" and **drops the La 1 broadcast entirely**.

Result: only Teledeporte broadcast survived (it uses `begintime` directly, which had a normal hour). `tve_channel_for` returned `"Teledeporte"` instead of `"La 1"`.

### The Fix

Replaced `datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M")` with manual hour/minute parsing plus `timedelta` rollover:

```python
hh, mm = time_str.split(":")
hour = int(hh)
minute = int(mm)
# RTVE uses Spanish "over-midnight" notation: 24:00 = midnight next day,
# 25:30 = 01:30 next day, etc.  Roll over when hour >= 24.
day_offset = hour // 24
hour_mod = hour % 24
date_base = datetime.strptime(date_str, "%Y%m%d")
dt_naive = date_base.replace(hour=hour_mod, minute=minute) + timedelta(days=day_offset)
local_dt = _MADRID_TZ.localize(dt_naive)
return local_dt.astimezone(_UTC)
```

- `"24:00"` on `20260703`: `day_offset=1`, `hour_mod=0` → `datetime(2026-07-04 00:00)` Madrid CEST → **UTC 2026-07-03 22:00**
- `"25:30"` on `20260703`: `day_offset=1`, `hour_mod=1` → `datetime(2026-07-04 01:30)` → **UTC 2026-07-03 23:30**
- `"20:45"` (normal): `day_offset=0`, `hour_mod=20` → exact same result as before (**regression-safe**)

Applied to both the description-derived `time_str` and the `begintime` fallback (same code path; defensive for both).

### Live Before/After (both fixes combined)

```
_parse_kickoff_utc(La 1 item, "La 1"):
  BEFORE fix:  None  (strptime raised ValueError on hour=24)
  AFTER fix:   2026-07-03 22:00:00+00:00  ✓

ARG/CPV La 1 broadcast:
  BEFORE:  dropped (None kickoff → skipped)
  AFTER:   channel=La 1, kickoff_utc=2026-07-03 22:00:00+00:00, home=ARG, away=CPV

ARG/CPV Teledeporte broadcast:
  channel=Teledeporte, kickoff_utc=2026-07-03 21:00:00+00:00 (from begintime, unchanged)

tve_channel_for(ARG vs CPV):
  BEFORE (round-prefix fix only):  'Teledeporte'  (La 1 was dropped)
  AFTER (both fixes):              'La 1'  ✓
  (La 1 at 22:00 UTC hits the ±20 min PRIMARY window; Teledeporte at 21:00 UTC falls back to same-day TLA; La 1 wins)
```

### Tests Added (6 new → 2157 total)

#### `tests/test_tve.py` — `TestParseKickoffUtcMidnightNotation`

| Test | Coverage |
|------|----------|
| `test_24_00_la1_description_gives_next_day_midnight` | Live bug case: `(24:00)` on 20260703 → UTC 22:00 |
| `test_25_30_la1_description_gives_next_day_01_30` | `(25:30)` → UTC 23:30 (madrugada) |
| `test_normal_time_la1_unchanged` | `(20:45)` → no rollover (regression guard) |
| `test_begintime_fallback_normal_hour_unchanged` | Teledeporte begintime normal hour unchanged |
| `test_parse_wc_broadcasts_la1_24h_item_valid_kickoff` | End-to-end: round prefix + 24:00 item → ARG, CPV, 22:00 UTC |
| `test_tve_channel_for_la1_24h_kickoff_primary_window` | La 1 at 22:00 wins via primary window |

Full suite: **2157 passed, 0 failures**.

---

# Review: TVE Knockout-Round Prefix + Midnight Notation Fix

**Reviewer:** Pirlo (Lead)  
**Date:** 2026-07-03  
**Scope:** `src/worldcup_bot/tve.py` — `_ROUND_PREFIX_RE` + `_parse_kickoff_utc` rollover  
**Test suite:** 2157 passed ✅  

---

## Checklist

### 1. Round-Prefix Regex — No False Stripping ✅ PASS

```python
_ROUND_PREFIX_RE = re.compile(
    r"^(?:\d+/\d+|octavos?...|cuartos?...|semifinal(?:es)?|final|tercer\s+puesto|3...puesto)\s+",
    re.IGNORECASE,
)
```

**Anchored at `^`** — only matches at the start of the already-prefix-stripped string.
A team name containing a round word mid-string (hypothetical) is never affected.

**Trailing `\s+` required** — the word "final" alone without a trailing space doesn't
match; only "Final España..." (with space after) does. This prevents eating the word
"final" if it somehow appeared as the only content.

Verified with manual tests:
- `"Uruguay - España"` → unchanged ✓ (no round token at start)
- `"Argentina - Austria"` → unchanged ✓
- `"Ecuador Final"` → unchanged ✓ (not anchored at start)
- `"1/16 Argentina - Cabo Verde"` → stripped to `"Argentina - Cabo Verde"` ✓
- `"Semifinal Brasil - Alemania"` → stripped to `"Brasil - Alemania"` ✓
- `"Final España - Francia"` → stripped to `"España - Francia"` ✓

**Both name fields** (`original_episode_name`, `original_event_name`) go through the
same `_parse_teams` function — both get the round-prefix strip. No path is left raw.

**`_teams_match` is unaffected** — the round-prefix strip only happens during TLA
extraction in `_parse_teams`. `tve_channel_for`'s matching logic uses the extracted
TLAs, not raw names.

### 2. 24:00 Rollover — Regression-Safe for Normal Times ✅ PASS

```python
hh, mm = time_str.split(":")
hour = int(hh)
minute = int(mm)
day_offset = hour // 24      # 0 for hour<24, 1 for 24-47
hour_mod = hour % 24         # actual hour-of-day
date_base = datetime.strptime(date_str, "%Y%m%d")
dt_naive = date_base.replace(hour=hour_mod, minute=minute) + timedelta(days=day_offset)
```

For **normal times** (hour < 24):
- `day_offset = 0`, `hour_mod = hour` → `date_base.replace(hour=hour, minute=minute) + 0`
- Identical to the old `strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M")`. ✓

For **over-midnight** (hour ≥ 24):
- `"24:00"` on 20260703 → `day_offset=1, hour_mod=0` → `2026-07-04 00:00` Madrid → UTC 22:00 ✓
- `"25:30"` → `day_offset=1, hour_mod=1` → `2026-07-04 01:30` Madrid → UTC 23:30 ✓

**DST-safe:** `_MADRID_TZ.localize(dt_naive)` handles the rollover date correctly —
if the rollover crosses a DST boundary, pytz resolves the right offset.

### 3. Best-Effort / Non-Fatal Preserved ✅ PASS

The entire `_parse_kickoff_utc` body is wrapped in `try/except Exception` (line 298-300):
```python
except Exception as exc:
    log.debug("TVE: failed to parse kickoff from item %r: %s", item, exc)
    return None
```

If `time_str` is malformed (non-numeric, no colon, etc.), `split(":")` or `int()` will
raise, caught by the existing except → returns None → broadcast skipped gracefully.
Same for `_parse_teams`: returns `(None, None)` on any parse failure. No crash path.

### 4. No Regression — Suite Green ✅ PASS

```
2157 passed, 5 warnings in 65.17s
```

All 86 TVE tests pass, including existing group-stage tests (regression guards) and
23 new tests covering round prefixes + midnight notation.

---

## VERDICT: ✅ APPROVE

Both fixes are surgical and regression-safe. The regex is properly anchored (`^` + trailing
`\s+`), the rollover arithmetic is identity for hour<24, and all parse failures remain
non-fatal. 2157 tests pass. Ship it.

