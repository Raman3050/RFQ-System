from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from app.core.errors import ConflictError


class Payload(BaseModel):
    amount: int


def _add_routes(app: FastAPI) -> None:
    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise ConflictError("Auction already closed", extra={"rfq_id": "r1"})

    @app.post("/_test/validate")
    async def validate(p: Payload) -> Payload:
        return p


async def test_app_error_renders_problem_json(app: FastAPI, client: AsyncClient) -> None:
    _add_routes(app)
    resp = await client.get("/_test/conflict")
    assert resp.status_code == 409
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["code"] == "CONFLICT"
    assert body["detail"] == "Auction already closed"
    assert body["rfq_id"] == "r1"
    assert body["request_id"]


async def test_validation_error_is_problem_json(app: FastAPI, client: AsyncClient) -> None:
    _add_routes(app)
    resp = await client.post("/_test/validate", json={"amount": "not-a-number"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["loc"] == ["body", "amount"]


async def test_unknown_route_is_problem_json(client: AsyncClient) -> None:
    resp = await client.get("/nope")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"
