import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


@pytest.fixture
def s() -> Settings:
    return Settings(environment="test", jwt_secret_key=SecretStr("x" * 40))


class TestPasswords:
    def test_hash_is_argon2id_and_verifies(self) -> None:
        h = hash_password("Secret123")
        assert h.startswith("$argon2id$")
        assert verify_password("Secret123", h)

    def test_wrong_password_fails(self) -> None:
        assert not verify_password("nope", hash_password("Secret123"))

    def test_missing_hash_never_verifies(self) -> None:
        # Used for unknown emails: must run the hash and still fail.
        assert not verify_password("anything", None)

    def test_corrupt_hash_fails_closed(self) -> None:
        assert not verify_password("Secret123", "not-a-hash")


class TestAccessTokens:
    def test_round_trip(self, s: Settings) -> None:
        uid = uuid.uuid4()
        token, expires_in = create_access_token(s, user_id=uid, role="BUYER")
        claims = decode_access_token(s, token)
        assert claims.user_id == uid
        assert claims.role == "BUYER"
        assert expires_in == s.access_token_ttl_minutes * 60

    def test_expired(self, s: Settings) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        token, _ = create_access_token(s, user_id=uuid.uuid4(), role="BUYER", now=past)
        with pytest.raises(InvalidTokenError) as exc:
            decode_access_token(s, token)
        assert exc.value.reason == "expired"

    def test_wrong_secret(self, s: Settings) -> None:
        token, _ = create_access_token(s, user_id=uuid.uuid4(), role="BUYER")
        other = Settings(environment="test", jwt_secret_key=SecretStr("y" * 40))
        with pytest.raises(InvalidTokenError):
            decode_access_token(other, token)

    def test_alg_none_rejected(self, s: Settings) -> None:
        now = datetime.now(UTC)
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "role": "ADMIN",
                "type": "access",
                "iss": s.jwt_issuer,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            key=None,
            algorithm="none",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(s, forged)

    def test_wrong_token_type_rejected(self, s: Settings) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "role": "BUYER",
                "type": "refresh",
                "iss": s.jwt_issuer,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            s.jwt_secret_key.get_secret_value(),
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(s, token)


class TestRefreshTokens:
    def test_tokens_are_unique_and_hash_is_stable(self) -> None:
        a, b = generate_refresh_token(), generate_refresh_token()
        assert a != b
        assert len(a) >= 64
        assert hash_refresh_token(a) == hash_refresh_token(a)
        assert len(hash_refresh_token(a)) == 64


class TestDeployedSettings:
    def test_production_rejects_default_secret(self) -> None:
        with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
            Settings(environment="production", refresh_cookie_secure=True)

    def test_production_requires_secure_cookie(self) -> None:
        with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
            Settings(environment="production", jwt_secret_key=SecretStr("z" * 40))

    def test_production_ok_when_configured(self) -> None:
        s = Settings(
            environment="production",
            jwt_secret_key=SecretStr("z" * 40),
            refresh_cookie_secure=True,
        )
        assert s.is_deployed
