# Changelog

Novedades de **WorldCup2026Over9000Bot**. Este archivo se actualiza automáticamente
en cada release de GitHub (ver `.github/workflows/docker-deploy.yml`).

<!-- releases -->

## [20260710.03] - 2026-07-10

- feat(picante): per-user auto-learned profiles (off by default)


## [20260710.02] - 2026-07-10

- chore(squad): commit agent history and drop stale inbox entry
- refactor(picante): use recent chat context only when related to the last message


## [20260710] - 2026-07-10

- feat(rich-image): Micky birthday special on July 10 (3-image composition)


## [20260708.02] - 2026-07-08

- fix(porra): defer knockout Final recap until a decisive winner is set


## [20260708] - 2026-07-08

- feat(rich): birthday mode on July 8 (turns 42 in 2026)
- Merged buffon-var-two-source-regression.md and pirlo-goal-flood-review.md into decisions entry (2026-07-07 SHIPPED)
- Deleted merged inbox files
- Added 3 orchestration logs (kante, buffon, pirlo)
- Added session log with root cause, solution, tests, review, deployment status
- Updated agent histories (kante, buffon, pirlo)


## [20260707] - 2026-07-07

- fix(goals): prevent VAR-disallowed goal flood from cross-source seen desync


## [20260706.04] - 2026-07-06

- feat(admin): add hidden /evilSanchez to fire the daily rich image on demand


## [20260706.03] - 2026-07-06

- feat(help): add /help command with command list + scoring explanation


## [20260706.02] - 2026-07-06

- feat(scoring): escalate knockout points (R16=2, QF=3, SF=5, Final=8)
- Scribe: merge clip-fallback + final-seed decisions, update histories


## [20260706] - 2026-07-06

- fix(clip): always use HTML fallback when JSON search yields no matching clip
- All 17 inbox files merged successfully
- No entries suppressed (all ≥2026-06-30, no >7-day entries)
- Maldini: mem-limit 512m (pending owner confirmation)
- Cannavaro: FINAL provisional+memory, streamff CDN resilience (shipped)
- Kanté: /elecciones MVP (approved-w-followups); keyboard+FINAL (rejected, reworked)
- Buffon: revive test determinism (shipped)
- Nesta: FINAL seed fix (approved), elecciones2 revision (approved-w-followups)
- Pirlo: 7 reviews (3 rejections with fix-forward, 3 approvals-w-followups, 1 design)


## [20260705] - 2026-07-05

- cache: include scheduled tie identity in version + never cache transient 'no disponible'/API-error/fallback artifacts (BLOCKER 1)
- split: guarantee every emitted part <=4096 incl header/prefix, hard-split a single overlong line at char boundary (BLOCKER 2)
- flags: switch twemoji base to gh path (npm 404s); add ENG/SCO/WAL tag-sequence flags, NIR falls back to text
- groups image API failure -> text fallback (no blank image)
- hourglass delete failure -> neutral placeholder edit
- 14 new/updated tests; full suite 2346 passed


## [20260704.11] - 2026-07-04

- tests/test_chat_edge_cases.py: add _frozen_datetime_active_cls() helper and an autouse fixture on TestReviveInactiveJob that wraps every test in the patch context.
- tests/test_revive_schedule.py: add the same helper and apply it explicitly to test_success_path_reschedules.
- docs(squad): kante hourglass UX learnings + decision note


## [20260704.10] - 2026-07-04

- Replace _serve_elecciones with _serve_after_placeholder(context, chat_id, placeholder_id, artifact): delete-then-send on success, edit- to-error on failure.
- Rewrite cmd_elecciones_callback: use query.edit_message_text('⏳ Generando…', reply_markup=None) as step 1; wrap generation in try/except so artifact=None on any exception; delegate to _serve_after_placeholder.
- Add delete_message + edit_message_text mocks to _make_context().
- Add edit_message_text mock to TestCmdEleccionesCallback._make_query().
- Update test_removes_keyboard, test_sends_text_result_for_grupos, test_cache_hit_serves_without_regeneration, test_cache_invalidated_on_mtime_change, test_grupos_image_mode_* to assert delete_message + send_* (not edit_message_reply_markup).
- Add test_generation_failure_edits_placeholder_to_error: assert no delete/send, bot.edit_message_text called with error text.


## [20260704.09] - 2026-07-04

- feat(elecciones): circular flag images in knockout & groups images (replace TLA text)


## [20260704.08] - 2026-07-04

- feat(elecciones): groups 2x2 image + tile-cache eviction + defensive text split


## [20260704.07] - 2026-07-04

- feat(elecciones): /elecciones command — phase keyboard + per-user text (knockout & groups) + knockout image + CHOICES_TYPE + lazy cache


## [20260704.06] - 2026-07-04

- fix(goals): startup seed must not consume final dedup for non-FINISHED matches


## [20260704.05] - 2026-07-04

- PRIMARY: _streamff_cdn_url() builds https://cdn.<matched-domain>/<id>.mp4 from the matched URL (streamff.pro -> cdn.streamff.pro). No .one/.pro/.com literals remain, so a future streamff domain rotation needs no code edit. This directly fixes the live failure where a .pro clip was downloaded from the stale hardcoded cdn.streamff.one -> ConnectionReset.
- SECONDARY: when the derived CDN host is dead, the matched page is scraped for the real <source> src.
- _download_file retries transient connection resets 2x with backoff; streamff never routes to yt-dlp (unsupported). Removed the hardcoded STREAMFF_CDN_HOSTS list, STREAMFF_CDN_BASE and _streamff_cdn_candidates.


## [20260704.04] - 2026-07-04

- Primary: _resolve_streamff_source() fetches the actual matched /v/{id} page and extracts the real .mp4 (STREAMFF_VIDEO_RE keyed on source src/file/src/ videoUrl/url; ANY_MP4_RE last resort). Domain-independent - survives future domain rotations instead of chasing them.
- Fallback: direct-CDN guess derived from the SAME matched domain first (cdn.streamff.pro), then a known host list.
- _download_file retries transient connection resets twice with backoff.
- streamff no longer falls through to yt-dlp (unsupported); streamin/streamain keep their yt-dlp fallback. Order: page-resolved -> matched CDN -> known CDNs.


## [20260704.03] - 2026-07-04

- perf(mem): reuse single football-data client, evict reddit body cache, close AI httpx clients
- fix(goals): provisional late-final that preserves official recap + bound keyboard retries


## [20260704] - 2026-07-04

- clip_store.py: add keyboard_attached=False to the entry schema in add_entry.
- __main__.py poll_goal_clips_job: set entry['keyboard_attached']=True after a successful edit_message_reply_markup.  Collect pending_retry (ready + not keyboard_attached) before the early-return guard so the retry loop runs even when there is no new clip-searching work.  On every tick, retry edit_message_reply_markup for all unattached ready entries until success.
- __main__.py poll_finished_matches_job: compute now_utc in the main loop and also collect stale_live_ids — matches where _match_is_over(m, now_utc) is True (kickoff >4h ago, MATCH_OVER_AGE) AND m.status in ('IN_PLAY', 'PAUSED').  Union with finished_ids before the already-announced filter. This caps worst-case delay at MATCH_OVER_AGE (4h from kickoff) regardless of API lag, without touching the dedup set logic or the seed pass.
- tests/test_poll_goal_clips_job.py TestKeyboardRetry (8 new tests): keyboard_attached tracking, retry loop fires for unattached entries, skips already-attached and timeout entries, multiple entries in one tick, failed retry keeps keyboard_attached False for next tick.
- tests/test_poll_finished_job.py TestWallClockFallback (6 new tests): IN_PLAY >4h announced, PAUSED >4h announced, IN_PLAY <4h NOT announced, TIMED >4h NOT announced (only live statuses), already-announced not re-fired, first-run seed still seeds stale IN_PLAY without sending.
- Merged 2 inbox decision files (kante + pirlo VAR reviews) → decisions.md
- Deleted processed inbox files
- Created orchestration logs for kante, buffon, pirlo (ISO 8601 UTC timestamps)
- Created session log for VAR final-correction deployment
- Updated pirlo history with VAR review summary
- Verified all history files < 15360-byte threshold
- No archive trigger (decisions.md = 12.7 KB < 51200-byte gate)
- Inbox processed: 2 files → 0 remaining


## [20260703.02] - 2026-07-03

- fix(goals): post-final VAR correction for wrong final score


## [20260703] - 2026-07-03

- fix(tve): 'La 1' label for knockout & midnight matches
- Belgium 3-2 Senegal penalty: timeout (18.75 → 30 min search window)
- USA 1-0 Bosnia: Reddit search miss ("United States" → "usa" alias) + timeout
- _MAX_CLIP_ATTEMPTS 25 → 40 in __main__.py
- Added _TEAM_SEARCH_SHORT + _search_term() in clip_finder.py
- 13 new tests (2134 total), all pass
- No regression: post-fetch matching unchanged
- .squad/log/2026-07-02T08-42-51Z-vergol-button-fix.md
- .squad/orchestration-log/2026-07-02T08-42-51Z-{kante,pirlo}.md
- .squad/decisions.md (merged entry prepended)
- .squad/agents/pirlo/history.md (added 2026-07-02 session)
- .squad/agents/pirlo/history-archive.md (archived old entries)


## [20260702] - 2026-07-02

- fix(clip): 'Ver gol' button - widen window + normalize team search
- .squad/decisions.md: merged inbox files, deleted inbox entries
- .squad/orchestration-log/: 3 agent logs (kante, buffon, pirlo)
- .squad/log/: session summary
- .squad/agents/pirlo/history.md: added session note


## [20260701.06] - 2026-07-01

- fix(goals): seed live matches by scheduled kickoff (real-time goals + /endirecto)


## [20260701.05] - 2026-07-01

- feat(rich-image): theme daily image by yesterday's winners


## [20260701.04] - 2026-07-01

- kante-podium-drawn-base.md: Drawn 3-block podium layout (gold/silver/bronze, tie-aware, crown asset)
- pirlo-podium-drawn-review.md: Lead review (APPROVED)
- decisions.md: Prepended merged podium decision
- agents/pirlo/history.md: Added note on podium-drawn-base review
- Deleted inbox files
- feat(porra): draw podium base under photos, crown worn on head


## [20260701.03] - 2026-07-01

- feat(porra): use bundled crown image for podium


## [20260701.02] - 2026-07-01

- feat(porra): podium image for top-3 rankings with crowns


## [20260701] - 2026-07-01

- fix(porra): standard competition ranking for tied points


## [20260630.06] - 2026-06-30

- refine(chat): picante replies to triggering message, mirrors its language


## [20260630.05] - 2026-06-30

- Merge 2 inbox decisions into decisions.md (Kanté + Pirlo ChatState eager persistence)
- Delete inbox files (2 files)
- Summarize Kanté history (25857 → 1634 bytes, archive pre-2026-06-27 sessions)
- Update Pirlo history (add ChatState review note)
- feat(chat): persist chat_state.json eagerly (startup + per-message)


## [20260630.04] - 2026-06-30

- feat(chat): revive quiet hours + randomized self-rescheduling interval
- Picante: probabilistic spicy AI reply to group messages (~1-in-5). Gates: probability, cooldown (5 min), daily cap (30), min buffer (5 msgs). Enable: CHAT_PICANTE_ENABLED=1 (requires OPENAI_* vars).
- Revive: periodic @mention of inactive porra participants. Cadence: every 4 h. Inactivity threshold: 3 days. Per-user cooldown: 2 days. Candidate set: porra participants only (matched by predictions YAML username key). Enable: CHAT_REVIVE_ENABLED=1 (requires OPENAI_* vars).
- DECISIONS ARCHIVE: decisions.md 78575 → 86224 bytes; no entries >7 days old (2026-06-26, 2026-06-27 entries preserved)
- DECISION INBOX: merged 4 files (pirlo-llm-chat-features.md, kante-chat-features-impl.md, pirlo-chat-features-review.md, maldini-chat-features-ops.md) → consolidated entry in decisions.md; deleted inbox files
- CROSS-AGENT: appended chat-features team update to kante/maldini/buffon/pirlo history.md noting shipped features + privacy-mode pre-step
- HISTORY SUMMARIZATION: Kante history.md >= 15360 bytes; Maldini history.md >= 15360 bytes (both reviewed for archival decision)
- Orchestration logs: 2026-06-30T09-16-38Z-{pirlo,kante,maldini,buffon}.md (agent deliverables)
- Session log: 2026-06-30T09-16-38Z-chat-features.md (brief summary)
- ✅ Pirlo: Design spec + lead review gate (APPROVED)
- ✅ Kanté: Implementation of src/worldcup_bot/chat/ package (5 modules), config wiring
- ✅ Buffon: 107 edge-case tests, 1875 total tests passing, 0 bugs found
- ✅ Maldini: README privacy-mode section, 12 env vars wired across all surfaces


## [20260630.03] - 2026-06-30

- docker-deploy.yml: add BuildKit cache (type=gha + inline registry cache on :latest) and provenance:false, so unchanged layers keep stable digests across runners and 'docker compose pull' fetches only the changed app layer.
- Dockerfile: create the /app/data and /app/state dirs BEFORE copying source, so that layer stays cached on code changes.


## [20260630.02] - 2026-06-30

- render_message: append '(penaltis X-Y)' for shootout matches (home_score/ away_score are already the penalty-stripped on-pitch score).
- build_ai_user_message: include the penalty result + who advanced so the AI commentary is correct.


## [20260630] - 2026-06-30

- Match model: parse duration + penalties; home_score/away_score are now the on-pitch score (penalties stripped); add in_penalty_shootout.
- formatters.format_final_result: penalty-aware Final card — on-pitch score + '🥅 Penaltis: X-Y — pasa <winner>', winner taken from score.winner.
- poll_goals_job + poll_thread_goals_job: skip matches in a shootout, so kicks are never announced as goals.
- poll_finished_matches_job: match_result_is_final defers the Final until the shootout is settled (penalties present + decisive winner), avoiding the premature/transient card.


## [20260629.04] - 2026-06-29

- formatters: render_endirecto always appends the ⚽ Goles button; add goal_button_label + build_endirecto_goals_keyboard.
- endirecto_store: set_reddit_goals merges/dedups/sorts parsed goals into the snapshot.
- handlers: cmd_endirecto_callback handles code 'g' (fetch + show buttons); new cmd_endirecto_goal_callback posts the goal and clears the keyboard.
- __main__: register the edgol callback handler.


## [20260629.03] - 2026-06-29

- get_stage_results(''ROUND_OF_32'') matched no finished match, so the already-played Canada result was never scored in /listaaciertosactual, /listaaciertos and /general.
- live/finished knockout matches (stage ''LAST_32'') were not recognised as knockout, so the ⚔️ face-off never appeared in /endirecto, the kickoff notice or the finish recap.


## [20260629.02] - 2026-06-29

- porra/camps.py: compute_match_camps splits participants by their round_of_X pick (knockout only; group-stage matches are not split).
- formatters.format_match_camps: style-B force bar (▓░) + names per team; HTML for kickoff/finish, plain text for /endirecto; empty string when no one backs either team so callers skip it.
- __main__ poll_kickoff_job + poll_finished_matches_job and handlers cmd_en_directo append the block (best-effort, never breaks the message).


## [20260629] - 2026-06-29

- score_knockout: add decided_teams param; not-yet-played picks are 'pending' (⏳) instead of 'fallo' (❌). Backward-compatible when None.
- client: add get_knockout_decided() (finished-match participants).
- engine.compute_user_detail: drop finished_stages gating; score KO from all finished matches in both modes via _build_decided_teams.
- formatters: render 'pending' as ⏳ in /listaaciertos[actual].
- Merge 5 inbox decision documents into decisions.md
- Add orchestration logs for all 5 agents (kante-4, pirlo-4, kante-5, pirlo-5, buffon-4)
- Add session log for catch-up recovery + FINISHED eviction fix
- Update Pirlo history with design and review gate roles


## [20260627.02] - 2026-06-27

- Seed live_scores at 0-0 when poll_kickoff_job fires, so goals are detected as proper 0-0->0-1 transitions from the first minute
- When a match is seeded late, recover the real per-goal scorer and clip from the Reddit thread and send proper "Ver gol" notifications, using the neutral "Me perdi N goles" message only as a fallback
- Two-tick FINISHED eviction stops goal-polling a match after full time, fixing the post-FT goal/disallowed oscillation (e.g. Uruguay 0-1 Spain), while preserving a real in-match VAR disallowed
- Persist live_scores immediately after each thread goal claim
- kante-3: Implementation of _match_is_over wall-clock guard (+10 tests)
- pirlo-3: Review gate APPROVED
- buffon-3: QA gate PASS WITH ADDED TESTS (+5)


## [20260627] - 2026-06-27

- Add _match_is_over (kickoff >4h ago) and exclude over-matches from both goal-polling jobs even when football-data status is stuck at IN_PLAY
- Evict and persist-prune over-matches from live_scores and per-source seen state so a stuck entry self-heals on the next tick
- Fixes the endless goal -> disallowed loop caused by an oscillating Reddit thread read on a match that ended hours ago (e.g. Egypt-Iran)


## [20260626.02] - 2026-06-26

- Stop poisoning the broadcast cache for 6h when the RTVE fetch fails; empty results now expire after 30 min so the next call retries
- Add a same-day exact-TLA-pair fallback in tve_channel_for so a match is still labelled when RTVE lists a programme-block time outside the +/-20-min kickoff window
- Merged 3 decision inbox files (kante-tve-*, pirlo-tve-*, buffon-tve-*) into decisions.md
- Updated agent histories (kante, pirlo, buffon) with session outcomes
- Kante: 1618→1627 (+9 tests); both gates passed
- Buffon: added +2 edge-case tests (1627→1629 final)
- Pirlo: approved; recommended moving DAILY_UPDATE_HOUR to 11:00
- Code changes remain UNCOMMITTED per owner decision


## [20260626] - 2026-06-26

- Compute the 8 best third-placed teams from group standings using FIFA tiebreakers (points -> goal difference -> goals for)
- Strict policy: a third that does not qualify scores 0 (no exact-3rd or boundary credit)
- Extend Standing with goal_difference/goals_for and thread the qualifying-thirds set through every scoring path (/clasificacion, /hoy, /ayer, /evolucion, /recalcular)
- Emit a single neutral catch-up message when goals are missed (API status-flip delay or restart) instead of fabricating per-goal scores
- Fix the race that stripped the "Ver gol" inline keyboard; the backfill now never clears an existing keyboard
- Delete the clip file from the volume after a successful send (the Telegram file_id is cached so re-taps still work)
- Merged 3 inbox files (kante, pirlo, buffon) into decisions.md
- Created orchestration logs for kante-1, pirlo-1, buffon-1
- Created session log for best-thirds scoring outcome
- Updated pirlo and buffon agent history files with session note
- Feature: WC2026 third-place qualification scoring (strict policy: non-qualifying 3rd = 0.0)
- Test delta: 1571 → 1618 (+47 tests, all passing)
- Both gates passed (Pirlo review, Buffon QA); source changes uncommitted for owner review
- Date: 2026-06-26
- Team: Kanté (fixes), Maldini (infra investigation), Pirlo (design review), Buffon (QA gate)
- Outcome: 4 bugs fixed (A1/A2: missed goals, B1/B2: missing keyboards, D: delete-after-send)
- Test count: 1571 passing (+19 new tests)
- Status: Ready for owner review and deployment
- .squad/decisions.md (merged 4 inbox entries from today's team)
- .squad/orchestration-log/2026-06-26T09-54-02Z-*.md (4 agent logs)
- .squad/log/2026-06-26T09-54-02Z-goal-notification-bugfix.md (session summary)
- Merged .squad/decisions/inbox/kante-kickoff-notice.md into decisions.md (no older entries to archive)
- Summarized kante's history.md (18.9KB → 2.8KB); archived detailed sessions to history-archive.md
- Updated test count: 1552 (kickoff notifications feature complete)


## [20260622.06] - 2026-06-22

- feat(kickoff): announce when a match starts at its scheduled kickoff


## [20260622.05] - 2026-06-22

- refactor(tongo): require TongoUsers.yml — fail (no fallback) if it can't load
- Merge decisions/inbox (kante-dailyupdate-tve-and-tongocheck) into decisions.md
- Condensed kante history.md (15566→15221 bytes, <15360 threshold)
- Appended phases 26–31 to history-archive.md (2026-06-22 TVE + tongocheck details)
- No entries >7 days old to archive


## [20260622.04] - 2026-06-22

- Daily update (/updatediario): the 📺 + channel now appears on the match line right after the kickoff (e.g. 'Inglaterra vs Ghana — 22:00 📺 La 1'), exactly like /hoy — rendered deterministically by render_message. The AI no longer mentions TVE (removed from _SYSTEM and build_ai_user_message), so it is no longer redundant with the line marker.
- New hidden admin command /tongocheck: validates data/TongoUsers.yml and replies '✅ N frases, M usuarios' or '❌ Error de YAML: línea X' — so a typo (e.g. a stray '.' after a closing quote) that silently drops all phrases is diagnosable from Telegram in seconds. Backed by check_tongo_config() in data/tongo.py.
- kante-tve-broadcasts.md (TVE broadcast markers via RTVE API)
- maldini-tve-enabled-env.md (TVE_ENABLED env toggle)
- rtveapi (research agent, RTVE API verification)
- kante (TVE module + 54 tests, 1491→1545)
- maldini (docker-compose.yml/local + .env.example)
- coordinator (live smoke test, TongoUsers.yml YAML-typo diagnosis)


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

