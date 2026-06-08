"""Classify the GraphQL response of a cookie-native group post.

Facebook answers HTTP 200 even when a write fails, may prefix the body with an
anti-JSON-hijack token, escapes quotes inside streamed deferred fragments, and
sprinkles benign ``errors`` that do not mean the post failed. So success is
confirmed *only* by lifting a real ``post_id`` out of the body — anything else
is treated as a failure and mapped to the most actionable exception we can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bot.constants import (
    FB_WEB_CHECKPOINT_NEEDLES,
    FB_WEB_DUPLICATE_NEEDLES,
    FB_WEB_GROUP_PENDING_URL_TEMPLATE,
    FB_WEB_GROUP_POST_URL_TEMPLATE,
    FB_WEB_JSON_HIJACK_PREFIXES,
    FB_WEB_PENDING_POSTS_MARKER,
    FB_WEB_PHOTO_ID_KEYS,
    FB_WEB_POST_ID_MIN_DIGITS,
    FB_WEB_RATE_LIMIT_NEEDLES,
    FB_WEB_RESTRICTED_NEEDLES,
)
from bot.core.exceptions import (
    FacebookWebCheckpointError,
    FacebookWebError,
    FacebookWebRateLimitedError,
)

_RE_POST_ID = re.compile(r'"post_id":"(\d+)"')
# One ``"<key>":"<digits>"`` matcher per accepted photo-id key (photoID / …).
_RE_PHOTO_IDS = tuple(re.compile(rf'"{key}":"(\d+)"') for key in FB_WEB_PHOTO_ID_KEYS)


@dataclass(frozen=True, slots=True)
class WebPostOutcome:
    """A confirmed group post: its id, permalink, and whether it awaits approval."""

    post_id: str
    url: str
    pending: bool


def _normalize(body: str) -> str:
    """Strip the anti-hijack prefix and the JSON escaping so needles/ids match."""
    cleaned = body
    for prefix in FB_WEB_JSON_HIJACK_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return cleaned.replace("\\", "")


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _first_post_id(text: str) -> str | None:
    """Return the first ``post_id`` with enough digits to be a real story id."""
    for match in _RE_POST_ID.finditer(text):
        post_id = match.group(1)
        if len(post_id) >= FB_WEB_POST_ID_MIN_DIGITS:
            return post_id
    return None


def extract_photo_id(body: str) -> str | None:
    """Lift the uploaded photo's id out of an upload response (``None`` if absent)."""
    text = _normalize(body)
    for pattern in _RE_PHOTO_IDS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def classify_post_response(body: str, *, group_id: str) -> WebPostOutcome:
    """Confirm a real ``post_id`` or raise the most actionable failure.

    A positive id always wins: streamed fragments may carry benign ``errors``
    yet still report a created story. With no id, the localized needles steer the
    failure toward a back-off (rate limit), a re-capture (checkpoint), or a plain
    domain error (restricted / duplicate / unconfirmed).
    """
    text = _normalize(body)

    post_id = _first_post_id(text)
    if post_id is not None:
        pending = f"{FB_WEB_PENDING_POSTS_MARKER}/{post_id}" in text
        template = FB_WEB_GROUP_PENDING_URL_TEMPLATE if pending else FB_WEB_GROUP_POST_URL_TEMPLATE
        url = template.format(group_id=group_id, post_id=post_id)
        return WebPostOutcome(post_id=post_id, url=url, pending=pending)

    if _contains_any(text, FB_WEB_RATE_LIMIT_NEEDLES):
        raise FacebookWebRateLimitedError(
            "Facebook is rate-limiting posts from this account — try again later"
        )
    if _contains_any(text, FB_WEB_CHECKPOINT_NEEDLES):
        raise FacebookWebCheckpointError(
            "Facebook requires an account checkpoint — clear it in a browser and re-capture"
        )
    if _contains_any(text, FB_WEB_RESTRICTED_NEEDLES):
        raise FacebookWebError("this account is restricted from posting to groups")
    if _contains_any(text, FB_WEB_DUPLICATE_NEEDLES):
        raise FacebookWebError("Facebook rejected the post as a duplicate")
    raise FacebookWebError("post could not be confirmed (no post id in the response)")
