"""Repository for :class:`~bot.db.models.user.User` rows."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from bot.constants import AccessStatus
from bot.db.models.user import User
from bot.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Persistence and queries for users."""

    model = User

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self.session.scalar(stmt)

    async def list_by_access_status(self, status: AccessStatus) -> Sequence[User]:
        """All users currently in the given whitelist *status*, oldest first."""
        stmt = select(User).where(User.access_status == status).order_by(User.created_at)
        result = await self.session.scalars(stmt)
        return result.all()

    async def set_access_status(self, telegram_id: int, status: AccessStatus) -> User | None:
        """Set a user's whitelist status. Returns ``None`` if the user is unknown."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            return None
        user.access_status = status
        await self.session.flush()
        return user

    async def touch_last_seen(self, telegram_id: int, *, when: datetime) -> bool:
        """Record the user's most recent activity. Returns ``False`` if unknown."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            return False
        user.last_seen_at = when
        await self.session.flush()
        return True
