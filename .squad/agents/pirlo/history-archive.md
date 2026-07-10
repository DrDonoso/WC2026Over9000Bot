# Pirlo — History Archive

Archived on 2026-07-10T11:49:33Z by Scribe. Contains all sessions prior to 2026-07-10.

## Archived Sessions (2026-06-30 to 2026-07-09)

### Approval Verdicts (completed reviews)
- ✅ LLM Chat Features (Picante + Revive) — SHIPPED
- ✅ Revive Quiet Hours + Jitter — SHIPPED
- ✅ ChatState Eager Persistence — APPROVED
- ✅ Podium Photo Feature (feasibility + impl) — SHIPPED
- ✅ Crown Asset Integration — SHIPPED
- ✅ Podium Drawn-Base Layout — SHIPPED
- ✅ USA-Belgium VAR Flood Cross-Source Fix — APPROVED
- ✅ Post-Final VAR Score Correction Watch — APPROVED
- ✅ TVE Knockout-Round Prefix + Midnight Notation Fix — APPROVED
- ✅ "Ver gol" Button Clip-Pipeline Fix — APPROVED
- ✅ Schedule-Live Seeding Fix — APPROVED
- ✅ KO Draw Deferral Bug Fix — APPROVED

### Pending Review
- ⏳ USA-Belgium VAR Reconcile Fix Review (2026-07-07) — Awaiting DrDonoso go-ahead

### Key Learnings
- Pure gate functions (probability, cooldown, daily_cap, min_buffer) enable comprehensive unit testing without mocks
- Self-rescheduling run_once loops with finally-based reschedule are more robust than run_repeating
- load_X/save_X atomic pattern (temp → os.replace, never-raises) is the standard for persistent stores
- Secondary AI client with different model (same endpoint, different model=) is correct for model split
- asyncio single-threaded semantics eliminate double-count in incremental jobs

---

*Full archived content available in prior session records.*
