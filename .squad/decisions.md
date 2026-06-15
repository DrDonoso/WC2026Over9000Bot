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

## Governance

- All meaningful changes require team consensus
- Architectural decisions locked as of 2026-06-15 (Phase 5 - Ship)
- API format normalization enforced at client layer (never in scoring logic)
- TLA mapping is the single source of truth for team identification
