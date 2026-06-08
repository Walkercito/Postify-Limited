"""Tests for the blueprint service and repository (saved posts)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.blueprint_service import BlueprintService

# FK enforcement is off in the in-memory test engine, so synthetic user ids need
# no backing ``User`` row — the service/repo are exercised in isolation.
USER_ID = 111
OTHER_ID = 222

FILE_IDS = ["AgACfile1", "AgACfile2"]


async def test_create_persists_blueprint(session: AsyncSession) -> None:
    service = BlueprintService(session)

    blueprint = await service.create(
        USER_ID, "Mi Plantilla", text="Hola mundo", photo_file_ids=FILE_IDS
    )

    assert blueprint.id is not None
    assert blueprint.user_id == USER_ID
    assert blueprint.name == "Mi Plantilla"
    assert blueprint.slug == "mi-plantilla"
    assert blueprint.text == "Hola mundo"
    assert blueprint.photo_file_ids == FILE_IDS


async def test_create_defaults_text_none_and_photos_empty(session: AsyncSession) -> None:
    blueprint = await BlueprintService(session).create(USER_ID, "Solo nombre")

    assert blueprint.text is None
    assert blueprint.photo_file_ids == []


async def test_slug_folds_accents_and_collapses_punctuation(session: AsyncSession) -> None:
    blueprint = await BlueprintService(session).create(USER_ID, "Mi Súper Plantilla!!! #1")

    assert blueprint.slug == "mi-super-plantilla-1"


async def test_slug_emoji_only_falls_back(session: AsyncSession) -> None:
    blueprint = await BlueprintService(session).create(USER_ID, "🎉🎊✨")

    assert blueprint.slug == "plantilla"


async def test_slug_uniqueness_appends_incrementing_suffix(session: AsyncSession) -> None:
    service = BlueprintService(session)

    first = await service.create(USER_ID, "Promo")
    second = await service.create(USER_ID, "Promo")
    third = await service.create(USER_ID, "Promo")

    assert first.slug == "promo"
    assert second.slug == "promo-2"
    assert third.slug == "promo-3"


async def test_slug_uniqueness_is_per_user(session: AsyncSession) -> None:
    service = BlueprintService(session)

    mine = await service.create(USER_ID, "Promo")
    theirs = await service.create(OTHER_ID, "Promo")

    # A name another user already took does not collide — slugs are per-user.
    assert mine.slug == "promo"
    assert theirs.slug == "promo"


async def test_find_by_id_returns_own_blueprint(session: AsyncSession) -> None:
    service = BlueprintService(session)
    created = await service.create(USER_ID, "Promo")

    found = await service.find_by_id(USER_ID, created.id)

    assert found is not None
    assert found.id == created.id


async def test_find_by_id_is_scoped_to_user(session: AsyncSession) -> None:
    service = BlueprintService(session)
    created = await service.create(USER_ID, "Promo")

    # Another user must never reach it through a stale button.
    assert await service.find_by_id(OTHER_ID, created.id) is None


async def test_find_by_id_unknown_returns_none(session: AsyncSession) -> None:
    assert await BlueprintService(session).find_by_id(USER_ID, 9999) is None


async def test_rename_changes_name_and_reslugs(session: AsyncSession) -> None:
    service = BlueprintService(session)
    blueprint = await service.create(USER_ID, "Promo")

    renamed = await service.rename(blueprint, "Oferta Especial")

    assert renamed.name == "Oferta Especial"
    assert renamed.slug == "oferta-especial"


async def test_rename_to_same_name_keeps_slug(session: AsyncSession) -> None:
    service = BlueprintService(session)
    blueprint = await service.create(USER_ID, "Promo")

    renamed = await service.rename(blueprint, "Promo")

    # Excluding itself from the collision check avoids a spurious ``-2`` suffix.
    assert renamed.slug == "promo"


async def test_rename_collision_with_other_blueprint_suffixes(session: AsyncSession) -> None:
    service = BlueprintService(session)
    await service.create(USER_ID, "Promo")
    other = await service.create(USER_ID, "Rebaja")

    renamed = await service.rename(other, "Promo")

    assert renamed.slug == "promo-2"


async def test_set_text_replaces_body(session: AsyncSession) -> None:
    service = BlueprintService(session)
    blueprint = await service.create(USER_ID, "Promo", text="viejo")

    updated = await service.set_text(blueprint, "nuevo")

    assert updated.text == "nuevo"


async def test_set_text_can_clear_body(session: AsyncSession) -> None:
    service = BlueprintService(session)
    blueprint = await service.create(USER_ID, "Promo", text="algo")

    updated = await service.set_text(blueprint, None)

    assert updated.text is None


async def test_remove_by_id_deletes_and_returns_it(session: AsyncSession) -> None:
    service = BlueprintService(session)
    blueprint = await service.create(USER_ID, "Promo")

    removed = await service.remove_by_id(USER_ID, blueprint.id)

    assert removed is not None
    assert removed.slug == "promo"
    assert await service.find_by_id(USER_ID, blueprint.id) is None
    assert await service.count_for_user(USER_ID) == 0


async def test_remove_by_id_is_scoped_to_user(session: AsyncSession) -> None:
    service = BlueprintService(session)
    blueprint = await service.create(USER_ID, "Promo")

    # Another user's stale button must not delete it.
    assert await service.remove_by_id(OTHER_ID, blueprint.id) is None
    assert await service.find_by_id(USER_ID, blueprint.id) is not None


async def test_remove_by_id_unknown_returns_none(session: AsyncSession) -> None:
    assert await BlueprintService(session).remove_by_id(USER_ID, 9999) is None


async def test_list_for_user_returns_only_owned(session: AsyncSession) -> None:
    service = BlueprintService(session)
    await service.create(USER_ID, "Uno")
    await service.create(USER_ID, "Dos")
    await service.create(OTHER_ID, "Ajeno")

    listed = await service.list_for_user(USER_ID)

    assert {blueprint.slug for blueprint in listed} == {"uno", "dos"}


async def test_list_for_user_respects_limit(session: AsyncSession) -> None:
    service = BlueprintService(session)
    for index in range(5):
        await service.create(USER_ID, f"Plantilla {index}")

    listed = await service.list_for_user(USER_ID, limit=3)

    assert len(listed) == 3


async def test_count_for_user_scopes_and_counts(session: AsyncSession) -> None:
    service = BlueprintService(session)
    await service.create(USER_ID, "Uno")
    await service.create(USER_ID, "Dos")
    await service.create(OTHER_ID, "Ajeno")

    assert await service.count_for_user(USER_ID) == 2
    assert await service.count_for_user(OTHER_ID) == 1


async def test_count_for_user_zero_when_empty(session: AsyncSession) -> None:
    assert await BlueprintService(session).count_for_user(USER_ID) == 0
