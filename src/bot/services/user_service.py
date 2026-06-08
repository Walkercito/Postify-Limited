"""Business logic for the user lifecycle."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import AccessStatus
from bot.db.models.user import User
from bot.repositories.user import UserRepository
from bot.schemas.user import UserCreate


class UserService:
    """Coordinates user persistence on top of :class:`UserRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def register(self, data: UserCreate) -> tuple[User, bool]:
        """Idempotently register a user.

        Returns the (possibly pre-existing) user and whether it was newly
        created. Create-only: an existing user is returned untouched, so a
        stored ``access_status`` is never overwritten by a fresh ``/start``.
        """
        existing = await self._users.get_by_telegram_id(data.telegram_id)
        if existing is not None:
            return existing, False

        user = User(
            telegram_id=data.telegram_id,
            role=data.role,
            access_status=data.access_status,
            first_name=data.first_name,
            last_name=data.last_name,
            username=data.username,
            language_code=data.language_code,
        )
        await self._users.add(user)
        return user, True

    async def set_access(self, telegram_id: int, status: AccessStatus) -> User | None:
        """Grant, deny or revoke a user's access. ``None`` if user is unknown."""
        return await self._users.set_access_status(telegram_id, status)

    async def list_by_access(self, status: AccessStatus) -> Sequence[User]:
        """List users in the given whitelist status (for the admin console)."""
        return await self._users.list_by_access_status(status)
