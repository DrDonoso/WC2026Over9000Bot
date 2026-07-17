"""Tests for the daily rich-image evolution feature.

Covers: build_rich_prompt, select_base_image, load_level/save_level,
edit_rich_image, run_rich_iteration, rich_image_job, and main() scheduling.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.ai.rich_image import (
    RICH_CAPTION_PROMPT,
    RICH_CAPTIONS_MAX,
    RICH_EDIT_PROMPT,
    RICH_FACE_ANCHOR_CLAUSE,
    RICH_HISTORY_MAX_LINES,
    RICH_THEME_PROMPT,
    RICH_DEATH_CAPTION_PROMPT,
    RICH_APEX_TRAMPLE_SENTENCE,
    POSE_ACTIVITIES,
    _normalize_caption,
    append_caption,
    append_history,
    build_rich_prompt,
    edit_rich_image,
    find_original_image,
    format_captions_for_prompt,
    format_history_for_prompt,
    generate_rich_caption,
    generate_wealth_themes,
    is_rich_apex,
    is_rich_death,
    load_captions,
    load_history_lines,
    load_level,
    run_rich_iteration,
    save_level,
    select_base_image,
)
from worldcup_bot.config import (
    Settings,
    _effective_image_api_key,
    _effective_image_base_url,
    image_ai_enabled,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        telegram_bot_token="tok",
        football_data_api_key="key",
        state_dir=str(tmp_path),
        openai_api_key="sk-chat",
        openai_base_url="http://litellm/v1",
        openai_model="gpt-4",
        openai_image_model="gpt-image-2",
        openai_image_api_key="sk-img",
        openai_image_base_url="http://litellm/v1",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _fake_client(b64_payload: str = base64.b64encode(b"PNGDATA").decode()):
    """Return a fake AsyncOpenAI-like client whose images.edit returns b64_payload."""
    img_obj = MagicMock()
    img_obj.b64_json = b64_payload
    resp = MagicMock()
    resp.data = [img_obj]
    client = MagicMock()
    client.images.edit = AsyncMock(return_value=resp)
    return client


def _fake_caption_client(content: str = "¡Soy el más rico!"):
    """Return a fake AsyncOpenAI-like client for chat caption generation."""
    msg = MagicMock()
    msg.content = f"  {content}  "
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


def _make_context(settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    ctx.bot.send_photo = AsyncMock()
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# Config — new image fields
# ══════════════════════════════════════════════════════════════════════════════


class TestImageAIConfig:
    def test_new_fields_default_values(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.openai_image_model == "gpt-image-2"
        assert s.openai_image_api_key == ""
        assert s.openai_image_base_url == ""
        assert s.rich_image_hour == 0

    def test_image_ai_enabled_true_with_dedicated_key(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_image_api_key="sk-img",
            openai_image_base_url="http://litellm/v1",
            openai_image_model="gpt-image-2",
        )
        assert image_ai_enabled(s) is True

    def test_image_ai_enabled_falls_back_to_chat_key(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-chat",
            openai_base_url="http://litellm/v1",
            openai_image_model="gpt-image-2",
        )
        assert image_ai_enabled(s) is True

    def test_image_ai_disabled_when_no_key(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_image_base_url="http://litellm/v1",
            openai_image_model="gpt-image-2",
        )
        assert image_ai_enabled(s) is False

    def test_image_ai_disabled_when_no_base_url(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_image_api_key="sk-img",
            openai_image_model="gpt-image-2",
        )
        assert image_ai_enabled(s) is False

    def test_image_ai_disabled_when_no_model(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_image_api_key="sk-img",
            openai_image_base_url="http://litellm/v1",
            openai_image_model="",
        )
        assert image_ai_enabled(s) is False

    def test_effective_key_prefers_image_key(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-chat",
            openai_image_api_key="sk-img",
        )
        assert _effective_image_api_key(s) == "sk-img"

    def test_effective_key_falls_back_to_chat_key(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-chat",
            openai_image_api_key="",
        )
        assert _effective_image_api_key(s) == "sk-chat"

    def test_effective_base_url_prefers_image_url(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_base_url="http://chat/v1",
            openai_image_base_url="http://img/v1",
        )
        assert _effective_image_base_url(s) == "http://img/v1"

    def test_effective_base_url_falls_back_to_chat(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_base_url="http://chat/v1",
            openai_image_base_url="",
        )
        assert _effective_image_base_url(s) == "http://chat/v1"

    def test_load_settings_reads_image_env_vars(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "key")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100")
        monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
        monkeypatch.setenv("OPENAI_IMAGE_API_KEY", "sk-img")
        monkeypatch.setenv("OPENAI_IMAGE_BASE_URL", "http://img/v1")
        monkeypatch.setenv("RICH_IMAGE_HOUR", "11")
        from worldcup_bot.config import load_settings
        s = load_settings()
        assert s.openai_image_model == "gpt-image-2"
        assert s.openai_image_api_key == "sk-img"
        assert s.openai_image_base_url == "http://img/v1"
        assert s.rich_image_hour == 11


# ══════════════════════════════════════════════════════════════════════════════
# build_rich_prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildRichPrompt:
    def test_no_arg_returns_base_prompt(self):
        assert build_rich_prompt() == RICH_EDIT_PROMPT

    def test_empty_history_gives_same_result_as_no_arg(self):
        assert build_rich_prompt(history="") == build_rich_prompt()

    def test_history_nonempty_adds_no_repeat_clause(self):
        history = "- 2026-06-01 | iter 1 | Rolls-Royce, Mónaco"
        p = build_rich_prompt(history=history)
        lower = p.lower()
        assert "different" in lower or "not repeat" in lower or "do not" in lower
        assert history in p

    def test_history_clause_appended_after_base(self):
        history = "- 2026-06-01 | iter 1 | Rolls-Royce"
        p = build_rich_prompt(history=history)
        assert p.startswith(RICH_EDIT_PROMPT)

    def test_history_nonempty_differs_from_no_history(self):
        history = "- 2026-06-01 | iter 1 | yate, Mónaco"
        assert build_rich_prompt(history=history) != build_rich_prompt()

    def test_returns_string(self):
        assert isinstance(build_rich_prompt(), str)

    def test_deterministic(self):
        assert build_rich_prompt() == build_rich_prompt()

    def test_identity_preservation(self):
        assert "same face" in build_rich_prompt().lower()


# ══════════════════════════════════════════════════════════════════════════════
# RICH_EDIT_PROMPT — pose allowed, identity-preservation scope
# ══════════════════════════════════════════════════════════════════════════════


class TestRichEditPromptContent:
    def test_preserves_skin_tone(self):
        assert "skin tone" in RICH_EDIT_PROMPT.lower()

    def test_preserves_body(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "head" in lower or "features" in lower

    def test_preserves_features(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "features" in lower or "traits" in lower

    def test_explicitly_allows_pose_change(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "pose" in lower or "posture" in lower

    def test_new_pose_required(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "new" in lower and "pose" in lower

    def test_identity_preservation_still_includes_face(self):
        assert "same face" in RICH_EDIT_PROMPT.lower()

    def test_allows_hands_and_gestures(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "hands" in lower or "gestures" in lower or "vary" in lower

    def test_allows_other_people_around_subject(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "other people" in lower or "entourage" in lower or "friends" in lower

    def test_mentions_luxury_vehicles(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "vehicle" in lower or "car" in lower or "yacht" in lower or "plane" in lower or "helicopter" in lower

    def test_mentions_varied_settings(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "setting" in lower or "island" in lower or "mansion" in lower or "pool" in lower

    def test_instructs_not_all_at_once(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "not add everything at once" in lower or "few" in lower

    def test_instructs_vary(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "vari" in lower or "different" in lower

# ══════════════════════════════════════════════════════════════════════════════
# select_base_image
# ══════════════════════════════════════════════════════════════════════════════


class TestSelectBaseImage:
    def test_prefers_state_rich_modified(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "rich_modified.png").write_bytes(b"evolved")
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"original")
        result = select_base_image(str(state_dir), str(data_dir))
        assert result == str(state_dir / "rich_modified.png")

    def test_falls_back_to_original_jpg(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"original")
        result = select_base_image(str(state_dir), str(data_dir))
        assert result == str(orig)

    def test_falls_back_to_original_png(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.png"
        orig.write_bytes(b"original")
        result = select_base_image(str(state_dir), str(data_dir))
        assert result == str(orig)

    def test_raises_when_neither_exists(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            select_base_image(str(state_dir), str(data_dir))

    def test_state_dir_without_modified_falls_back(self, tmp_path):
        # state_dir exists but rich_modified.png is absent
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"x")
        result = select_base_image(str(state_dir), str(data_dir))
        assert result == str(orig)


# ══════════════════════════════════════════════════════════════════════════════
# load_level / save_level
# ══════════════════════════════════════════════════════════════════════════════


class TestLevelPersistence:
    def test_load_returns_0_when_file_missing(self, tmp_path):
        assert load_level(str(tmp_path)) == 0

    def test_round_trip(self, tmp_path):
        save_level(str(tmp_path), 7)
        assert load_level(str(tmp_path)) == 7

    def test_overwrite(self, tmp_path):
        save_level(str(tmp_path), 3)
        save_level(str(tmp_path), 5)
        assert load_level(str(tmp_path)) == 5

    def test_returns_0_on_corrupt_json(self, tmp_path):
        (tmp_path / "rich_state.json").write_text("not-json")
        assert load_level(str(tmp_path)) == 0

    def test_returns_0_on_missing_key(self, tmp_path):
        (tmp_path / "rich_state.json").write_text('{"other": 1}')
        assert load_level(str(tmp_path)) == 0

    def test_save_creates_directory_if_needed(self, tmp_path):
        nested = tmp_path / "deep" / "state"
        save_level(str(nested), 4)
        assert load_level(str(nested)) == 4

    def test_persisted_as_json(self, tmp_path):
        save_level(str(tmp_path), 9)
        data = json.loads((tmp_path / "rich_state.json").read_text())
        assert data == {"level": 9}


# ══════════════════════════════════════════════════════════════════════════════
# edit_rich_image
# ══════════════════════════════════════════════════════════════════════════════


class TestEditRichImage:
    async def test_returns_decoded_bytes(self, tmp_path):
        img_path = tmp_path / "input.jpg"
        img_path.write_bytes(b"JPEG")
        fake = _fake_client(base64.b64encode(b"PNGDATA").decode())
        result = await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(img_path),
            prompt="make rich",
            _client=fake,
        )
        assert result == b"PNGDATA"

    async def test_passes_model_and_prompt_to_client(self, tmp_path):
        img_path = tmp_path / "input.jpg"
        img_path.write_bytes(b"JPEG")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(img_path),
            prompt="ultra rich",
            _client=fake,
        )
        call_kwargs = fake.images.edit.call_args
        assert call_kwargs.kwargs["model"] == "gpt-image-2"
        assert call_kwargs.kwargs["prompt"] == "ultra rich"

    async def test_raises_runtime_error_on_client_failure(self, tmp_path):
        img_path = tmp_path / "input.jpg"
        img_path.write_bytes(b"JPEG")
        bad_client = MagicMock()
        bad_client.images.edit = AsyncMock(side_effect=Exception("API error"))
        with pytest.raises(RuntimeError, match="edit_rich_image failed"):
            await edit_rich_image(
                api_key="k",
                base_url="http://x",
                model="gpt-image-2",
                image_path=str(img_path),
                prompt="rich",
                _client=bad_client,
            )

    async def test_raises_runtime_error_when_image_missing(self, tmp_path):
        # File doesn't exist → open() raises, should wrap to RuntimeError
        bad_client = MagicMock()
        bad_client.images.edit = AsyncMock(return_value=MagicMock())
        with pytest.raises(RuntimeError, match="edit_rich_image failed"):
            await edit_rich_image(
                api_key="k",
                base_url="http://x",
                model="gpt-image-2",
                image_path=str(tmp_path / "nonexistent.jpg"),
                prompt="rich",
                _client=bad_client,
            )

    async def test_default_size_is_1024(self, tmp_path):
        img_path = tmp_path / "input.jpg"
        img_path.write_bytes(b"JPEG")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(img_path),
            prompt="rich",
            _client=fake,
        )
        assert fake.images.edit.call_args.kwargs["size"] == "1024x1024"


# ══════════════════════════════════════════════════════════════════════════════
# generate_rich_caption
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateRichCaption:
    async def test_non_json_returns_raw_text_with_empty_memo(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"OLDJPEG")
        new_img.write_bytes(b"NEWPNG")
        fake = _fake_caption_client("¡Soy el más rico!")
        caption, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=3,
            _client=fake,
        )
        assert caption == "¡Soy el más rico!"
        assert memo == ""

    async def test_json_response_returns_caption_and_memo(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        payload = json.dumps(
            {"caption": "¡Soy el más rico!", "memo": "Lamborghini, Mónaco"},
            ensure_ascii=False,
        )
        fake = _fake_caption_client(payload)
        caption, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=2,
            _client=fake,
        )
        assert caption == "¡Soy el más rico!"
        assert memo == "Lamborghini, Mónaco"

    async def test_fenced_json_is_stripped(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        inner = json.dumps({"caption": "Pringados", "memo": "Rolls, Marbella"})
        fenced = f"```json\n{inner}\n```"
        msg = MagicMock()
        msg.content = fenced
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=resp)
        caption, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=4,
            _client=client,
        )
        assert caption == "Pringados"
        assert memo == "Rolls, Marbella"

    async def test_plain_text_non_json_returns_empty_memo(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("just text")
        caption, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        assert caption == "just text"
        assert memo == ""

    async def test_history_injected_in_request_when_provided(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("text")
        history = "- 2026-06-16 | iter 1 | Rolls-Royce, Mónaco"
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=2,
            history=history,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "Rolls-Royce" in combined
        assert "NO" in combined

    async def test_no_history_text_when_history_empty(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("text")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            history="",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "Memos ya usados" not in combined

    async def test_recent_captions_injected_when_provided(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("text")
        recent = "caption from last week"
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=2,
            recent_captions=recent,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "caption from last week" in combined
        assert "TEXTOS ANTERIORES" in combined

    async def test_no_recent_captions_text_when_empty(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("text")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            recent_captions="",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "TEXTOS ANTERIORES" not in combined

    async def test_jpg_old_image_uses_jpeg_mime(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client()
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        old_img_url = user_content[1]["image_url"]["url"]
        assert old_img_url.startswith("data:image/jpeg;base64,")

    async def test_png_old_image_uses_png_mime(self, tmp_path):
        old_img = tmp_path / "before.png"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client()
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=2,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        old_img_url = user_content[1]["image_url"]["url"]
        assert old_img_url.startswith("data:image/png;base64,")

    async def test_request_has_two_image_url_parts(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client()
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 2
        assert image_parts[0]["image_url"]["url"].startswith("data:")
        assert image_parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    async def test_level_in_user_message(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client()
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=7,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        assert "7" in " ".join(text_parts)

    async def test_uses_max_completion_tokens_not_max_tokens(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client()
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        call_kwargs = fake.chat.completions.create.call_args.kwargs
        assert "max_completion_tokens" in call_kwargs
        assert "max_tokens" not in call_kwargs

    async def test_raises_runtime_error_on_failure(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        bad_client = MagicMock()
        bad_client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
        with pytest.raises(RuntimeError, match="generate_rich_caption failed"):
            await generate_rich_caption(
                api_key="k",
                base_url="http://x",
                model="gpt-4",
                old_image_path=str(old_img),
                new_image_path=str(new_img),
                level=1,
                _client=bad_client,
            )


# ══════════════════════════════════════════════════════════════════════════════
# History helpers — append_history / load_history_lines / format_history_for_prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestRichHistory:
    def test_append_creates_file_with_correct_line(self, tmp_path):
        append_history(str(tmp_path), "2026-06-17", 3, "Lamborghini, Mónaco")
        hist = tmp_path / "rich_history.txt"
        assert hist.exists()
        assert "2026-06-17 | iter 3 | Lamborghini, Mónaco" in hist.read_text(encoding="utf-8")

    def test_append_skips_empty_memo(self, tmp_path):
        append_history(str(tmp_path), "2026-06-17", 1, "")
        assert not (tmp_path / "rich_history.txt").exists()

    def test_append_skips_whitespace_memo(self, tmp_path):
        append_history(str(tmp_path), "2026-06-17", 1, "   ")
        assert not (tmp_path / "rich_history.txt").exists()

    def test_append_caps_at_max_lines(self, tmp_path):
        for i in range(35):
            append_history(str(tmp_path), f"2026-05-{i + 1:02d}", i + 1, f"memo_{i}")
        lines = load_history_lines(str(tmp_path))
        assert len(lines) == RICH_HISTORY_MAX_LINES
        # newest 30 kept (indices 5–34, i.e. memo_5 … memo_34)
        assert any("memo_34" in ln for ln in lines)
        assert not any("memo_0" in ln for ln in lines)
        assert not any("memo_4" in ln for ln in lines)

    def test_append_multiple_lines_in_order(self, tmp_path):
        append_history(str(tmp_path), "2026-06-01", 1, "Rolls-Royce")
        append_history(str(tmp_path), "2026-06-02", 2, "Mónaco")
        lines = load_history_lines(str(tmp_path))
        assert len(lines) == 2
        assert "Rolls-Royce" in lines[0]
        assert "Mónaco" in lines[1]

    def test_load_history_lines_returns_empty_when_missing(self, tmp_path):
        assert load_history_lines(str(tmp_path)) == []

    def test_load_history_lines_round_trip(self, tmp_path):
        append_history(str(tmp_path), "2026-06-17", 3, "Lamborghini, Mónaco")
        lines = load_history_lines(str(tmp_path))
        assert len(lines) == 1
        assert "Lamborghini, Mónaco" in lines[0]

    def test_load_history_lines_strips_blanks(self, tmp_path):
        (tmp_path / "rich_history.txt").write_text("line1\n\n  \nline2\n", encoding="utf-8")
        lines = load_history_lines(str(tmp_path))
        assert lines == ["line1", "line2"]

    def test_format_history_empty_returns_empty_string(self, tmp_path):
        assert format_history_for_prompt(str(tmp_path)) == ""

    def test_format_history_nonempty_prefixes_with_dash(self, tmp_path):
        append_history(str(tmp_path), "2026-06-17", 3, "Lamborghini, Mónaco")
        result = format_history_for_prompt(str(tmp_path))
        assert result.startswith("- ")
        assert "Lamborghini, Mónaco" in result

    def test_format_history_multiple_lines(self, tmp_path):
        append_history(str(tmp_path), "2026-06-01", 1, "Rolls-Royce")
        append_history(str(tmp_path), "2026-06-02", 2, "yate")
        result = format_history_for_prompt(str(tmp_path))
        assert "Rolls-Royce" in result
        assert "yate" in result

    def test_format_history_max_items_limits_output(self, tmp_path):
        for i in range(4):
            append_history(str(tmp_path), f"2026-06-{i + 1:02d}", i + 1, f"memo{i}")
        result = format_history_for_prompt(str(tmp_path), max_items=2)
        result_lines = [ln for ln in result.split("\n") if ln]
        assert len(result_lines) == 2
        assert "memo3" in result
        assert "memo2" in result
        assert "memo0" not in result
        assert "memo1" not in result

    def test_format_history_max_items_none_returns_all(self, tmp_path):
        for i in range(4):
            append_history(str(tmp_path), f"2026-06-{i + 1:02d}", i + 1, f"memo{i}")
        result = format_history_for_prompt(str(tmp_path), max_items=None)
        result_lines = [ln for ln in result.split("\n") if ln]
        assert len(result_lines) == 4


# ══════════════════════════════════════════════════════════════════════════════
# append_caption / load_captions / format_captions_for_prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestRichCaptions:
    def test_append_caption_creates_file(self, tmp_path):
        append_caption(str(tmp_path), "caption text here")
        assert (tmp_path / "rich_captions.txt").exists()

    def test_append_caption_collapses_newlines(self, tmp_path):
        append_caption(str(tmp_path), "line one\nline two\nline three")
        lines = load_captions(str(tmp_path))
        assert len(lines) == 1
        assert " / " not in lines[0]
        assert "\n" not in lines[0]
        assert "line one" in lines[0]
        assert "line two" in lines[0]

    def test_append_caption_stores_no_slash_separator(self, tmp_path):
        append_caption(str(tmp_path), "first line\nsecond line\nthird line")
        lines = load_captions(str(tmp_path))
        assert len(lines) == 1
        assert "/" not in lines[0]
        assert "\n" not in lines[0]
        assert "first line" in lines[0]

    def test_format_captions_for_prompt_has_no_slash_separator(self, tmp_path):
        append_caption(str(tmp_path), "fruta\nverdura\npescado")
        result = format_captions_for_prompt(str(tmp_path))
        assert " / " not in result

    def test_append_caption_skips_empty(self, tmp_path):
        append_caption(str(tmp_path), "")
        assert not (tmp_path / "rich_captions.txt").exists()

    def test_append_caption_skips_whitespace(self, tmp_path):
        append_caption(str(tmp_path), "   ")
        assert not (tmp_path / "rich_captions.txt").exists()

    def test_append_caption_caps_at_max(self, tmp_path):
        for i in range(8):
            append_caption(str(tmp_path), f"caption_{i}")
        captions = load_captions(str(tmp_path))
        assert len(captions) == RICH_CAPTIONS_MAX
        assert any("caption_7" in c for c in captions)
        assert not any("caption_0" in c for c in captions)
        assert not any("caption_1" in c for c in captions)

    def test_load_captions_empty_returns_empty_list(self, tmp_path):
        assert load_captions(str(tmp_path)) == []

    def test_load_captions_round_trip(self, tmp_path):
        append_caption(str(tmp_path), "Mi yacht en Mónaco")
        captions = load_captions(str(tmp_path))
        assert len(captions) == 1
        assert "Mi yacht en Mónaco" in captions[0]

    def test_format_captions_for_prompt_empty(self, tmp_path):
        assert format_captions_for_prompt(str(tmp_path)) == ""

    def test_format_captions_for_prompt_nonempty(self, tmp_path):
        append_caption(str(tmp_path), "caption uno")
        append_caption(str(tmp_path), "caption dos")
        result = format_captions_for_prompt(str(tmp_path))
        assert result != ""
        assert "caption uno" in result
        assert "caption dos" in result


# ══════════════════════════════════════════════════════════════════════════════
# run_rich_iteration
# ══════════════════════════════════════════════════════════════════════════════


class TestRunRichIteration:
    async def test_first_iteration_uses_original_and_returns_level_1(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap = _fake_caption_client("Primera riqueza")
        with patch(
            "worldcup_bot.ai.rich_image.select_base_image",
            return_value=str(orig),
        ):
            out_path, level, caption = await run_rich_iteration(
                settings, _client=fake, _caption_client=fake_cap
            )

        assert level == 1
        assert out_path == str(state_dir / "rich_modified.png")
        assert Path(out_path).read_bytes() == b"PNG1"
        assert caption == "Primera riqueza"

    async def test_second_iteration_uses_modified_and_returns_level_2(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake1 = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap1 = _fake_caption_client("Nivel 1")
        await run_rich_iteration(
            settings, _client=fake1, _caption_client=fake_cap1, _data_dir=str(data_dir)
        )

        fake2 = _fake_client(base64.b64encode(b"PNG2").decode())
        fake_cap2 = _fake_caption_client("Nivel 2")
        out_path2, level2, caption2 = await run_rich_iteration(
            settings, _client=fake2, _caption_client=fake_cap2, _data_dir=str(data_dir)
        )

        assert level2 == 2
        assert Path(out_path2).read_bytes() == b"PNG2"
        assert caption2 == "Nivel 2"

    async def test_second_run_old_image_is_previous_modified(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img1 = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap1 = _fake_caption_client()
        await run_rich_iteration(
            settings, _client=fake_img1, _caption_client=fake_cap1, _data_dir=str(data_dir)
        )

        fake_img2 = _fake_client(base64.b64encode(b"PNG2").decode())
        fake_cap2 = _fake_caption_client()
        await run_rich_iteration(
            settings, _client=fake_img2, _caption_client=fake_cap2, _data_dir=str(data_dir)
        )

        # Second run: OLD image is the previous rich_modified.png (PNG extension)
        messages = fake_cap2.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        before_url = user_content[1]["image_url"]["url"]
        assert before_url.startswith("data:image/png;base64,")

    async def test_level_persisted_between_calls(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake = _fake_client()
        fake_cap = _fake_caption_client()

        await run_rich_iteration(
            settings, _client=fake, _caption_client=fake_cap, _data_dir=str(data_dir)
        )
        assert load_level(str(state_dir)) == 1

        await run_rich_iteration(
            settings, _client=fake, _caption_client=fake_cap, _data_dir=str(data_dir)
        )
        assert load_level(str(state_dir)) == 2

    async def test_overwrite_rich_modified_each_time(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_cap = _fake_caption_client()

        fake_a = _fake_client(base64.b64encode(b"ITERATION_A").decode())
        await run_rich_iteration(
            settings, _client=fake_a, _caption_client=fake_cap, _data_dir=str(data_dir)
        )
        assert Path(state_dir / "rich_modified.png").read_bytes() == b"ITERATION_A"

        fake_b = _fake_client(base64.b64encode(b"ITERATION_B").decode())
        await run_rich_iteration(
            settings, _client=fake_b, _caption_client=fake_cap, _data_dir=str(data_dir)
        )
        assert Path(state_dir / "rich_modified.png").read_bytes() == b"ITERATION_B"

    async def test_temp_file_removed_after_rename(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap = _fake_caption_client()

        await run_rich_iteration(
            settings, _client=fake, _caption_client=fake_cap, _data_dir=str(data_dir)
        )
        assert not (state_dir / "rich_modified.new.png").exists()
        assert (state_dir / "rich_modified.png").exists()

    async def test_caption_from_caption_client_returned(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake = _fake_client()
        fake_cap = _fake_caption_client("Soy millonario, pringados")

        _, _, caption = await run_rich_iteration(
            settings, _client=fake, _caption_client=fake_cap, _data_dir=str(data_dir)
        )
        assert caption == "Soy millonario, pringados"

    async def test_caption_falls_back_when_caption_client_raises(self, tmp_path):
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake = _fake_client()
        bad_cap = MagicMock()
        bad_cap.chat.completions.create = AsyncMock(side_effect=RuntimeError("caption API down"))
        non_birthday_now = datetime(2026, 7, 9, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings, _client=fake, _caption_client=bad_cap, _data_dir=str(data_dir),
            _now=non_birthday_now,
        )
        assert caption == "🤑 Cada día más rico a vuestra costa"
        assert Path(out_path).exists()

    async def test_caption_falls_back_when_chat_not_configured(self, tmp_path):
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(
            tmp_path,
            state_dir=str(state_dir),
            openai_api_key="",
            openai_base_url="",
            openai_model="",
        )
        fake = _fake_client()
        non_birthday_now = datetime(2026, 7, 9, 11, 0, 0, tzinfo=pytz.UTC)
        out_path, level, caption = await run_rich_iteration(
            settings, _client=fake, _data_dir=str(data_dir), _now=non_birthday_now,
        )
        assert caption == "🤑 Cada día más rico a vuestra costa"
        assert Path(out_path).exists()

    async def test_history_appended_after_json_caption_memo(self, tmp_path):
        """When caption client returns valid JSON with a memo, history file is created."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        payload = json.dumps({"caption": "¡Soy millonario!", "memo": "Lamborghini, Mónaco"}, ensure_ascii=False)
        fake_cap = _fake_caption_client(payload)
        fixed_now = datetime(2026, 6, 17, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=fixed_now,
        )

        assert caption == "¡Soy millonario!"
        assert Path(out_path).exists()
        hist_lines = load_history_lines(str(state_dir))
        assert len(hist_lines) == 1
        assert "Lamborghini, Mónaco" in hist_lines[0]
        assert "2026-06-17" in hist_lines[0]
        assert "iter" in hist_lines[0]
        captions = load_captions(str(state_dir))
        assert len(captions) == 1
        assert "¡Soy millonario!" in captions[0]

    async def test_second_run_history_injected_into_image_prompt(self, tmp_path):
        """Second run must pass prior history to the image-edit prompt."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fixed_now = datetime(2026, 6, 17, 11, 0, 0, tzinfo=pytz.UTC)

        # Run 1 — JSON caption so a memo gets persisted
        payload1 = json.dumps({"caption": "Nivel 1", "memo": "Rolls-Royce, Marbella"}, ensure_ascii=False)
        fake_img1 = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap1 = _fake_caption_client(payload1)
        await run_rich_iteration(
            settings,
            _client=fake_img1,
            _caption_client=fake_cap1,
            _data_dir=str(data_dir),
            _now=fixed_now,
        )

        # Run 2 — check that the image prompt includes the memo from run 1
        fake_img2 = _fake_client(base64.b64encode(b"PNG2").decode())
        fake_cap2 = _fake_caption_client("Nivel 2")
        await run_rich_iteration(
            settings,
            _client=fake_img2,
            _caption_client=fake_cap2,
            _data_dir=str(data_dir),
            _now=fixed_now,
        )

        img_call_kwargs = fake_img2.images.edit.call_args.kwargs
        assert "Rolls-Royce" in img_call_kwargs["prompt"]

    async def test_second_run_history_injected_into_caption_request(self, tmp_path):
        """Second run must pass prior history to the caption request messages."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fixed_now = datetime(2026, 6, 17, 11, 0, 0, tzinfo=pytz.UTC)

        # Run 1 — persist a memo
        payload1 = json.dumps({"caption": "Nivel 1", "memo": "yate, Canarias"}, ensure_ascii=False)
        fake_img1 = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap1 = _fake_caption_client(payload1)
        await run_rich_iteration(
            settings,
            _client=fake_img1,
            _caption_client=fake_cap1,
            _data_dir=str(data_dir),
            _now=fixed_now,
        )

        # Run 2 — check caption messages include history
        fake_img2 = _fake_client(base64.b64encode(b"PNG2").decode())
        fake_cap2 = _fake_caption_client("Nivel 2")
        await run_rich_iteration(
            settings,
            _client=fake_img2,
            _caption_client=fake_cap2,
            _data_dir=str(data_dir),
            _now=fixed_now,
        )

        cap_call_kwargs = fake_cap2.chat.completions.create.call_args.kwargs
        messages = cap_call_kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "yate" in combined or "Canarias" in combined

    async def test_caption_error_memo_not_appended_image_still_written(self, tmp_path):
        """When caption raises, no history line is written, but image is saved."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        bad_cap = MagicMock()
        bad_cap.chat.completions.create = AsyncMock(side_effect=RuntimeError("down"))
        non_birthday_now = datetime(2026, 7, 9, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=bad_cap,
            _data_dir=str(data_dir),
            _now=non_birthday_now,
        )

        assert caption == "🤑 Cada día más rico a vuestra costa"
        assert Path(out_path).exists()
        # Nothing appended on caption failure
        assert load_history_lines(str(state_dir)) == []
        assert load_captions(str(state_dir)) == []


    async def test_caption_appended_to_captions_file(self, tmp_path):
        """Successful caption generation stores caption in rich_captions.txt."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        payload = json.dumps({"caption": "Soy millonario hoy", "memo": "yacht"}, ensure_ascii=False)
        fake_cap = _fake_caption_client(payload)

        await run_rich_iteration(
            settings, _client=fake_img, _caption_client=fake_cap, _data_dir=str(data_dir)
        )

        captions = load_captions(str(state_dir))
        assert len(captions) == 1
        assert "Soy millonario hoy" in captions[0]

    async def test_image_prompt_limits_to_12_memos(self, tmp_path):
        """Image-edit prompt uses at most the last 12 history memos."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        # Pre-populate 13 history lines
        for i in range(13):
            append_history(str(state_dir), f"2026-05-{i + 1:02d}", i + 1, f"memo-item-{i}")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")

        await run_rich_iteration(
            settings, _client=fake_img, _caption_client=fake_cap, _data_dir=str(data_dir)
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        # Oldest entry should be excluded (only last 12 shown)
        assert "memo-item-0" not in img_prompt
        # Most recent entry should be present
        assert "memo-item-12" in img_prompt

    async def test_second_run_caption_receives_recent_captions(self, tmp_path):
        """Caption call must include recent captions from rich_captions.txt."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        # Pre-populate captions store
        append_caption(str(state_dir), "previous caption one")
        append_caption(str(state_dir), "previous caption two")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("new caption")

        await run_rich_iteration(
            settings, _client=fake_img, _caption_client=fake_cap, _data_dir=str(data_dir)
        )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "previous caption one" in combined
        assert "TEXTOS ANTERIORES" in combined


# ══════════════════════════════════════════════════════════════════════════════
# rich_image_job
# ══════════════════════════════════════════════════════════════════════════════


class TestRichImageJob:
    async def test_sends_photo_when_group_id_set(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-1001234567890")
        ctx = _make_context(settings)

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(return_value=(str(out_file), 1, "¡Soy rico!")),
        ):
            await main_mod.rich_image_job(ctx)

        ctx.bot.send_photo.assert_awaited_once()
        call_kwargs = ctx.bot.send_photo.call_args
        assert call_kwargs.kwargs["chat_id"] == "-1001234567890"
        assert call_kwargs.kwargs["caption"] == "¡Soy rico!"

    async def test_no_send_when_group_id_empty(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="")
        ctx = _make_context(settings)

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(return_value=(str(out_file), 1, "caption")),
        ):
            await main_mod.rich_image_job(ctx)

        ctx.bot.send_photo.assert_not_awaited()

    async def test_skips_when_image_ai_not_configured(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = Settings(
            telegram_bot_token="tok",
            football_data_api_key="key",
            state_dir=str(tmp_path),
            # No image keys configured
        )
        ctx = _make_context(settings)

        with patch("worldcup_bot.__main__.run_rich_iteration") as mock_run:
            await main_mod.rich_image_job(ctx)

        mock_run.assert_not_called()

    async def test_does_not_raise_on_iteration_error(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-1001234567890")
        ctx = _make_context(settings)

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(side_effect=RuntimeError("API down")),
        ):
            # Must NOT raise
            await main_mod.rich_image_job(ctx)

    async def test_does_not_raise_on_send_error(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-1001234567890")
        ctx = _make_context(settings)
        ctx.bot.send_photo = AsyncMock(side_effect=Exception("Telegram down"))

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(return_value=(str(out_file), 1, "caption")),
        ):
            await main_mod.rich_image_job(ctx)  # must not raise

    async def test_uses_caption_from_run_rich_iteration(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-1001234567890")
        ctx = _make_context(settings)

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(return_value=(str(out_file), 5, "🤑 Pringados de la porra!")),
        ):
            await main_mod.rich_image_job(ctx)

        caption = ctx.bot.send_photo.call_args.kwargs["caption"]
        assert caption == "🤑 Pringados de la porra!"


# ══════════════════════════════════════════════════════════════════════════════
# /evilSanchez — hidden manual trigger for the daily rich image
# ══════════════════════════════════════════════════════════════════════════════


def _make_evil_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


class TestCmdEvilSanchez:
    async def test_sends_image_to_group(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-1009999")
        ctx = _make_context(settings)
        update = _make_evil_update()

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(return_value=(str(out_file), 3, "🤑 caption")),
        ):
            await main_mod.cmd_evil_sanchez(update, ctx)

        ctx.bot.send_photo.assert_awaited_once()
        assert ctx.bot.send_photo.call_args.kwargs["chat_id"] == "-1009999"
        assert ctx.bot.send_photo.call_args.kwargs["caption"] == "🤑 caption"

    async def test_warns_when_image_ai_disabled(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = Settings(
            telegram_bot_token="tok",
            football_data_api_key="key",
            state_dir=str(tmp_path),
            telegram_group_id="-100",
        )
        ctx = _make_context(settings)
        update = _make_evil_update()

        with patch("worldcup_bot.__main__.run_rich_iteration") as mock_run:
            await main_mod.cmd_evil_sanchez(update, ctx)

        mock_run.assert_not_called()
        ctx.bot.send_photo.assert_not_awaited()
        assert "no está configurada" in update.message.reply_text.call_args[0][0]

    async def test_warns_when_no_group_id(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="")
        ctx = _make_context(settings)
        update = _make_evil_update()

        with patch("worldcup_bot.__main__.run_rich_iteration") as mock_run:
            await main_mod.cmd_evil_sanchez(update, ctx)

        mock_run.assert_not_called()
        ctx.bot.send_photo.assert_not_awaited()
        assert "TELEGRAM_GROUP_ID" in update.message.reply_text.call_args[0][0]

    async def test_reports_failure_on_error(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)
        update = _make_evil_update()

        with patch(
            "worldcup_bot.__main__.run_rich_iteration",
            new=AsyncMock(side_effect=Exception("LiteLLM down")),
        ):
            await main_mod.cmd_evil_sanchez(update, ctx)  # must not raise

        texts = [call.args[0] for call in update.message.reply_text.await_args_list]
        assert any("fallado" in t for t in texts)

    def test_evilsanchez_registered_but_not_in_help(self):
        import worldcup_bot.__main__ as main_mod
        from worldcup_bot.bot.handlers import _HELP_COMMANDS

        src = inspect.getsource(main_mod)
        assert 'CommandHandler("evilsanchez", cmd_evil_sanchez)' in src
        assert "evilsanchez" not in _HELP_COMMANDS.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Scheduling — main() wires up rich_image job
# ══════════════════════════════════════════════════════════════════════════════


class TestRichImageScheduling:
    def test_main_schedules_rich_image_job(self):
        """main() source contains run_daily(rich_image_job, ...)."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert "rich_image_job" in src
        assert "run_daily" in src

    def test_main_uses_rich_image_hour(self):
        """main() scheduling block references rich_image_hour from settings."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert "rich_image_hour" in src

    def test_main_names_job_rich_image(self):
        """Job is registered with name='rich_image'."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert '"rich_image"' in src or "'rich_image'" in src

    def test_main_gates_on_image_ai_enabled(self):
        """Scheduling is conditional on image_ai_enabled(settings)."""
        import worldcup_bot.__main__ as main_mod

        src = inspect.getsource(main_mod.main)
        assert "image_ai_enabled" in src

    def test_rich_image_job_importable_and_async(self):
        """rich_image_job is a top-level importable coroutine."""
        import asyncio
        from worldcup_bot.__main__ import rich_image_job

        assert callable(rich_image_job)
        assert asyncio.iscoroutinefunction(rich_image_job)

    def test_run_rich_iteration_importable(self):
        """run_rich_iteration is importable from rich_image module (for E2E use)."""
        from worldcup_bot.ai.rich_image import run_rich_iteration
        import asyncio

        assert callable(run_rich_iteration)
        assert asyncio.iscoroutinefunction(run_rich_iteration)


# ══════════════════════════════════════════════════════════════════════════════
# RICH_EDIT_PROMPT — luxury outfit + pose changes (moderation-safe framing)
# ══════════════════════════════════════════════════════════════════════════════


class TestRichEditPromptMandatoryChanges:
    def test_clothing_change_required(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "outfit" in lower or "attire" in lower
        assert "fully clothed" in lower

    def test_new_luxury_attire_per_iteration(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "new" in lower and (
            "clothing" in lower or "outfit" in lower or "attire" in lower
        )

    def test_pose_change_required(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "posture" in lower or "pose" in lower

    def test_only_face_and_skin_preserved_not_clothing(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "same face" in lower
        assert "skin tone" in lower
        assert "clothing" in lower or "outfit" in lower


# ══════════════════════════════════════════════════════════════════════════════
# build_rich_prompt — anchor parameter
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildRichPromptAnchor:
    def test_anchor_false_omits_anchor_clause(self):
        p = build_rich_prompt(anchor=False)
        assert RICH_FACE_ANCHOR_CLAUSE not in p

    def test_anchor_true_includes_anchor_clause(self):
        p = build_rich_prompt(anchor=True)
        assert RICH_FACE_ANCHOR_CLAUSE in p

    def test_anchor_true_contains_exact_match_language(self):
        p = build_rich_prompt(anchor=True)
        lower = p.lower()
        assert "exactly" in lower and "original" in lower

    def test_anchor_true_contains_original_language(self):
        p = build_rich_prompt(anchor=True)
        lower = p.lower()
        assert "original" in lower

    def test_anchor_true_contains_invent_new_clothing_and_pose(self):
        p = build_rich_prompt(anchor=True)
        lower = p.lower()
        assert "new" in lower and ("clothing" in lower or "outfit" in lower)
        assert "new" in lower and "pose" in lower
        assert "fully" in lower and "clothed" in lower

    def test_history_and_anchor_both_present(self):
        history = "- iter 1 | yacht"
        p = build_rich_prompt(history=history, anchor=True)
        assert RICH_FACE_ANCHOR_CLAUSE in p
        assert history in p
        assert p.startswith(RICH_EDIT_PROMPT)

    def test_anchor_false_with_history_no_anchor_clause(self):
        history = "- iter 1 | yacht"
        p = build_rich_prompt(history=history, anchor=False)
        assert RICH_FACE_ANCHOR_CLAUSE not in p
        assert history in p

    def test_anchor_true_no_history_starts_with_base(self):
        p = build_rich_prompt(anchor=True)
        assert p.startswith(RICH_EDIT_PROMPT)

    def test_anchor_false_no_history_equals_base_prompt(self):
        assert build_rich_prompt(anchor=False) == RICH_EDIT_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# edit_rich_image — anchor_path support
# ══════════════════════════════════════════════════════════════════════════════


class TestEditRichImageAnchor:
    async def test_anchor_path_sends_list_of_two(self, tmp_path):
        base_img = tmp_path / "base.jpg"
        anchor_img = tmp_path / "anchor.jpg"
        base_img.write_bytes(b"BASE")
        anchor_img.write_bytes(b"ANCHOR")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            anchor_path=str(anchor_img),
            prompt="rich",
            _client=fake,
        )
        call_kwargs = fake.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 2

    async def test_no_anchor_sends_single_image_not_list(self, tmp_path):
        base_img = tmp_path / "base.jpg"
        base_img.write_bytes(b"BASE")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            prompt="rich",
            _client=fake,
        )
        call_kwargs = fake.images.edit.call_args.kwargs
        assert not isinstance(call_kwargs["image"], list)

    async def test_anchor_same_as_image_path_sends_single(self, tmp_path):
        base_img = tmp_path / "base.jpg"
        base_img.write_bytes(b"BASE")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            anchor_path=str(base_img),  # same → no anchor
            prompt="rich",
            _client=fake,
        )
        call_kwargs = fake.images.edit.call_args.kwargs
        assert not isinstance(call_kwargs["image"], list)

    async def test_anchor_error_raises_runtime_error(self, tmp_path):
        base_img = tmp_path / "base.jpg"
        anchor_img = tmp_path / "anchor.jpg"
        base_img.write_bytes(b"BASE")
        anchor_img.write_bytes(b"ANCHOR")
        bad_client = MagicMock()
        bad_client.images.edit = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(RuntimeError, match="edit_rich_image failed"):
            await edit_rich_image(
                api_key="k",
                base_url="http://x",
                model="gpt-image-2",
                image_path=str(base_img),
                anchor_path=str(anchor_img),
                prompt="rich",
                _client=bad_client,
            )

    async def test_anchor_returns_decoded_bytes(self, tmp_path):
        base_img = tmp_path / "base.jpg"
        anchor_img = tmp_path / "anchor.jpg"
        base_img.write_bytes(b"BASE")
        anchor_img.write_bytes(b"ANCHOR")
        fake = _fake_client(base64.b64encode(b"RESULT").decode())
        result = await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            anchor_path=str(anchor_img),
            prompt="rich",
            _client=fake,
        )
        assert result == b"RESULT"


# ══════════════════════════════════════════════════════════════════════════════
# find_original_image
# ══════════════════════════════════════════════════════════════════════════════


class TestFindOriginalImage:
    def test_returns_jpg_original(self, tmp_path):
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPG")
        result = find_original_image(str(data_dir))
        assert result == str(orig)

    def test_returns_png_original(self, tmp_path):
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.png"
        orig.write_bytes(b"PNG")
        result = find_original_image(str(data_dir))
        assert result == str(orig)

    def test_raises_when_no_original_exists(self, tmp_path):
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            find_original_image(str(data_dir))

    def test_raises_when_rich_dir_missing(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            find_original_image(str(data_dir))

    def test_returns_original_when_evolved_exists_in_state(self, tmp_path):
        """Returns the data-dir original even when a state-dir evolved image exists."""
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPG")
        # Evolved image lives in state dir, not in data_dir/rich
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "rich_modified.png").write_bytes(b"EVOLVED")
        result = find_original_image(str(data_dir))
        assert result == str(orig)

    def test_never_returns_rich_modified(self, tmp_path):
        """find_original_image must never return rich_modified.png."""
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPG")
        result = find_original_image(str(data_dir))
        assert "rich_modified" not in result


# ══════════════════════════════════════════════════════════════════════════════
# run_rich_iteration — anchor wiring
# ══════════════════════════════════════════════════════════════════════════════


class TestRunRichIterationAnchor:
    async def test_first_run_no_evolved_single_image_no_anchor_clause(self, tmp_path):
        """First run: no evolved image → single image call, prompt without anchor clause."""
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap = _fake_caption_client("caption")

        await run_rich_iteration(
            settings, _client=fake, _caption_client=fake_cap, _data_dir=str(data_dir)
        )

        call_kwargs = fake.images.edit.call_args.kwargs
        assert not isinstance(call_kwargs["image"], list)
        assert RICH_FACE_ANCHOR_CLAUSE not in call_kwargs["prompt"]

    async def test_second_run_evolved_uses_list_with_anchor_clause(self, tmp_path):
        """Second run: evolved exists → list of 2 images, prompt has anchor clause."""
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        settings = _make_settings(tmp_path, state_dir=str(state_dir))

        # Run 1 to create the evolved image
        fake1 = _fake_client(base64.b64encode(b"PNG1").decode())
        fake_cap1 = _fake_caption_client("caption1")
        await run_rich_iteration(
            settings, _client=fake1, _caption_client=fake_cap1, _data_dir=str(data_dir)
        )

        # Run 2 — evolved now exists
        fake2 = _fake_client(base64.b64encode(b"PNG2").decode())
        fake_cap2 = _fake_caption_client("caption2")
        await run_rich_iteration(
            settings, _client=fake2, _caption_client=fake_cap2, _data_dir=str(data_dir)
        )

        call_kwargs = fake2.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 2
        assert RICH_FACE_ANCHOR_CLAUSE in call_kwargs["prompt"]

    async def test_second_run_original_is_anchor_path(self, tmp_path):
        """Second run: edit_rich_image receives anchor_path pointing to the original."""
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        orig = data_dir / "rich" / "rich_original.jpg"
        orig.write_bytes(b"JPEG")
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        settings = _make_settings(tmp_path, state_dir=str(state_dir))

        # Run 1
        fake1 = _fake_client(base64.b64encode(b"PNG1").decode())
        await run_rich_iteration(
            settings, _client=fake1, _data_dir=str(data_dir)
        )

        # Run 2 — capture edit_rich_image kwargs
        captured: dict = {}

        async def mock_edit(**kwargs):
            captured.update(kwargs)
            return b"PNG2"

        with patch("worldcup_bot.ai.rich_image.edit_rich_image", side_effect=mock_edit):
            await run_rich_iteration(settings, _data_dir=str(data_dir))

        assert captured.get("anchor_path") is not None
        assert os.path.abspath(captured["anchor_path"]) == os.path.abspath(str(orig))

    async def test_first_run_anchor_path_is_none(self, tmp_path):
        """First run (no evolved): anchor_path is None in edit call."""
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        captured: dict = {}

        async def mock_edit(**kwargs):
            captured.update(kwargs)
            return b"PNG1"

        with patch("worldcup_bot.ai.rich_image.edit_rich_image", side_effect=mock_edit):
            await run_rich_iteration(settings, _data_dir=str(data_dir))

        assert captured.get("anchor_path") is None


# ══════════════════════════════════════════════════════════════════════════════
# _normalize_caption
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeCaption:
    def test_literal_backslash_n_becomes_real_newline(self):
        assert _normalize_caption("a\\nb") == "a\nb"

    def test_literal_backslash_rn_becomes_real_newline(self):
        assert _normalize_caption("a\\r\\nb") == "a\nb"

    def test_real_crlf_normalized_to_lf(self):
        assert _normalize_caption("a\r\nb") == "a\nb"

    def test_three_newlines_collapsed_to_two(self):
        assert _normalize_caption("a\n\n\nb") == "a\n\nb"

    def test_four_newlines_collapsed_to_two(self):
        assert _normalize_caption("a\n\n\n\nb") == "a\n\nb"

    def test_two_newlines_kept_as_is(self):
        assert _normalize_caption("a\n\nb") == "a\n\nb"

    def test_strips_whole_string(self):
        assert _normalize_caption("  hello  ") == "hello"

    def test_strips_trailing_spaces_on_each_line(self):
        result = _normalize_caption("line one   \nline two   ")
        assert result == "line one\nline two"

    def test_empty_string_returns_empty(self):
        assert _normalize_caption("") == ""

    def test_no_escapes_returns_stripped(self):
        assert _normalize_caption("  ¡Soy rico!  ") == "¡Soy rico!"

    def test_mixed_real_and_escaped_newlines(self):
        result = _normalize_caption("a\\nb\r\nc")
        assert result == "a\nb\nc"

    def test_space_slash_space_becomes_newline(self):
        assert _normalize_caption("a / b / c") == "a\nb\nc"

    def test_slash_with_leading_space_and_trailing_newline_becomes_newline(self):
        assert _normalize_caption("a /\n b") == "a\nb"

    def test_slash_with_leading_newline_and_trailing_space_becomes_newline(self):
        assert _normalize_caption("a\n/ b") == "a\nb"

    def test_slash_without_space_preserved_24_7(self):
        assert "24/7" in _normalize_caption("available 24/7")

    def test_slash_without_space_preserved_and_or(self):
        assert "and/or" in _normalize_caption("and/or option")

    def test_slash_separator_in_sentence_becomes_newline(self):
        result = _normalize_caption("con hucha. / Me he regalado algo.")
        assert " / " not in result
        assert "\n" in result


# ══════════════════════════════════════════════════════════════════════════════
# generate_rich_caption — _normalize_caption applied
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateRichCaptionNormalization:
    async def test_json_caption_with_escaped_newline_is_normalized(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        payload = json.dumps(
            {"caption": "x\\ny", "memo": "Lamborghini"},
            ensure_ascii=False,
        )
        fake = _fake_caption_client(payload)
        caption, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        assert caption == "x\ny"
        assert "\n" in caption
        assert memo == "Lamborghini"

    async def test_non_json_caption_with_escaped_newline_is_normalized(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("line one\\nline two")
        caption, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        assert caption == "line one\nline two"
        assert memo == ""

    async def test_json_memo_is_stripped(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        payload = json.dumps({"caption": "texto", "memo": "  Mónaco  "}, ensure_ascii=False)
        fake = _fake_caption_client(payload)
        _, memo = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        assert memo == "Mónaco"

    async def test_slash_separator_in_caption_is_normalized_to_newline(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        payload = json.dumps(
            {"caption": "Me compré un yate. / Me fui de vacaciones. / Pringados.", "memo": "yate"},
            ensure_ascii=False,
        )
        fake = _fake_caption_client(payload)
        caption, _ = await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            _client=fake,
        )
        assert " / " not in caption
        assert "\n" in caption


# ══════════════════════════════════════════════════════════════════════════════
# RICH_CAPTION_PROMPT — line-break instruction
# ══════════════════════════════════════════════════════════════════════════════


class TestRichCaptionPromptLineBreaks:
    def test_mentions_saltos_de_linea(self):
        lower = RICH_CAPTION_PROMPT.lower()
        assert "saltos de línea" in lower or "salto de línea" in lower

    def test_forbids_slashes_with_nunca(self):
        lower = RICH_CAPTION_PROMPT.lower()
        assert "nunca" in lower

    def test_slash_character_mentioned_as_forbidden(self):
        assert "/" in RICH_CAPTION_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# RICH_EDIT_PROMPT — richer emphasis + optional accessories
# ══════════════════════════════════════════════════════════════════════════════


class TestRichEditPromptRicherEmphasis:
    def test_must_look_richer_than_input(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "richer" in lower or "more luxurious" in lower

    def test_escalate_noticeably(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "escalat" in lower or "noticeably" in lower or "noticeabl" in lower

    def test_richer_than_before_framing(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "before" in lower or "input" in lower or "previous" in lower

    def test_optional_sunglasses_or_hat_mentioned(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "sunglasses" in lower or "hat" in lower

    def test_accessories_framed_as_optional(self):
        lower = RICH_EDIT_PROMPT.lower()
        assert "may" in lower or "occasionally" in lower

    def test_still_fully_clothed(self):
        assert "fully clothed" in RICH_EDIT_PROMPT.lower()

    def test_still_preserves_face(self):
        assert "same face" in RICH_EDIT_PROMPT.lower()

    def test_still_preserves_skin_tone(self):
        assert "skin tone" in RICH_EDIT_PROMPT.lower()

    def test_still_preserves_features(self):
        assert "features" in RICH_EDIT_PROMPT.lower()


class TestRichFaceAnchorClauseRicherEmphasis:
    def test_surpass_wealthy_style_mentioned(self):
        lower = RICH_FACE_ANCHOR_CLAUSE.lower()
        assert "surpass" in lower or "exceed" in lower or "richer" in lower

    def test_not_merely_match_framing(self):
        lower = RICH_FACE_ANCHOR_CLAUSE.lower()
        assert "not merely" in lower or "not just" in lower or "surpass" in lower

    def test_still_fully_clothed(self):
        assert "fully" in RICH_FACE_ANCHOR_CLAUSE.lower()
        assert "clothed" in RICH_FACE_ANCHOR_CLAUSE.lower()

    def test_still_preserves_face_exactly(self):
        assert "exactly" in RICH_FACE_ANCHOR_CLAUSE.lower()
        assert "original" in RICH_FACE_ANCHOR_CLAUSE.lower()


# ══════════════════════════════════════════════════════════════════════════════
# build_rich_prompt — themes parameter
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildRichPromptThemes:
    def test_themes_nonempty_adds_clause_to_prompt(self):
        themes = "golden Viking helmet, jewel-encrusted baguette"
        p = build_rich_prompt(themes=themes)
        assert themes in p
        assert "opulent" in p.lower() or "country-themed" in p.lower() or "luxury" in p.lower()

    def test_themes_empty_string_no_clause(self):
        p = build_rich_prompt(themes="")
        assert "country-themed" not in p
        assert "yesterday" not in p.lower()

    def test_themes_none_equivalent_empty(self):
        """Default (no themes arg) produces same result as themes=''."""
        assert build_rich_prompt() == build_rich_prompt(themes="")

    def test_themes_clause_appended_after_base(self):
        themes = "golden tea cup"
        p = build_rich_prompt(themes=themes)
        assert p.startswith(RICH_EDIT_PROMPT)

    def test_themes_with_history_both_present(self):
        history = "- iter 1 | Rolls-Royce"
        themes = "golden tea cup"
        p = build_rich_prompt(history=history, themes=themes)
        assert history in p
        assert themes in p

    def test_themes_with_anchor_both_present(self):
        themes = "platter of nachos"
        p = build_rich_prompt(anchor=True, themes=themes)
        assert themes in p
        assert RICH_FACE_ANCHOR_CLAUSE in p

    def test_themes_clause_comes_before_anchor_clause(self):
        themes = "golden Viking helmet"
        p = build_rich_prompt(anchor=True, themes=themes)
        themes_pos = p.index(themes)
        anchor_pos = p.index(RICH_FACE_ANCHOR_CLAUSE)
        assert themes_pos < anchor_pos

    def test_history_anchor_themes_all_present(self):
        history = "- iter 1 | yacht"
        themes = "golden baguette"
        p = build_rich_prompt(history=history, anchor=True, themes=themes)
        assert history in p
        assert themes in p
        assert RICH_FACE_ANCHOR_CLAUSE in p


# ══════════════════════════════════════════════════════════════════════════════
# RICH_THEME_PROMPT — content checks
# ══════════════════════════════════════════════════════════════════════════════


class TestRichThemePrompt:
    def test_constant_exists(self):
        assert RICH_THEME_PROMPT is not None
        assert isinstance(RICH_THEME_PROMPT, str)

    def test_mentions_comma_separated(self):
        assert "comma-separated" in RICH_THEME_PROMPT.lower()

    def test_mentions_one_element_per_country(self):
        lower = RICH_THEME_PROMPT.lower()
        assert "one element" in lower or "one per" in lower or "exactly one" in lower

    def test_includes_norway_example(self):
        assert "Norway" in RICH_THEME_PROMPT

    def test_includes_france_example(self):
        assert "France" in RICH_THEME_PROMPT

    def test_includes_usa_example(self):
        assert "USA" in RICH_THEME_PROMPT

    def test_no_extra_text_instruction(self):
        lower = RICH_THEME_PROMPT.lower()
        assert "no extra text" in lower or "only" in lower

    def test_instructs_not_always_gold(self):
        lower = RICH_THEME_PROMPT.lower()
        assert "not" in lower and ("gold" in lower or "golden" in lower)

    def test_mentions_varied_luxury_materials(self):
        lower = RICH_THEME_PROMPT.lower()
        materials = ["diamond", "platinum", "marble", "silk", "crystal", "caviar"]
        assert any(m in lower for m in materials)


# ══════════════════════════════════════════════════════════════════════════════
# generate_wealth_themes
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateWealthThemes:
    async def test_returns_model_output(self):
        fake = _fake_caption_client("golden Viking helmet, jewel-encrusted baguette")
        result = await generate_wealth_themes(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            winners=["Norway", "France"],
            _client=fake,
        )
        assert result == "golden Viking helmet, jewel-encrusted baguette"

    async def test_empty_winners_returns_empty_string(self):
        result = await generate_wealth_themes(
            api_key="k", base_url="http://x", model="gpt-4", winners=[]
        )
        assert result == ""

    async def test_client_raises_returns_fallback_string(self):
        bad = MagicMock()
        bad.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
        result = await generate_wealth_themes(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            winners=["Norway", "France"],
            _client=bad,
        )
        assert "Norway" in result
        assert "France" in result

    async def test_fallback_format_one_per_country(self):
        bad = MagicMock()
        bad.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        result = await generate_wealth_themes(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            winners=["Mexico"],
            _client=bad,
        )
        assert "Mexico" in result
        assert "opulent" in result.lower() or "luxury" in result.lower()

    async def test_model_empty_response_returns_fallback(self):
        fake = _fake_caption_client("   ")  # whitespace-only → stripped to ""
        result = await generate_wealth_themes(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            winners=["England"],
            _client=fake,
        )
        assert "England" in result

    async def test_single_winner_returns_single_element(self):
        fake = _fake_caption_client("golden tea cup")
        result = await generate_wealth_themes(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            winners=["England"],
            _client=fake,
        )
        assert result == "golden tea cup"

    async def test_winners_list_sent_to_client(self):
        fake = _fake_caption_client("golden helmet")
        await generate_wealth_themes(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            winners=["Norway", "Mexico"],
            _client=fake,
        )
        call_kwargs = fake.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert any("Norway" in str(m.get("content", "")) and "Mexico" in str(m.get("content", ""))
                   for m in messages)

    async def test_never_raises(self):
        bad = MagicMock()
        bad.chat.completions.create = AsyncMock(side_effect=Exception("nuclear"))
        # Must not raise regardless of the exception
        result = await generate_wealth_themes(
            api_key="k", base_url="http://x", model="gpt-4", winners=["USA"], _client=bad
        )
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# run_rich_iteration — winners/themes flow
# ══════════════════════════════════════════════════════════════════════════════


class TestRunRichIterationWinners:
    async def test_winners_causes_themes_clause_in_image_prompt(self, tmp_path):
        """When winners are provided and themes resolved, the image prompt contains the themes clause."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")
        themes_value = "golden Viking helmet, gourmet nachos"

        with patch(
            "worldcup_bot.ai.rich_image.generate_wealth_themes",
            new=AsyncMock(return_value=themes_value),
        ):
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _caption_client=fake_cap,
                _data_dir=str(data_dir),
                winners=["Norway", "Mexico"],
            )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert themes_value in img_prompt
        assert "country-themed" in img_prompt.lower() or "opulent" in img_prompt.lower()

    async def test_winners_none_no_themes_clause(self, tmp_path):
        """When winners=None, no themes clause is added to the image prompt."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            winners=None,
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert "country-themed" not in img_prompt.lower()
        assert "yesterday" not in img_prompt.lower()

    async def test_winners_empty_list_no_themes_clause(self, tmp_path):
        """When winners=[], generate_wealth_themes returns '' and no clause is added."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            winners=[],
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert "country-themed" not in img_prompt.lower()

    async def test_themes_not_injected_into_caption_messages(self, tmp_path):
        """Themes must NOT appear in the caption request (caption reverted to rude-only)."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")
        themes_value = "silk-lined tea set, crystal nachos platter"

        with patch(
            "worldcup_bot.ai.rich_image.generate_wealth_themes",
            new=AsyncMock(return_value=themes_value),
        ):
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _caption_client=fake_cap,
                _data_dir=str(data_dir),
                winners=["England", "Mexico"],
            )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        # Themes text must NOT be present in the caption request
        assert themes_value not in combined
        assert "países que ganaron ayer" not in combined

    async def test_pose_injected_into_image_prompt(self, tmp_path):
        """run_rich_iteration must inject the randomly chosen pose into the image prompt."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")
        chosen_pose = "relaxing in an infinity pool"

        with patch("worldcup_bot.ai.rich_image.random.choice", return_value=chosen_pose):
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _caption_client=fake_cap,
                _data_dir=str(data_dir),
            )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert chosen_pose in img_prompt

    async def test_pose_not_injected_into_caption(self, tmp_path):
        """The randomly chosen pose must NOT appear in the caption request messages."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")
        chosen_pose = "getting a spa massage"

        with patch("worldcup_bot.ai.rich_image.random.choice", return_value=chosen_pose):
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _caption_client=fake_cap,
                _data_dir=str(data_dir),
            )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert chosen_pose not in combined

    async def test_winners_no_chat_config_no_themes(self, tmp_path):
        """When chat model is not configured, themes='' (no LLM call)."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(
            tmp_path,
            state_dir=str(state_dir),
            openai_api_key="",
            openai_base_url="",
            openai_model="",
        )
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())

        with patch(
            "worldcup_bot.ai.rich_image.generate_wealth_themes",
        ) as mock_themes:
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _data_dir=str(data_dir),
                winners=["Norway"],
            )
        mock_themes.assert_not_called()

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert "country-themed" not in img_prompt.lower()


# ══════════════════════════════════════════════════════════════════════════════
# rich_image_job — winner derivation
# ══════════════════════════════════════════════════════════════════════════════


def _make_mock_match(status: str, winner: str | None, home_name: str, away_name: str):
    m = MagicMock()
    m.status = status
    m.winner = winner
    m.home_name = home_name
    m.away_name = away_name
    return m


class TestRichImageJobWinners:
    async def test_home_team_winner_extracted(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        match = _make_mock_match("FINISHED", "HOME_TEAM", "Norway", "Sweden")
        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.return_value = [match]

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ) as mock_run,
        ):
            await main_mod.rich_image_job(ctx)

        mock_run.assert_awaited_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["winners"] == ["Norway"]

    async def test_away_team_winner_extracted(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        match = _make_mock_match("FINISHED", "AWAY_TEAM", "Norway", "France")
        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.return_value = [match]

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ) as mock_run,
        ):
            await main_mod.rich_image_job(ctx)

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["winners"] == ["France"]

    async def test_draw_excluded_from_winners(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        match = _make_mock_match("FINISHED", "DRAW", "Spain", "Portugal")
        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.return_value = [match]

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ) as mock_run,
        ):
            await main_mod.rich_image_job(ctx)

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["winners"] == []

    async def test_non_finished_excluded(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        in_play = _make_mock_match("IN_PLAY", "HOME_TEAM", "Brazil", "Argentina")
        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.return_value = [in_play]

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ) as mock_run,
        ):
            await main_mod.rich_image_job(ctx)

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["winners"] == []

    async def test_multiple_matches_all_winners_collected(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        matches = [
            _make_mock_match("FINISHED", "HOME_TEAM", "Norway", "Sweden"),
            _make_mock_match("FINISHED", "AWAY_TEAM", "Germany", "France"),
            _make_mock_match("FINISHED", "DRAW", "Spain", "Italy"),
        ]
        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.return_value = matches

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ) as mock_run,
        ):
            await main_mod.rich_image_job(ctx)

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["winners"] == ["Norway", "France"]

    async def test_football_client_error_winners_empty_job_still_runs(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.side_effect = Exception("API down")

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ) as mock_run,
        ):
            await main_mod.rich_image_job(ctx)

        mock_run.assert_awaited_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["winners"] == []

    async def test_football_client_error_job_does_not_raise(self, tmp_path):
        import worldcup_bot.__main__ as main_mod

        settings = _make_settings(tmp_path, telegram_group_id="-100")
        ctx = _make_context(settings)

        mock_fc = MagicMock()
        mock_fc.get_football_day_matches.side_effect = Exception("network error")

        out_file = tmp_path / "state" / "rich_modified.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"PNG")

        with (
            patch("worldcup_bot.__main__.make_client", return_value=mock_fc),
            patch(
                "worldcup_bot.__main__.run_rich_iteration",
                new=AsyncMock(return_value=(str(out_file), 1, "cap")),
            ),
        ):
            await main_mod.rich_image_job(ctx)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# POSE_ACTIVITIES constant
# ══════════════════════════════════════════════════════════════════════════════


class TestPoseActivities:
    def test_is_a_list(self):
        assert isinstance(POSE_ACTIVITIES, list)

    def test_has_at_least_ten_entries(self):
        assert len(POSE_ACTIVITIES) >= 10

    def test_all_entries_are_strings(self):
        assert all(isinstance(p, str) for p in POSE_ACTIVITIES)

    def test_all_entries_non_empty(self):
        assert all(p.strip() for p in POSE_ACTIVITIES)

    def test_no_champagne_toast_as_entry(self):
        """Champagne toast must not be one of the pose options (it was the repetitive default)."""
        combined = " ".join(POSE_ACTIVITIES).lower()
        assert "champagne" not in combined or "toast" not in combined

    def test_contains_variety_of_activities(self):
        """Should cover at least 3 distinct activity categories."""
        combined = " ".join(POSE_ACTIVITIES).lower()
        active = any(w in combined for w in ["danc", "walk", "laugh", "party"])
        relaxed = any(w in combined for w in ["loung", "nap", "relax", "spa", "massage"])
        social = any(w in combined for w in ["entourage", "crowd", "companion", "staff", "embrac"])
        assert active and relaxed and social


# ══════════════════════════════════════════════════════════════════════════════
# build_rich_prompt — pose parameter
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildRichPromptPose:
    def test_pose_nonempty_adds_clause(self):
        pose = "dancing at a lavish party"
        p = build_rich_prompt(pose=pose)
        assert pose in p

    def test_pose_empty_no_clause(self):
        p = build_rich_prompt(pose="")
        assert "champagne" not in p.lower()
        assert "In THIS image" not in p

    def test_pose_default_no_clause(self):
        p = build_rich_prompt()
        assert "In THIS image" not in p

    def test_pose_clause_starts_with_pose_intro(self):
        pose = "relaxing in an infinity pool"
        p = build_rich_prompt(pose=pose)
        assert f"In THIS image, show the person {pose}" in p

    def test_pose_clause_includes_vary_instruction(self):
        pose = "getting a spa massage"
        p = build_rich_prompt(pose=pose)
        lower = p.lower()
        assert "vary" in lower and "pose" in lower

    def test_pose_with_history_themes_anchor_all_present(self):
        history = "- iter 1 | yacht"
        themes = "silk-lined tea set"
        pose = "striding through a luxury penthouse"
        p = build_rich_prompt(history=history, themes=themes, pose=pose, anchor=True)
        assert history in p
        assert themes in p
        assert pose in p
        assert RICH_FACE_ANCHOR_CLAUSE in p

    def test_pose_clause_before_anchor(self):
        pose = "napping in an opulent king-size bed"
        p = build_rich_prompt(anchor=True, pose=pose)
        pose_pos = p.index(pose)
        anchor_pos = p.index(RICH_FACE_ANCHOR_CLAUSE)
        assert pose_pos < anchor_pos

    def test_pose_clause_after_themes_clause(self):
        themes = "diamond-encrusted longship"
        pose = "lounging on a chaise longue"
        p = build_rich_prompt(themes=themes, pose=pose)
        themes_pos = p.index(themes)
        pose_pos = p.index(pose)
        assert themes_pos < pose_pos


# ══════════════════════════════════════════════════════════════════════════════
# Birthday mode — July 8 every year
# ══════════════════════════════════════════════════════════════════════════════


class TestRichBirthdayMode:
    """Tests for the birthday mode (July 8 every year).

    Contract under test:
    - RICH_BIRTHDAY_MONTH=7, RICH_BIRTHDAY_DAY=8, RICH_BIRTH_YEAR=1984
    - is_rich_birthday(now) → True iff month==7 and day==8
    - rich_birthday_age(now) → now.year - RICH_BIRTH_YEAR
    - build_rich_prompt(birthday=True, age=N) → birthday-party clause with str(N) + cake/birthday words
    - build_rich_prompt(birthday=False) → no birthday clause; augments not replaces base
    - run_rich_iteration(_now=July 8) → prompt contains birthday clause + "42"; caption
      messages receive birthday instruction mentioning age; birthday-aware fallback when
      no chat model configured
    """

    # ── is_rich_birthday ───────────────────────────────────────────────────────

    def test_is_rich_birthday_true_on_july_8_2026(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_birthday
        import pytz
        assert is_rich_birthday(datetime(2026, 7, 8, 10, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_rich_birthday_true_another_year_july_8(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_birthday
        import pytz
        assert is_rich_birthday(datetime(2030, 7, 8, 12, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_rich_birthday_false_july_7(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_birthday
        import pytz
        assert is_rich_birthday(datetime(2026, 7, 7, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_birthday_false_july_9(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_birthday
        import pytz
        assert is_rich_birthday(datetime(2026, 7, 9, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_birthday_false_jan_8_guards_month_day_confusion(self):
        # Jan 8 has day==8 but wrong month — guards (month, day) transposition.
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_birthday
        import pytz
        assert is_rich_birthday(datetime(2026, 1, 8, 10, 0, 0, tzinfo=pytz.UTC)) is False

    # ── rich_birthday_age ──────────────────────────────────────────────────────

    def test_rich_birthday_age_2026_is_42(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import rich_birthday_age, RICH_BIRTH_YEAR
        import pytz
        age = rich_birthday_age(datetime(2026, 7, 8, tzinfo=pytz.UTC))
        assert age == 2026 - RICH_BIRTH_YEAR

    def test_rich_birthday_age_increments_year_on_year(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import rich_birthday_age
        import pytz
        age_2026 = rich_birthday_age(datetime(2026, 7, 8, tzinfo=pytz.UTC))
        age_2027 = rich_birthday_age(datetime(2027, 7, 8, tzinfo=pytz.UTC))
        assert age_2027 == age_2026 + 1

    # ── build_rich_prompt — birthday parameter ─────────────────────────────────

    def test_build_rich_prompt_birthday_true_contains_age_and_celebration(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(birthday=True, age=42)
        assert "42" in p
        lower = p.lower()
        assert (
            "birthday" in lower
            or "cumpleaños" in lower
            or "cake" in lower
            or "tarta" in lower
            or "celebr" in lower
            or "party" in lower
            or "fiesta" in lower
        )

    def test_build_rich_prompt_birthday_false_no_birthday_clause(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(birthday=False)
        lower = p.lower()
        assert "birthday" not in lower
        assert "cumpleaños" not in lower
        assert "42" not in p

    def test_build_rich_prompt_birthday_true_augments_base_not_replaces(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_EDIT_PROMPT
        p = build_rich_prompt(birthday=True, age=42)
        # Birthday mode augments — must start with (and include) the base prompt
        assert p.startswith(RICH_EDIT_PROMPT)
        # Core identity-preservation language must still be present
        assert "same face" in p.lower()

    # ── run_rich_iteration — birthday integration ───────────────────────────────

    async def test_run_rich_iteration_birthday_date_prompt_has_birthday_clause(self, tmp_path):
        """On July 8, the image-edit prompt must contain the birthday clause with age 42."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("¡Feliz cumpleaños!")
        birthday_now = datetime(2026, 7, 8, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=birthday_now,
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert "42" in img_prompt
        lower = img_prompt.lower()
        assert (
            "birthday" in lower
            or "cumpleaños" in lower
            or "cake" in lower
            or "tarta" in lower
            or "celebr" in lower
            or "party" in lower
            or "fiesta" in lower
        )

    async def test_run_rich_iteration_non_birthday_date_no_birthday_clause(self, tmp_path):
        """On a non-birthday date, image-edit prompt must NOT contain birthday clause."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("normal caption")
        non_birthday_now = datetime(2026, 7, 9, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=non_birthday_now,
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        lower = img_prompt.lower()
        assert "birthday" not in lower
        assert "cumpleaños" not in lower

    async def test_run_rich_iteration_birthday_caption_receives_birthday_instruction(self, tmp_path):
        """On July 8, the caption messages must contain a birthday instruction mentioning age 42."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("¡Feliz cumpleaños!")
        birthday_now = datetime(2026, 7, 8, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=birthday_now,
        )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        # Collect all text from every message (system + user parts)
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        assert "42" in all_text
        lower = all_text.lower()
        assert "birthday" in lower or "cumpleaños" in lower or "celebr" in lower

    async def test_run_rich_iteration_birthday_fallback_caption_when_no_chat(self, tmp_path):
        """On birthday with no chat model configured, fallback caption must be birthday-aware."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG")

        settings = _make_settings(
            tmp_path,
            state_dir=str(state_dir),
            openai_api_key="",
            openai_base_url="",
            openai_model="",
        )
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        birthday_now = datetime(2026, 7, 8, 11, 0, 0, tzinfo=pytz.UTC)

        _, _, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _data_dir=str(data_dir),
            _now=birthday_now,
        )

        lower = caption.lower()
        assert "birthday" in lower or "cumpleaños" in lower or "42" in caption


# ══════════════════════════════════════════════════════════════════════════════
# Micky birthday mode (July 10 every year)
# ══════════════════════════════════════════════════════════════════════════════


class TestMickyBirthdayMode:
    """Tests for the Micky birthday special (July 10 every year).

    Contract under test:
    - MICKY_BIRTHDAY_MONTH=7, MICKY_BIRTHDAY_DAY=10, MICKY_BIRTH_YEAR=1984
    - is_micky_birthday(now) → True iff month==7 and day==10
    - micky_birthday_age(now) → now.year - MICKY_BIRTH_YEAR (42 in 2026, 43 in 2027)
    - find_micky_image(data_dir) → data/rich/micky.jpg; raises FileNotFoundError if absent
    - edit_rich_image(extra_paths=[micky_path]) → 3-element image list; all fhs closed
    - build_rich_prompt(micky_birthday=True, age=42) → Micky protagonist clause + "42"
    - generate_rich_caption(micky_birthday=True, age=42) → Micky felicitation in user parts
    - run_rich_iteration(_now=July 10) → 3 images, rich_micky_birthday.png, chain untouched
    - run_rich_iteration(_now=July 10, micky.jpg absent) → graceful fallback, rich_modified.png
    - REGRESSION: July 8 still triggers rich birthday path; July 15 is a normal day
    """

    # ── is_micky_birthday ─────────────────────────────────────────────────────

    def test_is_micky_birthday_true_on_july_10_2026(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_micky_birthday
        import pytz
        assert is_micky_birthday(datetime(2026, 7, 10, 10, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_micky_birthday_true_another_year_july_10(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_micky_birthday
        import pytz
        assert is_micky_birthday(datetime(2030, 7, 10, 12, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_micky_birthday_false_july_9(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_micky_birthday
        import pytz
        assert is_micky_birthday(datetime(2026, 7, 9, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_micky_birthday_false_july_11(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_micky_birthday
        import pytz
        assert is_micky_birthday(datetime(2026, 7, 11, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_micky_birthday_false_july_8_rich_birthday(self):
        # July 8 is rich's birthday — NOT Micky's. Guards off-by-two-day confusion.
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_micky_birthday
        import pytz
        assert is_micky_birthday(datetime(2026, 7, 8, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_micky_birthday_false_oct_10_guards_month_day_transposition(self):
        # Oct 10 has day==10 but wrong month — guards month/day transposition.
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_micky_birthday
        import pytz
        assert is_micky_birthday(datetime(2026, 10, 10, 10, 0, 0, tzinfo=pytz.UTC)) is False

    # ── micky_birthday_age ────────────────────────────────────────────────────

    def test_micky_birthday_age_2026_is_42(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import micky_birthday_age, MICKY_BIRTH_YEAR
        import pytz
        age = micky_birthday_age(datetime(2026, 7, 10, tzinfo=pytz.UTC))
        assert age == 2026 - MICKY_BIRTH_YEAR
        assert age == 42  # explicit: 2026 - 1984

    def test_micky_birthday_age_2027_is_43(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import micky_birthday_age
        import pytz
        age_2026 = micky_birthday_age(datetime(2026, 7, 10, tzinfo=pytz.UTC))
        age_2027 = micky_birthday_age(datetime(2027, 7, 10, tzinfo=pytz.UTC))
        assert age_2027 == age_2026 + 1
        assert age_2027 == 43  # explicit: 2027 - 1984

    # ── find_micky_image ──────────────────────────────────────────────────────

    def test_find_micky_image_returns_jpg_when_present(self, tmp_path):
        from worldcup_bot.ai.rich_image import find_micky_image
        rich_dir = tmp_path / "rich"
        rich_dir.mkdir(parents=True)
        micky_jpg = rich_dir / "micky.jpg"
        micky_jpg.write_bytes(b"MICKY")
        result = find_micky_image(str(tmp_path))
        assert os.path.abspath(result) == os.path.abspath(str(micky_jpg))

    def test_find_micky_image_raises_file_not_found_when_absent(self, tmp_path):
        from worldcup_bot.ai.rich_image import find_micky_image
        (tmp_path / "rich").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            find_micky_image(str(tmp_path))

    # ── edit_rich_image — extra_paths ─────────────────────────────────────────

    async def test_extra_paths_sends_list_of_three(self, tmp_path):
        """With anchor + one extra_path, edit receives a 3-element image list."""
        base_img = tmp_path / "base.jpg"
        anchor_img = tmp_path / "anchor.jpg"
        extra_img = tmp_path / "micky.jpg"
        base_img.write_bytes(b"BASE")
        anchor_img.write_bytes(b"ANCHOR")
        extra_img.write_bytes(b"MICKY")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            anchor_path=str(anchor_img),
            extra_paths=[str(extra_img)],
            prompt="rich birthday micky",
            _client=fake,
        )
        call_kwargs = fake.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 3

    async def test_extra_paths_file_handles_all_closed_after_call(self, tmp_path):
        """ExitStack closes all file handles (base + anchor + extra) after edit returns."""
        base_img = tmp_path / "base.jpg"
        anchor_img = tmp_path / "anchor.jpg"
        extra_img = tmp_path / "micky.jpg"
        base_img.write_bytes(b"BASE")
        anchor_img.write_bytes(b"ANCHOR")
        extra_img.write_bytes(b"MICKY")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            anchor_path=str(anchor_img),
            extra_paths=[str(extra_img)],
            prompt="rich birthday micky",
            _client=fake,
        )
        images = fake.images.edit.call_args.kwargs["image"]
        assert all(fh.closed for fh in images)

    async def test_extra_paths_none_preserves_two_image_behavior(self, tmp_path):
        """extra_paths=None → existing 2-image path unchanged (regression guard)."""
        base_img = tmp_path / "base.jpg"
        anchor_img = tmp_path / "anchor.jpg"
        base_img.write_bytes(b"BASE")
        anchor_img.write_bytes(b"ANCHOR")
        fake = _fake_client()
        await edit_rich_image(
            api_key="k",
            base_url="http://x",
            model="gpt-image-2",
            image_path=str(base_img),
            anchor_path=str(anchor_img),
            extra_paths=None,
            prompt="rich",
            _client=fake,
        )
        call_kwargs = fake.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 2

    # ── build_rich_prompt — micky_birthday parameter ──────────────────────────

    def test_build_rich_prompt_micky_birthday_true_contains_age_and_protagonist_clause(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(micky_birthday=True, age=42)
        assert "42" in p
        lower = p.lower()
        assert "micky" in lower
        assert (
            "birthday" in lower
            or "cumpleaños" in lower
            or "celebr" in lower
            or "protagonist" in lower
        )

    def test_build_rich_prompt_micky_birthday_false_no_micky_clause(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(micky_birthday=False)
        assert "micky" not in p.lower()
        assert "MICKY" not in p

    def test_build_rich_prompt_micky_birthday_augments_not_replaces(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_EDIT_PROMPT
        p = build_rich_prompt(micky_birthday=True, age=42)
        assert p.startswith(RICH_EDIT_PROMPT)
        assert "same face" in p.lower()

    def test_build_rich_prompt_rich_birthday_flag_does_not_inject_micky(self):
        """build_rich_prompt(birthday=True, micky_birthday=False) has rich clause, no Micky."""
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(birthday=True, age=42, micky_birthday=False)
        assert "42" in p
        assert "micky" not in p.lower()

    # ── generate_rich_caption — micky_birthday parameter ─────────────────────

    async def test_generate_rich_caption_micky_birthday_injects_felicitation_and_age(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("¡Feliz cumple Micky!")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            micky_birthday=True,
            age=42,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        assert "42" in all_text
        lower = all_text.lower()
        assert "micky" in lower
        assert "felicit" in lower or "feliz" in lower or "cumpleaños" in lower

    async def test_generate_rich_caption_no_micky_birthday_no_micky_instruction(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("normal caption")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=1,
            micky_birthday=False,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        assert "micky" not in all_text.lower()

    # ── run_rich_iteration — July 10 end-to-end ───────────────────────────────

    async def test_run_rich_iteration_micky_birthday_edit_gets_three_images(self, tmp_path):
        """On July 10 with a pre-existing evolved image, edit receives 3 images."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        # Pre-seed evolved image so base != original → 3-image path
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_MICKY_RESULT").decode())
        fake_cap = _fake_caption_client("¡Feliz Micky!")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        call_kwargs = fake_img.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 3

    async def test_run_rich_iteration_micky_birthday_prompt_has_micky_clause(self, tmp_path):
        """On July 10, the image-edit prompt must contain Micky protagonist clause with age 42."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("¡Feliz Micky!")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert "42" in img_prompt
        lower = img_prompt.lower()
        assert "micky" in lower
        assert (
            "birthday" in lower
            or "cumpleaños" in lower
            or "celebr" in lower
            or "protagonist" in lower
        )

    async def test_run_rich_iteration_micky_birthday_output_is_separate_file(self, tmp_path):
        """On July 10, output path is rich_micky_birthday.png, not rich_modified.png."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_OUT").decode())
        fake_cap = _fake_caption_client("¡Feliz Micky!")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        assert os.path.basename(out_path) == "rich_micky_birthday.png"
        assert Path(out_path).read_bytes() == b"PNG_OUT"

    async def test_run_rich_iteration_micky_birthday_does_not_overwrite_rich_modified(self, tmp_path):
        """On July 10, rich_modified.png is NOT overwritten (evolution chain stays clean)."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        evolved_bytes = b"PNG_EVOLVED_UNTOUCHED"
        (state_dir / "rich_modified.png").write_bytes(evolved_bytes)

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_MICKY_NEW").decode())
        fake_cap = _fake_caption_client("¡Feliz Micky!")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        assert (state_dir / "rich_modified.png").read_bytes() == evolved_bytes

    async def test_run_rich_iteration_micky_birthday_level_not_bumped(self, tmp_path):
        """On July 10, save_level is NOT called — level counter stays unchanged."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")
        save_level(str(state_dir), 5)

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("¡Feliz Micky!")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        assert load_level(str(state_dir)) == 5

    async def test_run_rich_iteration_micky_birthday_caption_has_micky_felicitation(self, tmp_path):
        """On July 10, the caption messages sent to the chat model include Micky felicitation."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("¡Feliz cumpleaños Micky!")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        assert "42" in all_text
        lower = all_text.lower()
        assert "micky" in lower
        assert "felicit" in lower or "feliz" in lower or "cumpleaños" in lower

    async def test_run_rich_iteration_micky_birthday_fallback_caption_when_no_chat(self, tmp_path):
        """On July 10 with no chat model, fallback caption must be Micky birthday-aware."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (data_dir / "rich" / "micky.jpg").write_bytes(b"JPEG_MICKY")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(
            tmp_path,
            state_dir=str(state_dir),
            openai_api_key="",
            openai_base_url="",
            openai_model="",
        )
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        _, _, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        lower = caption.lower()
        assert "micky" in lower
        assert "42" in caption or "cumpleaños" in lower or "birthday" in lower

    # ── run_rich_iteration — July 10, micky.jpg absent → graceful fallback ────

    async def test_run_rich_iteration_micky_absent_falls_back_two_images(self, tmp_path):
        """When micky.jpg is absent on July 10, falls back to normal 2-image path (no crash)."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        # Deliberately no micky.jpg
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_FALLBACK").decode())
        fake_cap = _fake_caption_client("normal")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        call_kwargs = fake_img.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 2

    async def test_run_rich_iteration_micky_absent_output_is_rich_modified(self, tmp_path):
        """When micky.jpg is absent on July 10, output falls back to rich_modified.png."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        # Deliberately no micky.jpg
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_NORMAL").decode())
        fake_cap = _fake_caption_client("normal")
        micky_day = datetime(2026, 7, 10, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=micky_day,
        )

        assert os.path.basename(out_path) == "rich_modified.png"
        assert Path(out_path).read_bytes() == b"PNG_NORMAL"

    # ── REGRESSIONS ───────────────────────────────────────────────────────────

    async def test_regression_rich_birthday_july_8_two_images_and_rich_modified(self, tmp_path):
        """REGRESSION: July 8 (rich's birthday) still uses 2-image path and overwrites rich_modified.png."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_OLD")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_BIRTHDAY").decode())
        fake_cap = _fake_caption_client("¡Feliz cumple, rico!")
        rich_birthday = datetime(2026, 7, 8, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=rich_birthday,
        )

        call_kwargs = fake_img.images.edit.call_args.kwargs
        assert isinstance(call_kwargs["image"], list)
        assert len(call_kwargs["image"]) == 2
        assert os.path.basename(out_path) == "rich_modified.png"
        assert Path(out_path).read_bytes() == b"PNG_BIRTHDAY"
        img_prompt = call_kwargs["prompt"]
        assert "42" in img_prompt
        lower = img_prompt.lower()
        assert (
            "birthday" in lower
            or "cumpleaños" in lower
            or "cake" in lower
            or "celebr" in lower
        )

    async def test_regression_normal_day_july_15_no_birthday_clause_rich_modified(self, tmp_path):
        """REGRESSION: A normal non-birthday day (July 15) has no birthday clause."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_OLD")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_NORMAL").decode())
        fake_cap = _fake_caption_client("normal")
        normal_day = datetime(2026, 7, 15, 11, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=normal_day,
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        lower = img_prompt.lower()
        assert "birthday" not in lower
        assert "cumpleaños" not in lower
        assert "micky" not in lower
        assert os.path.basename(out_path) == "rich_modified.png"


# ══════════════════════════════════════════════════════════════════════════════
# Apex mode (July 20 — day after the World Cup Final)
# ══════════════════════════════════════════════════════════════════════════════


class TestRichApexMode:
    """Tests for the Apex special day (July 20 every year).

    Contract under test:
    - RICH_APEX_MONTH=7, RICH_APEX_DAY=20
    - is_rich_apex(now) → True iff month==7 and day==20
    - build_rich_prompt(apex=True, apex_country="Spain") → apex clause with "Spain"
    - build_rich_prompt(apex=True, apex_country="") → no dangling "{}" in output
    - build_rich_prompt(apex=True) → apex clause BEFORE anchor clause
    - generate_rich_caption(apex=True, apex_country="Spain") → apex instruction in user parts
    - run_rich_iteration(_now=July 20, winners=["Spain"]) → normal promote (rich_modified.png),
      level incremented, prompt has apex language + "Spain"
    - run_rich_iteration(_now=July 20, winners=[]) → no crash, no dangling braces
    """

    # ── is_rich_apex ──────────────────────────────────────────────────────────

    def test_is_rich_apex_true_on_july_20_2026(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_apex
        import pytz
        assert is_rich_apex(datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_rich_apex_true_another_year_july_20(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_apex
        import pytz
        assert is_rich_apex(datetime(2030, 7, 20, 12, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_rich_apex_false_july_19(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_apex
        import pytz
        assert is_rich_apex(datetime(2026, 7, 19, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_apex_false_july_21_death_day(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_apex
        import pytz
        assert is_rich_apex(datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_apex_false_july_8_rich_birthday(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_apex
        import pytz
        assert is_rich_apex(datetime(2026, 7, 8, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_apex_false_jan_20_guards_month_day_transposition(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_apex
        import pytz
        assert is_rich_apex(datetime(2026, 1, 20, 10, 0, 0, tzinfo=pytz.UTC)) is False

    # ── build_rich_prompt — apex parameter ───────────────────────────────────

    def test_build_rich_prompt_apex_true_contains_apex_language(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="Spain")
        lower = p.lower()
        assert "richest" in lower or "pinnacle" in lower or "apex" in lower or "universe" in lower

    def test_build_rich_prompt_apex_true_with_country_contains_country(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="Spain")
        assert "Spain" in p

    def test_build_rich_prompt_apex_empty_country_no_dangling_braces(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="")
        assert "{country}" not in p
        assert "{}" not in p
        # Should fall back to generic champion-nation wording
        lower = p.lower()
        assert "champion" in lower or "nation" in lower or "pinnacle" in lower

    def test_build_rich_prompt_apex_false_no_apex_clause(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=False)
        lower = p.lower()
        assert "apex mode" not in lower
        assert "pinnacle" not in lower

    def test_build_rich_prompt_apex_augments_base_not_replaces(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_EDIT_PROMPT
        p = build_rich_prompt(apex=True, apex_country="France")
        assert p.startswith(RICH_EDIT_PROMPT)
        assert "same face" in p.lower()

    def test_build_rich_prompt_apex_clause_before_anchor(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_FACE_ANCHOR_CLAUSE, RICH_APEX_CLAUSE
        p = build_rich_prompt(anchor=True, apex=True, apex_country="Brazil")
        # Apex content appears before the anchor clause
        apex_snippet = "APEX MODE"
        apex_pos = p.find(apex_snippet)
        anchor_pos = p.find(RICH_FACE_ANCHOR_CLAUSE)
        assert apex_pos != -1 and anchor_pos != -1
        assert apex_pos < anchor_pos

    def test_build_rich_prompt_apex_with_argentina(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="Argentina")
        assert "Argentina" in p

    def test_build_rich_prompt_apex_loser_adds_trample_sentence(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="Spain", apex_loser="France")
        assert "France" in p
        lower = p.lower()
        assert "beneath" in lower or "feet" in lower or "defeated" in lower or "trophy" in lower

    def test_build_rich_prompt_apex_empty_loser_no_trample_sentence(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_APEX_TRAMPLE_SENTENCE
        p = build_rich_prompt(apex=True, apex_country="Spain", apex_loser="")
        assert "{loser}" not in p
        # Trample snippet must be absent — key words from the sentence
        lower = p.lower()
        assert "trophy" not in lower or "beneath his feet" not in p

    def test_build_rich_prompt_apex_loser_no_dangling_braces(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="Spain", apex_loser="Argentina")
        assert "{loser}" not in p
        assert "{}" not in p

    def test_build_rich_prompt_apex_loser_and_country_both_in_prompt(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(apex=True, apex_country="France", apex_loser="Germany")
        assert "France" in p
        assert "Germany" in p

    # ── generate_rich_caption — apex parameter ────────────────────────────────

    async def test_generate_rich_caption_apex_injects_apex_instruction_with_country(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("¡Soy el dueño del universo!")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=5,
            apex=True,
            apex_country="Spain",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        lower = all_text.lower()
        assert "cima" in lower or "rico" in lower or "universo" in lower or "poderoso" in lower
        assert "spain" in lower or "Spain" in all_text

    async def test_generate_rich_caption_apex_empty_country_no_country_sentence(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("¡El dueño del universo!")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=5,
            apex=True,
            apex_country="",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        # No dangling country reference
        assert "ha ganado el Mundial" not in all_text or "apex_country" not in all_text

    async def test_generate_rich_caption_apex_uses_standard_system_prompt(self, tmp_path):
        """Apex mode still uses the cocky RICH_CAPTION_PROMPT as system message."""
        from worldcup_bot.ai.rich_image import RICH_CAPTION_PROMPT
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("caption")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=5,
            apex=True,
            apex_country="France",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        system_content = messages[0]["content"]
        assert system_content == RICH_CAPTION_PROMPT

    async def test_generate_rich_caption_apex_loser_in_user_instruction(self, tmp_path):
        """When apex=True and apex_loser is set, the loser name appears in the user instruction."""
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("caption")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=5,
            apex=True,
            apex_country="Spain",
            apex_loser="France",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "France" in combined or "france" in combined.lower()

    async def test_generate_rich_caption_apex_no_loser_no_loser_mention(self, tmp_path):
        """When apex_loser is empty, no loser mention in the user instruction."""
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("caption")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=5,
            apex=True,
            apex_country="Spain",
            apex_loser="",
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        assert "aplastado" not in combined.lower()
        assert "{loser}" not in combined

    # ── run_rich_iteration — July 20 end-to-end ───────────────────────────────

    async def test_run_rich_iteration_apex_promotes_to_rich_modified(self, tmp_path):
        """On July 20 (apex), output IS rich_modified.png — normal promotion path."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_APEX").decode())
        fake_cap = _fake_caption_client("¡El más rico del universo!")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Spain"],
        )

        assert os.path.basename(out_path) == "rich_modified.png"
        assert Path(out_path).read_bytes() == b"PNG_APEX"

    async def test_run_rich_iteration_apex_level_incremented(self, tmp_path):
        """On July 20, level is incremented and persisted (normal promotion)."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        save_level(str(state_dir), 3)

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("apex caption")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        _, level, _ = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Spain"],
        )

        assert level == 4
        assert load_level(str(state_dir)) == 4

    async def test_run_rich_iteration_apex_prompt_has_apex_and_country(self, tmp_path):
        """On July 20, image prompt contains apex language and the winning country."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("caption")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Spain"],
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        lower = img_prompt.lower()
        assert "richest" in lower or "pinnacle" in lower or "apex" in lower or "universe" in lower
        assert "Spain" in img_prompt or "spain" in lower

    async def test_run_rich_iteration_apex_empty_winners_no_crash_no_dangling_braces(self, tmp_path):
        """On July 20 with no winners, no crash and no '{country}' in the image prompt."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("fallback apex")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=[],
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        assert "{country}" not in img_prompt
        assert "{}" not in img_prompt
        assert Path(out_path).exists()

    async def test_run_rich_iteration_apex_no_themes_generated(self, tmp_path):
        """On July 20, generate_wealth_themes is NOT called (apex clause handles country)."""
        from datetime import datetime
        import pytz
        from unittest.mock import patch, AsyncMock

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        with patch(
            "worldcup_bot.ai.rich_image.generate_wealth_themes",
        ) as mock_themes:
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _data_dir=str(data_dir),
                _now=apex_day,
                winners=["Spain"],
            )
        mock_themes.assert_not_called()

    async def test_run_rich_iteration_apex_caption_uses_apex_instruction(self, tmp_path):
        """On July 20, the caption messages include the apex instruction with the country."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("apex caption")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Argentina"],
        )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        all_text = ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_text += " " + content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        all_text += " " + part["text"]
        lower = all_text.lower()
        assert "cima" in lower or "rico" in lower or "universo" in lower or "poderoso" in lower
        assert "argentina" in lower or "Argentina" in all_text

    async def test_run_rich_iteration_apex_losers_in_image_prompt(self, tmp_path):
        """On July 20 with losers=['France'], the image prompt contains trample language and 'France'."""
        import base64
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("apex caption")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Spain"],
            losers=["France"],
        )

        call_kwargs = fake_img.images.edit.call_args.kwargs
        prompt_used = call_kwargs.get("prompt", "")
        assert "France" in prompt_used
        lower = prompt_used.lower()
        assert "beneath" in lower or "feet" in lower or "defeated" in lower or "trophy" in lower

    async def test_run_rich_iteration_apex_no_losers_no_crash(self, tmp_path):
        """July 20 with losers=[] (or None) — no crash, no dangling {loser} in prompt."""
        import base64
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("apex caption")
        apex_day = datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)

        # empty losers list
        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Spain"],
            losers=[],
        )
        call_kwargs = fake_img.images.edit.call_args.kwargs
        prompt_used = call_kwargs.get("prompt", "")
        assert "{loser}" not in prompt_used
        assert "{}" not in prompt_used

        # None losers
        state_dir2 = tmp_path / "state2"
        state_dir2.mkdir()
        settings2 = _make_settings(tmp_path, state_dir=str(state_dir2))
        fake_img2 = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap2 = _fake_caption_client("apex caption")

        await run_rich_iteration(
            settings2,
            _client=fake_img2,
            _caption_client=fake_cap2,
            _data_dir=str(data_dir),
            _now=apex_day,
            winners=["Spain"],
            losers=None,
        )
        call_kwargs2 = fake_img2.images.edit.call_args.kwargs
        prompt_used2 = call_kwargs2.get("prompt", "")
        assert "{loser}" not in prompt_used2


# ══════════════════════════════════════════════════════════════════════════════
# Death mode (July 21 — two days after the World Cup Final)
# ══════════════════════════════════════════════════════════════════════════════


class TestRichDeathMode:
    """Tests for the Death special day (July 21 every year).

    Contract under test:
    - RICH_DEATH_MONTH=7, RICH_DEATH_DAY=21
    - is_rich_death(now) → True iff month==7 and day==21
    - build_rich_prompt(death=True) → death/farewell clause appended
    - build_rich_prompt(death=True) → death clause BEFORE anchor clause
    - generate_rich_caption(death=True) → uses RICH_DEATH_CAPTION_PROMPT as system
    - run_rich_iteration(_now=July 21) → writes rich_death.png, does NOT touch
      rich_modified.png / level / history / captions (separate-file path, mirrors Micky)
    """

    # ── is_rich_death ─────────────────────────────────────────────────────────

    def test_is_rich_death_true_on_july_21_2026(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_death
        import pytz
        assert is_rich_death(datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_rich_death_true_another_year_july_21(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_death
        import pytz
        assert is_rich_death(datetime(2030, 7, 21, 12, 0, 0, tzinfo=pytz.UTC)) is True

    def test_is_rich_death_false_july_20_apex_day(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_death
        import pytz
        assert is_rich_death(datetime(2026, 7, 20, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_death_false_july_22(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_death
        import pytz
        assert is_rich_death(datetime(2026, 7, 22, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_death_false_july_8_rich_birthday(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_death
        import pytz
        assert is_rich_death(datetime(2026, 7, 8, 10, 0, 0, tzinfo=pytz.UTC)) is False

    def test_is_rich_death_false_jan_21_guards_month_day_transposition(self):
        from datetime import datetime
        from worldcup_bot.ai.rich_image import is_rich_death
        import pytz
        assert is_rich_death(datetime(2026, 1, 21, 10, 0, 0, tzinfo=pytz.UTC)) is False

    # ── RICH_DEATH_CAPTION_PROMPT — content checks ────────────────────────────

    def test_rich_death_caption_prompt_exists(self):
        from worldcup_bot.ai.rich_image import RICH_DEATH_CAPTION_PROMPT
        assert isinstance(RICH_DEATH_CAPTION_PROMPT, str)
        assert len(RICH_DEATH_CAPTION_PROMPT) > 50

    def test_rich_death_caption_prompt_mentions_love_or_gratitude(self):
        from worldcup_bot.ai.rich_image import RICH_DEATH_CAPTION_PROMPT
        lower = RICH_DEATH_CAPTION_PROMPT.lower()
        assert "amor" in lower or "gratitud" in lower or "love" in lower or "gracias" in lower

    def test_rich_death_caption_prompt_forbids_slash_separator(self):
        from worldcup_bot.ai.rich_image import RICH_DEATH_CAPTION_PROMPT
        assert "/" in RICH_DEATH_CAPTION_PROMPT  # mentions "/" as forbidden
        lower = RICH_DEATH_CAPTION_PROMPT.lower()
        assert "nunca" in lower or "never" in lower

    def test_rich_death_caption_prompt_differs_from_rich_caption_prompt(self):
        from worldcup_bot.ai.rich_image import RICH_DEATH_CAPTION_PROMPT, RICH_CAPTION_PROMPT
        assert RICH_DEATH_CAPTION_PROMPT != RICH_CAPTION_PROMPT

    # ── build_rich_prompt — death parameter ──────────────────────────────────

    def test_build_rich_prompt_death_true_contains_farewell_language(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(death=True)
        lower = p.lower()
        assert (
            "farewell" in lower
            or "died" in lower
            or "passing" in lower
            or "peaceful" in lower
            or "state" in lower
        )

    def test_build_rich_prompt_death_true_is_non_gory(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(death=True)
        lower = p.lower()
        assert "non-gory" in lower or "non-violent" in lower or "no blood" in lower

    def test_build_rich_prompt_death_false_no_death_clause(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt
        p = build_rich_prompt(death=False)
        lower = p.lower()
        assert "farewell" not in lower
        assert "non-gory" not in lower
        assert "non-violent" not in lower

    def test_build_rich_prompt_death_augments_base_not_replaces(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_EDIT_PROMPT
        p = build_rich_prompt(death=True)
        assert p.startswith(RICH_EDIT_PROMPT)
        assert "same face" in p.lower()

    def test_build_rich_prompt_death_clause_before_anchor(self):
        from worldcup_bot.ai.rich_image import build_rich_prompt, RICH_FACE_ANCHOR_CLAUSE, RICH_DEATH_CLAUSE
        p = build_rich_prompt(anchor=True, death=True)
        death_snippet = "FAREWELL"
        death_pos = p.find(death_snippet)
        anchor_pos = p.find(RICH_FACE_ANCHOR_CLAUSE)
        assert death_pos != -1 and anchor_pos != -1
        assert death_pos < anchor_pos

    # ── generate_rich_caption — death parameter ───────────────────────────────

    async def test_generate_rich_caption_death_uses_death_system_prompt(self, tmp_path):
        """When death=True, the system message content is RICH_DEATH_CAPTION_PROMPT."""
        from worldcup_bot.ai.rich_image import RICH_DEATH_CAPTION_PROMPT
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("Adiós a todos... ❤️")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=10,
            death=True,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        system_content = messages[0]["content"]
        assert system_content == RICH_DEATH_CAPTION_PROMPT

    async def test_generate_rich_caption_death_uses_different_system_from_normal(self, tmp_path):
        """death=False uses RICH_CAPTION_PROMPT; death=True uses RICH_DEATH_CAPTION_PROMPT."""
        from worldcup_bot.ai.rich_image import RICH_CAPTION_PROMPT, RICH_DEATH_CAPTION_PROMPT
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")

        fake_normal = _fake_caption_client("normal caption")
        await generate_rich_caption(
            api_key="k", base_url="http://x", model="gpt-4",
            old_image_path=str(old_img), new_image_path=str(new_img), level=1,
            death=False, _client=fake_normal,
        )
        normal_system = fake_normal.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert normal_system == RICH_CAPTION_PROMPT

        fake_death = _fake_caption_client("farewell caption")
        await generate_rich_caption(
            api_key="k", base_url="http://x", model="gpt-4",
            old_image_path=str(old_img), new_image_path=str(new_img), level=1,
            death=True, _client=fake_death,
        )
        death_system = fake_death.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert death_system == RICH_DEATH_CAPTION_PROMPT
        assert death_system != normal_system

    async def test_generate_rich_caption_death_injects_farewell_instruction(self, tmp_path):
        old_img = tmp_path / "before.jpg"
        new_img = tmp_path / "after.png"
        old_img.write_bytes(b"DATA")
        new_img.write_bytes(b"DATA")
        fake = _fake_caption_client("Adiós... ❤️")
        await generate_rich_caption(
            api_key="k",
            base_url="http://x",
            model="gpt-4",
            old_image_path=str(old_img),
            new_image_path=str(new_img),
            level=10,
            death=True,
            _client=fake,
        )
        messages = fake.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = "\n".join(text_parts)
        lower = combined.lower()
        assert "despedida" in lower or "farewell" in lower or "último" in lower or "amor" in lower

    # ── run_rich_iteration — July 21 end-to-end ───────────────────────────────

    async def test_run_rich_iteration_death_writes_rich_death_png(self, tmp_path):
        """On July 21, output path is rich_death.png (separate file)."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_DEATH").decode())
        fake_cap = _fake_caption_client("Adiós...")
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        out_path, level, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        assert os.path.basename(out_path) == "rich_death.png"
        assert Path(out_path).read_bytes() == b"PNG_DEATH"

    async def test_run_rich_iteration_death_does_not_touch_rich_modified(self, tmp_path):
        """On July 21, rich_modified.png is NOT overwritten (chain stays clean)."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        evolved_bytes = b"PNG_EVOLVED_UNTOUCHED"
        (state_dir / "rich_modified.png").write_bytes(evolved_bytes)

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG_DEATH_NEW").decode())
        fake_cap = _fake_caption_client("Adiós...")
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        assert (state_dir / "rich_modified.png").read_bytes() == evolved_bytes

    async def test_run_rich_iteration_death_level_not_bumped(self, tmp_path):
        """On July 21, level counter is NOT incremented (no save_level call)."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")
        save_level(str(state_dir), 7)

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("Adiós...")
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        assert load_level(str(state_dir)) == 7

    async def test_run_rich_iteration_death_history_not_appended(self, tmp_path):
        """On July 21, rich_history.txt and rich_captions.txt are NOT appended."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        payload = json.dumps({"caption": "Adiós grupo", "memo": "some death memo"}, ensure_ascii=False)
        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client(payload)
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        assert load_history_lines(str(state_dir)) == []
        assert load_captions(str(state_dir)) == []

    async def test_run_rich_iteration_death_caption_uses_death_system_prompt(self, tmp_path):
        """On July 21, the caption API call uses RICH_DEATH_CAPTION_PROMPT as system message."""
        from datetime import datetime
        import pytz
        from worldcup_bot.ai.rich_image import RICH_DEATH_CAPTION_PROMPT

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("Adiós...")
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        messages = fake_cap.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["content"] == RICH_DEATH_CAPTION_PROMPT

    async def test_run_rich_iteration_death_prompt_has_farewell_language(self, tmp_path):
        """On July 21, the image-edit prompt contains the death/farewell clause."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        fake_cap = _fake_caption_client("Adiós...")
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        await run_rich_iteration(
            settings,
            _client=fake_img,
            _caption_client=fake_cap,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        img_prompt = fake_img.images.edit.call_args.kwargs["prompt"]
        lower = img_prompt.lower()
        assert (
            "farewell" in lower
            or "died" in lower
            or "passing" in lower
            or "peaceful" in lower
        )
        assert "non-gory" in lower or "non-violent" in lower or "no blood" in lower

    async def test_run_rich_iteration_death_fallback_caption_when_no_chat(self, tmp_path):
        """On July 21 with no chat model, fallback caption is the death farewell."""
        from datetime import datetime
        import pytz

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")
        (state_dir / "rich_modified.png").write_bytes(b"PNG_EVOLVED")

        settings = _make_settings(
            tmp_path,
            state_dir=str(state_dir),
            openai_api_key="",
            openai_base_url="",
            openai_model="",
        )
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        _, _, caption = await run_rich_iteration(
            settings,
            _client=fake_img,
            _data_dir=str(data_dir),
            _now=death_day,
        )

        lower = caption.lower()
        assert "marcho" in lower or "quiero" in lower or "gracias" in lower or "❤️" in caption or "🕊️" in caption

    async def test_run_rich_iteration_death_no_themes_generated(self, tmp_path):
        """On July 21, generate_wealth_themes is NOT called."""
        from datetime import datetime
        import pytz
        from unittest.mock import patch

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "rich").mkdir(parents=True)
        (data_dir / "rich" / "rich_original.jpg").write_bytes(b"JPEG_ORIG")

        settings = _make_settings(tmp_path, state_dir=str(state_dir))
        fake_img = _fake_client(base64.b64encode(b"PNG").decode())
        death_day = datetime(2026, 7, 21, 10, 0, 0, tzinfo=pytz.UTC)

        with patch("worldcup_bot.ai.rich_image.generate_wealth_themes") as mock_themes:
            await run_rich_iteration(
                settings,
                _client=fake_img,
                _data_dir=str(data_dir),
                _now=death_day,
                winners=["Spain"],
            )
        mock_themes.assert_not_called()

