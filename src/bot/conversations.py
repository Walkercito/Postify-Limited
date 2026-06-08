"""In-memory, per-user conversation state.

Some interactions span two updates: the user taps a button, then sends a
follow-up text (e.g. *Add a group* → paste a link). We remember the pending
:class:`~bot.constants.ConversationState` keyed by Telegram user id so the next
free-text message is routed to the right operation. State is process-local and
intentionally ephemeral — a restart simply forgets in-flight prompts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.constants import ConversationState


class ConversationStore:
    """Tracks each user's single in-flight conversation step."""

    def __init__(self) -> None:
        self._pending: dict[int, ConversationState] = {}

    def begin(self, user_id: int, state: ConversationState) -> None:
        """Record that *user_id* is now expected to send a follow-up message."""
        self._pending[user_id] = state

    def pop(self, user_id: int) -> ConversationState | None:
        """Consume and return *user_id*'s pending state, or ``None`` if idle."""
        return self._pending.pop(user_id, None)

    def clear(self, user_id: int) -> None:
        """Forget any pending state for *user_id* (e.g. on cancel)."""
        self._pending.pop(user_id, None)
