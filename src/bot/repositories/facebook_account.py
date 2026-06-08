"""Repository for :class:`~bot.db.models.facebook_account.FacebookAccount` rows."""

from __future__ import annotations

from sqlalchemy import select

from bot.db.models.facebook_account import FacebookAccount
from bot.repositories.base import BaseRepository


class FacebookAccountRepository(BaseRepository[FacebookAccount]):
    """Persistence and queries for users' linked Facebook accounts."""

    model = FacebookAccount

    async def get_for_user(self, user_id: int) -> FacebookAccount | None:
        """Return the Facebook account linked to *user_id*, if any."""
        stmt = select(FacebookAccount).where(FacebookAccount.user_id == user_id)
        return await self.session.scalar(stmt)

    async def get_by_fb_uid(self, fb_uid: str) -> FacebookAccount | None:
        """Return the account holding *fb_uid*, if any (to detect duplicates)."""
        stmt = select(FacebookAccount).where(FacebookAccount.fb_uid == fb_uid)
        return await self.session.scalar(stmt)
