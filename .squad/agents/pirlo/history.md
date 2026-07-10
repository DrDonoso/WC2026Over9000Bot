# Project Context

- **Owner:** DrDonoso
- **Project:** WorldCup2026Over9000TelegramBot — a Telegram bot to compete in a porra (betting pool) with friends, scoring predictions against real fixtures and results.
- **Stack:** Python (Telegram bot), football-data.org API for fixtures & results, Docker + docker-compose, GitHub Actions → Docker Hub.
- **Created:** 2026-06-15

## Recent Sessions (Picante Per-User Profiles Feature)

### 2026-07-10T12:00:56+02:00 — Spec: Perfiles per-user auto-aprendidos para Picante

**Rol:** Lead / Architect — design spec (no implementation).  
**Estado:** ✅ SPEC COMPLETED → KANTÉ IMPLEMENTATION APPROVED

**Scope:** Auto-learned profiles, 6 fields, include_others with cap, 2-day text retention, daily batch, model split (PICANTE_PROFILE_MODEL cheap / OPENAI_MODEL reply).

**Architecture:** 4 new modules (message_store, profiles, profile_updater, + 3 modified files picante/listener/config/__main__).

**Key design decisions locked:**
- Incremental summarization (load_since + save_last_run)
- 2-day retention window + trim-on-write
- Single chronological timeline (not per-user) with one AI call per run
- Model split: cheap PICANTE_PROFILE_MODEL for summaries

### 2026-07-10T12:00:56+02:00 — Review: Picante Per-User Profiles (Kanté impl) — APPROVED

**Rol:** Lead reviewer (gate).  
**Veredicto:** ✅ APPROVE — 0 blockers, 0 majors, 8 minors (all applied by Kanté).

**3 refinements verified correct:**
1. Incremental (load_since + save_last_run) — asyncio single-threaded, no double-count
2. Retención 2 días + trim-on-write — atomic, timezone-aware, no data loss
3. Timeline grupal + single AI call — participants filtered correctly, tokens scaled by N

**8 minors applied (kante-10 session):**
- M3: order-preserving dedupe (list(dict.fromkeys))
- M4: motes/temas caps (keep-most-recent strategy)
- M5: max_completion_tokens scaled (200 + 120*N)
- M1,M2,M6,M7,M8: refinements applied per review

**Test suite:** 2561 green baseline → Buffon +12 guard tests → 2573 green.

**Leadership status:** Both reviewer gates (Pirlo + Buffon) APPROVED. Feature ready for git commit.

---

*For archived sessions prior to 2026-07-10, see history-archive.md*
