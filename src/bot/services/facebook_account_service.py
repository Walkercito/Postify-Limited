"""Business logic for users' linked Facebook accounts (sessions)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.exceptions import FacebookAccountTakenError
from bot.db.models.facebook_account import FacebookAccount
from bot.facebook_web import encode_cookies
from bot.repositories.facebook_account import FacebookAccountRepository


class FacebookAccountService:
    """Coordinates account persistence on top of :class:`FacebookAccountRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._accounts = FacebookAccountRepository(session)

    async def get_for_user(self, user_id: int) -> FacebookAccount | None:
        """Return the Facebook account linked to *user_id*, or ``None``."""
        return await self._accounts.get_for_user(user_id)

    async def link(
        self,
        user_id: int,
        fb_uid: str,
        *,
        access_token: str | None = None,
        session_cookies: dict[str, str] | None = None,
    ) -> FacebookAccount:
        """Link (or relink) a Facebook session to *user_id*.

        Upsert: one account per user. Re-linking overwrites the stored ``fb_uid``
        and *both* credentials in place (so switching engines clears the old one)
        rather than creating a second row. Requires at least one credential — an
        ``access_token`` or a ``session_cookies`` jar (stored JSON-encoded).
        Raises :class:`FacebookAccountTakenError` if *fb_uid* is already linked to
        a different user (one Facebook account can't back two bot users).
        """
        if not access_token and not session_cookies:
            raise ValueError("a Facebook account needs an access token or session cookies")
        conflict = await self._accounts.get_by_fb_uid(fb_uid)
        if conflict is not None and conflict.user_id != user_id:
            raise FacebookAccountTakenError(fb_uid)
        encoded_cookies = encode_cookies(session_cookies)
        existing = await self._accounts.get_for_user(user_id)
        if existing is not None:
            existing.fb_uid = fb_uid
            existing.access_token = access_token
            existing.session_cookies = encoded_cookies
            return await self._accounts.add(existing)
        account = FacebookAccount(
            user_id=user_id,
            fb_uid=fb_uid,
            access_token=access_token,
            session_cookies=encoded_cookies,
        )
        return await self._accounts.add(account)

    async def unlink(self, user_id: int) -> bool:
        """Remove *user_id*'s linked account. ``True`` if one was removed."""
        existing = await self._accounts.get_for_user(user_id)
        if existing is None:
            return False
        await self._accounts.delete(existing)
        return True
