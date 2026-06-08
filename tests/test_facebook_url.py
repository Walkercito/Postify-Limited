"""Tests for Facebook group link parsing."""

from __future__ import annotations

import pytest

from bot.facebook_url import (
    extract_group_id,
    extract_group_share_token,
    group_url,
    share_group_url,
)

NUMERIC_ID = "2665200520405415"
SLUG_ID = "rodascienfuegos"
SHARE_TOKEN = "1PBmPiveZY"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.facebook.com/groups/2665200520405415", NUMERIC_ID),
        ("https://www.facebook.com/groups/rodascienfuegos", SLUG_ID),
        ("http://facebook.com/groups/rodascienfuegos", SLUG_ID),
        ("facebook.com/groups/rodascienfuegos", SLUG_ID),
        ("https://m.facebook.com/groups/rodascienfuegos/", SLUG_ID),
        ("https://www.facebook.com/groups/rodascienfuegos?ref=share", SLUG_ID),
        ("check this out: https://www.facebook.com/groups/rodascienfuegos !", SLUG_ID),
        ("just some text", None),
        ("https://www.facebook.com/profile.php?id=100", None),
        ("https://example.com/groups/rodascienfuegos", None),
        ("https://notfacebook.com/groups/rodascienfuegos", None),
        # A share link is not a direct group link.
        ("https://www.facebook.com/share/g/1PBmPiveZY/", None),
    ],
)
def test_extract_group_id(text: str, expected: str | None) -> None:
    assert extract_group_id(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.facebook.com/share/g/1PBmPiveZY/", SHARE_TOKEN),
        ("https://www.facebook.com/share/g/1PBmPiveZY", SHARE_TOKEN),
        ("http://facebook.com/share/g/1PBmPiveZY/", SHARE_TOKEN),
        ("facebook.com/share/g/1PBmPiveZY", SHARE_TOKEN),
        ("https://m.facebook.com/share/g/1PBmPiveZY/", SHARE_TOKEN),
        ("here: https://www.facebook.com/share/g/1PBmPiveZY/ thanks", SHARE_TOKEN),
        # Wrong share kind (a post, not a group).
        ("https://www.facebook.com/share/p/1PBmPiveZY/", None),
        # Missing the ``/g/`` group segment.
        ("https://www.facebook.com/share/1PBmPiveZY/", None),
        # A direct group link carries no share token.
        ("https://www.facebook.com/groups/rodascienfuegos", None),
        ("https://notfacebook.com/share/g/1PBmPiveZY/", None),
        ("just some text", None),
    ],
)
def test_extract_group_share_token(text: str, expected: str | None) -> None:
    assert extract_group_share_token(text) == expected


def test_group_url_builds_canonical_link() -> None:
    assert group_url(SLUG_ID) == "https://www.facebook.com/groups/rodascienfuegos"


def test_group_url_roundtrips_through_extract() -> None:
    assert extract_group_id(group_url(NUMERIC_ID)) == NUMERIC_ID


def test_share_group_url_builds_canonical_link() -> None:
    assert share_group_url(SHARE_TOKEN) == "https://www.facebook.com/share/g/1PBmPiveZY/"


def test_share_group_url_roundtrips_through_extract() -> None:
    assert extract_group_share_token(share_group_url(SHARE_TOKEN)) == SHARE_TOKEN
