"""Tests for the group repository and service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.schemas.user import UserCreate
from bot.services.group_service import GroupService
from bot.services.user_service import UserService

USER_TG_ID = 222
OTHER_TG_ID = 333
GROUP_A = "rodascienfuegos"
GROUP_B = "2665200520405415"


async def _make_user(session: AsyncSession, telegram_id: int) -> int:
    user, _ = await UserService(session).register(UserCreate(telegram_id=telegram_id))
    await session.flush()
    return user.id


async def test_add_creates_group(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)

    group, created = await GroupService(session).add(owner_id, GROUP_A)

    assert created is True
    assert group.id is not None
    assert group.user_id == owner_id
    assert group.facebook_id == GROUP_A


async def test_add_is_idempotent_per_user(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)

    first, created_first = await service.add(owner_id, GROUP_A)
    second, created_second = await service.add(owner_id, GROUP_A)

    assert created_first is True
    assert created_second is False
    assert first.id == second.id


async def test_same_group_for_different_users(session: AsyncSession) -> None:
    one = await _make_user(session, USER_TG_ID)
    two = await _make_user(session, OTHER_TG_ID)
    service = GroupService(session)

    _, created_one = await service.add(one, GROUP_A)
    _, created_two = await service.add(two, GROUP_A)

    assert created_one is True
    assert created_two is True


async def test_find_returns_saved_group(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    await service.add(owner_id, GROUP_A)

    found = await service.find(owner_id, GROUP_A)
    missing = await service.find(owner_id, GROUP_B)

    assert found is not None
    assert found.facebook_id == GROUP_A
    assert missing is None


async def test_set_name_persists(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(owner_id, GROUP_A)

    await service.set_name(group, "Rodas Cienfuegos")

    refreshed = await service.find(owner_id, GROUP_A)
    assert refreshed is not None
    assert refreshed.name == "Rodas Cienfuegos"


async def test_remove_by_id(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(owner_id, GROUP_A)

    removed = await service.remove_by_id(owner_id, group.id)

    assert removed is not None
    assert removed.facebook_id == GROUP_A
    assert await service.find(owner_id, GROUP_A) is None


async def test_remove_by_id_rejects_other_owner(session: AsyncSession) -> None:
    one = await _make_user(session, USER_TG_ID)
    two = await _make_user(session, OTHER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(one, GROUP_A)

    assert await service.remove_by_id(two, group.id) is None
    assert await service.find(one, GROUP_A) is not None


async def test_list_for_user_scoped_and_limited(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    other_id = await _make_user(session, OTHER_TG_ID)
    service = GroupService(session)
    await service.add(owner_id, GROUP_A)
    await service.add(owner_id, GROUP_B)
    await service.add(other_id, GROUP_A)

    mine = await service.list_for_user(owner_id)
    limited = await service.list_for_user(owner_id, limit=1)

    assert {group.facebook_id for group in mine} == {GROUP_A, GROUP_B}
    assert len(limited) == 1


async def test_find_by_id_scoped_to_owner(session: AsyncSession) -> None:
    one = await _make_user(session, USER_TG_ID)
    two = await _make_user(session, OTHER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(one, GROUP_A)

    assert (await service.find_by_id(one, group.id)) is not None
    assert await service.find_by_id(two, group.id) is None
    assert await service.find_by_id(one, group.id + 999) is None


async def test_count_for_user(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    other_id = await _make_user(session, OTHER_TG_ID)
    service = GroupService(session)

    assert await service.count_for_user(owner_id) == 0
    await service.add(owner_id, GROUP_A)
    await service.add(owner_id, GROUP_B)
    await service.add(other_id, GROUP_A)

    assert await service.count_for_user(owner_id) == 2
    assert await service.count_for_user(other_id) == 1


async def test_search_blank_query_returns_empty(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(owner_id, GROUP_A)
    await service.set_name(group, "Rodas Cienfuegos")

    assert await service.search(owner_id, "") == []
    assert await service.search(owner_id, "   ") == []


async def test_search_tolerates_typos(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(owner_id, GROUP_A)
    await service.set_name(group, "Rodas Cienfuegos")

    results = await service.search(owner_id, "rodaz sienfuegos")

    assert [g.id for g in results] == [group.id]


async def test_search_is_accent_insensitive(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    group, _ = await service.add(owner_id, GROUP_A)
    await service.set_name(group, "Compra y Venta Camagüey")

    results = await service.search(owner_id, "camaguey")

    assert [g.id for g in results] == [group.id]


async def test_search_ranks_best_match_first(session: AsyncSession) -> None:
    owner_id = await _make_user(session, USER_TG_ID)
    service = GroupService(session)
    havana, _ = await service.add(owner_id, "g-havana")
    await service.set_name(havana, "Compra y Venta La Habana")
    matanzas, _ = await service.add(owner_id, "g-matanzas")
    await service.set_name(matanzas, "Compra y Venta Matanzas")

    results = await service.search(owner_id, "habana")

    assert results
    assert results[0].id == havana.id


async def test_search_excludes_other_users(session: AsyncSession) -> None:
    one = await _make_user(session, USER_TG_ID)
    two = await _make_user(session, OTHER_TG_ID)
    service = GroupService(session)
    mine, _ = await service.add(one, GROUP_A)
    await service.set_name(mine, "Rodas Cienfuegos")
    theirs, _ = await service.add(two, GROUP_B)
    await service.set_name(theirs, "Rodas Cienfuegos")

    results = await service.search(one, "rodas")

    assert [g.id for g in results] == [mine.id]
