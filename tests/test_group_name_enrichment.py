"""The best-effort group-name enrichment glue (handlers.groups).

Name resolution prefers the owner's authenticated cookie session (Facebook no
longer serves group ``og`` tags to logged-out fetches) and falls back to the
public, unauthenticated scrape — tagging the wide ``group.added`` event with the
:class:`NameSource` that produced the name.
"""

from __future__ import annotations

import httpx
import pytest

from bot.constants import NameSource
from bot.core.exceptions import FacebookWebError
from bot.handlers import groups as groups_module
from fb_unofficial import GroupPreview

NUMERIC_ID = "235748574929899"
SHARE_TOKEN = "1PBmPiveZY"
COOKIES = {"c_user": "100012345678901", "xs": "secret"}


# --------------------------------------------------------------------------- #
# _resolve_group_name: authenticated first, public scrape as fallback.          #
# --------------------------------------------------------------------------- #
async def test_resolve_group_name_prefers_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_auth(_facebook_id: str, _cookies: dict[str, str]) -> str | None:
        return "Authenticated Name"

    async def fail(*_: object, **__: object) -> GroupPreview | None:
        raise AssertionError("the public scrape must not run once the session resolves a name")

    monkeypatch.setattr(groups_module, "_fetch_authenticated_name", fake_auth)
    monkeypatch.setattr(groups_module, "fetch_group_preview", fail)

    assert await groups_module._resolve_group_name(NUMERIC_ID, COOKIES) == (
        "Authenticated Name",
        NameSource.AUTHENTICATED,
    )


async def test_resolve_group_name_falls_back_to_public_when_auth_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_auth(_facebook_id: str, _cookies: dict[str, str]) -> str | None:
        return None

    async def fake(facebook_id: str, **_: object) -> GroupPreview | None:
        return GroupPreview(id=facebook_id, name="Public Name")

    monkeypatch.setattr(groups_module, "_fetch_authenticated_name", fake_auth)
    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name(NUMERIC_ID, COOKIES) == (
        "Public Name",
        NameSource.UNAUTHENTICATED,
    )


async def test_resolve_group_name_no_cookies_skips_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(facebook_id: str, **_: object) -> GroupPreview | None:
        return GroupPreview(id=facebook_id, name="Rodas Cienfuegos")

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name("rodascienfuegos", None) == (
        "Rodas Cienfuegos",
        NameSource.UNAUTHENTICATED,
    )


async def test_resolve_group_name_unresolved_when_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(_facebook_id: str, **_: object) -> GroupPreview | None:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name("rodascienfuegos", None) == (
        None,
        NameSource.UNRESOLVED,
    )


async def test_resolve_group_name_unresolved_when_no_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(_facebook_id: str, **_: object) -> GroupPreview | None:
        return None

    monkeypatch.setattr(groups_module, "fetch_group_preview", fake)

    assert await groups_module._resolve_group_name("walled-group", None) == (
        None,
        NameSource.UNRESOLVED,
    )


# --------------------------------------------------------------------------- #
# _fetch_authenticated_name: a failing session degrades to None (then fallback).#
# --------------------------------------------------------------------------- #
class _FakeWeb:
    """Stand-in for :class:`FacebookWeb` whose name fetch is scripted per test."""

    def __init__(self, _cookies: dict[str, str], *, name: str | None, error: Exception | None):
        self._name = name
        self._error = error

    async def __aenter__(self) -> _FakeWeb:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def fetch_group_name(self, _group_id: str) -> str | None:
        if self._error is not None:
            raise self._error
        return self._name


def _patch_web(
    monkeypatch: pytest.MonkeyPatch, *, name: str | None, error: Exception | None
) -> None:
    monkeypatch.setattr(
        groups_module,
        "FacebookWeb",
        lambda cookies: _FakeWeb(cookies, name=name, error=error),
    )


async def test_fetch_authenticated_name_returns_session_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_web(monkeypatch, name="Session Group", error=None)

    assert await groups_module._fetch_authenticated_name(NUMERIC_ID, COOKIES) == "Session Group"


async def test_fetch_authenticated_name_swallows_web_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_web(monkeypatch, name=None, error=FacebookWebError("expired session"))

    assert await groups_module._fetch_authenticated_name(NUMERIC_ID, COOKIES) is None


async def test_fetch_authenticated_name_swallows_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_web(monkeypatch, name=None, error=httpx.ConnectError("network down"))

    assert await groups_module._fetch_authenticated_name(NUMERIC_ID, COOKIES) is None


# --------------------------------------------------------------------------- #
# _resolve_reference: direct id vs share-token (unchanged behaviour).            #
# --------------------------------------------------------------------------- #
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
