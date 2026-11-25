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


async def test_ready_reports_worker_heartbeat(app: FastAPI, client: AsyncClient) -> None:
    from app.api.health import WorkerStatus, worker_probes

    async def fresh() -> WorkerStatus:
        return WorkerStatus(status="ok", seconds_ago=0.4)

    app.dependency_overrides[readiness_checks] = lambda: {"postgres": _ok}
    app.dependency_overrides[worker_probes] = lambda: {"lifecycle": fresh}
    body = (await client.get("/health/ready")).json()
    assert body["workers"]["lifecycle"]["status"] == "ok"


async def test_worker_status_unknown_when_redis_unavailable(
    app: FastAPI, client: AsyncClient
) -> None:
    # No Redis on app.state in unit tests: the probe must degrade, not fail the request.
    app.dependency_overrides[readiness_checks] = lambda: {"postgres": _ok}
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["workers"]["lifecycle"]["status"] == "unknown"


async def test_security_headers(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/nope")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in resp.headers  # only when deployed (HTTPS)


async def test_docs_can_be_disabled() -> None:
    from httpx import ASGITransport

    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(environment="test", expose_api_docs=False, log_json=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/docs")).status_code == 404
        assert (await c.get("/api/v1/openapi.json")).status_code == 404
