"""Tests for the user repository and service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import AccessStatus, Role
from bot.db.base import utcnow
from bot.repositories.user import UserRepository
from bot.schemas.user import UserCreate
from bot.services.user_service import UserService

ADMIN_ID = 111
USER_ID = 222
OTHER_ID = 333


async def test_register_creates_user(session: AsyncSession) -> None:
    service = UserService(session)

    user, created = await service.register(
        UserCreate(telegram_id=USER_ID, first_name="Alice", username="alice")
    )
    await session.commit()

    assert created is True
    assert user.id is not None
    assert user.telegram_id == USER_ID
    assert user.role is Role.USER
    assert user.username == "alice"
    assert user.full_name == "Alice"
    assert user.is_active is True
    assert user.last_seen_at is None


async def test_register_defaults_to_pending(session: AsyncSession) -> None:
    user, _ = await UserService(session).register(UserCreate(telegram_id=USER_ID))
    await session.commit()

    assert user.access_status is AccessStatus.PENDING
    assert user.is_allowed is False


async def test_register_is_idempotent(session: AsyncSession) -> None:
    service = UserService(session)

    await service.register(UserCreate(telegram_id=USER_ID))
    await session.commit()
    _, created = await service.register(UserCreate(telegram_id=USER_ID))

    assert created is False


async def test_register_does_not_overwrite_access(session: AsyncSession) -> None:
    service = UserService(session)

    await service.register(UserCreate(telegram_id=USER_ID, access_status=AccessStatus.ALLOWED))
    await session.commit()

    existing, created = await service.register(
        UserCreate(telegram_id=USER_ID, access_status=AccessStatus.PENDING)
    )

    assert created is False
    assert existing.access_status is AccessStatus.ALLOWED


async def test_many_users_coexist(session: AsyncSession) -> None:
    service = UserService(session)

    admin, _ = await service.register(UserCreate(telegram_id=ADMIN_ID, role=Role.ADMIN))
    first, _ = await service.register(UserCreate(telegram_id=USER_ID, role=Role.USER))
    second, _ = await service.register(UserCreate(telegram_id=OTHER_ID, role=Role.USER))
    await session.commit()

    assert admin.role is Role.ADMIN
    assert first.role is Role.USER
    assert second.role is Role.USER


async def test_set_access_grant_deny_revoke(session: AsyncSession) -> None:
    service = UserService(session)
    await service.register(UserCreate(telegram_id=USER_ID))
    await session.commit()

    granted = await service.set_access(USER_ID, AccessStatus.ALLOWED)
    assert granted is not None
    assert granted.access_status is AccessStatus.ALLOWED
    assert granted.is_allowed is True

    revoked = await service.set_access(USER_ID, AccessStatus.DENIED)
    assert revoked is not None
    assert revoked.access_status is AccessStatus.DENIED
    assert revoked.is_allowed is False


async def test_set_access_unknown_user(session: AsyncSession) -> None:
    assert await UserService(session).set_access(USER_ID, AccessStatus.ALLOWED) is None


async def test_list_by_access(session: AsyncSession) -> None:
    service = UserService(session)
    await service.register(UserCreate(telegram_id=USER_ID))
    await service.register(UserCreate(telegram_id=OTHER_ID, access_status=AccessStatus.ALLOWED))
    await session.commit()

    pending = await service.list_by_access(AccessStatus.PENDING)
    allowed = await service.list_by_access(AccessStatus.ALLOWED)

    assert [user.telegram_id for user in pending] == [USER_ID]
    assert [user.telegram_id for user in allowed] == [OTHER_ID]


async def test_admin_is_allowed_regardless_of_status(session: AsyncSession) -> None:
    admin, _ = await UserService(session).register(
        UserCreate(telegram_id=ADMIN_ID, role=Role.ADMIN, access_status=AccessStatus.PENDING)
    )

    assert admin.is_admin is True
    assert admin.is_allowed is True


async def test_display_name_falls_back(session: AsyncSession) -> None:
    service = UserService(session)
    named, _ = await service.register(
        UserCreate(telegram_id=USER_ID, first_name="Ada", last_name="Lovelace")
    )
    handled, _ = await service.register(UserCreate(telegram_id=OTHER_ID, username="ada"))
    anon, _ = await service.register(UserCreate(telegram_id=ADMIN_ID))

    assert named.display_name == "Ada Lovelace"
    assert handled.display_name == "@ada"
    assert anon.display_name == str(ADMIN_ID)


async def test_full_name_combines_parts(session: AsyncSession) -> None:
    service = UserService(session)

    user, _ = await service.register(
        UserCreate(telegram_id=USER_ID, first_name="Ada", last_name="Lovelace")
    )

    assert user.full_name == "Ada Lovelace"


async def test_touch_last_seen(session: AsyncSession) -> None:
    await UserService(session).register(UserCreate(telegram_id=USER_ID))
    await session.commit()
    repo = UserRepository(session)

    updated = await repo.touch_last_seen(USER_ID, when=utcnow())
    await session.commit()

    assert updated is True
    user = await repo.get_by_telegram_id(USER_ID)
    assert user is not None
    assert user.last_seen_at is not None


async def test_touch_last_seen_unknown_user(session: AsyncSession) -> None:
    repo = UserRepository(session)
    assert await repo.touch_last_seen(USER_ID, when=utcnow()) is False
