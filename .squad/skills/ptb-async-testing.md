# SKILL: Testing PTB Callbacks and Async Jobs (worldcup_bot)

## When to use
Any time you need to test a `python-telegram-bot` (PTB) callback (`on_group_text`, handlers)
or a periodic job (`revive_inactive_job`, `poll_kickoff_job`, etc.) without hitting Telegram.

---

## Environment

- `asyncio_mode = "auto"` in `pyproject.toml` → **no `@pytest.mark.asyncio` needed**.
  Just write `async def test_*()` and pytest-asyncio handles the event loop.
- All tests are isolated — conftest autouse fixtures reset module caches before/after every test.

---

## Minimal fake Update + Context for a PTB MessageHandler callback

```python
from unittest.mock import AsyncMock, MagicMock
from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.state import ChatState
from worldcup_bot.config import Settings

_GROUP_ID = "-1001234567"

def _make_msg(
    chat_id: str = _GROUP_ID,
    text: str = "Mensaje de prueba valido",
    # Explicitly set ALL media fields to None (falsy).
    # With MagicMock(), unset attributes auto-create truthy children!
    photo=None, video=None, animation=None, sticker=None,
    document=None, voice=None, video_note=None, audio=None,
) -> MagicMock:
    msg = MagicMock()
    msg.chat_id = chat_id
    msg.text = text
    msg.photo = photo
    msg.video = video
    msg.animation = animation
    msg.sticker = sticker
    msg.document = document
    msg.voice = voice
    msg.video_note = video_note
    msg.audio = audio
    msg.reply_text = AsyncMock()
    return msg


def _make_listener_ctx(
    msg=None, user_id=42, username="alice", full_name="Alice",
    bot_id=999, settings=None,
):
    if msg is None:
        msg = _make_msg()
    if settings is None:
        settings = Settings(telegram_bot_token="tok", football_data_api_key="key",
                            telegram_group_id=_GROUP_ID)

    update = MagicMock()
    update.effective_message = msg
    update.message = msg          # maybe_reply uses update.message, not effective_message
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_user.full_name = full_name

    buf = RingBuffer(maxlen=30)
    state = ChatState()

    context = MagicMock()
    context.bot.id = bot_id
    context.bot.send_message = AsyncMock()
    context.bot_data = {
        "settings": settings,
        "chat_buffer": buf,
        "chat_state": state,
        "chat_state_path": "",
        "ai_client": None,
    }
    return update, context, buf, state
```

---

## Minimal fake Context for a periodic job (e.g. revive_inactive_job)

```python
def _make_job_ctx(settings, porra_usernames, last_seen, state_path=""):
    state = ChatState(last_seen=last_seen)
    buf = RingBuffer(maxlen=10)

    ai_client = MagicMock()
    ai_client.complete = AsyncMock(return_value="AI reply text")

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot_data = {
        "settings": settings,
        "chat_state": state,
        "chat_state_path": state_path,
        "chat_buffer": buf,
        "porra_usernames": porra_usernames,
        "porra_display_names": {},
        "ai_client": ai_client,
    }
    return ctx
```

---

## AI client mock pattern

```python
ai = MagicMock()
ai.complete = AsyncMock(return_value="Respuesta de la IA")
# ai.complete is awaitable — use it in place of bot_data["ai_client"]
```

To simulate an AI failure:
```python
from worldcup_bot.ai.client import AIError
ai.complete = AsyncMock(side_effect=AIError("rate limit"))
```

---

## Critical pitfalls

| Pitfall | Fix |
|---------|-----|
| `MagicMock()` attribute → auto-creates truthy child | Explicitly set media fields to `None` for text-message mocks |
| `update.message` ≠ `update.effective_message` | Set both; PTB callbacks use `effective_message`, `maybe_reply` uses `message` |
| `select_candidate([])` raises `ZeroDivisionError` | Callers must guard with `if not candidates` before calling |
| Gate order in `maybe_reply`: min_buffer → probability → cooldown → daily_cap | Test each gate individually by making only that one fail |
| `save_chat_state("")` is a silent no-op on Windows | Use `tmp_path / "state.json"` whenever you need to verify persistence |
| `random.random()` is in `[0.0, 1.0)` — never reaches 1.0 | `probability_gate(1.0)` always passes without mocking; mock anyway for determinism |
| `time.time()` called inside `maybe_reply` | Patch `worldcup_bot.chat.picante.time.time` to freeze the timestamp |
| `random.random()` called inside `probability_gate` | Patch `worldcup_bot.chat.picante.random.random` |

---

## Freezing datetime.now for time-sensitive jobs

When a job calls `datetime.now(tz)` internally (e.g. to check quiet hours or compute a delay),
replace the entire `datetime` class in the module under test with a subclass that overrides `.now()`:

```python
import datetime as _dt

def _frozen_datetime_cls(hour: int, minute: int = 0):
    """
    Returns a datetime subclass whose .now() always returns a fixed local time.
    Inherits all other methods (fromisoformat, arithmetic, etc.) unchanged.
    """
    _fixed_time = _dt.datetime(2026, 6, 30, hour, minute, 0)

    class _FrozenDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):          # noqa: D102
            if tz is not None:
                return _fixed_time.replace(tzinfo=tz)
            return _fixed_time

    return _FrozenDatetime


# Usage: freeze the clock at 23:30 inside the revive module
from unittest.mock import patch

_FrozenDt = _frozen_datetime_cls(23, 30)

@pytest.mark.asyncio
async def test_quiet_skip_still_reschedules():
    ctx = _make_revive_ctx(...)
    with patch("worldcup_bot.chat.revive.datetime", _FrozenDt):
        await revive_inactive_job(ctx)
    # even though quiet → no send, run_once IS called
    ctx.job_queue.run_once.assert_called_once()
    ctx.bot.send_message.assert_not_called()
```

**Why a subclass (not MagicMock)?**
- `datetime.datetime` operations like `+`, `-`, `.replace()`, `.date()` still work on the subclass.
- A plain `MagicMock` replacing `datetime` breaks arithmetic inside the function.

**Scope of the patch:**
- Both `revive_inactive_job` and `schedule_next_revive` live in the same module (`worldcup_bot.chat.revive`).
- One `patch("worldcup_bot.chat.revive.datetime", ...)` covers all `datetime.now()` calls in both.

---

## Intercepting PIL drawing calls for geometry tests

Use a `MagicMock()` as the `draw` argument to test pure drawing helpers without a real canvas:

```python
from unittest.mock import MagicMock
from worldcup_bot.bot.podium_image import _draw_crown, _CROWN_GOLD

def test_crown_polygon_has_11_vertices():
    draw = MagicMock()
    _draw_crown(draw, cx=100, y_top=20)
    draw.polygon.assert_called_once()
    pts = draw.polygon.call_args.args[0]
    assert len(pts) == 11

def test_three_jewels_drawn():
    draw = MagicMock()
    _draw_crown(draw, cx=100, y_top=20)
    assert draw.ellipse.call_count == 3
```

**Why this works:** PIL `ImageDraw` methods (`polygon`, `ellipse`, `text`, etc.) are regular Python
methods. A `MagicMock()` auto-creates callable attributes that record all calls. No canvas needed,
no pixel output — pure behavioural verification of geometry.

---

## Spy on `_text_centered` to verify text values without pixel inspection

To verify name truncation or position labels inside a render without comparing pixel data:

```python
from unittest.mock import patch

def test_15_char_name_truncated():
    drawn: list[str] = []

    def _spy(draw, cx, cy, text, font, color):
        drawn.append(text)  # record; intentionally does NOT draw

    participants = [{"username": "u", "display_name": "B" * 15, "position": 1}]
    with patch("worldcup_bot.bot.podium_image.requests.get", side_effect=OSError()):
        with patch("worldcup_bot.bot.podium_image._text_centered", side_effect=_spy):
            render_podium(participants, settings)

    # Both tile-initials and canvas text are captured:
    assert "B" * 13 + "…" in drawn
    assert "B" * 15 not in drawn
```

**Note:** The spy skips drawing, so the canvas is saved without text. `render_podium` still returns a
valid `BytesIO` (canvas save succeeds) — the spy does NOT force a None return.

---

## Patching PIL Image.save to test save-failure resilience

To test that a function handles disk-full / IOError during PNG save:

```python
from PIL import Image
from unittest.mock import patch

with patch.object(Image.Image, "save", side_effect=OSError("disk full")):
    result = render_podium(participants, settings)

assert result is None  # caught by render_podium's exception handler
```

**Scope:** `patch.object(Image.Image, "save", ...)` patches the method on the PIL class — ALL Image
instances in the process are affected for the duration. Since `_placeholder_tile` and `_circular_crop`
do NOT call `.save()`, only the final `canvas.save(buf, format="PNG")` is impacted. Always pair with
`with` to restore the original after the test.

---

## Generating tiny PNG bytes for mock HTTP responses

```python
import io
from PIL import Image

def _tiny_png() -> bytes:
    """Return bytes for a minimal valid 10×10 PNG (usable as requests.get mock content)."""
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def _tiny_png_buf() -> io.BytesIO:
    buf = io.BytesIO(_tiny_png())
    buf.seek(0)
    return buf

# Usage in a mock:
resp = MagicMock()
resp.status_code = 200
resp.headers = {"Content-Type": "image/png"}
resp.content = _tiny_png()

with patch("worldcup_bot.bot.podium_image.requests.get", return_value=resp):
    result = render_podium(participants, settings)
```

**Why generate instead of loading a fixture file?** No file I/O in tests — the PNG is created
in-memory via PIL, which is already a test dependency. Keeps tests self-contained.

---

## Useful assertion snippets

```python
# Verify no message text was persisted (privacy check)
import json
raw = json.loads(open(state_path, encoding="utf-8").read())
def _has_text_key(obj):
    if isinstance(obj, dict):
        return "text" in obj or any(_has_text_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_text_key(v) for v in obj)
    return False
assert not _has_text_key(raw)

# Verify send_message got @mention + parse_mode=None (revive)
ctx.bot.send_message.assert_called_once()
kwargs = ctx.bot.send_message.call_args.kwargs
assert kwargs["text"].startswith("@alice ")
assert kwargs["parse_mode"] is None

# Verify AI call args (positional: system, user_msg)
call = ai.complete.call_args
system, user_msg = call.args[0], call.args[1]
```
