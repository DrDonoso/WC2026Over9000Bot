# Skill: telegram-html-messages

## When to Use

When sending a multi-line formatted Telegram message (results, scores, rankings, notes) that needs real bold/italic and emoji flags — use HTML mode, NOT plain text or MarkdownV2.

## Pattern

### 1. Escape all variable content

```python
import html

safe = html.escape(user_provided_string, quote=False)
```

Use this for: AI-generated text, team names, notes, user display names.  
Do NOT escape: your own `<b>`, `<i>` tags, integers, known-safe kickoff times.

### 2. Build message as a string, send with parse_mode="HTML"

```python
await context.bot.send_message(
    chat_id=chat_id,
    text=message_html,
    parse_mode="HTML",
)
```

### 3. Supported tags in Telegram HTML mode

| Tag | Use |
|-----|-----|
| `<b>text</b>` | Bold |
| `<i>text</i>` | Italic |
| `<code>text</code>` | Monospace |
| `<a href="url">text</a>` | Link |

No `<br>` — use literal `\n` for newlines.

### 4. Flag emojis

```python
from worldcup_bot.bot.formatters import team_flag
flag = team_flag("ESP")  # 🇪🇸  — returns "" for unknown TLAs
```

Flags are Unicode regional indicators — no HTML escaping needed.

## Full Example (match result line)

```python
home_esc = html.escape(match.home_name, quote=False)
away_esc = html.escape(match.away_name, quote=False)
hf = team_flag(match.home_tla)
af = team_flag(match.away_tla)

if match.winner == "HOME_TEAM":
    line = f"{hf} <b>{home_esc}</b> {match.home_score}-{match.away_score} {away_esc} {af}"
elif match.winner == "AWAY_TEAM":
    line = f"{hf} {home_esc} {match.home_score}-{match.away_score} <b>{away_esc}</b> {af}"
else:
    line = f"{hf} {home_esc} {match.home_score}-{match.away_score} {away_esc} {af}"
```

## AI JSON Contract (for structured AI output)

When asking the AI for structured data, request strict JSON — no code fences:

**System prompt ending:**
> Devuelve ÚNICAMENTE el objeto JSON, sin marcas de código ni nada más.

**Robust parsing:**

```python
import json, logging
log = logging.getLogger(__name__)

def parse_ai_json(raw: str) -> tuple[dict, str]:
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.lstrip("`")
            if text.startswith("json"):
                text = text[4:]
            last = text.rfind("```")
            if last != -1:
                text = text[:last]
            text = text.strip()
        data = json.loads(text)
        return data.get("field1", {}), str(data.get("field2", ""))
    except Exception as exc:
        log.warning("parse_ai_json failed (%s) | raw=%r", exc, raw[:300])
        return {}, ""
```

## References

- `src/worldcup_bot/ai/daily_update.py` — `render_message()`, `parse_ai_json()`
- `src/worldcup_bot/bot/formatters.py` — `team_flag()`
- `src/worldcup_bot/bot/handlers.py` — `cmd_update_diario` (sender)
- `src/worldcup_bot/__main__.py` — `daily_update_job` (sender)
