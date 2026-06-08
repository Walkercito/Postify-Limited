"""Generic asynchronous repository shared by all concrete repositories (DRY)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import DEFAULT_PAGE_LIMIT, DEFAULT_PAGE_OFFSET
from bot.db.base import Base


class BaseRepository[ModelT: Base]:
    """CRUD operations over a single ORM model.

    Concrete repositories set the :attr:`model` class attribute and may add
    entity-specific queries.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pk: Any) -> ModelT | None:
        return await self.session.get(self.model, pk)

    async def list(
        self,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = DEFAULT_PAGE_OFFSET,
    ) -> Sequence[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return result.all()

    async def add(self, instance: ModelT) -> ModelT:
        """Persist a new instance and flush to assign its primary key."""
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()
