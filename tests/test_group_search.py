"""Tests for the in-memory fuzzy-search result store and its pagination."""

from __future__ import annotations

from bot.group_search import GroupHit, GroupSearch, GroupSearchStore

USER_ID = 555
PAGE_SIZE = 2


def _hits(count: int) -> list[GroupHit]:
    return [GroupHit(id=i, facebook_id=f"g{i}", name=f"Grupo {i}") for i in range(count)]


def test_window_slices_first_page() -> None:
    search = GroupSearch(query="g", hits=_hits(5))

    page = search.window(PAGE_SIZE)

    assert [hit.id for hit in page.hits] == [0, 1]
    assert page.page == 0
    assert page.total == 5
    assert page.total_pages == 3
    assert page.has_prev is False
    assert page.has_next is True


def test_window_slices_last_partial_page() -> None:
    search = GroupSearch(query="g", hits=_hits(5), page=2)

    page = search.window(PAGE_SIZE)

    assert [hit.id for hit in page.hits] == [4]
    assert page.page == 2
    assert page.has_prev is True
    assert page.has_next is False


def test_window_clamps_overshot_page() -> None:
    search = GroupSearch(query="g", hits=_hits(3), page=99)

    page = search.window(PAGE_SIZE)

    assert page.page == 1
    assert [hit.id for hit in page.hits] == [2]


def test_window_empty_hits_has_single_page() -> None:
    search = GroupSearch(query="g", hits=[], page=3)

    page = search.window(PAGE_SIZE)

    assert page.hits == []
    assert page.page == 0
    assert page.total == 0
    assert page.total_pages == 1
    assert page.has_prev is False
    assert page.has_next is False


def test_go_to_changes_current_page() -> None:
    search = GroupSearch(query="g", hits=_hits(5))

    search.go_to(2)

    assert search.window(PAGE_SIZE).page == 2


def test_remove_drops_hit_and_reclamps_window() -> None:
    search = GroupSearch(query="g", hits=_hits(3), page=1)

    search.remove(2)

    assert [hit.id for hit in search.hits] == [0, 1]
    page = search.window(PAGE_SIZE)
    assert page.total == 2
    assert page.total_pages == 1
    assert page.page == 0


def test_remove_unknown_id_is_noop() -> None:
    search = GroupSearch(query="g", hits=_hits(3))

    search.remove(99)

    assert [hit.id for hit in search.hits] == [0, 1, 2]


def test_store_put_get_clear() -> None:
    store = GroupSearchStore()
    hits = _hits(2)

    search = store.put(USER_ID, "grupo", hits)

    assert store.get(USER_ID) is search
    assert search.query == "grupo"
    assert search.hits == hits

    store.clear(USER_ID)
    assert store.get(USER_ID) is None


def test_store_put_replaces_previous_search() -> None:
    store = GroupSearchStore()
    store.put(USER_ID, "first", _hits(2))

    second = store.put(USER_ID, "second", _hits(1))

    assert store.get(USER_ID) is second
    assert second.query == "second"
