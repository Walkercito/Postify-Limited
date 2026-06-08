"""In-memory, per-user post drafts.

Composing a post spans several updates: the user sends the text, then one or
more photos, then confirms. We accumulate that draft keyed by Telegram user id
until it is published or cancelled. Like :class:`~bot.conversations.Conversation\
Store`, state is process-local and ephemeral — a restart forgets in-flight
drafts. The *presence* of a draft is what marks a user as "currently composing".

A draft also carries the *sticky composer* location (``chat_id`` / ``message_id``
of the single bot message edited in place as the user builds the post) and, once
publishing begins, a :class:`asyncio.Event` the *Cancelar publicación* button
sets to request a cooperative stop — its mere presence flips the draft from the
*composing* phase to the *publishing* phase.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class PostDraft:
    """A post being composed: its text, photos, sticky message, and run state."""

    text: str | None = None
    photo_file_ids: list[str] = field(default_factory=list)
    # The control-card bot message: re-floated below new inputs while composing,
    # then edited in place for the confirm screen and the live progress view.
    chat_id: int | None = None
    message_id: int | None = None
    # Set when a publish run starts; the cancel button sets the event. Presence
    # marks the draft as *publishing* (no longer accepting composition input).
    cancel_event: asyncio.Event | None = None
    # True while the composer awaits a typed blueprint name: the user's next text
    # message is read as that name, not as new post content.
    naming: bool = False
    # The debounced album-coalescing task. A media-group burst arrives as separate
    # messages, each (re)scheduling this so only the final item renders the card.
    # Excluded from repr/compare — a live Task is not meaningfully comparable.
    render_task: asyncio.Task[None] | None = field(default=None, repr=False, compare=False)

    @property
    def has_text(self) -> bool:
        """Whether a non-blank caption has been provided."""
        return bool(self.text and self.text.strip())

    @property
    def photo_count(self) -> int:
        """How many photos are attached."""
        return len(self.photo_file_ids)

    @property
    def is_empty(self) -> bool:
        """Whether nothing has been composed yet (no text and no photos)."""
        return not self.has_text and self.photo_count == 0

    @property
    def is_publishing(self) -> bool:
        """Whether a publish run is in flight (composition input is now ignored)."""
        return self.cancel_event is not None

    def bind_message(self, chat_id: int, message_id: int) -> None:
        """Record the sticky composer message this draft is rendered into."""
        self.chat_id = chat_id
        self.message_id = message_id

    def remove_photo(self, index: int) -> bool:
        """Drop the photo at *index* (0-based); return whether it was in range."""
        if 0 <= index < len(self.photo_file_ids):
            del self.photo_file_ids[index]
            return True
        return False

    def reset_content(self) -> None:
        """Clear the composed text and photos, keeping the sticky-message binding."""
        self.text = None
        self.photo_file_ids.clear()

    def begin_publishing(self) -> asyncio.Event:
        """Enter the publishing phase, returning the run's cancel event."""
        self.cancel_event = asyncio.Event()
        return self.cancel_event

    def cancel_render(self) -> None:
        """Cancel any pending debounced album-render task and forget it."""
        if self.render_task is not None and not self.render_task.done():
            self.render_task.cancel()
        self.render_task = None


class PostDraftStore:
    """Tracks each user's single in-flight post draft."""

    def __init__(self) -> None:
        self._drafts: dict[int, PostDraft] = {}

    def start(self, user_id: int) -> PostDraft:
        """Begin a fresh draft for *user_id*, discarding any previous one."""
        draft = PostDraft()
        self._drafts[user_id] = draft
        return draft

    def get(self, user_id: int) -> PostDraft | None:
        """Return *user_id*'s draft, or ``None`` if they aren't composing."""
        return self._drafts.get(user_id)

    def is_active(self, user_id: int) -> bool:
        """Whether *user_id* currently has a post draft in progress."""
        return user_id in self._drafts

    def clear(self, user_id: int) -> None:
        """Forget *user_id*'s draft (on publish or cancel)."""
        self._drafts.pop(user_id, None)
