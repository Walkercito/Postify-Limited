"""Read a logged-in web.facebook.com group page: its display name, or a wall.

Facebook stopped exposing group ``og`` tags to logged-out fetches, so the public
(unauthenticated) preview in :mod:`fb_unofficial` now comes back nameless. The
cookie-authenticated client (:class:`bot.facebook_web.FacebookWeb`) still gets
the modern logged-in markup, which carries the group name in the HTML
``<title>``; :func:`extract_group_name` reads it from there.

A login wall (expired cookies) or a placeholder title yields ``None`` from
:func:`extract_group_name`; a checkpoint / account-restriction interstitial —
which answers HTTP 200 with its *own* ``<title>`` — is caught by
:func:`is_blocked_page`. Both cases mean "unresolved", and the caller falls back
to the public scrape.
"""

from __future__ import annotations

import html
import re
from typing import Final

from bot.constants import (
    FB_WEB_CHECKPOINT_NEEDLES,
    FB_WEB_RESTRICTED_NEEDLES,
    FB_WEB_TITLE_PLACEHOLDERS,
    FB_WEB_TITLE_SUFFIXES,
)

_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL
)


def _strip_locale_suffix(title: str) -> str:
    """Drop a trailing localized ``| Facebook`` / ``- Facebook`` from the title."""
    for suffix in FB_WEB_TITLE_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def extract_title(body: str) -> str | None:
    """Return the page's raw ``<title>`` text (entity-unescaped, trimmed), or ``None``.

    The *unfiltered* title — :func:`extract_group_name` layers the suffix-strip
    and placeholder rejection on top. Callers that must inspect the title itself
    (e.g. :func:`is_blocked_page`, spotting a checkpoint/restriction wall) read it
    from here so they never have to scan the full page body.
    """
    match = _TITLE_RE.search(body)
    if match is None:
        return None
    return html.unescape(match.group("title")).strip()


def extract_group_name(body: str) -> str | None:
    """Return the group's display name from page HTML, or ``None``.

    ``None`` when the page has no ``<title>`` or carries only the logged-out
    placeholder (``Facebook`` / a login prompt) — the cookies are likely expired,
    so the caller falls back to the unauthenticated public scrape.
    """
    title = extract_title(body)
    if title is None:
        return None
    name = _strip_locale_suffix(title)
    if not name or name.casefold() in FB_WEB_TITLE_PLACEHOLDERS:
        return None
    return name


def is_blocked_page(url: str, body: str) -> bool:
    """Whether a fetched page is a checkpoint/restriction wall, not real content.

    A cookie-authenticated GET that Facebook intercepts with a checkpoint or
    account-restriction interstitial still answers HTTP 200 with a real
    ``<title>`` — but it is the wall's title, not the group's. Callers use this to
    discard such a page (and fall back to the public scrape) rather than store the
    wall's title as if it were the group name.

    Only two short, trustworthy signals are inspected: the **final URL** (after
    redirects — a checkpoint redirects to ``/checkpoint/…``) and the page's
    **``<title>``**. The raw body is deliberately *never* scanned: a genuine
    logged-in page embeds JSON-escaped ``\\/checkpoint\\/`` links throughout its
    scripts, so un-escaping and searching the body would flag every real page.
    """
    haystack = f"{url}\n{extract_title(body) or ''}"
    return any(
        needle in haystack for needle in (*FB_WEB_CHECKPOINT_NEEDLES, *FB_WEB_RESTRICTED_NEEDLES)
    )
