"""FacebookAccount ORM model: a user's stored Facebook session.

Each bot user may have at most one linked Facebook account, whose session is
provided by the admin. Posting is driven by *one of two* credentials: a Graph
:attr:`access_token` (the ``fb_unofficial`` engine) or a browser cookie jar in
:attr:`session_cookies` (the cookie-native ``bot.facebook_web`` engine). Both are
nullable; the link flow enforces that at least one is present. :attr:`fb_uid`
identifies the account for display.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.constants import FB_ACCESS_TOKEN_MAX_LENGTH, FB_UID_MAX_LENGTH
from bot.db.base import Base, TimestampMixin
from bot.db.models.user import User


class FacebookAccount(Base, TimestampMixin):
    """The Facebook session linked to a single bot user.

    ``user_id`` is unique: one linked account per bot user. The row is created
    and updated by the admin provisioning flow; the posting flow reads it to
    obtain whichever credential is stored — an ``access_token`` or a JSON-encoded
    ``session_cookies`` jar.
    """

    __tablename__ = "facebook_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{User.__tablename__}.id", ondelete="CASCADE"), unique=True, index=True
    )
    fb_uid: Mapped[str] = mapped_column(String(FB_UID_MAX_LENGTH), index=True)
    access_token: Mapped[str | None] = mapped_column(
        String(FB_ACCESS_TOKEN_MAX_LENGTH), nullable=True
    )
    # Cookie jars are larger than tokens and unbounded in practice, so Text.
    session_cookies: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"FacebookAccount(id={self.id!r}, user_id={self.user_id!r}, fb_uid={self.fb_uid!r})"
