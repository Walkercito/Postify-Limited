"""Business logic for a user's saved posts (blueprints)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import (
    BLUEPRINT_LIST_DEFAULT_LIMIT,
    BLUEPRINT_SLUG_FALLBACK,
    BLUEPRINT_SLUG_FIRST_SUFFIX,
    BLUEPRINT_SLUG_MAX_LENGTH,
    BLUEPRINT_SLUG_SEPARATOR,
    BLUEPRINT_SLUG_STRIP_PATTERN,
    UNICODE_NONSPACING_MARK,
)
from bot.db.models.blueprint import Blueprint
from bot.repositories.blueprint import BlueprintRepository

_SLUG_STRIP = re.compile(BLUEPRINT_SLUG_STRIP_PATTERN)


def _slugify(name: str) -> str:
    """Derive a URL-safe handle from a human name.

    Folds accents (NFD then drops combining marks), lowercases, collapses every
    run of characters outside ``[a-z0-9]`` to the separator, and trims separators
    off the ends. An empty result (e.g. an emoji-only name) falls back to a fixed
    stem so a slug is always produced.
    """
    decomposed = unicodedata.normalize("NFD", name.lower())
    folded = "".join(
        char for char in decomposed if unicodedata.category(char) != UNICODE_NONSPACING_MARK
    )
    slug = _SLUG_STRIP.sub(BLUEPRINT_SLUG_SEPARATOR, folded).strip(BLUEPRINT_SLUG_SEPARATOR)
    slug = slug[:BLUEPRINT_SLUG_MAX_LENGTH].strip(BLUEPRINT_SLUG_SEPARATOR)
    return slug or BLUEPRINT_SLUG_FALLBACK


class BlueprintService:
    """Coordinates blueprint persistence on top of :class:`BlueprintRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._blueprints = BlueprintRepository(session)

    async def _unique_slug(self, user_id: int, name: str, *, exclude_id: int | None = None) -> str:
        """A slug for *name* that is unique among the user's blueprints.

        Starts from :func:`_slugify` and, on collision, appends an incrementing
        ``-<n>`` suffix. A blueprint matching *exclude_id* is ignored (so renaming
        a blueprint to its own current name keeps its slug).
        """
        base = _slugify(name)
        candidate = base
        suffix = BLUEPRINT_SLUG_FIRST_SUFFIX
        while True:
            existing = await self._blueprints.get_by_slug(user_id, candidate)
            if existing is None or existing.id == exclude_id:
                return candidate
            candidate = f"{base}{BLUEPRINT_SLUG_SEPARATOR}{suffix}"
            suffix += 1

    async def create(
        self,
        user_id: int,
        name: str,
        *,
        text: str | None = None,
        photo_file_ids: Sequence[str] | None = None,
    ) -> Blueprint:
        """Save a new blueprint for the user with a per-user-unique slug."""
        slug = await self._unique_slug(user_id, name)
        blueprint = Blueprint(
            user_id=user_id,
            name=name,
            slug=slug,
            text=text,
            photo_file_ids=list(photo_file_ids or []),
        )
        await self._blueprints.add(blueprint)
        return blueprint

    async def find_by_id(self, user_id: int, blueprint_id: int) -> Blueprint | None:
        """Return one of the user's blueprints by internal id, or ``None``.

        ``None`` if it doesn't exist or belongs to someone else, so a stale
        button can never reach another user's blueprint.
        """
        blueprint = await self._blueprints.get(blueprint_id)
        if blueprint is None or blueprint.user_id != user_id:
            return None
        return blueprint

    async def rename(self, blueprint: Blueprint, name: str) -> Blueprint:
        """Change a blueprint's name and re-derive its (still unique) slug."""
        blueprint.name = name
        blueprint.slug = await self._unique_slug(blueprint.user_id, name, exclude_id=blueprint.id)
        return await self._blueprints.add(blueprint)

    async def set_text(self, blueprint: Blueprint, text: str | None) -> Blueprint:
        """Replace a blueprint's post body."""
        blueprint.text = text
        return await self._blueprints.add(blueprint)

    async def remove_by_id(self, user_id: int, blueprint_id: int) -> Blueprint | None:
        """Delete one of the user's blueprints by internal id.

        Returns the removed blueprint, or ``None`` if it doesn't exist or belongs
        to someone else (so a stale button can't delete another user's blueprint).
        """
        blueprint = await self.find_by_id(user_id, blueprint_id)
        if blueprint is None:
            return None
        await self._blueprints.delete(blueprint)
        return blueprint

    async def list_for_user(
        self, user_id: int, *, limit: int = BLUEPRINT_LIST_DEFAULT_LIMIT
    ) -> Sequence[Blueprint]:
        """List the user's saved blueprints (capped at *limit*)."""
        return await self._blueprints.list_for_user(user_id, limit=limit)

    async def count_for_user(self, user_id: int) -> int:
        """How many blueprints the user has saved."""
        return await self._blueprints.count_for_user(user_id)
