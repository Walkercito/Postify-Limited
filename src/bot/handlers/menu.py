"""Callback-query handlers for the inline main menu.

Hosts the cross-cutting *⬅️ Volver* button (``MenuAction.MAIN``), which every
submenu uses to return here. It is ``observed`` (one wide event per tap) and
``tracks_activity`` like any other handler. The per-feature buttons live in their
own routers (see :class:`~bot.handlers.post.PostRouter`,
:class:`~bot.handlers.blueprints.BlueprintsRouter`, ``GroupsRouter``,
``AccountsRouter``, ``AccessRouter``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyrogram import filters

from bot.constants import HandlerGroup, MenuAction, Role
from bot.handlers.base import Router
from bot.handlers.edits import edit_text
from bot.handlers.guards import is_admin
from bot.handlers.middleware import observed, tracks_activity
from bot.keyboards import main_menu

if TYPE_CHECKING:
    from pyrogram.types import CallbackQuery

    from bot.core.client import Bot

MENU_HOME = "🏠 <b>Menú principal</b>\nElige una opción:"


class MenuRouter(Router):
    """Registers the main-menu *Volver* button (``MenuAction.MAIN``)."""

    def register(self, bot: Bot) -> None:
        self._add_callback_query_handler(
            bot, self._on_main, filters.regex(rf"^{MenuAction.MAIN}$"), HandlerGroup.DEFAULT
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_main(client: Bot, callback_query: CallbackQuery) -> None:
        role = Role.ADMIN if is_admin(client, callback_query.from_user) else Role.USER
        await edit_text(callback_query, MENU_HOME, reply_markup=main_menu(role))
        await callback_query.answer()
