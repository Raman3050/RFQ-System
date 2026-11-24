"""Authentication use-cases: register, login, refresh-token rotation, logout.

The service owns the transaction boundary (commit) for each use-case.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.models.user import User
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    user: User
    access_token: str
    access_expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def register(self, data: RegisterRequest, *, user_agent: str | None) -> IssuedTokens:
        if await self.users.get_by_email(data.email):
            raise ConflictError("An account with this email already exists", code="EMAIL_TAKEN")

        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            company_name=data.company_name,
            role=data.role,
            last_login_at=func.now(),
        )
        try:
            await self.users.add(user)
        except IntegrityError as exc:  # lost a race with a concurrent sign-up
            await self.session.rollback()
            raise ConflictError(
                "An account with this email already exists", code="EMAIL_TAKEN"
            ) from exc

        issued = await self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        await self.session.commit()
        log.info("user_registered", user_id=str(user.id), role=user.role.value)
        return issued

    async def login(self, data: LoginRequest, *, user_agent: str | None) -> IssuedTokens:
        user = await self.users.get_by_email(data.email)
        # verify_password always runs (against a dummy hash if no user) to keep timing flat.
        password_ok = verify_password(data.password, user.password_hash if user else None)
        if user is None or not password_ok:
            log.info("login_failed", reason="bad_credentials")
            raise AuthenticationError("Invalid email or password", code="INVALID_CREDENTIALS")
        if not user.is_active:
            raise AuthenticationError("This account is disabled", code="ACCOUNT_DISABLED")

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
        user.last_login_at = func.now()

        issued = await self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        await self.session.commit()
        log.info("login_succeeded", user_id=str(user.id))
        return issued

    async def refresh(self, raw_token: str | None, *, user_agent: str | None) -> IssuedTokens:
        if not raw_token:
            raise AuthenticationError("No active session", code="REFRESH_TOKEN_MISSING")

        stored = await self.tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if stored is None:
            raise AuthenticationError("Session is invalid", code="REFRESH_TOKEN_INVALID")

        if stored.revoked_at is not None:
            if not await self.tokens.family_has_active_token(stored.family_id):
                # Session already ended (logout or earlier revocation): nothing to protect.
                raise AuthenticationError("Session has ended", code="REFRESH_TOKEN_INVALID")
            # A rotated token was replayed while the session is live: assume theft and
            # kill every token in the family.
            await self.tokens.revoke_family(stored.family_id)
            await self.session.commit()
            log.warning(
                "refresh_token_reuse_detected",
                user_id=str(stored.user_id),
                family_id=str(stored.family_id),
            )
            raise AuthenticationError(
                "Session was revoked. Please log in again.", code="REFRESH_TOKEN_REUSED"
            )

        if stored.expires_at <= datetime.now(UTC):
            raise AuthenticationError("Session expired", code="REFRESH_TOKEN_EXPIRED")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            await self.tokens.revoke_family(stored.family_id)
            await self.session.commit()
            raise AuthenticationError("This account is disabled", code="ACCOUNT_DISABLED")

        await self.tokens.revoke(stored)
        issued = await self._issue(user, family_id=stored.family_id, user_agent=user_agent)
        await self.session.commit()
        return issued

    async def logout(self, raw_token: str | None) -> None:
        """Revokes the whole session (token family). Idempotent."""
        if not raw_token:
            return
        stored = await self.tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if stored is not None:
            await self.tokens.revoke_family(stored.family_id)
            await self.session.commit()
            log.info("logout", user_id=str(stored.user_id))

    async def _issue(
        self, user: User, *, family_id: uuid.UUID, user_agent: str | None
    ) -> IssuedTokens:
        access_token, expires_in = create_access_token(
            self.settings, user_id=user.id, role=user.role.value
        )
        refresh_token = generate_refresh_token()
        refresh_expires_at = datetime.now(UTC) + timedelta(
            days=self.settings.refresh_token_ttl_days
        )
        await self.tokens.add(
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
        )
        await self.session.refresh(user)  # resolve server-side defaults (func.now())
        return IssuedTokens(
            user=user,
            access_token=access_token,
            access_expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
        )
