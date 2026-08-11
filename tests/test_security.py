from __future__ import annotations

from app.security import LoginLimiter, hash_password, token_digest, verify_password


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct-horse-battery")

    assert encoded.startswith("scrypt$")
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("incorrect-password", encoded)
    assert not verify_password("correct-horse-battery", "invalid")


def test_short_passwords_are_rejected() -> None:
    try:
        hash_password("too-short")
    except ValueError as exc:
        assert "12" in str(exc)
    else:
        raise AssertionError("short password was accepted")


def test_session_tokens_are_not_stored_verbatim() -> None:
    digest = token_digest("sample-token")

    assert digest != "sample-token"
    assert len(digest) == 64


def test_login_limiter_blocks_after_five_failures() -> None:
    limiter = LoginLimiter.create()

    for _ in range(5):
        assert limiter.allowed("127.0.0.1")
        limiter.record_failure("127.0.0.1")

    assert not limiter.allowed("127.0.0.1")
    limiter.clear("127.0.0.1")
    assert limiter.allowed("127.0.0.1")
