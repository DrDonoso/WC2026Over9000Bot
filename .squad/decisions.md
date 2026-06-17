# Squad Decisions

## 1. Architecture & Product Design — WorldCup2026Over9000TelegramBot

**Author:** Pirlo (Lead)  
**Date:** 2026-06-15 (REVISED)  
**Status:** LOCKED — migration from legacy Euro 2024 bot complete.

### Overview
Complete rewrite from legacy Euro bot with new Porra model (group standings + knockout qualifiers, NOT exact-score per match). No SQLite—predictions live in mounted YAML file, results from football-data.org API.

### Key Decisions
1. **Porra model:** Group standings (top-3 per group) + knockout qualifiers per stage (not match-by-match).
2. **Predictions storage:** YAML file (mounted at `/app/data/predictions.yml`), keyed by Telegram @username, case-insensitive.
3. **API client:** Synchronous `requests`-based (not async httpx) for simplicity; TTL in-memory cache respects 10 req/min rate limit.
4. **No SQLite:** Rankings computed on-the-fly; YAML is single source of truth for predictions.
5. **Hot-reload:** Predictions file is checked on each command (mtime-based); edits take effect without restart.
6. **Docker mount:** Bind-mount at container startup; `docker-compose.yml` (prod pulls from Docker Hub) vs `docker-compose.local.yml` (dev builds locally).

### Project Layout
```
pyproject.toml
Dockerfile (two-stage, python:3.12-slim, no ffmpeg/yt-dlp)
docker-compose.yml / docker-compose.local.yml
.env.example
predictions.example.yml (template, committed)
data/ (git-ignored; host mounts predictions.yml here)
src/worldcup_bot/
  __init__.py, __main__.py, config.py
  bot/ (handlers.py, formatters.py)
  api/ (client.py, models.py, cache.py)
  porra/ (predictions.py, scoring.py, engine.py)
  data/ (tla_map.py, tongo.py, stages.py)
tests/
  conftest.py, test_scoring.py, test_predictions_loader.py, test_api_client.py, test_handlers.py
```

### WC2026 Constants (data/stages.py)
```python
GROUPS = list("ABCDEFGHIJKL")  # 12 groups
TEAMS_PER_GROUP = 4
QUALIFY_PER_GROUP = 3  # users predict top-3 (legacy feel + 3rd-place matters)

KNOCKOUT_STAGES = [
    ("ROUND_OF_32", "Treintaidosavos", 1),
    ("LAST_16", "Octavos de Final", 1),
    ("QUARTER_FINALS", "Cuartos de Final", 2),
    ("SEMI_FINALS", "Semifinales", 3),
    ("FINAL", "Final", 5),
]
```

### Scoring
- **Group phase:** exact position +1.0, qualified-wrong-position +0.5, wildcard `**` +0 (see Decision #6 for details)
- **Knockout:** correct qualifier per stage = stage_points
- **General ranking:** base_score + group_points + sum(knockout_points)

### Module Decoupling (enforced)
- `porra/scoring.py`: pure functions only, no I/O
- `api/client.py`: depends on config, cache; never imports bot/ or porra/
- `bot/handlers`: depends on porra/engine, config
- `data/*`: pure constants, no dependencies

### Environment Variables
**Required:** `TELEGRAM_BOT_TOKEN`, `FOOTBALL_DATA_API_KEY`  
**Optional:** `PREDICTIONS_PATH` (def: `/app/data/predictions.yml`), `COMPETITION_CODE` (def: `WC`), `TIMEZONE` (def: `Europe/Madrid`), `TELEGRAM_GROUP_ID`

### Governance
- All stage names, points, group letters driven from `data/stages.py` (never hardcode).
- YAML validation on load: skip invalid users (log error, don't crash).
- TLA normalization at API client layer (group identifiers from API are title-case "Group A" → normalize to "GROUP_A").

---

## 2. Infra Scaffold Decision — Phase 1

**Author:** Maldini (DevOps)  
**Date:** 2026-06-15  
**Status:** DONE — scaffolding complete.

### Dockerfile (Two-Stage Cache Pattern)
```dockerfile
# Stage 1: install deps
COPY pyproject.toml .
RUN mkdir -p src/worldcup_bot && touch src/worldcup_bot/__init__.py && pip install .

# Stage 2: copy code + install package (no re-download)
COPY src/ src/
RUN pip install --no-deps .
```
- **Base image:** `python:3.12-slim` (no ffmpeg, no yt-dlp — not needed)
- **Caching:** deps layer cached until pyproject.toml changes; code layer is small, fast rebuild

### docker-compose.yml vs docker-compose.local.yml
- **docker-compose.yml (production):** pulls `drdonoso/worldcup2026` from Docker Hub, always up-to-date
- **docker-compose.local.yml (dev):** adds `build: .`, builds locally before start

Both mount `./data/predictions.yml` → `/app/data/predictions.yml:ro` (read-only bind-mount).

### CI Pipeline
Mirrors `RedditSoccerGoals` exactly:
- CalVer versioning
- Buildx for multi-arch
- Docker Hub push via `DOCKER_USERNAME` / `DOCKER_PASSWORD` secrets
- GitHub Release on tag

### File Conventions
- `predictions.example.yml` — committed template
- `data/predictions.yml` — git-ignored, contains real data
- `data/.gitkeep` — ensures directory exists in repo
- `.env.example` — template for env vars
- `.gitignore` — adds `data/predictions.yml`, `.env`

---

## 3. Kanté Implementation Summary — Public API Contract

**Author:** Kanté (Backend)  
**Date:** 2026-06-15  
**Status:** COMPLETE — all modules implemented and syntax-validated.

### Public API Signatures (for Buffon tests)

#### config.py
```python
@dataclass
class Settings:
    telegram_bot_token: str
    football_data_api_key: str
    predictions_path: str = "/app/data/predictions.yml"
    competition_code: str = "WC"
    timezone: str = "Europe/Madrid"
    telegram_group_id: str | None = None

def load_settings() -> Settings:
    """Reads env vars. Raises RuntimeError if required vars missing."""
```

#### data/tla_map.py
```python
TLA_TO_ISO: dict[str, str]  # 100+ entries

def tla_to_iso(code: str) -> str | None:
    """Return ISO alpha-2 code or None for unknown TLAs."""
```

#### data/stages.py
```python
GROUPS: list[str]
TEAMS_PER_GROUP: int
QUALIFY_PER_GROUP: int
KNOCKOUT_STAGES: list[tuple[str, str, int]]
STAGE_YAML_KEYS: dict[str, str]  # API keys → yaml keys
GROUP_SCORING: dict[str, int]
```

#### api/models.py
```python
@dataclass
class Match:
    id: int
    utc_date: str
    status: str  # SCHEDULED | IN_PLAY | PAUSED | FINISHED
    stage: str   # GROUP_STAGE | LAST_16 | QUARTER_FINALS | ...
    group: str | None  # "GROUP_A" or None (normalized)
    home_tla: str; away_tla: str
    home_name: str; away_name: str
    home_score: int | None; away_score: int | None
    winner: str | None  # HOME_TEAM | AWAY_TEAM | DRAW | None

@dataclass
class Standing:
    group: str  # "GROUP_A" (normalized)
    position: int
    tla: str
    team_name: str
    points: int
    played: int

@dataclass
class StageResult:
    stage: str
    home_tla: str; away_tla: str
    winner_tla: str | None
```

#### api/cache.py
```python
class TTLCache:
    def __init__(self, ttl: float = 60.0) -> None: ...
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def invalidate(self, key: str) -> None: ...
    def clear(self) -> None: ...
```

#### api/client.py
```python
class FootballAPIError(Exception):
    status_code: int

class FootballDataClient:
    def __init__(self, api_key: str, competition_code: str = "WC", cache: TTLCache | None = None) -> None: ...
    
    def get_standings(self) -> list[Standing]: ...
    def get_all_matches(self) -> list[Match]: ...
    def get_stage_results(self, stage: str) -> list[StageResult]: ...
    def get_today_matches(self, tz_name: str = "Europe/Madrid") -> list[Match]: ...
    def get_next_match(self, tz_name: str = "Europe/Madrid") -> Match | None: ...
    def get_live_matches(self) -> list[Match]: ...
    def get_knockout_results(self) -> dict[str, list[str]]: ...  # {api_stage: [winner_tla, ...]}
    
    @staticmethod
    def _normalize_group(raw: str | None) -> str | None:
        """Group A → GROUP_A (applied at API parse layer)"""
```

#### porra/predictions.py
```python
def load(path: str) -> dict:
    """Hot-reload by mtime. Returns {"participants": {username: {...}}} or {} on error."""

def get_participant(predictions: dict, username: str) -> dict | None:
    """Case-insensitive lookup."""

def find_by_display_name(predictions: dict, name: str) -> tuple[str, dict] | None:
    """Case-insensitive search by display_name."""

def display_name_for(username: str, user_data: dict) -> str:
    """Returns display_name or '@username'."""

def list_usernames(predictions: dict) -> list[str]: ...
```

#### porra/scoring.py (pure functions)
```python
def score_groups(
    user_groups: dict[str, list[str]],      # {"A": ["GER", "HUN", "SUI"], ...}
    actual_standings: dict[str, list[str]], # {"GROUP_A": ["GER", "SUI", ...], ...}
) -> tuple[float, list[dict]]:
    """Returns (total_pts, detail_list).
    detail keys: group, team, predicted_pos, actual_pos, points, note
    note: 'exacto'(+1.0), 'clasifica'(+0.5), 'fallo'(0), 'no_data'(0), 'wildcard'(0)"""

def score_user_groups_detail(...) -> tuple[float, list[dict]]:
    """Alias for score_groups."""

def score_knockout(
    user_knockout: dict[str, list[str]],    # yaml keys e.g. "round_of_32"
    actual_winners: dict[str, list[str]],   # API keys e.g. "ROUND_OF_32"
    stages_config: list[tuple[str, str, int]] = KNOCKOUT_STAGES,
) -> tuple[float, list[dict]]:
    """Returns (total_pts, detail_list).
    detail keys: stage, display, team, points, note
    note: 'acierto', 'fallo', 'wildcard'"""
```

#### porra/engine.py
```python
@dataclass
class UserRankEntry:
    username: str; display_name: str
    total_score: float; base_score: float; group_score: float
    knockout_scores: dict[str, float]
    exact_group_hits: int

@dataclass
class StageRankEntry:
    username: str; display_name: str
    stage_score: float; winner_tla: str | None

def compute_group_ranking(predictions: dict, client: FootballDataClient) -> list[UserRankEntry]:
    """Sorted by total (group only), tie-break: exact_hits desc, name alpha."""

def compute_knockout_ranking(stage: str, predictions: dict, client: FootballDataClient) -> list[StageRankEntry]:
    """Sorted by stage_score desc, name alpha."""

def compute_general_ranking(predictions: dict, client: FootballDataClient) -> list[UserRankEntry]:
    """total = base + group + sum(all knockout stages). Same sort as above."""

def compute_user_detail(username: str, predictions: dict, client: FootballDataClient) -> dict | None:
    """Full breakdown or None if user not found."""
```

#### __main__.py
```python
def build_app(settings: Settings) -> Application:
    """Wires settings into bot_data and registers all 17 handlers."""

def main() -> None:
    """Entry point — loads settings, builds app, calls run_polling(). Exits 1 on missing env vars."""
```

### Registered Commands (17 total)
| Command | Notes |
|---------|-------|
| `/start` | Help text |
| `/resultados` | Knockout results |
| `/clasificacion` | Group standings |
| `/porra` | Group ranking |
| `/listaaciertos` | No-arg = caller; `@user` = lookup |
| `/endirecto` | Live matches |
| `/hoy` | Today's matches |
| `/siguiente` | Next match |
| `/ronda32`, `/octavos`, `/cuartos`, `/semis`, `/final` | Knockout stage rankings |
| `/general` | Full porra ranking |
| `/tongo` | Random frase |
| `/mispredicciones` | Caller's picks |
| `/participantes` | List all users |

### Caveats for Testing
1. **Actual standings key format:** `score_groups()` expects `GROUP_A` keys (API format). User dicts use plain `A`—`L`.
2. **Knockout yaml vs API keys:** User dict has `round_of_16` (yaml); API has `LAST_16` — mapping done internally.
3. **Wildcard `**`** always scores 0, never errors.
4. **Teams with `playedGames == 0`:** `score_groups()` returns `note="no_data"` (0 pts).
5. **TTLCache:** Not thread-safe for extreme concurrent load, but fine for <15 users.
6. **Flag library:** England `GBENG`, Scotland `GBSCT`, Wales `GBWLS` (updated from legacy `GB`).
7. **Photo URL pattern:** `http://victorsaez.cat/{display_name}.png` — falls back to text on 404.

---

## 4. API Format Gotcha: football-data.org group identifiers (CRITICAL FIX)

**Author:** Kanté  
**Date:** 2026-06-15  
**Status:** FIXED — regression test added.

### The Problem
`football-data.org /standings` returns groups as title-case `"Group A"` (with space), not `"GROUP_A"`. Our `score_groups()` expected the latter; lookups were silently missing. Tests passed because fixtures hard-coded `"GROUP_A"`.

### The Fix
Added `_normalize_group()` static helper to `FootballDataClient`:
```python
@staticmethod
def _normalize_group(raw: str | None) -> str | None:
    if not raw:
        return raw
    return raw.strip().upper().replace(" ", "_")
```

Applied at **both** parse boundaries:
1. `get_standings()` — normalizes group before setting `Standing.group`
2. `_parse_match()` — normalizes match group before setting `Match.group`

Result: `score_groups()` always receives canonical `GROUP_X` format.

### Regression Test
`tests/test_api_client.py::TestGetStandings::test_real_api_format_group_a_normalized` — mocks real API format `"Group A"` and asserts normalization to `"GROUP_A"`.

### Lesson Learned
**Always mock 3rd-party API fixtures using the real response shape**, not internal canonical form. When in doubt, use recorded or documented API responses.

---

## 5. Buffon QA Findings — Test Suite Results

**Author:** Buffon (Tester)  
**Date:** 2026-06-15  
**Status:** TWO CRITICAL BUGS FIXED; 131 passing tests.

### Bug 1 — pyproject.toml: wrong flag library name (CRITICAL)

**File:** `pyproject.toml`, line with `flag>=1.4`  
**Severity:** Blocks `pip install` entirely

**Expected:** `emoji-country-flag>=2.0`  
**Actual:** `flag>=1.4`

The package `flag` on PyPI (https://pypi.org/project/Flag/) is a Go-style CLI parser (v0.1.1), not the country emoji library.  
The actual library is `emoji-country-flag` (https://pypi.org/project/emoji-country-flag/), currently at v2.1.0.

**Fix Applied:** Updated `pyproject.toml` to `emoji-country-flag>=2.0`.

### Bug 2 — TLA mismatch for Saudi Arabia (HIGH)

**Files:** `predictions.example.yml` (group I) and `src/worldcup_bot/data/tla_map.py`  
**Severity:** Silently drops users at load time

**Expected:** `tla_map.py` and `predictions.example.yml` agree on Saudi Arabia TLA.  
**Actual:**
- `tla_map.py` maps `"KSA"` → `"SA"`
- `predictions.example.yml` uses `"SAU"` in group I

**Observed behavior:** Users `davidrodr` and `cris_username` silently skipped on load (only `victorsaez` loaded).

**Root cause:** football-data.org likely uses `"SAU"` as Saudi Arabia's TLA in API responses. The example YAML was correct; the mapping was incomplete.

**Fix Applied:** Added `"SAU": "SA"` alias to `tla_map.py`.

### Test Suite Status
```
131 passed in 1.40s
pytest command: .venv\Scripts\python.exe -m pytest -q
```

### Non-bugs (documentation)
- `predictions.py` docstring says "Returns {} on missing file" but actually returns `{"participants": {}}`. Tests use real behavior; doc update pending.

---

## 6. Decision: Live predictions file populated with real participants

**Author:** Maldini (DevOps)
**Date:** 2026-06-15
**Status:** DONE

### Summary

`data/predictions.yml` has been populated with the group-stage predictions for all 12 real porra participants. The file is git-ignored and must be manually copied to the server on deploy — it will never be committed to the repository.

### Participants (in file order)

crispavon, dsantosmerino, vansid, patri, javipege, pilarfreixas, amalia, vicsaez, mariatarrago, josunefon, drdonoso, sialau

### Key facts

- **Group stage only:** all knockout stage lists are explicit `[]` (empty).
- **display_names:** set to `@handle` placeholders; owner fills real names when ready.
- **Validation:** loader reports `participants loaded: 12`, every user `thirds= 8`. No ERROR log lines.
- **TLA coverage:** all TLAs verified against `tla_map.py` before writing.

### Deploy note ⚠️

Because `data/predictions.yml` is git-ignored, it is **not** included in the Docker image or git history. On every new server deployment (fresh clone or new machine), this file must be copied manually before starting the container. Recommended workflow:

```bash
# On the server, after cloning the repo:
scp predictions.yml user@server:/path/to/repo/data/predictions.yml
docker compose up -d
```

Hot-reload is mtime-based: editing the file on the host takes effect immediately without restarting the container (as long as `./data:/app/data:ro` directory-mount is used, not a single-file mount).

---

## 7. Decision: Group-Phase Scoring Model Change

**Author:** Kanté (Backend)  
**Date:** 2026-06-15  
**Status:** IMPLEMENTED  
**Supersedes:** decision §1 Scoring line (previous: "exact position +3, off-by-one +1")

### Decision

The group-phase scoring model was changed from the original exact+3 / off-by-one+1 scheme to:

| Outcome | Points | Note label |
|---|---|---|
| Predicted team finishes at **exact** predicted position | **+1.0** | `exacto` |
| Predicted team finishes in top-3 but **wrong** position | **+0.5** | `clasifica` |
| Predicted team finishes **4th** (does not qualify) | **0** | `fallo` |
| Wildcard `**` or empty | **0** | `wildcard` |
| Team not in standings yet | **0** | `no_data` |

The qualification threshold is `QUALIFY_PER_GROUP = 3` (already defined in `stages.py`).

### Rationale

User's verbatim intent: "1 punto por acierto, pero si aciertas que el 3º pasa pero pasa como primero, o al revés, tienes 0,5 puntos." The old diff-based model (diff=0 → 3pts, diff=1 → 1pt, diff≥2 → 0) did not reward the scenario where a team qualifies but in a different position — predicted 3rd, finishes 1st was scoring 0 instead of 0.5.

### Files Changed

- `src/worldcup_bot/data/stages.py` — `GROUP_SCORING` type changed to `dict[str, float]`, keys `exact_position=1.0` / `qualified_wrong_position=0.5` (removed `off_by_one`).
- `src/worldcup_bot/porra/scoring.py` — diff-based logic replaced with qualification-aware logic; `QUALIFY_PER_GROUP` imported; note `"cerca"` removed, `"clasifica"` introduced.
- `src/worldcup_bot/bot/formatters.py` — `note_map` updated: `"exacto": "✅ +1"`, `"clasifica": "🔶 +0.5"`.
- `tests/test_scoring.py` — all group-phase assertions recomputed; `TestScoreGroupsQualifiesWrongPosition` added with 5 explicit edge-case tests.

### Out of Scope

Knockout scoring (`score_knockout`, `KNOCKOUT_STAGES`) was intentionally **not changed**.

---

---

## 8. Decision: docker-compose.local.yml — Corporate SSL Remediation

**Author:** Maldini (DevOps)  
**Date:** 2026-06-15  
**Status:** DONE — applied and verified.

### Problem

On a corporate network with SSL inspection, outbound HTTPS is intercepted by an SSL-inspection proxy. The proxy presents certificates signed by the corporation's own root/intermediate CAs. These are trusted on the Windows host (via the Windows certificate store + `truststore` Python dep) but **not** inside the Linux container (`python:3.12-slim`).

On first container start the bot crashed immediately:
```
httpcore.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
  self-signed certificate in certificate chain (_ssl.c:1010)
```

Note: `truststore.inject_into_ssl()` is called in `__main__.py` but it reads the **Linux OS trust store**, which has no corporate CAs — so it does not help inside the container.

### Decision

Inject the corporate CAs into the container's SSL verification chain via environment variables (`SSL_CERT_FILE` + `REQUESTS_CA_BUNDLE`), pointing to a pre-built combined CA bundle mounted from the host.

**No Dockerfile change.** The fix lives entirely in `docker-compose.local.yml` (local dev only). Production `docker-compose.yml` is unchanged.

### Implementation

#### 1 — CA bundle at `certs/combined-ca-bundle.pem` (git-ignored)

Built on the developer's machine:

```powershell
# Export the corporate SSL-inspection CAs from the Windows trust store to PEM
$certs = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -match '<YOUR_CORPORATE_CA_NAME>' }
$pem = ""
foreach ($c in $certs) {
    $b64 = [Convert]::ToBase64String($c.Export("Cert"), "InsertLineBreaks")
    $pem += "# $($c.Subject)`n-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----`n`n"
}
$pem | Out-File certs\corp-ca-bundle.pem -Encoding ascii

# Extract container system CA bundle
docker run --rm --entrypoint sh drdonoso/worldcup2026 -c "cat /etc/ssl/certs/ca-certificates.crt" > certs\system-ca-bundle.pem

# Combine
(Get-Content certs\system-ca-bundle.pem -Raw) + "`n" + (Get-Content certs\corp-ca-bundle.pem -Raw) |
    Out-File certs\combined-ca-bundle.pem -Encoding ascii -NoNewline

# Clean up intermediates
Remove-Item certs\system-ca-bundle.pem, certs\corp-ca-bundle.pem -Force
```

The `certs/` directory is added to `.gitignore` — corporate root CAs must never be committed.

#### 2 — docker-compose.local.yml additions

```yaml
environment:
  SSL_CERT_FILE: /certs/combined-ca-bundle.pem
  REQUESTS_CA_BUNDLE: /certs/combined-ca-bundle.pem

volumes:
  - ./certs:/certs:ro
```

`SSL_CERT_FILE` is read by Python's `ssl` module (used by httpx → python-telegram-bot).  
`REQUESTS_CA_BUNDLE` is read by the `requests` library (used by `FootballDataClient`).  
Both cover all outbound HTTPS calls the bot makes.

### Verification

```
docker compose -f docker-compose.local.yml ps
# → STATUS: Up  (no Restarting)

docker inspect worldcup2026over9000telegrambot-worldcup-bot-1 \
  --format "RestartCount={{.RestartCount}}"
# → RestartCount=0

docker compose -f docker-compose.local.yml logs --tail=20
# → [INFO] __main__: Starting WorldCup2026 bot | competition=WC | predictions=/app/data/predictions.yml
# → [INFO] telegram.ext.Application: Application started
# → getUpdates HTTP/1.1 200 OK

docker exec worldcup2026over9000telegrambot-worldcup-bot-1 \
  python -c "from worldcup_bot.porra.predictions import load; d=load('/app/data/predictions.yml'); print('participants loaded:', len(d['participants']))"
# → participants loaded: 12
```

### Portability

| Environment | SSL fix needed? | Notes |
|---|---|---|
| Developer machine (corporate network) | **YES** — this PR | Requires `certs/combined-ca-bundle.pem` on host |
| CI (GitHub Actions) | No | Not behind corporate proxy |
| Production server (VPS/cloud) | No | `docker-compose.yml` has no cert mounts |

**If a new developer needs to reproduce:** they must regenerate `certs/combined-ca-bundle.pem` on their own machine following the PowerShell steps above (or get the file from a colleague — but never via git).

### Alternatives Considered

| Option | Rejected because |
|---|---|
| Add certs to Dockerfile (`update-ca-certificates`) | Embeds corporate CAs in the image; breaks non-inspected deployments |
| `user: root` + entrypoint `update-ca-certificates && su app -c ...` | Complex; forces root in docker-compose.local.yml |
| Only `REQUESTS_CA_BUNDLE` | Doesn't cover httpx (python-telegram-bot), which uses `ssl` module |
| Only `SSL_CERT_FILE` | Replaces entire CA bundle; risky if not combined with system CAs |

---

---

## 9. Decision: /actual (provisional) vs /general (official) ranking split

**Author:** Kanté (Backend)  
**Date:** 2026-06-15T15:14+02:00  
**Status:** IMPLEMENTED  
**Requested by:** DrDonoso

### Context

During the group stage, `/general` was scoring groups from the live standings (`client.get_standings()`). This meant points were provisional and fluctuated as matches were played. Users wanted a clear distinction between a live snapshot and an "official" score that only commits once a group is fully complete.

### Decision

Split ranking commands into three:

| Command | Mode | Group scoring |
|---|---|---|
| `/actual` | Provisional | All groups — uses live standings regardless of match status |
| `/porra` | Alias of `/actual` | (same) |
| `/general` | Official | Only groups where **all** matches are `FINISHED` contribute points; in-progress groups score 0 |

Knockout scoring is **unchanged in both modes** — it already only counts finished matches.

### Implementation

#### `client.get_finished_groups() -> set[str]`
New method on `FootballDataClient`. Calls `get_all_matches()` (already TTL-cached), groups by `Match.group` (ignores `None` = knockout), and returns only groups where every match has `status == "FINISHED"`. Returns canonical `GROUP_X` keys (already normalised at the parse boundary).

#### `engine._build_actual_standings(client, only_groups=None)`
Added `only_groups: set[str] | None = None` parameter. When given, standings for groups not in the set are excluded from the returned dict. `score_groups` sees a missing key → falls through its `no_data` branch → 0 pts. Default `None` preserves original behaviour.

#### `engine.compute_general_ranking(predictions, client, official=False)`
Added `official: bool = False` keyword argument.
- `official=False`: calls `_build_actual_standings(client)` — unchanged behaviour.
- `official=True`: calls `client.get_finished_groups()` then `_build_actual_standings(client, only_groups=finished)`.

#### `handlers.cmd_actual` (new) / `handlers.cmd_general` (updated)
- `cmd_actual`: provisional, title `"🏆 Clasificación provisional (a día de hoy):"`, calls `official=False`.
- `cmd_general`: official, title `"🏆 Clasificación general (oficial):"`, calls `official=True`. Appends a footer showing `📋 Grupos cerrados: N/12` and a hint to use `/actual` while the tournament is in progress.
- Old `cmd_porra` (group-only) removed. `/porra` routes to `cmd_actual` in `__main__.py`.

#### `cmd_start` help text updated
Shows `/actual`, `/general`, `/porra — alias de /actual`.

### Trade-offs considered

- **Why not always show official?** During the group stage users want to see how they stand *right now*, not just after every group closes. Provisional `/actual` satisfies that.
- **Calling `get_finished_groups()` twice in `cmd_general`**: once inside the engine (`official=True`), once in the handler for the footer. The TTLCache on `get_all_matches()` absorbs this — only one HTTP round-trip per command.
- **`compute_group_ranking` preserved**: not deleted from engine.py even though `cmd_porra` is gone. Other callers or future commands may use it. Cost is negligible.

### Tests added

- `TestGetFinishedGroups` (6 cases) — `test_api_client.py`
- `TestComputeGeneralRankingProvisional` (4 cases) + `TestComputeGeneralRankingOfficial` (7 cases) — `test_engine.py` (new file)
- `TestBuildAppRegistrations` (2 cases) — `test_handlers.py`

Total: 137 → 156 tests, all green.

---

---

## 6. Removal of Per-Stage Knockout Ranking Commands

**Date:** 2026-06-15T15:33+02:00  
**Author:** Kanté (Backend)  
**Approved by:** DrDonoso

### Context

The bot had five per-knockout-stage leaderboard commands (`/ronda32`, `/octavos`, `/cuartos`, `/semis`, `/final`) backed by `compute_knockout_ranking` + `StageRankEntry` in `engine.py` and `format_stage_ranking` in `formatters.py`.

These were redundant because:
- Knockout points already roll into `/general` (official) and `/actual` (provisional).
- `/listaaciertos` shows the per-stage breakdown for each participant.

### Decision

Remove the feature entirely. Deleted:

| Symbol | File | Reason |
|--------|------|--------|
| `cmd_ronda32`, `cmd_octavos`, `cmd_cuartos`, `cmd_semis`, `cmd_final` | `bot/handlers.py` | The 5 per-stage ranking handlers |
| `_cmd_knockout_stage` | `bot/handlers.py` | Shared helper, now orphaned |
| `format_stage_ranking` import | `bot/handlers.py` | Unused after handlers removed |
| `CommandHandler` registrations (×5) + imports | `__main__.py` | Registrations orphaned |
| `compute_knockout_ranking(stage, predictions, client)` | `porra/engine.py` | Called only by deleted handlers |
| `StageRankEntry` dataclass | `porra/engine.py` | Return type of deleted function |
| `format_stage_ranking(rows, stage_display)` | `bot/formatters.py` | Called only by deleted handlers |
| 5 command lines from `/start` help text | `bot/handlers.py` | Commands no longer exist |
| 5 rows from command table | `README.md` | Commands no longer exist |

### What Was Kept (critical — do not remove)

| Symbol | File | Reason |
|--------|------|--------|
| `score_knockout` | `porra/scoring.py` | **Scoring function** used by `compute_general_ranking` — feeds `/general` & `/actual`. Not the same as the removed `compute_knockout_ranking` (which was a ranking function). |
| `compute_general_ranking` | `porra/engine.py` | Powers `/general` and `/actual` |
| `compute_group_ranking` | `porra/engine.py` | Still available for potential future use |
| `compute_user_detail` | `porra/engine.py` | Powers `/listaaciertos` |
| `KNOCKOUT_STAGES` + escalating points | `data/stages.py` | Knockout scoring config unchanged |
| All `TestScoreKnockout*` tests | `tests/test_scoring.py` | `score_knockout` is still active |

### Key Distinction

`score_knockout` (scoring) ≠ `compute_knockout_ranking` (ranking).
- `score_knockout`: pure function, takes user picks + actual winners → returns points. Used by `compute_general_ranking` to compute total KO points per user.
- `compute_knockout_ranking`: orchestration function that called `score_knockout` internally and returned a per-stage sorted leaderboard. Only the ranking commands needed this — now gone.

### Verification

- 156 tests, all green.
- Smoke check: `removed gone: True` / `kept present: True`.
- Zero references to deleted symbols in `src/` or `tests/`.

---

## 7. Removal of /resultados Command

**Date:** 2026-06-15T15:47+02:00  
**Author:** Kanté (Backend Developer)  
**Requested by:** DrDonoso

### Decision

Remove the `/resultados` command entirely from the bot until the knockout phase begins.

### Rationale

- `/resultados` displays finished knockout-stage match results.
- The 2026 World Cup is still in the group phase — no knockout matches have been played yet.
- The command would always respond "No hay resultados de eliminatorias disponibles aún." with no useful information.
- This is consistent with the prior removal of the per-stage ranking commands (`/ronda32`, `/octavos`, `/cuartos`, `/semis`, `/final`), which were also premature for the current phase.

### What was removed

| Artifact | Change |
|---|---|
| `handlers.py` | Deleted `cmd_resultados` handler; removed `format_knockout_results` import |
| `__main__.py` | Removed `cmd_resultados` import and `CommandHandler("resultados", cmd_resultados)` |
| `formatters.py` | Deleted `format_knockout_results(matches, stages_display)` |
| `/start` help text | Removed `/resultados — resultados de eliminatorias` line |
| `README.md` | Removed `/resultados` row from command table |

### What was explicitly kept

The underlying data-fetching layer is **not removed** — it is still actively used by the `/general` and `/actual` scoring engine:

| Artifact | Why kept |
|---|---|
| `client.get_stage_results()` | Called by `engine._build_actual_winners()` → `compute_general_ranking()` |
| `client.get_knockout_results()` | Same call chain |
| `StageResult` dataclass | Return type of `get_stage_results` |
| `KNOCKOUT_STAGES` config | Used by scoring and by `/mispredicciones` display |
| All KO scoring/client tests | Still valid; functionality intact |

### Re-addition plan

When the knockout phase starts, restore `/resultados` by:
1. Re-adding `format_knockout_results` to `formatters.py`.
2. Re-adding `cmd_resultados` to `handlers.py` (importing the formatter).
3. Re-registering `CommandHandler("resultados", cmd_resultados)` in `__main__.py`.
4. Restoring the help line and README row.

The client methods and scoring logic will need zero changes.

---

## 8. Decision: /listaaciertos → official-only; /listaaciertosactual → provisional

**Date:** 2026-06-15  
**Author:** Kanté (Backend Developer)  
**Requested by:** DrDonoso

### Context

`/listaaciertos` previously scored from fully LIVE data (provisional), making it inconsistent with the `/general` vs `/actual` split that was already in place for the leaderboard commands. Users expected `/listaaciertos` to behave as an "official" view, symmetric with `/general`.

### Decision

- **`/listaaciertos`** is now **official**: only groups whose matches are ALL `FINISHED` count; only knockout stages whose matches are ALL `FINISHED` produce scored entries. Mirrors the behavior of `/general`.
- **`/listaaciertosactual`** is added as the **provisional** counterpart: identical to the old `/listaaciertos` behavior (live standings, all groups/stages included).

### Implementation

#### New API method: `client.get_finished_stages()`
Mirrors `get_finished_groups()`. Filters `get_all_matches()` to KNOCKOUT_STAGES api names and returns the subset where every match has `status == "FINISHED"`. Reuses the TTL-cached matches call — no extra HTTP round-trip.

#### Engine: `compute_user_detail(official: bool = False)`
New kwarg mirrors `compute_general_ranking(official=False)`.

- `official=False` (default): unchanged live behavior — all groups/stages included.
- `official=True`:
  - Groups: `_build_actual_standings(client, only_groups=finished_groups)` — unclosed groups absent from standings → `score_groups` returns `"no_data"` (⏳ 0).
  - Knockout: only `finished_stages` entries included in both `actual_winners` and the user's filtered `user_ko` dict. Unfinished stages produce empty picks → no detail entries (no ❌ for pending rounds).
  - New keys in returned dict: `"official"`, `"finished_groups"` (int or None), `"total_groups"` (12).

#### Formatter: `format_user_detail`
- Title now reads "oficial" or "provisional, a día de hoy" depending on `detail["official"]`.
- Footer: official mode shows `📋 Grupos cerrados: N/12` when not all groups are closed, plus hint to use `/listaaciertosactual`. Provisional mode appends a one-liner hint pointing to `/listaaciertos` for the official view.

#### Handlers
Shared private helper `_send_user_detail(update, context, *, official)` to avoid duplication. `cmd_lista_aciertos` calls it with `official=True`; `cmd_lista_aciertos_actual` with `official=False`.

#### Registration
`CommandHandler("listaaciertosactual", cmd_lista_aciertos_actual)` added to `build_app()`.

### Alternatives considered

- **Keep `/listaaciertos` as provisional, add `/listaaciertosoficial`** — rejected; the user wants the default (shorter) command to be authoritative/official, consistent with `/general`.
- **Single command with a flag argument** — rejected; command-per-mode is simpler for end users and consistent with the `/general` vs `/actual` design.

### Tests added (31 new, 187 total)

| Class | File | Count |
|---|---|---|
| `TestGetFinishedStages` | `test_api_client.py` | 6 |
| `TestComputeUserDetailProvisional` | `test_engine.py` | 8 |
| `TestComputeUserDetailOfficial` | `test_engine.py` | 9 |
| `TestBuildAppRegistrations` (extended) | `test_handlers.py` | 1 |
| `TestCmdListaAciertosOfficial` | `test_handlers.py` | 2 |
| `TestCmdListaAciertosActual` | `test_handlers.py` | 5 |

---

## 2. Shared Process-Wide API Cache — Kante

**Date:** 2026-06-15  
**Author:** Kanté  
**Status:** Implemented

### Context

football-data.org free tier allows 10 requests/minute. The bot was receiving HTTP 429 errors even though `api/cache.py` defined a 60-second `TTLCache`. DrDonoso reported hitting rate limits during group-stage commands with ~12 active users.

### Root Cause

`bot/handlers.py:make_client(settings)` built a **new** `FootballDataClient` on every incoming Telegram command. The `FootballDataClient` constructor had:

```python
self._cache = cache or TTLCache(ttl=60)
```

With no `cache` argument passed, each client instance received its own fresh empty `TTLCache`. The module-level `_default_cache = TTLCache(ttl=60)` in `api/cache.py` was never injected anywhere — dead code. The 60-second TTL only deduplicated calls within a single command invocation. Across commands and users, every command independently re-fetched `/competitions/WC/standings` and `/competitions/WC/matches`, easily exceeding the 10 req/min limit.

### Decision

Make the `TTLCache` a **process-wide shared singleton**, injected into every `FootballDataClient` via `make_client`. This is minimal, low-risk, and requires no retry logic or async coordination.

### Changes

| File | Change |
|------|--------|
| `api/cache.py` | `_default_cache` changed to lazy-init global (`None`); added `get_default_cache(ttl)` and `reset_default_cache(ttl)` |
| `config.py` | Added `football_cache_ttl: float = 60.0` to `Settings`; reads `FOOTBALL_CACHE_TTL` env var |
| `bot/handlers.py` | `make_client` passes `cache=get_default_cache(ttl=settings.football_cache_ttl)` |
| `api/client.py` | HTTP 429 handler now logs `WARNING` with URL + `Retry-After` header |
| `tests/conftest.py` | `reset_api_default_cache` autouse fixture prevents cross-test singleton bleed |

### Rationale

- **Shared singleton**: all commands (from any user) hit the same TTL window. Each distinct URL (standings, matches) fetches the network at most once per 60 seconds regardless of concurrency.  
- **Lazy init with `get_default_cache(ttl)`**: the first `make_client` call initialises the singleton with the configured TTL; subsequent calls return the same instance. Clean, testable, no global mutable state visible outside the module.  
- **Client ctor default preserved** (`cache or TTLCache(...)`): unit tests that construct `FootballDataClient` directly still get an isolated cache — no test pollution.  
- **No retry/backoff loops**: these would block the async event loop. The fix prevents the 429 from occurring rather than recovering from it.

### Alternatives Considered

- **Thread-local cache**: rejected — would not deduplicate across concurrent users hitting the same endpoint in the same TTL window.  
- **Redis/external cache**: rejected — adds infrastructure dependency unnecessary for a single-process bot.  
- **Rate-limiting middleware**: rejected — adds complexity and doesn't address the root cause (too many distinct client instances).

---

## 3. Football-day rolling window for /hoy and /ayer

**Date:** 2026-06-15T16:21+02:00  
**Author:** Kante (Backend Developer)  
**Requested by:** DrDonoso  
**Status:** Implemented

### Context

WC2026 is hosted in North America. Many matches kick off late at night or early morning CEST, which means a natural calendar-day boundary (midnight) splits a single matchday awkwardly — e.g. a 02:00 CEST match on June 16 logically belongs to "June 15's matchday" for a Madrid viewer.

### Decision

Implement a **"football day"** concept: a rolling 24-hour window anchored at 09:00 local time (configurable) instead of a calendar day.

#### Window definition

- `now_local` = current time in `settings.timezone` (default `Europe/Madrid`).
- Build `naive_anchor = now_local.date() @ anchor_hour:00`.
- `anchor = local_tz.localize(naive_anchor)` (pytz, DST-safe).
- `start = anchor if now_local >= anchor else anchor - 1 day`.
- `end = start + 24h`.
- `/hoy` → day_offset=0 → `[start, end)`.
- `/ayer` → day_offset=-1 → `[start-1d, start)`.
- Comparison done in UTC after `.astimezone(timezone.utc)`.

### Implementation

#### config.py
- Added `football_day_start_hour: int = 9` to `Settings`.
- `load_settings()` reads `FOOTBALL_DAY_START_HOUR` env var (default `"9"`).

#### api/client.py
- Added `timedelta` to datetime imports.
- Added `_football_day_bounds(tz_name, day_offset, anchor_hour)` private helper.
- Added `get_football_day_matches(tz_name, day_offset, anchor_hour)` public method.
- **Deleted** `get_today_matches` (calendar-day semantics). No tests referenced it.

#### bot/handlers.py
- `cmd_hoy`: now calls `get_football_day_matches(settings.timezone, 0, h)`. Header: `⚽️ Partidos de hoy (09:00–09:00):` (configured hour).
- Added `cmd_ayer`: calls `get_football_day_matches(settings.timezone, -1, h)`. Header: `📅 Resultados de ayer (09:00–09:00):`.
- `/start` help text updated.

#### __main__.py
- Imported `cmd_ayer`.
- Registered `CommandHandler("ayer", cmd_ayer)` next to `"hoy"`.

#### Tests
- `test_config.py`: 4 new tests for `football_day_start_hour` (default + env override, Settings + load_settings).
- `test_api_client.py`: `TestGetFootballDayMatches` — 13 new tests covering inside/outside window, rolling rule (02:00 case), day_offset=-1, sorting, empty.

#### README.md
- Updated `/hoy` command description.
- Added `/ayer` command row.
- Added "Football-day window" section documenting the 09:00→09:00 window and env vars.

#### .env.example
- Added commented `FOOTBALL_CACHE_TTL=60` and `FOOTBALL_DAY_START_HOUR=9` lines to the optional-vars block.

### Note for Maldini

The `.env.example` was updated to add `FOOTBALL_DAY_START_HOUR=9` (commented, optional) in the existing optional-vars block. Maldini should be aware of this new env var when updating Dockerfile / docker-compose docs or CI environment templates.

### Test results

212 tests, all green (196 pre-existing + 16 new).

---

---

## 9. Decision: /clasificacion optional group letter argument

**Date:** 2026-06-15T16:34+02:00  
**Author:** Kanté (backend)  
**Requested by:** DrDonoso

### Context

`/clasificacion` previously always returned all 12 group standings in one message, which is verbose. Users often only care about a specific group.

### Decision

`/clasificacion` now accepts an optional A–L letter (case-insensitive):

- **No arg** → unchanged: all 12 groups via `format_standings(standings, live_tlas=...)`.
- **`/clasificacion L`** (or `/clasificacion l`) → filters `standings` to `GROUP_L` before passing to `format_standings`. Works with any position in args so `/clasificacion grupo L` also works.
- **Invalid letter** (e.g. `Z`, `foo`) → friendly Spanish error: `"Grupo no válido. Indica una letra de la A a la L, por ejemplo: /clasificacion L"` — no API call made.
- **Valid letter but no data** → `"No hay clasificación disponible para el Grupo {letter} todavía."`.

### Implementation

- **`handlers.py`** (`cmd_clasificacion`): loop over `context.args`, find first token where `token.strip().upper() in GROUPS` and `len == 1`. Filter applied *after* the `try/except` API block.
- **`format_standings`** unchanged — passing a single-group list produces a single-group output naturally.
- **`/start` help text** updated: `/clasificacion [grupo] — clasificación de grupos (ej: /clasificacion L)`.
- **README.md** command table updated.

### Tests added (`TestCmdClasificacion`, 5 cases)

1. No arg → output contains both `"Grupo A"` and `"Grupo L"`.
2. Uppercase `L` → only `"Grupo L"` in output, `"Grupo A"` absent.
3. Lowercase `l` → same as uppercase.
4. Invalid args (`Z`, `foo`, `12`) → friendly error, `get_standings` not called.
5. Valid letter with no data → "no disponible todavía" message.

### Alternatives considered

- Factoring out a `_parse_group_arg` pure helper for isolated unit tests — decided against since the handler logic is simple enough to test directly with mocked `make_client`.

---

---

## 10. Decision: /actual & /general send top-3 photo album

**Date:** 2026-06-15T16:52+02:00  
**Author:** Kanté (backend)  
**Requested by:** DrDonoso

---

## What changed

`/actual` (`/porra`) and `/general` now send a Telegram **photo album** (`sendMediaGroup`) containing the photos of the **top-3 ranked participants** instead of a single hardcoded winner photo.

---

## Decisions made

### Photo URL scheme
- Base URL: `{PHOTO_BASE_URL}/{username}.png` — where `username` is the **lowercase predictions.yml key** (e.g. `crispavon`, `dsantosmerino`, `pilarfreixas`).
- Default base: `http://victorsaez.cat` (no trailing slash).
- Filenames **must match lowercase usernames exactly** — case-sensitive on the server.

### URL validation before sending
Each candidate URL is validated with `requests.get(url, timeout=4, stream=True)` before building the album:
- Must return HTTP 200 AND `Content-Type: image/*`.
- Network errors or non-image responses: skip that URL silently (log nothing — it's routine).
- Order preserved (1st, 2nd, 3rd place).
- Rationale: `sendMediaGroup` fails atomically on a bad URL; pre-validation keeps the album clean.

### Caption placement
- Ranking text goes as `caption` on the **first** `InputMediaPhoto` only (Telegram shows it for the whole album).
- Caption truncated at 1024 chars if needed; if truncated, full text sent as a follow-up `reply_text`.

### Fallback strategy
- 0 valid images → `reply_text(text)` (plain text).
- `send_media_group` raises → `log.warning` + `reply_text(text)` fallback.

### Text-only change: `format_general_ranking`
Return type changed from `tuple[str, str | None]` to `str`. The photo URL was the only tuple item removed; the leader/tie text line is unchanged. All callers updated.

### Shared helper
`_send_ranking_with_top3_photos(update, context, text, rows, settings)` is a private async helper shared by both `cmd_actual` and `cmd_general`. Both handlers pre-build the full `text` (including cmd_general's footer) and pass it to the helper, which owns all photo logic.

### `photo_base_url` setting
Added `photo_base_url: str = "http://victorsaez.cat"` to `Settings`, loaded from env `PHOTO_BASE_URL`. Mirrors the `football_cache_ttl`/`football_day_start_hour` pattern (dataclass field + `os.getenv` in `load_settings()`).

---

## Note for Maldini (infra/Docker)

`.env.example` now includes a commented optional line:

```
# PHOTO_BASE_URL=http://victorsaez.cat
```

No Docker rebuild is required — the default is baked in. If the photo host changes, set `PHOTO_BASE_URL` in the `.env` on the server and restart the container (no image rebuild needed).

---

## Files changed

| File | Change |
|------|--------|
| `src/worldcup_bot/config.py` | Added `photo_base_url` field + `PHOTO_BASE_URL` env read |
| `src/worldcup_bot/bot/formatters.py` | Added `participant_photo_url(username, base_url)`; `format_general_ranking` returns `str` |
| `src/worldcup_bot/bot/handlers.py` | Added `_send_ranking_with_top3_photos`; updated `cmd_actual`, `cmd_general` |
| `tests/test_config.py` | 4 new tests for `photo_base_url` |
| `tests/test_handlers.py` | 22 new tests (`TestParticipantPhotoUrl`, `TestSendRankingWithTop3Photos`, `TestCmdActual`, `TestCmdGeneral`) |
| `.env.example` | Added `# PHOTO_BASE_URL=http://victorsaez.cat` |
| `README.md` | Documented ranking photo album + `PHOTO_BASE_URL` env var |
| `.squad/agents/kante/history.md` | Learning appended |

---

## 11. Decision: "Ver gol" inline button — clip finder + multi-host downloader

**Date:** 2026-06-16T09:45+02:00  
**Author:** Kanté  
**Status:** Implemented  

### Context

Users requested that the "Ver gol" inline button (shown on each goal notification) actually
fetches and sends the goal video clip instead of showing a placeholder toast.

### Design

#### A — Clip finder (`reddit/clip_finder.py`)

- `find_goal_clip(scanner, home_team, away_team, home_score, away_score, scorer, minute) -> str | None`
- Searches r/soccer via JSON endpoint (q=`home away`, restrict_sr, sort=new, t=day, limit=100) with HTML fallback.
- Parses each post title with `GOAL_TITLE_PATTERN` (ported from the proven RedditSoccerGoals repo).
- Match criteria: fuzzy team names (reuses `_teams_match` from scanner.py) + exact scoreline + (scorer fuzzy OR minute ±2).
- Returns the first matching post's external media URL, or `None`.
- **Synchronous** — callers wrap in `await asyncio.to_thread(find_goal_clip, ...)`.

#### B — Downloader (`reddit/downloader.py`)

`MediaDownloader` with host-specific resolvers, all using `requests` (sync) in `asyncio.to_thread`:

| Host | Strategy |
|------|----------|
| streamff.link / streamff.com | CDN id → `cdn.streamff.one/{id}.mp4`, else page scrape |
| streamin.link / streamin.me | CDN id → `c-cdn.streamin.top/uploads/{id}.mp4`, else embed scrape |
| streamain.com | Embed page scrape → `cdn.streamain.com/*.mp4` |
| v.redd.it, streamable.com, dubz.link, unknown | **yt-dlp subprocess fallback** |

Writes to system temp dir (`tempfile.gettempdir()`).

#### C — Video helpers (`reddit/video.py`)

- `probe_video(path) -> dict` — ffprobe JSON → `{width, height, duration}`.  
  **Without width/height Telegram renders video square.** This is the key fix.
- `compress_if_needed(path) -> Path` — returns original if ≤ 50 MB; ffmpeg two-pass bitrate re-encode otherwise.  
  Raises `VideoTooLargeError` if duration unknown, required bitrate < 200 kbps, ffmpeg fails, or ffmpeg times out.

#### D — Callback data / token

- `build_goal_keyboard(token: str)` — token = `hashlib.sha1(event.key)[:12]` (12 hex chars; well within 64-byte limit).
- Token → `bot_data["goal_clips"][token]` dict (in-memory, lost on restart — **acceptable for v1**).
  A future v2 could persist to SQLite.

#### E — Handler flow (`cmd_ver_gol_callback`)

1. Parse token from `query.data`.
2. Look up goal context; unknown token → alert, return.
3. Concurrency guard: "sending" → toast; "sent" → toast; else set "sending".
4. `query.answer("⏳ Buscando…")` (single answer call allowed by Telegram).
5. `find_goal_clip` via `asyncio.to_thread`.
6. `MediaDownloader.download(media_url)`.
7. `compress_if_needed(path)`.
8. `probe_video(send_path)` → `bot.send_video(**meta)`.
9. On success: `status="sent"`, `query.edit_message_reply_markup(None)` removes keyboard.
10. On any failure: `status="pending"` (allow retry), send error message, keep keyboard.
11. `finally`: unlink temp files.

### Dependencies introduced

| Dependency | Rationale |
|-----------|-----------|
| `yt-dlp>=2024.0` (added to `pyproject.toml`) | Subprocess fallback downloader for unsupported hosts |
| `ffprobe` (system binary) | Video dimension probe — prevents square video in Telegram |
| `ffmpeg` (system binary) | Video compression for files > 50 MB |

### Tests

72 new tests (407 total, all green):
- `tests/test_clip_finder.py` — GOAL_TITLE_PATTERN, URL extraction, _match_post (7 cases), find_goal_clip (6 cases), _parse_clip_posts_html.
- `tests/test_downloader.py` — CDN URL resolution for streamff + streamin, streamain embed scrape, yt-dlp fallback paths.
- `tests/test_video.py` — probe_video (5 cases), compress_if_needed (6 cases).
- `tests/test_handlers.py` — TestGoalToken (3), TestCmdVerGolCallback (8 cases: unknown token, concurrency guards, clip not found, download failure, happy path with correct meta, reply_to_message_id).

---

## 12. Decision: Reddit HTML Fallback Hardening (JSON 403 from Datacenter IPs)

**Author:** Kanté (Backend Developer)
**Date:** 2026-06-16T10:05+02:00
**Status:** IMPLEMENTED

### Context

The "Ver gol" download pipeline was confirmed working (17 MB, 1920×1080, ffprobe dims correct). However the Reddit READ path was fragile: `old.reddit.com` JSON endpoints (`/.../.json`, `/r/soccer/search.json`) return **HTTP 403** from datacenter/corporate IPs including the user's production LXC. The existing HTML fallback in `get_thread_body` returned only 1363 chars (0 goals parsed) and `find_goal_clip` had no HTML search fallback at all.

### Diagnosis

Measured inside the running Docker container:

| Endpoint | Status | Notes |
|---|---|---|
| `old.reddit.com/.../.json` | **403** | Blocked from datacenter IPs |
| `old.reddit.com/r/soccer/search.json` | **403** | Blocked from datacenter IPs |
| `old.reddit.com/...thread.../` (HTML) | **200** | 681 KB, contains goals |
| `old.reddit.com/r/soccer/search?q=...` (HTML) | **200** | Contains clip posts |

The match-thread HTML has **no `data-selftext`** attribute. Goals are rendered as:
```html
<p><strong>7&#39;</strong> ⚽ <strong>Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) right footed shot...</strong></p>
```

The old `_MD_DIV_RE` (non-greedy `.*?`) stopped at the first `</div>` inside the post body, capturing only 1363 chars. There are 181 `class="md"` divs (post + every comment).

The search results HTML (`/r/soccer/search?q=...`) uses a completely different structure from `/new/` listing pages: the external clip URL is in a footer anchor `<a class="search-link" href="https://streamin.link/v/...">` — there is **no `data-url` attribute**.

### Decisions

#### 1. `get_thread_body` HTML fallback (`scanner.py`)

**Remove** `_MD_DIV_RE`. **Add** `_html_to_goaltext(html)`:
- `<strong>`/`</strong>`/`<b>`/`</b>` → `**` (bold markers for parse_goal_events)
- `</p>`/`<br>`/`</tr>`/`</li>` → `\n` (one event per line)
- Strip all remaining HTML tags
- `html.unescape()` (converts `&#39;` → `'`, `&amp;` → `&`, etc.)
- Collapse 3+ newlines to 2

**Update** `_fetch_thread_body_html`:
1. Try `data-selftext` attribute first (legacy/non-match threads may have it)
2. Cut HTML at `<div class="commentarea"` → excludes comment-section Goal! lines
3. Apply `_html_to_goaltext` to pre-commentarea HTML

Result: `**7'** ⚽ **Goal! Sweden 1, Tunisia 0. Yasin Ayari (Sweden) right footed shot...**` which `parse_goal_events` handles normally.

#### 2. `find_goal_clip` HTML search fallback (`clip_finder.py`)

**Add** `_REDDIT_SEARCH_HTML` endpoint: `https://old.reddit.com/r/soccer/search?q={query}&restrict_sr=on&sort=new&include_over_18=on`

**Add** `_parse_search_results_html(html)`:
- Splits by `data-fullname="t3_"` blocks
- Extracts title from `<a class="search-title ...">Title</a>`
- Extracts external media URL from `<a class="search-link ..." href="https://streamin.link/v/...">` footer anchor
- Skips blocks without `search-title` (to avoid false positives on listing-format pages)

**Updated fallback chain** in `find_goal_clip`:
1. JSON search (`search.json?q=...`) — skip on 403
2. **HTML search** (`search?q=...`) — new, parses `search-link` footer URLs
3. `/new/` HTML listing — existing last resort

### Results

E2E inside container: **10 OK | 0 fallos | 0 sin clip**
- **Sweden vs Tunisia** (1u62p01): 6 goals parsed from HTML; 6 clips downloaded (streamin.link, 1920×1080, 17–20 MB)
- **Netherlands vs Japan** (1u5uc8w): 4 goals parsed; 4 clips downloaded (streamin.link + streamff.link)

Unit tests: 420 total, all green (+13 new).

---

## 13. Decision: ffmpeg shipped in the drdonoso/worldcup2026 image

**Date:** 2026-06-16  
**Author:** Maldini (DevOps agent)  
**Status:** Applied

### Context

The "Ver gol" feature (goal-clip download + Telegram delivery) requires `ffmpeg` and `ffprobe` as system binaries inside the container. `ffmpeg` is available in Debian's package repos (`ffmpeg` package ships both binaries). The Python `yt-dlp` library (which calls `ffmpeg`/`ffprobe` internally) is added to `pyproject.toml` by Kanté and installed via the existing `pip install .` layer.

### Decision

Add a single `RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*` layer to the Dockerfile, placed immediately after `FROM python:3.12-slim AS base` and before any user-creation or `COPY`/pip steps.

### Rationale

- **Cache efficiency:** System deps (apt) change far less often than Python deps. Placing the apt layer first means Python dep changes (e.g., adding `yt-dlp` to `pyproject.toml`) do not invalidate the apt cache layer.
- **Minimal image surface:** `--no-install-recommends` keeps image size small; cleanup of apt lists reclaims ~20 MB.
- **No new mounts or env vars:** `/tmp` is world-writable in debian-slim by default, so the non-root `app` user can write temporary video files without any extra Docker configuration.
- **Mirrors sibling repo:** `Z:/Repos/Personal/RedditSoccerGoals/Dockerfile` uses the identical pattern (ffmpeg via apt, yt-dlp via pip/pyproject).

### Verification

```
ffmpeg version 7.1.4-0+deb13u1 Copyright (c) 2000-2026 the FFmpeg developers
ffprobe version 7.1.4-0+deb13u1 Copyright (c) 2007-2026 the FFmpeg developers
yt-dlp: not yet in image (pending Kanté's pyproject.toml change)
```

Build: `docker compose -f docker-compose.local.yml build` → exit 0.

---

---

## 14. Decision: OpenAI-Compatible AI Integration + Daily 9 AM Spanish Recap

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T13:45+02:00  
**Status:** IMPLEMENTED  
**Phase:** 21

### Summary

Added an optional OpenAI-compatible AI integration that calls a self-hosted LiteLLM instance. When configured, a daily job at 9:00 AM local time posts a short Spanish recap to the Telegram group: yesterday's results, today's fixtures, plus historical/armed-conflict curiosities between the competing nations. A hidden `/updatediario` command allows manual testing without waiting for 9 AM.

### Env Vars for Maldini (wire into compose + .env.example)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | When feature enabled | — | API key for LiteLLM/OpenAI endpoint |
| `OPENAI_BASE_URL` | When feature enabled | — | Base URL of the LiteLLM OpenAI-compatible endpoint (e.g. `https://litellm.example/v1`) |
| `OPENAI_MODEL` | When feature enabled | — | Model name to pass to the completions API |
| `DAILY_UPDATE_HOUR` | No | `9` | Local hour (0–23) for the daily recap post |

**Feature self-disables** when any of the three OPENAI_* vars is absent/empty — the bot still starts and logs: `Daily AI update DISABLED — set OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL to enable.`

### Architecture Notes

- Uses official `openai>=1.40` SDK with `AsyncOpenAI(api_key=..., base_url=...)` — LiteLLM is OpenAI-compatible so pointing `base_url` at it is the standard pattern.
- `src/worldcup_bot/ai/` package — **NOT** named `openai` (would clash with SDK import).
  - `ai/client.py` — `AIClient` wraps `AsyncOpenAI`; injectable `_client` param for tests; raises `AIError` on failure.
  - `ai/daily_update.py` — `build_messages()` (pure function, testable), `generate_daily_update()` (orchestrator).
- `ai_enabled(settings) -> bool` in `config.py` — checks all three OPENAI_* non-empty.
- `daily_update_job` in `__main__.py` — swallows exceptions (never crashes the process, never spams the group).
- `/updatediario` in `handlers.py` — hidden from `/start` help, like `/simulagol`.

### Dependency Added

```toml
"openai>=1.40"
```
added to `pyproject.toml` `dependencies`.

### Files Changed

- `pyproject.toml` — `openai>=1.40` dependency
- `src/worldcup_bot/config.py` — 4 new fields + `ai_enabled()` function
- `src/worldcup_bot/ai/__init__.py` *(new)*
- `src/worldcup_bot/ai/client.py` *(new)*
- `src/worldcup_bot/ai/daily_update.py` *(new)*
- `src/worldcup_bot/bot/handlers.py` — `cmd_update_diario` + imports
- `src/worldcup_bot/__main__.py` — `daily_update_job` + scheduling + handler registration
- `tests/test_ai.py` *(new)* — 36 tests, all mocked

---

## 15. Decision: /simulagol picks a random WC goal from finished fixtures

**Date:** 2026-06-16T11:01+02:00  
**Agent:** Kanté  
**Status:** Implemented

### Context

`/simulagol` previously always fired the exact same fixed goal (Sweden 3-1 Tunisia, Gyökeres 60'). Useful for E2E testing, but limited: it always tested the same clip/scoreline and gave no variety.

### Decision

Make `/simulagol` pick a **random goal from any FINISHED WC match**. Keep the fixed Sweden-Tunisia goal as an infallible fallback.

### Implementation

#### New: `RedditMatchScanner.find_match_thread(home_name, away_name) -> str | None`

Queries `old.reddit.com/r/soccer/search?q=match+thread+{home}+{away}&t=week` via the existing session (browser headers + over18 cookie). Parses results using **`_SEARCH_RESULT_LINK_RE`** — a regex targeting `class="search-title"` links — because search-results pages use a completely different HTML structure from `/r/soccer/new/` (no `data-fullname`/`data-timestamp`/`data-permalink` attributes, no `class="title"` links). Filters by `_is_match_thread` (excludes Pre/Post) and `_teams_match` (both team-order directions). Resilient: wrapped in try/except, returns None on any failure.

#### New: `_pick_random_goal(client, scanner, max_candidates=6) -> (GoalEvent, str, str) | None`

Sync helper called from `cmd_simula_gol` via `asyncio.to_thread`. Algorithm:
1. `client.get_all_matches()` → filter `status == "FINISHED"` → shuffle
2. For each of up to 6 candidates: `scanner.find_match_thread(...)` → `scanner.get_thread_body(...)` → `parse_goal_events(...)` → `random.choice(goals)`
3. Align TLAs to the API fixture (handles title home/away reversal)
4. Return first `(goal, home_tla, away_tla)` or None

#### Updated: `cmd_simula_gol`

- Sends `"⏳ Eligiendo un gol al azar del Mundial…"` first (UX)
- Runs `_pick_random_goal` in a thread
- Falls back to fixed Sweden-Tunisia goal if pick fails
- Stores in `bot_data["goal_clips"]` with identical shape — `cmd_ver_gol_callback` unchanged

### Key Discovery

Reddit's **search results page** (`/r/soccer/search?...`) returns HTML with links structured as:
```html
<a href="https://old.reddit.com/r/soccer/comments/[id]/[slug]/" class="search-title may-blank">Title</a>
```
This is **completely different** from `/r/soccer/new/` which uses `data-fullname`, `data-timestamp`, `data-permalink` attributes and `class="title"` links. The existing `_parse_html_posts` function only works for listing pages, not search pages. New `_SEARCH_RESULT_LINK_RE` constant added to handle this.

### Alternatives Considered

- **Use Reddit JSON search**: 403 in datacenter (known issue; already worked around elsewhere)
- **Hardcode thread IDs**: Brittle, doesn't scale
- **Use football-data match IDs for lookup**: football-data doesn't include Reddit links

### Tests Added (17 new, all green — 443 total)

- `TestFindMatchThread` (7 tests): canned search-result HTML, pre/post exclusion, None on error, reversed team order, different fixture
- `TestCmdSimulaGolRandomPath` (5 tests): mock client + scanner, correct goal stored, TLA alignment, fallback on missing thread/no goals/no finished matches
- `TestPickRandomGoal` (4 tests): unit tests for the sync helper

### Live Verification

3 different random WC goals from real Reddit threads (inside container, real Reddit 403 env):
- Côte d'Ivoire 1-0 Ecuador | Amad Diallo 90' | TLA: CIV/ECU  
- Saudi Arabia 1-1 Uruguay | Maxi Araújo 80' | TLA: KSA/URY  
- Sweden 2-0 Tunisia | Alexander Isak 30' | TLA: SWE/TUN

---

## 16. Decision: TELEGRAM_GROUP_ID is now a required setting

**Author:** Kante (Backend)  
**Date:** 2026-06-16T12:24+02:00  
**Status:** IMPLEMENTED  

### Context

The goal notifier (`poll_goals_job` in `__main__.py`) calls `context.bot.send_message(chat_id=settings.telegram_group_id, ...)` on every goal event. If `TELEGRAM_GROUP_ID` is not set the bot starts without error but silently fails to send any notifications — a confusing silent failure mode.

### Decision

`load_settings()` now validates `TELEGRAM_GROUP_ID` with the same fail-fast pattern used for `TELEGRAM_BOT_TOKEN` and `FOOTBALL_DATA_API_KEY`:

```python
group_id = os.getenv("TELEGRAM_GROUP_ID", "")
if not group_id:
    raise RuntimeError(
        "❌ TELEGRAM_GROUP_ID is not set. "
        "It is required for live goal notifications. "
        "Set it in the environment or in .env before starting the bot."
    )
```

The `Settings` dataclass field default (`telegram_group_id: str | None = None`) is **intentionally kept** to avoid breaking the many unit tests that construct `Settings(...)` directly without a group id.

### Consequences

- `__main__.py`: The `if settings.telegram_group_id` / `else` conditional around `job_queue.run_repeating` is removed — the job is always scheduled because the group id is guaranteed by the time `main()` runs.
- The "Goal notifier DISABLED" warning branch is dead code and has been removed.
- Operators must set `TELEGRAM_GROUP_ID` before starting the bot. Maldini is updating `docker-compose.yml` and `.env.example` in parallel.
- 473 tests green.

---

## 17. Decision: /simulagol test command

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T10:48+02:00  
**Status:** IMPLEMENTED  
**Requested by:** DrDonoso

### Context

There are no live WC2026 matches right now, so `poll_goals_job` never fires a goal notification. This makes it impossible to test the "Ver gol" inline button flow end-to-end in the real Telegram group.

### Decision

Added `/simulagol` — a small utility command that fires a **real goal notification** with a known-good clip (Sweden 3-1 Tunisia, Viktor Gyökeres 60') and stores full goal context in `bot_data["goal_clips"]`, so the "Ver gol" button can be tapped and the full flow (find clip → download → send video → remove keyboard) is exercised without any live match.

### Implementation

- `cmd_simula_gol` in `src/worldcup_bot/bot/handlers.py`:
  - Builds a `GoalEvent` with fixed data (home=Sweden, away=Tunisia, hs=3, as=1, scorer=Viktor Gyökeres, minute=60').
  - Token = `_goal_token("SIM:sweden-tunisia-3-1-60-gyokeres")` — stable across restarts.
  - Stores EXACTLY the same dict shape that `poll_goals_job` stores (home_team, away_team, home_score, away_score, scorer, minute_text, scoring_team, home_tla, away_tla, status="pending").
  - Calls `format_goal_notification` + `build_goal_keyboard` and replies with `🧪 [SIMULACIÓN]\n<text>` + inline keyboard in the CURRENT chat.
  - Logs at INFO.
- `src/worldcup_bot/__main__.py`: `CommandHandler("simulagol", cmd_simula_gol)` registered.
- `/start` help text updated.
- 6 new tests in `tests/test_handlers.py` (`TestCmdSimulaGol`). 426 total, all green.

### Future Options

- **Make admin-only**: add a check `update.effective_user.id in settings.admin_ids` and reply with an error for non-admins. Useful if deployed in a public group.
- **Remove**: once live WC matches are happening regularly and the flow has been validated in production.
- **Parameterise**: accept optional team/scorer/minute args to test different scenarios.

The command is intentionally left without an admin gate for now (harmless test utility in a private group context), but this should be revisited if the bot is ever opened to a larger audience.

---

## 18. Decision: Gender-aware /tongo phrase via gender-guesser

**Date:** 2026-06-16T12:54+02:00
**Author:** Kante (Backend)
**Status:** Implemented

### Context

The `/tongo` command returns a random sarcastic phrase (2/3 chance) or "Sanchez ens roba" (1/3 chance). DrDonoso requested a new phrase that adapts its grammatical gender to the user who triggers the command: *"Que tongo ni que tongo, eres mas pesad_ que un_ argentin_."*

### Problem

Telegram's `User` object does **not** include a gender field. The only available name data is `first_name`, `last_name`, and `username`. To infer gender from `first_name` we need an external name database.

### Decision

**Use `gender-guesser` (PyPI, pure Python, offline name database).** Added as a production dependency (`gender-guesser>=0.4`).

- Inference is done in `worldcup_bot.data.gender.infer_gender(first_name)`.
- Returns `'f'` for `female` / `mostly_female`; `'m'` for everything else (male, mostly_male, andy, unknown, None, empty).
- Default to male (`'m'`) is intentional: it minimises misgendering in the unknown/ambiguous case for a bot where the user base is mostly male.
- The dynamic phrase is added to the 2/3 random candidate pool at runtime (`candidatas = FRASES + [frase_argentino(gender)]`). It is NOT a static string in `FRASES`, so it never inflates the static list count.

### Alternatives Considered

| Option | Rejected because |
|--------|-----------------|
| Ask user to set their gender in bot | Unnecessary friction for a joke command |
| Use Telegram username heuristics | Usernames are often handles, not names; low accuracy |
| External gender API (e.g., genderize.io) | Network dependency; privacy concern; offline DB is sufficient |
| Hard-code gender per known participant | Not scalable; bot can run for unknown users |

### Consequences

- New production dependency: `gender-guesser>=0.4` (pure Python, ~200 KB, offline). Added to `pyproject.toml` and rebuilt Docker image.
- Inference accuracy is "good enough" for a joke command. Ambiguous/unknown names → male (silent fallback, no error).
- `gender.py` module is independent and unit-tested; easy to swap the backend if needed.
- The 1/3 `SANCHEZ_ENS_ROBA` guarantee is fully preserved (dynamic phrase is only in the 2/3 pool).

---

## 19. Decision: /tongo GIF pool (mounted hot-reload)

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T13:05+02:00  
**Status:** IMPLEMENTED

### Context

DrDonoso requested that `/tongo` be able to send GIFs (and short MP4s) mixed into the same random pool as the existing phrases, so that taunting responses can be animated. Storage must reuse the existing `./data:/app/data:ro` Docker volume so files can be dropped on the server without a rebuild.

### Decision

#### Storage
GIFs live in `data/tongo_gifs/` on the host, mounted at `/app/data/tongo_gifs/` in the container via the existing `./data:/app/data:ro` bind-mount. The folder is committed with a `.gitkeep` so the mount target exists in the image even when empty. The folder is **not** git-ignored so users can optionally version "factory" GIFs.

#### Directory resolution (in order)
1. If `Settings.tongo_gifs_dir` is set (env `TONGO_GIFS_DIR`), use it directly.
2. Otherwise derive `Path(settings.predictions_path).parent / "tongo_gifs"` — mirrors predictions.yml location in both local (`data/`) and container (`/app/data/`) contexts.

#### Pool mixing
```
pool = FRASES + [frase_argentino(gender)] + gifs   # gifs = list[Path]
choice = random.choice(pool)
isinstance(choice, Path) → send_animation   else → reply_text
```
Each GIF has the same individual probability weight as each phrase. Adding more GIFs increases the GIF fraction of the 2/3 block proportionally. `SANCHEZ_ENS_ROBA` is unaffected (early-return at 1/3).

#### Hot-reload
`list_tongo_gifs(gifs_dir)` is called fresh on every `/tongo`. Adding or removing a file on the server is reflected on the next invocation without restart.

#### Graceful degradation
If `send_animation` raises (bad file, Telegram error), a warning is logged and a fallback `random.choice(FRASES)` phrase is sent via `reply_text` so the command never silently fails.

#### Supported formats
`.gif`, `.mp4`, `.webp` (lowercased suffix check). Non-existent or unreadable directory → `[]` (never raises).

### Alternatives considered

| Option | Rejected because |
|---|---|
| Store GIFs in the image (Dockerfile COPY) | Requires rebuild to add/change GIFs |
| Separate Docker volume for GIFs | Extra infrastructure; existing `./data` mount already covers it |
| Weighted pool (different weight per GIF) | Over-engineering; equal weight is the simplest correct model |

### Files changed

| File | Change |
|---|---|
| `src/worldcup_bot/data/gifs.py` | New — `list_tongo_gifs` helper |
| `src/worldcup_bot/config.py` | Added `tongo_gifs_dir: str = ""` + `TONGO_GIFS_DIR` env |
| `src/worldcup_bot/bot/handlers.py` | `cmd_tongo` rewritten; added `Path`, `list_tongo_gifs` imports |
| `data/tongo_gifs/.gitkeep` | New — seeds the mounted folder |
| `.gitignore` | Note that `data/tongo_gifs/` is NOT ignored |
| `tests/test_tongo.py` | `TestListTongoGifs` (6 tests) |
| `tests/test_handlers.py` | `TestCmdTongoGifs` (6 tests), `Path` import, `send_animation` in `_make_context` |
| `README.md` | Documents GIF hot-reload + `TONGO_GIFS_DIR` |
| `.env.example` | Commented `TONGO_GIFS_DIR` line |

---

## 20. Decision: /simulagol hidden from /start help + /tongo probability rework

**Author:** Kante (Backend Developer)
**Date:** 2026-06-16T12:08+02:00
**Status:** IMPLEMENTED

### Context

Two small UX/logic changes requested by DrDonoso:

1. `/simulagol` is a test command used to exercise the "Ver gol" button flow. It should remain functional but not be advertised in `/start` help text (it clutters the menu for real users).

2. `/tongo` previously weighted "Sanchez ens roba" by repeating it 25 times in `FRASES` — a quick hack from the legacy Euro 2024 bot. The desired probability is exactly 1/3, which is better expressed explicitly.

### Decisions

#### 1. `/simulagol` removed from `/start` help (command kept)

- Deleted only the `/simulagol — (test) …` line from `cmd_start`'s reply string.
- The `CommandHandler("simulagol", cmd_simula_gol)` registration in `__main__.py` is untouched.
- No behaviour change — the command still works when typed manually.

#### 2. `/tongo` explicit 1/3 probability

- Introduced `SANCHEZ_ENS_ROBA = "Sanchez ens roba"` constant in `tongo.py`.
- `FRASES` now contains ONLY the 15 original sarcasm phrases + 13 new Spanish/Catalan phrases (28 total). Zero "Sanchez ens roba" entries.
- `cmd_tongo` logic: `if random.random() < 1/3 → SANCHEZ_ENS_ROBA; else → random.choice(FRASES)`.
- Rationale: explicit probability is readable, testable, and not fragile to future list edits. The 25-duplicate approach would silently break if someone added more phrases.

### Files Changed

- `src/worldcup_bot/data/tongo.py` — full rewrite of FRASES, new SANCHEZ_ENS_ROBA constant, updated docstring.
- `src/worldcup_bot/bot/handlers.py` — import update, cmd_start line removed, cmd_tongo logic replaced.
- `tests/test_tongo.py` — new file: data integrity tests.
- `tests/test_handlers.py` — added TestCmdTongo, extended TestCmdStart.

### Verification

- 471 pytest tests passing.
- Smoke: `sanchez not in FRASES: True`, `frases count: 28`, `new phrase present: True`.
- Container rebuilt (`drdonoso/worldcup2026`), State=running, RestartCount=0.

---

## 21. Decision: Ver-gol Concurrency Hardening + file_id Cache

**Author:** Kante (Backend Developer)  
**Date:** 2026-06-16T11:43+02:00  
**Status:** DONE — implemented, 449 tests green, container running.

### Context

`cmd_ver_gol_callback` already had a status-based guard (`"sending"` / `"sent"`) that was effectively atomic on PTB's single-threaded event loop (no await between check and set). However:
1. The mutual-exclusion was implicit — a future edit adding an `await` between the status check and status set would silently break it.
2. Every call to "Ver gol" re-downloaded and re-uploaded the same video file, even if Telegram had already stored a permanent `file_id` for it.

### Decisions

#### A — Explicit non-blocking in-flight lock per goal token

A `vergol_inflight: set` in `bot_data` provides an explicit, self-documenting guard:

```python
inflight: set = context.bot_data.setdefault("vergol_inflight", set())
if token in inflight:
    await query.answer("Ya estoy enviando el vídeo…")
    return
inflight.add(token)
info["status"] = "sending"   # both lines before the first await — atomic
```

`inflight.discard(token)` always runs in `finally`, so the lock is never stuck. The existing `status` field is kept as belt-and-suspenders; the inflight set is the suspenders that make the intent explicit even if future edits add awaits.

**Rejected alternative:** asyncio.Lock per token — would block the 2nd click for ~15s (Telegram spins a loading indicator on the button). Non-blocking fast-fail (toast answer + immediate return) is significantly better UX.

#### B — Two-level Telegram file_id cache

Telegram video file_ids are effectively permanent for the same bot. Once a video is uploaded, all future sends can use the file_id directly — no re-download, no re-upload, instant delivery.

**Level 1 — per-goal shortcut (`info["file_id"]`):**
If the same goal button is pressed again (unlikely but possible), skip everything including `find_goal_clip`.

**Level 2 — per-media-url cache (`bot_data["clip_file_ids"][url]`):**
If two different goals share the same clip URL (same highlight used for two notifications), the second send re-uses the file_id without downloading.

**Fresh-send capture:**
```python
sent_msg = await context.bot.send_video(...)
if sent_msg and sent_msg.video:
    fid = sent_msg.video.file_id
    info["file_id"] = fid
    clip_file_ids[media_url] = fid
```

**Stale file_id handling:**
If a fast-path `send_video(video=file_id)` raises (very rare — Telegram file_ids for videos are effectively permanent), the file_id is evicted from both caches, `status` is reset to `"pending"`, and the exception propagates through the outer `except` block so the user sees the standard error toast and can retry.

#### Initialisation

`build_app` now eagerly creates both new dicts/sets so they always exist and tests/handlers can rely on them without `.setdefault` races:

```python
app.bot_data["vergol_inflight"] = set()
app.bot_data["clip_file_ids"] = {}
```

### Trade-offs considered

| Option | Pro | Con | Decision |
|--------|-----|-----|----------|
| asyncio.Lock per token | True async safety | Blocks 2nd click ~15s (bad UX) | Rejected |
| Status field only | Already works today | Implicit; breaks if await added | Keep as belt |
| Inflight set (chosen) | Explicit; non-blocking; easy to audit | Slightly more code | ✅ |
| Persistent file_id (DB/Redis) | Survives restart | Overkill for in-memory bot | Rejected |
| In-memory file_id cache (chosen) | Zero extra deps; instant repeat sends | Lost on restart | ✅ |

### Tests added (6 new)

- `test_inflight_guard_answers_immediately_no_download` — pre-add token, assert toast + no find/send
- `test_inflight_token_discarded_after_successful_run` — token removed from inflight in finally
- `test_cached_file_id_on_info_resends_instantly_no_download` — fast path A
- `test_cached_file_id_per_media_url_resends_instantly` — fast path B
- `test_fresh_send_stores_file_id_in_cache` — capture + store after real upload
- `test_bad_file_id_evicted_and_status_reset` — stale fid evicted, status pending

---

## 22. Decision: OpenAI / LiteLLM env vars wired into compose files

**Date:** 2026-06-16T13:45+02:00  
**Author:** Maldini (DevOps)  
**Requested by:** DrDonoso

### Context

Kanté added an OpenAI-compatible AI integration (daily 9AM update via the user's self-hosted LiteLLM proxy). The feature reads four env vars (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `DAILY_UPDATE_HOUR`) and self-disables in-app when any of the three key vars are unset.

### Decision

Wire the four vars into the Compose infra layer as **optional pass-throughs** so:
1. The production image can receive them at runtime without a code change.
2. The feature stays dormant until the operator explicitly sets all three enable vars.

### Changes Made

| File | Change |
|------|--------|
| `docker-compose.yml` | Added 4-var block under `# --- OpenAI-compatible AI ---`, after `TELEGRAM_GROUP_ID` |
| `docker-compose.local.yml` | Same 4-var block (same position, same style) |
| `.env.example` | New commented-out section at the end; notes that ALL THREE (key/base_url/model) must be set |

**Style used** (mirrors existing optional vars like `TIMEZONE`):
```yaml
OPENAI_API_KEY: "${OPENAI_API_KEY:-}"
OPENAI_BASE_URL: "${OPENAI_BASE_URL:-}"
OPENAI_MODEL: "${OPENAI_MODEL:-}"
DAILY_UPDATE_HOUR: "${DAILY_UPDATE_HOUR:-9}"
```

### Files NOT modified

- `config.py` — Kanté owns the in-app feature-flag logic.
- `.env` — user's real secrets; git-ignored; never touched by infra changes.
- `Dockerfile` — no build-time changes needed; all vars are runtime env.

### Verification

```powershell
$env:TELEGRAM_GROUP_ID='-100123'; $env:TELEGRAM_BOT_TOKEN='fake'; $env:FOOTBALL_DATA_API_KEY='fake'
docker compose -f docker-compose.yml config --quiet       # exit 0
docker compose -f docker-compose.local.yml config --quiet # exit 0
```

Both parsed with exit code 0 and no YAML errors.

---

## 23. Decision: Promote TELEGRAM_GROUP_ID to Required

**Date:** 2026-06-16T12:24+02:00
**Author:** Maldini (DevOps)
**Status:** Implemented

### Context

The live goal notifier feature requires a Telegram group/channel ID to post goal alerts. Without it the feature is silently broken. Kanté is updating `load_settings()` to fail fast (hard validation) if the variable is missing.

### Decision

`TELEGRAM_GROUP_ID` is now a **required** environment variable across the entire stack:

| File | Change |
|------|--------|
| `docker-compose.yml` | Comment → "REQUIRED for live goal notifications"; value `"${TELEGRAM_GROUP_ID:-}"` → `"${TELEGRAM_GROUP_ID}"` |
| `docker-compose.local.yml` | Same change |
| `.env.example` | Moved from `# Optional — Override defaults` (commented) to its own `# Required` block (uncommented), after `FOOTBALL_DATA_API_KEY` |

### Rationale

- Dropping the `:-}` empty-default causes Compose to emit a **warning** when the variable is unset, giving operators an early signal before the container even starts.
- Hard enforcement (startup failure) is delegated to the application layer (`load_settings()` — Kanté's responsibility).
- `.env` (git-ignored, holds real values) was **not** modified.

### Files Changed

- `docker-compose.yml`
- `docker-compose.local.yml`
- `.env.example`

### Files NOT Changed

- `config.py` (Kanté's ownership — not touched)
- `.env` (user data — not touched)

---

## 24. Decision: Daily Update HTML Format + Snapshot

**Author:** Kanté (Backend)  
**Date:** 2026-06-16  
**Status:** IMPLEMENTED — 594 tests green.

### Context

The daily AI update posted at 09:00 and via `/updatediario` was sending raw Markdown-like text without `parse_mode`, causing `**bold**` to appear literally, results jammed into one paragraph, no flag emojis, and filler notes even when no interesting match context existed.

### Decisions

#### 1. Message format — HTML, built deterministically

The final message is now assembled **in code** (pure `render_message()` function) and sent with `parse_mode="HTML"`.  Layout:

```
📅 <b>Resultados de ayer</b>
{home_flag} {home_bold?} {hs}-{as} {away_bold?} {away_flag}

⚽ <b>Partidos de hoy</b>
{home_flag} <b>{home}</b> vs <b>{away}</b> {away_flag} — {HH:MM}
   <i>{note}</i>   ← only if non-empty

📊 <b>La porra</b>
{standings_comment}
```

All AI-provided and team-name strings pass through `html.escape(s, quote=False)` before insertion.

#### 2. AI contract — JSON only

The model must return **strict JSON** (no markdown fences):
```json
{"today_notes": {"TLA1-TLA2": "nota o vacía"}, "standings_comment": "texto"}
```
- `today_notes` keys: `"{home_tla}-{away_tla}"` for each today match.
- Note is non-empty **only** for matches with a genuine rivalry, conflict, or interesting fact.  If nothing, empty string (no filler).
- `parse_ai_json()` strips fences and calls `json.loads()`; on failure → `({}, "")` + `log.warning`.

#### 3. Snapshot module — `src/worldcup_bot/ai/snapshot.py`

Tracks provisional ranking positions day-by-day.  
File: `{state_dir}/porra_snapshot.json`.  
Schema: `{"YYYY-MM-DD": {username: position(int)}}`.  
Prunes to 7 dates.  All I/O is best-effort (swallow+log, never crash).  
On first run: `baseline=None` → AI notified → writes intro instead of movement recap.

#### 4. `state_dir` config field

`Settings.state_dir` added (default `/app/state`, env `STATE_DIR`).  
Maldini owns the Docker volume at `/app/state` (writable bind-mount).

#### 5. `parse_mode="HTML"` on both senders

- `__main__.py` `daily_update_job` → `send_message(..., parse_mode="HTML")`
- `bot/handlers.py` `cmd_update_diario` → `send_message(..., parse_mode="HTML")`

### Impact

- `build_messages()` (old) removed; replaced by `build_ai_user_message()`, `parse_ai_json()`, `render_message()`.
- `generate_daily_update()` now also loads porra ranking + snapshot before calling AI.
- 56 new tests; 594 total green.

---

## 25. Decision: Raise AI max_tokens to 1500 + bound standings_comment length

**Date:** 2026-06-16  
**Author:** Kanté (Backend Developer)  
**File:** `src/worldcup_bot/ai/daily_update.py`

### Context

Live E2E revealed that `generate_daily_update()` called `ai.complete()` with `max_tokens=800`. With 12 porra participants + today's match notes + standings narrative, the model's JSON response was truncated → `parse_ai_json` failed with "Unterminated string" → the "La porra" section and today-match notes were silently empty (graceful degradation worked, but AI content was lost).

### Decision

1. **`max_tokens` raised from 800 → 1500** in the `ai.complete(...)` call.  
2. **`_SYSTEM` prompt updated**: `standings_comment` is now explicitly bounded to "máximo 4-5 frases cortas" to reduce the token footprint of the narrative and further lower truncation risk.  
3. Everything else unchanged: HTML render, snapshot, parse fallback, team names in English.

### Tests

- New test `test_complete_called_with_max_tokens_1500` asserts the `complete()` call uses `max_tokens=1500`.  
- Full suite: **595 passed** (was 594).

---

## 26. Decision: Use `max_completion_tokens` instead of `max_tokens` for AI calls

**Date:** 2026-06-16  
**Author:** Kante (Backend)  
**Status:** Implemented

### Context

Live diagnostics against the user's LiteLLM endpoint revealed that the proxy silently clamps the legacy `max_tokens` parameter to 100 tokens (`finish_reason="length"`, `completion_tokens=100`, `reasoning_tokens=0`). This caused the daily-update JSON response to be truncated, breaking `parse_ai_json` and producing an empty "La porra" section.

### Decision

Replace all uses of `max_tokens` in `AIClient.complete` (signature + `chat.completions.create` call) with `max_completion_tokens`, which the OpenAI SDK ≥1.x and modern OpenAI-compatible backends honour correctly. Do **not** send both params simultaneously — some backends reject duplicate token limit fields.

### Changes

- `src/worldcup_bot/ai/client.py` — `AIClient.complete` signature: `max_tokens: int = 600` → `max_completion_tokens: int = 600`; pass `max_completion_tokens=max_completion_tokens` to `create()`.
- `src/worldcup_bot/ai/daily_update.py` — `generate_daily_update`: call site updated to `max_completion_tokens=1500`.
- `tests/test_ai.py` — renamed `test_passes_temperature_and_max_tokens` → `test_passes_temperature_and_max_completion_tokens`; renamed `test_complete_called_with_max_tokens_1500` → `test_complete_called_with_max_completion_tokens_1500`; both now assert `max_completion_tokens` is present and `max_tokens` is **absent** from the SDK call kwargs.

### Outcome

595 tests pass (no regressions). `finish_reason` will be `"stop"` with full JSON output instead of `"length"` truncated at 100 tokens.

### Rule going forward

Every future `AIClient.complete` call — and any direct `chat.completions.create` call added later — **must** use `max_completion_tokens`, never `max_tokens`.

---

## 27. Decision: Persistent State Volume for Porra Snapshot (Phase 23)

**Date:** 2026-06-16  
**Owner:** Maldini (DevOps)  
**Status:** ✅ Implemented

### Problem

Kanté's new porra-standings feature requires persisting a daily JSON snapshot (`porra_snapshot.json`) that survives container restarts and recreations. The existing `/app/data` mount is **read-only** (`:ro`), so a new writable location is needed.

### Solution

Introduced a **Docker named volume** at `/app/state` to hold persistent bot state, independent of container lifecycle or host filesystem paths.

#### Changes

##### docker-compose.yml (production)
- Added `STATE_DIR: /app/state` to bot service environment
- Added `- bot_state:/app/state` to bot service volumes (kept `./data:/app/data:ro` unchanged)
- Added top-level `volumes: { bot_state: }` declaration

##### docker-compose.local.yml (local dev)
- Identical STATE_DIR and volume mount as production
- Kept existing SSL cert mount (`./certs:/certs:ro`) and data mount

##### .env.example
- Added explanatory comment: STATE_DIR is set in compose files, not a user-configurable secret
- No secrets, no mandatory new keys

### Verification

Both compose files validated:
```
docker compose -f docker-compose.local.yml config -q  → exit 0 ✅
docker compose -f docker-compose.yml config -q        → exit 0 ✅
```

### Why Named Volume?

- **Persistence across restarts:** State survives `docker compose restart`
- **Persistence across recreations:** State survives `docker compose down && up`
- **Environment-agnostic:** Works on Docker Desktop, Swarm, cloud (Compose abstractly manages volume backend)
- **No host filesystem coupling:** No need for ./state directory on host; Docker manages lifecycle

### Contracts

- **Kanté reads `STATE_DIR` env var** (default: `/app/state`)
- **Kanté writes `{STATE_DIR}/porra_snapshot.json`** on daily update
- **No user intervention needed:** Volume auto-creates on first container start
- **Cleanup:** `docker volume rm bot_state` if the project is removed

### References

- `.squad/agents/maldini/history.md`: Learning entry Phase 23

---

## 28. Decision: Docker Named-Volume Ownership Fix for /app/state

**Date:** 2026-06-16T15:26+02:00  
**Owner:** Maldini (DevOps)  
**Status:** Implemented  

### Problem
The Docker named volume `bot_state` (mounted at `/app/state`) was owned by `root:root` at creation time. When the non-root `app` user (uid 1000) tried to write the daily porra snapshot (`porra_snapshot.json`), the container crashed with:
```
[Errno 13] Permission denied: '/app/state/porra_snapshot.json'
```

### Root Cause
Docker initializes a fresh named volume's directory ownership from the **image's directory state** at that mount path. Because the Dockerfile never explicitly created `/app/state`, the mountpoint inherited root ownership when the volume was first created.

### Solution
**Dockerfile change (line 24–25):** Extended the existing directory setup to also create and chown `/app/state` before `USER app`:

```dockerfile
# Create writable directories for the data mount + persistent state volume
RUN mkdir -p /app/data /app/state && chown -R app:app /app/data /app/state
```

This ensures both `/app/data` and `/app/state` are created with `app:app` (uid 1000, gid 1000) ownership **before** the `USER app` line, so any named volumes mounted at these paths will inherit the correct permissions.

### Pattern (for future reference)
Docker's named-volume ownership inheritance:
- Happens at **image build time** (directory permissions are baked into the image layers)
- Applies when the volume is **first mounted** (if the image's directory already exists with specific ownership, the volume inherits it)
- Cannot be fixed retroactively on existing volumes (must be recreated)

### Verification Checklist
- ✅ Dockerfile creates `/app/state` and chowns it to `app:app`
- ✅ Creation and chown happen **before** `USER app` line
- ✅ Single combined `RUN` line for smaller layer footprint
- ✅ Existing `/app/data` handling unchanged

### Coordinator Handoff
**After rebuilding the image:** The existing `bot_state` volume on development machines was created with root ownership and must be recreated. Run:
```bash
docker volume rm bot_state
```
Then the next `docker compose up` will create a fresh `bot_state` volume that inherits `app:app` ownership from the updated image.

### Impact
- **Scope:** Dockerfile only (no changes to compose files, env vars, or Python code)
- **Backward compat:** Yes — existing `/app/data` behavior unchanged; `/app/state` now properly permissioned
- **Image size:** Negligible (one additional `mkdir -p`)

---

## Governance

- All meaningful changes require team consensus
- Architectural decisions locked as of 2026-06-15 (Phase 5 - Ship)
- API format normalization enforced at client layer (never in scoring logic)
- TLA mapping is the single source of truth for team identification

---

## 29. Decision: Scenario-Aware Daily Update

# Decision: Scenario-Aware Daily Update

**Date:** 2026-06-16  
**Author:** Kanté (Backend Developer)  
**Status:** Implemented  

## Context

The AI daily update (`generate_daily_update`) previously always produced a full HTML message regardless of whether there were matches. This led to confusing or empty posts on rest days.

## Decision

`generate_daily_update` now returns `str | None` and follows 4 scenarios based on whether yesterday had FINISHED matches and whether today has any matches (any status):

| has_yesterday | has_today | Scenario       | Result                                      |
|:---:|:---:|:---:|:---|
| ✗ | ✗ | — | **Return `None`** — callers skip post entirely |
| ✓ | ✗ | `"pausa"`      | Recap yesterday + standings frozen notice; `get_next_match` used for resume date |
| ✗ | ✓ | `"reanudacion"` | Competition resumes framing; no ayer section rendered |
| ✓ | ✓ | `"normal"`     | Unchanged full recap + preview |

## Key Implementation Details

### `generate_daily_update` → `str | None`
- Calls `get_football_day_matches` for both days before checking (both calls always made).
- Returns `None` early if both empty.
- For `"pausa"`: calls `client.get_next_match(settings.timezone)` and formats a Spanish date via `format_spanish_date()`.
- Passes `scenario`, `next_match`, `next_date_str` to `build_ai_user_message` and `render_message`.

### `render_message` section omission rules
- **Ayer section**: included only when `yesterday` is non-empty (never prints "Sin partidos ayer.").
- **Today section**: if `today` non-empty → fixtures; elif `scenario == "pausa"` → `⏸️ Hoy no hay partidos` with standings-frozen text and optional date; else → section omitted.
- **Porra section**: always present.

### Spanish date helper — `format_spanish_date(utc_date, tz_name) → str | None`
- Uses constant lists `_DIAS_ES` / `_MESES_ES` (no locale dependency).
- Returns `None` on any exception (graceful degradation).
- Example output: `"el sábado 20 de junio"`.

### Callers
- `daily_update_job` (`__main__.py`): `if text is None → log.info + return` (no `send_message`).
- `cmd_update_diario` (`handlers.py`): `if text is None → reply_text("🤷 No hay partidos ni ayer ni hoy…")`.

### AI system prompt (`_SYSTEM`)
Extended with per-scenario `standings_comment` guidance: `"normal"` / `"pausa"` / `"reanudacion"` instructions. User message now includes `ESCENARIO: {scenario}` line and, for `"pausa"`, a `PROXIMOS PARTIDOS:` line.

## Tests Added
19 new tests across: `TestFormatSpanishDate` (4), `TestRenderMessageScenarios` (7), `TestGenerateDailyUpdateScenarios` (5), `TestCmdUpdateDiarioNoneResult` (2), `TestDailyUpdateJob.test_does_not_send_when_result_is_none` (1).

**Final test count: 614 passing.**


## Decision: Strengthen today_notes to name armed conflicts concretely

# Decision: Strengthen today_notes to name armed conflicts concretely

**Author:** Kanté  
**Date:** 2026-06-16  
**Status:** Implemented

## Problem

Live diagnostics revealed that the `today_notes` AI field produced soft, vague notes for historically sensitive matchups:
- England vs Argentina → "rivalidad futbolera / mucha historia" — did NOT name the Falklands/Malvinas War.
- Israel vs Palestine → "partido sensible por el conflicto, mejor con respeto" — unnamed, unanchored.

The root cause was the `_SYSTEM` prompt treating armed conflicts as one optional item in a loose "notable rivalry or interesting fact" bucket, with no explicit priority ordering.

## Decision

Rewrote `_SYSTEM` in `src/worldcup_bot/ai/daily_update.py` with a **three-tier explicit priority**:

1. **ARMED CONFLICT (PRIORITY):** If the two nations share a current or historical armed conflict, war, military confrontation, or serious military-political tension → name it concisely and factually (e.g. "se enfrentaron en la Guerra de las Malvinas (1982)"). Informative and concrete, not euphemistic.
2. **OTHER GENUINE CURIOSITY:** Colonial history, notable territorial dispute, memorable past World Cup meeting — only if genuinely documented.
3. **EMPTY STRING:** If nothing genuine exists → return `""`. Forbidden: inventing facts, stretching weak connections, generic filler like "es un partido bonito".

### Structural change

The `today_notes` rule is now stated **up-front and unconditionally** before the scenario-specific `standings_comment` guidance. This prevents scenario branches (`reanudacion`, `pausa`) from causing the model to skip or dilute the notes.

## What did NOT change

- JSON-only output contract (`{"today_notes": {…}, "standings_comment": "…"}`)
- `today_notes` keyed by `HOME_TLA-AWAY_TLA`
- `standings_comment` ≤ 4–5 short sentences
- `max_completion_tokens=1500` usage
- `parse_ai_json` fallback behaviour
- Empty-string = no rendered note (correct, preserved)

## Tests

Added `TestSystemPromptContract` (5 tests) asserting:
- `_SYSTEM` contains "conflicto armado"
- `_SYSTEM` cites "Malvinas" as example
- `_SYSTEM` states the empty-string / "CADENA VACÍA" rule
- `today_notes` rule appears before `standings_comment` rule
- `_SYSTEM` explicitly forbids filler

**Final test count: 619 passing** (614 existing + 5 new).




## Decision: Match-Finish Stats Card + Porra Commentary

**Author:** Kanté (Backend)
**Date:** 2026-06-16
**Status:** COMPLETE — 702 tests green.

### Context

When a WC match finishes, the Telegram group should automatically receive:
- **Part A** — A rich match-stats card sourced from ESPN's public summary API, translated to Spanish.
- **Part B** — A short AI commentary (≤4 lines) about porra ranking changes, delivered in the voice of a randomly chosen Spanish football commentator.

### Decisions

#### 1. ESPN Stats API

- Endpoint: `GET https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={gameId}`
- League slug `fifa.world` works for WC2026 events; configurable via `ESPN_LEAGUE_SLUG`.
- `ESPNClient` is a thin sync `requests` wrapper; callers use `asyncio.to_thread` in the async job.
- `get_match_stats()` returns `None` on any error (log warning); callers degrade gracefully.
- Stat units: `possessionPct` already a %; `passPct` is a fraction 0-1 (×100 for display).
- Formatter omits rows whose stat is absent in both sides; omits red-cards row if both are 0.

#### 2. ESPN game ID via Reddit thread

- `RedditMatchScanner.get_espn_game_id(home, away)` reuses the existing `find_match_thread()` search, fetches the full thread HTML, and regexes `gameId=(\d+)` from the ESPN link embedded in the thread body.
- Returns `None` on any failure; job continues with Part B even if Part A has no game ID.

#### 3. Commentators pool

- `COMMENTATORS = ["Manolo Lama", "Julio Maldini", "Andrés Montes"]` — easily extensible list.
- Per-persona style hints embedded in the system prompt so the model mimics the persona's recognisable voice.
- `max_completion_tokens=400` (follows codebase rule: never `max_tokens`).

#### 4. Live ranking tracker (`porra/live.py`)

- State file: `{state_dir}/porra_live.json` — **different from** `porra_snapshot.json` (daily).
- Schema: `{username: {"pos": int, "pts": float, "name": str}}`.
- `diff_live(old, new)` returns a `LiveDiff` dataclass with `changed` bool, `movements` list, and `new_entries` list.
- Pts delta threshold for change detection: `> 0.001` (avoids float noise).
- Always `save_live()` after processing a finished match, even when AI is disabled, so the next match diffs against the latest state.

#### 5. `poll_finished_matches_job` dedup pattern

- On **first run**: seed `finished_seen` = all currently-finished IDs → return without sending. Mirrors goal-notifier seeding pattern.
- On **subsequent runs**: set diff (`current_finished - finished_seen`) yields newly-finished IDs.
- Each match is try/except isolated — one failure never breaks others.
- `espn_client` and `reddit_scanner` lazily initialised in `bot_data` (same pattern as goal notifier scanner).

#### 6. Config changes

Both new env vars have safe defaults so prod works without `docker-compose` changes (Maldini's domain):
- `ESPN_LEAGUE_SLUG` → default `"fifa.world"`
- `FINISHED_POLL_INTERVAL_SECONDS` → default `120`

### Files Changed / Created

| File | Change |
|------|--------|
| `src/worldcup_bot/espn/__init__.py` | New package |
| `src/worldcup_bot/espn/client.py` | New — ESPN HTTP client |
| `src/worldcup_bot/espn/formatter.py` | New — HTML stats card builder |
| `src/worldcup_bot/ai/commentators.py` | New — commentators pool + prompt builder |
| `src/worldcup_bot/porra/live.py` | New — live ranking tracker |
| `src/worldcup_bot/reddit/scanner.py` | Added `get_espn_game_id()` |
| `src/worldcup_bot/__main__.py` | Added `poll_finished_matches_job` + scheduling |
| `src/worldcup_bot/config.py` | Added `espn_league_slug`, `finished_poll_interval_seconds` |
| `tests/test_espn_client.py` | New — 11 tests |
| `tests/test_espn_formatter.py` | New — 18 tests |
| `tests/test_espn_scanner.py` | New — 6 tests |
| `tests/test_commentators.py` | New — 13 tests |
| `tests/test_porra_live.py` | New — 20 tests |
| `tests/test_poll_finished_job.py` | New — 15 tests |

**Final test count: 702 passing (619 baseline + 83 new).**

---

## Decision: Combined match-finish message, persona hidden, bold_person_names

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-16  
**Status:** IMPLEMENTED  

### Context

Three UX improvements requested for the porra bot's match-finish notification and participant-name display:

1. ESPN stats card and porra commentary were sent as two separate Telegram messages; user wants one combined message.
2. The `🎙️ Manolo Lama:` prefix was exposing which AI persona narrated the commentary; user wants the style to be hidden.
3. Participant display_names appear in multiple views (commentary, daily standings, ranking/detail commands) without visual emphasis; user wants them in bold across all outputs.

### Decisions

#### 1. Combined match-finish message

`poll_finished_matches_job` collects `stats_text` (Part A, from ESPN) and `commentary_text` (Part B, from AI) separately, then sends **one** `send_message(parse_mode="HTML")` call with:

```
{stats_text}

----

{commentary_text}
```

If only one part is available, send it alone (no separator). If neither is available, send nothing.

**Rationale:** Keeps the chat cleaner (one notification per match instead of two) and makes the `----` separator visually group the two sections as a single atomic post.

#### 2. Persona hidden — style-only

- Removed the `🎙️ {persona}:` prefix from the sent message.
- Added `"No firmes ni menciones tu propio nombre."` to `build_commentary_messages` system prompt so the model doesn't self-identify either.
- `pick_commentator()` is still called: the selected persona drives the **style** of generation but its name is never surfaced.

**Rationale:** The persona is an internal style directive, not content the user needs to see; hiding it removes clutter and avoids confusion about imaginary commentators.

#### 3. `bold_person_names` helper + HTML everywhere

Added `bold_person_names(text: str, names: Iterable[str]) -> str` to `bot/formatters.py`:
- HTML-escapes the input text.
- Sorts names by length descending (longest-first, prevents partial overlaps).
- Matches with `(?<!\w)…(?!\w)` Unicode word boundaries to handle accented names (Peñalver, Tarragó) and multi-word names ("Maria Tarrago") correctly.
- Single regex pass → no double-wrapping.

Applied to:
- `poll_finished_matches_job`: commentary bolded before combining.
- `render_message` (daily update): `standings_comment` bolded; `participant_names` passed in from `generate_daily_update`.
- `format_general_ranking`: display_names in `<b>…</b>` directly in the formatter.
- `format_user_detail`: display_name header in `<b>…</b>`; Markdown `*…*` replaced with HTML `<b>…</b>`.
- `cmd_participantes`: display_names wrapped in `<b>…</b>`, `parse_mode="HTML"`.
- `_send_ranking_with_top3_photos`: all `reply_text` calls and `InputMediaPhoto` captions use `parse_mode="HTML"`.
- `_send_user_detail`: changed `parse_mode="Markdown"` → `parse_mode="HTML"`.

**Rationale:** HTML is already used by the daily update; unifying all user-facing messages to HTML simplifies the mental model and enables safe name bolding without the ambiguity of Telegram's Markdown V1 escaping rules.

### Test impact

- 702 baseline → **733 passing** after adding 31 new tests.
- New file: `tests/test_formatters.py` (25 `bold_person_names` tests).
- Updated: `test_poll_finished_job.py`, `test_handlers.py`, `test_ai.py`, `test_commentators.py`.

---

## 36. Decision: Auto-Changelog via GitHub Release Workflow

**Author:** Maldini
**Date:** 2026-06-17
**Status:** IMPLEMENTED

### Context

The repo had no CHANGELOG.md and the CI workflow used `--generate-notes` (GitHub-generated release notes). The team wanted a human-readable CHANGELOG.md that auto-updates from real commit subjects on every release, with internal Scribe commits filtered out.

### Decision

Added automated CHANGELOG.md maintenance to `.github/workflows/docker-deploy.yml`. A new `CHANGELOG.md` file is created at the repo root with a `<!-- releases -->` marker where entries are inserted newest-first.

### Mechanism

1. **Range detection:** After CalVer (which already runs `git fetch --tags`), `git describe --tags --abbrev=0` finds the previous release tag. Range is `$PREV_TAG..HEAD`; falls back to `HEAD` on first release (no previous tag).
2. **Commit filtering:** `git log "$RANGE" --no-merges --pretty=format:'%s'` is piped through four `grep -v -i` filters:
   - `^\.squad:` — Scribe memory commits
   - `^docs: update changelog` — the auto-commit itself (loop prevention)
   - `^Merge ` — merge commits
   - `^chore:` — non-user-facing housekeeping
3. **Prefix stripping:** `sed -E 's/^(feat|fix|perf|refactor|docs)(\([^)]+\))?: //'` removes conventional-commit prefixes for readability; plain imperative subjects are left unchanged.
4. **Bullet list:** `sed 's/^/- /'` prefixes each surviving line. Written to `release_notes.md` on disk to avoid multiline-output escaping in `$GITHUB_OUTPUT`.
5. **Release creation:** `has_notes=true` → `--notes-file release_notes.md`; `has_notes=false` (all commits internal) → fallback `--generate-notes`.
6. **CHANGELOG insertion:** `sed -i "/<!-- releases -->/r new_entry.md"` appends the `## [VERSION] - DATE` block right after the marker (newest-first). Avoids awk `-v` multiline quoting issues.
7. **Loop prevention:** Auto-commit uses `[skip ci]` suffix so GitHub Actions skips the push.
8. **Race resilience:** Non-fast-forward push retried once with `git pull --rebase --autostash`; second failure logs a warning and exits 0 — deploy never fails over the changelog.

### Constraints Honored

- Docker image build/push and CalVer logic untouched.
- No Python application code or Dockerfile modified.
- `permissions: contents: write` was already present.
- `fetch-depth: 0` was already present on checkout.

---

## 37. Decision: Goal Detection Rework — Block 1

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 789 tests green, not yet committed (coordinator commits at end of multi-block goal).

### Problem

The previous goal notifier detected goals by **parsing Reddit match threads** via `parse_goal_events`, which required the ESPN-structured format:
```
⚽ Goal! France 1, Senegal 0. Mbappé (France)
```

The France-Senegal thread (1u7ltq6) used a **human-narrated format** with no `⚽` emoji and no structured `Goal!` line:
```
66': [](#icon-ball-big)**GOAL FRANCE!! ...narrative... _Kylian Mbappé_ ...**
```

Result: `parse_goal_events` found 0 goals → nothing notified (bug #1).

Additionally, re-parsing Reddit on each tick caused flip-flops (1-0 → 1-1 → 1-0) when ESPN reordered events mid-game (bug #5).

### Decision

**Use football-data.org score changes as the AUTHORITATIVE goal detection source.** Reddit/OpenAI is used ONLY for scorer enrichment.

#### Rationale
- football-data.org free tier reliably reports `home_score`/`away_score` on `IN_PLAY`/`PAUSED` matches, even though it does not provide scorer or minute.
- Score changes are monotonic and unambiguous: increase = goal, decrease = VAR disallowed.
- LLM reads natural language — handles ANY Reddit thread format, not just ESPN-structured.
- Persistent state survives bot restarts; seed-on-first-sight prevents false positives.

### Implementation

#### New modules

**`src/worldcup_bot/reddit/score_state.py`**
- `GoalDelta` dataclass: `{side, scoring_team, new_home, new_away, kind: "goal"|"disallowed"}`
- `load_scores(path) → dict` — reads `{state_dir}/live_scores.json`, returns `{}` on any error (graceful)
- `save_scores(path, data)` — best-effort, swallows/logs failures
- `diff_scores(stored, match) → list[GoalDelta]` — pure: `None` stored → seed (return `[]`); increase → goal(s); decrease → disallowed

**`src/worldcup_bot/ai/goal_extractor.py`**
- `extract_scorer(ai, thread_text, scoring_team, home_team, away_team, new_home, new_away) → (scorer|None, minute|None)`
- Strict information extractor prompt: "Devuelve ÚNICAMENTE JSON {\"scorer\": ..., \"minute\": ...}". No invention. `null` if not found.
- `_parse_extractor_json(raw)` — strips ``` fences; returns `(None, None)` on garbage
- Thread text trimmed to last 6000 chars; uses `max_completion_tokens=100` (not `max_tokens`)

#### Modified modules

**`src/worldcup_bot/reddit/notifier.py`** — added:
- `format_new_goal_message(scoring_team, home_name, away_name, home_score, away_score, ...)` → HTML, scoring team bold, flag emojis, optional scorer + minute line
- `format_disallowed_message(home_name, away_name, home_score, away_score, ...)` → HTML VAR message
- Kept: `format_goal_notification`, `build_goal_keyboard` (used by cmd_simula_gol + block-2 flow)

**`src/worldcup_bot/reddit/parser.py`** — REMOVED `compute_new_goals` (Reddit-parse detection mechanism). Kept `parse_goal_events` as fallback enrichment helper.

**`src/worldcup_bot/__main__.py`** — rewrote `poll_goals_job`:
- `load_scores(state_path)` each tick (persistent across restarts)
- `get_all_matches()` (cached); relevant = IN_PLAY/PAUSED or FINISHED-already-tracked
- First-seen → SEED (no notify)
- Score change → `_process_goal_delta` → sends HTML message WITHOUT keyboard
- Enrichment via `_enrich_scorer`: `find_match_thread` → `get_thread_body` → OpenAI `extract_scorer` → `parse_goal_events` fallback → `(None, None)`
- `save_scores` after any state change
- Removed: `notified_goal_keys`, `seeded_threads`, `compute_new_goals`, `build_goal_keyboard` usage

### NOT in block 1 (block 2)
- "Ver gol" inline keyboard on goal messages
- Clip download / video sending
- `goal_clips` population from new job

### Tests added (56 new, 789 total)
- `tests/test_score_state.py` — diff_scores (seed, home goal, away goal, double increase, decrease→disallowed, no change, None scores), load/save round-trip, error handling
- `tests/test_goal_extractor.py` — `_parse_extractor_json` (clean, fenced, garbage, nulls, empty strings), `extract_scorer` (AI success, AI failure, garbage, trim, temperature, system prompt content)
- `tests/test_goal_formatter.py` — `format_new_goal_message` (scorer present/absent, flags, bold team, HTML escaping, score, both team names), `format_disallowed_message` (VAR text, score, flags, escaping)
- `tests/test_poll_goals_job.py` — seed-on-first-sight (no sends), score increase → goal message (no keyboard), state updated, FINISHED-already-tracked catches final goal, FINISHED-not-tracked ignored, VAR disallowed message, persistence called/not-called on changes/no-changes, API error → no save
- `tests/test_reddit_parser.py` — removed `TestComputeNewGoals` (function deleted)

---

## 38. Decision: Block 2 — Decoupled Clip Search & Persistent Clip Store

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** Implemented, 826 tests green

### Context

Block 1 sent goal messages without a "Ver gol" button. Block 2 decouples the clip search from the goal notification: the goal message fires immediately, then a background job searches Reddit and edits the message to add the button only when the clip is ready.

### Decisions

#### 1. Persistent clip state: `reddit/clip_store.py`
- File: `{state_dir}/goal_clips.json`. One entry per `token` (SHA1[:12] of a goal key).
- Entry fields: `chat_id`, `message_id`, `home_name`, `away_name`, `home_tla`, `away_tla`, `home_score`, `away_score`, `scoring_team`, `scorer`, `minute`, `status` ("searching"|"ready"|"timeout"), `clip_path`, `file_id`, `attempts`, `created_at`.
- `load_clips` / `save_clips` are best-effort (swallow + log on error).
- `add_entry` initialises status="searching", attempts=0, timestamps.
- `prune_old_entries` removes entries older than 7 days (prevents volume bloat).
- **Rationale:** Pure sync module, no async, no Telegram → safe to call anywhere.

#### 2. `bot_data["clip_store"]` as authoritative in-memory dict
- `build_app` loads `goal_clips.json` into `bot_data["clip_store"]` at startup.
- Callbacks and jobs mutate this dict; JSON file is persisted after each write.
- Old `bot_data["goal_clips"]` and `bot_data["clip_file_ids"]` removed entirely.
- **Rationale:** Single source of truth, survives restart: "ready" entries work immediately (clip_path on disk, file_id cached), "searching" entries resume in background.

#### 3. `_process_goal_delta` captures `message_id`
- After `send_message` for a goal, captures `sent.message_id` and calls `add_entry` + `save_clips`.
- Disallowed (VAR) branch returns early — no clip-store entry created.

#### 4. `poll_goal_clips_job` (run_repeating, 45s, first=20s)
- Iterates "searching" entries. Per entry: `attempts += 1`. If > 25 → "timeout".
- `find_goal_clip` via `asyncio.to_thread`; `MediaDownloader.download` awaited directly.
- Downloads to temp file → `compress_if_needed` → `shutil.move` to `{clips_dir}/{token}.mp4`.
- `probe_video` for dims. Sets `status="ready"`, `clip_path`.
- `edit_message_reply_markup` to add `build_goal_keyboard(token)`.
- Each entry wrapped in `try/except` for isolation.
- `prune_old_entries` called every tick.
- Scheduled only when `telegram_group_id` is set.

#### 5. Reworked `cmd_ver_gol_callback`
- Reads from `bot_data["clip_store"]` (not `goal_clips`).
- Guards: unknown token → show_alert; status != "ready" or no clip_path → "no listo".
- Inflight guard: `vergol_inflight` set keyed by token.
- Fast path: `entry["file_id"]` → send by file_id (skip disk read + probe).
- Stale file_id → evict, fall through to fresh disk send.
- Fresh send: open `Path(clip_path)`, `probe_video`, `send_video` with `reply_to_message_id`.
- Cache returned file_id in entry + `save_clips`.
- TODO [Block 4]: click counter hook marked in source.

#### 6. Reworked `cmd_simula_gol`
- Sends goal message WITHOUT keyboard.
- Registers clip-store entry (status="searching") so `poll_goal_clips_job` picks it up.
- `_cs_save_clips` persists immediately.

#### 7. Clips directory
- `{state_dir}/clips/` created by `build_app` if missing.
- Clip files named `{token}.mp4`.

### Key function names (for coordinator E2E)
- `poll_goal_clips_job` — background job in `__main__.py`
- `add_entry` / `load_clips` / `save_clips` / `prune_old_entries` — in `reddit/clip_store.py`
- `cmd_ver_gol_callback` — reworked in `bot/handlers.py`
- `cmd_simula_gol` — reworked in `bot/handlers.py`

### Test count
- Baseline (Block 1): 789
- Block 2 adds: 37 new tests (clip_store: 14, poll_goal_clips_job: 13, poll_goals integration: 2, handlers: 8)
- **Total: 826 passing**

---

## 39. Decision: Match-finish message always contains a 🏁 Final result section

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 835 tests green, no commit yet.

### Context

`poll_finished_matches_job` previously sent nothing when ESPN stats were unavailable and the porra ranking did not change. Users reported that finished matches went completely silent — no confirmation that a match had ended.

### Decision

The match-finish message is now assembled from up to **3 sections** joined by `"\n\n---\n\n"` (3-dash separator):

1. **Final result** *(always present)*
   ```
   🏁 <b>Final</b>
   {home_flag} {h_name} {hs}-{as_} {a_name} {away_flag}
   ```
   The winning team's name is wrapped in `<b>…</b>` (`match.winner == "HOME_TEAM"` → bold home; `"AWAY_TEAM"` → bold away; `"DRAW"` or `None` → neither). Team names are `html.escape`d.

2. **ESPN stats card** *(only if stats were found)*  
   Unchanged stat rows. Header simplified from  
   `"📊 <b>Estadísticas — {flag} {home} {hs}-{as} {away} {flag}</b>"` → `"📊 <b>Estadísticas</b>"`  
   to avoid duplicating the scoreline already in section 1.

3. **Porra commentary** *(only if `live_diff.changed` AND `ai_enabled`)*  
   AI-generated text with `bold_person_names` applied — unchanged logic.

`send_message` is called unconditionally (section 1 guarantees a non-empty message).

### Rationale

- Users need immediate feedback that a match has ended, regardless of API availability.
- The scoreline was duplicated in section 1 (final result) and in the old stats-card header; removing it from the header keeps the card focused on statistics.
- 3-dash `---` aligns with the separator used in goal notifications; the old 4-dash `----` was inconsistent.

### Files changed

| File | Change |
|------|--------|
| `src/worldcup_bot/__main__.py` | Added `import html`, `team_flag` import; replaced combine+send logic with section-builder + unconditional send |
| `src/worldcup_bot/espn/formatter.py` | Simplified header to `"📊 <b>Estadísticas</b>"`; removed unused `html`, `team_flag` imports and 6 header-only variables |
| `tests/test_espn_formatter.py` | Updated 3 tests to reflect header no longer contains scoreline or team names |
| `tests/test_poll_finished_job.py` | `_make_match` gains `winner` param; new `TestFinalResultSection` (9 tests); `TestCombinedMessage` fully updated; `test_no_send_when_game_id_none` renamed and inverted |

---

## 40. Decision: Always generate porra commentary on match finish (Block 3 refinement)

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 882 tests green, not yet committed.

### Problem

`poll_finished_matches_job` only generated porra commentary when `live_diff.changed` was `True`. If a match finished without moving the ranking (or with no ESPN stats), users received either a bare `🏁 Final` result line with no context, or nothing.

### Decision

**Commentary is generated whenever `ai_enabled(settings)` AND `bool(ranking)` — regardless of whether the ranking changed and regardless of whether ESPN stats are available.**

The `live_diff.changed` gate is removed from Part B of `poll_finished_matches_job`.

### Implementation

#### `porra/live.py` — new `render_porra_context`

```python
def render_porra_context(diff: LiveDiff, ranking: list) -> str:
    """Always non-empty when ranking exists.
    Returns CLASIFICACIÓN ACTUAL (top-5) + CAMBIOS CON ESTE RESULTADO blocks.
    """
```

- Top-5 standings: `{pos}. {display_name} — {pts:.1f} pts`
- Changes block: movement wording if `diff.changed`, else `"Ninguno — la clasificación no se ha movido con este resultado."`
- `render_changes_text` unchanged — preserved for any other callers.

#### `__main__.py` — `poll_finished_matches_job` Part B

Before:
```python
if live_diff.changed and ai_enabled(settings):
    ...
```

After:
```python
if ai_enabled(settings) and bool(ranking):
    ...
    context_text = render_porra_context(live_diff, ranking)
```

#### `ai/commentators.py` — updated system prompt

Extended with per-scenario instructions: explains input always contains current standings + change block; if "Ninguno" appears → acknowledge no change, remind who leads; never invent movements not in the text.

### Net message structure

| Condition | Sections |
|---|---|
| No stats, no participants | `🏁 Final` only |
| No stats, AI disabled | `🏁 Final` only |
| No stats, AI enabled + participants | `🏁 Final` --- `commentary` |
| No stats, AI disabled | `🏁 Final` only |
| Stats, AI enabled + participants | `🏁 Final` --- `stats` --- `commentary` |

### Tests added / changed

- `test_porra_live.py`: `TestRenderPorraContext` (9 tests)
- `test_commentators.py`: new system-prompt tests (2)
- `test_poll_finished_job.py`: `TestAlwaysCommentary` (5 tests)

**Test count: 882 (up from 866 baseline).**

---

## 41. Decision: vergol-stats-block4 — Persistent per-user "Ver gol" counter

**Date:** 2026-06-17  
**Author:** Kanté (Backend Developer)  
**Block:** 4 (final)

### Context

User requirement #6: a persistent counter of who taps "Ver gol", survived bot restarts, with a `/estadisticas` command showing the leaderboard.

### Decision

#### Module placement
New file `src/worldcup_bot/reddit/vergol_stats.py` (alongside `clip_store.py`). Both are pure/sync persistence helpers for the goal-notifier subsystem.

#### Schema
```json
{
  "<str(user_id)>": {
    "name": "<display name>",
    "tokens": ["<goal token>", ...]
  }
}
```
Keyed by `str(user_id)` (Telegram user IDs are ints; stringified for JSON key consistency). `tokens` is a list of *distinct* goal tokens. `len(tokens)` = the count shown in `/estadisticas`.

#### Deduplication
`record_view` only appends a token if it is not already in the list. Multiple taps on the same goal clip by the same user do not inflate the count. Display name is always updated to the latest value (handles username changes).

#### Load-on-tap vs. in-memory cache
Stats are loaded fresh from disk on every `cmd_ver_gol_callback` invocation. This avoids needing a new `bot_data` key and keeps the data model simple. View events are low-frequency.

#### Best-effort isolation
`_record_vergol_view` wraps all stats logic in a `try/except Exception`. A disk error, corrupt JSON, or any unexpected failure writes a warning log and returns without raising.

#### `/estadisticas` output
HTML parse_mode; names wrapped in `<b>` with `html.escape` applied; trophy header; empty-state fallback message in Spanish; numbered leaderboard sorted by count desc, name asc.

#### Registration
`CommandHandler("estadisticas", cmd_estadisticas)` added to `build_app`. Listed in `/start` help text (normal user command).

### Consequences

- `vergol_stats.json` is created on first tap in `{settings.state_dir}/`.
- Pure functions (`load_stats`, `save_stats`, `record_view`, `leaderboard`) are importable for E2E verification.
- No migration needed — missing file returns `{}` gracefully.
- Test count: 866 passing (31 new tests: 24 in `test_vergol_stats.py` + 7 in `test_handlers.py`).

---

## 42. Decision: CI Trigger Optimization via paths-ignore

**Timestamp:** 2026-06-17T08:35:56Z  
**Agent:** Maldini (DevOps)  
**Owner:** DrDonoso  
**Status:** Applied  

### Summary

Added `paths-ignore` filter to `.github/workflows/docker-deploy.yml` `push` trigger to prevent team memory (`.squad/**`) and auto-changelog (`CHANGELOG.md`) commits from triggering unnecessary Docker builds and GitHub Releases.

### Implementation

**File:** `.github/workflows/docker-deploy.yml`

**Before:**
```yaml
on:
  push:
    branches:
      - main
```

**After:**
```yaml
on:
  push:
    branches:
      - main
    paths-ignore:
      - '.squad/**'
      - 'CHANGELOG.md'
```

### Rationale

- **`.squad/**`:** Team memory (Scribe's decision ledger, agent history, etc.) never affects the bot image; commits here should not trigger CI.
- **`CHANGELOG.md`:** Auto-generated by the workflow itself on release; the commit is infrastructure-only and already protected by `[skip ci]` flag.
- **GitHub Actions behavior:** Workflow runs only if ≥1 changed file is NOT in `paths-ignore`. A push touching ONLY these paths is skipped entirely, reducing wasted Docker Hub builds and empty releases.
- **Code/config changes still trigger:** Any push touching `src/`, `tests/`, `Dockerfile`, `docker-compose*.yml`, `.github/workflows/`, or other infrastructure code will still run the workflow normally.

### Verification

- ✅ Workflow YAML is syntactically valid
- ✅ `paths-ignore` is correctly nested
- ✅ No other workflow sections modified

---

# Decision: porra-evolution checkpoints by jornada (football-day reconstruction)

**Author:** Kanté (Backend Developer)  
**Date:** 2026-06-17  
**Status:** DONE — 950 tests green

---

## Context

The original `/evolucion` feature (BLOCK 4) computed ranking history keyed by local
calendar date and reconstructed group standings via the `?date=` query parameter of the
football-data.org standings endpoint. That approach had a fundamental flaw: consecutive
football-days share UTC calendar dates (a match at 02:00 local on June 14 is still
June 13 UTC), so the `?date=` param cannot represent the 9am→9am football-day window
that `/hoy` and `/ayer` use.

## Decision

**Rebuild checkpoints entirely from match results, keyed by football-day label.**

The "football-day" is the same 9am→9am window (configurable via `settings.football_day_start_hour`)
already used by `get_football_day_matches`. A match's football-day label is:
- local date if `local_hour >= anchor_hour`
- local date minus 1 day otherwise

Group standings are **reconstructed** from the match results directly (points W=3/D=1/L=0,
GD, GF, then TLA alpha for remaining ties). Knockout winners come from finished knockout
matches in the same pass. No `?date=` API calls are made during history construction.

## Key new functions (`porra/history.py`)

| Function | Purpose |
|---|---|
| `football_day_of(match, tz, anchor_hour)` | Football-day label for a match (YYYY-MM-DD) |
| `build_jornadas(matches, tz, anchor_hour)` | Sorted distinct jornadas with ≥1 finished match |
| `reconstruct_group_standings(finished_group_matches)` | Points/GD/GF ordering per group |
| `compute_ranking_at_jornada(predictions, all_matches, jornada, tz, anchor_hour)` | Full ranking as of a jornada |
| `_check_reconstruction_vs_api(reconstructed, api_standings_raw)` | Sanity-log top-3 match vs live API |

`ensure_history` calls `get_all_matches()` once, derives all jornadas, reconstructs all
rankings from that single batch. The sanity check logs `INFO` on full match, `WARNING`
with per-group diffs on any top-3 mismatch (tie-break differences are acceptable).

## Removed dead code

- `build_checkpoint_dates` (replaced by `build_jornadas`)
- `engine.compute_ranking_at_date` (used `?date=` param, now unused)

`get_standings(date=...)` is **kept** in `api/client.py` (harmless, tested separately).

## Chart fixes

- matplotlib title: removed `📈` emoji → "Evolución de la porra" (DejaVu Sans has no emoji glyph, causing missing-box rendering)
- x-axis: labels changed from `YYYY-MM-DD` to `DD/MM` short form; axis label "Jornada" instead of "Fecha"
- Telegram caption in `cmd_evolucion` keeps `📈` (Telegram renders emoji fine)

## Test count

936 → **950** (+14). Removed `TestBuildCheckpointDates` (6) + `TestComputeRankingAtDate` (7);
added `TestFootballDayOf` (5) + `TestBuildJornadas` (7) + `TestReconstructGroupStandings` (9)
+ `TestComputeRankingAtJornada` (4) + updated `TestEnsureHistory` (7) + chart tests (2).


---

# Decision: porra-evolution exact latest jornada + startup/daily backfill

**Author:** Kanté (Backend)  
**Date:** 2026-06-17  
**Status:** IMPLEMENTED — 962 tests green.

## Context

`porra/history.py ensure_history` was building per-jornada ranking history by reconstructing group standings from match results for ALL jornadas, including the latest. The reconstruction approximates FIFA tie-breaks (no head-to-head), so the latest data point could differ ±1–2 positions from the live `/actual` ranking. Additionally, history was only populated when a user ran `/evolucion`.

## Decisions

### 1. Latest jornada uses exact live ranking

**Decision:** For the latest (most recent) jornada only, `ensure_history` now calls `engine.compute_general_ranking(predictions, client, official=False)` instead of `compute_ranking_at_jornada`. Past jornadas keep using reconstruction (acceptable approximation for a trend chart).

**Rationale:** The newest data point in the chart is the most visible and most compared against `/actual`. Using the exact live ranking eliminates the tie-break mismatch at the tip of the chart. The reconstruction is still accurate enough for the trend shape of all past jornadas.

**Implementation:**
- Inside the `for jornada in jornadas` loop, branch on `if jornada == latest`.
- Import `engine` lazily inside `ensure_history` (already the pattern for `compute_ranking_at_jornada`).
- Removed `_check_reconstruction_vs_api` and `_safe_jornada_le` helpers — they were only used by the now-removed sanity check. The sanity check was comparing reconstruction to API; it's no longer needed since the latest is exact.

### 2. Auto-backfill at startup + daily refresh

**Decision:** `history_backfill_job` is scheduled unconditionally (not gated on `telegram_group_id`) in `main()`:
- `run_once(history_backfill_job, when=15)` — 15 seconds after startup, to populate the volume on first launch.
- `run_daily(history_backfill_job, time=dtime(9,5,tzinfo=tz))` — 09:05 local time daily, just after the typical football-day close window (09:00).

**Rationale:** Users should not have to run `/evolucion` to trigger history generation. The volume should be pre-populated so the command is fast (only latest jornada recomputed). The daily refresh at 09:05 catches newly-completed jornadas automatically.

**Implementation note:** `history_backfill_job` wraps everything in `try/except` so it can never crash other jobs. Skips early if predictions file has no participants.

### 3. `/evolucion` command unchanged

`cmd_evolucion` still calls `ensure_history` (incremental) on demand. Since past jornadas are cached in the JSON file and only the latest is recomputed, the command is fast.

## Files changed

- `src/worldcup_bot/porra/history.py` — modified `ensure_history`; removed `_check_reconstruction_vs_api`, `_safe_jornada_le`
- `src/worldcup_bot/__main__.py` — added `history_backfill_job`; added `run_once` + `run_daily` scheduling in `main()`; added `from worldcup_bot.porra.history import ensure_history` import
- `tests/test_history.py` — updated `TestEnsureHistory` to patch `worldcup_bot.porra.engine.compute_general_ranking` for latest-jornada tests; added `TestEnsureHistoryLatestUsesLiveRanking` (3 tests)
- `tests/test_history_backfill.py` (NEW) — 9 tests covering job behaviour + scheduling wiring


---

# Decision: Porra Evolution Chart — /evolucion command

**Author:** Kanté (Backend)
**Date:** 2026-06-17
**Status:** READY — 936 tests green, awaiting coordinator commit + container rebuild.

---

## Summary

Adds `/evolucion` — a Telegram photo command that renders a **bump chart** showing how the porra (prediction-pool) ranking has evolved over the tournament, one line per participant.

---

## Architecture Decisions

### 1. `get_standings(date=...)` — backward-compatible param extension
- Added optional `date: str | None = None` to `FootballDataClient.get_standings()`.
- Extended `_get(url, params=None)` to accept optional query-params dict; cache key is deterministically built as `url?key=val` (sorted), so `no-date` and `with-date` have distinct cache entries.
- No existing callers need changes — `date=None` produces identical behaviour to the old signature.

### 2. Dependency-injection refactor in `engine.py`
- Extracted `compute_general_ranking_from(predictions, actual_standings, actual_winners)` — the pure scoring loop with no client dependency.
- `compute_general_ranking` retains its current signature and delegates to it (zero behaviour change; all existing tests pass).
- `compute_ranking_at_date(predictions, client, date)`:
  - Calls `client.get_standings(date=date)` for historical group standings.
  - Filters to groups with `played > 0` (safe for partially-started days).
  - Derives knockout winners from `client.get_all_matches()` filtered by `status=FINISHED` and `utc_date <= {date}T23:59:59Z` — string comparison works because format is ISO UTC.
  - Returns `compute_general_ranking_from(...)`.

### 3. History module (`porra/history.py`)
- Persistence file: `{state_dir}/porra_history.json` — dict keyed by `"YYYY-MM-DD"`, values `{username: {pos, pts, name}}`.
- `build_checkpoint_dates`: converts FINISHED match UTC timestamps → local dates via pytz (settings.timezone), deduplicates, returns sorted list.
- `ensure_history`: for each checkpoint NOT in stored history → compute; **always recompute the latest date** so it stays fresh. Best-effort save. API errors return existing history unchanged.

### 4. Chart (`porra/chart.py`)
- `matplotlib.use("Agg")` set at module import time (before pyplot) — no display/GUI required in container.
- Bump chart: x = dates (sorted), y = rank (1 at top, `ax.invert_yaxis()`), one line+markers per participant, `tab20` colormap for up to 20 users, legend outside right panel.
- Degenerate cases (0 dates, 0 users, 1 date) all handled — always write a valid PNG.
- Font warning for 📈 glyph is cosmetic only (DejaVu Sans fallback); PNG is valid.

### 5. `matplotlib>=3.8` in `pyproject.toml`
- Wheels are self-contained on `python:3.12-slim`; no additional system libs needed for the Agg backend.

---

## Public API for E2E (coordinator)

```python
from worldcup_bot.porra.history import ensure_history
from worldcup_bot.porra.chart import render_evolution_png
```

- `ensure_history(client, predictions, settings, path)` — build history from live API, returns dict.
- `render_evolution_png(history, out_path)` — render PNG, returns out_path.

---

## Caveats

- The emoji `📈` in the chart title renders as a missing-glyph box on the default matplotlib font (DejaVu Sans). This is cosmetic — the PNG is valid and the chart is readable. A font upgrade in the container could fix it but is not required.
- `ensure_history` re-fetches the latest checkpoint date on every invocation of `/evolucion`. With the shared TTL cache this is a cache hit most of the time.


---

# Decision: Changelog from Commit-Body Bullets

**Author:** Maldini (DevOps)  
**Date:** 2026-06-17  
**Status:** DONE — workflow updated, verified locally.

## Context

The `docker-deploy.yml` "Generate release notes from commits" step previously used `git log --pretty='%s'` to generate one bullet per commit subject line. For a squash-merge commit this yields a single generic bullet even when the body contains detailed, itemised bullet points.

## Decision

Replace the shell grep/sed chain with a `python3 - <<'PYEOF'` quoted heredoc. The Python script:

1. Determines range: `prev = git describe --tags --abbrev=0`; `rng = "{prev}..HEAD"` if prev else `"HEAD"`.
2. Enumerates commit SHAs via `git log rng --no-merges --format=%H`.
3. For each SHA: fetches full message via `git log -1 --format=%B`; skips commits whose subject starts with `.squad:`, `chore:`, `docs: update changelog`, or `merge ` (case-insensitive).
4. Scans the body for bullet blocks: lines starting with `- ` (after optional indent) begin a bullet; lines with 2+ leading spaces that follow a bullet are continuations (folded with a single space); any blank or non-bullet non-indented line ends the block; scanning stops at `Co-authored-by:` trailer.
5. Emits body bullets verbatim (prefixes kept). Falls back to `- {subject}` when no body bullets exist.
6. Writes to stdout; redirected to `release_notes.md`.

## Rationale

Squash commits produced by the team contain rich bullet-per-change bodies. The old approach discarded that information. The Python heredoc handles multi-line folding, trailer exclusion, and internal-commit filtering reliably without requiring extra shell tools.

## Verification

Local test against range `20260617.04^..48edda9` (single commit `48edda9`) produced 4 elaborate folded bullets:

```
- Detect goals from football-data SCORE CHANGES (reliable; ends the Reddit-parse flip-flop) with persistent per-match score state. Enrich scorer/minute via an OpenAI information extractor that handles any r/soccer thread format (ESPN-structured or human-narrated). VAR score decreases post a Gol anulado.
- Send the goal message immediately WITHOUT a button; a 45s job polls for the clip, downloads it to the state volume, then edits the message to add the Ver gol button; the tap replies with the video. Survives restarts.
- Match-finish ALWAYS posts a Final result; ESPN stats card when available; and ALWAYS a /porra recap by a random commentator (acknowledges when nothing moved), sections separated by ---.
- New /estadisticas command: a persistent per-user Ver gol view counter.
```

YAML parse: `python -c "import yaml; yaml.safe_load(open('.github/workflows/docker-deploy.yml'))"` → exit 0.

## Files Changed

- `.github/workflows/docker-deploy.yml` — "Generate release notes from commits" step `run:` block replaced.


---


