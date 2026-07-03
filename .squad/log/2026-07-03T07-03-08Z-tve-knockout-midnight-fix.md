# Session Log — TVE Knockout-Midnight Fix

**Session:** 2026-07-03T07-03-08Z

---

## What Shipped

Two-part fix for TVE broadcast channel detection in knockout matches:

1. **Round-Prefix Stripping** (`tve.py` `_ROUND_PREFIX_RE`): RTVE knockout episode names carry leading round token. Regex strips "1/16", "Semifinal", etc. before team parsing.

2. **Over-Midnight Notation** (`tve.py` `_parse_kickoff_utc`): La 1 uses Spanish "24:00" for midnight. Manual hour/minute parsing + `timedelta` rollover replaces `strptime` for hours >= 24.

**Live Verification:** `tve_channel_for(ARG vs CPV)` now returns `'La 1'` ✓

**Tests:** 2157 passed (+23)

**Commit:** 8087d83

---

## Files Changed

- `src/worldcup_bot/tve.py`
- `tests/test_tve.py`
- `.squad/agents/kante/history.md`

**Status:** ✅ Main branch ready
