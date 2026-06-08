"""Command handlers: ``/start`` and ``/help``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyrogram import filters

from bot.constants import AccessStatus, Command, HandlerGroup, LogEvent, Role
from bot.core.logging import get_logger
from bot.handlers.base import Router
from bot.handlers.middleware import observed, tracks_activity
from bot.keyboards import main_menu, request_access_menu
from bot.repositories.facebook_account import FacebookAccountRepository
from bot.repositories.group import GroupRepository
from bot.schemas.user import UserCreate
from bot.services.user_service import UserService

if TYPE_CHECKING:
    from pyrogram.types import Message
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.core.client import Bot

log = get_logger(__name__)

# How many groups to peek at when deciding the onboarding hint (presence only).
_ONBOARDING_GROUP_PROBE = 1

START_GREETING = "👋 <b>¡Bienvenido!</b>"
START_ADMIN_HINT = (
    "Eres el administrador. Desde el menú puedes crear publicaciones, gestionar "
    "grupos, administrar el acceso de los usuarios y vincular cuentas de Facebook."
)
START_HINT_NO_ACCOUNT = (
    "Todavía no tienes una cuenta de Facebook vinculada. Pídele al administrador "
    "que vincule la tuya para poder publicar."
)
START_HINT_NO_GROUPS = (
    "Tu cuenta de Facebook ya está lista. Añade tus grupos desde 👥 Mis grupos "
    "para empezar a publicar."
)
START_HINT_READY = "Todo está listo. Pulsa 📝 Crear publicación cuando quieras empezar."

NOT_ALLOWED_MESSAGE = (
    "⛔ <b>Todavía no tienes acceso a este bot.</b>\n\n"
    "Pulsa el botón de abajo para pedírselo al administrador."
)

HELP_MESSAGE = (
    "❓ <b>Ayuda</b>\n\n"
    "Este bot publica en tus grupos de Facebook por ti.\n\n"
    "<b>Comandos</b>\n"
    "/start — abre el menú principal\n"
    "/help — muestra esta ayuda\n\n"
    "<b>Desde el menú</b>\n"
    "📝 Crear publicación — escribe el texto, añade fotos y elige los grupos.\n"
    "👥 Mis grupos — añade o elimina los grupos donde publicas.\n"
    "📋 Plantillas — guarda publicaciones para reutilizarlas (próximamente)."
)
HELP_ADMIN_EXTRA = (
    "\n\n<b>Solo para el administrador</b>\n"
    "⚙️ Administración — aprueba, rechaza o revoca el acceso de los usuarios.\n"
    "🔗 Facebook — vincula la cuenta de Facebook de cada usuario."
)


class CommandRouter(Router):
    """Registers the bot's slash-command handlers."""

    def register(self, bot: Bot) -> None:
        self._add_message_handler(
            bot, self._on_start, filters.command(Command.START), HandlerGroup.DEFAULT
        )
        self._add_message_handler(
            bot, self._on_help, filters.command(Command.HELP), HandlerGroup.DEFAULT
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_start(client: Bot, message: Message) -> None:
        user = message.from_user
        if user is None:
            return

        is_admin = user.id == client.settings.telegram.admin_id
        role = Role.ADMIN if is_admin else Role.USER
        access_status = AccessStatus.ALLOWED if is_admin else AccessStatus.PENDING
        async with client.database.session() as session:
            registered, created = await UserService(session).register(
                UserCreate.from_telegram(user, role=role, access_status=access_status)
            )
            allowed = registered.is_allowed
            hint = await _onboarding_hint(session, registered.id, is_admin) if allowed else None

        if created:
            log.info(LogEvent.USER_REGISTERED, role=role)
        if hint is not None:
            await message.reply_text(f"{START_GREETING}\n{hint}", reply_markup=main_menu(role))
        else:
            await message.reply_text(NOT_ALLOWED_MESSAGE, reply_markup=request_access_menu())

    @staticmethod
    @observed
    @tracks_activity
    async def _on_help(client: Bot, message: Message) -> None:
        user = message.from_user
        is_admin = user is not None and user.id == client.settings.telegram.admin_id
        await message.reply_text(HELP_MESSAGE + (HELP_ADMIN_EXTRA if is_admin else ""))


async def _onboarding_hint(session: AsyncSession, user_id: int, is_admin: bool) -> str:
    """The state-aware line shown under the greeting for an allowed user.

    Nudges the user toward the next missing step: link a Facebook account, then
    add groups, then post. The admin gets a capabilities overview instead.
    """
    if is_admin:
        return START_ADMIN_HINT
    if await FacebookAccountRepository(session).get_for_user(user_id) is None:
        return START_HINT_NO_ACCOUNT
    groups = await GroupRepository(session).list_for_user(user_id, limit=_ONBOARDING_GROUP_PROBE)
    if not groups:
        return START_HINT_NO_GROUPS
    return START_HINT_READY
