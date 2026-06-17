# Changelog

Novedades de **WorldCup2026Over9000Bot**. Este archivo se actualiza automáticamente
en cada release de GitHub (ver `.github/workflows/docker-deploy.yml`).

<!-- releases -->

## [20260617.05] - 2026-06-17




## [20260617.04] - 2026-06-17

- feat: score-based goal detection — goals are now detected from football-data score changes instead of parsing Reddit, fixing missed goals on human-narrated match threads and the 1-0 → 1-1 → 1-0 flip-flop.
- feat: OpenAI scorer extraction — the scorer and minute are pulled by an LLM information-extractor that understands any r/soccer thread format (ESPN-structured or narrated).
- feat: VAR notices — a disallowed goal (score decrease) now posts a "Gol anulado".
- feat: deferred goal clips — the goal is announced instantly without a button; a background job polls for the video, downloads it to a persistent volume, then edits the message to add the "Ver gol" button. Survives bot restarts.
- feat: richer match-finish — always posts the final result, plus the ESPN stats card when available, plus a /porra recap by a random commentator (now even when nothing moved); sections separated by ---.
- feat: /estadisticas — a persistent per-user counter of who taps "Ver gol".


## [20260617] - 2026-06-17

- auto-updating CHANGELOG.md from GitHub releases

