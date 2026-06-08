"""Tests for the Facebook account repository and service."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.exceptions import FacebookAccountTakenError
from bot.db.models.facebook_account import FacebookAccount
from bot.facebook_web import decode_cookies
from bot.schemas.user import UserCreate
from bot.services.facebook_account_service import FacebookAccountService
from bot.services.user_service import UserService

USER_TG_ID = 4242
OTHER_TG_ID = 7373
FB_UID = "100012345678901"
FB_TOKEN = "EAABwz-token-one"
FB_UID_OTHER = "100098765432109"
FB_TOKEN_OTHER = "EAABwz-token-two"
FB_COOKIES = {"c_user": FB_UID, "xs": "cookie-secret-xs", "datr": "cookie-datr"}


async def _make_user(session: AsyncSession, telegram_id: int) -> int:
    user, _ = await UserService(session).register(UserCreate(telegram_id=telegram_id))
    await session.flush()
    return user.id


async def test_link_creates_account(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)

    account = await FacebookAccountService(session).link(owner_id, FB_UID, access_token=FB_TOKEN)

    assert account.id is not None
    assert account.user_id == owner_id
    assert account.fb_uid == FB_UID
    assert account.access_token == FB_TOKEN


async def test_get_for_user_returns_linked_account(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = FacebookAccountService(session)
    await service.link(owner_id, FB_UID, access_token=FB_TOKEN)

    found = await service.get_for_user(owner_id)

    assert found is not None
    assert found.fb_uid == FB_UID
    assert found.access_token == FB_TOKEN


async def test_get_for_user_none_when_unlinked(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)

    assert await FacebookAccountService(session).get_for_user(owner_id) is None


async def test_link_is_upsert(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = FacebookAccountService(session)

    first = await service.link(owner_id, FB_UID, access_token=FB_TOKEN)
    second = await service.link(owner_id, FB_UID_OTHER, access_token=FB_TOKEN_OTHER)

    assert first.id == second.id
    assert second.fb_uid == FB_UID_OTHER
    assert second.access_token == FB_TOKEN_OTHER

    rows = (
        await session.scalars(select(FacebookAccount).where(FacebookAccount.user_id == owner_id))
    ).all()
    assert len(rows) == 1


async def test_link_rejects_uid_owned_by_another_user(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    other_id = await _make_user(session, OTHER_TG_ID)
    service = FacebookAccountService(session)
    await service.link(owner_id, FB_UID, access_token=FB_TOKEN)

    with pytest.raises(FacebookAccountTakenError):
        await service.link(other_id, FB_UID, access_token=FB_TOKEN_OTHER)


async def test_relink_same_uid_same_user_is_allowed(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = FacebookAccountService(session)
    await service.link(owner_id, FB_UID, access_token=FB_TOKEN)

    account = await service.link(owner_id, FB_UID, access_token=FB_TOKEN_OTHER)

    assert account.fb_uid == FB_UID
    assert account.access_token == FB_TOKEN_OTHER


async def test_unlink_removes_account(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = FacebookAccountService(session)
    await service.link(owner_id, FB_UID, access_token=FB_TOKEN)

    removed = await service.unlink(owner_id)

    assert removed is True
    assert await service.get_for_user(owner_id) is None


async def test_unlink_returns_false_when_absent(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)

    assert await FacebookAccountService(session).unlink(owner_id) is False


async def test_link_creates_account_with_cookies(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)

    account = await FacebookAccountService(session).link(
        owner_id, FB_UID, session_cookies=FB_COOKIES
    )

    assert account.access_token is None
    assert account.session_cookies is not None
    assert decode_cookies(account.session_cookies) == FB_COOKIES


async def test_relink_switches_token_to_cookies(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = FacebookAccountService(session)
    await service.link(owner_id, FB_UID, access_token=FB_TOKEN)

    account = await service.link(owner_id, FB_UID, session_cookies=FB_COOKIES)

    assert account.access_token is None
    assert decode_cookies(account.session_cookies) == FB_COOKIES


async def test_link_requires_a_credential(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)

    with pytest.raises(ValueError, match="access token or session cookies"):
        await FacebookAccountService(session).link(owner_id, FB_UID)
