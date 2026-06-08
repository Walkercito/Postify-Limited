"""Tests for the in-memory pending-blueprint-edit store."""

from __future__ import annotations

from bot.blueprint_edits import BlueprintEditStore, PendingBlueprintEdit
from bot.constants import BlueprintField

USER_ID = 111
OTHER_ID = 222
BLUEPRINT_ID = 7
CHAT_ID = 555
MESSAGE_ID = 99


def _edit(field: BlueprintField = BlueprintField.NAME) -> PendingBlueprintEdit:
    return PendingBlueprintEdit(
        blueprint_id=BLUEPRINT_ID, field=field, chat_id=CHAT_ID, message_id=MESSAGE_ID
    )


def test_get_unknown_user_returns_none() -> None:
    assert BlueprintEditStore().get(USER_ID) is None


def test_begin_then_get_roundtrips() -> None:
    store = BlueprintEditStore()
    edit = _edit(BlueprintField.TEXT)

    store.begin(USER_ID, edit)

    assert store.get(USER_ID) is edit


def test_begin_overwrites_previous_edit() -> None:
    store = BlueprintEditStore()
    store.begin(USER_ID, _edit(BlueprintField.NAME))

    replacement = _edit(BlueprintField.TEXT)
    store.begin(USER_ID, replacement)

    assert store.get(USER_ID) is replacement


def test_clear_forgets_edit() -> None:
    store = BlueprintEditStore()
    store.begin(USER_ID, _edit())

    store.clear(USER_ID)

    assert store.get(USER_ID) is None


def test_clear_unknown_user_is_a_noop() -> None:
    store = BlueprintEditStore()

    store.clear(USER_ID)  # must not raise

    assert store.get(USER_ID) is None


def test_edits_are_isolated_per_user() -> None:
    store = BlueprintEditStore()
    mine = _edit(BlueprintField.NAME)
    store.begin(USER_ID, mine)

    store.clear(OTHER_ID)

    assert store.get(USER_ID) is mine
