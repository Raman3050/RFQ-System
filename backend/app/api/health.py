"""Liveness and readiness probes.

- /health/live  : process is up (no dependency checks) — for restart decisions.
- /health/ready : Postgres and Redis reachable — for load-balancer routing. Also reports
                  the lifecycle worker's heartbeat (informational: the API keeps serving
                  if the worker is down, because readers derive status from the clock).
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.cache.redis import ping_redis
from app.db.session import ping_db

router = APIRouter(prefix="/health", tags=["health"])

CHECK_TIMEOUT_SECONDS = 2.0
WORKER_HEARTBEAT_KEY = "worker:lifecycle:heartbeat"  # written by app.workers.lifecycle
WORKER_STALE_AFTER_SECONDS = 10


class DependencyStatus(BaseModel):
    status: Literal["ok", "error"]
    error: str | None = None


class WorkerStatus(BaseModel):
    status: Literal["ok", "stale", "missing", "unknown"]
    last_seen_at: datetime | None = None
    seconds_ago: float | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    server_time: datetime
    checks: dict[str, DependencyStatus] = {}
    workers: dict[str, WorkerStatus] = {}


Check = Callable[[], Awaitable[None]]
WorkerProbe = Callable[[], Awaitable[WorkerStatus]]


def readiness_checks(request: Request) -> dict[str, Check]:
    state = request.app.state
    return {
        "postgres": lambda: ping_db(state.engine),
        "redis": lambda: ping_redis(state.redis),
    }


async def _lifecycle_heartbeat(request: Request) -> WorkerStatus:
    raw = await request.app.state.redis.get(WORKER_HEARTBEAT_KEY)
    if raw is None:
        return WorkerStatus(status="missing")
    seen = datetime.fromisoformat(json.loads(raw)["at"])
    ago = (datetime.now(UTC) - seen).total_seconds()
    return WorkerStatus(
        status="ok" if ago <= WORKER_STALE_AFTER_SECONDS else "stale",
        last_seen_at=seen,
        seconds_ago=round(ago, 1),
    )


def worker_probes(request: Request) -> dict[str, WorkerProbe]:
    return {"lifecycle": lambda: _lifecycle_heartbeat(request)}


async def _run(check: Check) -> DependencyStatus:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        return DependencyStatus(status="ok")
    except Exception as exc:  # report, never raise, from a probe
        return DependencyStatus(status="error", error=type(exc).__name__)


async def _probe(probe: WorkerProbe) -> WorkerStatus:
    try:
        return await asyncio.wait_for(probe(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception:  # Redis down or not configured: we simply don't know
        return WorkerStatus(status="unknown")


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok", server_time=datetime.now(UTC))


@router.get("/ready", response_model=HealthResponse)
async def ready(
    response: Response,
    checks: dict[str, Check] = Depends(readiness_checks),
    probes: dict[str, WorkerProbe] = Depends(worker_probes),
) -> HealthResponse:
    results, worker_results = await asyncio.gather(
        asyncio.gather(*(_run(c) for c in checks.values())),
        asyncio.gather(*(_probe(p) for p in probes.values())),
    )
    healthy = all(r.status == "ok" for r in results)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        server_time=datetime.now(UTC),
        checks=dict(zip(checks.keys(), results, strict=True)),
        workers=dict(zip(probes.keys(), worker_results, strict=True)),
    )
