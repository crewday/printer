from __future__ import annotations

from printer_app.auth import hash_password, verify_password


def test_verify_password_respects_stored_round_count() -> None:
    stored = hash_password("secret", salt="fixed-salt", rounds=1_000)

    assert verify_password("secret", stored) is True
    assert verify_password("wrong", stored) is False


def test_verify_password_rejects_invalid_round_count() -> None:
    stored = "pbkdf2_sha256$not-int$salt$digest"

    assert verify_password("secret", stored) is False
