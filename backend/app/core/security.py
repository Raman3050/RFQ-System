"""Password hashing and token primitives. No database or framework access here."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

_hasher = PasswordHasher()  # argon2id with library-recommended parameters

# Verified against when the email is unknown, so login takes the same time either way
# (prevents discovering registered emails by timing).
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ---------------------------------------------------------------- access tokens (JWT)


class InvalidTokenError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    role: str
    expires_at: datetime


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, role: str, now: datetime | None = None
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = now or datetime.now(UTC)
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iss": settings.jwt_issuer,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, int(ttl.total_seconds())


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pinned: never trust the token's `alg`
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "type", "role"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("invalid") from exc

    if payload.get("type") != "access":
        raise InvalidTokenError("invalid")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError("invalid") from exc
    return AccessTokenClaims(
        user_id=user_id,
        role=str(payload["role"]),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )


# ---------------------------------------------------------------- refresh tokens (opaque)


def generate_refresh_token() -> str:
    """Opaque, high-entropy token handed to the client (in an httpOnly cookie)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Only the SHA-256 digest is stored, so a DB leak does not leak usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()
