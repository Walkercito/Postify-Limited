"""Error reporting: deliver unexpected failures to the admin via Telegram."""

from __future__ import annotations

import html
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pyrogram.enums import ParseMode

from bot.constants import ERROR_REPORT_TRACEBACK_LIMIT, LogEvent
from bot.core.logging import get_logger

if TYPE_CHECKING:
    from pyrogram import Client

log = get_logger(__name__)

_TRUNCATION_MARKER = "...\n"
_EMPTY_PLACEHOLDER = "—"


class ErrorReporter:
    """Formats unexpected errors and sends them to the admin chat.

    Reporting is best-effort: a failure to deliver the report is logged but
    never propagated, so it can never mask the original error.
    """

    def __init__(self, client: Client, admin_id: int) -> None:
        self._client = client
        self._admin_id = admin_id

    async def report(
        self,
        error: BaseException,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        """Format an unexpected error (with traceback) and send it to the admin."""
        await self.deliver(self._format(error, context or {}))

    async def deliver(self, text: str) -> None:
        """Send a pre-formatted HTML alert to the admin (best-effort).

        For *expected* conditions worth surfacing to the admin (e.g. a per-group
        post failure) where a traceback would add no signal — the caller composes
        the message. Like :meth:`report`, a delivery failure is logged, not raised.
        """
        try:
            await self._client.send_message(
                chat_id=self._admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception(LogEvent.ERROR_REPORT_FAILED)

    @staticmethod
    def _format(error: BaseException, context: dict[str, object]) -> str:
        now = datetime.now(UTC).isoformat()
        lines = [
            "🚨 <b>Bot error</b>",
            f"<b>time:</b> {html.escape(now)}",
            f"<b>type:</b> {html.escape(type(error).__name__)}",
            f"<b>message:</b> {html.escape(str(error)) or _EMPTY_PLACEHOLDER}",
        ]
        lines.extend(
            f"<b>{html.escape(str(key))}:</b> {html.escape(str(value))}"
            for key, value in context.items()
        )
        header = "\n".join(lines)

        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if len(trace) > ERROR_REPORT_TRACEBACK_LIMIT:
            trace = _TRUNCATION_MARKER + trace[-ERROR_REPORT_TRACEBACK_LIMIT:]

        return f"{header}\n<pre>{html.escape(trace)}</pre>"
