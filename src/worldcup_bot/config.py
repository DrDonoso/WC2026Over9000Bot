"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


_DEFAULT_REDDIT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _parse_tla_list(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated TLA list into an upper-cased tuple, dropping empties."""
    return tuple(t.strip().upper() for t in raw.split(",") if t.strip())


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
    goal_poll_interval_seconds: int = 60
    reddit_user_agent: str = field(default=_DEFAULT_REDDIT_UA)
    tongo_gifs_dir: str = ""
    tongo_phrases_path: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""
    daily_update_hour: int = 9
    state_dir: str = "/app/state"
    espn_league_slug: str = "fifa.world"
    finished_poll_interval_seconds: int = 120
    openai_image_model: str = "gpt-image-2"
    openai_image_api_key: str = ""
    openai_image_base_url: str = ""
    rich_image_hour: int = 0
    beloved_teams: tuple[str, ...] = ("PAN", "UZB", "CUW")


def ai_enabled(settings: "Settings") -> bool:
    """Return True only when all three OpenAI env vars are non-empty."""
    return bool(
        settings.openai_api_key
        and settings.openai_base_url
        and settings.openai_model
    )


def image_ai_enabled(settings: "Settings") -> bool:
    """Return True when image-model key, base_url, and model are all resolvable."""
    return bool(
        _effective_image_api_key(settings)
        and _effective_image_base_url(settings)
        and settings.openai_image_model
    )


def _effective_image_api_key(settings: "Settings") -> str:
    """Return the image-specific API key, falling back to the chat key."""
    return settings.openai_image_api_key or settings.openai_api_key


def _effective_image_base_url(settings: "Settings") -> str:
    """Return the image-specific base URL, falling back to the chat base URL."""
    return settings.openai_image_base_url or settings.openai_base_url


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

    group_id = os.getenv("TELEGRAM_GROUP_ID", "")
    if not group_id:
        raise RuntimeError(
            "❌ TELEGRAM_GROUP_ID is not set. "
            "It is required for live goal notifications. "
            "Set it in the environment or in .env before starting the bot."
        )

    return Settings(
        telegram_bot_token=token,
        football_data_api_key=api_key,
        predictions_path=os.getenv("PREDICTIONS_PATH", "data/predictions.yml"),
        competition_code=os.getenv("COMPETITION_CODE", "WC"),
        timezone=os.getenv("TIMEZONE", "Europe/Madrid"),
        telegram_group_id=group_id,
        football_cache_ttl=float(os.getenv("FOOTBALL_CACHE_TTL", "60")),
        football_day_start_hour=int(os.getenv("FOOTBALL_DAY_START_HOUR", "9")),
        photo_base_url=os.getenv("PHOTO_BASE_URL", "http://victorsaez.cat"),
        goal_poll_interval_seconds=int(os.getenv("GOAL_POLL_INTERVAL_SECONDS", "60")),
        reddit_user_agent=os.getenv("REDDIT_USER_AGENT", _DEFAULT_REDDIT_UA),
        tongo_gifs_dir=os.getenv("TONGO_GIFS_DIR", ""),
        tongo_phrases_path=os.getenv("TONGO_PHRASES_PATH", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
        openai_model=os.getenv("OPENAI_MODEL", ""),
        daily_update_hour=int(os.getenv("DAILY_UPDATE_HOUR", "9")),
        state_dir=os.getenv("STATE_DIR", "/app/state"),
        espn_league_slug=os.getenv("ESPN_LEAGUE_SLUG", "fifa.world"),
        finished_poll_interval_seconds=int(os.getenv("FINISHED_POLL_INTERVAL_SECONDS", "120")),
        openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        openai_image_api_key=os.getenv("OPENAI_IMAGE_API_KEY", ""),
        openai_image_base_url=os.getenv("OPENAI_IMAGE_BASE_URL", ""),
        rich_image_hour=int(os.getenv("RICH_IMAGE_HOUR", "0")),
        beloved_teams=_parse_tla_list(os.getenv("BELOVED_TEAMS", "PAN,UZB,CUW")),
    )
