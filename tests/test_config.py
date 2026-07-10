"""Tests for Settings dataclass and load_settings()."""

from __future__ import annotations

import pytest

from worldcup_bot.config import Settings, load_settings, picante_profiles_enabled


class TestSettings:
    def test_football_cache_ttl_default_is_60(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.football_cache_ttl == 60.0

    def test_football_cache_ttl_can_be_overridden(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k", football_cache_ttl=120.0)
        assert s.football_cache_ttl == 120.0

    def test_football_day_start_hour_default_is_9(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.football_day_start_hour == 9

    def test_football_day_start_hour_can_be_overridden(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k", football_day_start_hour=6)
        assert s.football_day_start_hour == 6

    def test_photo_base_url_default_is_victorsaez(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.photo_base_url == "http://victorsaez.cat"

    def test_photo_base_url_can_be_overridden(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k", photo_base_url="http://example.com")
        assert s.photo_base_url == "http://example.com"

    def test_beloved_teams_default_is_pan_uzb_cuw(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert set(s.beloved_teams) == {"PAN", "UZB", "CUW"}

    def test_beloved_teams_can_be_overridden(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k", beloved_teams=("ESP", "FRA"))
        assert set(s.beloved_teams) == {"ESP", "FRA"}


class TestLoadSettings:
    def test_football_cache_ttl_default_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("FOOTBALL_CACHE_TTL", raising=False)
        s = load_settings()
        assert s.football_cache_ttl == 60.0

    def test_football_cache_ttl_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("FOOTBALL_CACHE_TTL", "120")
        s = load_settings()
        assert s.football_cache_ttl == 120.0

    def test_football_day_start_hour_default_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("FOOTBALL_DAY_START_HOUR", raising=False)
        s = load_settings()
        assert s.football_day_start_hour == 9

    def test_football_day_start_hour_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("FOOTBALL_DAY_START_HOUR", "6")
        s = load_settings()
        assert s.football_day_start_hour == 6

    def test_photo_base_url_default_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("PHOTO_BASE_URL", raising=False)
        s = load_settings()
        assert s.photo_base_url == "http://victorsaez.cat"

    def test_photo_base_url_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("PHOTO_BASE_URL", "http://photos.example.com")
        s = load_settings()
        assert s.photo_base_url == "http://photos.example.com"

    def test_missing_telegram_group_id_raises(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.delenv("TELEGRAM_GROUP_ID", raising=False)
        with pytest.raises(RuntimeError, match="TELEGRAM_GROUP_ID"):
            load_settings()

    def test_telegram_group_id_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100987654")
        s = load_settings()
        assert s.telegram_group_id == "-100987654"

    def test_beloved_teams_default_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.delenv("BELOVED_TEAMS", raising=False)
        s = load_settings()
        assert set(s.beloved_teams) == {"PAN", "UZB", "CUW"}

    def test_beloved_teams_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("BELOVED_TEAMS", "pan, cuw")
        s = load_settings()
        assert set(s.beloved_teams) == {"PAN", "CUW"}

    def test_beloved_teams_env_uppercased_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("BELOVED_TEAMS", " esp , fra , ger ")
        s = load_settings()
        assert set(s.beloved_teams) == {"ESP", "FRA", "GER"}

    def test_beloved_teams_env_empty_entries_dropped(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")
        monkeypatch.setenv("BELOVED_TEAMS", "PAN,,, ,CUW")
        s = load_settings()
        assert set(s.beloved_teams) == {"PAN", "CUW"}


# ── Picante per-user profiles — Settings defaults ─────────────────────────────


class TestPicanteProfilesSettings:
    def test_profiles_enabled_default_is_false(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_profiles_enabled is False

    def test_store_text_default_is_true(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_store_text is True

    def test_profile_model_default_is_nano(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_profile_model == "gpt-5.4-nano"

    def test_profiles_window_days_default_is_2(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_profiles_window_days == 2

    def test_profiles_others_cap_default_is_3(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_profiles_others_cap == 3

    def test_profiles_piques_cap_default_is_5(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_profiles_piques_cap == 5

    def test_profiles_update_hour_default_is_4(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert s.picante_profiles_update_hour == 4

    def test_all_7_fields_can_be_overridden(self):
        s = Settings(
            telegram_bot_token="t",
            football_data_api_key="k",
            picante_profiles_enabled=True,
            picante_store_text=False,
            picante_profile_model="custom-model",
            picante_profiles_window_days=7,
            picante_profiles_others_cap=5,
            picante_profiles_piques_cap=10,
            picante_profiles_update_hour=3,
        )
        assert s.picante_profiles_enabled is True
        assert s.picante_store_text is False
        assert s.picante_profile_model == "custom-model"
        assert s.picante_profiles_window_days == 7
        assert s.picante_profiles_others_cap == 5
        assert s.picante_profiles_piques_cap == 10
        assert s.picante_profiles_update_hour == 3


# ── picante_profiles_enabled() helper ────────────────────────────────────────


class TestPicanteProfilesEnabled:
    def _full_settings(self, **overrides) -> Settings:
        base = dict(
            telegram_bot_token="t",
            football_data_api_key="k",
            openai_api_key="sk-key",
            openai_base_url="https://api.example.com/v1",
            openai_model="gpt-test",
            chat_picante_enabled=True,
            picante_profiles_enabled=True,
        )
        base.update(overrides)
        return Settings(**base)

    def test_returns_true_when_all_three_conditions_met(self):
        assert picante_profiles_enabled(self._full_settings()) is True

    def test_returns_false_when_profiles_flag_off(self):
        assert picante_profiles_enabled(self._full_settings(picante_profiles_enabled=False)) is False

    def test_returns_false_when_picante_disabled(self):
        assert picante_profiles_enabled(self._full_settings(chat_picante_enabled=False)) is False

    def test_returns_false_when_no_ai_api_key(self):
        assert picante_profiles_enabled(self._full_settings(openai_api_key="")) is False

    def test_returns_false_when_no_ai_base_url(self):
        assert picante_profiles_enabled(self._full_settings(openai_base_url="")) is False

    def test_returns_false_when_no_ai_model(self):
        assert picante_profiles_enabled(self._full_settings(openai_model="")) is False

    def test_returns_false_when_all_disabled(self):
        s = Settings(telegram_bot_token="t", football_data_api_key="k")
        assert picante_profiles_enabled(s) is False


# ── load_settings — 7 new picante profiles env vars ──────────────────────────


class TestLoadSettingsPicanteProfiles:
    """Verify that load_settings() reads the 7 new env vars (with correct defaults)."""

    def _base(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "apikey")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100123")

    def test_profiles_enabled_default_is_false(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_PROFILES_ENABLED", raising=False)
        s = load_settings()
        assert s.picante_profiles_enabled is False

    def test_profiles_enabled_reads_from_env_true(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILES_ENABLED", "1")
        s = load_settings()
        assert s.picante_profiles_enabled is True

    def test_profiles_enabled_zero_is_false(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILES_ENABLED", "0")
        s = load_settings()
        assert s.picante_profiles_enabled is False

    def test_store_text_default_is_true(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_STORE_TEXT", raising=False)
        s = load_settings()
        assert s.picante_store_text is True

    def test_store_text_zero_is_false(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_STORE_TEXT", "0")
        s = load_settings()
        assert s.picante_store_text is False

    def test_profile_model_default_is_nano(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_PROFILE_MODEL", raising=False)
        s = load_settings()
        assert s.picante_profile_model == "gpt-5.4-nano"

    def test_profile_model_reads_from_env(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILE_MODEL", "custom-model-v2")
        s = load_settings()
        assert s.picante_profile_model == "custom-model-v2"

    def test_window_days_default_is_2(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_PROFILES_WINDOW_DAYS", raising=False)
        s = load_settings()
        assert s.picante_profiles_window_days == 2

    def test_window_days_reads_from_env(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILES_WINDOW_DAYS", "7")
        s = load_settings()
        assert s.picante_profiles_window_days == 7

    def test_others_cap_default_is_3(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_PROFILES_OTHERS_CAP", raising=False)
        s = load_settings()
        assert s.picante_profiles_others_cap == 3

    def test_others_cap_reads_from_env(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILES_OTHERS_CAP", "5")
        s = load_settings()
        assert s.picante_profiles_others_cap == 5

    def test_piques_cap_default_is_5(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_PROFILES_PIQUES_CAP", raising=False)
        s = load_settings()
        assert s.picante_profiles_piques_cap == 5

    def test_piques_cap_reads_from_env(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILES_PIQUES_CAP", "10")
        s = load_settings()
        assert s.picante_profiles_piques_cap == 10

    def test_update_hour_default_is_4(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.delenv("PICANTE_PROFILES_UPDATE_HOUR", raising=False)
        s = load_settings()
        assert s.picante_profiles_update_hour == 4

    def test_update_hour_reads_from_env(self, monkeypatch):
        self._base(monkeypatch)
        monkeypatch.setenv("PICANTE_PROFILES_UPDATE_HOUR", "3")
        s = load_settings()
        assert s.picante_profiles_update_hour == 3
