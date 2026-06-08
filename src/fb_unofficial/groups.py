"""Fetch a group's public preview (name / cover) without authentication.

Facebook still embeds Open Graph meta tags in the (login-gated) group page;
this module fetches that HTML over a plain :mod:`httpx` GET — **no access
token** — and reads ``og:title`` / ``og:image`` / ``og:url`` /
``og:description``. Only public metadata is available this way: member counts,
privacy, and feed content sit behind the login wall and are never returned.

:func:`fetch_group_preview` returns ``None`` when the page exposes no usable
public data (a login wall or a placeholder title); it raises
:class:`httpx.HTTPError` only when the page can't be fetched at all, leaving
that policy to the caller.
"""

from __future__ import annotations

import html
import re
from typing import Final

import httpx

from .constants import (
    DEFAULT_TIMEOUT_SEC,
    FB_GROUPS_PATH,
    FB_WEB_BASE,
    GROUP_PREVIEW_USER_AGENT,
)
from .resolve import _extract_numeric_id
from .types import GroupPreview

_OG_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"<meta[^>]+?property=[\"']og:(?P<key>title|image|url|description)[\"']"
    r"[^>]+?content=[\"'](?P<value>[^\"']*)[\"']",
    re.IGNORECASE,
)
_URL_SCHEME_RE: Final[re.Pattern[str]] = re.compile(r"^https?://", re.IGNORECASE)
_LOGIN_PATH_RE: Final[re.Pattern[str]] = re.compile(r"/login|/checkpoint", re.IGNORECASE)

# Titles Facebook serves on the login wall instead of the real group name.
_PLACEHOLDER_TITLES: Final[frozenset[str]] = frozenset(
    {"facebook", "log in to facebook", "log into facebook", "log in or sign up to view"}
)


def _group_page_url(url_or_id: str) -> str:
    """Build the page URL to scrape from a full URL or a bare id/slug."""
    value = url_or_id.strip()
    if _URL_SCHEME_RE.match(value):
        return value
    return f"{FB_WEB_BASE}/{FB_GROUPS_PATH}/{value}"


def _fallback_id(url_or_id: str) -> str | None:
    """A best-effort id from the original input (numeric id, slug, or ``None``)."""
    value = url_or_id.strip()
    if _URL_SCHEME_RE.match(value):
        return _extract_numeric_id(value)
    return value or None


def _parse_og_tags(body: str) -> dict[str, str]:
    """Extract and HTML-unescape the ``og:*`` tags we care about."""
    return {
        match.group("key").lower(): html.unescape(match.group("value"))
        for match in _OG_TAG_RE.finditer(body)
    }


def _preview_from_tags(tags: dict[str, str], fallback_id: str | None) -> GroupPreview | None:
    """Build a :class:`GroupPreview` from parsed tags, or ``None`` if unusable."""
    name = tags.get("title", "").strip()
    if not name or name.lower() in _PLACEHOLDER_TITLES:
        return None
    url = tags.get("url")
    group_id = (_extract_numeric_id(url) if url else None) or fallback_id
    return GroupPreview(
        id=group_id,
        name=name,
        cover_url=tags.get("image"),
        description=tags.get("description"),
        url=url,
    )


async def fetch_group_preview(
    url_or_id: str,
    *,
    user_agent: str | None = None,
    proxy: str | None = None,
    timeout: float | None = None,
) -> GroupPreview | None:
    """Return a public :class:`GroupPreview` for a group link/id, or ``None``.

    No authentication is used. ``None`` means the page exposed no usable public
    metadata (a login wall or a placeholder title). Transport failures raise
    :class:`httpx.HTTPError`, so the caller decides how to treat them.
    """
    target = _group_page_url(url_or_id)
    headers = {"User-Agent": user_agent or GROUP_PREVIEW_USER_AGENT}
    timeout_val = timeout if timeout is not None else DEFAULT_TIMEOUT_SEC
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout_val, proxy=proxy, headers=headers
    ) as client:
        response = await client.get(target)

    if _LOGIN_PATH_RE.search(response.url.path):
        return None
    tags = _parse_og_tags(response.text)
    return _preview_from_tags(tags, _fallback_id(url_or_id))
