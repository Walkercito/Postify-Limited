"""Pydantic schemas for the :class:`~bot.db.models.user.User` entity."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from bot.constants import AccessStatus, Role
from bot.schemas.base import BaseSchema

if TYPE_CHECKING:
    from pyrogram.types import User as TelegramUser


class UserCreate(BaseModel):
    """Fields captured when a user first registers."""

    telegram_id: int
    role: Role = Role.USER
    access_status: AccessStatus = AccessStatus.PENDING
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None

    @classmethod
    def from_telegram(
        cls,
        user: TelegramUser,
        *,
        role: Role = Role.USER,
        access_status: AccessStatus = AccessStatus.PENDING,
    ) -> UserCreate:
        """Build a create payload from a Pyrogram user plus the chosen role/status."""
        return cls(
            telegram_id=user.id,
            role=role,
            access_status=access_status,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code,
        )


class UserUpdate(BaseModel):
    """Mutable user fields; all optional for partial updates."""

    access_status: AccessStatus | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_active: bool | None = None
    last_seen_at: datetime | None = None


class UserRead(BaseSchema):
    """User representation returned to callers."""

    id: int
    telegram_id: int
    role: Role
    access_status: AccessStatus
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
