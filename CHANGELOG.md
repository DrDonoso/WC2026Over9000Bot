# Changelog

Novedades de **WorldCup2026Over9000Bot**. Este archivo se actualiza automáticamente
en cada release de GitHub (ver `.github/workflows/docker-deploy.yml`).

<!-- releases -->

## [20260617.07] - 2026-06-17

- feat: add /evolucion command that renders a bump chart of each participant's porra ranking across jornadas
- feat: reconstruct historical group standings from match results grouped by football-day (09:00-09:00 window, aligned with the Mexico/USA/Canada match day) so a "jornada" is one day of matches
- feat: the latest jornada uses the exact live /actual ranking while past jornadas are reconstructed, so the rightmost point of the chart always matches the current classification
- feat: build and persist per-jornada snapshots to the state volume at startup (15s after boot) and refresh them daily at 09:05 Europe/Madrid, so the history is ready without recomputing on every command
- perf: /evolucion reads the cached snapshots from the volume and only recomputes the latest point, keeping the command fast
- chore: add matplotlib as a dependency for chart rendering (self-contained wheels, no extra system libs)
- refactor: remove the unused get_standings(date=...) parameter from the football-data client (dead code from the earlier date-based approach)


## [20260617.04] - 2026-06-17

- feat: score-based goal detection — goals are now detected from football-data score changes instead of parsing Reddit, fixing missed goals on human-narrated match threads and the 1-0 → 1-1 → 1-0 flip-flop.
- feat: OpenAI scorer extraction — the scorer and minute are pulled by an LLM information-extractor that understands any r/soccer thread format (ESPN-structured or narrated).
- feat: VAR notices — a disallowed goal (score decrease) now posts a "Gol anulado".
- feat: deferred goal clips — the goal is announced instantly without a button; a background job polls for the video, downloads it to a persistent volume, then edits the message to add the "Ver gol" button. Survives bot restarts.
- feat: richer match-finish — always posts the final result, plus the ESPN stats card when available, plus a /porra recap by a random commentator (now even when nothing moved); sections separated by ---.
- feat: /estadisticas — a persistent per-user counter of who taps "Ver gol".


## [20260617] - 2026-06-17

- auto-updating CHANGELOG.md from GitHub releases

