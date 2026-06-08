"""In-memory, per-user fuzzy-search result sets.

Searching groups spans two updates: the user taps *Buscar* and replies with a
term, then pages through / acts on the ranked matches. We keep that result set
keyed by Telegram user id — like :class:`~bot.post_drafts.PostDraftStore`, state
is process-local and ephemeral (a restart forgets in-flight searches).

The ranked hits live here (not in callback data) so pagination and quick-delete
only carry a page number / group id; the heavy list stays server-side. Deleting
a group from a result row mutates the stored hits in place so the re-render stays
consistent without re-running the query.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GroupHit:
    """One ranked search match: enough to render a link row and quick-delete it."""

    id: int
    facebook_id: str
    name: str | None


@dataclass(slots=True)
class GroupSearchPage:
    """A clamped slice of a search's hits, plus the geometry to render nav arrows."""

    hits: list[GroupHit]
    page: int
    total_pages: int
    total: int

    @property
    def has_prev(self) -> bool:
        """Whether an earlier page exists."""
        return self.page > 0

    @property
    def has_next(self) -> bool:
        """Whether a later page exists."""
        return self.page < self.total_pages - 1


@dataclass(slots=True)
class GroupSearch:
    """A user's current ranked result set and which page they're viewing."""

    query: str
    hits: list[GroupHit]
    page: int = 0

    def go_to(self, page: int) -> None:
        """Move to *page* (clamping happens lazily in :meth:`window`)."""
        self.page = page

    def remove(self, group_id: int) -> None:
        """Drop a group from the results (after a quick-delete)."""
        self.hits = [hit for hit in self.hits if hit.id != group_id]

    def window(self, page_size: int) -> GroupSearchPage:
        """Clamp the current page to the (possibly shrunk) hits and slice it."""
        total = len(self.hits)
        total_pages = max(1, -(-total // page_size))  # ceil division
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * page_size
        return GroupSearchPage(
            hits=self.hits[start : start + page_size],
            page=self.page,
            total_pages=total_pages,
            total=total,
        )


class GroupSearchStore:
    """Tracks each user's single in-flight search result set."""

    def __init__(self) -> None:
        self._searches: dict[int, GroupSearch] = {}

    def put(self, user_id: int, query: str, hits: list[GroupHit]) -> GroupSearch:
        """Store a fresh result set for *user_id*, replacing any previous one."""
        search = GroupSearch(query=query, hits=hits)
        self._searches[user_id] = search
        return search

    def get(self, user_id: int) -> GroupSearch | None:
        """Return *user_id*'s active search, or ``None`` if none is open."""
        return self._searches.get(user_id)

    def clear(self, user_id: int) -> None:
        """Forget *user_id*'s search results."""
        self._searches.pop(user_id, None)
