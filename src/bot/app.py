"""Application bootstrap and lifecycle (composition root)."""

from __future__ import annotations

import asyncio
import signal

from bot.constants import AccessStatus, LogEvent, Role
from bot.core.client import Bot
from bot.core.config import Settings, get_settings
from bot.core.logging import configure_logging, get_logger
from bot.db.database import Database
from bot.handlers import register_routers
from bot.schemas.user import UserCreate
from bot.services.user_service import UserService

log = get_logger(__name__)

_SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class BotApplication:
    """Owns and orchestrates the bot's dependencies and lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._database = Database(settings.database)
        self._client = Bot(settings, self._database)

    async def start(self) -> None:
        log.info(LogEvent.BOT_STARTING)
        await self._database.create_all()
        log.info(LogEvent.DATABASE_INITIALIZED)
        await self._seed_admin()
        register_routers(self._client)
        await self._client.start()
        log.info(LogEvent.BOT_STARTED)

    async def stop(self) -> None:
        log.info(LogEvent.BOT_STOPPING)
        await self._client.stop()
        await self._database.dispose()
        log.info(LogEvent.DATABASE_DISPOSED)
        log.info(LogEvent.BOT_STOPPED)

    async def run(self) -> None:
        """Start the bot, block until a shutdown signal, then stop cleanly."""
        await self.start()
        try:
            await self._wait_for_shutdown()
        finally:
            await self.stop()

    async def _seed_admin(self) -> None:
        """Ensure the single admin user exists (idempotent)."""
        admin_id = self._settings.telegram.admin_id
        async with self._database.session() as session:
            _, created = await UserService(session).register(
                UserCreate(
                    telegram_id=admin_id, role=Role.ADMIN, access_status=AccessStatus.ALLOWED
                )
            )
        if created:
            log.info(LogEvent.ADMIN_SEEDED, telegram_id=admin_id)

    @staticmethod
    async def _wait_for_shutdown() -> None:
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        for sig in _SHUTDOWN_SIGNALS:
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()


async def _amain() -> None:
    settings = get_settings()
    configure_logging(settings.logging)
    application = BotApplication(settings)
    await application.run()


def main() -> None:
    """Console-script / ``python -m bot`` entry point."""
    asyncio.run(_amain())
