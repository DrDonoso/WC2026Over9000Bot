# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2618 tests ✅

## Current Session: 2026-07-13 — /perfil Inline Keyboard

**Feature:** /perfil (no-args) now shows an InlineKeyboardMarkup with profile buttons instead of plain text list.

**Key changes:**
- Extracted _format_profile() helper for shared rendering
- Added InlineKeyboardMarkup with buttons (2 per row, alphabetically sorted)
- New cb_perfil_select() callback removes keyboard via dit_message_text without eply_markup
- Backward compatible: /perfil @usuario unchanged

**Files:** handlers.py, __main__.py  
**Test result:** 2618 passed, 0 regressions

---

## Prior Sessions

See .squad/agents/kante/history-archive.md for detailed Micky Birthday Special, Picante profile system, and related entries (2026-07-10 onwards).
