"""Whitelist access control: request, admin alert, grant/deny/revoke.

A not-yet-allowed user taps *Request access*; the admin gets an instant alert
(DM) with Grant/Deny, and can also manage everyone from the *Management* screen.
Both decision surfaces share one parameterized callback handler.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from pyrogram import filters
from pyrogram.enums import ParseMode

from bot.callbacks import ACCESS_DECISION_PATTERN, parse_access_decision
from bot.constants import AccessStatus, CallbackScope, HandlerGroup, LogEvent, MenuAction, Role
from bot.core.logging import get_logger
from bot.handlers.base import Router
from bot.handlers.edits import edit_markup, edit_text
from bot.handlers.guards import is_admin
from bot.handlers.middleware import observed, tracks_activity
from bot.keyboards import access_alert_menu, back_to_menu, main_menu, management_menu
from bot.schemas.user import UserCreate
from bot.services.user_service import UserService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pyrogram.types import CallbackQuery
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.core.client import Bot
    from bot.db.models.user import User

log = get_logger(__name__)

# Toasts and notices (user-facing prose lives with its handler).
REQUEST_SENT_TOAST = "⏳ Tu solicitud fue enviada al administrador."
ALREADY_ALLOWED_TOAST = "✅ Ya tienes acceso."
MANAGEMENT_DENIED = "⛔ La administración es solo para el admin."
MANAGEMENT_TITLE = "👮 <b>Administración</b>\nElige una acción:"
MANAGEMENT_EMPTY = "👮 <b>Administración</b>\nAún no hay usuarios."
USER_NOT_FOUND_TOAST = "Ese usuario ya no existe."
GRANTED_TOAST = "Aprobado ✅"
DENIED_TOAST = "Rechazado 🚫"
ACCESS_GRANTED_NOTICE = "✅ ¡Tienes acceso! Elige una opción del menú para empezar."
ACCESS_DENIED_NOTICE = "🚫 Tu acceso a este bot fue rechazado."
ACCESS_REQUEST_ALERT = "🔔 <b>Nueva solicitud de acceso</b>\n{name}\nid: <code>{telegram_id}</code>"
GRANTED_CONFIRMATION = "✅ Acceso concedido a {name}."
DENIED_CONFIRMATION = "🚫 Acceso rechazado para {name}."


async def _management_lists(client: Bot, session: AsyncSession) -> tuple[list[User], list[User]]:
    """Pending/allowed users for the management screen, excluding the admin.

    Reads through the caller's session so a just-applied (flushed but not yet
    committed) access change is reflected in the rendered lists.
    """
    admin_id = client.settings.telegram.admin_id
    service = UserService(session)
    pending = await service.list_by_access(AccessStatus.PENDING)
    allowed = await service.list_by_access(AccessStatus.ALLOWED)
    return (
        [user for user in pending if user.telegram_id != admin_id],
        [user for user in allowed if user.telegram_id != admin_id],
    )


class AccessRouter(Router):
    """Registers the whitelist's request, management and decision handlers."""

    def register(self, bot: Bot) -> None:
        self._add_callback_query_handler(
            bot,
            self._on_request_access,
            filters.regex(rf"^{MenuAction.REQUEST_ACCESS}$"),
            HandlerGroup.DEFAULT,
        )
        self._add_callback_query_handler(
            bot,
            self._on_management,
            filters.regex(rf"^{MenuAction.MANAGEMENT}$"),
            HandlerGroup.DEFAULT,
        )
        self._add_callback_query_handler(
            bot,
            self._on_access_decision,
            filters.regex(ACCESS_DECISION_PATTERN),
            HandlerGroup.DEFAULT,
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_request_access(client: Bot, callback_query: CallbackQuery) -> None:
        user = callback_query.from_user
        async with client.database.session() as session:
            registered, _ = await UserService(session).register(
                UserCreate.from_telegram(user, role=Role.USER, access_status=AccessStatus.PENDING)
            )
            if registered.is_allowed:
                await callback_query.answer(ALREADY_ALLOWED_TOAST)
                return
        await client.send_message(
            chat_id=client.settings.telegram.admin_id,
            text=ACCESS_REQUEST_ALERT.format(
                name=html.escape(user.first_name or str(user.id)),
                telegram_id=user.id,
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=access_alert_menu(user.id),
        )
        log.info(LogEvent.ACCESS_REQUESTED, telegram_id=user.id)
        await callback_query.answer(REQUEST_SENT_TOAST)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_management(client: Bot, callback_query: CallbackQuery) -> None:
        if not is_admin(client, callback_query.from_user):
            await callback_query.answer(MANAGEMENT_DENIED, show_alert=True)
            return
        async with client.database.session() as session:
            pending, allowed = await _management_lists(client, session)
        if not pending and not allowed:
            await callback_query.message.reply_text(MANAGEMENT_EMPTY, reply_markup=back_to_menu())
        else:
            await callback_query.message.reply_text(
                MANAGEMENT_TITLE, reply_markup=management_menu(pending, allowed)
            )
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_access_decision(client: Bot, callback_query: CallbackQuery) -> None:
        if not is_admin(client, callback_query.from_user):
            await callback_query.answer(MANAGEMENT_DENIED, show_alert=True)
            return
        data = callback_query.data
        parsed = parse_access_decision(data) if isinstance(data, str) else None
        if parsed is None:
            return
        scope, status, target_id = parsed
        async with client.database.session() as session:
            service = UserService(session)
            updated = await service.set_access(target_id, status)
            if updated is None:
                await callback_query.answer(USER_NOT_FOUND_TOAST, show_alert=True)
                return
            name = updated.display_name
            await _notify_target(client, target_id, status)
            await _rerender(client, session, callback_query, scope, name, status)
        log.info(_decision_event(status), telegram_id=target_id)
        await callback_query.answer(
            GRANTED_TOAST if status is AccessStatus.ALLOWED else DENIED_TOAST
        )


def _decision_event(status: AccessStatus) -> LogEvent:
    return LogEvent.ACCESS_GRANTED if status is AccessStatus.ALLOWED else LogEvent.ACCESS_DENIED


async def _notify_target(client: Bot, telegram_id: int, status: AccessStatus) -> None:
    """Best-effort: tell the user about the decision (never raises)."""
    granted = status is AccessStatus.ALLOWED
    notice = ACCESS_GRANTED_NOTICE if granted else ACCESS_DENIED_NOTICE
    markup = main_menu(Role.USER) if granted else None
    try:
        await client.send_message(chat_id=telegram_id, text=notice, reply_markup=markup)
    except Exception:
        log.exception(LogEvent.ACCESS_NOTIFY_FAILED, telegram_id=telegram_id)


async def _rerender(
    client: Bot,
    session: AsyncSession,
    callback_query: CallbackQuery,
    scope: CallbackScope,
    name: str,
    status: AccessStatus,
) -> None:
    """Update the source message: confirm the alert, or refresh the list.

    The management refresh reads through ``session`` so it observes the access
    change just applied in the same transaction (a separate session would still
    see the pre-decision rows and render an identical keyboard).
    """
    if scope is CallbackScope.MANAGE:
        pending, allowed = await _management_lists(client, session)
        await _refresh_management(callback_query, pending, allowed)
        return
    template = GRANTED_CONFIRMATION if status is AccessStatus.ALLOWED else DENIED_CONFIRMATION
    await edit_text(callback_query, template.format(name=html.escape(name)))


async def _refresh_management(
    callback_query: CallbackQuery, pending: Sequence[User], allowed: Sequence[User]
) -> None:
    if not pending and not allowed:
        await edit_text(callback_query, MANAGEMENT_EMPTY, reply_markup=back_to_menu())
    else:
        await edit_markup(callback_query, management_menu(pending, allowed))
