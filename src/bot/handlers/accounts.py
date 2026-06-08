"""Admin-only Facebook account provisioning.

The bot posts on a user's behalf using a Facebook *session* the admin captures
on a trusted device (``scripts/fb_capture_session.py``) and uploads here. The
admin opens *Facebook* (main-menu button), taps *Link* for a user, then sends
the resulting ``session.json`` as a document; the bot extracts the account uid
and access token and stores them for that user. *Unlink* removes a stored
account. Only the access token + uid are persisted — never the password.

The "awaiting a session file" state is held in the in-memory
:class:`~bot.fb_link_requests.FacebookLinkStore` keyed by the admin's id; a
custom filter (:data:`_AWAITING_SESSION_FILTER`) lets this router claim the
admin's next document upload only while a link is armed.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Literal, cast

from pyrogram import Client, filters

from bot.callbacks import ACCOUNT_DECISION_PATTERN, parse_account_decision
from bot.constants import (
    SESSION_FILE_MAX_BYTES,
    AccessStatus,
    AccountAction,
    HandlerGroup,
    LogEvent,
    MenuAction,
)
from bot.core.exceptions import FacebookAccountTakenError, InvalidSessionPayloadError
from bot.core.logging import get_logger
from bot.facebook_session import parse_session_payload
from bot.handlers.base import Router
from bot.handlers.edits import edit_text
from bot.handlers.guards import is_admin
from bot.handlers.middleware import observed, tracks_activity
from bot.keyboards import account_link_cancel_menu, accounts_menu
from bot.repositories.user import UserRepository
from bot.services.facebook_account_service import FacebookAccountService
from bot.services.user_service import UserService

if TYPE_CHECKING:
    from pyrogram.filters import Filter
    from pyrogram.types import CallbackQuery, Message
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.core.client import Bot
    from bot.db.models.user import User
    from bot.facebook_session import CapturedSession

log = get_logger(__name__)

# Screen titles + prompts (user-facing prose lives with its handler).
ACCOUNTS_DENIED = "⛔ La sección de Facebook es solo para el administrador."
ACCOUNTS_TITLE = "🔗 <b>Cuentas de Facebook</b>\nElige un usuario para vincular o desvincular:"
ACCOUNT_LINK_PROMPT = "📎 Envíame el archivo session.json capturado para <b>{name}</b>."

# Decision toasts.
LINK_CANCELLED_TOAST = "Vinculación cancelada."
UNLINKED_TOAST = "Desvinculado 🔓"
NOT_LINKED_TOAST = "Ese usuario no tiene ninguna cuenta vinculada."
TARGET_NOT_ELIGIBLE_TOAST = "Ese usuario no tiene acceso al bot."

# Inject-session outcomes (replies to the uploaded document).
SESSION_TOO_LARGE = "🚫 Ese archivo es demasiado grande para ser un session.json."
SESSION_DOWNLOAD_FAILED = "⚠️ No pude leer ese archivo. Inténtalo de nuevo."
SESSION_PARSE_FAILED = "🚫 Ese archivo no es un session.json válido: {reason}"
SESSION_TARGET_GONE = "🤷 Ese usuario ya no existe."
SESSION_ACCOUNT_TAKEN = "🚫 Esa cuenta de Facebook ya está vinculada a otro usuario."
SESSION_LINKED = "✅ Vinculé la cuenta de Facebook <code>{fb_uid}</code> a <b>{name}</b>."


async def _awaiting_session_predicate(_filter: Filter, client: Client, message: Message) -> bool:
    """True when the document's sender has an armed Facebook-link request."""
    bot = cast("Bot", client)
    user = message.from_user
    return user is not None and bot.fb_links.get(user.id) is not None


# State gate: only claim a document while the admin has tapped *Link* for a user.
_AWAITING_SESSION_FILTER = filters.create(_awaiting_session_predicate)


class AccountsRouter(Router):
    """Registers the Facebook-accounts screen and the inject-session flow."""

    def register(self, bot: Bot) -> None:
        self._add_callback_query_handler(
            bot,
            self._on_accounts,
            filters.regex(rf"^{MenuAction.ACCOUNTS}$"),
            HandlerGroup.DEFAULT,
        )
        self._add_callback_query_handler(
            bot,
            self._on_account_decision,
            filters.regex(ACCOUNT_DECISION_PATTERN),
            HandlerGroup.DEFAULT,
        )
        self._add_message_handler(
            bot,
            self._on_session_document,
            filters.private & filters.document & _AWAITING_SESSION_FILTER,
            HandlerGroup.DEFAULT,
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_accounts(client: Bot, callback_query: CallbackQuery) -> None:
        if not is_admin(client, callback_query.from_user):
            await callback_query.answer(ACCOUNTS_DENIED, show_alert=True)
            return
        async with client.database.session() as session:
            rows = await _accounts_overview(session)
        await edit_text(callback_query, ACCOUNTS_TITLE, reply_markup=accounts_menu(rows))
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_account_decision(client: Bot, callback_query: CallbackQuery) -> None:
        if not is_admin(client, callback_query.from_user):
            await callback_query.answer(ACCOUNTS_DENIED, show_alert=True)
            return
        data = callback_query.data
        parsed = parse_account_decision(data) if isinstance(data, str) else None
        if parsed is None:
            return
        action, target_id = parsed
        if action is AccountAction.CANCEL:
            await _cancel_link(client, callback_query)
        elif action is AccountAction.UNLINK:
            await _do_unlink(client, callback_query, target_id)
        else:
            await _start_link(client, callback_query, target_id)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_session_document(client: Bot, message: Message) -> None:
        target_id = client.fb_links.get(client.settings.telegram.admin_id)
        if target_id is None:
            return
        raw = await _read_session_document(client, message)
        if raw is None:
            return
        try:
            captured = parse_session_payload(raw)
        except InvalidSessionPayloadError as exc:
            await message.reply_text(SESSION_PARSE_FAILED.format(reason=html.escape(str(exc))))
            return
        await _apply_capture(client, message, target_id, captured)


async def _accounts_overview(session: AsyncSession) -> list[tuple[User, bool]]:
    """Allowed users paired with whether each already has a linked account."""
    users = await UserService(session).list_by_access(AccessStatus.ALLOWED)
    accounts = FacebookAccountService(session)
    rows: list[tuple[User, bool]] = []
    for user in users:
        linked = await accounts.get_for_user(user.id) is not None
        rows.append((user, linked))
    return rows


async def _cancel_link(client: Bot, callback_query: CallbackQuery) -> None:
    """Disarm any in-flight link and return to the accounts overview."""
    client.fb_links.clear(client.settings.telegram.admin_id)
    async with client.database.session() as session:
        rows = await _accounts_overview(session)
    await edit_text(callback_query, ACCOUNTS_TITLE, reply_markup=accounts_menu(rows))
    await callback_query.answer(LINK_CANCELLED_TOAST)


async def _start_link(client: Bot, callback_query: CallbackQuery, target_id: int) -> None:
    """Validate the target is eligible, arm the link, and ask for the session file."""
    async with client.database.session() as session:
        target = await UserRepository(session).get_by_telegram_id(target_id)
    if target is None or not target.is_allowed:
        await callback_query.answer(TARGET_NOT_ELIGIBLE_TOAST, show_alert=True)
        return
    client.fb_links.begin(client.settings.telegram.admin_id, target_id)
    await edit_text(
        callback_query,
        ACCOUNT_LINK_PROMPT.format(name=html.escape(target.display_name)),
        reply_markup=account_link_cancel_menu(target_id),
    )
    await callback_query.answer()


async def _do_unlink(client: Bot, callback_query: CallbackQuery, target_id: int) -> None:
    """Remove the target's linked account and refresh the overview."""
    async with client.database.session() as session:
        target = await UserRepository(session).get_by_telegram_id(target_id)
        removed = await FacebookAccountService(session).unlink(target.id) if target else False
        rows = await _accounts_overview(session)
    if removed:
        log.info(LogEvent.FB_ACCOUNT_UNLINKED, telegram_id=target_id)
    await edit_text(callback_query, ACCOUNTS_TITLE, reply_markup=accounts_menu(rows))
    await callback_query.answer(UNLINKED_TOAST if removed else NOT_LINKED_TOAST)


async def _read_session_document(client: Bot, message: Message) -> bytes | None:
    """Validate size and download the uploaded document; reply on failure."""
    document = message.document
    if document is None:
        return None
    if document.file_size and document.file_size > SESSION_FILE_MAX_BYTES:
        await message.reply_text(SESSION_TOO_LARGE)
        return None
    raw = await _download_document(client, message)
    if raw is None:
        await message.reply_text(SESSION_DOWNLOAD_FAILED)
    return raw


async def _download_document(client: Bot, message: Message) -> bytes | None:
    """Download the message's document into memory and return its bytes."""
    in_memory: Literal[True] = True  # selects download_media's BinaryIO overload
    buffer = await client.download_media(message, in_memory=in_memory)
    if isinstance(buffer, list):
        return None
    buffer.seek(0)  # pyrogram leaves the cursor at EOF after writing the download
    return buffer.read()


async def _apply_capture(
    client: Bot, message: Message, target_id: int, captured: CapturedSession
) -> None:
    """Persist the captured session for the target user and confirm the link."""
    admin_id = client.settings.telegram.admin_id
    async with client.database.session() as session:
        target = await UserRepository(session).get_by_telegram_id(target_id)
        if target is None:
            client.fb_links.clear(admin_id)
            await message.reply_text(SESSION_TARGET_GONE)
            return
        try:
            await FacebookAccountService(session).link(
                target.id,
                captured.uid,
                access_token=captured.access_token,
                session_cookies=captured.session_cookies,
            )
        except FacebookAccountTakenError:
            client.fb_links.clear(admin_id)
            await message.reply_text(SESSION_ACCOUNT_TAKEN)
            return
        name = target.display_name
        rows = await _accounts_overview(session)
    client.fb_links.clear(admin_id)
    log.info(LogEvent.FB_ACCOUNT_LINKED, telegram_id=target_id, fb_uid=captured.uid)
    await message.reply_text(
        SESSION_LINKED.format(fb_uid=html.escape(captured.uid), name=html.escape(name)),
        reply_markup=accounts_menu(rows),
    )
