# Orchestration Log: Strengthen Armed-Conflict Notes in Daily Update

**Date:** 2026-06-16T14:46:04Z (UTC)  
**Round:** Strengthen historical/armed-conflict notes in daily update  
**Status:** COMPLETE

## Summary

Kanté rewrote the `_SYSTEM` prompt in `src/worldcup_bot/ai/daily_update.py` to enforce a three-tier priority for `today_notes`:

1. **Armed conflict (priority):** Name real armed conflicts concretely (e.g., "Guerra de las Malvinas/Falklands (1982)").
2. **Other genuine curiosity:** Colonial history, territorial dispute, memorable WC match (only if documented).
3. **Empty string:** No filler. Forbidden: inventing facts, generic phrases like "es un partido bonito".

The rule is stated up-front and unconditionally before scenario-specific guidance, so it fires in all scenarios (`normal`, `reanudacion`, `pausa`).

## Verification (Coordinator)

**Live test runs (3 synthetic conflict matchups):**
- England–Argentina → Named "Falklands/Malvinas War (1982)"
- Israel–Palestine → Concrete armed-conflict note (Gaza, Cisjordania, tactful)
- Japan–Canada → Empty string (no filler)

**Consistency:** Consistent across all 3 runs.

## Code & Tests

- **Files changed:** `src/worldcup_bot/ai/daily_update.py`, `tests/test_ai.py`
- **New tests:** `TestSystemPromptContract` (5 tests asserting prompt structure)
- **Test count:** 619 passing (614 existing + 5 new)
- **Commit:** `8c029c5` pushed to origin/main
- **CI:** Rebuilding Docker image

## Decision Record

Decision summary added to `.squad/decisions.md` (merged from inbox).

## Known Issues

None. Feature live-verified and ready for deployment.
