"""Rate limiting against a real Redis (skipped if Redis isn't reachable)."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis

from app.core import rate_limit as rl
from app.core.rate_limit import Limit, RateLimitedError, RateLimiter
from app.models.user import UserRole
from tests.conftest import redis_url_for_tests
from tests.integration.helpers import RFQS, bid_payload, create_rfq, make_user, set_schedule

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url_for_tests(), decode_responses=True, socket_connect_timeout=1)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        if os.environ.get("REQUIRE_INTEGRATION") == "1":
            raise
        pytest.skip(f"Redis not reachable: {exc}")
    yield client
    await client.aclose()


@pytest.fixture
async def limited_app(db_app: FastAPI, redis: Redis) -> FastAPI:
    # Unique prefix per test: no cross-test interference, no FLUSHDB needed.
    db_app.state.rate_limiter = RateLimiter(redis, prefix=f"rl-test-{uuid.uuid4().hex}")
    return db_app


async def test_limiter_counts_per_key_and_window(redis: Redis) -> None:
    limiter = RateLimiter(redis, prefix=f"rl-test-{uuid.uuid4().hex}")
    tiny = Limit("tiny", 2, 1)
    await limiter.check(tiny, "alice")
    await limiter.check(tiny, "alice")
    with pytest.raises(RateLimitedError) as exc:
        await limiter.check(tiny, "alice")
    assert exc.value.headers == {"Retry-After": "1"}
    await limiter.check(tiny, "bob")  # separate key, separate budget

    await asyncio.sleep(1.1)  # window expires
    await limiter.check(tiny, "alice")


async def test_limiter_fails_open_when_redis_is_down() -> None:
    dead = Redis.from_url("redis://localhost:1/0", socket_connect_timeout=0.2)
    limiter = RateLimiter(dead)
    for _ in range(5):
        await limiter.check(Limit("x", 1, 60), "k")  # never raises
    await dead.aclose()


async def test_login_is_limited_per_account(limited_app: FastAPI, db_client: AsyncClient) -> None:
    await make_user(limited_app, "victim@example.com", UserRole.BUYER)
    body = {"email": "victim@example.com", "password": "WrongPass1"}
    for _ in range(rl.LOGIN_PER_ACCOUNT.max_requests):
        assert (await db_client.post("/api/v1/auth/login", json=body)).status_code == 401

    blocked = await db_client.post("/api/v1/auth/login", json=body)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) > 0
    # The limit is per account: another email from the same client still works.
    other = await db_client.post(
        "/api/v1/auth/login", json={"email": "someone@example.com", "password": "x"}
    )
    assert other.status_code == 401


async def test_bids_are_limited_per_supplier_and_rfq(
    limited_app: FastAPI, db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rl, "BIDS_PER_SUPPLIER_RFQ", Limit("bid", 3, 60))
    _, buyer = await make_user(limited_app, "buyer@example.com", UserRole.BUYER)
    _, sup = await make_user(limited_app, "a@carrier.com", UserRole.SUPPLIER)
    rfq = await create_rfq(db_client, buyer, supplier_emails=["a@carrier.com"])
    minute = timedelta(minutes=1)
    await set_schedule(limited_app, rfq["id"], start=-minute, close=60 * minute, forced=90 * minute)

    url = f"{RFQS}/{rfq['id']}/bids"
    codes = [
        (await db_client.post(url, json=bid_payload(1000 - i), headers=sup)).status_code
        for i in range(5)
    ]
    assert codes == [201, 201, 201, 429, 429]
