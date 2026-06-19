"""Tests for the templated tongo phrase system.

Covers: hot-reload loader, render_tongo, build_tongo_context,
phrase_eligible / phrase_uses_reply, and the templated cmd_tongo handler paths.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import worldcup_bot.data.tongo as _tongo_mod
from worldcup_bot.data.tongo import (
    FRASES,
    TongoContext,
    build_tongo_context,
    load_tongo_phrases,
    phrase_eligible,
    phrase_uses_reply,
    render_tongo,
)
from worldcup_bot.bot.handlers import cmd_tongo
from worldcup_bot.config import Settings


# ── helpers ────────────────────────────────────────────────────────────────────


def _fake_user(
    first_name: str = "Alice",
    last_name: str | None = None,
    username: str | None = "alice",
    user_id: int = 111,
    is_bot: bool = False,
) -> SimpleNamespace:
    full = (first_name + " " + last_name).strip() if last_name else first_name
    return SimpleNamespace(
        first_name=first_name,
        last_name=last_name,
        full_name=full,
        username=username,
        id=user_id,
        is_bot=is_bot,
    )


def _fake_update(
    user: object | None = None,
    reply_user: object | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace update.  reply_user=None → no reply message."""
    sender = user if user is not None else _fake_user()
    msg = SimpleNamespace()
    if reply_user is not None:
        reply_msg = SimpleNamespace(from_user=reply_user)
        msg.reply_to_message = reply_msg
    else:
        msg.reply_to_message = None
    return SimpleNamespace(effective_user=sender, message=msg)


def _make_update_mock(
    first_name: str = "Alice",
    has_reply: bool = False,
    reply_first: str = "Bob",
) -> MagicMock:
    """Create a MagicMock Update for handler tests."""
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    update.effective_user.first_name = first_name
    update.effective_user.last_name = None
    update.effective_user.full_name = first_name
    update.effective_user.username = first_name.lower()
    update.effective_user.id = 111
    if has_reply:
        reply_user = MagicMock()
        reply_user.first_name = reply_first
        reply_user.last_name = None
        reply_user.full_name = reply_first
        reply_user.username = reply_first.lower()
        reply_user.id = 222
        reply_user.is_bot = False
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.from_user = reply_user
    else:
        update.message.reply_to_message = None
    return update


def _make_context(settings: Settings) -> MagicMock:
    context = MagicMock()
    context.bot_data = {"settings": settings}
    context.args = []
    context.bot.send_animation = AsyncMock()
    return context


def _phrase_settings(phrases_path: str = "") -> Settings:
    return Settings(
        telegram_bot_token="fake",
        football_data_api_key="fake",
        predictions_path="fake_predictions.yml",
        tongo_phrases_path=phrases_path,
    )


# ══════════════════════════════════════════════════════════════════════════════
# load_tongo_phrases — hot-reload loader
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadTongoPhrases:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Isolate module-level cache between tests."""
        _tongo_mod._cached_path = None
        _tongo_mod._cached_mtime = 0.0
        _tongo_mod._cached_data = []
        yield
        _tongo_mod._cached_path = None
        _tongo_mod._cached_mtime = 0.0
        _tongo_mod._cached_data = []

    def test_comments_and_blanks_skipped(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("# comentario\n\nfrase real\n  \n# otro\n", encoding="utf-8")
        result = load_tongo_phrases(str(f))
        assert result == ["frase real"]

    def test_missing_file_returns_frases(self):
        result = load_tongo_phrases("/nonexistent/path/TongoPhrases.txt")
        assert result is FRASES

    def test_empty_file_returns_frases(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("# solo comentarios\n\n", encoding="utf-8")
        result = load_tongo_phrases(str(f))
        assert result is FRASES

    def test_only_comments_returns_frases(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("# línea 1\n# línea 2\n", encoding="utf-8")
        result = load_tongo_phrases(str(f))
        assert result is FRASES

    def test_valid_file_returns_phrases(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("frase uno\nfrase dos\n", encoding="utf-8")
        result = load_tongo_phrases(str(f))
        assert result == ["frase uno", "frase dos"]

    def test_strips_whitespace(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("  espacios  \n   otro   \n", encoding="utf-8")
        result = load_tongo_phrases(str(f))
        assert result == ["espacios", "otro"]

    def test_hot_reload_picks_up_new_content(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("primera\n", encoding="utf-8")
        result1 = load_tongo_phrases(str(f))
        assert result1 == ["primera"]

        # Overwrite and bump mtime so the cache is invalidated
        f.write_text("segunda\n", encoding="utf-8")
        os.utime(str(f), (time.time() + 2, time.time() + 2))

        result2 = load_tongo_phrases(str(f))
        assert result2 == ["segunda"]

    def test_cache_used_on_second_call_same_mtime(self, tmp_path):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("cached\n", encoding="utf-8")
        result1 = load_tongo_phrases(str(f))
        # Corrupt the module cache directly — second call should return cached
        _tongo_mod._cached_data = ["cached"]
        result2 = load_tongo_phrases(str(f))
        assert result1 == result2

    def test_never_raises_on_oserror(self, tmp_path, monkeypatch):
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("frase\n", encoding="utf-8")
        monkeypatch.setattr(os.path, "getmtime", lambda _: (_ for _ in ()).throw(OSError("boom")))
        result = load_tongo_phrases(str(f))
        assert result is FRASES


# ══════════════════════════════════════════════════════════════════════════════
# render_tongo
# ══════════════════════════════════════════════════════════════════════════════


class TestRenderTongo:
    def _ctx(self, **kwargs) -> TongoContext:
        defaults = dict(
            first_name="Ana",
            last_name="García",
            full_name="Ana García",
            username="ana",
            id="100",
            reply_to_first_name="Luis",
            reply_to_last_name="Pérez",
            reply_to_full_name="Luis Pérez",
            reply_to_username="luis",
            reply_to_id="200",
            has_reply=True,
        )
        defaults.update(kwargs)
        return TongoContext(**defaults)

    def test_first_name(self):
        ctx = self._ctx()
        assert render_tongo("Hola {{first_name}}!", ctx) == "Hola Ana!"

    def test_last_name(self):
        ctx = self._ctx()
        assert render_tongo("Apellido: {{last_name}}", ctx) == "Apellido: García"

    def test_full_name(self):
        ctx = self._ctx()
        assert render_tongo("{{full_name}} al poder", ctx) == "Ana García al poder"

    def test_username(self):
        ctx = self._ctx()
        assert render_tongo("@{{username}}", ctx) == "@ana"

    def test_id(self):
        ctx = self._ctx()
        assert render_tongo("id={{id}}", ctx) == "id=100"

    def test_reply_to_first_name(self):
        ctx = self._ctx()
        assert render_tongo("{{reply_to_first_name}} hace trampa", ctx) == "Luis hace trampa"

    def test_reply_to_last_name(self):
        ctx = self._ctx()
        assert render_tongo("{{reply_to_last_name}}", ctx) == "Pérez"

    def test_reply_to_full_name(self):
        ctx = self._ctx()
        assert render_tongo("{{reply_to_full_name}}", ctx) == "Luis Pérez"

    def test_reply_to_username(self):
        ctx = self._ctx()
        assert render_tongo("@{{reply_to_username}}", ctx) == "@luis"

    def test_reply_to_id(self):
        ctx = self._ctx()
        assert render_tongo("id={{reply_to_id}}", ctx) == "id=200"

    def test_missing_last_name_renders_empty(self):
        ctx = self._ctx(last_name="")
        assert render_tongo("{{last_name}}", ctx) == ""

    def test_full_name_single_when_no_last(self):
        ctx = self._ctx(last_name="", full_name="Ana")
        assert render_tongo("{{full_name}}", ctx) == "Ana"

    def test_unknown_placeholder_renders_empty(self):
        ctx = self._ctx()
        assert render_tongo("{{unknown_var}}", ctx) == ""

    def test_spaced_placeholder_tolerant(self):
        ctx = self._ctx()
        assert render_tongo("{{ first_name }}", ctx) == "Ana"
        assert render_tongo("{{  last_name  }}", ctx) == "García"

    def test_no_placeholders_returns_unchanged(self):
        ctx = self._ctx()
        assert render_tongo("Frase sin variables.", ctx) == "Frase sin variables."

    def test_multiple_placeholders_in_one_phrase(self):
        ctx = self._ctx()
        result = render_tongo("{{first_name}} vs {{reply_to_first_name}}", ctx)
        assert result == "Ana vs Luis"


# ══════════════════════════════════════════════════════════════════════════════
# build_tongo_context
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildTongoContext:
    def test_plain_no_reply(self):
        update = _fake_update(_fake_user(first_name="David", username="david"))
        ctx = build_tongo_context(update)
        assert ctx.first_name == "David"
        assert ctx.username == "david"
        assert ctx.has_reply is False
        assert ctx.reply_to_first_name == ""
        assert ctx.reply_to_id == ""

    def test_with_last_name(self):
        update = _fake_update(_fake_user(first_name="Ana", last_name="García"))
        ctx = build_tongo_context(update)
        assert ctx.last_name == "García"
        assert ctx.full_name == "Ana García"

    def test_no_last_name_full_name_equals_first(self):
        update = _fake_update(_fake_user(first_name="DrDonoso", last_name=None))
        ctx = build_tongo_context(update)
        assert ctx.last_name == ""
        assert ctx.full_name == "DrDonoso"

    def test_id_converted_to_string(self):
        update = _fake_update(_fake_user(user_id=42))
        ctx = build_tongo_context(update)
        assert ctx.id == "42"

    def test_with_reply(self):
        reply = _fake_user(first_name="Carlos", username="carlos", user_id=999)
        update = _fake_update(_fake_user(), reply_user=reply)
        ctx = build_tongo_context(update)
        assert ctx.has_reply is True
        assert ctx.reply_to_first_name == "Carlos"
        assert ctx.reply_to_username == "carlos"
        assert ctx.reply_to_id == "999"

    def test_reply_to_bot_still_populated(self):
        """is_bot=True must NOT prevent reply vars from being populated."""
        bot_user = _fake_user(first_name="MyBot", username="mybot", is_bot=True)
        update = _fake_update(_fake_user(), reply_user=bot_user)
        ctx = build_tongo_context(update)
        assert ctx.has_reply is True
        assert ctx.reply_to_first_name == "MyBot"

    def test_message_is_none_guarded(self):
        """If update.message is None, has_reply must be False and no exception."""
        update = SimpleNamespace(
            effective_user=_fake_user(),
            message=None,
        )
        ctx = build_tongo_context(update)
        assert ctx.has_reply is False
        assert ctx.reply_to_first_name == ""

    def test_none_username_maps_to_empty(self):
        update = _fake_update(_fake_user(username=None))
        ctx = build_tongo_context(update)
        assert ctx.username == ""

    def test_reply_to_none_username_maps_to_empty(self):
        reply = _fake_user(username=None)
        update = _fake_update(_fake_user(), reply_user=reply)
        ctx = build_tongo_context(update)
        assert ctx.reply_to_username == ""


# ══════════════════════════════════════════════════════════════════════════════
# phrase_uses_reply / phrase_eligible
# ══════════════════════════════════════════════════════════════════════════════


class TestPhraseUsesReply:
    def test_with_reply_var(self):
        assert phrase_uses_reply("Hola {{reply_to_first_name}}") is True

    def test_with_spaced_reply_var(self):
        assert phrase_uses_reply("{{  reply_to_username  }}") is True

    def test_without_reply_var(self):
        assert phrase_uses_reply("Hola {{first_name}}") is False

    def test_no_placeholders(self):
        assert phrase_uses_reply("Sin variables.") is False


class TestPhraseEligible:
    def _ctx(self, has_reply: bool) -> TongoContext:
        return TongoContext(has_reply=has_reply)

    def test_reply_phrase_ineligible_without_reply(self):
        assert phrase_eligible("{{reply_to_first_name}}", self._ctx(has_reply=False)) is False

    def test_reply_phrase_eligible_with_reply(self):
        assert phrase_eligible("{{reply_to_first_name}}", self._ctx(has_reply=True)) is True

    def test_sender_phrase_always_eligible(self):
        assert phrase_eligible("{{first_name}}", self._ctx(has_reply=False)) is True
        assert phrase_eligible("{{first_name}}", self._ctx(has_reply=True)) is True

    def test_plain_phrase_always_eligible(self):
        assert phrase_eligible("Sin variables", self._ctx(has_reply=False)) is True
        assert phrase_eligible("Sin variables", self._ctx(has_reply=True)) is True


# ══════════════════════════════════════════════════════════════════════════════
# cmd_tongo — templated handler paths
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdTongoTemplating:
    """Tests for the templated phrase paths in cmd_tongo."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        _tongo_mod._cached_path = None
        _tongo_mod._cached_mtime = 0.0
        _tongo_mod._cached_data = []
        yield
        _tongo_mod._cached_path = None
        _tongo_mod._cached_mtime = 0.0
        _tongo_mod._cached_data = []

    async def test_sender_first_name_rendered_on_default_path(self, tmp_path):
        """Sender's {{first_name}} is substituted in the output phrase."""
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("Tongo de {{first_name}}!\n", encoding="utf-8")

        update = _make_update_mock("Alice", has_reply=False)
        context = _make_context(_phrase_settings(str(f)))

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.return_value = "Tongo de Alice!"
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Tongo de Alice!"

    async def test_reply_path_renders_replied_persons_name(self, tmp_path):
        """{{reply_to_first_name}} resolves to the replied-to user's first name."""
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("Qué tongo {{reply_to_first_name}}!\n", encoding="utf-8")

        update = _make_update_mock("Alice", has_reply=True, reply_first="Bob")
        context = _make_context(_phrase_settings(str(f)))

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.choice.return_value = "Qué tongo Bob!"
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Qué tongo Bob!"

    async def test_reply_path_pool_contains_rendered_phrase(self, tmp_path):
        """The pool passed to random.choice on the reply path contains rendered phrases."""
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("Ojo con {{reply_to_full_name}}!\n", encoding="utf-8")

        update = _make_update_mock("Alice", has_reply=True, reply_first="Bob")
        context = _make_context(_phrase_settings(str(f)))

        captured_pool = []

        def capture_choice(pool):
            captured_pool.extend(pool)
            return pool[0]

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.choice.side_effect = capture_choice
            await cmd_tongo(update, context)

        assert "Ojo con Bob!" in captured_pool

    async def test_no_reply_phrase_falls_through_to_default_path(self, tmp_path):
        """Even with a reply, if no phrase uses reply vars → default path (SANCHEZ possible)."""
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("Frase sin reply vars.\n", encoding="utf-8")

        update = _make_update_mock("Alice", has_reply=True, reply_first="Bob")
        context = _make_context(_phrase_settings(str(f)))

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.1  # < 1/3 → SANCHEZ
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Sanchez ens roba"

    async def test_sanchez_invariant_preserved_on_default_path(self, tmp_path):
        """random.random() < 1/3 always yields SANCHEZ on the default path."""
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("Una frase.\n", encoding="utf-8")

        update = _make_update_mock("Alice", has_reply=False)
        context = _make_context(_phrase_settings(str(f)))

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.0
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Sanchez ens roba"

    async def test_rendered_phrase_never_contains_raw_braces(self, tmp_path):
        """No {{...}} template syntax should survive to the reply_text call."""
        f = tmp_path / "TongoPhrases.txt"
        f.write_text("Hola {{first_name}} y {{last_name}}.\n", encoding="utf-8")

        update = _make_update_mock("Alice", has_reply=False)
        context = _make_context(_phrase_settings(str(f)))

        captured_pool = []

        def capture_choice(pool):
            captured_pool.extend(p for p in pool if isinstance(p, str))
            return pool[0] if pool else ""

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.side_effect = capture_choice
            await cmd_tongo(update, context)

        for phrase in captured_pool:
            assert "{{" not in phrase, f"Raw template found in pool: {phrase!r}"

    async def test_missing_file_falls_back_to_builtin_frases(self):
        """When TongoPhrases.txt doesn't exist, built-in FRASES are used."""
        update = _make_update_mock("Alice", has_reply=False)
        context = _make_context(_phrase_settings("/nonexistent/TongoPhrases.txt"))

        captured_pool = []

        def capture_choice(pool):
            captured_pool.extend(p for p in pool if isinstance(p, str))
            return pool[0] if pool else ""

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.random.return_value = 0.9
            mock_random.choice.side_effect = capture_choice
            await cmd_tongo(update, context)

        # All built-in FRASES should appear in the pool
        for phrase in FRASES:
            assert phrase in captured_pool

    async def test_gif_fallback_on_reply_path_uses_rendered_phrase(self, tmp_path):
        """GIF send error on reply path falls back to a rendered reply phrase."""
        phrases_file = tmp_path / "TongoPhrases.txt"
        phrases_file.write_text("Trampa de {{reply_to_first_name}}!\n", encoding="utf-8")

        gif_file = tmp_path / "funny.gif"
        gif_file.write_bytes(b"GIF89a")

        update = _make_update_mock("Alice", has_reply=True, reply_first="Bob")
        settings = Settings(
            telegram_bot_token="fake",
            football_data_api_key="fake",
            predictions_path="fake_predictions.yml",
            tongo_phrases_path=str(phrases_file),
            tongo_gifs_dir=str(tmp_path),
        )
        context = _make_context(settings)
        context.bot.send_animation = AsyncMock(side_effect=Exception("Telegram error"))

        with patch("worldcup_bot.bot.handlers.random") as mock_random:
            mock_random.choice.side_effect = [gif_file, "Trampa de Bob!"]
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with("Trampa de Bob!")
