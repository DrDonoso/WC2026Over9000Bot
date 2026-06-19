# WorldCup2026Over9000TelegramBot

A Telegram porra (betting pool) bot for the 2026 FIFA World Cup. Participants submit predictions in a YAML file keyed by Telegram `@username`; the bot scores them live against real fixtures and results via football-data.org.

---

## Quick start (local)

```bash
cp .env.example .env          # fill TELEGRAM_BOT_TOKEN and FOOTBALL_DATA_API_KEY
cp predictions.example.yml data/predictions.yml   # edit with your group & knockout picks
docker compose -f docker-compose.local.yml up --build
```

---

## Deploy on a server

1. Create `.env` with your tokens:
   ```
   TELEGRAM_BOT_TOKEN=...
   FOOTBALL_DATA_API_KEY=...
   ```
2. Put participant picks in `./data/predictions.yml` (see [Predictions format](#predictions-format)).
3. Start the bot (pulls `drdonoso/worldcup2026` from Docker Hub):
   ```bash
   docker compose up -d
   ```

**Hot-reload predictions** — just edit `./data/predictions.yml` on the server. No rebuild, no restart. The bot re-reads the file on every command.

**Hot-reload `/tongo` GIFs** — drop `.gif`, `.mp4`, or `.webp` files into `./data/tongo_gifs/` on the server. They are picked up immediately on the next `/tongo` with the same individual weight as each phrase (more GIFs → higher chance of a GIF in the 2/3 pool; "Sanchez ens roba" is unaffected at 1/3). Optionally override the scan folder with `TONGO_GIFS_DIR` in `.env`.

**Hot-reload `/tongo` phrases** — edit `./data/TongoPhrases.txt` on the server. One phrase per line; lines starting with `#` are comments (ignored). The bot re-reads the file on every `/tongo` call (mtime-based cache). If the file is missing or empty, the built-in default phrases are used automatically.

Phrases support 10 template variables substituted at render time:

| Variable | Description |
|---|---|
| `{{first_name}}` | Sender's first name |
| `{{last_name}}` | Sender's last name (empty if absent) |
| `{{full_name}}` | Sender's full name |
| `{{username}}` | Sender's @username (empty if no username) |
| `{{id}}` | Sender's Telegram user ID |
| `{{reply_to_first_name}}` | Replied-to user's first name |
| `{{reply_to_last_name}}` | Replied-to user's last name |
| `{{reply_to_full_name}}` | Replied-to user's full name |
| `{{reply_to_username}}` | Replied-to user's @username |
| `{{reply_to_id}}` | Replied-to user's Telegram user ID |

**Reply-targeting** — if a phrase uses any `{{reply_to_*}}` variable AND the `/tongo` command is sent as a reply to another message, the bot enters *reply-targeted mode*: only reply phrases are picked, and the "Sanchez ens roba" 1/3 check is skipped. On plain `/tongo` (no reply), or when no reply phrases exist in the file, the normal 1/3 Sanchez / 2/3 phrase pool logic applies. Reply targeting works even when the replied-to message is from a bot.

Optionally override the phrases file path with `TONGO_PHRASES_PATH` in `.env`.

**Per-user `/tongo` config** — create/edit `data/TongoUsers.yml` on the server to customise each participant's `/tongo` experience. The file is committed (empty by default) and hot-reloaded on every `/tongo` call. All entries are optional; an absent entry preserves the original behaviour (1/3 Sanchez, global phrase pool).

Schema (all keys optional):

```yaml
username:                      # Telegram @username, lowercase, without @
  sanchez_ratio: 0.66          # float 0–1; default 1/3 global.  0 = never, 1 = always
  phrases_mode: append         # "append" (default): add phrases to global pool
                               # "replace": replace global pool entirely
                               #   (if replace + empty pool → falls back to global)
  phrases:                     # inline list — same {{...}} variables as TongoPhrases.txt
    - "Frase exclusiva, {{first_name}}"
  phrases_file: tongo/nom.txt  # extra phrases from a file (path relative to TongoUsers.yml)
```

All 10 template variables (`{{first_name}}`, `{{reply_to_first_name}}`, …) work the same way in per-user phrases as in `TongoPhrases.txt`. Inline `phrases` and `phrases_file` are merged; `phrases_mode` controls whether the result is appended to or replaces the global pool.

Invalid fields are silently ignored (logged at WARNING); other entries in the file are unaffected. Optionally override the file path with `TONGO_USERS_PATH` in `.env`.

**Update the image** — the GitHub Action builds and pushes on every push to `main` (needs repo secrets `DOCKER_USERNAME` / `DOCKER_PASSWORD`). To pull the latest on the server:
```bash
docker compose pull && docker compose up -d
```

---

## Bot commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/clasificacion` | Group stage standings (optional letter A–L for a single group, e.g. `/clasificacion L`) |
| `/actual` | Provisional leaderboard (live standings; only groups with ≥1 finished match score, so un-started groups award 0 pts) — sends top-3 photo album |
| `/general` | Official leaderboard (only fully finished groups score) — sends top-3 photo album |
| `/porra` | Alias of `/actual` |
| `/hoy` | Matches in the current football day (09:00–09:00 local window) |
| `/ayer` | Results from the previous football day (09:00–09:00 local window) |
| `/siguiente` | Next upcoming match |
| `/endirecto` | Matches currently live |
| `/listaaciertos` | Official picks breakdown (only closed groups/rounds count) |
| `/listaaciertosactual` | Provisional picks breakdown (live standings; only groups with ≥1 finished match score) |
| `/mispredicciones` | Your full prediction sheet |
| `/participantes` | List of participants |
| `/tongo` | Easter egg 🤫 — edit `data/TongoPhrases.txt` (one phrase per line, hot-reload, 10 template variables, reply-targeting) or drop `.gif` / `.mp4` files into `data/tongo_gifs/` to mix animations into the pool |

---

## Predictions format

File: `data/predictions.yml` — keyed by Telegram `@username` (without `@`, lowercase).

```yaml
participants:
  yourusername:
    display_name: "Your Name"
    groups:
      A: ["MEX", "KOR", "CZE"]   # top-3 finishers in order
      # … groups B–L
    knockout:
      round_of_32:   [BRA, ESP, ARG, …]   # 16 teams advancing
      round_of_16:   [BRA, ESP, ARG, …]   # 8 teams advancing
      quarter_finals:[BRA, ARG, …]        # 4 teams advancing
      semi_finals:   [BRA, GER]           # 2 teams advancing
      final:         [BRA]                # champion
```

- Use `"**"` as a no-pick wildcard (always scores 0, never errors).
- TLA codes **must** match football-data.org exactly (e.g. `KSA` not `SAU`, `URY` not `URU`). Wrong codes score 0 silently.
- See `predictions.example.yml` for a complete working example with all 12 WC2026 groups.

---

## Football-day window

`/hoy` and `/ayer` use a **rolling 24-hour window** anchored at 09:00 local time (configurable via `FOOTBALL_DAY_START_HOUR`) instead of a calendar day.  This keeps North-American late-night / early-morning kickoffs on the correct "day" for CEST viewers.

- **Active window** (`/hoy`): `[09:00 today, 09:00 tomorrow)` local — but if it's currently before 09:00 (e.g., 02:00), the active window started at 09:00 *yesterday*, so tonight's early matches still show under `/hoy`.
- **Previous window** (`/ayer`): the 24h block immediately before the active one.
- Timezone is controlled by the `TIMEZONE` env var (default `Europe/Madrid`).
- Anchor hour is controlled by `FOOTBALL_DAY_START_HOUR` (default `9`).

---

## Ranking photos (`/actual` and `/general`)

Both ranking commands send a **Telegram photo album** with the photos of the top-3 ranked participants, and the ranking text as the album caption.

- Photos are fetched from `{PHOTO_BASE_URL}/{username}.png` (default: `http://victorsaez.cat`).
- `username` is the lowercase key from `predictions.yml` (e.g. `crispavon`, `dsantosmerino`, `pilarfreixas`).
- Each URL is validated before sending: if an image is unreachable or not an `image/*` Content-Type, it is **skipped gracefully** — the album is sent with whatever photos are available.
- If **no** images are reachable, the ranking is sent as plain text instead.
- Override the base URL with `PHOTO_BASE_URL` in `.env` (no trailing slash).

---

## Notes

- **Corporate / SSL-inspection networks:** the container uses [`truststore`](https://pypi.org/project/truststore/) to pick up the OS CA bundle automatically. On a normal cloud host nothing extra is needed.
- **Image:** `drdonoso/worldcup2026` on Docker Hub.
- **Volume mount:** `./data` is mounted read-only into `/app/data` inside the container. The `PREDICTIONS_PATH` env var defaults to `/app/data/predictions.yml`.
