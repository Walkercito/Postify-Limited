"""Abstract base class for handler routers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, cast

from pyrogram.handlers import CallbackQueryHandler as PyrogramCallbackQueryHandler
from pyrogram.handlers import MessageHandler as PyrogramMessageHandler

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram import Client
    from pyrogram.filters import Filter
    from pyrogram.types import CallbackQuery, Message

    from bot.core.client import Bot
    from bot.handlers.middleware import Handler

    PyrogramMessageCallback = Callable[[Client, Message], Any]
    PyrogramCallbackQueryCallback = Callable[[Client, CallbackQuery], Any]


class Router(ABC):
    """Groups related handlers and registers them on the bot client."""

    @abstractmethod
    def register(self, bot: Bot) -> None:
        """Attach this router's handlers to *bot*."""
        raise NotImplementedError

    @staticmethod
    def _add_message_handler(
        bot: Bot,
        callback: Handler[Message],
        filter_: Filter,
        group: int,
    ) -> None:
        """Register a :class:`Bot`-typed message handler on *bot*.

        Pyrogram types its callback against the base :class:`~pyrogram.Client`;
        our handlers are typed against the :class:`Bot` subclass for ergonomic
        access to shared services. The single, safe bridge between the two lives
        here (DRY) instead of being repeated at every call site.
        """
        bot.add_handler(
            PyrogramMessageHandler(cast("PyrogramMessageCallback", callback), filter_),
            group=group,
        )

    @staticmethod
    def _add_callback_query_handler(
        bot: Bot,
        callback: Handler[CallbackQuery],
        filter_: Filter,
        group: int,
    ) -> None:
        """Register a :class:`Bot`-typed callback-query handler on *bot*.

        The :class:`Bot`-vs-:class:`~pyrogram.Client` bridge mirrors
        :meth:`_add_message_handler`; see its docstring.
        """
        bot.add_handler(
            PyrogramCallbackQueryHandler(cast("PyrogramCallbackQueryCallback", callback), filter_),
            group=group,
        )
