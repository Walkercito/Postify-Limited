"""In-memory, per-user pending blueprint edits.

Renaming a blueprint or editing its text spans two updates: the user taps
*Renombrar* / *Editar texto* (arming an edit), then types the new value as a
free-text reply. We remember which blueprint and which field the next message
updates, keyed by the user's Telegram id, plus the card to refresh afterwards.
Like the other in-memory stores, state is process-local and ephemeral — a
restart simply forgets any in-flight edit.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.constants import BlueprintField


@dataclass(slots=True)
class PendingBlueprintEdit:
    """A blueprint field edit awaiting the user's next text message.

    ``chat_id`` / ``message_id`` locate the detail card to re-render once the new
    value is applied.
    """

    blueprint_id: int
    field: BlueprintField
    chat_id: int
    message_id: int


class BlueprintEditStore:
    """Tracks each user's single in-flight blueprint edit (rename / edit-text)."""

    def __init__(self) -> None:
        self._pending: dict[int, PendingBlueprintEdit] = {}

    def begin(self, user_id: int, edit: PendingBlueprintEdit) -> None:
        """Record that *user_id* is now editing a blueprint field."""
        self._pending[user_id] = edit

    def get(self, user_id: int) -> PendingBlueprintEdit | None:
        """Return the user's in-flight blueprint edit, or ``None``."""
        return self._pending.get(user_id)

    def clear(self, user_id: int) -> None:
        """Forget any in-flight blueprint edit for *user_id* (on apply or cancel)."""
        self._pending.pop(user_id, None)
