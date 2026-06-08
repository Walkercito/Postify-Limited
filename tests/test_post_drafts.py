"""Tests for the in-memory post-draft store."""

from __future__ import annotations

from bot.post_drafts import PostDraftStore

USER_ID = 777


def test_start_creates_active_draft() -> None:
    store = PostDraftStore()

    draft = store.start(USER_ID)

    assert store.is_active(USER_ID) is True
    assert store.get(USER_ID) is draft
    assert draft.text is None
    assert draft.photo_count == 0


def test_get_and_is_active_false_when_inactive() -> None:
    store = PostDraftStore()

    assert store.get(USER_ID) is None
    assert store.is_active(USER_ID) is False


def test_clear_forgets_draft() -> None:
    store = PostDraftStore()
    store.start(USER_ID)

    store.clear(USER_ID)

    assert store.is_active(USER_ID) is False
    assert store.get(USER_ID) is None


def test_start_replaces_previous_draft() -> None:
    store = PostDraftStore()
    first = store.start(USER_ID)
    first.text = "old"

    second = store.start(USER_ID)

    assert second is not first
    assert second.text is None


def test_has_text_ignores_whitespace() -> None:
    store = PostDraftStore()
    draft = store.start(USER_ID)

    assert draft.has_text is False
    draft.text = "   "
    assert draft.has_text is False
    draft.text = "hello"
    assert draft.has_text is True


def test_photo_count_tracks_appended_ids() -> None:
    store = PostDraftStore()
    draft = store.start(USER_ID)

    draft.photo_file_ids.append("a")
    draft.photo_file_ids.append("b")

    assert draft.photo_count == 2


def test_remove_photo_drops_in_range_index() -> None:
    store = PostDraftStore()
    draft = store.start(USER_ID)
    draft.photo_file_ids.extend(["a", "b", "c"])

    removed = draft.remove_photo(1)

    assert removed is True
    assert draft.photo_file_ids == ["a", "c"]


def test_remove_photo_rejects_out_of_range_index() -> None:
    store = PostDraftStore()
    draft = store.start(USER_ID)
    draft.photo_file_ids.append("a")

    assert draft.remove_photo(5) is False
    assert draft.remove_photo(-1) is False
    assert draft.photo_file_ids == ["a"]


def test_reset_content_keeps_message_binding() -> None:
    store = PostDraftStore()
    draft = store.start(USER_ID)
    draft.bind_message(chat_id=10, message_id=20)
    draft.text = "hello"
    draft.photo_file_ids.extend(["a", "b"])

    draft.reset_content()

    assert draft.is_empty is True
    assert draft.text is None
    assert draft.photo_count == 0
    assert draft.chat_id == 10
    assert draft.message_id == 20
