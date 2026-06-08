"""Group ORM model: a Facebook group saved to a user's personal list."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.constants import GROUP_FB_ID_MAX_LENGTH, GROUP_NAME_MAX_LENGTH
from bot.db.base import Base, TimestampMixin
from bot.db.models.user import User


class Group(Base, TimestampMixin):
    """A Facebook group on a single user's list.

    Identified internally by ``id`` (for quick lookups from callback data) and
    by ``facebook_id`` — the numeric id or vanity slug parsed from a group URL.
    Each user keeps an independent list, so ``(user_id, facebook_id)`` is unique
    rather than ``facebook_id`` alone.
    """

    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("user_id", "facebook_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{User.__tablename__}.id", ondelete="CASCADE"), index=True
    )
    facebook_id: Mapped[str] = mapped_column(String(GROUP_FB_ID_MAX_LENGTH), index=True)
    name: Mapped[str | None] = mapped_column(String(GROUP_NAME_MAX_LENGTH), default=None)

    def __repr__(self) -> str:
        return f"Group(id={self.id!r}, user_id={self.user_id!r}, facebook_id={self.facebook_id!r})"
