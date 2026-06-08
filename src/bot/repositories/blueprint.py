"""Repository for :class:`~bot.db.models.blueprint.Blueprint` rows."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from bot.constants import BLUEPRINT_LIST_DEFAULT_LIMIT
from bot.db.models.blueprint import Blueprint
from bot.repositories.base import BaseRepository


class BlueprintRepository(BaseRepository[Blueprint]):
    """Persistence and queries for a user's saved posts (blueprints)."""

    model = Blueprint

    async def get_by_slug(self, user_id: int, slug: str) -> Blueprint | None:
        """Return the user's blueprint with this ``slug``, if it exists."""
        stmt = select(Blueprint).where(Blueprint.user_id == user_id, Blueprint.slug == slug)
        return await self.session.scalar(stmt)

    async def list_for_user(
        self, user_id: int, *, limit: int = BLUEPRINT_LIST_DEFAULT_LIMIT
    ) -> Sequence[Blueprint]:
        """The user's saved blueprints, oldest first, capped at *limit*."""
        stmt = (
            select(Blueprint)
            .where(Blueprint.user_id == user_id)
            .order_by(Blueprint.created_at)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return result.all()

    async def count_for_user(self, user_id: int) -> int:
        """How many blueprints the user has saved."""
        stmt = select(func.count()).select_from(Blueprint).where(Blueprint.user_id == user_id)
        return await self.session.scalar(stmt) or 0
