"""Per-update cross-cutting concerns: observability, error capture, activity.

``observed`` emits exactly one rich, structured "wide event" per update — with
per-update context bound via ``contextvars`` and the outcome + duration recorded
— and reports any unexpected error (with traceback) to the admin.

``tracks_activity`` records the user's "last online" time after each update.

The two are composable, single-responsibility decorators; stack them on a
handler (``observed`` outermost) as needed.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol

import structlog
from pyrogram.types import CallbackQuery, Message

from bot.constants import LogEvent, Outcome, UpdateType
from bot.core.logging import get_logger
from bot.db.base import utcnow
from bot.repositories.user import UserRepository

if TYPE_CHECKING:
    from bot.core.client import Bot

log = get_logger(__name__)

# Both update kinds expose ``id`` and ``from_user``; the decorators only ever
# touch that common surface, so they are generic over exactly these two.
type Update = Message | CallbackQuery


class Handler[UpdateT: (Message, CallbackQuery)](Protocol):
    """A Pyrogram handler bound to our :class:`Bot` client.

    Modelled as a ``Protocol`` (rather than a bare ``Callable`` alias) so the
    decorators can read each handler's ``__name__`` for the wide event, and
    generic over the update type so a message handler stays distinct from a
    callback-query handler.
    """

    __name__: str

    def __call__(self, client: Bot, update: UpdateT, /) -> Awaitable[None]: ...


_MS_PER_SECOND = 1000
_DURATION_PRECISION = 2


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * _MS_PER_SECOND, _DURATION_PRECISION)


def _update_context(handler_name: str, update: Update) -> dict[str, object]:
    user = update.from_user
    context: dict[str, object] = {
        "handler": handler_name,
        "user_id": user.id if user else None,
    }
    if isinstance(update, CallbackQuery):
        message = update.message
        context["update_type"] = UpdateType.CALLBACK_QUERY
        context["callback_data"] = update.data
        context["chat_id"] = message.chat.id if message and message.chat else None
    else:
        context["update_type"] = UpdateType.MESSAGE
        context["message_id"] = update.id
        context["chat_id"] = update.chat.id if update.chat else None
    return context


def observed[UpdateT: (Message, CallbackQuery)](handler: Handler[UpdateT]) -> Handler[UpdateT]:
    """Decorate a handler to emit one canonical log event per update."""

    @functools.wraps(handler)
    async def wrapper(client: Bot, update: UpdateT) -> None:
        context = _update_context(handler.__name__, update)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**context)
        start = time.perf_counter()
        try:
            await handler(client, update)
        except Exception as exc:
            log.error(
                LogEvent.UPDATE_HANDLED,
                outcome=Outcome.ERROR,
                duration_ms=_elapsed_ms(start),
                exc_info=exc,
            )
            await client.error_reporter.report(exc, context=context)
        else:
            log.info(
                LogEvent.UPDATE_HANDLED,
                outcome=Outcome.SUCCESS,
                duration_ms=_elapsed_ms(start),
            )
        finally:
            structlog.contextvars.clear_contextvars()

    return wrapper


def tracks_activity[UpdateT: (Message, CallbackQuery)](
    handler: Handler[UpdateT],
) -> Handler[UpdateT]:
    """Decorate a handler to update the user's ``last_seen_at`` after it runs."""

    @functools.wraps(handler)
    async def wrapper(client: Bot, update: UpdateT) -> None:
        await handler(client, update)
        user = update.from_user
        if user is None:
            return
        try:
            async with client.database.session() as session:
                await UserRepository(session).touch_last_seen(user.id, when=utcnow())
        except Exception:
            log.exception(LogEvent.ACTIVITY_UPDATE_FAILED)

    return wrapper
