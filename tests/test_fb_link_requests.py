"""Tests for the in-memory Facebook-link request store."""

from __future__ import annotations

from bot.fb_link_requests import FacebookLinkStore

ADMIN_ID = 1
TARGET_ID = 4242
OTHER_TARGET_ID = 9001


def test_begin_then_get_returns_target() -> None:
    store = FacebookLinkStore()

    store.begin(ADMIN_ID, TARGET_ID)

    assert store.get(ADMIN_ID) == TARGET_ID


def test_get_none_when_unarmed() -> None:
    assert FacebookLinkStore().get(ADMIN_ID) is None


def test_clear_forgets_target() -> None:
    store = FacebookLinkStore()
    store.begin(ADMIN_ID, TARGET_ID)

    store.clear(ADMIN_ID)

    assert store.get(ADMIN_ID) is None


def test_clear_is_idempotent() -> None:
    store = FacebookLinkStore()

    store.clear(ADMIN_ID)  # nothing armed — must not raise

    assert store.get(ADMIN_ID) is None


def test_begin_replaces_previous_target() -> None:
    store = FacebookLinkStore()

    store.begin(ADMIN_ID, TARGET_ID)
    store.begin(ADMIN_ID, OTHER_TARGET_ID)

    assert store.get(ADMIN_ID) == OTHER_TARGET_ID
