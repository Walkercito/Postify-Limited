"""Resilient inline-message edits.

Telegram raises ``MESSAGE_NOT_MODIFIED`` when an edit would leave a message
byte-for-byte identical. For our re-renders that is a benign no-op (the message
already shows the desired state), so these helpers swallow it instead of letting
it surface as a handler error.

:func:`edit_text` / :func:`edit_markup` edit the message a :class:`CallbackQuery`
rode in on; :func:`edit_message` edits a message addressed by ``chat_id`` /
``message_id`` directly — used to update the sticky composer from plain message
handlers and the publish loop, which hold no callback query.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from pyrogram.errors import MessageNotModified

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.enums import ParseMode
    from pyrogram.types import CallbackQuery, InlineKeyboardMarkup


async def edit_text(
    callback_query: CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: ParseMode | None = None,
) -> None:
    """Edit the callback message's text, ignoring an identical-content no-op."""
    extra: dict[str, Any] = {}
    if reply_markup is not None:
        extra["reply_markup"] = reply_markup
    if parse_mode is not None:
        extra["parse_mode"] = parse_mode
    with contextlib.suppress(MessageNotModified):
        await callback_query.edit_message_text(text, **extra)


async def edit_markup(callback_query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
    """Replace the callback message's inline keyboard, ignoring a no-op edit."""
    with contextlib.suppress(MessageNotModified):
        await callback_query.edit_message_reply_markup(reply_markup)


async def edit_message(
    client: Client,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: ParseMode | None = None,
) -> None:
    """Edit a message by ``chat_id`` / ``message_id``, ignoring a no-op edit."""
    extra: dict[str, Any] = {}
    if reply_markup is not None:
        extra["reply_markup"] = reply_markup
    if parse_mode is not None:
        extra["parse_mode"] = parse_mode
    with contextlib.suppress(MessageNotModified):
        await client.edit_message_text(chat_id, message_id, text, **extra)
