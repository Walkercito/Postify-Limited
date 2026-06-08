"""Parse the ``session.json`` payload an admin uploads to link a Facebook account.

The capture script (``scripts/fb_capture_session.py``) emits a JSON document
whose ``session_blob`` holds the captured session under a ``session`` key (and,
for the login path, the credentials used to obtain it under ``credentials`` —
which the bot does *not* store). This module extracts just what the posting flow
needs — the Facebook ``uid`` and at least one posting credential (a Graph
``access_token`` and/or a browser ``session_cookies`` jar) — and rejects anything
malformed or credential-less.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from bot.constants import (
    SESSION_BLOB_SESSION_KEY,
    SESSION_COOKIE_NAME_KEY,
    SESSION_COOKIE_VALUE_KEY,
    SESSION_PAYLOAD_BLOB_KEY,
)
from bot.core.exceptions import InvalidSessionPayloadError


@dataclass(frozen=True, slots=True)
class CapturedSession:
    """The minimal session data the bot persists: uid + one posting credential."""

    uid: str
    access_token: str | None
    session_cookies: dict[str, str] | None


def _normalize_cookies(value: Any) -> dict[str, str] | None:
    """Coerce a cookie jar to a flat name→value map.

    Accepts either a ``{name: value}`` object (cookie-capture mode) or a list of
    cookie objects (the shape ``fb_unofficial.Session`` serializes), dropping any
    entry without both a name and a value. Returns ``None`` when nothing usable
    remains, so an empty jar reads as "no cookie credential".
    """
    if isinstance(value, dict):
        flat = {str(name): str(val) for name, val in value.items() if name and val}
        return flat or None
    if isinstance(value, list):
        collected: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get(SESSION_COOKIE_NAME_KEY)
            val = item.get(SESSION_COOKIE_VALUE_KEY)
            if name and val:
                collected[str(name)] = str(val)
        return collected or None
    return None


class _SessionBlob(BaseModel):
    """Validates the ``session`` object: a uid plus at least one credential."""

    uid: str
    access_token: str | None = None
    session_cookies: dict[str, str] | None = None

    @field_validator("session_cookies", mode="before")
    @classmethod
    def _coerce_cookies(cls, value: Any) -> dict[str, str] | None:
        return _normalize_cookies(value)

    @model_validator(mode="after")
    def _require_credential(self) -> _SessionBlob:
        if not self.uid:
            raise ValueError("session has an empty uid")
        if not self.access_token and not self.session_cookies:
            raise ValueError("session has neither an access token nor cookies")
        return self


def parse_session_payload(raw: bytes) -> CapturedSession:
    """Parse uploaded ``session.json`` bytes into a :class:`CapturedSession`.

    Raises :class:`InvalidSessionPayloadError` on anything that isn't a usable
    captured session: bad encoding/JSON, a missing ``session_blob``/``session``
    key, an empty uid, or no posting credential (neither token nor cookies).
    """
    blob = _session_blob(raw)
    try:
        session = _SessionBlob.model_validate(blob[SESSION_BLOB_SESSION_KEY])
    except KeyError as exc:
        raise InvalidSessionPayloadError(f"missing key: {exc}") from exc
    except ValidationError as exc:
        raise InvalidSessionPayloadError(f"invalid session: {exc}") from exc
    return CapturedSession(
        uid=session.uid,
        access_token=session.access_token,
        session_cookies=session.session_cookies,
    )


def _session_blob(raw: bytes) -> dict[str, Any]:
    """Extract the ``session_blob`` object from the uploaded bytes."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidSessionPayloadError(f"not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or SESSION_PAYLOAD_BLOB_KEY not in payload:
        raise InvalidSessionPayloadError(f"missing {SESSION_PAYLOAD_BLOB_KEY!r}")
    return _coerce_blob(payload[SESSION_PAYLOAD_BLOB_KEY])


def _coerce_blob(blob: Any) -> dict[str, Any]:
    """Coerce a blob value to a dict, tolerating an escaped JSON string.

    The capture script embeds the blob as a nested object, but a hand-built file
    may serialize it as an escaped JSON string; both shapes are accepted.
    """
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise InvalidSessionPayloadError(f"blob is not valid JSON: {exc}") from exc
    if not isinstance(blob, dict):
        raise InvalidSessionPayloadError(f"blob has invalid type: {type(blob).__name__}")
    return blob
