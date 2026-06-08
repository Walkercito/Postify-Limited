"""Handler registration entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.handlers.access import AccessRouter
from bot.handlers.accounts import AccountsRouter
from bot.handlers.base import Router
from bot.handlers.blueprints import BlueprintsRouter
from bot.handlers.commands import CommandRouter
from bot.handlers.groups import GroupsRouter
from bot.handlers.menu import MenuRouter
from bot.handlers.post import PostRouter

if TYPE_CHECKING:
    from bot.core.client import Bot

# Every router the application exposes. Add new routers here (DRY registration).
# PostRouter and BlueprintsRouter precede GroupsRouter so their state-gated
# text/photo handlers (composing a post, editing a blueprint) claim those updates
# first; GroupsRouter is last so its always-on link shortcut only sees messages no
# other router claims.
ROUTERS: tuple[Router, ...] = (
    CommandRouter(),
    MenuRouter(),
    AccessRouter(),
    AccountsRouter(),
    PostRouter(),
    BlueprintsRouter(),
    GroupsRouter(),
)


def register_routers(bot: Bot) -> None:
    """Register every router's handlers on *bot*."""
    for router in ROUTERS:
        router.register(bot)
