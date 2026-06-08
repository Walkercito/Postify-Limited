"""In-memory, per-user paginator for a finished publish run's per-group results.

When a post fans out to many groups (80+ is common), the terminal summary cannot
fit every per-group line in one Telegram message, so the user pages through it.
We keep that finished result set keyed by Telegram user id — like
:class:`~bot.group_search.GroupSearchStore`, the state is process-local and
ephemeral (a restart forgets the last summary).

The set is stored as a pre-rendered ``header`` plus one pre-rendered ``line`` per
group, so this module stays a pure line paginator with no knowledge of the post
service's result dataclass or of HTML rendering (those live in the post handler);
pagination only ever carries a page number, never the heavy list.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PostResultPage:
    """A clamped slice of a result set's lines, plus the geometry to render arrows."""

    lines: list[str]
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
class PostResultSet:
    """A finished run's rendered summary: a header line and one line per group."""

    header: str
    lines: list[str]
    page: int = 0

    def go_to(self, page: int) -> None:
        """Move to *page* (clamping happens lazily in :meth:`window`)."""
        self.page = page

    def window(self, page_size: int) -> PostResultPage:
        """Clamp the current page to the line count and slice it."""
        total = len(self.lines)
        total_pages = max(1, -(-total // page_size))  # ceil division
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * page_size
        return PostResultPage(
            lines=self.lines[start : start + page_size],
            page=self.page,
            total_pages=total_pages,
            total=total,
        )


class PostResultStore:
    """Tracks each user's most recent finished publish-result summary."""

    def __init__(self) -> None:
        self._sets: dict[int, PostResultSet] = {}

    def put(self, user_id: int, header: str, lines: list[str]) -> PostResultSet:
        """Store a fresh result summary for *user_id*, replacing any previous one."""
        result_set = PostResultSet(header=header, lines=lines)
        self._sets[user_id] = result_set
        return result_set

    def get(self, user_id: int) -> PostResultSet | None:
        """Return *user_id*'s last result summary, or ``None`` if none is open."""
        return self._sets.get(user_id)

    def clear(self, user_id: int) -> None:
        """Forget *user_id*'s result summary."""
        self._sets.pop(user_id, None)
