"""Repository for :class:`~bot.db.models.group.Group` rows."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from bot.constants import GROUP_LIST_DEFAULT_LIMIT
from bot.db.models.group import Group
from bot.repositories.base import BaseRepository


class GroupRepository(BaseRepository[Group]):
    """Persistence and queries for a user's saved groups."""

    model = Group

    async def get_for_user(self, user_id: int, facebook_id: str) -> Group | None:
        """Return the user's group with this ``facebook_id``, if saved."""
        stmt = select(Group).where(Group.user_id == user_id, Group.facebook_id == facebook_id)
        return await self.session.scalar(stmt)

    async def list_for_user(
        self, user_id: int, *, limit: int = GROUP_LIST_DEFAULT_LIMIT
    ) -> Sequence[Group]:
        """The user's saved groups, oldest first, capped at *limit*."""
        stmt = select(Group).where(Group.user_id == user_id).order_by(Group.created_at).limit(limit)
        result = await self.session.scalars(stmt)
        return result.all()

    async def count_for_user(self, user_id: int) -> int:
        """How many groups the user has saved."""
        stmt = select(func.count()).select_from(Group).where(Group.user_id == user_id)
        return await self.session.scalar(stmt) or 0
