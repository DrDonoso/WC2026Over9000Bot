"""Comprehensive edge-case tests for the chat package.

Covers beyond the smoke tests in test_chat.py:
- RingBuffer: ring eviction, ordering, empty state, snapshot isolation, field integrity
- ChatState: no message text on disk (privacy), empty/null/corrupt JSON, atomic write
- probability_gate: boundary behavior with mocked random.random
- cooldown / daily_cap / min_buffer gates: extra boundary and near-boundary cases
- on_group_text (listener): every rejection filter + acceptance path, buffer+last_seen update
- maybe_reply orchestrator: each gate shortcutting, AI+reply on success, counter update,
  exception safety (AIError and general Exception both swallowed)
- compute_inactive_candidates: exact inactivity and mention-cooldown boundary seconds,
  never-seen users, non-porra users, corrupt timestamps
- select_candidate: wrapping, consecutive cycling, large index
- revive_inactive_job: @username send format, parse_mode=None, last_mentioned update,
  state persistence, rotate_index advance, disabled/no-AI early returns, exception safety
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytz
import pytest

from worldcup_bot.ai.client import AIError
from worldcup_bot.chat.buffer import RingBuffer
from worldcup_bot.chat.listener import on_group_text
from worldcup_bot.chat.picante import (
    cooldown_gate,
    daily_cap_gate,
    maybe_reply,
    min_buffer_gate,
    probability_gate,
)
from worldcup_bot.chat.revive import (
    compute_inactive_candidates,
    revive_inactive_job,
    select_candidate,
)
from worldcup_bot.chat.state import ChatState, load_chat_state, save_chat_state
from worldcup_bot.config import Settings


# ── shared constants / helpers ────────────────────────────────────────────────

_GROUP_ID = "-1001234567"
_TS = datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)


def _item(username: str = "u", text: str = "hello world") -> dict:
    """Minimal RingBuffer.append keyword-argument dict."""
    return dict(
        username=username,
        display_name=username.title(),
        user_id=1,
        text=text,
        timestamp=_TS,
    )


def _ai_settings(**overrides) -> Settings:
    """Settings with AI fully configured; picante + revive both enabled."""
    base: dict = dict(
        telegram_bot_token="test-token",
        football_data_api_key="test-api-key",
        telegram_group_id=_GROUP_ID,
        openai_api_key="sk-test",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt-test",
        chat_picante_enabled=True,
        chat_revive_enabled=True,
        picante_probability=1.0,    # deterministic: always fire
        picante_cooldown_seconds=0, # no cooldown
        picante_max_per_day=100,    # effectively unlimited
        picante_min_buffer=1,       # easy threshold
        revive_inactive_days=3,
        revive_mention_cooldown_days=2,
    )
    base.update(overrides)
    return Settings(**base)


def _make_msg(
    chat_id: str = _GROUP_ID,
    text: str = "Hola, este es un mensaje",
    photo=None,
    video=None,
    animation=None,
    sticker=None,
    document=None,
    voice=None,
    video_note=None,
    audio=None,
) -> MagicMock:
    """Fake PTB Message object. All media fields default to None (falsy)."""
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
    msg: MagicMock | None = None,
    user_id: int = 42,
    username: str | None = "alice",
    full_name: str = "Alice Foo",
    bot_id: int = 999,
    settings: Settings | None = None,
) -> tuple[MagicMock, MagicMock, RingBuffer, ChatState]:
    """Return (update, context, buf, state) for on_group_text tests."""
    if msg is None:
        msg = _make_msg()
    if settings is None:
        settings = Settings(
            telegram_bot_token="tok",
            football_data_api_key="key",
            telegram_group_id=_GROUP_ID,
        )

    update = MagicMock()
    update.effective_message = msg
    update.message = msg
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


def _make_revive_ctx(
    settings: Settings | None = None,
    porra_usernames: list[str] | None = None,
    porra_display: dict[str, str] | None = None,
    last_seen: dict[str, str] | None = None,
    last_mentioned: dict[str, str] | None = None,
    ai_reply: str = "¡Vuelve, te echamos de menos!",
    state_path: str = "",
) -> MagicMock:
    """Return context mock suitable for revive_inactive_job."""
    if settings is None:
        settings = _ai_settings()
    state = ChatState(
        last_seen=last_seen or {},
        last_mentioned=last_mentioned or {},
    )
    buf = RingBuffer(maxlen=10)

    ai_client = MagicMock()
    ai_client.complete = AsyncMock(return_value=ai_reply)

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot_data = {
        "settings": settings,
        "chat_state": state,
        "chat_state_path": state_path,
        "chat_buffer": buf,
        "porra_usernames": porra_usernames or [],
        "porra_display_names": porra_display or {},
        "ai_client": ai_client,
    }
    return ctx


# ── RingBuffer — edge cases ───────────────────────────────────────────────────


class TestRingBufferEdgeCases:
    def test_empty_buffer_snapshot_returns_empty_list(self):
        assert RingBuffer(maxlen=5).snapshot() == []

    def test_empty_buffer_len_is_zero(self):
        assert len(RingBuffer(maxlen=5)) == 0

    def test_maxlen_one_keeps_only_last_appended(self):
        buf = RingBuffer(maxlen=1)
        buf.append(**_item("a", "first"))
        buf.append(**_item("b", "second"))
        snap = buf.snapshot()
        assert len(snap) == 1
        assert snap[0]["username"] == "b"

    def test_ten_appends_to_maxlen_three_keeps_last_three_in_order(self):
        buf = RingBuffer(maxlen=3)
        for i in range(10):
            buf.append(**_item(f"u{i}", f"msg{i}"))
        snap = buf.snapshot()
        assert len(snap) == 3
        assert [s["username"] for s in snap] == ["u7", "u8", "u9"]

    def test_snapshot_is_independent_copy(self):
        """Clearing the returned list must not affect the internal buffer."""
        buf = RingBuffer(maxlen=5)
        buf.append(**_item("alice", "hello"))
        snap = buf.snapshot()
        snap.clear()
        assert len(buf) == 1
        assert len(buf.snapshot()) == 1

    def test_snapshot_preserves_oldest_first_after_eviction(self):
        buf = RingBuffer(maxlen=3)
        for i in range(5):
            buf.append(**_item(f"u{i}", f"m{i}"))
        snap = buf.snapshot()
        assert snap[0]["username"] == "u2"
        assert snap[-1]["username"] == "u4"

    def test_append_stores_all_fields_exactly(self):
        buf = RingBuffer(maxlen=5)
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        buf.append(
            username="bob", display_name="Bob Smith",
            user_id=777, text="¡Gol!", timestamp=ts,
        )
        item = buf.snapshot()[0]
        assert item["username"] == "bob"
        assert item["display_name"] == "Bob Smith"
        assert item["user_id"] == 777
        assert item["text"] == "¡Gol!"
        assert item["timestamp"] == ts

    def test_len_tracks_evictions_correctly(self):
        buf = RingBuffer(maxlen=5)
        for i in range(7):
            buf.append(**_item(f"u{i}", f"m{i}"))
        assert len(buf) == 5  # capped at maxlen


# ── ChatState — persisted metadata only (no message text) ────────────────────


class TestChatStateNoPersistText:
    def test_json_file_has_no_text_key_at_any_nesting_level(self, tmp_path):
        """Privacy guarantee: save_chat_state must NEVER write message text."""
        path = str(tmp_path / "state.json")
        state = ChatState(
            last_seen={"alice": "2026-06-30T10:00:00+00:00"},
            last_mentioned={"bob": "2026-06-28T08:00:00+00:00"},
            picante_last_ts=12345.0,
            picante_daily_count=7,
            picante_last_date="2026-06-30",
            rotate_index=3,
        )
        save_chat_state(path, state)
        raw: dict = json.loads(open(path, encoding="utf-8").read())

        allowed_keys = {
            "last_seen", "last_mentioned", "picante_last_ts",
            "picante_daily_count", "picante_last_date", "rotate_index",
        }
        assert set(raw.keys()) == allowed_keys

        def _has_text_key(obj) -> bool:
            if isinstance(obj, dict):
                return "text" in obj or any(_has_text_key(v) for v in obj.values())
            if isinstance(obj, list):
                return any(_has_text_key(v) for v in obj)
            return False

        assert not _has_text_key(raw), "Found 'text' key in persisted state — PRIVACY VIOLATION"

    def test_load_empty_json_object_returns_defaults(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{}", encoding="utf-8")
        state = load_chat_state(str(path))
        assert state.last_seen == {}
        assert state.last_mentioned == {}
        assert state.picante_last_ts == 0.0
        assert state.picante_daily_count == 0
        assert state.picante_last_date == ""
        assert state.rotate_index == 0

    def test_load_null_fields_return_defaults(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({
                "last_seen": None, "last_mentioned": None,
                "picante_last_ts": None, "picante_daily_count": None,
                "picante_last_date": None, "rotate_index": None,
            }),
            encoding="utf-8",
        )
        state = load_chat_state(str(path))
        assert state.last_seen == {}
        assert state.last_mentioned == {}
        assert state.picante_last_ts == 0.0
        assert state.picante_daily_count == 0
        assert state.rotate_index == 0

    def test_load_empty_file_content_returns_defaults(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("", encoding="utf-8")
        state = load_chat_state(str(path))
        assert state.last_seen == {}

    def test_atomic_write_leaves_no_tmp_file(self, tmp_path):
        path = str(tmp_path / "chat_state.json")
        save_chat_state(path, ChatState(rotate_index=99))
        assert not os.path.exists(f"{path}.tmp")
        assert os.path.exists(path)

    def test_roundtrip_preserves_last_seen_and_last_mentioned(self, tmp_path):
        path = str(tmp_path / "state.json")
        state = ChatState(
            last_seen={"user1": "2026-06-30T10:00:00+00:00", "user2": "2026-06-29T08:00:00+00:00"},
            last_mentioned={"user3": "2026-06-28T12:00:00+00:00"},
            rotate_index=5,
        )
        save_chat_state(path, state)
        loaded = load_chat_state(path)
        assert loaded.last_seen == state.last_seen
        assert loaded.last_mentioned == state.last_mentioned
        assert loaded.rotate_index == 5


# ── probability_gate — boundary with mocked random ───────────────────────────


class TestProbabilityGateBoundary:
    def test_zero_probability_never_fires(self):
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.5):
            assert probability_gate(0.0) is False

    def test_unit_probability_always_fires(self):
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.9999):
            assert probability_gate(1.0) is True

    def test_exactly_at_threshold_does_not_fire(self):
        # gate uses strict <, so random == probability → False
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.2):
            assert probability_gate(0.2) is False

    def test_just_below_threshold_fires(self):
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.1999):
            assert probability_gate(0.2) is True

    def test_just_above_threshold_does_not_fire(self):
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.2001):
            assert probability_gate(0.2) is False


# ── cooldown_gate — extra boundary cases ─────────────────────────────────────


class TestCooldownGateBoundary:
    def test_one_second_below_cooldown_blocked(self):
        assert cooldown_gate(1000.0, 300, 1299.0) is False

    def test_one_second_above_cooldown_allowed(self):
        assert cooldown_gate(1000.0, 300, 1301.0) is True

    def test_no_time_elapsed_blocked(self):
        assert cooldown_gate(1000.0, 1, 1000.0) is False

    def test_zero_cooldown_always_passes(self):
        assert cooldown_gate(1000.0, 0, 1000.0) is True


# ── daily_cap_gate — extra boundary cases ────────────────────────────────────


class TestDailyCapGateBoundary:
    def test_one_under_cap_allowed(self):
        assert daily_cap_gate(29, 30, "2026-06-30", "2026-06-30") is True

    def test_count_zero_on_same_day_allowed(self):
        assert daily_cap_gate(0, 30, "2026-06-30", "2026-06-30") is True

    def test_rollover_with_very_high_count_passes(self):
        assert daily_cap_gate(999, 1, "2026-06-29", "2026-06-30") is True

    def test_max_per_day_one_first_send_allowed(self):
        assert daily_cap_gate(0, 1, "2026-06-30", "2026-06-30") is True

    def test_max_per_day_one_second_send_blocked(self):
        assert daily_cap_gate(1, 1, "2026-06-30", "2026-06-30") is False


# ── min_buffer_gate — extra boundary cases ────────────────────────────────────


class TestMinBufferGateBoundary:
    def test_one_below_min_blocked(self):
        assert min_buffer_gate(4, 5) is False

    def test_exact_min_allowed(self):
        assert min_buffer_gate(5, 5) is True

    def test_one_above_min_allowed(self):
        assert min_buffer_gate(6, 5) is True

    def test_zero_buffer_zero_min_allowed(self):
        assert min_buffer_gate(0, 0) is True


# ── Listener — null guard tests ───────────────────────────────────────────────


class TestListenerNullGuards:
    async def test_none_effective_message_ignored_no_crash(self):
        update = MagicMock()
        update.effective_message = None
        ctx = MagicMock()
        ctx.bot_data = {
            "settings": Settings(telegram_bot_token="tok", football_data_api_key="key"),
        }
        # Must not raise
        await on_group_text(update, ctx)

    async def test_none_effective_user_ignored_no_crash(self):
        msg = _make_msg(text="Mensaje largo y válido aquí")
        update = MagicMock()
        update.effective_message = msg
        update.effective_user = None
        ctx = MagicMock()
        ctx.bot_data = {
            "settings": Settings(
                telegram_bot_token="tok",
                football_data_api_key="key",
                telegram_group_id=_GROUP_ID,
            ),
        }
        buf = RingBuffer(maxlen=10)
        ctx.bot_data["chat_buffer"] = buf
        ctx.bot_data["chat_state"] = ChatState()
        ctx.bot_data["chat_state_path"] = ""
        ctx.bot_data["ai_client"] = None
        # Must not raise; buffer must stay empty
        await on_group_text(update, ctx)
        assert len(buf) == 0


# ── Listener — command rejection ─────────────────────────────────────────────


class TestListenerCommandRejection:
    @pytest.mark.parametrize("cmd", ["/tongo", "/listaaciertosactual", "/siguiente", "/start"])
    async def test_slash_command_rejected(self, cmd):
        msg = _make_msg(text=cmd)
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_command_with_leading_whitespace_rejected(self):
        msg = _make_msg(text="  /tongo@bot")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_command_with_args_rejected(self):
        msg = _make_msg(text="/simula_gol Argentina Spain")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0


# ── Listener — media rejection ────────────────────────────────────────────────


class TestListenerMediaRejection:
    @pytest.mark.parametrize("field", [
        "photo", "video", "animation", "sticker",
        "document", "voice", "video_note", "audio",
    ])
    async def test_each_media_type_individually_rejected(self, field):
        """Every distinct media field triggers rejection."""
        msg = _make_msg(text="", **{field: MagicMock()})
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0, f"Media field '{field}' should have been rejected"

    async def test_photo_with_long_caption_rejected(self):
        """A well-formed caption must NOT sneak through when a photo is present."""
        msg = _make_msg(text="Qué partido tan increíble, mira este momento!", photo=MagicMock())
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_video_with_caption_rejected(self):
        msg = _make_msg(text="Este video es increíble, mira qué golazo más épico!", video=MagicMock())
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_sticker_with_none_text_rejected(self):
        msg = _make_msg(text=None, sticker=MagicMock())
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0


# ── Listener — text length / content rejection ────────────────────────────────


class TestListenerTextRejection:
    async def test_none_text_rejected(self):
        msg = _make_msg(text=None)
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_empty_text_rejected(self):
        msg = _make_msg(text="")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_whitespace_only_rejected(self):
        msg = _make_msg(text="     ")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_newlines_only_rejected(self):
        msg = _make_msg(text="\n\n\t\n")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_four_char_text_rejected(self):
        msg = _make_msg(text="Hola")  # 4 chars < threshold of 5
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_five_char_text_accepted(self):
        msg = _make_msg(text="Hola!")  # exactly 5 chars — passes
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 1


# ── Listener — chat_id filter ─────────────────────────────────────────────────


class TestListenerChatIdFilter:
    async def test_wrong_chat_id_rejected(self):
        msg = _make_msg(chat_id="-9999999999", text="Hola, esto es texto normal!")
        settings = Settings(
            telegram_bot_token="tok", football_data_api_key="key",
            telegram_group_id=_GROUP_ID,
        )
        update, ctx, buf, _ = _make_listener_ctx(msg=msg, settings=settings)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_correct_chat_id_accepted(self):
        msg = _make_msg(chat_id=_GROUP_ID, text="Hola, esto es texto normal!")
        settings = Settings(
            telegram_bot_token="tok", football_data_api_key="key",
            telegram_group_id=_GROUP_ID,
        )
        update, ctx, buf, _ = _make_listener_ctx(msg=msg, settings=settings)
        await on_group_text(update, ctx)
        assert len(buf) == 1

    async def test_no_group_id_configured_accepts_any_chat(self):
        """When telegram_group_id is None the chat-id guard is skipped."""
        msg = _make_msg(chat_id="-9999999999", text="Hola, esto es texto!")
        settings = Settings(
            telegram_bot_token="tok", football_data_api_key="key",
            telegram_group_id=None,
        )
        update, ctx, buf, _ = _make_listener_ctx(msg=msg, settings=settings)
        await on_group_text(update, ctx)
        assert len(buf) == 1


# ── Listener — bot-own-message rejection ─────────────────────────────────────


class TestListenerBotRejection:
    async def test_bot_own_message_rejected(self):
        msg = _make_msg(text="Soy el bot y dije algo largo")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg, user_id=999, bot_id=999)
        await on_group_text(update, ctx)
        assert len(buf) == 0

    async def test_non_bot_user_not_rejected_on_id(self):
        msg = _make_msg(text="Mensaje válido de usuario normal")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg, user_id=42, bot_id=999)
        await on_group_text(update, ctx)
        assert len(buf) == 1


# ── Listener — acceptance path ────────────────────────────────────────────────


class TestListenerAcceptance:
    async def test_valid_text_recorded_in_buffer(self):
        msg = _make_msg(text="Que buen gol el de Yamal!")
        update, ctx, buf, _ = _make_listener_ctx(msg=msg)
        await on_group_text(update, ctx)
        assert len(buf) == 1
        assert buf.snapshot()[0]["text"] == "Que buen gol el de Yamal!"

    async def test_valid_text_updates_last_seen(self):
        msg = _make_msg(text="Que buen gol el de Yamal!")
        update, ctx, buf, state = _make_listener_ctx(msg=msg, username="alice")
        await on_group_text(update, ctx)
        assert "alice" in state.last_seen

    async def test_username_stored_lowercase_in_buffer_and_state(self):
        msg = _make_msg(text="Hola, buenos días todos!")
        update, ctx, buf, state = _make_listener_ctx(msg=msg, username="ALICE")
        update.effective_user.username = "ALICE"
        await on_group_text(update, ctx)
        snap = buf.snapshot()
        assert snap[0]["username"] == "alice"
        assert "alice" in state.last_seen

    async def test_user_without_username_not_in_last_seen(self):
        """username=None → empty-string key must NOT be stored in last_seen."""
        msg = _make_msg(text="Hola, buenos días a todos!")
        update, ctx, buf, state = _make_listener_ctx(msg=msg, username=None)
        await on_group_text(update, ctx)
        assert len(buf) == 1
        assert "" not in state.last_seen

    async def test_buffer_accumulates_across_multiple_calls(self):
        _, ctx, buf, _ = _make_listener_ctx()
        texts = ["Mensaje uno de prueba!", "Mensaje dos de prueba!"]
        for i, text in enumerate(texts):
            msg = _make_msg(text=text)
            update = MagicMock()
            update.effective_message = msg
            update.message = msg
            update.effective_user = MagicMock()
            update.effective_user.id = 40 + i
            update.effective_user.username = f"user{i}"
            update.effective_user.full_name = f"User {i}"
            await on_group_text(update, ctx)
        assert len(buf) == 2


# ── maybe_reply — orchestrator ────────────────────────────────────────────────


class TestMaybeReply:
    def _setup(self, tmp_path, **setting_overrides):
        settings = _ai_settings(**setting_overrides)
        buf = RingBuffer(maxlen=30)
        for i in range(5):
            buf.append(**_item(f"u{i}", f"mensaje {i} de prueba para contexto"))
        state = ChatState(picante_last_ts=0.0, picante_daily_count=0, picante_last_date="")
        state_path = str(tmp_path / "state.json")

        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()

        ai = MagicMock()
        ai.complete = AsyncMock(return_value="¡Qué jugada más picante!")

        return settings, buf, state, state_path, update, ai

    async def test_all_gates_pass_ai_called_and_reply_sent(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        ai.complete.assert_called_once()
        update.message.reply_text.assert_called_once_with("¡Qué jugada más picante!", parse_mode=None)

    async def test_all_gates_pass_counters_updated(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            with patch("worldcup_bot.chat.picante.time.time", return_value=9999.0):
                await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        assert state.picante_last_ts == 9999.0
        assert state.picante_daily_count == 1
        assert state.picante_last_date != ""

    async def test_new_day_resets_count_to_one(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        state.picante_daily_count = 10
        state.picante_last_date = "2026-06-29"  # yesterday
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        assert state.picante_daily_count == 1

    async def test_same_day_increments_count(self, tmp_path):
        import pytz
        tz = pytz.timezone("Europe/Madrid")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        state.picante_daily_count = 5
        state.picante_last_date = today
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        assert state.picante_daily_count == 6

    async def test_min_buffer_gate_fail_no_ai_call(self, tmp_path):
        settings, _, state, sp, update, ai = self._setup(tmp_path, picante_min_buffer=100)
        buf = RingBuffer(maxlen=30)  # empty — fails min_buffer gate
        await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        ai.complete.assert_not_called()
        update.message.reply_text.assert_not_called()

    async def test_cooldown_gate_fail_no_ai_call(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(
            tmp_path, picante_cooldown_seconds=3600
        )
        state.picante_last_ts = 1_000_000.0
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            with patch("worldcup_bot.chat.picante.time.time", return_value=1_000_001.0):
                await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        ai.complete.assert_not_called()

    async def test_daily_cap_gate_fail_no_ai_call(self, tmp_path):
        import pytz
        tz = pytz.timezone("Europe/Madrid")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        settings, buf, state, sp, update, ai = self._setup(tmp_path, picante_max_per_day=5)
        state.picante_daily_count = 5
        state.picante_last_date = today
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        ai.complete.assert_not_called()

    async def test_probability_gate_fail_no_ai_call(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(
            tmp_path, picante_probability=0.1
        )
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.9):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        ai.complete.assert_not_called()

    async def test_ai_error_no_crash_no_reply(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        ai.complete = AsyncMock(side_effect=AIError("rate limit"))
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        update.message.reply_text.assert_not_called()

    async def test_unexpected_exception_no_crash(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        ai.complete = AsyncMock(side_effect=RuntimeError("something went wrong"))
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            # Must not propagate
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)

    async def test_reply_text_receives_exact_ai_output(self, tmp_path):
        settings, buf, state, sp, update, ai = self._setup(tmp_path)
        ai.complete = AsyncMock(return_value="Texto especial pícaro 🌶️")
        with patch("worldcup_bot.chat.picante.random.random", return_value=0.0):
            await maybe_reply(update, MagicMock(), buf, state, sp, settings, ai)
        update.message.reply_text.assert_called_once_with("Texto especial pícaro 🌶️", parse_mode=None)


# ── compute_inactive_candidates — boundary + edge cases ───────────────────────


class TestComputeInactiveCandidatesEdgeCases:
    _now = datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)

    def _ts(self, days: float = 0, seconds: int = 0) -> str:
        return (self._now - timedelta(days=days, seconds=seconds)).isoformat()

    def test_exactly_at_inactivity_boundary_is_not_inactive(self):
        """(now - seen) == inactive_days → NOT strictly > → still considered active."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=3, seconds=0)},
            last_mentioned={}, porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" not in candidates

    def test_one_second_over_inactivity_boundary_is_candidate(self):
        """3 days + 1 s → strictly > 3 days → inactive."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=3, seconds=1)},
            last_mentioned={}, porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_exactly_at_mention_cooldown_still_excluded(self):
        """(now - mentioned) == cooldown_days → <= cooldown → excluded."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=10)},
            last_mentioned={"alice": self._ts(days=2, seconds=0)},
            porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" not in candidates

    def test_one_second_over_mention_cooldown_is_candidate(self):
        """2 days + 1 s since mention → cooldown expired → now a candidate."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=10)},
            last_mentioned={"alice": self._ts(days=2, seconds=1)},
            porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_user_absent_from_last_seen_is_immediately_inactive(self):
        """No entry in last_seen → treated as inactive regardless of elapsed time."""
        candidates = compute_inactive_candidates(
            last_seen={}, last_mentioned={},
            porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_non_porra_participant_who_spoke_is_never_a_candidate(self):
        """'outsider' spoke and is inactive, but not in porra_usernames → excluded."""
        candidates = compute_inactive_candidates(
            last_seen={"outsider": self._ts(days=10)},
            last_mentioned={}, porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "outsider" not in candidates

    def test_all_participants_active_returns_empty_list(self):
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=1), "bob": self._ts(days=0)},
            last_mentioned={}, porra_usernames=["alice", "bob"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert candidates == []

    def test_corrupt_last_seen_timestamp_treated_as_inactive(self):
        """Unparseable ISO → inactive=True per the except-pass fallback."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": "NOT-A-DATE"},
            last_mentioned={}, porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_corrupt_last_mentioned_skips_cooldown_allows_candidate(self):
        """Unparseable last_mentioned → cooldown check skipped → user is a candidate."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=10)},
            last_mentioned={"alice": "INVALID-DATE"},
            porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" in candidates

    def test_empty_porra_list_returns_empty(self):
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=10)},
            last_mentioned={}, porra_usernames=[],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert candidates == []

    def test_multiple_inactive_users_sorted_alphabetically(self):
        candidates = compute_inactive_candidates(
            last_seen={u: self._ts(days=5) for u in ["zara", "alice", "mike"]},
            last_mentioned={}, porra_usernames=["zara", "alice", "mike"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert candidates == ["alice", "mike", "zara"]

    def test_seeded_user_within_inactive_threshold_not_candidate(self):
        """Startup-seeded user (1 day ago, threshold 3 days) → not inactive."""
        candidates = compute_inactive_candidates(
            last_seen={"alice": self._ts(days=1)},
            last_mentioned={}, porra_usernames=["alice"],
            now=self._now, inactive_days=3, mention_cooldown_days=2,
        )
        assert "alice" not in candidates


# ── select_candidate — edge cases ─────────────────────────────────────────────


class TestSelectCandidateEdgeCases:
    def test_large_rotate_index_wraps_correctly(self):
        candidates = ["alice", "bob", "charlie"]
        username, new_idx = select_candidate(candidates, rotate_index=100)
        assert username == candidates[100 % 3]
        assert new_idx == 101

    def test_single_candidate_always_selected_and_index_always_increments(self):
        for i in range(10):
            username, new_idx = select_candidate(["only"], rotate_index=i)
            assert username == "only"
            assert new_idx == i + 1

    def test_consecutive_calls_cycle_through_all_candidates(self):
        candidates = ["a", "b", "c"]
        idx = 0
        results = []
        for _ in range(6):
            username, idx = select_candidate(candidates, idx)
            results.append(username)
        assert results == ["a", "b", "c", "a", "b", "c"]

    def test_rotate_index_one_beyond_length_wraps_to_second(self):
        candidates = ["x", "y"]
        username, _ = select_candidate(candidates, rotate_index=3)
        assert username == "y"  # 3 % 2 == 1


# ── revive_inactive_job ───────────────────────────────────────────────────────

_TZ_MADRID = pytz.timezone("Europe/Madrid")


def _frozen_datetime_active_cls() -> type:
    """Return a datetime subclass frozen to today at 14:00 Madrid.

    Using today's date (not a hardcoded one) keeps the frozen 'now' close
    enough to real-now that _inactive_ts(days=5) timestamps remain > 3 days
    stale from the frozen perspective.  Hour 14 is always outside the default
    quiet window (23→06).
    """
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    now_madrid = now_utc.astimezone(_TZ_MADRID)
    frozen = _TZ_MADRID.localize(
        _dt.datetime(now_madrid.year, now_madrid.month, now_madrid.day, 14, 0, 0)
    )

    class _FrozenDt(_dt.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return frozen.astimezone(tz)
            return frozen

    return _FrozenDt


class TestReviveInactiveJob:
    def _inactive_ts(self, days: float = 5.0) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def _active_ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @pytest.fixture(autouse=True)
    def _freeze_clock_to_daytime(self):
        """Pin worldcup_bot.chat.revive.datetime to today at 14:00 Madrid.

        Ensures every test in this class runs as if it's midday — always
        outside the default quiet window (23:00–06:00) — regardless of when
        the test suite actually executes.
        """
        with patch("worldcup_bot.chat.revive.datetime", _frozen_datetime_active_cls()):
            yield

    async def test_sends_message_prefixed_with_at_username(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_called_once()
        text = ctx.bot.send_message.call_args.kwargs["text"]
        assert text.startswith("@alice ")

    async def test_parse_mode_is_none(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        pm = ctx.bot.send_message.call_args.kwargs["parse_mode"]
        assert pm is None

    async def test_updates_last_mentioned_in_state(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        state: ChatState = ctx.bot_data["chat_state"]
        await revive_inactive_job(ctx)
        assert "alice" in state.last_mentioned

    async def test_persists_last_mentioned_to_disk(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=state_path,
        )
        await revive_inactive_job(ctx)
        assert os.path.exists(state_path)
        raw = json.loads(open(state_path, encoding="utf-8").read())
        assert "alice" in raw.get("last_mentioned", {})

    async def test_advances_rotate_index(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice", "bob"],
            last_seen={"alice": self._inactive_ts(), "bob": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        state: ChatState = ctx.bot_data["chat_state"]
        assert state.rotate_index == 0
        await revive_inactive_job(ctx)
        assert state.rotate_index == 1

    async def test_no_candidates_no_send_message(self, tmp_path):
        """All users recently active → no candidates → no send_message call."""
        ctx = _make_revive_ctx(
            porra_usernames=["alice", "bob"],
            last_seen={"alice": self._active_ts(), "bob": self._active_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_revive_disabled_no_op(self, tmp_path):
        settings = _ai_settings(chat_revive_enabled=False)
        ctx = _make_revive_ctx(
            settings=settings,
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_ai_not_configured_no_op(self, tmp_path):
        settings = Settings(
            telegram_bot_token="tok", football_data_api_key="key",
            telegram_group_id=_GROUP_ID,
            chat_revive_enabled=True,
            # no openai_* fields → ai_enabled() == False
        )
        ctx = _make_revive_ctx(
            settings=settings,
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_ai_client_none_no_op(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"] = None
        await revive_inactive_job(ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_ai_error_no_crash_no_send(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"].complete = AsyncMock(side_effect=AIError("oops"))
        await revive_inactive_job(ctx)  # must not raise
        ctx.bot.send_message.assert_not_called()

    async def test_unexpected_exception_no_crash(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        ctx.bot_data["ai_client"].complete = AsyncMock(side_effect=ValueError("unexpected"))
        await revive_inactive_job(ctx)  # must not raise

    async def test_uses_porra_display_name_in_ai_prompt(self, tmp_path):
        ctx = _make_revive_ctx(
            porra_usernames=["alice"],
            porra_display={"alice": "Alice Wonderland"},
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        user_msg = ctx.bot_data["ai_client"].complete.call_args.args[1]
        assert "Alice Wonderland" in user_msg

    async def test_sends_to_configured_group_id(self, tmp_path):
        settings = _ai_settings(telegram_group_id="-9998887776")
        ctx = _make_revive_ctx(
            settings=settings,
            porra_usernames=["alice"],
            last_seen={"alice": self._inactive_ts()},
            state_path=str(tmp_path / "state.json"),
        )
        await revive_inactive_job(ctx)
        chat_id = ctx.bot.send_message.call_args.kwargs["chat_id"]
        assert chat_id == "-9998887776"
