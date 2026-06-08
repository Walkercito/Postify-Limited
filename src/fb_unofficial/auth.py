"""Login, 2FA / approval handling, session refresh, and encrypted persistence."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from .constants import ANDROID_API_KEY, ANDROID_API_SECRET, DEFAULT_REST_BASE
from .crypto import decrypt_json, encrypt_json, sign_params
from .errors import (
    FacebookApiError,
    FacebookApprovalRequired,
    FacebookAuthError,
    FacebookCheckpointRequired,
    FacebookTwoFactorRequired,
)
from .http import request
from .types import Credentials, LoadResult, Session, TwoFactorChallenge

# Subcodes inferred from reverse-engineered Facebook for Android clients.
# TOTP / SMS 2FA (user provides a 6-digit code):
_TWO_FACTOR_SUBCODES: Final[frozenset[int]] = frozenset({1348162, 1348092, 1348161, 1348556})
# "Was this you?" / Login Approval (user taps approve on another device):
_APPROVAL_SUBCODES: Final[frozenset[int]] = frozenset({1348163, 1348183, 1346748})
# "User must verify their account on www.facebook.com" — a full checkpoint the
# user clears in a browser/app, not an in-flow 2FA/approval prompt.
_CHECKPOINT_ERROR_CODE: Final[int] = 405

CodeProvider = Callable[[], Awaitable[str]]


def _new_machine_id() -> str:
    return uuid.uuid4().hex


def _base_login_params(email: str, password: str, machine_id: str) -> dict[str, str]:
    return {
        "api_key": ANDROID_API_KEY,
        "credentials_type": "password",
        "device_id": machine_id,
        "email": email,
        "format": "json",
        "generate_machine_id": "1",
        "generate_session_cookies": "1",
        "locale": "en_US",
        "method": "auth.login",
        "password": password,
        "return_ssl_resources": "0",
        "v": "1.0",
    }


def _signed(params: dict[str, str]) -> dict[str, str]:
    signed = dict(params)
    signed["sig"] = sign_params(signed, ANDROID_API_SECRET)
    return signed


async def _do_login(params: dict[str, str]) -> dict[str, Any]:
    """Send auth.login and return the raw response dict (success or error)."""
    try:
        data = await request(
            f"{DEFAULT_REST_BASE}/method/auth.login",
            method="POST",
            body=_signed(params),
            step="auth",
        )
    except FacebookApiError as exc:
        raise FacebookAuthError(f"login transport failed: {exc}") from exc
    if isinstance(data, str):
        data = _coerce_text_response(data)
    if not isinstance(data, dict):
        raise FacebookAuthError(f"unexpected login response: {data!r}")
    return data


def _coerce_text_response(text: str) -> Any:
    """Parse a raw-text login body into JSON when possible.

    Facebook's REST ``auth.login`` sometimes returns a JSON error envelope (e.g.
    a 405 verification checkpoint) with a non-JSON content type, so the HTTP
    layer hands it back as text; recover the dict so callers can inspect it.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _to_session(data: dict[str, Any], fallback_machine_id: str) -> Session:
    return Session(
        access_token=data["access_token"],
        uid=str(data.get("uid", "")),
        secret=data.get("secret"),
        session_key=data.get("session_key"),
        machine_id=data.get("machine_id") or fallback_machine_id,
        session_cookies=data.get("session_cookies") or None,
        identifier=data.get("identifier"),
        created_at=int(time.time()),
    )


def _coerce_error_data(raw: Any) -> dict[str, Any]:
    """FB returns ``error_data`` as either a dict or a JSON-encoded string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_challenge(data: dict[str, Any], email: str, fallback_machine_id: str) -> TwoFactorChallenge:
    error_data = _coerce_error_data(data.get("error_data"))
    return TwoFactorChallenge(
        email=email,
        uid=str(error_data.get("uid", "")),
        machine_id=str(error_data.get("machine_id") or fallback_machine_id),
        first_factor=str(error_data.get("login_first_factor", "")),
        subcode=data.get("error_subcode"),
    )


def _two_factor_retry_params(
    base: dict[str, str],
    challenge: TwoFactorChallenge,
    code: str,
) -> dict[str, str]:
    """Build the second-leg auth.login params using the challenge state."""
    params = dict(base)
    params["device_id"] = challenge.machine_id
    params["machine_id"] = challenge.machine_id
    params["twofactor_code"] = code
    params["first_factor"] = challenge.first_factor
    params["userid"] = challenge.uid
    params["source"] = "device_based_login"
    return params


async def _resolve_totp_code(
    totp: str | None,
    code_provider: CodeProvider | None,
) -> str | None:
    if totp is not None:
        return totp
    if code_provider is not None:
        return await code_provider()
    return None


async def login(
    *,
    email: str,
    password: str,
    machine_id: str | None = None,
    totp: str | None = None,
    code_provider: CodeProvider | None = None,
    approval_poll_seconds: float = 0.0,
    approval_poll_interval: float = 5.0,
) -> Session:
    """Log in and return a :class:`Session`.

    When Facebook prompts for 2FA, a TOTP code is resolved in this order:
    ``totp`` argument, then ``code_provider()``. If neither supplies a code,
    :class:`FacebookTwoFactorRequired` is raised carrying the challenge so the
    caller can ask the user and retry.

    When Facebook requires device approval ("Was this you?"), the login is
    retried every ``approval_poll_interval`` seconds for up to
    ``approval_poll_seconds``. If the window elapses without approval,
    :class:`FacebookApprovalRequired` is raised.
    """
    mid = machine_id or _new_machine_id()
    base = _base_login_params(email, password, mid)

    data = await _do_login(base)
    if "access_token" in data:
        return _to_session(data, mid)

    subcode = data.get("error_subcode")

    if subcode in _TWO_FACTOR_SUBCODES:
        challenge = _parse_challenge(data, email, mid)
        code = await _resolve_totp_code(totp, code_provider)
        if code is None:
            raise FacebookTwoFactorRequired(challenge)
        retry = _two_factor_retry_params(base, challenge, code)
        data2 = await _do_login(retry)
        if "access_token" in data2:
            return _to_session(data2, challenge.machine_id)
        raise FacebookAuthError(
            f"2FA verification failed: {data2.get('error_msg') or data2!r}",
        )

    if subcode in _APPROVAL_SUBCODES:
        if approval_poll_seconds > 0:
            deadline = time.monotonic() + approval_poll_seconds
            while time.monotonic() < deadline:
                await asyncio.sleep(approval_poll_interval)
                polled = await _do_login(base)
                if "access_token" in polled:
                    return _to_session(polled, mid)
                if polled.get("error_subcode") not in _APPROVAL_SUBCODES:
                    data = polled
                    break
            else:
                raise FacebookApprovalRequired(email)
        else:
            raise FacebookApprovalRequired(email)

    if data.get("error_code") == _CHECKPOINT_ERROR_CODE:
        raise FacebookCheckpointRequired(email)

    raise FacebookAuthError(f"login failed: {data.get('error_msg') or data!r}")


async def validate_session(session: Session) -> bool:
    """Cheap liveness check: hit /me with the token."""
    try:
        await request(
            "https://graph.facebook.com/me",
            query={"access_token": session.access_token, "fields": "id"},
            step="auth",
        )
        return True
    except FacebookApiError:
        return False


async def refresh_session(
    session: Session,
    credentials: Credentials,
    *,
    totp: str | None = None,
    code_provider: CodeProvider | None = None,
    approval_poll_seconds: float = 0.0,
    approval_poll_interval: float = 5.0,
) -> Session:
    """Re-login with the same machine_id to avoid triggering a checkpoint.

    2FA / approval kwargs are forwarded to :func:`login` in case FB still
    challenges the refresh (rare when ``machine_id`` is preserved).
    """
    return await login(
        email=credentials.email,
        password=credentials.password,
        machine_id=session.machine_id,
        totp=totp,
        code_provider=code_provider,
        approval_poll_seconds=approval_poll_seconds,
        approval_poll_interval=approval_poll_interval,
    )


def save_session(
    session: Session,
    *,
    path: str | Path,
    passphrase: str | None = None,
    persist_credentials: Credentials | None = None,
) -> None:
    """Persist a session to disk.

    When ``passphrase`` is given, the file is encrypted and may also include
    ``persist_credentials`` so ``refresh_session`` can run without re-prompting.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    session_data = session.model_dump(mode="json", exclude_none=True)

    if passphrase is None:
        if persist_credentials is not None:
            raise ValueError("persist_credentials requires a passphrase")
        target.write_text(json.dumps(session_data, separators=(",", ":")), encoding="utf-8")
        return

    payload: dict[str, Any] = {"session": session_data}
    if persist_credentials is not None:
        payload["credentials"] = persist_credentials.model_dump(mode="json")
    target.write_text(encrypt_json(payload, passphrase), encoding="utf-8")


def load_session(*, path: str | Path, passphrase: str | None = None) -> LoadResult:
    """Load a session (and optional credentials) from disk."""
    source = Path(path)
    blob = source.read_text(encoding="utf-8")

    if passphrase is None:
        return LoadResult(session=Session(**json.loads(blob)))

    data = decrypt_json(blob, passphrase)
    session_data = data.get("session") if isinstance(data, dict) else None
    if not isinstance(session_data, dict):
        raise FacebookAuthError("encrypted file is missing a `session` entry")

    creds_data = data.get("credentials") if isinstance(data, dict) else None
    credentials = Credentials(**creds_data) if isinstance(creds_data, dict) else None
    return LoadResult(session=Session(**session_data), credentials=credentials)
