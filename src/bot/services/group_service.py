"""Business logic for a user's saved Facebook groups."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from rapidfuzz import fuzz, process
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import (
    GROUP_LIST_DEFAULT_LIMIT,
    GROUP_SEARCH_MAX_RESULTS,
    GROUP_SEARCH_SCAN_LIMIT,
    GROUP_SEARCH_SCORE_CUTOFF,
    UNICODE_NONSPACING_MARK,
)
from bot.db.models.group import Group
from bot.repositories.group import GroupRepository


def _fold(text: str) -> str:
    """Normalize for fuzzy matching: lowercase, strip accents, collapse whitespace.

    Decomposes to NFD and drops the combining marks so ``Rodás`` and ``rodas``
    compare equal; used as rapidfuzz's processor so both query and choices fold
    the same way.
    """
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(
        char for char in decomposed if unicodedata.category(char) != UNICODE_NONSPACING_MARK
    )
    return " ".join(stripped.split())


class GroupService:
    """Coordinates group persistence on top of :class:`GroupRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._groups = GroupRepository(session)

    async def add(self, user_id: int, facebook_id: str) -> tuple[Group, bool]:
        """Save a group for the user.

        Idempotent per user: returns ``(existing, False)`` if the user already
        has this group, otherwise creates it and returns ``(group, True)``.
        """
        existing = await self._groups.get_for_user(user_id, facebook_id)
        if existing is not None:
            return existing, False
        group = Group(user_id=user_id, facebook_id=facebook_id)
        await self._groups.add(group)
        return group, True

    async def find(self, user_id: int, facebook_id: str) -> Group | None:
        """Return the user's group with this ``facebook_id``, if saved."""
        return await self._groups.get_for_user(user_id, facebook_id)

    async def set_name(self, group: Group, name: str) -> Group:
        """Set a saved group's display name (e.g. from a public preview)."""
        group.name = name
        return await self._groups.add(group)

    async def find_by_id(self, user_id: int, group_id: int) -> Group | None:
        """Return one of the user's groups by internal id, or ``None``.

        ``None`` if it doesn't exist or belongs to someone else, so a stale
        button can never reach another user's group.
        """
        group = await self._groups.get(group_id)
        if group is None or group.user_id != user_id:
            return None
        return group

    async def remove_by_id(self, user_id: int, group_id: int) -> Group | None:
        """Delete one of the user's groups by internal id.

        Returns the removed group, or ``None`` if it doesn't exist or belongs to
        someone else (so a stale button can't delete another user's group).
        """
        group = await self.find_by_id(user_id, group_id)
        if group is None:
            return None
        await self._groups.delete(group)
        return group

    async def list_for_user(
        self, user_id: int, *, limit: int = GROUP_LIST_DEFAULT_LIMIT
    ) -> Sequence[Group]:
        """List the user's saved groups (capped at *limit*)."""
        return await self._groups.list_for_user(user_id, limit=limit)

    async def count_for_user(self, user_id: int) -> int:
        """How many groups the user has saved."""
        return await self._groups.count_for_user(user_id)

    async def search(
        self,
        user_id: int,
        query: str,
        *,
        limit: int = GROUP_SEARCH_MAX_RESULTS,
        score_cutoff: int = GROUP_SEARCH_SCORE_CUTOFF,
    ) -> Sequence[Group]:
        """Rank the user's groups by fuzzy similarity to *query*, best first.

        Tolerates typos and accents: each group's display name (or its id when
        unnamed) is scored against *query* with rapidfuzz's weighted ratio after
        both are folded by :func:`_fold`. A blank query — or one matching nothing
        above *score_cutoff* — yields no results.
        """
        if not _fold(query):
            return []
        candidates = await self._groups.list_for_user(user_id, limit=GROUP_SEARCH_SCAN_LIMIT)
        if not candidates:
            return []
        haystack = [group.name or group.facebook_id for group in candidates]
        matches = process.extract(
            query,
            haystack,
            scorer=fuzz.WRatio,
            processor=_fold,
            limit=limit,
            score_cutoff=score_cutoff,
        )
        return [candidates[index] for _choice, _score, index in matches]
