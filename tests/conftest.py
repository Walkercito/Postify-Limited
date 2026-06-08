"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bot.db.base import Base
from bot.db.models import User  # noqa: F401  (register model metadata)

_MEMORY_URL = "sqlite+aiosqlite://"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A clean, isolated in-memory database session per test."""
    engine = create_async_engine(
        _MEMORY_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session

    await engine.dispose()
