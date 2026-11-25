"""Real-time updates and the winner email.

- What gets published (and that it never leaks supplier identities).
- The lifecycle worker emails the winner exactly once.
- End-to-end over a real WebSocket + Redis pub/sub (skipped if Redis isn't reachable).
"""

import json
import os
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
import redis as sync_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.email.sender import MemoryEmailSender
from app.main import create_app
from app.models.user import UserRole
from app.realtime.publisher import MemoryPublisher
from app.services.lifecycle_service import LifecycleService
from tests.integration.helpers import RFQS, bid_payload, create_rfq, make_user, set_schedule

pytestmark = pytest.mark.integration

MIN = timedelta(minutes=1)


@pytest.fixture
async def ctx(db_app: FastAPI, db_client: AsyncClient) -> dict[str, Any]:
    publisher = MemoryPublisher()
    db_app.state.publisher = publisher
    _, buyer = await make_user(db_app, "buyer@example.com", UserRole.BUYER, company="Acme")
    _, a = await make_user(
        db_app, "a@carrier.com", UserRole.SUPPLIER, full_name="Arjun Mehta", company="Carrier A"
    )
    _, b = await make_user(db_app, "b@carrier.com", UserRole.SUPPLIER, company="Carrier B")
    rfq = await create_rfq(db_client, buyer, supplier_emails=["a@carrier.com", "b@carrier.com"])
    return {"buyer": buyer, "A": a, "B": b, "rfq": rfq, "pub": publisher}


async def bid(client: AsyncClient, ctx: dict[str, Any], who: str, total: int) -> Any:
    resp = await client.post(
        f"{RFQS}/{ctx['rfq']['id']}/bids", json=bid_payload(total), headers=ctx[who]
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- what is published


async def test_bid_publishes_a_public_notification(
    db_app: FastAPI, db_client: AsyncClient, ctx: dict[str, Any]
) -> None:
    await set_schedule(db_app, ctx["rfq"]["id"], start=-MIN, close=60 * MIN, forced=90 * MIN)
    await bid(db_client, ctx, "A", 500)

    [msg] = ctx["pub"].messages
    assert msg["type"] == "BID_SUBMITTED"
    assert msg["rfq_id"] == ctx["rfq"]["id"]
    assert isinstance(msg["seq"], int)
    assert msg["auction"]["status"] == "ACTIVE"
    assert msg["auction"]["current_lowest_bid"] == "500.00"
    assert msg["extension"] is None
    # Notifications never identify suppliers: viewers refetch their own (anonymised) view.
    raw = json.dumps(msg)
    assert "Carrier A" not in raw
    assert "a@carrier.com" not in raw


async def test_extension_publishes_reason_and_new_close(
    db_app: FastAPI, db_client: AsyncClient, ctx: dict[str, Any]
) -> None:
    await set_schedule(db_app, ctx["rfq"]["id"], start=-MIN, close=5 * MIN, forced=60 * MIN)
    await bid(db_client, ctx, "A", 500)

    [msg] = ctx["pub"].messages
    assert msg["type"] == "TIME_EXTENDED"
    assert msg["extension"]["reason"] == "Bid received in the last 10 minutes"
    assert msg["extension"]["new_close_at"] == msg["auction"]["current_close_at"]
    assert msg["auction"]["extension_count"] == 1


async def test_seq_increases_with_each_change(
    db_app: FastAPI, db_client: AsyncClient, ctx: dict[str, Any]
) -> None:
    await set_schedule(db_app, ctx["rfq"]["id"], start=-MIN, close=60 * MIN, forced=90 * MIN)
    await bid(db_client, ctx, "A", 500)
    await bid(db_client, ctx, "B", 400)
    first, second = ctx["pub"].messages
    assert second["seq"] > first["seq"]


async def test_cancel_publishes(db_client: AsyncClient, ctx: dict[str, Any]) -> None:
    await db_client.post(f"{RFQS}/{ctx['rfq']['id']}/cancel", headers=ctx["buyer"])
    assert [m["type"] for m in ctx["pub"].messages] == ["RFQ_CANCELLED"]
    assert ctx["pub"].messages[0]["auction"]["status"] == "CANCELLED"


# ---------------------------------------------------------------- close: publish + winner email


def lifecycle(db_app: FastAPI, pub: MemoryPublisher, mail: MemoryEmailSender) -> LifecycleService:
    return LifecycleService(
        db_app.state.sessionmaker,
        settings=db_app.state.settings,
        email_sender=mail,
        publisher=pub,
    )


async def test_close_emails_the_winner_and_publishes(
    db_app: FastAPI, db_client: AsyncClient, ctx: dict[str, Any]
) -> None:
    rfq_id = ctx["rfq"]["id"]
    await set_schedule(db_app, rfq_id, start=-MIN, close=60 * MIN, forced=90 * MIN)
    await bid(db_client, ctx, "B", 500)
    await bid(db_client, ctx, "A", 450)
    await set_schedule(db_app, rfq_id, start=-90 * MIN, close=-MIN, forced=30 * MIN)
    pub, mail = MemoryPublisher(), MemoryEmailSender()

    await lifecycle(db_app, pub, mail).run_once()

    [email] = mail.outbox
    assert email.to == "a@carrier.com"
    assert email.subject.startswith(f"You won {ctx['rfq']['reference_id']}")
    assert "Hi Arjun Mehta" in email.text
    assert "INR 450.00" in email.text
    assert f"http://app.test/auctions/{rfq_id}" in email.text
    closed = [m for m in pub.messages if m["type"] == "AUCTION_CLOSED"]
    assert len(closed) == 1
    assert closed[0]["auction"]["status"] == "CLOSED"


async def test_no_email_when_nobody_bid(
    db_app: FastAPI, db_client: AsyncClient, ctx: dict[str, Any]
) -> None:
    await set_schedule(db_app, ctx["rfq"]["id"], start=-90 * MIN, close=-MIN, forced=30 * MIN)
    mail = MemoryEmailSender()
    await lifecycle(db_app, MemoryPublisher(), mail).run_once()
    assert mail.outbox == []


async def test_winner_is_emailed_once_even_with_parallel_workers(
    db_app: FastAPI, db_client: AsyncClient, ctx: dict[str, Any]
) -> None:
    import asyncio

    rfq_id = ctx["rfq"]["id"]
    await set_schedule(db_app, rfq_id, start=-MIN, close=60 * MIN, forced=90 * MIN)
    await bid(db_client, ctx, "A", 450)
    await set_schedule(db_app, rfq_id, start=-90 * MIN, close=-MIN, forced=30 * MIN)
    mail = MemoryEmailSender()

    await asyncio.gather(*(lifecycle(db_app, MemoryPublisher(), mail).run_once() for _ in range(4)))

    assert [m.to for m in mail.outbox] == ["a@carrier.com"]


# ---------------------------------------------------------------- end-to-end WebSocket


def _redis_url() -> str:
    # A dedicated logical DB so tests never touch app data.
    base = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return base.rsplit("/", 1)[0] + "/15"


@pytest.fixture
def ws_app(integration_settings: Settings) -> Iterator[TestClient]:
    url = _redis_url()
    try:
        sync_redis.Redis.from_url(url, socket_connect_timeout=1).ping()
    except Exception as exc:
        if os.environ.get("REQUIRE_INTEGRATION") == "1":
            raise
        pytest.skip(f"Redis not reachable for WebSocket tests: {exc}")
    settings = integration_settings.model_copy(
        update={
            "redis_url": url,
            "ws_ping_seconds": 0.5,
            "ws_auth_timeout_seconds": 1.0,
        }
    )
    with TestClient(create_app(settings)) as client:  # runs lifespan: Redis listener on
        yield client


def recv(ws: Any, want: str, limit: int = 40) -> dict[str, Any]:
    """Next message of type `want`, skipping keep-alive pings."""
    for _ in range(limit):
        msg: dict[str, Any] = ws.receive_json()
        if msg["type"] == want:
            return msg
        assert msg["type"] in ("PING", "PONG", "SUBSCRIBED", "SNAPSHOT", "READY"), msg
    raise AssertionError(f"no {want} message received")


def token_of(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


async def test_websocket_requires_a_valid_token(ws_app: TestClient) -> None:
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": "garbage"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


async def test_websocket_requires_auth_first(ws_app: TestClient) -> None:
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "rfq_ids": []})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


async def test_subscriptions_are_access_checked(
    ws_app: TestClient, db_app: FastAPI, ctx: dict[str, Any]
) -> None:
    _, outsider = await make_user(db_app, "x@carrier.com", UserRole.SUPPLIER)
    rfq_id = ctx["rfq"]["id"]
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token_of(outsider)})
        recv(ws, "READY")
        ws.send_json({"type": "subscribe", "rfq_ids": [rfq_id, "not-a-uuid"]})
        sub = recv(ws, "SUBSCRIBED")
    assert sub["rfq_ids"] == []
    assert sorted(sub["rejected"]) == sorted([rfq_id, "not-a-uuid"])


async def test_live_bid_reaches_other_viewers_through_redis(
    ws_app: TestClient, db_app: FastAPI, ctx: dict[str, Any]
) -> None:
    rfq_id = ctx["rfq"]["id"]
    await set_schedule(db_app, rfq_id, start=-MIN, close=5 * MIN, forced=60 * MIN)

    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token_of(ctx["B"])})
        recv(ws, "READY")
        ws.send_json({"type": "subscribe", "rfq_ids": [rfq_id]})
        assert recv(ws, "SUBSCRIBED")["rfq_ids"] == [rfq_id]
        snapshot = recv(ws, "SNAPSHOT")
        assert snapshot["auction"]["status"] == "ACTIVE"

        # Supplier A bids through the same app's REST API (real Redis publish).
        resp = ws_app.post(f"{RFQS}/{rfq_id}/bids", json=bid_payload(300), headers=ctx["A"])
        assert resp.status_code == 201, resp.text

        live = recv(ws, "TIME_EXTENDED")  # bid inside the window extends the close
        assert live["rfq_id"] == rfq_id
        assert live["seq"] > (snapshot["seq"] or 0)
        assert live["auction"]["current_lowest_bid"] == "300.00"
        assert live["extension"]["reason"] == "Bid received in the last 10 minutes"
