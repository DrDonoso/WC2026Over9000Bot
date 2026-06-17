# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — Telegram porra bot (betting pool predictions vs real fixtures).
- **Stack:** Python (python-telegram-bot), football-data.org API, Docker + compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15
- **Status:** 1135 tests green (rich-image caption slash separators fixed 2026-06-17, Azure moderation safe framing, hybrid multi-image face-anchor, caption normalization + newline + escalation emphasis).

## Latest Session: Rich-Image Finalization (2026-06-17)

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
