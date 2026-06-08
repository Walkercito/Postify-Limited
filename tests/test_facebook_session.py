"""Tests for parsing the uploaded ``session.json`` payload."""

from __future__ import annotations

import json

import pytest

from bot.constants import (
    SESSION_BLOB_SESSION_KEY,
    SESSION_PAYLOAD_BLOB_KEY,
)
from bot.core.exceptions import InvalidSessionPayloadError
from bot.facebook_session import parse_session_payload

FB_UID = "100012345678901"
FB_TOKEN = "EAABwz-token"
FB_COOKIES = {"c_user": FB_UID, "xs": "secret-xs"}


def _session() -> dict[str, object]:
    return {"access_token": FB_TOKEN, "uid": FB_UID, "created_at": 1700000000}


def _payload(blob: object) -> bytes:
    return json.dumps({SESSION_PAYLOAD_BLOB_KEY: blob}).encode("utf-8")


def test_parses_nested_blob() -> None:
    raw = _payload({SESSION_BLOB_SESSION_KEY: _session(), "credentials": {"x": 1}})

    captured = parse_session_payload(raw)

    assert captured.uid == FB_UID
    assert captured.access_token == FB_TOKEN


def test_parses_string_encoded_blob() -> None:
    blob = json.dumps({SESSION_BLOB_SESSION_KEY: _session()})
    raw = _payload(blob)

    captured = parse_session_payload(raw)

    assert captured.uid == FB_UID
    assert captured.access_token == FB_TOKEN


def test_rejects_non_json() -> None:
    with pytest.raises(InvalidSessionPayloadError):
        parse_session_payload(b"not json at all")


def test_rejects_missing_blob() -> None:
    raw = json.dumps({"something": "else"}).encode("utf-8")

    with pytest.raises(InvalidSessionPayloadError):
        parse_session_payload(raw)


def test_rejects_missing_session_key() -> None:
    raw = _payload({"credentials": {"x": 1}})

    with pytest.raises(InvalidSessionPayloadError):
        parse_session_payload(raw)


def test_rejects_empty_uid() -> None:
    session = _session()
    session["uid"] = ""
    raw = _payload({SESSION_BLOB_SESSION_KEY: session})

    with pytest.raises(InvalidSessionPayloadError):
        parse_session_payload(raw)


def test_rejects_invalid_session_shape() -> None:
    raw = _payload({SESSION_BLOB_SESSION_KEY: {"uid": FB_UID}})  # neither token nor cookies

    with pytest.raises(InvalidSessionPayloadError):
        parse_session_payload(raw)


def test_parses_cookie_session() -> None:
    session = {"uid": FB_UID, "session_cookies": FB_COOKIES}
    raw = _payload({SESSION_BLOB_SESSION_KEY: session})

    captured = parse_session_payload(raw)

    assert captured.uid == FB_UID
    assert captured.access_token is None
    assert captured.session_cookies == FB_COOKIES


def test_parses_cookie_list_shape() -> None:
    # Some exports serialize cookies as a list of {name, value} objects.
    session = {
        "uid": FB_UID,
        "session_cookies": [
            {"name": "c_user", "value": FB_UID},
            {"name": "xs", "value": "secret-xs"},
        ],
    }
    raw = _payload({SESSION_BLOB_SESSION_KEY: session})

    captured = parse_session_payload(raw)

    assert captured.session_cookies == FB_COOKIES


def test_parses_session_with_token_and_cookies() -> None:
    session = {"uid": FB_UID, "access_token": FB_TOKEN, "session_cookies": FB_COOKIES}
    raw = _payload({SESSION_BLOB_SESSION_KEY: session})

    captured = parse_session_payload(raw)

    assert captured.access_token == FB_TOKEN
    assert captured.session_cookies == FB_COOKIES


def test_rejects_empty_cookie_jar_without_token() -> None:
    session = {"uid": FB_UID, "session_cookies": {}}
    raw = _payload({SESSION_BLOB_SESSION_KEY: session})

    with pytest.raises(InvalidSessionPayloadError):
        parse_session_payload(raw)
