"""Liveness and readiness probes.

- /health/live  : process is up (no dependency checks) — for restart decisions.
- /health/ready : Postgres and Redis reachable — for load-balancer routing.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.cache.redis import ping_redis
from app.db.session import ping_db

router = APIRouter(prefix="/health", tags=["health"])

CHECK_TIMEOUT_SECONDS = 2.0


class DependencyStatus(BaseModel):
    status: Literal["ok", "error"]
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    server_time: datetime
    checks: dict[str, DependencyStatus] = {}


Check = Callable[[], Awaitable[None]]


def readiness_checks(request: Request) -> dict[str, Check]:
    state = request.app.state
    return {
        "postgres": lambda: ping_db(state.engine),
        "redis": lambda: ping_redis(state.redis),
    }


async def _run(check: Check) -> DependencyStatus:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        return DependencyStatus(status="ok")
    except Exception as exc:  # report, never raise, from a probe
        return DependencyStatus(status="error", error=type(exc).__name__)


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok", server_time=datetime.now(UTC))


@router.get("/ready", response_model=HealthResponse)
async def ready(
    response: Response, checks: dict[str, Check] = Depends(readiness_checks)
) -> HealthResponse:
    results = await asyncio.gather(*(_run(c) for c in checks.values()))
    by_name = dict(zip(checks.keys(), results, strict=True))
    healthy = all(r.status == "ok" for r in results)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        server_time=datetime.now(UTC),
        checks=by_name,
    )
