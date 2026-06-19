"""Tests for the merged /tongo YAML config (TongoUsers.yml).

Covers:
  - load_tongo_config loader (validation, hot-reload, graceful degradation)
  - choose_tongo_response (pure function; deterministic fake rng)
  - cmd_tongo integration with the merged single-file config
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

import worldcup_bot.data.tongo as _tongo_mod
from worldcup_bot.data.tongo import (
    FRASES,
    SANCHEZ_ENS_ROBA,
    TongoConfig,
    TongoContext,
    TongoUserConfig,
    choose_tongo_response,
    load_tongo_config,
)
from worldcup_bot.bot.handlers import cmd_tongo
from worldcup_bot.config import Settings


# ── helpers ────────────────────────────────────────────────────────────────────


class _FakeRNG:
    """Deterministic fake RNG for choose_tongo_response tests.

    random() always returns `random_val`.
    choice() returns items from `choices` in order (cycling), or seq[0] if empty.
    """

    def __init__(self, random_val: float = 0.5, choices: list | None = None) -> None:
        self._random_val = random_val
        self._choices = choices or []
        self._idx = 0

    def random(self) -> float:
        return self._random_val

    def choice(self, seq):
        if self._choices:
            item = self._choices[self._idx % len(self._choices)]
            self._idx += 1
            return item
        return seq[0]


def _make_ctx(
    first_name: str = "Alice",
    username: str = "alice",
    has_reply: bool = False,
    reply_first: str = "Bob",
) -> TongoContext:
    return TongoContext(
        first_name=first_name,
        last_name="",
        full_name=first_name,
        username=username,
        id="111",
        reply_to_first_name=reply_first if has_reply else "",
        reply_to_last_name="",
        reply_to_full_name=reply_first if has_reply else "",
        reply_to_username=reply_first.lower() if has_reply else "",
        reply_to_id="222" if has_reply else "",
        has_reply=has_reply,
    )


def _make_update_mock(
    first_name: str = "Alice",
    username: str | None = "alice",
    has_reply: bool = False,
    reply_first: str = "Bob",
) -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    update.effective_user.first_name = first_name
    update.effective_user.last_name = None
    update.effective_user.full_name = first_name
    update.effective_user.username = username
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


def _make_context(
    tmp_path: Path,
    config_file: Path | None = None,
) -> MagicMock:
    settings = Settings(
        telegram_bot_token="fake",
        football_data_api_key="fake",
        predictions_path=str(tmp_path / "predictions.yml"),
        tongo_users_path=str(config_file) if config_file else "",
    )
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    ctx.args = []
    ctx.bot.send_animation = AsyncMock()
    return ctx


def _write_yaml(tmp_path: Path, data: object, filename: str = "TongoUsers.yml") -> str:
    f = tmp_path / filename
    f.write_text(yaml.dump(data), encoding="utf-8")
    return str(f)


# ── autouse cache-reset fixture ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_tongo_caches():
    """Isolate the module-level tongo config cache between tests."""
    _tongo_mod._cached_config_path = None
    _tongo_mod._cached_config_mtime = 0.0
    _tongo_mod._cached_config_data = None
    yield
    _tongo_mod._cached_config_path = None
    _tongo_mod._cached_config_mtime = 0.0
    _tongo_mod._cached_config_data = None


# ══════════════════════════════════════════════════════════════════════════════
# load_tongo_config — merged YAML loader & validation
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadTongoConfig:
    def test_valid_merged_yaml(self, tmp_path):
        """Full valid YAML with phrases and users loads correctly."""
        path = _write_yaml(tmp_path, {
            "phrases": ["Frase uno.", "Frase dos."],
            "users": {
                "alice": {
                    "sanchez_ratio": 0.66,
                    "phrases_mode": "replace",
                    "phrases": ["Frase de {{first_name}}"],
                }
            },
        })
        result = load_tongo_config(path)
        assert result.phrases == ["Frase uno.", "Frase dos."]
        assert "alice" in result.users
        cfg = result.users["alice"]
        assert cfg.sanchez_ratio == pytest.approx(0.66)
        assert cfg.phrases_mode == "replace"
        assert cfg.phrases == ["Frase de {{first_name}}"]

    def test_phrases_not_a_list_becomes_empty(self, tmp_path):
        path = _write_yaml(tmp_path, {"phrases": "una sola frase", "users": {}})
        result = load_tongo_config(path)
        assert result.phrases == []

    def test_phrases_absent_becomes_empty(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {}})
        result = load_tongo_config(path)
        assert result.phrases == []

    def test_users_null_becomes_empty_dict(self, tmp_path):
        """users: null (YAML null) → empty dict, no error."""
        f = tmp_path / "TongoUsers.yml"
        f.write_text("phrases:\n  - Frase.\nusers:\n", encoding="utf-8")
        result = load_tongo_config(str(f))
        assert result.users == {}

    def test_users_absent_becomes_empty_dict(self, tmp_path):
        path = _write_yaml(tmp_path, {"phrases": ["Frase."]})
        result = load_tongo_config(path)
        assert result.users == {}

    def test_users_not_a_mapping_becomes_empty_dict(self, tmp_path):
        path = _write_yaml(tmp_path, {"phrases": ["Frase."], "users": ["lista", "invalida"]})
        result = load_tongo_config(path)
        assert result.users == {}

    def test_username_lowercased(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"DrDonoso": {"sanchez_ratio": 0.5}}})
        result = load_tongo_config(path)
        assert "drdonoso" in result.users
        assert "DrDonoso" not in result.users

    def test_sanchez_ratio_zero_accepted(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"sanchez_ratio": 0.0}}})
        assert load_tongo_config(path).users["alice"].sanchez_ratio == 0.0

    def test_sanchez_ratio_one_accepted(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"sanchez_ratio": 1.0}}})
        assert load_tongo_config(path).users["alice"].sanchez_ratio == pytest.approx(1.0)

    def test_sanchez_ratio_out_of_range_above_ignored(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"sanchez_ratio": 1.5}}})
        assert load_tongo_config(path).users["alice"].sanchez_ratio is None

    def test_sanchez_ratio_negative_ignored(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"sanchez_ratio": -0.1}}})
        assert load_tongo_config(path).users["alice"].sanchez_ratio is None

    def test_sanchez_ratio_non_numeric_ignored(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"sanchez_ratio": "mucho"}}})
        assert load_tongo_config(path).users["alice"].sanchez_ratio is None

    def test_bad_phrases_mode_defaults_to_append(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"phrases_mode": "overwrite"}}})
        assert load_tongo_config(path).users["alice"].phrases_mode == "append"

    def test_phrases_mode_replace_accepted(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"phrases_mode": "replace"}}})
        assert load_tongo_config(path).users["alice"].phrases_mode == "replace"

    def test_non_list_user_phrases_ignored(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"phrases": "una sola frase"}}})
        assert load_tongo_config(path).users["alice"].phrases == []

    def test_list_with_non_string_items_ignored(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {"phrases": [1, 2, 3]}}})
        assert load_tongo_config(path).users["alice"].phrases == []

    def test_non_mapping_user_entry_skipped(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": "not a dict"}})
        assert "alice" not in load_tongo_config(path).users

    def test_missing_file_returns_empty(self):
        result = load_tongo_config("/nonexistent/path/TongoUsers.yml")
        assert result.phrases == []
        assert result.users == {}

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "TongoUsers.yml"
        f.write_text("", encoding="utf-8")
        result = load_tongo_config(str(f))
        assert result.phrases == []
        assert result.users == {}

    def test_parse_error_returns_empty(self, tmp_path):
        f = tmp_path / "TongoUsers.yml"
        f.write_text("{ broken: [yaml: error", encoding="utf-8")
        result = load_tongo_config(str(f))
        assert result.phrases == []
        assert result.users == {}

    def test_never_raises_on_oserror(self, tmp_path, monkeypatch):
        f = tmp_path / "TongoUsers.yml"
        f.write_text("phrases:\n  - Frase.\n", encoding="utf-8")
        monkeypatch.setattr(
            os.path, "getmtime", lambda _: (_ for _ in ()).throw(OSError("boom"))
        )
        result = load_tongo_config(str(f))
        assert result.phrases == []
        assert result.users == {}

    def test_hot_reload_picks_up_edits(self, tmp_path):
        f = tmp_path / "TongoUsers.yml"
        f.write_text(yaml.dump({"users": {"alice": {"sanchez_ratio": 0.2}}}), encoding="utf-8")
        r1 = load_tongo_config(str(f))
        assert r1.users["alice"].sanchez_ratio == pytest.approx(0.2)

        f.write_text(yaml.dump({"users": {"alice": {"sanchez_ratio": 0.8}}}), encoding="utf-8")
        os.utime(str(f), (time.time() + 2, time.time() + 2))
        r2 = load_tongo_config(str(f))
        assert r2.users["alice"].sanchez_ratio == pytest.approx(0.8)

    def test_cache_used_on_same_mtime(self, tmp_path):
        f = tmp_path / "TongoUsers.yml"
        f.write_text(yaml.dump({"users": {"alice": {}}}), encoding="utf-8")
        load_tongo_config(str(f))
        _tongo_mod._cached_config_data = TongoConfig(phrases=["sentinel"])
        result = load_tongo_config(str(f))
        assert result.phrases == ["sentinel"]

    def test_multiple_users_all_loaded(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "users": {
                "alice": {"sanchez_ratio": 0.1},
                "bob": {"sanchez_ratio": 0.9},
            }
        })
        result = load_tongo_config(path)
        assert result.users["alice"].sanchez_ratio == pytest.approx(0.1)
        assert result.users["bob"].sanchez_ratio == pytest.approx(0.9)

    def test_absent_sanchez_ratio_defaults_none(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {}}})
        assert load_tongo_config(path).users["alice"].sanchez_ratio is None

    def test_absent_phrases_mode_defaults_append(self, tmp_path):
        path = _write_yaml(tmp_path, {"users": {"alice": {}}})
        assert load_tongo_config(path).users["alice"].phrases_mode == "append"


# ══════════════════════════════════════════════════════════════════════════════
# choose_tongo_response — pure selection function
# ══════════════════════════════════════════════════════════════════════════════


class TestChooseTongoResponse:
    def test_unconfigured_sanchez_when_random_below_one_third(self):
        ctx = _make_ctx(has_reply=False)
        rng = _FakeRNG(random_val=0.0)
        assert choose_tongo_response(ctx, FRASES, 1 / 3, "m", [], rng=rng) == SANCHEZ_ENS_ROBA

    def test_unconfigured_no_sanchez_when_random_above_one_third(self):
        ctx = _make_ctx(has_reply=False)
        rng = _FakeRNG(random_val=0.9)
        result = choose_tongo_response(ctx, FRASES, 1 / 3, "m", [], rng=rng)
        assert result != SANCHEZ_ENS_ROBA

    def test_high_ratio_sanchez_fires_at_0_65(self):
        ctx = _make_ctx(has_reply=False)
        rng = _FakeRNG(random_val=0.65)
        assert choose_tongo_response(ctx, FRASES, 0.66, "m", [], rng=rng) == SANCHEZ_ENS_ROBA

    def test_high_ratio_no_sanchez_above_threshold(self):
        ctx = _make_ctx(has_reply=False)
        rng = _FakeRNG(random_val=0.67)
        result = choose_tongo_response(ctx, FRASES, 0.66, "m", [], rng=rng)
        assert result != SANCHEZ_ENS_ROBA

    def test_zero_ratio_never_sanchez(self):
        ctx = _make_ctx(has_reply=False)
        phrases = ["Frase segura."]
        for rv in (0.0, 0.001, 0.33, 0.5, 0.99):
            rng = _FakeRNG(random_val=rv)
            result = choose_tongo_response(ctx, phrases, 0.0, "m", [], rng=rng)
            assert result != SANCHEZ_ENS_ROBA, f"SANCHEZ returned for rv={rv}"

    def test_replace_mode_only_user_phrases_in_pool(self):
        ctx = _make_ctx(has_reply=False)
        user_phrases = ["Exclusiva de Alice."]

        class CaptureRNG:
            def __init__(self): self.pool = []
            def random(self): return 0.9
            def choice(self, seq): self.pool = list(seq); return seq[0]

        cap = CaptureRNG()
        choose_tongo_response(ctx, user_phrases, 0.0, "m", [], rng=cap)
        assert "Exclusiva de Alice." in cap.pool
        # Global phrases must NOT appear (the caller passes only user phrases in replace mode)
        assert "Per robos el de Javi a Raona" not in cap.pool

    def test_append_mode_both_global_and_user_in_pool(self):
        ctx = _make_ctx(has_reply=False)
        combined = ["Global frase.", "Usuario frase."]

        class CaptureRNG:
            def __init__(self): self.pool = []
            def random(self): return 0.9
            def choice(self, seq): self.pool = list(seq); return seq[0]

        cap = CaptureRNG()
        choose_tongo_response(ctx, combined, 0.0, "m", [], rng=cap)
        assert "Global frase." in cap.pool
        assert "Usuario frase." in cap.pool

    def test_reply_targeted_path_fires_and_renders(self):
        ctx = _make_ctx(has_reply=True, reply_first="Carlos")
        phrases = ["Tongo de {{reply_to_first_name}}!"]
        rng = _FakeRNG(random_val=0.9)
        result = choose_tongo_response(ctx, phrases, 1.0, "m", [], rng=rng)
        assert result == "Tongo de Carlos!"

    def test_reply_targeted_path_skips_sanchez(self):
        ctx = _make_ctx(has_reply=True, reply_first="Carlos")
        phrases = ["Trampa de {{reply_to_first_name}}!"]
        rng = _FakeRNG(random_val=0.0)
        result = choose_tongo_response(ctx, phrases, 1.0, "m", [], rng=rng)
        assert result == "Trampa de Carlos!"
        assert result != SANCHEZ_ENS_ROBA

    def test_no_reply_phrase_skips_reply_path(self):
        ctx = _make_ctx(has_reply=True)
        phrases = ["Solo sender phrase."]
        rng = _FakeRNG(random_val=0.0)
        assert choose_tongo_response(ctx, phrases, 1 / 3, "m", [], rng=rng) == SANCHEZ_ENS_ROBA

    def test_templating_applied_in_result(self):
        ctx = _make_ctx(first_name="Elena", has_reply=False)
        phrases = ["Hola {{first_name}}!"]
        rng = _FakeRNG(random_val=0.9)
        result = choose_tongo_response(ctx, phrases, 0.0, "m", [], rng=rng)
        assert result == "Hola Elena!"
        assert "{{" not in str(result)

    def test_gif_can_be_returned(self, tmp_path):
        gif = tmp_path / "funny.gif"
        gif.write_bytes(b"GIF89a")
        ctx = _make_ctx(has_reply=False)
        rng = _FakeRNG(random_val=0.9, choices=[gif])
        result = choose_tongo_response(ctx, ["Frase."], 0.0, "m", [gif], rng=rng)
        assert result == gif
        assert isinstance(result, Path)

    def test_female_gender_phrase_in_pool(self):
        ctx = _make_ctx(has_reply=False)
        captured = []

        class CaptureRNG:
            def random(self): return 0.9
            def choice(self, pool):
                captured.extend(str(p) for p in pool if isinstance(p, str))
                return pool[0]

        choose_tongo_response(ctx, ["Frase."], 0.0, "f", [], rng=CaptureRNG())
        assert any("pesada" in p for p in captured)

    def test_male_gender_phrase_in_pool(self):
        ctx = _make_ctx(has_reply=False)
        captured = []

        class CaptureRNG:
            def random(self): return 0.9
            def choice(self, pool):
                captured.extend(str(p) for p in pool if isinstance(p, str))
                return pool[0]

        choose_tongo_response(ctx, ["Frase."], 0.0, "m", [], rng=CaptureRNG())
        assert any("pesado" in p for p in captured)

    def test_empty_effective_phrases_falls_back_to_frases(self):
        ctx = _make_ctx(has_reply=False)
        rng = _FakeRNG(random_val=0.9)
        # Empty pool → should fall back to FRASES in the function
        result = choose_tongo_response(ctx, [], 0.0, "m", [], rng=rng)
        assert result != SANCHEZ_ENS_ROBA

    def test_sanchez_invariant_exactly_at_boundary(self):
        ctx = _make_ctx(has_reply=False)
        # Exactly 1/3 is NOT less than 1/3
        rng = _FakeRNG(random_val=1 / 3)
        result = choose_tongo_response(ctx, FRASES, 1 / 3, "m", [], rng=rng)
        assert result != SANCHEZ_ENS_ROBA


# ══════════════════════════════════════════════════════════════════════════════
# cmd_tongo integration — per-user config
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdTongoUsersIntegration:
    async def test_unconfigured_user_sanchez_at_one_third(self, tmp_path):
        """Unconfigured user keeps the global 1/3 SANCHEZ invariant."""
        uf = _write_yaml(tmp_path, {"phrases": ["Una frase."], "users": {}})

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.0
            mock_rng.choice.return_value = "Una frase."
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with(SANCHEZ_ENS_ROBA)

    async def test_high_sanchez_ratio_fires_more(self, tmp_path):
        """User with sanchez_ratio=0.66 gets SANCHEZ when random() < 0.66."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Frase normal."],
            "users": {"alice": {"sanchez_ratio": 0.66}},
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.65
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with(SANCHEZ_ENS_ROBA)

    async def test_high_ratio_no_sanchez_above_threshold(self, tmp_path):
        """sanchez_ratio=0.66 does NOT fire when random()=0.67."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Frase normal."],
            "users": {"alice": {"sanchez_ratio": 0.66}},
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.67
            mock_rng.choice.return_value = "Frase normal."
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text != SANCHEZ_ENS_ROBA

    async def test_zero_sanchez_ratio_never_fires(self, tmp_path):
        """User with sanchez_ratio=0.0 never sees SANCHEZ."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Frase segura."],
            "users": {"alice": {"sanchez_ratio": 0.0}},
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.0
            mock_rng.choice.return_value = "Frase segura."
            await cmd_tongo(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert text == "Frase segura."

    async def test_replace_mode_only_user_phrases_in_pool(self, tmp_path):
        """phrases_mode=replace: only per-user phrases in pool, not global."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Frase global."],
            "users": {
                "alice": {
                    "sanchez_ratio": 0.0,
                    "phrases_mode": "replace",
                    "phrases": ["Exclusiva de Alice."],
                }
            },
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))
        captured = []

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.9
            mock_rng.choice.side_effect = lambda pool: (
                captured.extend(p for p in pool if isinstance(p, str)) or pool[0]
            )
            await cmd_tongo(update, context)

        assert "Exclusiva de Alice." in captured
        assert "Frase global." not in captured

    async def test_append_mode_both_in_pool(self, tmp_path):
        """phrases_mode=append (default): global + user phrases both in pool."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Frase global."],
            "users": {
                "alice": {
                    "sanchez_ratio": 0.0,
                    "phrases": ["Frase extra de Alice."],
                }
            },
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))
        captured = []

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.9
            mock_rng.choice.side_effect = lambda pool: (
                captured.extend(p for p in pool if isinstance(p, str)) or pool[0]
            )
            await cmd_tongo(update, context)

        assert "Frase global." in captured
        assert "Frase extra de Alice." in captured

    async def test_replace_mode_empty_user_pool_falls_back_to_global(self, tmp_path):
        """replace mode with no per-user phrases falls back to global pool."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Frase global."],
            "users": {"alice": {"sanchez_ratio": 0.0, "phrases_mode": "replace"}},
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))
        captured = []

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.9
            mock_rng.choice.side_effect = lambda pool: (
                captured.extend(p for p in pool if isinstance(p, str)) or pool[0]
            )
            await cmd_tongo(update, context)

        assert "Frase global." in captured

    async def test_user_without_telegram_username_gets_global_defaults(self, tmp_path):
        """User with no @username → no per-user lookup → global 1/3 SANCHEZ."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Global."],
            "users": {"alice": {"sanchez_ratio": 0.0}},
        })

        update = _make_update_mock("Alice", None, has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.0
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with(SANCHEZ_ENS_ROBA)

    async def test_unknown_username_uses_global_defaults(self, tmp_path):
        """User whose username is not in TongoUsers.yml → global behavior."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Global."],
            "users": {"otheruser": {"sanchez_ratio": 0.0}},
        })

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.0
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with(SANCHEZ_ENS_ROBA)

    async def test_sanchez_invariant_preserved_for_unconfigured_user(self, tmp_path):
        """The SANCHEZ 1/3 invariant holds for unconfigured users."""
        uf = _write_yaml(tmp_path, {"phrases": ["Una frase."], "users": {}})

        update = _make_update_mock("Alice", "alice", has_reply=False)
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.random.return_value = 0.0  # always triggers SANCHEZ at 1/3
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with(SANCHEZ_ENS_ROBA)

    async def test_reply_path_still_works_with_per_user_config(self, tmp_path):
        """Reply-targeted path still fires correctly when user has a config entry."""
        uf = _write_yaml(tmp_path, {
            "phrases": ["Trampa de {{reply_to_first_name}}!"],
            "users": {"alice": {"sanchez_ratio": 0.0}},
        })

        update = _make_update_mock("Alice", "alice", has_reply=True, reply_first="Bob")
        context = _make_context(tmp_path, Path(uf))

        with patch("worldcup_bot.bot.handlers.random") as mock_rng:
            mock_rng.choice.return_value = "Trampa de Bob!"
            await cmd_tongo(update, context)

        update.message.reply_text.assert_called_once_with("Trampa de Bob!")
