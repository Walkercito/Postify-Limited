"""The best-effort group-name enrichment glue (handlers.groups)."""

from __future__ import annotations

import httpx
import pytest

from bot.handlers import groups as groups_module
from fb_unofficial import GroupPreview

NUMERIC_ID = "235748574929899"
SHARE_TOKEN = "1PBmPiveZY"


async def test_resolve_group_name_returns_preview_name(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(facebook_id: str, **_: object) -> GroupPreview | None:
        return GroupPreview(id=facebook_id, name="Rodas Cienfuegos")

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name("rodascienfuegos") == "Rodas Cienfuegos"


async def test_resolve_group_name_swallows_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(_facebook_id: str, **_: object) -> GroupPreview | None:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name("rodascienfuegos") is None


async def test_resolve_group_name_none_when_no_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_facebook_id: str, **_: object) -> GroupPreview | None:
        return None

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name("walled-group") is None


async def test_resolve_reference_direct_id_skips_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_: object, **__: object) -> GroupPreview | None:
        msg = "a direct id must not touch the network"
        raise AssertionError(msg)

    monkeypatch.setattr(groups_module, "fetch_group_preview", fail)

    assert await groups_module._resolve_reference("rodascienfuegos", None) == (
        "rodascienfuegos",
        None,
    )


async def test_resolve_reference_share_token_returns_canonical_id_and_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(url_or_id: str, **_: object) -> GroupPreview | None:
        assert SHARE_TOKEN in url_or_id  # the share URL was rebuilt from the token
        return GroupPreview(id=NUMERIC_ID, name="Rodas Cienfuegos")

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_reference(None, SHARE_TOKEN) == (
        NUMERIC_ID,
        "Rodas Cienfuegos",
    )


async def test_resolve_reference_share_token_none_when_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(_url_or_id: str, **_: object) -> GroupPreview | None:
        return None  # login wall / placeholder

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_reference(None, SHARE_TOKEN) is None


async def test_resolve_reference_share_token_none_without_usable_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(_url_or_id: str, **_: object) -> GroupPreview | None:
        return GroupPreview(id=None, name="Some Group")  # name but no canonical id

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_reference(None, SHARE_TOKEN) is None


async def test_resolve_reference_none_when_nothing_parsed() -> None:
    assert await groups_module._resolve_reference(None, None) is None
