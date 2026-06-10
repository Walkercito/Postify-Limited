"""Repository for :class:`~bot.db.models.account_post_limit.AccountPostLimit` rows."""

from __future__ import annotations

from sqlalchemy import select

from bot.db.models.account_post_limit import AccountPostLimit
from bot.repositories.base import BaseRepository


class AccountPostLimitRepository(BaseRepository[AccountPostLimit]):
    """Persistence and queries for per-account publish-guard state."""

    model = AccountPostLimit

    async def get_by_fb_uid(self, fb_uid: str) -> AccountPostLimit | None:
        """Return the guard-state row for *fb_uid*, if one exists yet."""
        stmt = select(AccountPostLimit).where(AccountPostLimit.fb_uid == fb_uid)
        return await self.session.scalar(stmt)
