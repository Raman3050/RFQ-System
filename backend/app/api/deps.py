"""Shared FastAPI dependencies: settings, DB session, current user, role checks."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository

# auto_error=False so we return our own problem+json 401 instead of FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication required", code="NOT_AUTHENTICATED")
    try:
        claims = decode_access_token(settings, credentials.credentials)
    except InvalidTokenError as exc:
        code = "TOKEN_EXPIRED" if exc.reason == "expired" else "TOKEN_INVALID"
        raise AuthenticationError("Access token is invalid or expired", code=code) from exc

    # Load the user every request so deactivation and role changes apply immediately.
    # Own short session: the pooled connection is released at once instead of being held
    # for the whole request (which matters while bids queue for an auction).
    async with request.app.state.sessionmaker() as session:
        user = await UserRepository(session).get(claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account not found or disabled", code="TOKEN_INVALID")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: `Depends(require_roles(UserRole.BUYER))`."""
    allowed = frozenset(roles)

    async def _check(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError(
                "You do not have permission to perform this action",
                code="FORBIDDEN_ROLE",
                extra={"required_roles": sorted(r.value for r in allowed)},
            )
        return user

    return _check


BuyerUser = Annotated[User, Depends(require_roles(UserRole.BUYER, UserRole.ADMIN))]
SupplierUser = Annotated[User, Depends(require_roles(UserRole.SUPPLIER))]
