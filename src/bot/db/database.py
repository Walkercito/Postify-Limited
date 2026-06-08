"""Async SQLAlchemy engine and session lifecycle, wrapped in a class."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.constants import SQLITE_MEMORY, SQLitePragma
from bot.core.config import DatabaseSettings
from bot.db.base import Base


class Database:
    """Owns the async engine and session factory for the application.

    Build this once at startup (engine and pool are long-lived); open one
    short-lived :class:`AsyncSession` per unit of work via :meth:`session`.
    """

    def __init__(self, settings: DatabaseSettings) -> None:
        self._ensure_parent_dir(settings.url)
        self._engine = create_async_engine(settings.url, echo=settings.echo)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )
        self._register_sqlite_pragmas()

    @staticmethod
    def _ensure_parent_dir(url: str) -> None:
        """Create the directory that will hold an on-disk SQLite file."""
        database = make_url(url).database
        if database and database != SQLITE_MEMORY:
            Path(database).parent.mkdir(parents=True, exist_ok=True)

    def _register_sqlite_pragmas(self) -> None:
        """Enforce foreign keys and enable WAL on every new connection.

        The listener must target ``sync_engine`` (the underlying DBAPI engine),
        not the async wrapper.
        """

        @event.listens_for(self._engine.sync_engine, "connect")
        def _apply_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            for pragma in SQLitePragma:
                cursor.execute(pragma.value)
            cursor.close()

    async def create_all(self) -> None:
        """Create any missing tables. Use Alembic for real migrations later."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Dispose of the engine and its connection pool."""
        await self._engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a transactional session: commit on success, rollback on error."""
        async with self._session_factory.begin() as session:
            yield session
