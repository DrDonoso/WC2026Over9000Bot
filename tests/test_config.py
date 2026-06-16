"""Tests for Settings dataclass and load_settings()."""

from __future__ import annotations

import pytest

from worldcup_bot.config import Settings, load_settings


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
