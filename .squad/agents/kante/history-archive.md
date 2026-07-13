# Kanté — History Archive

## Prior Sessions Summary (2026-07-01 to 2026-07-09)

- **2026-07-08:** KO draw-deferral fix (Switzerland 0-0 Colombia false notification). Added _KNOCKOUT_STAGE_NAMES frozenset in formatters.py to defer FINISHED KO matches without a decisive winner. Tests: 161 in test_formatters.py, all green.

- **2026-07-08:** Rich image birthday mode (July 8 annual). Birthday-themed images with wealth escalation. Cake imagery + balloons. Auto-incrementing age from RICH_BIRTH_YEAR=1984 (age 42 in 2026). Caption celebratory. Tests: 14 new in test_rich_image.py.

- **2026-07-07:** USA-Belgium goal flood post-mortem. Cross-source score reconciliation bug: when thread reports goal+VAR disallowed before API catches up, API's seen baseline drifts, causing false goal+false disallowed oscillation. Fix: advance OTHER source's seen to pre-VAR score on disallowed claim inside lock. .squad/skills/two-source-score-reconciliation/SKILL.md.

- **2026-07-06:** Clip fallback fix. Reddit soft-blocks datacenter IPs with HTTP 200 + empty JSON children. Code gated fallback on posts is None only → missed soft-blocks. Fix: normalize with or [], unconditional fallback when no JSON match. Tests: 5 new regression tests in test_clip_finder.py.

- **2026-07-01–2026-07-05:** /elecciones feature increments (MVP + image renderers + hourglass). Knockout matrix image (PIL, twemoji CDN flags). Phase-selector inline keyboard. CHOICES_TYPE env var. Cache with mtime+results hash. Multiple rejects (cache staleness, message split >4096) all fixed by Nesta on re-submission.

- **2026-07-01–2026-07-03:** Podium image rendering feature. New src/worldcup_bot/bot/podium_image.py module. Circular crop + crown drawing + placeholder tiles. Album → text fallback chain. 45 edge-case tests.

## Archived Sessions — 2026-07-10 Sessions

### Micky Birthday Special (2026-07-10)

- Added july-10 Micky birthday special image generation (separate pipeline, evolution chain isolation)
- Implemented in ich_image.py with helpers: is_micky_birthday(), micky_birthday_age()
- Generalized dit_rich_image with xtra_paths parameter
- Tests: 251 existing green, 30 new tests added

### Picante per-user profile system (2026-07-10)

- Design: cost model analysis, 3-strategy evaluation (daily batch recommended)
- Implementation: timeline_store.py, profiles.py, profile_updater.py
- Feature: per-user profiles with rasgos, equipo, motes, temas, tono, piques_recientes
- Picante prompt recalibration: balanced conditional context usage
- Hidden commands: /perfil @usuario (inspector), /calcularperfiles (on-demand trigger)
- Tests: 2586 passed (profiles feature OFF by default)

_For complete details on these sessions, see the previous git history._
