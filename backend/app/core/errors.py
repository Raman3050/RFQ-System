"""Domain errors and RFC 7807 (problem+json) exception handlers."""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

PROBLEM_JSON = "application/problem+json"
log = get_logger(__name__)


class AppError(Exception):
    """Base class for expected, client-facing errors.

    Subclasses set `status_code` and a stable machine-readable `code`
    (e.g. AUCTION_CLOSED) that the frontend can switch on.
    """

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "BAD_REQUEST"
    headers: Mapping[str, str] | None = None

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        self.extra = extra or {}


class AuthenticationError(AppError):
    """401 — missing, invalid or expired credentials. `code` says which."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "NOT_AUTHENTICATED"
    headers = {"WWW-Authenticate": "Bearer"}  # noqa: RUF012 - read-only class constant


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "CONFLICT"


class PermissionDeniedError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "FORBIDDEN"


def _problem(
    request: Request,
    status: int,
    code: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    err = cast(AppError, exc)
    return _problem(request, err.status_code, err.code, err.detail, err.extra, err.headers)


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    err = cast(StarletteHTTPException, exc)
    code = HTTPStatus(err.status_code).name
    return _problem(request, err.status_code, code, str(err.detail), headers=err.headers)


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    err = cast(RequestValidationError, exc)
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in err.errors()
    ]
    return _problem(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "VALIDATION_ERROR",
        "Request validation failed",
        {"errors": errors},
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path)
    return _problem(
        request,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
