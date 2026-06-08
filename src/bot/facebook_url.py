"""Parse and build Facebook group links.

A direct group link looks like ``facebook.com/groups/<id>`` where ``<id>`` is
either a numeric id (``2665200520405415``) or a vanity slug (``rodascienfuegos``).
We extract that id from arbitrary user text and can rebuild the canonical URL
from a stored id.

A *share* link looks like ``facebook.com/share/g/<token>``. The token is an
opaque redirect handle — not a usable group id (``facebook.com/groups/<token>``
just bounces to ``/login/``). We only extract the token here; resolving it to
the canonical numeric id happens elsewhere, by opening the rebuilt share URL and
reading its ``og:url``.
"""

from __future__ import annotations

import re

from bot.constants import (
    FACEBOOK_DOMAIN,
    FACEBOOK_GROUP_ID_CHARSET,
    FACEBOOK_GROUP_URL_TEMPLATE,
    FACEBOOK_GROUPS_PATH,
    FACEBOOK_SHARE_GROUP_SEGMENT,
    FACEBOOK_SHARE_GROUP_URL_TEMPLATE,
    FACEBOOK_SHARE_PATH,
    FACEBOOK_SHARE_TOKEN_CHARSET,
)

# The lookbehind keeps ``facebook.com`` a whole domain label, so look-alikes
# such as ``notfacebook.com`` don't match while subdomains (``m.facebook.com``)
# still do.
_GROUP_URL_RE = re.compile(
    rf"(?<![\w-]){re.escape(FACEBOOK_DOMAIN)}/{FACEBOOK_GROUPS_PATH}/({FACEBOOK_GROUP_ID_CHARSET})",
    re.IGNORECASE,
)

# Same domain anchoring, for the ``/share/g/<token>`` shortlink form.
_SHARE_GROUP_URL_RE = re.compile(
    rf"(?<![\w-]){re.escape(FACEBOOK_DOMAIN)}/{FACEBOOK_SHARE_PATH}"
    rf"/{FACEBOOK_SHARE_GROUP_SEGMENT}/({FACEBOOK_SHARE_TOKEN_CHARSET})",
    re.IGNORECASE,
)


def extract_group_id(text: str) -> str | None:
    """Return the group id embedded in *text*, or ``None`` if there isn't one."""
    match = _GROUP_URL_RE.search(text)
    return match.group(1) if match else None


def extract_group_share_token(text: str) -> str | None:
    """Return the ``/share/g/<token>`` token in *text*, or ``None`` if absent."""
    match = _SHARE_GROUP_URL_RE.search(text)
    return match.group(1) if match else None


def group_url(group_id: str) -> str:
    """Rebuild the canonical group URL from a stored *group_id*."""
    return FACEBOOK_GROUP_URL_TEMPLATE.format(group_id=group_id)


def share_group_url(token: str) -> str:
    """Rebuild the canonical share URL from a *token* so it can be resolved."""
    return FACEBOOK_SHARE_GROUP_URL_TEMPLATE.format(token=token)
