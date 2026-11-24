from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.core.config import Settings
from app.schemas.auth import (
    AcceptInviteRequest,
    AuthResponse,
    InviteInfo,
    InviteTokenRequest,
    LoginRequest,
    RegisterRequest,
    UserRead,
)
from app.services.auth_service import AuthService, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, settings: Settings, issued: IssuedTokens) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=issued.refresh_token,
        expires=issued.refresh_expires_at,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def _auth_response(response: Response, settings: Settings, issued: IssuedTokens) -> AuthResponse:
    _set_refresh_cookie(response, settings, issued)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(
        access_token=issued.access_token,
        expires_in=issued.access_expires_in,
        user=UserRead.model_validate(issued.user),
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a buyer account and start a session (suppliers are invite-only)",
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: DbSession,
    settings: SettingsDep,
) -> AuthResponse:
    issued = await AuthService(session, settings).register(
        body, user_agent=request.headers.get("user-agent")
    )
    return _auth_response(response, settings, issued)


@router.post(
    "/invitations/inspect",
    response_model=InviteInfo,
    summary="Look up a supplier invite link (to pre-fill the sign-up form)",
)
async def inspect_invite(
    body: InviteTokenRequest, session: DbSession, settings: SettingsDep
) -> InviteInfo:
    return await AuthService(session, settings).inspect_invite(body.token)


@router.post(
    "/invitations/accept",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a supplier account from an invite link and start a session",
)
async def accept_invite(
    body: AcceptInviteRequest,
    request: Request,
    response: Response,
    session: DbSession,
    settings: SettingsDep,
) -> AuthResponse:
    issued = await AuthService(session, settings).accept_invite(
        body, user_agent=request.headers.get("user-agent")
    )
    return _auth_response(response, settings, issued)


@router.post("/login", response_model=AuthResponse, summary="Log in with email and password")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
    settings: SettingsDep,
) -> AuthResponse:
    issued = await AuthService(session, settings).login(
        body, user_agent=request.headers.get("user-agent")
    )
    return _auth_response(response, settings, issued)


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Rotate the refresh-token cookie and get a new access token",
)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    settings: SettingsDep,
    rfq_refresh: Annotated[str | None, Cookie(include_in_schema=False)] = None,
) -> AuthResponse:
    # Read by configured name; the parameter above only documents the default.
    raw = request.cookies.get(settings.refresh_cookie_name, rfq_refresh)
    issued = await AuthService(session, settings).refresh(
        raw, user_agent=request.headers.get("user-agent")
    )
    return _auth_response(response, settings, issued)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
)
async def logout(request: Request, session: DbSession, settings: SettingsDep) -> Response:
    await AuthService(session, settings).logout(request.cookies.get(settings.refresh_cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/me", response_model=UserRead, summary="The authenticated user")
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
