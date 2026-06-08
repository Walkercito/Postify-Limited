"""Tests for the in-memory post-draft model and store."""

from __future__ import annotations

import asyncio

from bot.post_drafts import PostDraft, PostDraftStore

USER_ID = 111
CHAT_ID = 555
MESSAGE_ID = 99
FILE_IDS = ["AgACfile1", "AgACfile2", "AgACfile3"]


def test_new_draft_is_empty_and_not_naming() -> None:
    draft = PostDraft()

    assert draft.is_empty is True
    assert draft.has_text is False
    assert draft.photo_count == 0
    assert draft.naming is False
    assert draft.is_publishing is False


def test_has_text_ignores_blank() -> None:
    assert PostDraft(text="   ").has_text is False
    assert PostDraft(text="hola").has_text is True


def test_photo_count_and_not_empty_with_photos() -> None:
    draft = PostDraft(photo_file_ids=list(FILE_IDS))

    assert draft.photo_count == len(FILE_IDS)
    assert draft.is_empty is False


def test_is_empty_false_with_only_text() -> None:
    assert PostDraft(text="algo").is_empty is False


def test_bind_message_records_location() -> None:
    draft = PostDraft()

    draft.bind_message(CHAT_ID, MESSAGE_ID)

    assert draft.chat_id == CHAT_ID
    assert draft.message_id == MESSAGE_ID


def test_remove_photo_in_range() -> None:
    draft = PostDraft(photo_file_ids=list(FILE_IDS))

    removed = draft.remove_photo(1)

    assert removed is True
    assert draft.photo_file_ids == ["AgACfile1", "AgACfile3"]


def test_remove_photo_out_of_range() -> None:
    draft = PostDraft(photo_file_ids=list(FILE_IDS))

    assert draft.remove_photo(9) is False
    assert draft.photo_count == len(FILE_IDS)


def test_reset_content_keeps_binding() -> None:
    draft = PostDraft(text="hola", photo_file_ids=list(FILE_IDS))
    draft.bind_message(CHAT_ID, MESSAGE_ID)

    draft.reset_content()

    assert draft.is_empty is True
    assert draft.chat_id == CHAT_ID
    assert draft.message_id == MESSAGE_ID


def test_begin_publishing_flips_phase() -> None:
    draft = PostDraft()

    event = draft.begin_publishing()

    assert isinstance(event, asyncio.Event)
    assert draft.is_publishing is True
    assert draft.cancel_event is event


async def test_cancel_render_cancels_pending_task() -> None:
    draft = PostDraft()

    async def _never() -> None:
        await asyncio.sleep(3600)

    draft.render_task = asyncio.create_task(_never())
    await asyncio.sleep(0)  # let the task start

    draft.cancel_render()

    assert draft.render_task is None


def test_cancel_render_without_task_is_a_noop() -> None:
    draft = PostDraft()

    draft.cancel_render()  # must not raise

    assert draft.render_task is None


def test_store_start_get_is_active_clear() -> None:
    store = PostDraftStore()

    assert store.is_active(USER_ID) is False
    assert store.get(USER_ID) is None

    draft = store.start(USER_ID)

    assert store.is_active(USER_ID) is True
    assert store.get(USER_ID) is draft

    store.clear(USER_ID)

    assert store.is_active(USER_ID) is False
    assert store.get(USER_ID) is None


def test_store_start_discards_previous_draft() -> None:
    store = PostDraftStore()
    first = store.start(USER_ID)

    second = store.start(USER_ID)

    assert second is not first
    assert store.get(USER_ID) is second
