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

### 2026-07-10 — Picante prompt recalibration (conditional context usage)

**File:** `src/worldcup_bot/chat/picante.py:23-38` (`_SYSTEM`), `picante.py:104-108` (inline instruction in `build_picante_user_message`)

**What changed:**
- `_SYSTEM` REGLA DE CONTEXTO: removed "EXCLUSIVAMENTE" from MISIÓN, removed "solo de apoyo" / "IGNÓRALOS por completo" framing. Replaced with a **balanced conditional**: if CONTEXTO RECIENTE is clearly related (same topic / ongoing thread) → *tenlo en cuenta y aprovéchalo* (explicitly active); if not related → *ignóralo por completo*. The "use-it-when-related" branch is now a positive instruction, not a barely-permitted exception.
- `build_picante_user_message` inline label: "CONTEXTO RECIENTE — si está claramente relacionado con el ÚLTIMO MENSAJE, tenlo en cuenta y aprovéchalo; si no lo está, ignóralo por completo" (was "úsalo SOLO si está claramente relacionado... si no, ignóralo").

**Why:** The old absolute wording ("EXCLUSIVAMENTE", "solo de apoyo", "IGNÓRALOS por completo") biased the model toward always ignoring context, even when the recent conversation was clearly on the same topic. The plumbing was already correct — listener.py appends every valid group message to the RingBuffer *before* calling `maybe_reply`, and `build_picante_user_message` puts all prior messages (up to `chat_buffer_size`) into the CONTEXTO RECIENTE block. The fix was prompt-only.

**Tests:** 156 tests green after change (test_chat.py + test_chat_edge_cases.py). No test assertions on the specific old wording substrings; no Buffon updates required from this change.

---

## Prior Sessions Summary (2026-07-01 to 2026-07-09)

- **2026-07-08:** KO draw-deferral fix (Switzerland 0-0 Colombia false notification). Added _KNOCKOUT_STAGE_NAMES frozenset in formatters.py to defer FINISHED KO matches without a decisive winner. Tests: 161 in test_formatters.py, all green.

- **2026-07-08:** Rich image birthday mode (July 8 annual). Birthday-themed images with wealth escalation. Cake imagery + balloons. Auto-incrementing age from RICH_BIRTH_YEAR=1984 (age 42 in 2026). Caption celebratory. Tests: 14 new in test_rich_image.py.

- **2026-07-07:** USA-Belgium goal flood post-mortem. Cross-source score reconciliation bug: when thread reports goal+VAR disallowed before API catches up, API's seen baseline drifts, causing false goal+false disallowed oscillation. Fix: advance OTHER source's seen to pre-VAR score on disallowed claim inside lock. .squad/skills/two-source-score-reconciliation/SKILL.md.

- **2026-07-06:** Clip fallback fix. Reddit soft-blocks datacenter IPs with HTTP 200 + empty JSON children. Code gated fallback on posts is None only → missed soft-blocks. Fix: normalize with or [], unconditional fallback when no JSON match. Tests: 5 new regression tests in test_clip_finder.py.

- **2026-07-01–2026-07-05:** /elecciones feature increments (MVP + image renderers + hourglass). Knockout matrix image (PIL, twemoji CDN flags). Phase-selector inline keyboard. CHOICES_TYPE env var. Cache with mtime+results hash. Multiple rejects (cache staleness, message split >4096) all fixed by Nesta on re-submission.

- **2026-07-01–2026-07-03:** Podium image rendering feature. New src/worldcup_bot/bot/podium_image.py module. Circular crop + crown drawing + placeholder tiles. Album → text fallback chain. 45 edge-case tests.
