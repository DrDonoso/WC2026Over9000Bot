"""Tests for the AI integration: config, AIClient, build_ai_user_message,
parse_ai_json, render_message, generate_daily_update, cmd_update_diario, and
daily_update_job.

All external dependencies (OpenAI SDK, football API, snapshot, pred_loader) are
mocked — no network, no filesystem.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worldcup_bot.ai.client import AIClient, AIError
from worldcup_bot.ai.daily_update import (
    _SYSTEM,
    build_ai_user_message,
    generate_daily_update,
    parse_ai_json,
    render_message,
)
from worldcup_bot.ai.snapshot import Movement
from worldcup_bot.api.models import Match
from worldcup_bot.bot.handlers import cmd_update_diario
from worldcup_bot.config import Settings, ai_enabled, load_settings
from worldcup_bot.porra.engine import UserRankEntry


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_match(
    home_name: str = "Spain",
    away_name: str = "France",
    home_score: int | None = 1,
    away_score: int | None = 0,
    status: str = "FINISHED",
    utc_date: str = "2026-06-15T18:00:00Z",
    home_tla: str = "ESP",
    away_tla: str = "FRA",
    winner: str | None = None,
) -> Match:
    return Match(
        id=1,
        utc_date=utc_date,
        status=status,
        stage="GROUP_STAGE",
        group="GROUP_A",
        home_tla=home_tla,
        away_tla=away_tla,
        home_name=home_name,
        away_name=away_name,
        home_score=home_score,
        away_score=away_score,
        winner=winner,
    )


def _make_rank_entry(username: str = "user1", display_name: str = "Player One", total_score: float = 5.0) -> UserRankEntry:
    return UserRankEntry(
        username=username,
        display_name=display_name,
        total_score=total_score,
        base_score=0.0,
        group_score=total_score,
        knockout_scores={},
        exact_group_hits=0,
    )


def _make_update(username: str | None = "testuser") -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 12345
    update.effective_user.username = username
    return update


def _make_context(settings: Settings) -> MagicMock:
    context = MagicMock()
    context.bot_data = {"settings": settings}
    context.args = []
    context.bot.send_message = AsyncMock()
    return context


# ── config: new AI fields ─────────────────────────────────────────────────────


class TestAISettingsDefaults:
    def test_openai_fields_default_to_empty(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.openai_api_key == ""
        assert s.openai_base_url == ""
        assert s.openai_model == ""

    def test_daily_update_hour_default_is_9(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.daily_update_hour == 9

    def test_daily_update_hour_can_be_overridden(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k", daily_update_hour=8)
        assert s.daily_update_hour == 8

    def test_state_dir_default_is_app_state(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.state_dir == "/app/state"

    def test_state_dir_can_be_overridden(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k", state_dir="/data/state")
        assert s.state_dir == "/data/state"


class TestAIEnabled:
    def test_true_when_all_three_set(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        assert ai_enabled(s) is True

    def test_false_when_key_missing(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        assert ai_enabled(s) is False

    def test_false_when_base_url_missing(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="",
            openai_model="gpt-4",
        )
        assert ai_enabled(s) is False

    def test_false_when_model_missing(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="",
        )
        assert ai_enabled(s) is False

    def test_false_when_all_missing(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert ai_enabled(s) is False


class TestLoadSettingsAI:
    def test_openai_api_key_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        s = load_settings()
        assert s.openai_api_key == "sk-test"

    def test_openai_base_url_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://litellm.example/v1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        s = load_settings()
        assert s.openai_base_url == "https://litellm.example/v1"

    def test_openai_model_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4-turbo")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        s = load_settings()
        assert s.openai_model == "gpt-4-turbo"

    def test_daily_update_hour_default_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("DAILY_UPDATE_HOUR", raising=False)
        s = load_settings()
        assert s.daily_update_hour == 9

    def test_daily_update_hour_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("DAILY_UPDATE_HOUR", "10")
        s = load_settings()
        assert s.daily_update_hour == 10

    def test_missing_openai_vars_do_not_raise(self, monkeypatch):
        """Missing OPENAI_* must NOT raise RuntimeError (feature is optional)."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        s = load_settings()  # must not raise
        assert s.openai_api_key == ""
        assert s.openai_base_url == ""
        assert s.openai_model == ""

    def test_state_dir_default_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("STATE_DIR", raising=False)
        s = load_settings()
        assert s.state_dir == "/app/state"

    def test_state_dir_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("STATE_DIR", "/data/mystate")
        s = load_settings()
        assert s.state_dir == "/data/mystate"


# ── AIClient ──────────────────────────────────────────────────────────────────


def _mock_openai(content: str) -> MagicMock:
    """Build a minimal mock AsyncOpenAI client that returns *content*."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content

    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)
    return mock_openai


class TestAIClientComplete:
    async def test_returns_stripped_content(self):
        client = AIClient("key", "http://base", "model", _client=_mock_openai("  hola  "))
        result = await client.complete("system", "user")
        assert result == "hola"

    async def test_passes_model_and_messages(self):
        mock_openai = _mock_openai("texto")
        client = AIClient("key", "http://base", "gpt-4", _client=mock_openai)
        await client.complete("sys", "usr")

        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4"
        assert call_kwargs["messages"][0] == {"role": "system", "content": "sys"}
        assert call_kwargs["messages"][1] == {"role": "user", "content": "usr"}

    async def test_passes_temperature_and_max_completion_tokens(self):
        mock_openai = _mock_openai("ok")
        client = AIClient("key", "http://base", "model", _client=mock_openai)
        await client.complete("sys", "usr", temperature=0.5, max_completion_tokens=100)

        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_completion_tokens"] == 100
        assert "max_tokens" not in call_kwargs

    async def test_raises_ai_error_on_sdk_exception(self):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))
        client = AIClient("key", "http://base", "model", _client=mock_openai)

        with pytest.raises(AIError):
            await client.complete("sys", "usr")


# ── build_ai_user_message ─────────────────────────────────────────────────────


class TestBuildAiUserMessage:
    def test_results_block_contains_finished_match(self):
        yesterday = [_make_match("Spain", "France", 1, 0, "FINISHED")]
        msg = build_ai_user_message(yesterday, [], [], [], "Europe/Madrid")
        assert "Spain 1-0 France" in msg

    def test_today_block_contains_fixture_with_key_and_kickoff(self):
        today = [_make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")]
        msg = build_ai_user_message([], today, [], [], "Europe/Madrid")
        assert "[GER-BRA]" in msg
        assert "Germany vs Brazil" in msg
        assert "20:00" in msg  # UTC+2

    def test_empty_yesterday_uses_fallback(self):
        msg = build_ai_user_message([], [], [], [], "Europe/Madrid")
        assert "Sin partidos ayer." in msg

    def test_empty_today_uses_fallback(self):
        msg = build_ai_user_message([], [], [], [], "Europe/Madrid")
        assert "Sin partidos hoy." in msg

    def test_ranking_included(self):
        ranking = [
            _make_rank_entry("u1", "Alice", 10.0),
            _make_rank_entry("u2", "Bob", 7.0),
        ]
        msg = build_ai_user_message([], [], ranking, [], "Europe/Madrid")
        assert "1. Alice" in msg
        assert "2. Bob" in msg
        assert "CLASIFICACIÓN ACTUAL:" in msg

    def test_movements_climbed_and_dropped(self):
        movements = [
            Movement("u1", "Alice", old_pos=3, new_pos=1, delta=2),
            Movement("u2", "Bob", old_pos=1, new_pos=3, delta=-2),
        ]
        msg = build_ai_user_message([], [], [], movements, "Europe/Madrid")
        assert "Alice" in msg
        assert "subió 2" in msg
        assert "Bob" in msg
        assert "bajó 2" in msg

    def test_first_snapshot_flag_shows_no_prior_data(self):
        msg = build_ai_user_message([], [], [], [], "Europe/Madrid", first_snapshot=True)
        assert "Primera instantánea" in msg

    def test_no_movements_no_first_snapshot_says_sin_cambios(self):
        msg = build_ai_user_message([], [], [], [], "Europe/Madrid", first_snapshot=False)
        assert "Sin cambios de posición" in msg

    def test_message_has_four_sections(self):
        msg = build_ai_user_message([], [], [], [], "Europe/Madrid")
        assert "ESCENARIO:" in msg
        assert "RESULTADOS DE AYER:" in msg
        assert "PARTIDOS DE HOY:" in msg
        assert "CLASIFICACIÓN ACTUAL:" in msg
        assert "CAMBIOS DESDE AYER:" in msg


# ── parse_ai_json ─────────────────────────────────────────────────────────────


class TestParseAiJson:
    def test_clean_json_parsed(self):
        raw = '{"today_notes": {"ESP-FRA": "rivalidad histórica"}, "standings_comment": "¡Emocionante!"}'
        notes, comment = parse_ai_json(raw)
        assert notes == {"ESP-FRA": "rivalidad histórica"}
        assert comment == "¡Emocionante!"

    def test_fenced_json_parsed(self):
        raw = '```json\n{"today_notes": {}, "standings_comment": "Ok"}\n```'
        notes, comment = parse_ai_json(raw)
        assert notes == {}
        assert comment == "Ok"

    def test_fenced_no_lang_tag(self):
        raw = '```\n{"today_notes": {}, "standings_comment": "test"}\n```'
        notes, comment = parse_ai_json(raw)
        assert comment == "test"

    def test_garbage_returns_fallback(self):
        notes, comment = parse_ai_json("Este no es JSON")
        assert notes == {}
        assert comment == ""

    def test_missing_today_notes_defaults_empty_dict(self):
        raw = '{"standings_comment": "texto"}'
        notes, comment = parse_ai_json(raw)
        assert notes == {}
        assert comment == "texto"

    def test_missing_standings_comment_defaults_empty_string(self):
        raw = '{"today_notes": {"A-B": ""}}'
        notes, comment = parse_ai_json(raw)
        assert comment == ""

    def test_today_notes_not_dict_defaults_empty(self):
        raw = '{"today_notes": "not_a_dict", "standings_comment": "ok"}'
        notes, _ = parse_ai_json(raw)
        assert notes == {}


# ── render_message ────────────────────────────────────────────────────────────


class TestRenderMessage:
    def test_winner_home_bolds_home_name(self):
        m = _make_match("Spain", "France", 2, 1, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "")
        assert "<b>Spain</b>" in result
        # away name NOT in bold
        assert "<b>France</b>" not in result

    def test_winner_away_bolds_away_name(self):
        m = _make_match("Spain", "France", 0, 1, "FINISHED", winner="AWAY_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "")
        assert "<b>France</b>" in result
        assert "<b>Spain</b>" not in result

    def test_draw_no_bold(self):
        m = _make_match("Spain", "France", 1, 1, "FINISHED", winner="DRAW")
        result = render_message([m], [], "Europe/Madrid", {}, "")
        assert "<b>Spain</b>" not in result
        assert "<b>France</b>" not in result

    def test_winner_none_no_bold(self):
        m = _make_match("Spain", "France", 1, 0, "FINISHED", winner=None)
        result = render_message([m], [], "Europe/Madrid", {}, "")
        assert "<b>Spain</b>" not in result
        assert "<b>France</b>" not in result

    def test_today_both_teams_bold(self):
        m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([], [m], "Europe/Madrid", {}, "")
        assert "<b>Germany</b>" in result
        assert "<b>Brazil</b>" in result

    def test_flags_present_for_known_tlas(self):
        m = _make_match("Spain", "France", home_tla="ESP", away_tla="FRA")
        result = render_message([m], [], "Europe/Madrid", {}, "")
        # Flags are emoji characters — just check the section is non-empty
        assert "Resultados de ayer" in result
        assert "Spain" in result
        assert "France" in result

    def test_note_line_rendered_when_present(self):
        m = _make_match("Morocco", "Algeria", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="MAR", away_tla="ALG")
        result = render_message([], [m], "Europe/Madrid", {"MAR-ALG": "frontera cerrada"}, "")
        assert "<i>frontera cerrada</i>" in result

    def test_note_line_not_rendered_when_absent(self):
        m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([], [m], "Europe/Madrid", {}, "")
        assert "<i>" not in result

    def test_note_line_not_rendered_when_empty_string(self):
        m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([], [m], "Europe/Madrid", {"GER-BRA": ""}, "")
        assert "<i>" not in result

    def test_sin_partidos_ayer_when_no_yesterday(self):
        m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([], [m], "Europe/Madrid", {}, "")
        assert "📅 <b>Resultados de ayer</b>" not in result

    def test_sin_partidos_hoy_when_no_today(self):
        m = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "", scenario="pausa")
        assert "⏸️ <b>Hoy no hay partidos</b>" in result

    def test_standings_comment_rendered(self):
        result = render_message([], [], "Europe/Madrid", {}, "¡Gran jornada!")
        assert "¡Gran jornada!" in result

    def test_html_section_headers_present(self):
        m_y = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        m_t = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([m_y], [m_t], "Europe/Madrid", {}, "")
        assert "📅 <b>Resultados de ayer</b>" in result
        assert "⚽ <b>Partidos de hoy</b>" in result
        assert "📊 <b>La porra</b>" in result

    def test_html_escaping_team_name(self):
        m = _make_match("A & B", "C < D", 1, 0, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "")
        assert "<b>A &amp; B</b>" in result
        assert "C &lt; D" in result

    def test_html_escaping_note(self):
        m = _make_match("X", "Y", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="XXX", away_tla="YYY")
        result = render_message([], [m], "Europe/Madrid", {"XXX-YYY": "nota <especial> & más"}, "")
        assert "nota &lt;especial&gt; &amp; más" in result

    def test_html_escaping_standings_comment(self):
        result = render_message([], [], "Europe/Madrid", {}, "líder <Alice> & amigos")
        assert "líder &lt;Alice&gt; &amp; amigos" in result

    def test_participant_names_bolded_in_standings_comment(self):
        """Known participant names in standings_comment get wrapped in <b>.</b>."""
        result = render_message(
            [], [], "Europe/Madrid", {},
            "Alice sube al 1er puesto y Bob baja.",
            participant_names=["Alice", "Bob"],
        )
        assert "<b>Alice</b>" in result
        assert "<b>Bob</b>" in result

    def test_unknown_names_not_bolded_in_standings_comment(self):
        """Words that are NOT in participant_names are NOT bolded."""
        result = render_message(
            [], [], "Europe/Madrid", {},
            "Great game today.",
            participant_names=["Alice"],
        )
        assert "<b>Great</b>" not in result
        assert "<b>game</b>" not in result

    def test_three_sections_separated_by_blank_lines(self):
        m_y = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        m_t = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([m_y], [m_t], "Europe/Madrid", {}, "comment")
        parts = result.split("\n\n")
        assert len(parts) == 3


# ── generate_daily_update ─────────────────────────────────────────────────────


def _make_generate_patches(ai_json_response: str = '{"today_notes": {}, "standings_comment": "Ok"}'):
    """Return a context-manager stack of patches needed for generate_daily_update tests."""
    import contextlib

    @contextlib.contextmanager
    def _patches():
        with patch("worldcup_bot.ai.daily_update.pred_loader.load", return_value={"participants": {}}):
            with patch("worldcup_bot.ai.daily_update.engine.compute_general_ranking", return_value=[]):
                with patch("worldcup_bot.ai.daily_update._snapshot.update_and_diff", return_value=(None, {})):
                    with patch("worldcup_bot.ai.daily_update._snapshot.compute_movements", return_value=[]):
                        yield

    return _patches()


class TestGenerateDailyUpdate:
    async def test_returns_html_string(self):
        today_m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[], [today_m]]  # reanudacion scenario

        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": "buena jornada"}')

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)

        assert result is not None
        assert "<b>Partidos de hoy</b>" in result

    async def test_standings_comment_in_output(self):
        today_m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[], [today_m]]

        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": "¡Arriba!"}')

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)

        assert result is not None
        assert "¡Arriba!" in result

    async def test_filters_yesterday_to_finished(self):
        """Only FINISHED matches appear as results; SCHEDULED must not."""
        finished = _make_match("Spain", "France", 1, 0, "FINISHED")
        not_finished = _make_match("Brazil", "Germany", status="SCHEDULED")

        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [
            [finished, not_finished],  # yesterday
            [],                        # today
        ]

        mock_ai = MagicMock()
        captured_user: list[str] = []

        async def capture(system: str, user: str, **_kw: object) -> str:
            captured_user.append(user)
            return '{"today_notes": {}, "standings_comment": ""}'

        mock_ai.complete = capture

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            await generate_daily_update(mock_client, mock_ai, settings)

        assert "Spain" in captured_user[0]
        assert "Brazil" not in captured_user[0]

    async def test_calls_get_football_day_matches_for_both_days(self):
        mock_client = MagicMock()
        mock_client.get_football_day_matches.return_value = []

        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": ""}')

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            await generate_daily_update(mock_client, mock_ai, settings)

        calls = mock_client.get_football_day_matches.call_args_list
        assert len(calls) == 2
        offsets = [c.kwargs["day_offset"] for c in calls]
        assert -1 in offsets
        assert 0 in offsets

    async def test_ai_failure_degrades_gracefully(self):
        """AI error must not propagate — message still renders."""
        today_m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[], [today_m]]

        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(side_effect=Exception("AI timeout"))

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)

        assert result is not None
        assert "<b>Partidos de hoy</b>" in result  # message still rendered

    async def test_today_notes_used_in_render(self):
        """Note from AI JSON shows up in the rendered HTML."""
        m = _make_match("Morocco", "Algeria", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="MAR", away_tla="ALG")

        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[], [m]]

        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(
            return_value='{"today_notes": {"MAR-ALG": "rivalidad norteafricana"}, "standings_comment": ""}'
        )

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)

        assert "rivalidad norteafricana" in result

    async def test_complete_called_with_max_completion_tokens_1500(self):
        """ai.complete() must be called with max_completion_tokens=1500 (not max_tokens)."""
        today_m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[], [today_m]]

        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": "ok"}')

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            await generate_daily_update(mock_client, mock_ai, settings)

        mock_ai.complete.assert_called_once()
        _, call_kwargs = mock_ai.complete.call_args
        assert call_kwargs.get("max_completion_tokens") == 1500
        assert "max_tokens" not in call_kwargs


# ── cmd_update_diario ─────────────────────────────────────────────────────────


class TestCmdUpdateDiario:
    async def test_replies_not_configured_when_ai_disabled(self):
        update = _make_update()
        settings = Settings(telegram_bot_token="t", football_data_api_key="k")
        context = _make_context(settings)

        await cmd_update_diario(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "OPENAI_*" in text

    async def test_no_ai_call_when_disabled(self):
        update = _make_update()
        settings = Settings(telegram_bot_token="t", football_data_api_key="k")
        context = _make_context(settings)

        with patch("worldcup_bot.bot.handlers.generate_daily_update") as mock_gen:
            await cmd_update_diario(update, context)
            mock_gen.assert_not_called()

    async def test_sends_to_current_chat_with_html_parse_mode(self):
        update = _make_update()
        update.effective_chat.id = 99999
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = _make_context(settings)

        with patch(
            "worldcup_bot.bot.handlers.generate_daily_update",
            new=AsyncMock(return_value="¡Hola grupo!"),
        ):
            with patch("worldcup_bot.bot.handlers.make_client"):
                await cmd_update_diario(update, context)

        context.bot.send_message.assert_called_once_with(
            chat_id=99999,
            text="¡Hola grupo!",
            parse_mode="HTML",
        )

    async def test_replies_waiting_message_first(self):
        update = _make_update()
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = _make_context(settings)

        with patch(
            "worldcup_bot.bot.handlers.generate_daily_update",
            new=AsyncMock(return_value="text"),
        ):
            with patch("worldcup_bot.bot.handlers.make_client"):
                await cmd_update_diario(update, context)

        first_reply = update.message.reply_text.call_args_list[0][0][0]
        assert "⏳" in first_reply

    async def test_replies_error_on_generate_failure(self):
        update = _make_update()
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = _make_context(settings)

        with patch(
            "worldcup_bot.bot.handlers.generate_daily_update",
            new=AsyncMock(side_effect=RuntimeError("AI error")),
        ):
            with patch("worldcup_bot.bot.handlers.make_client"):
                await cmd_update_diario(update, context)  # must not crash

        calls = update.message.reply_text.call_args_list
        assert len(calls) >= 2
        last_text = calls[-1][0][0]
        assert "❌" in last_text


# ── daily_update_job ──────────────────────────────────────────────────────────


class TestDailyUpdateJob:
    async def test_sends_message_to_group_with_html_parse_mode(self):
        from worldcup_bot.__main__ import daily_update_job

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            telegram_group_id="-100group",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = MagicMock()
        context.bot_data = {"settings": settings}
        context.bot.send_message = AsyncMock()

        with patch(
            "worldcup_bot.__main__.generate_daily_update",
            new=AsyncMock(return_value="recap text"),
        ):
            with patch("worldcup_bot.__main__.make_client"):
                await daily_update_job(context)

        context.bot.send_message.assert_called_once_with(
            chat_id="-100group",
            text="recap text",
            parse_mode="HTML",
        )

    async def test_exception_swallowed_send_not_called(self):
        """When generate raises, daily_update_job must NOT propagate and must NOT send."""
        from worldcup_bot.__main__ import daily_update_job

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            telegram_group_id="-100group",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = MagicMock()
        context.bot_data = {"settings": settings}
        context.bot.send_message = AsyncMock()

        with patch(
            "worldcup_bot.__main__.generate_daily_update",
            new=AsyncMock(side_effect=RuntimeError("API down")),
        ):
            with patch("worldcup_bot.__main__.make_client"):
                await daily_update_job(context)  # must NOT raise

        context.bot.send_message.assert_not_called()

    async def test_does_not_send_when_result_is_none(self):
        """When generate returns None, daily_update_job must NOT call send_message."""
        from worldcup_bot.__main__ import daily_update_job

        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            telegram_group_id="-100group",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = MagicMock()
        context.bot_data = {"settings": settings}
        context.bot.send_message = AsyncMock()

        with patch(
            "worldcup_bot.__main__.generate_daily_update",
            new=AsyncMock(return_value=None),
        ):
            with patch("worldcup_bot.__main__.make_client"):
                await daily_update_job(context)

        context.bot.send_message.assert_not_called()


# ── format_spanish_date ───────────────────────────────────────────────────────


class TestFormatSpanishDate:
    def test_saturday_20_june(self):
        from worldcup_bot.ai.daily_update import format_spanish_date
        # 2026-06-20T18:00:00Z → UTC+2 → 2026-06-20 20:00 local; June 20 2026 = Saturday
        result = format_spanish_date("2026-06-20T18:00:00Z", "Europe/Madrid")
        assert result == "el sábado 20 de junio"

    def test_monday_15_june(self):
        from worldcup_bot.ai.daily_update import format_spanish_date
        # 2026-06-15T12:00:00Z → UTC+2 → 2026-06-15 14:00 local; June 15 2026 = Monday
        result = format_spanish_date("2026-06-15T12:00:00Z", "Europe/Madrid")
        assert result == "el lunes 15 de junio"

    def test_invalid_date_returns_none(self):
        from worldcup_bot.ai.daily_update import format_spanish_date
        result = format_spanish_date("not-a-date", "Europe/Madrid")
        assert result is None

    def test_invalid_timezone_returns_none(self):
        from worldcup_bot.ai.daily_update import format_spanish_date
        result = format_spanish_date("2026-06-20T18:00:00Z", "Not/ATimezone")
        assert result is None


# ── render_message: new scenario branches ────────────────────────────────────


class TestRenderMessageScenarios:
    def test_ayer_section_absent_when_yesterday_empty(self):
        m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([], [m], "Europe/Madrid", {}, "")
        assert "📅 <b>Resultados de ayer</b>" not in result

    def test_pausa_section_shown_when_today_empty(self):
        m = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "", scenario="pausa")
        assert "⏸️ <b>Hoy no hay partidos</b>" in result
        assert "clasificación de la porra se mantiene intacta" in result

    def test_pausa_section_includes_next_date_str(self):
        m = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "", scenario="pausa", next_date_str="el sábado 20 de junio")
        assert "el sábado 20 de junio" in result

    def test_pausa_section_graceful_without_date(self):
        m = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "", scenario="pausa", next_date_str=None)
        assert "⏸️ <b>Hoy no hay partidos</b>" in result
        assert "competición." in result

    def test_reanudacion_has_today_no_ayer(self):
        m = _make_match("Germany", "Brazil", status="SCHEDULED", utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA")
        result = render_message([], [m], "Europe/Madrid", {}, "", scenario="reanudacion")
        assert "📅 <b>Resultados de ayer</b>" not in result
        assert "⚽ <b>Partidos de hoy</b>" in result

    def test_porra_section_always_present(self):
        result = render_message([], [], "Europe/Madrid", {}, "")
        assert "📊 <b>La porra</b>" in result

    def test_pausa_two_sections_ayer_and_porra(self):
        m = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        result = render_message([m], [], "Europe/Madrid", {}, "", scenario="pausa")
        parts = result.split("\n\n")
        assert len(parts) == 3  # ayer + pausa_note + porra


# ── generate_daily_update: new scenario tests ────────────────────────────────


class TestGenerateDailyUpdateScenarios:
    async def test_returns_none_when_both_days_empty(self):
        mock_client = MagicMock()
        mock_client.get_football_day_matches.return_value = []
        mock_ai = MagicMock()
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)
        assert result is None

    async def test_pausa_scenario_calls_get_next_match(self):
        finished = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        next_m = _make_match(
            "Germany", "Brazil", status="SCHEDULED",
            utc_date="2026-06-20T18:00:00Z", home_tla="GER", away_tla="BRA",
        )
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[finished], []]
        mock_client.get_next_match.return_value = next_m
        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": ""}')
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)
        assert result is not None
        assert "⏸️" in result
        mock_client.get_next_match.assert_called_once()

    async def test_pausa_scenario_contains_next_date(self):
        finished = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        next_m = _make_match(
            "Germany", "Brazil", status="SCHEDULED",
            utc_date="2026-06-20T18:00:00Z", home_tla="GER", away_tla="BRA",
        )
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[finished], []]
        mock_client.get_next_match.return_value = next_m
        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": ""}')
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)
        assert result is not None
        assert "20 de junio" in result

    async def test_reanudacion_scenario_no_ayer_section(self):
        today_m = _make_match(
            "Germany", "Brazil", status="SCHEDULED",
            utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA",
        )
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[], [today_m]]
        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": ""}')
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)
        assert result is not None
        assert "📅 <b>Resultados de ayer</b>" not in result
        assert "⚽ <b>Partidos de hoy</b>" in result

    async def test_normal_scenario_has_all_sections(self):
        yesterday_m = _make_match("Spain", "France", 1, 0, "FINISHED", winner="HOME_TEAM")
        today_m = _make_match(
            "Germany", "Brazil", status="SCHEDULED",
            utc_date="2026-06-15T18:00:00Z", home_tla="GER", away_tla="BRA",
        )
        mock_client = MagicMock()
        mock_client.get_football_day_matches.side_effect = [[yesterday_m], [today_m]]
        mock_ai = MagicMock()
        mock_ai.complete = AsyncMock(return_value='{"today_notes": {}, "standings_comment": "top"}')
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            timezone="Europe/Madrid",
            football_day_start_hour=9,
        )
        with _make_generate_patches():
            result = await generate_daily_update(mock_client, mock_ai, settings)
        assert result is not None
        assert "📅 <b>Resultados de ayer</b>" in result
        assert "⚽ <b>Partidos de hoy</b>" in result
        assert "📊 <b>La porra</b>" in result


# ── cmd_update_diario: None-result reply ─────────────────────────────────────


class TestCmdUpdateDiarioNoneResult:
    async def test_replies_no_matches_when_result_is_none(self):
        update = _make_update()
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = _make_context(settings)

        with patch(
            "worldcup_bot.bot.handlers.generate_daily_update",
            new=AsyncMock(return_value=None),
        ):
            with patch("worldcup_bot.bot.handlers.make_client"):
                await cmd_update_diario(update, context)

        texts = [c[0][0] for c in update.message.reply_text.call_args_list]
        assert any("🤷" in t for t in texts)

    async def test_does_not_send_to_group_when_result_is_none(self):
        update = _make_update()
        settings = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-x",
            openai_base_url="http://litellm/v1",
            openai_model="gpt-4",
        )
        context = _make_context(settings)

        with patch(
            "worldcup_bot.bot.handlers.generate_daily_update",
            new=AsyncMock(return_value=None),
        ):
            with patch("worldcup_bot.bot.handlers.make_client"):
                await cmd_update_diario(update, context)

        context.bot.send_message.assert_not_called()


# ── _SYSTEM prompt contract ───────────────────────────────────────────────────


class TestSystemPromptContract:
    def test_system_prompt_references_armed_conflict_priority(self):
        """_SYSTEM must explicitly prioritise naming armed conflicts."""
        prompt_lower = _SYSTEM.lower()
        assert "conflicto armado" in prompt_lower

    def test_system_prompt_names_malvinas_as_example(self):
        """_SYSTEM must cite the Malvinas/Falklands war as a concrete example."""
        assert "Malvinas" in _SYSTEM or "malvinas" in _SYSTEM.lower()

    def test_system_prompt_empty_string_rule_stated(self):
        """_SYSTEM must instruct the model to return an empty string when nothing genuine."""
        assert '""' in _SYSTEM or "cadena vacía" in _SYSTEM.lower() or "CADENA VACÍA" in _SYSTEM

    def test_system_prompt_today_notes_rule_stated_unconditionally(self):
        """today_notes rule must appear before scenario-specific standing_comment guidance."""
        idx_today_notes = _SYSTEM.find("today_notes")
        idx_standings = _SYSTEM.find("standings_comment")
        assert idx_today_notes != -1
        assert idx_standings != -1
        assert idx_today_notes < idx_standings

    def test_system_prompt_forbids_filler(self):
        """_SYSTEM must explicitly forbid generic filler notes."""
        assert "relleno" in _SYSTEM.lower() or "nunca inventes" in _SYSTEM.lower() or "NUNCA" in _SYSTEM

    def test_system_prompt_mentions_panama_love(self):
        """_SYSTEM must instruct the AI to show warmth for Panamá."""
        assert "Panamá" in _SYSTEM or "Panama" in _SYSTEM.lower()

    def test_system_prompt_mentions_uzbekistan_love(self):
        """_SYSTEM must instruct the AI to show warmth for Uzbekistán."""
        assert "Uzbekistán" in _SYSTEM or "Uzbekistan" in _SYSTEM.lower()

    def test_system_prompt_both_beloved_teams_mentioned(self):
        """_SYSTEM must reference both Panama and Uzbekistan in the same love instruction."""
        assert ("Panamá" in _SYSTEM or "Panama" in _SYSTEM.lower()) and (
            "Uzbekistán" in _SYSTEM or "Uzbekistan" in _SYSTEM.lower()
        )

    def test_system_prompt_mentions_curacao_love(self):
        """_SYSTEM must instruct the AI to show warmth for Curaçao."""
        assert "Curaçao" in _SYSTEM or "Curacao" in _SYSTEM.lower()

    def test_system_prompt_all_three_beloved_teams_mentioned(self):
        """_SYSTEM must reference all three beloved teams: Panama, Uzbekistan, and Curaçao."""
        has_pan = "Panamá" in _SYSTEM or "Panama" in _SYSTEM.lower()
        has_uzb = "Uzbekistán" in _SYSTEM or "Uzbekistan" in _SYSTEM.lower()
        has_cuw = "Curaçao" in _SYSTEM or "Curacao" in _SYSTEM.lower()
        assert has_pan and has_uzb and has_cuw

