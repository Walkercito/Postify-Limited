"""The *Lista* (full saved-group list) view branches in ``handlers.groups``.

The list view reuses the search result store and renderer with ``query=None``;
these tests pin the renderer's mode split (list header / list empty vs. the
search equivalents) and the ORM→hit projection the list and search flows share.
"""

from __future__ import annotations

from bot.db.models.group import Group
from bot.group_search import GroupHit, GroupSearch
from bot.handlers import groups as groups_module

QUERY = "mercado"


def _hits(count: int) -> list[GroupHit]:
    return [GroupHit(id=i, facebook_id=f"10{i}", name=f"Grupo {i}") for i in range(count)]


def test_render_list_view_uses_the_list_header() -> None:
    text, keyboard = groups_module._render_search(GroupSearch(query=None, hits=_hits(1)))

    assert text == groups_module.GROUP_LIST_HEADER.format(page=1, total_pages=1, total=1)
    assert keyboard.inline_keyboard  # result rows are rendered as usual


def test_render_list_view_empty_uses_the_list_empty_message() -> None:
    text, _keyboard = groups_module._render_search(GroupSearch(query=None, hits=[]))

    assert text == groups_module.GROUP_LIST_EMPTY


def test_render_search_view_keeps_the_query_messages() -> None:
    # A real search still renders its own header / empty message, query included.
    header, _kb = groups_module._render_search(GroupSearch(query=QUERY, hits=_hits(1)))
    empty, _kb = groups_module._render_search(GroupSearch(query=QUERY, hits=[]))

    assert QUERY in header
    assert header != groups_module.GROUP_LIST_HEADER.format(page=1, total_pages=1, total=1)
    assert empty == groups_module.GROUP_SEARCH_NO_RESULTS.format(query=QUERY)


def test_to_hits_projects_orm_groups() -> None:
    groups = [
        Group(id=1, facebook_id="123", name="Alpha"),
        Group(id=2, facebook_id="456", name=None),
    ]

    hits = groups_module._to_hits(groups)

    assert hits == [
        GroupHit(id=1, facebook_id="123", name="Alpha"),
        GroupHit(id=2, facebook_id="456", name=None),
    ]
