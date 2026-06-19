# Session: Daily Update Full Names Fix

**Timestamp:** 2026-06-19T07:35:47Z (UTC)  
**Commit:** 75530e7 (on origin/main)  
**Author:** Kanté

## Summary

Fixed participant name bolding in AI daily updates by strengthening the _SYSTEM prompt to require full names, never first-name-only. Added inline reminder in build_ai_user_message. New test: test_system_prompt_requires_full_participant_names. All 1358 tests green. Coordinator verified live—full names now render correctly and bold as expected.
