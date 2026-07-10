# Kanté — Backend Developer

**Project:** WorldCup2026Over9000TelegramBot | **Stack:** Python, PTB, football-data.org, Reddit scanner, LLM | **Current:** 2417 tests ✅

## Current Session: 2026-07-10 — Micky Birthday Special

**Feature:** On July 10 each year, un_rich_iteration enters Micky-birthday mode — generates a 3-image special scene with Micky as protagonist and the rich character alongside him, then sends it WITHOUT touching the evolution chain.

**New constants/helpers** (ich_image.py):
- MICKY_BIRTHDAY_MONTH=7, MICKY_BIRTHDAY_DAY=10, MICKY_BIRTH_YEAR=1984 (age 42 in 2026)
- MICKY_IMAGE = "micky.jpg", MICKY_BIRTHDAY_CLAUSE (age-formatted birthday description)
- is_micky_birthday(now), micky_birthday_age(now) — pure helpers mirroring the rich birthday pair
- ind_micky_image(data_dir) — mirrors ind_original_image; globs ich/micky.*; raises FileNotFoundError if absent

**dit_rich_image generalisation:**
- New param xtra_paths: list[str] | None = None
- ALL file handles now use contextlib.ExitStack (replaces old try/finally)
- Existing 2-image and 1-image paths UNCHANGED when xtra_paths=None

**uild_rich_prompt and generate_rich_caption:**
- Both gained micky_birthday: bool = False parameter
- When True: MICKY_BIRTHDAY_CLAUSE.format(age=age) appended + mandatory Micky felicitation in caption

**un_rich_iteration — evolution-chain isolation:**
- Computes micky_birthday = is_micky_birthday(now), micky_age = micky_birthday_age(now)
- Graceful fallback: FileNotFoundError on ind_micky_image → WARNING + reset micky_birthday=False
- On Micky birthday: writes to ich_micky_birthday.png in state_dir; skips save_level, ppend_history, ppend_caption → evolution chain stays clean

**Tests:** All 251 existing tests green after changes; Buffon added 30 new tests for July-10 coverage.

**Decision note:** .squad/decisions/inbox/kante-micky-birthday.md (6 design decisions)

---

## Learnings

<!-- 2026-07-10: Applied Pirlo's 8 minors (M1–M8): load_since uses strict >, M2 single store_text guard, M3/M4 order-preserving dedupe with MOTES_CAP=8/TEMAS_CAP=10 keep-most-recent, M5 max_tokens=200*N, M6 log delta not total, M7 settings.state_dir, M8 no inline imports. Suite: 2561 pass. -->

### 2026-07-10 — Picante per-user profile design options & cost model

**Context:** Design-only task (no code written). User wants personalized picante replies using per-user profiles with: rasgos, equipo, motes, temas, tono, piques_recientes. scope=include_others (inject author profile + other recent users, cap 3–5).

**Architecture constraints to remember:**
- `RingBuffer` is RAM-only (no disk, resets on restart) — auto-learning needs a new on-disk message accumulator per user. This deliberately breaks the current ChatState philosophy ("no text on disk"). Proposed mitigation: 7-day rolling window with auto-rotation.
- `ChatState` (state.py) only stores counters/metadata. Per-user profiles go in a NEW file: `state_dir/picante_profiles.json`.
- Natural model: `TongoUsers.yml` pattern (tongo.py) for MANUAL profiles — hot-reload YAML keyed by username, graceful degradation. Reuse/mirror this for `PicanteProfiles.yml`.
- `build_picante_user_message` (picante.py:79-114) is the injection point — add a PERFIL block above CONTEXTO RECIENTE.

**Profile data model (per user):**
```json
{
  "username": "pepe",
  "rasgos": "texto libre",
  "equipo": "España / Barça",
  "motes": ["el Profeta"],
  "temas": ["F1", "IA"],
  "tono": "banter duro con predicciones fallidas",
  "piques_recientes": ["2026-07-08: Predijo 4-0..."],
  "pinned_fields": ["tono", "equipo"],
  "updated_at": "2026-07-10T08:00:00"
}
```
`pinned_fields`: manually-set fields the auto-updater NEVER overwrites.

**Three update strategies:**
- (a) Incremental per-message: fresh but prohibitively expensive (~13.5M tokens/month for 20 users)
- (b) Batch daily (RECOMMENDED): 1 AI call/user/day at off-peak hours; ~1.5k input + 350 output tokens per user; predictable, no picante latency impact
- (c) On-demand at picante fire: doubles every picante call, +300–500ms latency, ~2.5M tokens/month extra

**Token estimates (approximate, 30-message buffer, system ~350 tokens):**
- Picante baseline (no profiles): ~850 input + 150 output tokens/call
- With profiles injected (scope=include_others, 5 users × ~300 tokens): ~2.350 input tokens/call (+1.500 extra)
- Batch update per user/day: ~1.500 input + 350 output tokens

**Monthly totals (strategy b, 30 disparos/day, 10 active users):**
- Picante with profiles: ~2.1M input + 135k output tokens
- Batch updates (10 users): ~450k input + 105k output tokens
- TOTAL: ~2.55M input + 240k output tokens

**Cost under two assumptions (batch diario, 10 usuarios):**
- GPT-4o class (~$2.50/1M in, ~$10/1M out): ~$8.50/month
- GPT-4o mini class (~$0.15/1M in, ~$0.60/1M out): ~$0.52/month
- Local model (Ollama/vLLM): ~€0 marginal

**Scaling formula:** `€/mes = [(N×1500 + 30×30×2220)/1M]×P_in + [(N×350 + 30×30×150)/1M]×P_out`
where N = active users, P_in/P_out = real model price per 1M tokens.

**Recommended approach:**
1. FASE 1 — Manual YAML (€0, ~1h admin work): immediate high-quality profiles
2. FASE 2 — Hybrid (manual base + optional daily auto-updater): pinned_fields protected
3. FASE 3 — piques_recientes: persist each picante reply with target username; inject last 3–5 per user

**piques_recientes note:** Requires maybe_reply to save each reply + target username to profiles JSON. Small storage, but non-trivial injection logic and extra prompt tokens.

---

### 2026-07-10 — Picante prompt recalibration (conditional context usage)

**File:** `src/worldcup_bot/chat/picante.py:23-38` (`_SYSTEM`), `picante.py:104-108` (inline instruction in `build_picante_user_message`)

**What changed:**
- `_SYSTEM` REGLA DE CONTEXTO: removed "EXCLUSIVAMENTE" from MISIÓN, removed "solo de apoyo" / "IGNÓRALOS por completo" framing. Replaced with a **balanced conditional**: if CONTEXTO RECIENTE is clearly related (same topic / ongoing thread) → *tenlo en cuenta y aprovéchalo* (explicitly active); if not related → *ignóralo por completo*. The "use-it-when-related" branch is now a positive instruction, not a barely-permitted exception.
- `build_picante_user_message` inline label: "CONTEXTO RECIENTE — si está claramente relacionado con el ÚLTIMO MENSAJE, tenlo en cuenta y aprovéchalo; si no lo está, ignóralo por completo" (was "úsalo SOLO si está claramente relacionado... si no, ignóralo").

**Why:** The old absolute wording ("EXCLUSIVAMENTE", "solo de apoyo", "IGNÓRALOS por completo") biased the model toward always ignoring context, even when the recent conversation was clearly on the same topic. The plumbing was already correct — listener.py appends every valid group message to the RingBuffer *before* calling `maybe_reply`, and `build_picante_user_message` puts all prior messages (up to `chat_buffer_size`) into the CONTEXTO RECIENTE block. The fix was prompt-only.

**Tests:** 156 tests green after change (test_chat.py + test_chat_edge_cases.py). No test assertions on the specific old wording substrings; no Buffon updates required from this change.

---

### 2026-07-10 — Picante per-user auto-learned profiles (IMPLEMENTED)

**Feature:** Per-user profiles for picante personalisation — with 3 user-approved refinements vs Pirlo's spec.

**Files created:**
- `src/worldcup_bot/chat/timeline_store.py` — Single JSONL chronological timeline of ALL group messages (Refinement 3). Functions: `append_message(state_dir, username, text, ts, *, store_text, window_days)`, `load_since(state_dir, since_ts) -> list[dict]`, `load_last_run(state_dir) -> datetime|None`, `save_last_run(state_dir, ts)`, `_trim_timeline(path, *, window_days)`. Path: `{state_dir}/picante_timeline.jsonl`. Injectable `_now` clock for tests.
- `src/worldcup_bot/chat/profiles.py` — `UserProfile` dataclass + `load_profiles(path)->dict` (never raises), `save_profiles(path, profiles)` (atomic), `get_profile(profiles, username)->UserProfile|None`. Path: `{state_dir}/picante_profiles.json`.
- `src/worldcup_bot/chat/profile_updater.py` — `async update_profiles_from_conversation(timeline_messages, current_profiles, ai, *, piques_cap) -> dict[str, UserProfile]`. Single AI call feeding the full attributed conversation (Refinement 3). Incremental: called only with messages since last_run (Refinement 1). Empty timeline → no AI call. AIError/JSON error → WARNING + return unchanged. Respects pinned_fields. motes/temas are accumulative (union). Injectable `_now` for tests.

**Files modified:**
- `src/worldcup_bot/config.py` — Added 7 new Settings fields + `picante_profiles_enabled(settings)->bool` helper. `load_settings()` updated with all env vars. PICANTE_PROFILES_ENABLED defaults False (feature off by default).
- `src/worldcup_bot/chat/listener.py` — Step 7.5: best-effort `timeline_append` after last_seen update. Guarded by `picante_profiles_enabled(settings) and settings.picante_store_text`. Any exception → WARNING, never breaks on_group_text.
- `src/worldcup_bot/chat/picante.py` — `build_picante_user_message` gained optional params `profiles`, `author_username`, `others_cap`. Profiles=None → identical behaviour. `maybe_reply` loads profiles (fail→None), passes to builder, persists pique after reply (best-effort). PROFILES path in `context.bot_data["picante_profiles_path"]`.
- `src/worldcup_bot/__main__.py` — Added `profile_update_job(context)` async function (incremental, single-conversation pass). Added profile AI client setup (cheap model, fallback to main). Registered with `run_daily` at `PICANTE_PROFILES_UPDATE_HOUR`. Added `picante_profiles_path` and `profile_ai_client` to `bot_data`.

**3 Refinements implemented vs Pirlo's original spec:**
1. **Incremental** (not 7-day re-read): `load_since(state_dir, last_run)` returns only new messages; `save_last_run` persists timestamp. No full re-read per run.
2. **2-day window** (not 7): `PICANTE_PROFILES_WINDOW_DAYS=2` default. Trim-on-write in `_trim_timeline`.
3. **Single timeline** (not per-user files): `picante_timeline.jsonl` with `{ts, username, text}` per line. One AI call per batch run, feeding the whole attributed conversation — captures threads, banter between users, running jokes.

**Key design anchors (file:line):**
- config fields: `config.py:68-74`
- `picante_profiles_enabled`: `config.py:97-99`
- timeline append: `timeline_store.py:40-57`
- trim-on-write: `timeline_store.py:60-81`
- `load_since`: `timeline_store.py:84-107`
- `UserProfile` dataclass: `profiles.py:19-44`
- group-conversation updater: `profile_updater.py:47-165`
- listener hook: `listener.py:104-115`
- profiles injection in build_picante_user_message: `picante.py:99-152`
- pique persistence in maybe_reply: `picante.py:222-238`
- profile_update_job: `__main__.py:219-265`

**Tests:** 2419 tests pass (0 regressions). Feature OFF by default → zero profile code runs in existing tests.

---

## Prior Sessions Summary (2026-07-01 to 2026-07-09)

- **2026-07-08:** KO draw-deferral fix (Switzerland 0-0 Colombia false notification). Added _KNOCKOUT_STAGE_NAMES frozenset in formatters.py to defer FINISHED KO matches without a decisive winner. Tests: 161 in test_formatters.py, all green.

- **2026-07-08:** Rich image birthday mode (July 8 annual). Birthday-themed images with wealth escalation. Cake imagery + balloons. Auto-incrementing age from RICH_BIRTH_YEAR=1984 (age 42 in 2026). Caption celebratory. Tests: 14 new in test_rich_image.py.

- **2026-07-07:** USA-Belgium goal flood post-mortem. Cross-source score reconciliation bug: when thread reports goal+VAR disallowed before API catches up, API's seen baseline drifts, causing false goal+false disallowed oscillation. Fix: advance OTHER source's seen to pre-VAR score on disallowed claim inside lock. .squad/skills/two-source-score-reconciliation/SKILL.md.

- **2026-07-06:** Clip fallback fix. Reddit soft-blocks datacenter IPs with HTTP 200 + empty JSON children. Code gated fallback on posts is None only → missed soft-blocks. Fix: normalize with or [], unconditional fallback when no JSON match. Tests: 5 new regression tests in test_clip_finder.py.

- **2026-07-01–2026-07-05:** /elecciones feature increments (MVP + image renderers + hourglass). Knockout matrix image (PIL, twemoji CDN flags). Phase-selector inline keyboard. CHOICES_TYPE env var. Cache with mtime+results hash. Multiple rejects (cache staleness, message split >4096) all fixed by Nesta on re-submission.

- **2026-07-01–2026-07-03:** Podium image rendering feature. New src/worldcup_bot/bot/podium_image.py module. Circular crop + crown drawing + placeholder tiles. Album → text fallback chain. 45 edge-case tests.
