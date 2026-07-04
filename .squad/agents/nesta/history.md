# Nesta — history

## Learnings

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
