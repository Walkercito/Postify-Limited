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
    FB_WEB_UPLOAD_ERROR_SNIPPET_MAX_LENGTH,
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


def _raise_for_blocking_needles(text: str) -> None:
    """Raise the account-level failure if *text* carries a known needle.

    These two conditions end the whole run, not just one request: a rate limit
    needs a back-off, a checkpoint needs the admin to re-capture the session.
    """
    if _contains_any(text, FB_WEB_RATE_LIMIT_NEEDLES):
        raise FacebookWebRateLimitedError(
            "Facebook is rate-limiting posts from this account — try again later"
        )
    if _contains_any(text, FB_WEB_CHECKPOINT_NEEDLES):
        raise FacebookWebCheckpointError(
            "Facebook requires an account checkpoint — clear it in a browser and re-capture"
        )


def _snippet(text: str) -> str:
    """Collapse whitespace and clip *text* for inclusion in an error message."""
    return " ".join(text.split())[:FB_WEB_UPLOAD_ERROR_SNIPPET_MAX_LENGTH]


def extract_photo_id(body: str) -> str | None:
    """Lift the uploaded photo's id out of an upload response (``None`` if absent)."""
    text = _normalize(body)
    for pattern in _RE_PHOTO_IDS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def classify_upload_response(body: str) -> str:
    """Confirm an uploaded photo's id or raise the most actionable failure.

    The upload endpoint mirrors the post endpoint's habit of answering HTTP 200
    while refusing the write (Facebook soft-blocks uploads after a burst), so
    the photo id is the only success signal. With no id, the blocking needles
    steer the failure toward a back-off or re-capture; otherwise a generic
    error quotes a snippet of the body so the report shows *what* came back.
    """
    photo_id = extract_photo_id(body)
    if photo_id is not None:
        return photo_id
    text = _normalize(body)
    _raise_for_blocking_needles(text)
    raise FacebookWebError(f"photo upload failed (no photo id in the response): {_snippet(text)}")


def is_blocked_page(url: str, body: str) -> bool:
    """Whether a fetched page is a checkpoint/restriction wall, not real content.

    A cookie-authenticated GET that Facebook intercepts with a checkpoint or
    account-restriction interstitial still answers HTTP 200 with a real
    ``<title>`` — but it is the wall's title, not the group's. Callers use this to
    discard such a page (and fall back to the public scrape) rather than store the
    wall's title as if it were the group name. Both the final URL (after redirects)
    and the page body are checked against the checkpoint and restricted needles.
    """
    haystack = f"{url} {_normalize(body)}"
    return _contains_any(haystack, FB_WEB_CHECKPOINT_NEEDLES) or _contains_any(
        haystack, FB_WEB_RESTRICTED_NEEDLES
    )


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

    _raise_for_blocking_needles(text)
    if _contains_any(text, FB_WEB_RESTRICTED_NEEDLES):
        raise FacebookWebError("this account is restricted from posting to groups")
    if _contains_any(text, FB_WEB_DUPLICATE_NEEDLES):
        raise FacebookWebError("Facebook rejected the post as a duplicate")
    raise FacebookWebError("post could not be confirmed (no post id in the response)")
