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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide, cached :class:`Settings` instance."""
    return Settings()
