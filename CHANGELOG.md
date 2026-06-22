# Changelog

Novedades de **WorldCup2026Over9000Bot**. Este archivo se actualiza automáticamente
en cada release de GitHub (ver `.github/workflows/docker-deploy.yml`).

<!-- releases -->

## [20260622.03] - 2026-06-22

- fetch + parse WC items (idPrograma=1030562, excluding 'resumen'), extract teams (Spanish->TLA) and kickoff (Madrid-local->UTC, DST-correct), 6h TTL cache, fully graceful (a flaky RTVE API never breaks a command).
- tve_channel_for() matches a fixture by kickoff (+/-20 min) + unordered TLA pair (time-only fallback only when unambiguous).
- /hoy, /siguiente and the daily AI update append a TV emoji (+ channel) to matches on TVE. Toggle with TVE_ENABLED (default on).
- kante-goal-notif-fixes.md: Four live goal-notification bugs + keyboard follow-up


## [20260622.02] - 2026-06-22

- Duplicate goal (e.g. '5-0' sent twice): both jobs read a stale announced score and re-announced. Fixed with a shared asyncio goal_lock — each job now claims the new announced score atomically inside the lock BEFORE the slow enrichment/send, so the other job sees it and produces no delta. This also fixes goals being missed in the same race (NZ-Egypt).
- Goal sent with no scorer and no 'Ver gol' button (API beat the thread and scorer enrichment was empty): the thread now back-fills the scorer onto the already-sent message (edits text + sets the clip-store scorer so the clip search runs), and re-attaches the existing 'Ver gol' keyboard so the edit cannot strip it.
- VAR 'Gol anulado' showed a wrong, too-low score from a momentary thread mis-read: the post-VAR score is clamped to announced-1 on the dropped side.


## [20260622] - 2026-06-22

- pred & actual both in top-2 (positions 1-2) -> 1.0 (order irrelevant) - exact 3rd (pred=3, actual=3) -> 1.0 - boundary between top-2 and 3rd -> 0.5 - otherwise -> 0


## [20260621] - 2026-06-21

- Update daily_update.py


## [20260619.04] - 2026-06-19

- New load_tongo_config(path) -> TongoConfig (phrases + users), mtime hot-reload, per-field graceful validation, never raises. Removed load_tongo_phrases / read_tongo_phrase_file and their caches.
- cmd_tongo loads one file; unconfigured users keep the 1/3 Sanchez + global pool behavior; FRASES remain the built-in fallback.
- data/TongoUsers.yml is now git-ignored (runtime). Added committed Spanish templates data/TongoUsers.template.yml and data/predictions.template.yml (example data only, no real participants).
- TONGO_USERS_PATH points to the merged file; compose + .env.example updated. README rewritten. Tests reworked (1452 passing).


## [20260619.03] - 2026-06-19

- sanchez_ratio (0..1): override the global 1/3 'Sanchez ens roba' probability (e.g. 0.66 for 2/3, 0.0 to disable, 1.0 to always). - phrases (inline) + phrases_file (relative path): per-user phrases, full {{...}} templating supported. - phrases_mode: append (default, merge with the global pool) or replace (use only the user's phrases; empty -> safe fallback to global pool).


## [20260619.02] - 2026-06-19

- feat(tongo): customizable templated phrases from data/TongoPhrases.txt
- Merged inbox decision into decisions.md (kante-44: daily-update fix)
- Deleted inbox file
- Added orchestration log (2026-06-19T07-35-47Z-kante.md)
- Added session log (2026-06-19T07-35-47Z-daily-update-full-names.md)


## [20260619] - 2026-06-19

- fix: the daily-summary AI prompt now requires writing each participant's full name (nombre y apellidos) exactly as it appears in the ranking, never just the first name — so bold_person_names always matches and everyone is bolded (first-name-only mentions like "Miquel"/"Cristina"/"Patri" were going unbolded)
- Archived 14 pre-2026-06-18 decisions to decisions-archive.md (102KB → 33KB decisions.md)
- Merged 2 inbox files (kante-czechia-team-alias.md, kante-endirecto-429-shared-scanner-cache.md)
- Created orchestration-log/2026-06-18T17-21-15Z-kante.md (kante-42 + kante-43 summary)
- Created log/2026-06-18T17-21-15Z-czechia-and-endirecto-429.md (session record for commit 6cfe641)


## [20260618.06] - 2026-06-18

- fix: add a Czech Republic ↔ Czechia team alias so goal clips posted as "Czech Republic ..." match the football-data "Czechia" fixture and get the "Ver gol" button
- fix: /endirecto now reuses the shared Reddit scanner (the one the goal poller uses) instead of creating a throwaway one, and finds the match thread via the reliable /new/ listing instead of the rate-limited search endpoint
- fix: cache the r/soccer thread listing (30s) and thread bodies (90s) on the scanner and degrade gracefully on HTTP 429, so /endirecto reuses the goal poller's recent fetches and shows the inline keyboard instead of falling back to a bare score line
- BELOVED_TEAMS env-configurable (default: PAN,UZB,CUW)
- Curaçao (CUW) added to beloved teams
- Pure module pattern in formatters.py
- All 1329 tests green, verified end-to-end


## [20260618.05] - 2026-06-18

- feat: add Curaçao 🇨🇼 (TLA CUW) to the teams that get a ❤️ next to their flag, alongside Panama and Uzbekistan
- feat: make the favourites configurable via a new BELOVED_TEAMS env var (comma-separated football-data TLAs, default PAN,UZB,CUW), parsed in config and applied to the flag renderer at startup
- feat: the AI daily summary now shows warmth for all three (Panamá, Uzbekistán y Curaçao)
- chore: expose BELOVED_TEAMS in both docker-compose files and document it in .env.example


## [20260618.04] - 2026-06-18

- feat: append a ❤️ to the flag of Panama 🇵🇦 and Uzbekistan 🇺🇿 in team_flag, so the love appears anywhere teams are rendered — goal notifications, /hoy, /endirecto, standings and match recaps
- feat: tell the AI daily-summary prompt to show warmth and encouragement for Panama and Uzbekistan when they come up in its prose
- chore: BELOVED_TEAMS is a small constant ({PAN, UZB}) so the favourites are easy to adjust later
- Merge kante-hoy-rollover-next-jornada.md from inbox into decisions.md (1 entry, 2026-06-18)
- Delete inbox file
- Write orchestration-log (kante-39 feature summary)
- Write session log (brief feature + test count)


## [20260618.03] - 2026-06-18

- feat: /hoy now shows the first 9am→9am football-day window (from today forward) that still has a non-finished match, so calling it at e.g. 07:00 after the night's games have ended shows the upcoming day's fixtures instead of an empty/finished list
- feat: when it rolls forward, the header reads "Ya han acabado los partidos de hoy. Estos son los próximos:" and each match shows its date; the normal same-day case is unchanged
- feat: if there are no upcoming matches in the next two weeks, fall back to today's results, or "No hay partidos programados." when there are none at all


## [20260618.02] - 2026-06-18

- fix: persist the set of matches already recapped to finished_announced.json so the "🏁 Final" dedup survives container restarts (was in-memory only)
- fix: on startup, seed as already-handled any match that is FINISHED OR whose kickoff was more than 4h ago, so a match that ended hours ago but still shows IN_PLAY in football-data (status lag) never fires a late recap when it finally flips to FINISHED
- fix: persist immediately after each recap send so a crash mid-batch can't replay it


## [20260618] - 2026-06-18

- fix: give each goal detector (Reddit match thread and football-data) its own private last-seen score while sharing a single announced score, via a new pure reconcile() function
- fix: a source that is merely lagging behind the other (e.g. football-data still 3-2 while the thread already announced 4-2) is treated as catching up, never as a disallowed goal — so no more false "Gol anulado (VAR)" spam
- fix: a disallowed goal is only announced when the SAME source that was ahead actually drops (a real VAR review), counted once even when the other source later catches up
- test: reproduce the exact production screenshot (thread 4-2 / api 3-2 loop) and assert one goal and zero disallowed; plus real-VAR, multi-goal and interleaved-lag cases


## [20260617.14] - 2026-06-17

- feat: detect goals directly from the r/soccer match thread every 25s, so notifications arrive earlier than football-data's lagging score update; the scorer comes straight from the thread (no extra AI call)
- feat: share a single in-memory live-score state between the football-data poll and the new thread poll, so whichever sees a goal first notifies and the other is deduplicated (no double messages)
- fix: download goal clips from any streamff mirror domain (streamff.pro, .gg, etc.) by routing them to the streamff CDN — previously only .link/.com worked, so streamff.pro clips never got the "Ver gol" button


## [20260617.13] - 2026-06-17

- feat: /endirecto now sends only the header and goals, with an inline keyboard offering Tarjetas, Alineación and Cambios
- feat: tapping a button edits the message in place to add that section, always rendered in a fixed order (goles → tarjetas → alineación → cambios) regardless of click order
- feat: persist a per-match snapshot of that moment to the state volume (endirecto.json) so the buttons keep working across bot restarts; entries auto-prune after 6h
- feat: extract the current lineup (starting XI with substitutions applied) from the Reddit match thread as part of the AI information extractor
- chore: register a dedicated callback handler (pattern ^ed|) separate from the goal-clip "Ver gol" callback


## [20260617.12] - 2026-06-17

- feat: enrich the /endirecto command with live match detail — current minute, goals (scorer + minute), yellow/red cards and substitutions
- feat: since football-data does not expose these on our tier, extract them from the r/soccer match thread "MATCH EVENTS" feed via an OpenAI information extractor (new ai/match_events.py)
- feat: render each live match as a readable block with ⚽ goles / 🟨 tarjetas / 🔄 cambios sections, omitting empty ones, multiple matches separated by a divider
- fix: gracefully fall back to the score-only view per match when the thread or the AI is unavailable, so the command never fails


## [20260617.11] - 2026-06-17

- fix: make the scorer match robust to r/soccer title variants — accent-fold names, ignore the trailing "goal"/"penalty" words and single-letter initials, and match on shared surname tokens (e.g. "Wissa Y. goal" now matches "Yoane Wissa")
- fix: widen the goal-minute tolerance from ±2 to ±3 to absorb added-time discrepancies between football-data and the Reddit clip title
- fix: when Reddit's JSON search is blocked, search the HTML results AND the /new/ listing merged (deduplicated) so a very recent clip that isn't in the search index yet is still found


## [20260617.10] - 2026-06-17

- fix: normalize team names with dots so "D.R. Congo" matches "Congo DR" (strip periods before alias lookup) — was breaking the clip match for that fixture
- fix: add dropr.co to the recognised goal-clip video hosts
- fix: accept any external (non-reddit, non-image) link from an already title-matched clip post as the media URL, so future clip-host rotations don't silently drop the "Ver gol" button


## [20260617.09] - 2026-06-17

- Merged all 6 inbox decisions into decisions.md (kante-25, kante-26, kante-27, kante-29, maldini-10)
- Deleted inbox files after merge
- Updated decisions.md compaction warning (date-gate can fire, entries span 3 days)
- Archived kante/history.md (58534 bytes → summarized to history-archive.md)
- Trimmed kante/history.md to lightweight project context (1263 bytes)
- Maldini history unchanged (12283 bytes, under 15360 threshold)
- Hybrid multi-image face-anchor (run 2+ uses [evolved, original])
- Azure moderation-safe framing (positive-dressing language)
- Caption newline normalization (fixes literal \n)
- No slash separators in captions (model no longer imitates \/" / \")
- Escalation emphasis (PRIMARY critical ask)
- Rich photo gitignore (personal base photo never committed)


## [20260617.08] - 2026-06-17

- feat: new daily job (11:00 Europe/Madrid) that edits a base photo with gpt-image-2 (via LiteLLM) to make the subject look progressively richer and posts it to the group
- feat: hybrid face anchoring — each day the model edits the previous image together with the original photo as a reference, so the face, skin tone and features stay consistent and don't drift over time
- feat: the prompt forces a brand-new luxury outfit, a new pose and a new opulent setting each day, and demands the result look clearly richer than the day before (occasional tasteful sunglasses or hat)
- feat: cocky first-person Spanish caption generated by the multimodal chat model from the before/after images, role-playing the person who is getting rich by rigging the group's porra
- feat: bounded plain-text memory in the state volume — rich_history.txt (luxuries/places, capped at 30) and rich_captions.txt (last 6 captions) are fed back to both the image and caption prompts so purchases, destinations and catchphrases never repeat
- fix: convert literal "\n" and stray " / " separators in captions into real line breaks
- chore: keep the personal base photo out of the public repo (gitignore data/rich/, keep .gitkeep); image destination is TELEGRAM_GROUP_ID
- chore: add OPENAI_IMAGE_MODEL / OPENAI_IMAGE_API_KEY / OPENAI_IMAGE_BASE_URL / RICH_IMAGE_HOUR settings (image key falls back to the main OpenAI key)
- Merged 3 decision inbox files into decisions.md (kante-22, kante-23, maldini-9)
- Deleted inbox files after merge
- Added manual compaction warning to decisions.md (144 KB, all same-day)
- Recorded orchestration logs for kante (caption+history) and maldini (env consolidation)
- Recorded session log for rich-image feature checkpoint


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

