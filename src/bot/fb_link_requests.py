"""In-memory, per-admin Facebook-link requests.

Linking a Facebook account spans two updates: the admin taps *Link* for a user
(arming a request), then uploads the captured ``session.json`` as a document.
We remember which user the admin is provisioning, keyed by the admin's Telegram
id, so the next uploaded document is applied to the right target. Like
:class:`~bot.conversations.ConversationStore`, state is process-local and
ephemeral — a restart simply forgets any in-flight link.
"""

from __future__ import annotations


class FacebookLinkStore:
    """Tracks each admin's single in-flight account-link target."""

    def __init__(self) -> None:
        self._targets: dict[int, int] = {}

    def begin(self, admin_id: int, target_telegram_id: int) -> None:
        """Record that *admin_id* is now provisioning *target_telegram_id*."""
        self._targets[admin_id] = target_telegram_id

    def get(self, admin_id: int) -> int | None:
        """Return the target Telegram id *admin_id* is provisioning, or ``None``."""
        return self._targets.get(admin_id)

    def clear(self, admin_id: int) -> None:
        """Forget any in-flight link for *admin_id* (on apply or cancel)."""
        self._targets.pop(admin_id, None)
