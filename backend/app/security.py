from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

SCRYPT_N = 16_384
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_LENGTH,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64encode(salt)}${_b64encode(key)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        calculated = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_b64decode(expected)),
        )
        return hmac.compare_digest(calculated, _b64decode(expected))
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@dataclass
class LoginLimiter:
    attempts: dict[str, deque[float]]
    window_seconds: int = 300
    max_attempts: int = 5

    @classmethod
    def create(cls) -> LoginLimiter:
        return cls(defaultdict(deque))

    def _trim(self, key: str, now: float) -> deque[float]:
        events = self.attempts[key]
        cutoff = now - self.window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        return events

    def allowed(self, key: str) -> bool:
        return len(self._trim(key, time.monotonic())) < self.max_attempts

    def record_failure(self, key: str) -> None:
        self._trim(key, time.monotonic()).append(time.monotonic())

    def clear(self, key: str) -> None:
        self.attempts.pop(key, None)
