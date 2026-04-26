from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

SECRET_PREFIX = "enc:v1:"


def secret_key_configured() -> bool:
    return bool(os.environ.get("PRINTER_CONFIG_SECRET_KEY"))


def is_encrypted_secret(value: object) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_PREFIX)


def encrypt_secret(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    if is_encrypted_secret(value):
        return value
    key = _fernet_key()
    if key is None:
        return value
    encrypted = Fernet(key).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{SECRET_PREFIX}{encrypted}"


def decrypt_secret(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    if not is_encrypted_secret(value):
        return value
    key = _fernet_key()
    if key is None:
        raise ValueError("PRINTER_CONFIG_SECRET_KEY is required for encrypted config")
    token = value[len(SECRET_PREFIX) :].encode("ascii")
    try:
        return Fernet(key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("encrypted config secret could not be decrypted") from exc


def _fernet_key() -> bytes | None:
    raw = os.environ.get("PRINTER_CONFIG_SECRET_KEY")
    if not raw:
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)
