from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

PASSWORD_HASH_ROUNDS = 200_000


def hash_password(
    password: str,
    *,
    salt: str | None = None,
    rounds: int = PASSWORD_HASH_ROUNDS,
) -> str:
    if rounds < 1:
        raise ValueError("password hash rounds must be positive")
    salt_bytes = (salt or secrets.token_hex(16)).encode("ascii")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, rounds)
    salt_text = salt_bytes.decode("ascii")
    digest_text = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${rounds}${salt_text}${digest_text}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, rounds_raw, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_raw)
    except ValueError:
        return False
    if rounds < 1:
        return False
    expected = hash_password(password, salt=salt, rounds=rounds).split("$", 3)[3]
    return hmac.compare_digest(expected, digest)


def configured_password_hash(config_hash: str | None) -> str | None:
    env_password = os.environ.get("PRINTER_UI_PASSWORD")
    if env_password:
        return hash_password(env_password, salt="env")
    return config_hash


API_TOKEN_PREFIX = "cpt_"


def generate_api_token() -> tuple[str, str, str]:
    raw = secrets.token_hex(32)
    token = f"{API_TOKEN_PREFIX}{raw}"
    prefix = token[:12]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, prefix, token_hash


def verify_api_token(token: str, stored_hash: str) -> bool:
    computed = hashlib.sha256(token.encode()).hexdigest()
    return hmac.compare_digest(computed, stored_hash)


SCOPE_ALLOWED_PATHS: dict[str, frozenset[str]] = {
    "print": frozenset({"/api/receipts/print"}),
}


def scope_allows_path(scope: str, method: str, path: str) -> bool:
    allowed = SCOPE_ALLOWED_PATHS.get(scope, frozenset())
    return path in allowed and method.upper() == "POST"
