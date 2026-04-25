from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt_bytes = (salt or secrets.token_hex(16)).encode("ascii")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, 200_000)
    salt_text = salt_bytes.decode("ascii")
    digest_text = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256$200000${salt_text}${digest_text}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, rounds_raw, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = hash_password(password, salt=salt).split("$", 3)[3]
    _ = rounds_raw
    return hmac.compare_digest(expected, digest)


def configured_password_hash(config_hash: str | None) -> str | None:
    env_password = os.environ.get("PRINTER_UI_PASSWORD")
    if env_password:
        return hash_password(env_password, salt="env")
    return config_hash
