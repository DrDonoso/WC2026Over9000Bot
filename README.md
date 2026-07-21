# WorldCup2026Over9000TelegramBot

A Telegram porra (betting pool) bot for the 2026 FIFA World Cup. Participants submit predictions in a YAML file keyed by Telegram `@username`; the bot scores them live against real fixtures and results via football-data.org, posts live goal notifications from dual sources, runs a daily AI narrative update, and keeps the group chat engaged with several opt-in features.

> 📖 Para la referencia completa de comandos y subsistemas, ver [`docs/REFERENCIA.md`](docs/REFERENCIA.md).

---

## Features

### 🏆 Porra scoring
Predictions (group-stage order + full knockout bracket) are scored live against football-data.org results. Scoring is evaluated incrementally: each finished match updates points immediately.

### 📊 Leaderboards
- **`/actual`** — provisional leaderboard: groups with ≥1 finished match score live; photo album of top-3 participants.
- **`/general`** — official leaderboard: only fully-closed groups and completed knockout rounds count; photo album of top-3.
- **`/evolucion`** — bump-chart image of ranking evolution across the whole tournament.
- **`/estadisticas`** — leaderboard of who has watched the most live goal clips ("ver gol" button).
- **`/elecciones`** — interactive knockout-picks matrix: tap a phase to see all participants' picks at a glance. Display mode configurable as text or PIL image (`CHOICES_TYPE`).

### ⚽ Live goal notifications (dual source, deduplicated)
- **football-data.org polling** (every `GOAL_POLL_INTERVAL_SECONDS`, default 60 s): score-change detection triggers a goal card with AI-generated scorer attribution and a "Ver gol" inline button.
- **Reddit match-thread polling** (every 25 s): early goal detection from the live match thread — fires ahead of the API on fast goals.
- Both sources feed the same in-memory deduplication table; the group sees at most one notification per goal regardless of which source wins the race.
- **VAR / disallowed goals**: a post-final correction watch (`FINAL_CORRECTION_WINDOW_MINUTES`) patches the score and edits the original goal message if the API reports a score rollback after the whistle.
- **Match-start notices**: `🟢 ¡Empieza el partido!` posted at each kickoff (within ~30 s). Restart-safe.
- **Match recap**: when a match finishes, a full-time card with final score and porra impact is posted.

### 📺 TVE broadcast markers
`/hoy`, `/siguiente`, and the daily AI update mark fixtures broadcast on Spanish public TV (La 1 / Teledeporte) with 📺, fetched from the RTVE schedule API. Disable with `TVE_ENABLED=0`.

### 🤖 AI daily update
At `DAILY_UPDATE_HOUR` (default 09:00), the bot generates a narrative daily summary — yesterday's results, today's fixtures, current porra standings — and posts it to the group. Requires `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL` (e.g. a self-hosted LiteLLM). Disabled by default.

### 🎨 AI "rich image" evolution
A daily gpt-image-2 generated image (Rich Sánchez getting progressively richer) is sent to the group at `RICH_IMAGE_HOUR` (default 00:00). Special-day variants on July 20 (apex) and July 21 (death). Requires `OPENAI_IMAGE_API_KEY`/`OPENAI_IMAGE_BASE_URL` (or falls back to the chat key/URL) + `OPENAI_IMAGE_MODEL`. Disabled by default.

### 💬 Chat features: picante + revive + per-user profiles
All opt-in; require Telegram privacy mode OFF (see [Telegram privacy mode](#telegram-privacy-mode-required-for-chat-features)).

- **Picante** (`CHAT_PICANTE_ENABLED=1`): spicy AI-generated replies to random group messages (~20% probability, configurable). Requires `OPENAI_*` vars.
- **Revive** (`CHAT_REVIVE_ENABLED=1`): re-engages participants silent for `REVIVE_INACTIVE_DAYS` days (default 3) with a personalised AI nudge. Respects a nightly quiet window (default 23:00–06:00).
- **Per-user profiles** (`PICANTE_PROFILES_ENABLED=1`): auto-learned personality profiles that make picante replies more targeted. The bot stores a 2-day sliding window of group messages, summarises them daily at `PICANTE_PROFILES_UPDATE_HOUR` using a cheap dedicated model (`PICANTE_PROFILE_MODEL`), and injects relevant profiles into reply context.

### 🃏 `/tongo` easter egg
Group-specific phrase pool + per-user overrides + optional GIF/MP4/WebP animations, all hot-reloaded. See [Tongo config](#tongo-config) below.

### 🏅 Final ceremony
Auto-triggered by `poll_final_ceremony_job` when the Final finishes; also manually triggerable via `/granfinal`. Posts a pre-final preview, then champion announcement + podium ranking with rendered podium image.

---

## Quick start (local)

```bash
cp .env.example .env                              # fill TELEGRAM_BOT_TOKEN, FOOTBALL_DATA_API_KEY, TELEGRAM_GROUP_ID
cp predictions.example.yml data/predictions.yml  # edit with your group & knockout picks
cp data/TongoUsers.template.yml data/TongoUsers.yml
docker compose -f docker-compose.local.yml up --build
```

---

## Deploy on a server

1. Create `.env` with your tokens:
   ```
   TELEGRAM_BOT_TOKEN=...
   FOOTBALL_DATA_API_KEY=...
   TELEGRAM_GROUP_ID=-100XXXXXXXXXX
   ```
2. Put participant picks in `./data/predictions.yml` (see [Predictions format](#predictions-format)).
3. Copy `data/TongoUsers.template.yml` → `data/TongoUsers.yml` and edit.
4. **[Required for chat features]** Disable Telegram privacy mode (see [below](#telegram-privacy-mode-required-for-chat-features)).
5. Start the bot (pulls `drdonoso/worldcup2026` from Docker Hub):
   ```bash
   docker compose up -d
   ```

**Update the image** — the GitHub Action builds and pushes on every push to `main`. To pull the latest:
```bash
docker compose pull && docker compose up -d
```

---

### Hot-reload behaviours

| What | How |
|---|---|
| Predictions | Edit `./data/predictions.yml` on the host; re-read on every command (mtime cache). No restart needed. |
| Tongo phrases / per-user config | Edit `./data/TongoUsers.yml`; re-read on every `/tongo` call (mtime cache). |
| Tongo GIFs | Drop `.gif`, `.mp4`, or `.webp` files into `./data/tongo_gifs/`; picked up immediately on the next `/tongo`. |

---

### Telegram privacy mode (required for chat features)

The **picante** and **revive** features require the bot to receive all group text messages. By default, Telegram's privacy mode restricts bots to `/commands` and replies only.

1. Open BotFather (`@BotFather`) → `/setprivacy` → select your bot → **Disable**.
2. **Remove the bot from the group and re-add it.** The change only applies to new memberships.
3. Enable in `.env`:
   ```
   CHAT_PICANTE_ENABLED=1
   CHAT_REVIVE_ENABLED=1
   ```

Both features are **disabled by default** and remain opt-in via env flags.

---

## Bot commands

### User-facing

| Command | Description |
|---|---|
| `/start` | Bienvenida e instrucciones básicas |
| `/help` | Lista rápida de comandos |
| `/clasificacion [A-L]` | Clasificación de fase de grupos (letra opcional para un solo grupo, e.g. `/clasificacion L`) |
| `/actual` | Clasificación provisional de la porra (grupos con ≥1 partido jugado puntúan); incluye álbum de fotos del top-3 |
| `/porra` | Alias de `/actual` |
| `/general` | Clasificación oficial (sólo grupos/rondas completamente cerrados); álbum de fotos del top-3 |
| `/evolucion` | Gráfico de evolución del ranking a lo largo del torneo (bump chart) |
| `/estadisticas` | Ranking de quién ha visto más goles (botón "Ver gol") |
| `/elecciones` | Matriz interactiva de elecciones en fase eliminatoria — pulsa una fase para ver las apuestas de todos |
| `/hoy` | Partidos del "día futbolístico" actual (ventana 09:00–09:00 local); 📺 si da TVE |
| `/ayer` | Resultados del día futbolístico anterior |
| `/siguiente` | Próximo partido; 📺 si da TVE |
| `/endirecto` | Partidos en juego ahora mismo |
| `/listaaciertos` | Desglose oficial de aciertos (sólo rondas cerradas) |
| `/listaaciertosactual` | Desglose provisional de aciertos (live) |
| `/mispredicciones` | Tu hoja completa de predicciones |
| `/participantes` | Lista de participantes |
| `/tongo` | Easter egg 🤫 |

### Admin / ocultos

Los siguientes comandos no aparecen en `/help`. Documentación detallada en [`docs/REFERENCIA.md`](docs/REFERENCIA.md).

| Command | Description |
|---|---|
| `/simulagol` | Simula una notificación de gol (testing) |
| `/updatediario` | Lanza manualmente el update diario de IA |
| `/recalcular` | Fuerza recálculo del snapshot de porra |
| `/tongocheck` | Diagnostica la configuración de TongoUsers.yml |
| `/evilsanchez` | Lanza manualmente la evolución de imagen "rich" |
| `/granfinal` | Lanza manualmente la ceremonia de la final |
| `/perfil [@usuario]` | Inspecciona el perfil picante auto-aprendido de un usuario |
| `/calcularperfiles` | Lanza manualmente la actualización de perfiles picante |

---

## Configuration

All settings are loaded from environment variables. Required vars cause a startup error if missing; optional vars have the listed defaults.

### Core — required

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `FOOTBALL_DATA_API_KEY` | football-data.org API key |
| `TELEGRAM_GROUP_ID` | Telegram group/channel ID for live notifications (e.g. `-100XXXXXXXXXX`) |

### Core — optional

| Variable | Default | Description |
|---|---|---|
| `PREDICTIONS_PATH` | `data/predictions.yml` | Path to predictions YAML inside the container |
| `COMPETITION_CODE` | `WC` | football-data.org competition code |
| `TIMEZONE` | `Europe/Madrid` | Timezone for all local-time operations |
| `FOOTBALL_CACHE_TTL` | `60` | Football API cache TTL in seconds |
| `STATE_DIR` | `/app/state` | Directory for persistent bot state (named volume in docker-compose) |
| `BELOVED_TEAMS` | `PAN,UZB,CUW` | Comma-separated TLAs that get a ❤️ next to their flag |

### Football-day window

| Variable | Default | Description |
|---|---|---|
| `FOOTBALL_DAY_START_HOUR` | `9` | Hour (local) at which the "football day" resets for `/hoy` / `/ayer` |

`/hoy` and `/ayer` use a **rolling 24-hour window** anchored at this hour instead of a calendar day, keeping North-American late-night kickoffs on the correct "day" for European viewers.

- **Active window** (`/hoy`): `[HH:00 today, HH:00 tomorrow)` local. Before the anchor hour (e.g. 02:00) the active window still started at HH:00 *yesterday*.
- **Previous window** (`/ayer`): the 24 h block immediately before the active one.

### Ranking photos

| Variable | Default | Description |
|---|---|---|
| `PHOTO_BASE_URL` | `http://victorsaez.cat` | Base URL for participant photos (no trailing slash). Fetched as `{base}/{username}.png` |

Both `/actual` and `/general` send a Telegram photo album of the top-3 participants. Unreachable photos are skipped gracefully; if none are reachable the ranking is sent as plain text.

### TVE broadcast markers

| Variable | Default | Description |
|---|---|---|
| `TVE_ENABLED` | `1` | Set to `0` to disable 📺 markers entirely (useful if the RTVE API breaks) |

### Live goals / Reddit / match tracking

| Variable | Default | Description |
|---|---|---|
| `GOAL_POLL_INTERVAL_SECONDS` | `60` | football-data.org score-poll interval |
| `FINISHED_POLL_INTERVAL_SECONDS` | `120` | Finished-match recap poll interval |
| `FINAL_CORRECTION_WINDOW_MINUTES` | `30` | Minutes after a match finalises to watch for VAR score corrections |
| `REDDIT_USER_AGENT` | Chrome UA | User-agent string for Reddit match-thread polling |

### AI / daily update

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | _(disabled)_ | API key for the OpenAI-compatible endpoint (e.g. LiteLLM) |
| `OPENAI_BASE_URL` | _(disabled)_ | Base URL of the AI endpoint (e.g. `https://your-litellm/v1`) |
| `OPENAI_MODEL` | _(disabled)_ | Model name for chat completions |
| `DAILY_UPDATE_HOUR` | `9` | Local hour at which the daily AI update is posted |

All three `OPENAI_*` vars must be set to enable the daily update and picante/revive features.

### AI / rich image evolution

| Variable | Default | Description |
|---|---|---|
| `OPENAI_IMAGE_MODEL` | `gpt-image-2` | Image model name |
| `OPENAI_IMAGE_API_KEY` | _(falls back to `OPENAI_API_KEY`)_ | Image endpoint key |
| `OPENAI_IMAGE_BASE_URL` | _(falls back to `OPENAI_BASE_URL`)_ | Image endpoint base URL |
| `RICH_IMAGE_HOUR` | `0` | Local hour (0–23) for the daily rich-image job |

All three image vars (or their fallbacks) must resolve to enable rich-image generation.

### Chat — picante (spicy random replies)

| Variable | Default | Description |
|---|---|---|
| `CHAT_PICANTE_ENABLED` | `0` | Master switch. Also requires `OPENAI_*` vars + privacy mode OFF |
| `CHAT_BUFFER_SIZE` | `30` | Recent messages kept in memory for AI context |
| `PICANTE_PROBABILITY` | `0.20` | Probability of replying to an eligible message |
| `PICANTE_COOLDOWN_SECONDS` | `300` | Minimum seconds between spicy replies |
| `PICANTE_MAX_PER_DAY` | `30` | Hard daily cap on spicy replies |
| `PICANTE_MIN_BUFFER` | `5` | Don't fire until buffer has ≥ N messages |
| `PICANTE_TEMPERATURE` | `0.9` | LLM temperature for picante replies |

### Chat — revive (re-engage inactive users)

| Variable | Default | Description |
|---|---|---|
| `CHAT_REVIVE_ENABLED` | `0` | Master switch. Also requires `OPENAI_*` vars + privacy mode OFF |
| `REVIVE_CHECK_INTERVAL_SECONDS` | `14400` | Base check interval (~4 h); actual interval is randomised ±`REVIVE_JITTER_SECONDS` |
| `REVIVE_JITTER_SECONDS` | `2700` | Jitter for revive interval (±45 min) |
| `REVIVE_INACTIVE_DAYS` | `3` | Days silent = considered inactive |
| `REVIVE_MENTION_COOLDOWN_DAYS` | `2` | Don't mention the same user within N days |
| `REVIVE_QUIET_START_HOUR` | `23` | No revive mentions at/after this local hour |
| `REVIVE_QUIET_END_HOUR` | `6` | Quiet window ends at this local hour (wraps midnight) |
| `REVIVE_TEMPERATURE` | `0.8` | LLM temperature for revive messages |

### Chat — per-user picante profiles (auto-learned)

| Variable | Default | Description |
|---|---|---|
| `PICANTE_PROFILES_ENABLED` | `0` | Master flag. Requires `CHAT_PICANTE_ENABLED=1` |
| `PICANTE_STORE_TEXT` | `1` | Store group message text on disk for profile learning. Set to `0` to opt out |
| `PICANTE_PROFILE_MODEL` | `gpt-5.4-nano` | Cheap dedicated model for daily profile summarisation |
| `PICANTE_PROFILES_WINDOW_DAYS` | `2` | Days of messages retained on disk |
| `PICANTE_PROFILES_OTHERS_CAP` | `3` | Max other users' profiles injected alongside the author's |
| `PICANTE_PROFILES_PIQUES_CAP` | `5` | Max stored past picante jabs per user |
| `PICANTE_PROFILES_UPDATE_HOUR` | `4` | Local hour for the daily profile-update job |

### /elecciones display

| Variable | Default | Description |
|---|---|---|
| `CHOICES_TYPE` | `text` | `"text"` (default) or `"image"` (PIL knockout matrix image) |

### /tongo

| Variable | Default | Description |
|---|---|---|
| `TONGO_USERS_PATH` | `data/TongoUsers.yml` | Path to the tongo config YAML |
| `TONGO_GIFS_DIR` | `data/tongo_gifs/` | Directory scanned for `.gif` / `.mp4` / `.webp` files |

---

## Predictions format

File: `data/predictions.yml` — keyed by Telegram `@username` (without `@`, lowercase).

```yaml
participants:
  yourusername:
    display_name: "Your Name"
    base_score: 0            # optional manual point adjustment
    groups:
      A: ["MEX", "KOR", "CZE"]   # top-3 finishers in order
      # … groups B–L (12 groups total in WC2026)
    knockout:
      round_of_32:    [BRA, ESP, ARG, …]   # 16 teams advancing
      round_of_16:    [BRA, ESP, ARG, …]   # 8 teams advancing
      quarter_finals: [BRA, ARG, …]        # 4 teams advancing
      semi_finals:    [BRA, GER]           # 2 teams advancing
      final:          [BRA]                # champion
```

- Use `"**"` as a no-pick wildcard (always scores 0, never errors).
- TLA codes **must** match football-data.org exactly (e.g. `KSA` not `SAU`, `URY` not `URU`). Wrong codes score 0 silently.
- See `predictions.example.yml` for a complete working example with all 12 WC2026 groups.
- `data/predictions.template.yml` is the committed template; `data/predictions.yml` is git-ignored (runtime file).

---

## Tongo config

The bot reads `data/TongoUsers.yml` on every `/tongo` call (mtime-based cache). Two top-level keys:

```yaml
phrases:                      # Pool global de frases
  - "{{first_name}} calla anda"
  # …

users:                        # Overrides por persona (clave = @username en minúsculas)
  algun_usuario:
    sanchez_ratio: 0.66       # float 0–1; default 1/3.  0 = nunca, 1 = siempre
    phrases_mode: append      # "append" (default): añade al pool global
                              # "replace": sustituye el pool global
    phrases:
      - "{{first_name}}, ..."
```

- `data/TongoUsers.yml` is git-ignored. Use `data/TongoUsers.template.yml` as starting point.
- ⚠️ **REQUIRED.** Missing or invalid YAML → `/tongo` replies `❌ No puedo cargar las frases…`. Use `/tongocheck` to diagnose.
- Invalid fields are silently ignored (logged at WARNING).

Phrases support 10 template variables:

| Variable | Description |
|---|---|
| `{{first_name}}` | Sender's first name |
| `{{last_name}}` | Sender's last name (empty if absent) |
| `{{full_name}}` | Sender's full name |
| `{{username}}` | Sender's @username |
| `{{id}}` | Sender's Telegram user ID |
| `{{reply_to_first_name}}` | Replied-to user's first name |
| `{{reply_to_last_name}}` | Replied-to user's last name |
| `{{reply_to_full_name}}` | Replied-to user's full name |
| `{{reply_to_username}}` | Replied-to user's @username |
| `{{reply_to_id}}` | Replied-to user's Telegram user ID |

**Reply-targeting** — if a phrase uses any `{{reply_to_*}}` variable and `/tongo` is sent as a reply, the bot enters reply-targeted mode (only reply phrases; "Sanchez ens roba" 1/3 check skipped).

---

## Architecture / project layout

```
src/worldcup_bot/
├── __main__.py       # Entry point: wires all handlers + jobs, starts polling
├── config.py         # Settings dataclass — authoritative env-var catalogue
├── tve.py            # RTVE schedule API integration (📺 markers)
│
├── api/              # football-data.org client
│   ├── client.py     # HTTP client, caching, match/standings models
│   ├── cache.py
│   └── models.py
│
├── porra/            # Scoring rules — no Telegram imports
│   ├── predictions.py  # YAML loader + validator
│   ├── engine.py       # Scoring logic (groups + knockout)
│   ├── scoring.py
│   ├── camps.py        # Match-camps (who picked whom) display
│   ├── elecciones.py   # Knockout-picks matrix logic
│   ├── history.py      # Porra history snapshots
│   └── chart.py        # Evolution bump-chart renderer (PIL)
│
├── bot/              # Telegram layer — handlers only call porra/ and api/
│   ├── handlers.py          # All CommandHandler / CallbackQueryHandler implementations
│   ├── formatters.py        # Text + photo formatting helpers
│   ├── final_ceremony.py    # Final-ceremony state machine
│   ├── podium_image.py      # Podium photo renderer
│   ├── elecciones_image.py  # PIL knockout matrix image renderer
│   └── endirecto_store.py   # /endirecto live snapshot store
│
├── reddit/           # Reddit match-thread polling (early goals + clips)
│   ├── scanner.py
│   ├── parser.py
│   ├── notifier.py
│   ├── clip_finder.py
│   ├── clip_store.py
│   ├── downloader.py
│   ├── video.py
│   └── …
│
├── espn/             # ESPN match-stats client (used in /endirecto detail)
│   ├── client.py
│   └── formatter.py
│
├── ai/               # OpenAI-compatible AI features
│   ├── client.py          # Thin async wrapper around the API
│   ├── daily_update.py    # Daily narrative update generator
│   ├── goal_extractor.py  # AI scorer attribution from match events
│   ├── commentators.py    # Porra commentary generation
│   ├── rich_image.py      # Rich-image evolution pipeline
│   ├── match_events.py
│   └── snapshot.py
│
└── chat/             # Picante + revive + per-user profiles
    ├── listener.py          # Group-message listener (feeds buffer, updates last_seen)
    ├── buffer.py            # Ring buffer of recent messages
    ├── picante.py           # Spicy-reply logic
    ├── revive.py            # Inactive-user re-engagement
    ├── state.py             # Chat state (last_seen, etc.)
    ├── profiles.py          # Per-user profile dataclass + store
    ├── profile_updater.py   # Daily profile summarisation job
    └── timeline_store.py    # 2-day sliding window of group messages
```

**Clean seam rule**: the Telegram layer (`bot/`) never imports from `api/` directly — it calls `porra/engine` and uses the shared football client injected via `context.bot_data`. `porra/` has zero Telegram dependencies. `ai/` is stateless (pure functions + the AI client). `chat/` features are gated at startup and add zero overhead when disabled.

---

## Notes

- **Corporate / SSL-inspection networks:** the container uses [`truststore`](https://pypi.org/project/truststore/) to pick up the OS CA bundle automatically. On a normal cloud host nothing extra is needed. `docker-compose.local.yml` also mounts `./certs/combined-ca-bundle.pem` for local development behind a corporate proxy.
- **Docker image:** `drdonoso/worldcup2026` on Docker Hub. Built and pushed automatically by GitHub Actions on every push to `main` (needs repo secrets `DOCKER_USERNAME` / `DOCKER_PASSWORD`).
- **Volume mounts:** `./data` → `/app/data` (read-only). Named volume `bot_state` → `/app/state` persists goal tracking, kickoff announcements, ceremony state, and porra snapshots across container restarts.
- **Memory limits:** docker-compose sets `mem_limit: 512m` / `mem_reservation: 256m`; the bot uses a single shared football-data HTTP session to keep RSS low.
- **TVE broadcast markers (📺):** `/hoy`, `/siguiente`, and the daily AI update automatically mark World Cup fixtures broadcast on Spanish public TV (La 1 / Teledeporte) with 📺, fetched from the RTVE schedule API. Disable with `TVE_ENABLED=0` in `.env` if the undocumented RTVE API breaks mid-tournament.
- **Match-start notices:** the bot posts `🟢 ¡Empieza el partido!` to the group at each scheduled kickoff (within ~30 s). Restart-safe: already-announced kickoffs are persisted in `kickoff_announced.json`.
