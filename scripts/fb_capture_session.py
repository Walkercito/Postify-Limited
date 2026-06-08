#!/usr/bin/env python3
"""Capture a Facebook session on a trusted device and emit ``session.json``.

Three ways to produce the file the bot admin uploads:

1. **Log in** (default): provide email + password and the script mints a token
   via Facebook's Android login. Run it on a device Facebook already trusts
   (e.g. your laptop) to sidestep the checkpoint challenges Facebook raises for
   logins from an unfamiliar host. If Facebook still challenges the login — an
   account-verification checkpoint or a "Was this you?" approval — the script
   pauses: clear it at https://www.facebook.com (the Facebook *app* is most
   reliable), then press Enter to retry. The device id is persisted to
   ``.fb_machine_id`` and reused every run, so a cleared checkpoint sticks. A
   2FA code, if asked for, is prompted inline.

2. **Bring your own token** (``--access-token``): when the login above is
   permanently checkpoint-blocked, supply an ``EAAB…`` token obtained from an
   already-authenticated session (e.g. intercepting the Facebook app's Graph
   traffic). The script verifies it against the Graph API, derives the ``uid``,
   and writes the same ``session.json`` — no email/password or login needed.

3. **Bring your own cookies** (``--cookies PATH``): when even a token is out of
   reach, export the browser cookie jar of a logged-in ``facebook.com`` tab
   (Netscape ``cookies.txt`` or a JSON export) and point the flag at it. The
   bot's cookie-native engine posts with those cookies; the ``uid`` is taken
   from the ``c_user`` cookie (override with ``--uid``). Cookies are *not*
   re-verified here — export them from a tab you know is logged in.

Usage::

    uv run python scripts/fb_capture_session.py                  # log in
    uv run python scripts/fb_capture_session.py --access-token    # paste a token
    uv run python scripts/fb_capture_session.py --cookies c.txt   # use cookies

Do NOT redirect stdout (e.g. ``> session.json``): the script writes the output
file itself, and redirecting would swallow the interactive prompts. Delete
``session.json`` once the admin has uploaded it — it holds a live credential.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import time
import uuid
from pathlib import Path

from bot.constants import (
    SESSION_ACCESS_TOKEN_KEY,
    SESSION_BLOB_CREDENTIALS_KEY,
    SESSION_BLOB_SESSION_KEY,
    SESSION_COOKIE_NAME_KEY,
    SESSION_COOKIE_USER_ID_NAME,
    SESSION_COOKIE_VALUE_KEY,
    SESSION_COOKIES_KEY,
    SESSION_CREATED_AT_KEY,
    SESSION_PAYLOAD_BLOB_KEY,
    SESSION_UID_KEY,
)
from fb_unofficial import (
    Credentials,
    Facebook,
    FacebookApprovalRequired,
    FacebookCheckpointRequired,
    FacebookError,
    login,
)

_DEFAULT_OUT = "session.json"
_MACHINE_ID_FILE = ".fb_machine_id"
_TOKEN_PROMPT_SENTINEL = "-"  # `--access-token` with no value -> prompt for it
_ERROR_HINT_MAX_LEN = 300
_JSON_START_CHARS = ("{", "[")  # a cookie file that begins with these is JSON
_NETSCAPE_COMMENT_PREFIX = "#"
_NETSCAPE_HTTPONLY_PREFIX = "#HttpOnly_"  # some exporters keep the cookie behind this
_NETSCAPE_DELIMITER = "\t"
_NETSCAPE_MIN_FIELDS = 7
_NETSCAPE_NAME_INDEX = 5
_NETSCAPE_VALUE_INDEX = 6
_LOGIN_HINTS: tuple[tuple[str, str], ...] = (
    ('"error_code":401', "invalid credentials (check the email/password)"),
    ("Invalid username or password", "invalid credentials (check the email/password)"),
    (
        '"error_code":1',
        "Facebook blocked the login from this device (checkpoint). "
        "Log in via a browser on this device first to clear it.",
    ),
    ('"error_code":406', "Facebook requires 2FA — not supported by this script"),
)
_AUTHORIZE_INSTRUCTIONS = (
    "\n⚠️  {reason}\n"
    "→ Clear it in the Facebook *app* (most reliable) or at https://www.facebook.com,\n"
    "  signed in as this account, from the same network you're running this on.\n"
    "  Then press Enter here to retry — or Ctrl-C / Ctrl-D to abort.\n"
)


def _prompt(text: str) -> str:
    # input() writes its prompt to stdout, which would be swallowed under ``>``
    # redirection; force it to stderr so it's always visible.
    sys.stderr.write(text)
    sys.stderr.flush()
    return input().strip()


def _explain_login_error(msg: str) -> str:
    """Map fb_unofficial's raw error message to a one-line hint."""
    for needle, hint in _LOGIN_HINTS:
        if needle in msg:
            return hint
    return msg.split("\n", 1)[0][:_ERROR_HINT_MAX_LEN]


def _build_upload(
    blob: dict[str, object],
    first_name: str | None,
    full_name: str | None,
    picture_url: str | None,
) -> dict[str, object]:
    """Assemble the JSON document the bot admin uploads."""
    return {
        SESSION_PAYLOAD_BLOB_KEY: blob,
        "first_name": first_name,
        "full_name": full_name,
        "picture_url": picture_url,
    }


def _resolve_machine_id(args: argparse.Namespace) -> str:
    """Reuse a persisted device id so a cleared checkpoint stays cleared.

    A fresh ``machine_id`` every run looks like a brand-new device to Facebook
    and re-triggers verification, so we store one and reuse it across runs.
    """
    if args.machine_id:
        return str(args.machine_id)
    path = Path(args.machine_id_file)
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    machine_id = uuid.uuid4().hex
    path.write_text(machine_id + "\n", encoding="utf-8")
    print(f"new device id saved to {path} — keep it so the trust sticks.", file=sys.stderr)
    return machine_id


async def _prompt_totp() -> str:
    """Supply a 2FA code if Facebook challenges the login with one."""
    return _prompt("2FA code (from your authenticator app): ")


async def _capture(email: str, password: str, machine_id: str) -> dict[str, object]:
    """Log in, best-effort fetch the profile, and build the upload payload."""
    print("logging in…", file=sys.stderr)
    session = await login(
        email=email,
        password=password,
        machine_id=machine_id,
        code_provider=_prompt_totp,
    )

    first_name: str | None = None
    full_name: str | None = None
    picture_url: str | None = None
    try:
        profile = await Facebook.from_session(session).get_profile()
        first_name, full_name, picture_url = profile.first_name, profile.name, profile.picture_url
    except Exception as exc:  # best-effort: a missing profile must not abort capture
        print(f"warning: profile fetch failed: {exc}", file=sys.stderr)

    blob = {
        SESSION_BLOB_SESSION_KEY: session.model_dump(mode="json", exclude_none=True),
        SESSION_BLOB_CREDENTIALS_KEY: Credentials(email=email, password=password).model_dump(),
    }
    print(f"ok: fb_uid={session.uid}", file=sys.stderr)
    return _build_upload(blob, first_name, full_name, picture_url)


async def _capture_from_token(token: str, uid_override: str | None) -> dict[str, object]:
    """Verify an existing access token via Graph and build the upload payload.

    Unlike the login path, the profile fetch here is the *verification* — if the
    token is dead it raises and the caller aborts rather than writing a useless
    ``session.json``.
    """
    print("verifying token…", file=sys.stderr)
    profile = await Facebook(token).get_profile()
    uid = uid_override or profile.id
    session_dict = {
        SESSION_ACCESS_TOKEN_KEY: token,
        SESSION_UID_KEY: uid,
        SESSION_CREATED_AT_KEY: int(time.time()),
    }
    blob = {SESSION_BLOB_SESSION_KEY: session_dict}
    print(f"ok: fb_uid={uid}", file=sys.stderr)
    return _build_upload(blob, profile.first_name, profile.name, profile.picture_url)


def _cookies_from_json(text: str) -> dict[str, str]:
    """Parse a browser-extension JSON cookie export into a name→value map.

    Accepts either a ``{name: value}`` object or the list-of-cookie-objects shape
    exporters like Cookie-Editor produce (each with ``name`` / ``value`` keys).
    """
    data = json.loads(text)
    if isinstance(data, dict):
        return {str(name): str(val) for name, val in data.items() if name and val}
    if isinstance(data, list):
        jar: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get(SESSION_COOKIE_NAME_KEY)
            val = item.get(SESSION_COOKIE_VALUE_KEY)
            if name and val:
                jar[str(name)] = str(val)
        return jar
    raise ValueError("cookie JSON must be an object or a list of cookie objects")


def _cookies_from_netscape(text: str) -> dict[str, str]:
    """Parse a Netscape ``cookies.txt`` file into a name→value map."""
    jar: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(_NETSCAPE_HTTPONLY_PREFIX):
            line = line[len(_NETSCAPE_HTTPONLY_PREFIX) :]
        elif not line or line.startswith(_NETSCAPE_COMMENT_PREFIX):
            continue
        fields = line.split(_NETSCAPE_DELIMITER)
        if len(fields) < _NETSCAPE_MIN_FIELDS:
            continue
        name, val = fields[_NETSCAPE_NAME_INDEX], fields[_NETSCAPE_VALUE_INDEX]
        if name and val:
            jar[name] = val
    return jar


def _parse_cookie_file(path: Path) -> dict[str, str]:
    """Read *path* and parse it as JSON or Netscape cookies, by content sniff."""
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith(_JSON_START_CHARS):
        return _cookies_from_json(text)
    return _cookies_from_netscape(text)


def _capture_from_cookies(cookie_path: str, uid_override: str | None) -> dict[str, object]:
    """Parse a browser cookie export and build a cookie-mode upload payload.

    The ``uid`` comes from the ``c_user`` cookie (or ``--uid``). Cookies are not
    re-verified — export them from a tab you know is logged in.
    """
    print("reading cookies…", file=sys.stderr)
    path = Path(cookie_path)
    if not path.exists():
        raise FileNotFoundError(cookie_path)
    jar = _parse_cookie_file(path)
    if not jar:
        raise ValueError("no cookies found in the file")
    uid = uid_override or jar.get(SESSION_COOKIE_USER_ID_NAME)
    if not uid:
        raise ValueError(
            f"could not derive the uid — cookie {SESSION_COOKIE_USER_ID_NAME!r} is missing "
            "(pass --uid to set it explicitly)"
        )
    session_dict = {
        SESSION_COOKIES_KEY: jar,
        SESSION_UID_KEY: uid,
        SESSION_CREATED_AT_KEY: int(time.time()),
    }
    blob = {SESSION_BLOB_SESSION_KEY: session_dict}
    print(f"ok: fb_uid={uid} ({len(jar)} cookies)", file=sys.stderr)
    return _build_upload(blob, None, None, None)


def _wait_for_authorization(reason: str) -> bool:
    """Pause until the user clears the challenge. ``False`` if they abort."""
    sys.stderr.write(_AUTHORIZE_INSTRUCTIONS.format(reason=reason))
    sys.stderr.flush()
    try:
        input()
    except EOFError:
        return False
    return True


def _capture_with_retry(email: str, password: str, machine_id: str) -> dict[str, object] | None:
    """Run capture, waiting for the user to clear any verification challenge."""
    while True:
        try:
            return asyncio.run(_capture(email, password, machine_id))
        except (FacebookApprovalRequired, FacebookCheckpointRequired) as exc:
            if not _wait_for_authorization(str(exc)):
                print("aborted.", file=sys.stderr)
                return None
        except FacebookError as exc:
            print(f"error: login failed — {_explain_login_error(str(exc))}", file=sys.stderr)
            return None


def _write_payload(out: str, payload: dict[str, object]) -> int:
    out_path = Path(out)
    out_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {out_path.resolve()} — upload it to the bot, then delete it.", file=sys.stderr)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a Facebook session to session.json.")
    parser.add_argument("--email", help="Facebook account email (prompts if omitted)")
    parser.add_argument(
        "--password",
        help="Facebook password (prompts if omitted; avoid on the CLI — it lands in shell history)",
    )
    parser.add_argument(
        "--access-token",
        nargs="?",
        const=_TOKEN_PROMPT_SENTINEL,
        help="capture from an existing EAAB token instead of logging in; pass the token, "
        "or use the flag alone to be prompted for it (not echoed)",
    )
    parser.add_argument(
        "--cookies",
        metavar="PATH",
        help="capture from a browser cookie export (Netscape cookies.txt or JSON) instead of "
        "logging in; the uid is read from the c_user cookie",
    )
    parser.add_argument(
        "--uid",
        help="Facebook user id for --access-token / --cookies mode "
        "(default: derived from the token or the c_user cookie)",
    )
    parser.add_argument(
        "--out", default=_DEFAULT_OUT, help=f"output path (default: ./{_DEFAULT_OUT})"
    )
    parser.add_argument(
        "--machine-id",
        help="reuse a specific device id (default: persisted in .fb_machine_id)",
    )
    parser.add_argument(
        "--machine-id-file",
        default=_MACHINE_ID_FILE,
        help=f"where the device id is stored (default: ./{_MACHINE_ID_FILE})",
    )
    return parser.parse_args()


def _run_cookies_mode(args: argparse.Namespace) -> int:
    try:
        payload = _capture_from_cookies(args.cookies, args.uid)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not read cookies — {exc}", file=sys.stderr)
        return 1
    return _write_payload(args.out, payload)


def _run_token_mode(args: argparse.Namespace) -> int:
    flagged = args.access_token
    token = (
        getpass.getpass("access token: ", stream=sys.stderr)
        if flagged == _TOKEN_PROMPT_SENTINEL
        else flagged
    ).strip()
    if not token:
        print("error: no access token provided.", file=sys.stderr)
        return 1
    try:
        payload = asyncio.run(_capture_from_token(token, args.uid))
    except KeyboardInterrupt:
        print("\naborted.", file=sys.stderr)
        return 130
    except FacebookError as exc:
        print(f"error: token rejected — {_explain_login_error(str(exc))}", file=sys.stderr)
        return 1
    return _write_payload(args.out, payload)


def _run_password_mode(args: argparse.Namespace) -> int:
    email = args.email or _prompt("email: ")
    password = args.password or getpass.getpass("password: ", stream=sys.stderr)
    machine_id = _resolve_machine_id(args)
    try:
        payload = _capture_with_retry(email=email, password=password, machine_id=machine_id)
    except KeyboardInterrupt:
        print("\naborted.", file=sys.stderr)
        return 130
    if payload is None:
        return 1
    return _write_payload(args.out, payload)


def main() -> int:
    args = _parse_args()
    if args.cookies is not None:
        return _run_cookies_mode(args)
    if args.access_token is not None:
        return _run_token_mode(args)
    return _run_password_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
