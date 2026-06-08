"""User ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from bot.constants import (
    ACCESS_STATUS_MAX_LENGTH,
    FIRST_NAME_MAX_LENGTH,
    LANGUAGE_CODE_MAX_LENGTH,
    LAST_NAME_MAX_LENGTH,
    ROLE_NAME_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
    AccessStatus,
    Role,
)
from bot.db.base import Base, TimestampMixin, enum_values


class User(Base, TimestampMixin):
    """A Telegram user known to the bot.

    There is exactly one ``admin`` (the seeded ``admin_id``); every other user
    is a ``user`` whose ``access_status`` the admin controls (the whitelist).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[Role] = mapped_column(
        SAEnum(
            Role,
            name="role",
            native_enum=False,
            length=ROLE_NAME_MAX_LENGTH,
            values_callable=enum_values,
        ),
        index=True,
    )
    access_status: Mapped[AccessStatus] = mapped_column(
        SAEnum(
            AccessStatus,
            name="access_status",
            native_enum=False,
            length=ACCESS_STATUS_MAX_LENGTH,
            values_callable=enum_values,
        ),
        default=AccessStatus.PENDING,
        index=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(FIRST_NAME_MAX_LENGTH), default=None)
    last_name: Mapped[str | None] = mapped_column(String(LAST_NAME_MAX_LENGTH), default=None)
    username: Mapped[str | None] = mapped_column(String(USERNAME_MAX_LENGTH), default=None)
    language_code: Mapped[str | None] = mapped_column(
        String(LANGUAGE_CODE_MAX_LENGTH), default=None
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(default=None)

    @property
    def full_name(self) -> str | None:
        """Display name built from first/last name, or ``None`` if unset."""
        parts = [part for part in (self.first_name, self.last_name) if part]
        return " ".join(parts) if parts else None

    @property
    def display_name(self) -> str:
        """Best human label for the user: full name, then @username, then id."""
        if self.full_name:
            return self.full_name
        if self.username:
            return f"@{self.username}"
        return str(self.telegram_id)

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def is_allowed(self) -> bool:
        """Whether the user may use the bot (admins are implicitly allowed)."""
        return self.is_admin or self.access_status is AccessStatus.ALLOWED

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, telegram_id={self.telegram_id!r}, role={self.role!r})"
