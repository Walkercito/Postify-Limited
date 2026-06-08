"""MD5 signing + scrypt/AES-GCM envelope for encrypting session files."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_SCRYPT_N: Final[int] = 2**15
_SCRYPT_R: Final[int] = 8
_SCRYPT_P: Final[int] = 1
_KEY_LEN: Final[int] = 32
_SALT_LEN: Final[int] = 16
_NONCE_LEN: Final[int] = 12
_ENVELOPE_VERSION: Final[int] = 1


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def sign_params(params: dict[str, str], secret: str) -> str:
    """Facebook's legacy MD5 signing: sorted k=v concatenation + secret, md5."""
    items = sorted(params.items())
    raw = "".join(f"{k}={v}" for k, v in items) + secret
    return md5_hex(raw)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_json(payload: Any, passphrase: str) -> str:
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(passphrase, salt)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    envelope = {
        "v": _ENVELOPE_VERSION,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":"))


def decrypt_json(blob: str, passphrase: str) -> Any:
    envelope = json.loads(blob)
    if envelope.get("v") != _ENVELOPE_VERSION:
        raise ValueError(f"unsupported envelope version {envelope.get('v')!r}")
    salt = base64.b64decode(envelope["salt"])
    nonce = base64.b64decode(envelope["nonce"])
    ciphertext = base64.b64decode(envelope["ct"])
    key = _derive_key(passphrase, salt)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
    return json.loads(plaintext.decode("utf-8"))
