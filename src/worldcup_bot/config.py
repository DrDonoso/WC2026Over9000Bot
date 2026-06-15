"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    telegram_bot_token: str
    football_data_api_key: str
    predictions_path: str = "data/predictions.yml"
    competition_code: str = "WC"
    timezone: str = "Europe/Madrid"
    telegram_group_id: str | None = None
    football_cache_ttl: float = 60.0
    football_day_start_hour: int = 9
    photo_base_url: str = "http://victorsaez.cat"


def load_settings() -> Settings:
    """Read configuration from environment. Raises RuntimeError on missing required vars."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError(
            "❌ TELEGRAM_BOT_TOKEN is not set. "
            "Set it in the environment or in .env before starting the bot."
        )

    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "❌ FOOTBALL_DATA_API_KEY is not set. "
            "Set it in the environment or in .env before starting the bot."
        )

    return Settings(
        telegram_bot_token=token,
        football_data_api_key=api_key,
        predictions_path=os.getenv("PREDICTIONS_PATH", "data/predictions.yml"),
        competition_code=os.getenv("COMPETITION_CODE", "WC"),
        timezone=os.getenv("TIMEZONE", "Europe/Madrid"),
        telegram_group_id=os.getenv("TELEGRAM_GROUP_ID") or None,
        football_cache_ttl=float(os.getenv("FOOTBALL_CACHE_TTL", "60")),
        football_day_start_hour=int(os.getenv("FOOTBALL_DAY_START_HOUR", "9")),
        photo_base_url=os.getenv("PHOTO_BASE_URL", "http://victorsaez.cat"),
    )
