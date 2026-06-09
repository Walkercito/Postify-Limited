"""Lift a group's display name from its logged-in web.facebook.com page.

Facebook stopped exposing group ``og`` tags to logged-out fetches, so the public
(unauthenticated) preview in :mod:`fb_unofficial` now comes back nameless. The
cookie-authenticated client (:class:`bot.facebook_web.FacebookWeb`) still gets
the modern logged-in markup, which carries the group name in the HTML
``<title>``; :func:`extract_group_name` reads it from there.

A login wall (expired cookies) or a placeholder title yields ``None``, which the
caller treats as "unresolved" and falls back to the public scrape.
"""

from __future__ import annotations

import html
import re
from typing import Final

from bot.constants import FB_WEB_TITLE_PLACEHOLDERS, FB_WEB_TITLE_SUFFIXES

_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL
)


def _strip_locale_suffix(title: str) -> str:
    """Drop a trailing localized ``| Facebook`` / ``- Facebook`` from the title."""
    for suffix in FB_WEB_TITLE_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def extract_group_name(body: str) -> str | None:
    """Return the group's display name from page HTML, or ``None``.

    ``None`` when the page has no ``<title>`` or carries only the logged-out
    placeholder (``Facebook`` / a login prompt) — the cookies are likely expired,
    so the caller falls back to the unauthenticated public scrape.
    """
    match = _TITLE_RE.search(body)
    if match is None:
        return None
    title = _strip_locale_suffix(html.unescape(match.group("title")).strip())
    if not title or title.casefold() in FB_WEB_TITLE_PLACEHOLDERS:
        return None
    return title
