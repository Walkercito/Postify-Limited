"""Blueprint ORM model: a saved post a user can publish later.

A blueprint captures the *content* of a post — its text and/or its photos — under
a human-readable :attr:`name` and a derived, per-user-unique :attr:`slug`. Photos
are stored as Telegram ``file_id`` strings (re-downloadable / re-sendable even
after the source message is gone), not copied to disk.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from bot.constants import BLUEPRINT_NAME_MAX_LENGTH, BLUEPRINT_SLUG_MAX_LENGTH
from bot.db.base import Base, TimestampMixin
from bot.db.models.user import User


class Blueprint(Base, TimestampMixin):
    """A reusable saved post on a single user's list.

    Each user keeps an independent set of blueprints, so ``(user_id, slug)`` is
    unique rather than ``slug`` alone. ``text`` is the (optional) post body;
    ``photo_file_ids`` is the ordered list of Telegram photo ``file_id``s — at
    least one of the two is non-empty by construction of the save flow.
    """

    __tablename__ = "blueprints"
    __table_args__ = (UniqueConstraint("user_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{User.__tablename__}.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(BLUEPRINT_NAME_MAX_LENGTH))
    slug: Mapped[str] = mapped_column(String(BLUEPRINT_SLUG_MAX_LENGTH), index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reassigned as a whole list (no in-place mutation), so plain JSON is enough.
    photo_file_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    def __repr__(self) -> str:
        return f"Blueprint(id={self.id!r}, user_id={self.user_id!r}, slug={self.slug!r})"
