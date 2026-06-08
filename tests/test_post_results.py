"""Tests for the in-memory finished-publish result store and its pagination."""

from __future__ import annotations

from bot.post_results import PostResultSet, PostResultStore

USER_ID = 777
PAGE_SIZE = 2
HEADER = "✅ done"


def _lines(count: int) -> list[str]:
    return [f"line {i}" for i in range(count)]


def test_window_slices_first_page() -> None:
    result_set = PostResultSet(header=HEADER, lines=_lines(5))

    page = result_set.window(PAGE_SIZE)

    assert page.lines == ["line 0", "line 1"]
    assert page.page == 0
    assert page.total == 5
    assert page.total_pages == 3
    assert page.has_prev is False
    assert page.has_next is True


def test_window_slices_last_partial_page() -> None:
    result_set = PostResultSet(header=HEADER, lines=_lines(5), page=2)

    page = result_set.window(PAGE_SIZE)

    assert page.lines == ["line 4"]
    assert page.page == 2
    assert page.has_prev is True
    assert page.has_next is False


def test_window_clamps_overshot_page() -> None:
    result_set = PostResultSet(header=HEADER, lines=_lines(3), page=99)

    page = result_set.window(PAGE_SIZE)

    assert page.page == 1
    assert page.lines == ["line 2"]


def test_window_empty_lines_has_single_page() -> None:
    result_set = PostResultSet(header=HEADER, lines=[], page=3)

    page = result_set.window(PAGE_SIZE)

    assert page.lines == []
    assert page.page == 0
    assert page.total == 0
    assert page.total_pages == 1
    assert page.has_prev is False
    assert page.has_next is False


def test_go_to_changes_current_page() -> None:
    result_set = PostResultSet(header=HEADER, lines=_lines(5))

    result_set.go_to(2)

    assert result_set.window(PAGE_SIZE).page == 2


def test_store_put_get_clear() -> None:
    store = PostResultStore()
    lines = _lines(3)

    result_set = store.put(USER_ID, HEADER, lines)

    assert store.get(USER_ID) is result_set
    assert result_set.header == HEADER
    assert result_set.lines == lines

    store.clear(USER_ID)
    assert store.get(USER_ID) is None


def test_store_put_replaces_previous_set() -> None:
    store = PostResultStore()
    store.put(USER_ID, "first", _lines(2))

    second = store.put(USER_ID, "second", _lines(1))

    assert store.get(USER_ID) is second
    assert second.header == "second"
