# Archive: Kante History (Earlier Sessions)

## 2026-06-15 — Full package implementation [ARCHIVED]

**Module map (all 18 files created):**

```
src/worldcup_bot/
  __init__.py           — version only
  __main__.py           — build_app() + main() entry point
  config.py             — Settings dataclass + load_settings()
  data/
    stages.py           — GROUPS, KNOCKOUT_STAGES, STAGE_YAML_KEYS, GROUP_SCORING
    tla_map.py          — TLA_TO_ISO (100+ entries) + tla_to_iso(code)
    tongo.py            — FRASES list (42 entries, heavy Sanchez weighting)
  api/
    models.py           — Match, Standing, StageResult dataclasses
    cache.py            — TTLCache(ttl=60) + module-level _default_cache
    client.py           — FootballDataClient + FootballAPIError
  porra/
    predictions.py      — load(path), get_participant, find_by_display_name, display_name_for, list_usernames
    scoring.py          — score_groups(), score_knockout(), score_user_groups_detail()
    engine.py           — compute_group_ranking(), compute_knockout_ranking(), compute_general_ranking(), compute_user_detail()
  bot/
    formatters.py       — format_match, format_standings, format_knockout_results, format_general_ranking, format_stage_ranking, format_user_detail, team_flag
    handlers.py         — 17 command handlers
```

**Key decisions made:**
- `actual_standings` dict uses `GROUP_A` keys (as returned by football-data.org); `user_groups` dict uses plain letters `A`–`L`. `score_groups()` internally maps `A` → `GROUP_A`.
- `STAGE_YAML_KEYS` in `stages.py` maps `"ROUND_OF_32"` → `"round_of_32"` etc. Scoring uses this so nothing is hardcoded.
- `predictions.py` hot-reload uses `os.path.getmtime()` — file must be accessible from within the container.
- `engine.compute_general_ranking()` calls `score_knockout()` once for total KO pts, then a second pass per-stage for the breakdown dict. Slight redundancy but keeps `score_knockout` pure.
- `bot_data["settings"]` is how Settings reaches handlers (set in `build_app()`).
- Winner photo URL pattern: `http://victorsaez.cat/{display_name}.png` (from legacy). Falls back to Nicolas Cage URL on tie.
- England TLA `ENG` → ISO `GBENG` (England flag 🏴󠁧󠁢󠁥󠁮󠁧󠁿) — changed from legacy's `GB` for correctness.

## 2026-06-15 — Group scoring model changed to exact=1.0 / qualifies-wrong-position=0.5 [ARCHIVED]

**New model (active):**
- `GROUP_SCORING = {"exact_position": 1.0, "qualified_wrong_position": 0.5}`
- Predicted team finishes at **exact** predicted position → **+1.0 pt**, note `"exacto"`
- Predicted team finishes in top-3 (qualifies) but in a **different** position → **+0.5 pt**, note `"clasifica"`
- Predicted team finishes **4th** (does not qualify) → **0 pt**, note `"fallo"`
- `QUALIFY_PER_GROUP = 3` drives the qualification threshold; imported into `scoring.py`.
- Note label `"cerca"` was removed entirely; replaced by `"clasifica"`.
- Knockout scoring intentionally left **unchanged** (see `KNOCKOUT_STAGES` in `stages.py`).

- `main()` in `__main__.py` now calls `truststore.inject_into_ssl()` (guarded in `try/except`) before any HTTP or settings loading, so the OS/container trust store is used and corporate CA certs are trusted automatically.

## 2026-06-15 — TLA map made alias-tolerant (Buffon QA fix) [ARCHIVED]

- `tla_map.py` now carries **both** the FIFA code and the ISO 3166-1 alpha-3 alias for Saudi Arabia (`KSA` and `SAU` → `"SA"`) and for Chile (`CHI` and `CHL` → `"CL"`) and Paraguay (`PAR` and `PRY` → `"PY"`). Neither old entry was removed.
- `predictions.py` docstring for `load()` was corrected: it returns `{"participants": {}}` on missing file or parse error (not `{}`).
- **Still to verify against live API:** whether football-data.org actually returns `SAU` or `KSA` (and `CHL`/`PRY`) in `/standings` responses — the alias approach protects us either way, but the example data should ultimately reflect what the API actually sends.

## 2026-06-15 — predictions default is now relative data/predictions.yml; works on host and in container [ARCHIVED]

- `config.py` default for `predictions_path` changed from `/app/data/predictions.yml` to `data/predictions.yml` (relative). Resolves correctly from repo root on host and from `WORKDIR /app` in container. Docker compose files already set `PREDICTIONS_PATH` explicitly — unaffected. Prediction-dependent commands (`/porra`, `/general`, `/participantes`, `/listaaciertos`, `/mispredicciones`, and all knockout-stage commands) now reply with a path-aware Spanish error message when no participants are loaded.

- **Bug confirmed in production:** `football-data.org /standings` returns `"group": "Group A"` (title-case, space-separated), not `"GROUP_A"`. This caused `score_groups()` lookups to fail — every team resolved as `no_data` and all users scored 0.
- **Fix:** Added `_normalize_group(raw)` static helper to `FootballDataClient` (`client.py`). It does `raw.strip().upper().replace(" ", "_")` and handles `None`/empty passthrough. Applied at two parse boundaries: `get_standings()` (group_name) and `_parse_match()` (match group field). `score_groups()` was NOT changed — canonical form is `GROUP_X` throughout the domain.
- **Root cause of test blindness:** unit test fixtures used `"GROUP_A"` directly instead of the real API format, so the mismatch was invisible until live testing.

## 2026-06-15 — Consolidation + Cross-Agent Learnings [ARCHIVED]

- **Normalization layer belongs at API boundary:** Group identifiers should be normalized once, at the API client layer, never in business logic. This keeps scoring.py pure and ensures correctness for all callers (current + future).
- **Public API contracts enable parallel testing:** Buffon wrote tests before implementation completed because Kanté published exact signatures early. Zero rework.
- **Silent failures require end-to-end testing:** Group normalization and Saudi Arabia TLA bugs both passed unit tests but failed in production. Both had zero error messages — just wrong output. Unit test fixtures (using canonical forms) masked the API mismatch.
- **Truststore injection at startup is critical:** SSL cert validation in corporate/containerized environments requires explicit truststore.inject_into_ssl() call before any HTTP.
- **Hot-reload via mtime checking works well:** Predictions file changes take effect on next command; no restart needed. Useful for tournament corrections and user adjustments.
- **Lesson for future sessions:** Always mock third-party APIs using real response shapes in test fixtures, not internal canonical forms. When in doubt, grab a recorded response from the actual API docs.
