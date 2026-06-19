# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot  
**Stack:** Python, python-telegram-bot, football-data.org, Reddit scanner, LLM  
**Test count:** 1463 (as of 2026-06-19, per-user /tongo feature)

## Current Session: 2026-06-19 — Per-User /tongo Config

**Feature:** DrDonoso wanted `/tongo` behavior to vary per user (custom sanchez_ratio, custom phrase pool).

**Delivered:**
- `data/TongoUsers.yml` — YAML config file (committed, empty/commented by default, loads to `{}` = zero behavior change until opt-in)
- `TongoUserConfig` dataclass + `load_tongo_users(mtime cache)` in `tongo.py`
- `read_tongo_phrase_file(path-keyed mtime cache)` to support per-user phrase files
- `choose_tongo_response(pure, injectable rng)` extracted from handler
- `cmd_tongo` rewritten to compose effective_phrases + sanchez_ratio, then delegate selection
- 55 new tests; all existing tests green (1408 → 1463)

**Key design decisions:**
- Committed (not git-ignored) to version-control user configs
- Backward compatible: unconfigured users get exact original behavior (1/3 SANCHEZ, global pool)
- Effective phrases: per-user + global (append mode, default), or per-user only (replace mode, with fallback to global if empty)
- Path-keyed cache dict avoids thrash when alternating per-user file paths
- `rng=random` kwarg pattern lets existing handler tests (patching `worldcup_bot.bot.handlers.random`) control behavior without changes

**E2E verified:** Coordinator ran real Telegram tests (sanchez_ratio 1.0, 0.0, phrases_mode=replace, default user) — all 4 cases passed. Committed to origin/main (7ffaeb9).

## Past Sessions Summary

**Archived to history-archive.md:** Phases 1–29 (Goal detection, live-match infrastructure, rich images, LLM scoring, `/endirecto` redesign, Czechia alias fix, Reddit 429 fix, /tongo templated phrases). 1463 tests total. All design constraints preserved (module decoupling, shared TTLCache, injectable test patterns).

## Learnings

### 2026-06-19 — Merged single-YAML /tongo schema

**Schema change:** `data/TongoPhrases.txt` (plain-text global phrases) + `data/TongoUsers.yml`
(flat username → config mapping) merged into ONE YAML `data/TongoUsers.yml` with:

```yaml
phrases:                  # global pool (replaces TongoPhrases.txt)
  - "Frase {{first_name}}"
users:                    # per-user overrides (keyed by @username lowercase)
  algun_usuario:
    sanchez_ratio: 0.66   # optional, 0..1 (absent = 1/3 global)
    phrases_mode: append  # "append" (default) or "replace"
    phrases:              # optional inline phrases
      - "{{first_name}}, ..."
```

**Removed from `tongo.py`:**
- `load_tongo_phrases` + txt-based hot-reload cache (`_cached_path`, `_cached_mtime`, `_cached_data`)
- `read_tongo_phrase_file` + path-keyed cache (`_phrase_file_cache`)
- `phrases_file` field from `TongoUserConfig`
- `load_tongo_users` (merged into the new loader)

**Added to `tongo.py`:**
- `TongoConfig` dataclass: `phrases: list[str]`, `users: dict[str, TongoUserConfig]`
- `load_tongo_config(path)`: single-file YAML loader with mtime hot-reload, mirrors
  `porra/predictions.py` cache pattern. Graceful validation (never raises, logs warnings).

**Removed from `config.py`:** `tongo_phrases_path` field + `TONGO_PHRASES_PATH` env var.
`tongo_users_path` / `TONGO_USERS_PATH` now points to the merged file.

**Data file layout:**
- `data/TongoUsers.template.yml` — committed template (Spanish comments, 16 default phrases,
  2 commented fake user examples)
- `data/predictions.template.yml` — committed template for predictions.yml (fake data)
- `data/TongoUsers.yml` — git-ignored runtime file (migrated 22 phrases from TongoPhrases.txt,
  12 participant keys as commented blocks)

**Test count:** 1463 → 1452 (removed txt-loader and file-reader tests; replaced with 26
`TestLoadTongoConfig` tests covering merged schema validation).

