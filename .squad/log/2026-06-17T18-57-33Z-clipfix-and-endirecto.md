# Session Log — Clipfix & Endirecto Live Detail

**ISO8601:** 2026-06-17T18:57:33Z  
**Commits:** 5a6e654 (kante-32/33 clip robustness), be7e520 (kante-34 endirecto enrichment)

## Overview

Live stability improvements for goal-clip matching and match enrichment. Robust scorer format handling (accent-fold, token-intersection), HTML search + /new/ listing merge fallback, and OpenAI-extracted live match detail via r/soccer thread "MATCH EVENTS" section.

**Verification:** 1205 tests pass; live E2E against Portugal 2-1 D.R. Congo confirmed minute + goals + cards + subs rendered and sent.

## Key Fixes

1. **Scorer matching:** Accent-normalized, token-based, ±3 minute tolerance.
2. **Clip search fallback:** Merge `/new/` listing when JSON search fails.
3. **Live detail:** Extract goals/cards/subs from r/soccer Match Thread; fallback to score-only on any error.

## Deployed

- kante-32: robust-goal-clip-scorer-match
- kante-33: clip-merge-new-listing
- kante-34: endirecto-live-detail
