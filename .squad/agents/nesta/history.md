# Nesta — history

## Learnings

### 2026-07-05 — /elecciones increment 2 revision (Kanté rejected by Pirlo)

Owned the fix-forward after Pirlo rejected Kanté's elecciones image/hourglass work
(`30919a7`). Under the reviewer-gate lockout Kanté couldn't revise, so I owned it.

- **Cache staleness (BLOCKER 1).** The elecciones cache version only hashed
  FINISHED stage results (`get_stage_results`), so a "cuadro no disponible"
  artifact rendered before any ties existed kept being served after ties got
  *scheduled* (md5 unchanged — no finished result). Fixed with BOTH: (a)
  `_elecciones_results_version` now hashes the full scheduled tie identity
  (`get_all_matches()` pairings for the stage) + winners, so it invalidates the
  moment ties appear/change; (b) transient artifacts (no-ties, API errors, the
  groups-image API-failure text fallback) are marked `cacheable: False` and never
  stored. `get_stage_results` already calls `get_all_matches` internally (TTL
  cached 60s), so (a) added no extra HTTP calls.

- **Telegram 4096 hard split (BLOCKER 2).** `_split_messages` packed to a soft
  threshold then added the header + `(i/n)\n` prefix AFTER — a near-limit block
  produced parts >4096 (Pirlo saw 4098), and a single overlong line passed
  through unsplit. Rewrote so `block_budget = 4096 − PREFIX_RESERVE(16) −
  (len(header)+2)`, every block is pre-split to that budget, and `_split_block_
  at_lines` now hard-splits a single overlong line at a character boundary.
  Tracked `blocks_in_current` (not `len(current)>1`) so we never force two blocks
  into one message unchecked. Every emitted part is now provably ≤4096.

- **Twemoji 404 (the "no flags, only TLA text" bug).** `_TWEMOJI_BASE` pointed at
  `cdn.jsdelivr.net/npm/twemoji@14.0.2/...` which 404s for EVERY flag (npm package
  ships no assets there). Empirically verified the GitHub tree
  `cdn.jsdelivr.net/gh/twitter/twemoji@v14.0.2/assets/72x72` returns 200. This
  alone restores all standard flags.

- **ENG/SCO/WAL tag-sequence flags.** Extended `_flag_url` for 5-char ISO values
  starting "GB": `1f3f4-` + tag chars (`0xE0000 + ord(c)` per lowercase letter) +
  `-e007f.png`. GBNIR has no asset → returns None → existing TLA-text fallback.
  Verified England/Scotland/Wales URLs return 200.

- **Graceful fallbacks (non-blocking).** Groups image on standings-API failure now
  falls back to the TEXT renderer instead of rendering a blank grid (and isn't
  cached). Hourglass delete failure now best-effort edits the placeholder to a
  neutral notice ("📊 Predicciones 👇") so no stale ⏳ lingers, then still delivers
  the result.

- **Gotcha:** an existing test asserted `_flag_url("ENG") is None` and another
  asserted a single overlong line is NOT split — both encoded the OLD (buggy)
  behavior. Owning the revision meant updating those tests to the new contract.

### 2026-07-06 — FINAL seed-path fix (3rd revision, SHIPPED)

Escalation revision after Kanté (a61757d) and Cannavaro (615c34e) both rejected by Pirlo.

**Problem:** Startup seed path added ALL matches >4h old to `finished_announced` (dedup set), regardless of status — including stale `IN_PLAY` and `PAUSED`. On restart during stuck API state, the official final recap was permanently suppressed once the API eventually flipped to `FINISHED`.

**Root:** Only two write sites to `finished_announced`: seed + loop. Seed wasn't guarded on FINISHED status; loop was already correct.

**Fix — FINISHED-only invariant:** `finished_announced` now populated ONLY for `status == "FINISHED"` at every write:
- Seed: `seeded = {m.id for m in all_matches if m.status == "FINISHED"}` (stale IN_PLAY/PAUSED excluded)
- Loop: already compliant (inside `new_ids` subquery, added comment)
- Non-FINISHED >4h: handled via separate `provisional_announced` set (never consumes finished)

**Tests:** Rewrote `TestFirstRunSeedWithAge` to assert FINISHED-only seeding. Added three restart regressions: IN_PLAY→FINISHED, PAUSED→FINISHED, genuinely-FINISHED-seeded. Each asserts exactly-once announcement. 2231 tests pass.

**Commit:** a8b9c5f (initial investigation; final fix bundled in later commit)

Full suite: **2346 passed** (2332 baseline + 14 new tests), 0 failures.

---

### 2026-07-04 — FINAL-announcement seed-path fix (escalation, 3rd revision)

Owned the fix-forward after Pirlo rejected Kanté (a61757d) and Cannavaro (615c34e)
twice. Under the reviewer-gate lockout, neither prior author could revise, so I
owned it independently.

- **The seed-path bug.** `poll_finished_matches_job` in
  `src/worldcup_bot/__main__.py` has TWO paths that write the real-final dedup
  set `finished_announced`: the normal per-tick loop AND the first-run / startup
  SEED path. Cannavaro fixed the loop (provisional path for stuck IN_PLAY) but
  the seed still added ANY match over-by-wall-clock (`kickoff > MATCH_OVER_AGE`,
  4 h) into `finished_announced` regardless of status — including stale IN_PLAY
  and PAUSED. On a restart while football-data is still stuck IN_PLAY (the real
  Australia–Egypt failure mode, ~9.5 h lag), the seed marked the match
  final-deduped, so `new_ids = finished_ids - announced` excluded it forever and
  the official 🏁 Final recap was permanently suppressed.

- **The FINISHED-only dedup invariant.** `finished_announced` must be populated
  ONLY for matches whose `status == "FINISHED"`, at EVERY write site. Audited all
  writes in the finished job:
  - first-run seed (was `~line 1690`) — FIXED to `{m.id for m in all_matches if
    m.status == "FINISHED"}`.
  - main-loop `announced.add(match_id)` for the None-match guard and the `finally`
    block — both live inside `for match_id in new_ids`, and
    `new_ids ⊆ finished_ids` (`status == "FINISHED"`), so already compliant.
  - Note: `poll_kickoff_job` also uses a local `announced` var, but that is the
    SEPARATE `kickoff_announced` set (`kickoff_announced.json`) — unrelated.

- **Non-FINISHED over-by-wall-clock matches** are simply left UNSEEDED. The
  normal per-tick pass routes a stuck IN_PLAY through the SEPARATE
  `provisional_announced` set (⏳ provisional notice, persisted, restart-safe),
  and waits for a PAUSED match to legitimately reach FINISHED (PAUSED may be a
  resumable suspension). When the API finally reports FINISHED, the official
  recap fires with the API-confirmed score — the official message IS the
  correction.

- **Key file:line areas** (`src/worldcup_bot/__main__.py`):
  - `MATCH_OVER_AGE` / `_match_is_over` ≈ lines 113, 131-144.
  - `poll_finished_matches_job` starts ≈ line 1631; seed block ≈ 1689-1711;
    provisional block ≈ 1716-1765; main FINISHED loop ≈ 1773-1927; VAR-correction
    watch call ≈ 1930.
  - build_app state init: `finished_announced`/`finished_seeded` ≈ 2178-2181,
    `provisional_announced` ≈ 2186-2187.

- **Tests** (`tests/test_poll_finished_job.py`): rewrote `TestFirstRunSeedWithAge`
  and `TestStaleLaterFlip` to assert FINISHED-only seeding, and replaced
  `test_stale_inplay_seeded_on_first_run_not_announced` with restart regressions
  (IN_PLAY→FINISHED, PAUSED→FINISHED, genuinely-FINISHED-seeded-not-reannounced).
  Full suite: 2231 passed.
