"""Serialize the browser cookie jar that authenticates the web posting engine.

A cookie-linked account stores its Facebook cookies as a ``name -> value`` map
(``c_user`` / ``xs`` / ``datr`` / ``fr`` / …). On the wire and in the database
that map is a compact JSON object; these helpers are the single place that
encodes it for storage and decodes it back for :class:`bot.facebook_web.FacebookWeb`.
"""

from __future__ import annotations

import json


def encode_cookies(cookies: dict[str, str] | None) -> str | None:
    """Serialize a cookie map to a compact JSON string for storage (``None`` passes through)."""
    if not cookies:
        return None
    return json.dumps(cookies, separators=(",", ":"))


def decode_cookies(raw: str | None) -> dict[str, str] | None:
    """Parse a stored JSON cookie string back into a map.

    Returns ``None`` for an absent/blank/invalid value or one that doesn't
    decode to a non-empty string→string object, so a malformed row degrades to
    "no cookie credential" rather than raising.
    """
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    decoded = {str(name): str(val) for name, val in value.items() if name and val}
    return decoded or None
