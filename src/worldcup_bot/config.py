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
    tongo_users_path: str = ""
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
    tve_enabled: bool = True
    # ── Chat features (picante + revive) ──────────────────────────────────────
    chat_picante_enabled: bool = False
    chat_revive_enabled: bool = False
    chat_buffer_size: int = 30
    picante_probability: float = 0.20
    picante_cooldown_seconds: int = 300
    picante_max_per_day: int = 30
    picante_min_buffer: int = 5
    picante_temperature: float = 0.9
    revive_check_interval_seconds: int = 14400
    revive_inactive_days: int = 3
    revive_mention_cooldown_days: int = 2
    revive_temperature: float = 0.8
    revive_quiet_start_hour: int = 23
    revive_quiet_end_hour: int = 6
    revive_jitter_seconds: int = 2700
    # ── Post-final VAR-correction watch ──────────────────────────────────────
    final_correction_window_minutes: int = 30
    # ── /elecciones display mode ─────────────────────────────────────────────
    choices_type: str = "text"   # "text" | "image"
    # ── Picante per-user profiles (feature flag OFF by default) ──────────────
    picante_profiles_enabled: bool = False
    picante_store_text: bool = True
    picante_profile_model: str = "gpt-5.4-nano"
    picante_profiles_window_days: int = 2
    picante_profiles_others_cap: int = 3
    picante_profiles_piques_cap: int = 5
    picante_profiles_update_hour: int = 4


def _parse_bool(raw: str) -> bool:
    """Parse a boolean-ish env var ('0', 'false', 'no' → False; anything else → True)."""
    return raw.strip().lower() not in ("0", "false", "no")


def ai_enabled(settings: "Settings") -> bool:
    """Return True only when all three OpenAI env vars are non-empty."""
    return bool(
        settings.openai_api_key
        and settings.openai_base_url
        and settings.openai_model
    )


def picante_enabled(settings: "Settings") -> bool:
    """Return True when picante is explicitly enabled AND AI is configured."""
    return settings.chat_picante_enabled and ai_enabled(settings)


def revive_enabled(settings: "Settings") -> bool:
    """Return True when revive is explicitly enabled AND AI is configured."""
    return settings.chat_revive_enabled and ai_enabled(settings)


def picante_profiles_enabled(settings: "Settings") -> bool:
    """Return True when profiles feature is enabled AND picante is enabled."""
    return settings.picante_profiles_enabled and picante_enabled(settings)


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
        tongo_users_path=os.getenv("TONGO_USERS_PATH", ""),
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
        tve_enabled=_parse_bool(os.getenv("TVE_ENABLED", "1")),
        chat_picante_enabled=_parse_bool(os.getenv("CHAT_PICANTE_ENABLED", "0")),
        chat_revive_enabled=_parse_bool(os.getenv("CHAT_REVIVE_ENABLED", "0")),
        chat_buffer_size=int(os.getenv("CHAT_BUFFER_SIZE", "30")),
        picante_probability=float(os.getenv("PICANTE_PROBABILITY", "0.20")),
        picante_cooldown_seconds=int(os.getenv("PICANTE_COOLDOWN_SECONDS", "300")),
        picante_max_per_day=int(os.getenv("PICANTE_MAX_PER_DAY", "30")),
        picante_min_buffer=int(os.getenv("PICANTE_MIN_BUFFER", "5")),
        picante_temperature=float(os.getenv("PICANTE_TEMPERATURE", "0.9")),
        revive_check_interval_seconds=int(os.getenv("REVIVE_CHECK_INTERVAL_SECONDS", "14400")),
        revive_inactive_days=int(os.getenv("REVIVE_INACTIVE_DAYS", "3")),
        revive_mention_cooldown_days=int(os.getenv("REVIVE_MENTION_COOLDOWN_DAYS", "2")),
        revive_temperature=float(os.getenv("REVIVE_TEMPERATURE", "0.8")),
        revive_quiet_start_hour=int(os.getenv("REVIVE_QUIET_START_HOUR", "23")),
        revive_quiet_end_hour=int(os.getenv("REVIVE_QUIET_END_HOUR", "6")),
        revive_jitter_seconds=int(os.getenv("REVIVE_JITTER_SECONDS", "2700")),
        final_correction_window_minutes=int(os.getenv("FINAL_CORRECTION_WINDOW_MINUTES", "30")),
        choices_type=os.getenv("CHOICES_TYPE", "text"),
        picante_profiles_enabled=_parse_bool(os.getenv("PICANTE_PROFILES_ENABLED", "0")),
        picante_store_text=_parse_bool(os.getenv("PICANTE_STORE_TEXT", "1")),
        picante_profile_model=os.getenv("PICANTE_PROFILE_MODEL", "gpt-5.4-nano"),
        picante_profiles_window_days=int(os.getenv("PICANTE_PROFILES_WINDOW_DAYS", "2")),
        picante_profiles_others_cap=int(os.getenv("PICANTE_PROFILES_OTHERS_CAP", "3")),
        picante_profiles_piques_cap=int(os.getenv("PICANTE_PROFILES_PIQUES_CAP", "5")),
        picante_profiles_update_hour=int(os.getenv("PICANTE_PROFILES_UPDATE_HOUR", "4")),
    )
