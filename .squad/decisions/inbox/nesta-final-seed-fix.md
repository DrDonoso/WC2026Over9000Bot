# Decision — FINAL seed-path fix (FINISHED-only dedup invariant)

Author: Nesta (backend, escalation)
Date: 2026-07-04
Re: 3rd revision of the FINAL-announcement fix. Fix-forward on `main`.
Prior rejects: a61757d (Kanté), 615c34e (Cannavaro). Requested by: danielrdon.

## The remaining bug (Pirlo's re-review of 615c34e)

`poll_finished_matches_job` (`src/worldcup_bot/__main__.py`) has TWO code paths
that could write the real-final dedup set `finished_announced`:

1. the normal per-tick loop (Cannavaro fixed this — provisional path), and
2. the first-run / startup **SEED** path.

The seed path was still adding EVERY match over-by-wall-clock
(`kickoff > MATCH_OVER_AGE`, 4 h) into `finished_announced` regardless of status,
including stale `IN_PLAY` and `PAUSED`. Consequences:

- On a restart while football-data is still stuck `IN_PLAY` for a match that
  really ended (the production Australia–Egypt failure mode), the seed marks it
  final-deduped. When the API finally flips to `FINISHED`,
  `new_ids = finished_ids - announced` excludes it and the official 🏁 Final
  recap is **permanently suppressed**.
- `PAUSED` >4h (possibly a resumable suspension) was likewise treated as
  already-handled, suppressing its future official final.

## The fix — the FINISHED-only dedup invariant

**Invariant:** `finished_announced` (the real-final dedup) is populated ONLY for
matches whose `status == "FINISHED"`, at EVERY write site.

Audited every write to `finished_announced` in the finished job and guarded them
all on FINISHED:

- **First-run seed** — CHANGED. Now seeds only genuinely finished matches:
  `seeded = {m.id for m in all_matches if m.status == "FINISHED"}`.
  Non-FINISHED over-by-wall-clock matches (stale `IN_PLAY` / `PAUSED`) are NOT
  seeded — they stay eligible for the later official recap.
- **Main loop `announced.add(...)`** (the None-match guard and the `finally`
  block) — already compliant: both are inside `for match_id in new_ids`, and
  `new_ids ⊆ finished_ids` where `finished_ids = {m.id ... if status ==
  "FINISHED"}`. Added a comment at the `new_ids` definition documenting this.
- Not a write site: `poll_kickoff_job` uses a local `announced` bound to the
  SEPARATE `kickoff_announced` set — untouched.

Non-FINISHED "over" matches are handled by the existing, already-approved normal
path:
- stuck `IN_PLAY` >4h → ⏳ provisional notice tracked in the SEPARATE persisted
  `provisional_announced` set (never consumes `finished_announced`);
- `PAUSED` → excluded from the provisional path, announced only when it
  legitimately reaches `FINISHED`.

When the API eventually reports `FINISHED`, the official recap fires with the
API-confirmed score (self-correcting), clears the provisional marker, and the
existing VAR-correction watch still handles genuine post-final score changes
within its window.

## Restart / no-double-announce guarantees

- (over + `IN_PLAY` at startup → later `FINISHED`): NOT seeded; provisional may
  fire once (deduped via persisted `provisional_announced`); official `FINISHED`
  fires exactly once.
- (over + `PAUSED` at startup → later `FINISHED`): NOT seeded; no provisional;
  official `FINISHED` fires exactly once.
- (genuinely `FINISHED` at startup): seeded on first run, never re-announced.

## Tests

`tests/test_poll_finished_job.py`:
- `TestFirstRunSeedWithAge` — rewritten to assert FINISHED-only seeding (stale
  `IN_PLAY` and `PAUSED` NOT in `finished_announced`; disk persists only the
  FINISHED id).
- `TestStaleLaterFlip` — rewritten: an unseeded stale match that flips to
  `FINISHED` now DOES get the official recap.
- Replaced `test_stale_inplay_seeded_on_first_run_not_announced` with
  `test_stale_inplay_not_seeded_on_first_run` plus three restart regressions:
  IN_PLAY→FINISHED, PAUSED→FINISHED, and genuinely-FINISHED-seeded-not-
  reannounced — each asserting exactly-once official announcement.

Full suite `.venv\Scripts\python.exe -m pytest -q`: **2231 passed** (~64 s).
`docker-compose*.yml` untouched.
