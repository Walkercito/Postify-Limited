"""Application configuration loaded from the environment / ``.env``.

Uses pydantic-settings v2. Nested sections are populated with the ``__``
delimiter, e.g. ``TELEGRAM__API_ID`` maps to ``settings.telegram.api_id``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot.constants import (
    DEFAULT_DATABASE_URL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_SESSION_NAME,
    DEFAULT_WORKDIR,
    POST_BACKOFF_BASE_SEC,
    POST_BACKOFF_CAP_SEC,
    POST_BACKOFF_MULTIPLIER,
    POST_CIRCADIAN_ACTIVE_END_HOUR,
    POST_CIRCADIAN_ACTIVE_END_MINUTE,
    POST_CIRCADIAN_ACTIVE_START_HOUR,
    POST_CIRCADIAN_ACTIVE_START_MINUTE,
    POST_CIRCADIAN_TIMEZONE,
    POST_DAILY_CAP_ATTEMPTS,
    POST_WINDOW_SECONDS,
    LogFormat,
)


class TelegramSettings(BaseModel):
    """Credentials and options for the Telegram MTProto session."""

    api_id: int
    api_hash: SecretStr
    bot_token: SecretStr
    admin_id: int  # Telegram user id of the single admin (seeded on startup).
    session_name: str = DEFAULT_SESSION_NAME
    workdir: str = DEFAULT_WORKDIR


class DatabaseSettings(BaseModel):
    """SQLAlchemy async engine options."""

    url: str = DEFAULT_DATABASE_URL
    echo: bool = False


class LoggingSettings(BaseModel):
    """structlog rendering and verbosity options."""

    level: str = DEFAULT_LOG_LEVEL
    format: LogFormat = LogFormat.CONSOLE


class PostLimitsSettings(BaseModel):
    """Per-account publish guards: WHEN and HOW MANY posts go out, never content.

    Backs the three behaviour-only anti-automation gates (circadian active-hours,
    rolling daily cap, escalating cross-run back-off) enforced by
    :class:`~bot.services.account_post_limit_service.AccountPostLimitService`.
    Defaults come from ``constants.py``; override via the ``POST_LIMITS__`` env
    prefix (e.g. ``POST_LIMITS__DAILY_CAP=120``).
    """

    active_start_hour: int = POST_CIRCADIAN_ACTIVE_START_HOUR
    active_start_minute: int = POST_CIRCADIAN_ACTIVE_START_MINUTE
    active_end_hour: int = POST_CIRCADIAN_ACTIVE_END_HOUR
    active_end_minute: int = POST_CIRCADIAN_ACTIVE_END_MINUTE
    timezone: str = POST_CIRCADIAN_TIMEZONE
    daily_cap: int = POST_DAILY_CAP_ATTEMPTS
    window_seconds: int = POST_WINDOW_SECONDS
    backoff_base_sec: float = POST_BACKOFF_BASE_SEC
    backoff_multiplier: float = POST_BACKOFF_MULTIPLIER
    backoff_cap_sec: float = POST_BACKOFF_CAP_SEC


class Settings(BaseSettings):
    """Root settings object."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    post_limits: PostLimitsSettings = Field(default_factory=PostLimitsSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide, cached :class:`Settings` instance."""
    return Settings()
