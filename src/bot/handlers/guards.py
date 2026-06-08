"""Shared handler guards.

Cross-router access checks live here (DRY) so each feature router enforces the
whitelist the same way instead of re-implementing the lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.repositories.user import UserRepository

if TYPE_CHECKING:
    from pyrogram.types import CallbackQuery
    from pyrogram.types import User as TelegramUser
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.core.client import Bot
    from bot.db.models.user import User

NO_ACCESS_TOAST = "⛔ No tienes acceso a este bot."


def is_admin(client: Bot, user: TelegramUser | None) -> bool:
    """Whether *user* is the single configured admin (works for any update kind)."""
    return user is not None and user.id == client.settings.telegram.admin_id


async def guard_owner(client: Bot, callback_query: CallbackQuery) -> User | None:
    """The allowed user behind this callback, or answer + ``None`` if not allowed."""
    user = callback_query.from_user
    if user is not None:
        async with client.database.session() as session:
            owner = await UserRepository(session).get_by_telegram_id(user.id)
            if owner is not None and owner.is_allowed:
                return owner
    await callback_query.answer(NO_ACCESS_TOAST, show_alert=True)
    return None


async def allowed_owner(session: AsyncSession, telegram_id: int) -> User | None:
    """The whitelisted user for *telegram_id*, or ``None`` if missing / not allowed.

    The text-handler counterpart of :func:`guard_owner`: it takes an already-open
    session and a Telegram id (there is no callback to answer), so routers
    handling free-text replies can resolve and access-check the sender in one
    call instead of re-implementing the lookup.
    """
    owner = await UserRepository(session).get_by_telegram_id(telegram_id)
    if owner is None or not owner.is_allowed:
        return None
    return owner
