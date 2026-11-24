from fastapi import FastAPI
from httpx import AsyncClient

from app.api.health import readiness_checks


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("down")


async def test_live_returns_ok_and_server_time(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["server_time"].endswith(("Z", "+00:00"))
    assert resp.headers["X-Request-ID"]


async def test_ready_ok_when_all_dependencies_up(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[readiness_checks] = lambda: {"postgres": _ok, "redis": _ok}
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"] == {
        "postgres": {"status": "ok", "error": None},
        "redis": {"status": "ok", "error": None},
    }


async def test_ready_503_when_a_dependency_is_down(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[readiness_checks] = lambda: {"postgres": _ok, "redis": _fail}
    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == {"status": "error", "error": "ConnectionError"}


async def test_request_id_is_propagated(client: AsyncClient) -> None:
    resp = await client.get("/health/live", headers={"X-Request-ID": "abc123"})
    assert resp.headers["X-Request-ID"] == "abc123"
