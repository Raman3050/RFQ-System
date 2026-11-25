"""Lifecycle worker: persisting start / close / force-close on time, exactly once."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.auction_event import AuctionEvent
from app.models.rfq import Rfq, RfqStatus
from app.models.user import UserRole
from app.services.lifecycle_service import LifecycleService
from tests.integration.helpers import RFQS, bid_payload, create_rfq, make_user, set_schedule

pytestmark = pytest.mark.integration

MIN = timedelta(minutes=1)


@pytest.fixture
async def setup(db_app: FastAPI, db_client: AsyncClient) -> dict[str, Any]:
    _, buyer = await make_user(db_app, "buyer@example.com", UserRole.BUYER)
    _, a = await make_user(db_app, "a@carrier.com", UserRole.SUPPLIER, company="Carrier A")
    _, b = await make_user(db_app, "b@carrier.com", UserRole.SUPPLIER, company="Carrier B")
    return {"buyer": buyer, "A": a, "B": b}


async def new_rfq(client: AsyncClient, ctx: dict[str, Any]) -> str:
    rfq = await create_rfq(client, ctx["buyer"], supplier_emails=["a@carrier.com", "b@carrier.com"])
    return str(rfq["id"])


def worker(app: FastAPI) -> LifecycleService:
    return LifecycleService(app.state.sessionmaker)


async def stored(app: FastAPI, rfq_id: str) -> Rfq:
    async with app.state.sessionmaker() as s:
        rfq = await s.get(Rfq, uuid.UUID(rfq_id))
        assert rfq is not None
        return rfq


async def events(app: FastAPI, rfq_id: str, *types: str) -> list[AuctionEvent]:
    async with app.state.sessionmaker() as s:
        stmt = (
            select(AuctionEvent)
            .where(AuctionEvent.rfq_id == uuid.UUID(rfq_id))
            .order_by(AuctionEvent.id)
        )
        if types:
            stmt = stmt.where(AuctionEvent.event_type.in_(types))
        return list((await s.execute(stmt)).scalars())


# ---------------------------------------------------------------- start


async def test_starts_auctions_at_bid_start(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    due = await new_rfq(db_client, setup)
    later = await new_rfq(db_client, setup)
    await set_schedule(db_app, due, start=-MIN, close=30 * MIN, forced=60 * MIN)

    stats = await worker(db_app).run_once()

    assert stats.started == 1
    assert (await stored(db_app, due)).status == RfqStatus.ACTIVE
    assert (await stored(db_app, later)).status == RfqStatus.SCHEDULED
    assert len(await events(db_app, due, "AUCTION_STARTED")) == 1


# ---------------------------------------------------------------- close


async def test_closes_at_bid_close_and_records_the_winner(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    await set_schedule(db_app, rfq_id, start=-30 * MIN, close=20 * MIN, forced=40 * MIN)
    await worker(db_app).run_once()
    for who, total in (("A", 500), ("B", 450), ("A", 400)):
        resp = await db_client.post(
            f"{RFQS}/{rfq_id}/bids", json=bid_payload(total), headers=setup[who]
        )
        assert resp.status_code == 201
    # Time passes: the close is now in the past (but before the forced close).
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=20 * MIN)

    stats = await worker(db_app).run_once()

    assert stats.closed == 1
    rfq = await stored(db_app, rfq_id)
    assert rfq.status == RfqStatus.CLOSED
    assert rfq.closed_at is not None
    [closed] = await events(db_app, rfq_id, "AUCTION_CLOSED")
    p = closed.payload
    assert p["reason"] == "Bid close time reached"
    assert p["winning_supplier_company"] == "Carrier A"
    assert p["winning_total"] == "400.00"
    assert p["total_bids"] == 3
    assert p["bidders"] == 2

    detail = (await db_client.get(f"{RFQS}/{rfq_id}", headers=setup["buyer"])).json()
    assert detail["status"] == "CLOSED"
    assert detail["closed_at"] is not None


async def test_auction_extended_to_the_cap_is_force_closed(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    # Close in 5 min, forced 2 min later: the first in-window bid extends to the cap.
    await set_schedule(db_app, rfq_id, start=-30 * MIN, close=5 * MIN, forced=7 * MIN)
    resp = await db_client.post(f"{RFQS}/{rfq_id}/bids", json=bid_payload(100), headers=setup["A"])
    assert resp.json()["extension"]["capped"] is True
    # Jump past the forced close while keeping current_close == forced_close.
    async with db_app.state.sessionmaker() as s:
        rfq = await s.get(Rfq, uuid.UUID(rfq_id))
        assert rfq is not None
        rfq.bid_close_at = func.now() - timedelta(minutes=3)
        rfq.current_close_at = func.now() - MIN
        rfq.forced_close_at = func.now() - MIN
        await s.commit()

    stats = await worker(db_app).run_once()

    assert stats.force_closed == 1
    assert (await stored(db_app, rfq_id)).status == RfqStatus.FORCE_CLOSED
    [closed] = await events(db_app, rfq_id, "AUCTION_FORCE_CLOSED")
    assert closed.payload["reason"] == "Reached the forced close time"
    assert closed.payload["extension_count"] == 1


async def test_auction_with_no_bids_closes_without_a_winner(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=10 * MIN)

    await worker(db_app).run_once()

    [closed] = await events(db_app, rfq_id, "AUCTION_CLOSED")
    assert closed.payload["winning_supplier_company"] is None
    assert closed.payload["total_bids"] == 0


async def test_catch_up_after_downtime_records_start_and_close(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    """The worker was down for an auction's whole life: it still logs both transitions."""
    rfq_id = await new_rfq(db_client, setup)
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-30 * MIN, forced=-10 * MIN)

    stats = await worker(db_app).run_once()

    assert (stats.started, stats.closed) == (1, 1)
    types = [
        e.event_type for e in await events(db_app, rfq_id, "AUCTION_STARTED", "AUCTION_CLOSED")
    ]
    assert types == ["AUCTION_STARTED", "AUCTION_CLOSED"]
    assert (await events(db_app, rfq_id, "AUCTION_STARTED"))[0].payload["late"] is True


async def test_cancelled_rfqs_are_left_alone(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    assert (
        await db_client.post(f"{RFQS}/{rfq_id}/cancel", headers=setup["buyer"])
    ).status_code == 200
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=10 * MIN)

    stats = await worker(db_app).run_once()

    assert stats.changed == 0
    assert (await stored(db_app, rfq_id)).status == RfqStatus.CANCELLED


# ---------------------------------------------------------------- exactly once


async def test_running_again_changes_nothing(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=10 * MIN)
    await worker(db_app).run_once()

    again = await worker(db_app).run_once()

    assert again.changed == 0
    assert len(await events(db_app, rfq_id, "AUCTION_CLOSED")) == 1


async def test_parallel_workers_close_each_auction_exactly_once(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    ids = [await new_rfq(db_client, setup) for _ in range(12)]
    for rfq_id in ids:
        await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=10 * MIN)

    results = await asyncio.gather(*(worker(db_app).run_once() for _ in range(4)))

    closed_by_anyone = [rid for r in results for rid in r.closed_ids]
    assert sorted(map(str, closed_by_anyone)) == sorted(ids)  # each exactly once
    for rfq_id in ids:
        assert len(await events(db_app, rfq_id, "AUCTION_CLOSED")) == 1
        assert (await stored(db_app, rfq_id)).status == RfqStatus.CLOSED


async def test_bids_after_the_worker_closed_are_rejected(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=10 * MIN)
    await worker(db_app).run_once()
    # Even if someone moved the close time back into the future, a stored terminal
    # status is final.
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=30 * MIN, forced=60 * MIN)

    resp = await db_client.post(f"{RFQS}/{rfq_id}/bids", json=bid_payload(100), headers=setup["A"])
    assert resp.status_code == 409
    assert resp.json()["code"] == "AUCTION_CLOSED"


# ---------------------------------------------------------------- visibility


async def test_suppliers_see_the_result_anonymised(
    db_app: FastAPI, db_client: AsyncClient, setup: dict[str, Any]
) -> None:
    rfq_id = await new_rfq(db_client, setup)
    await set_schedule(db_app, rfq_id, start=-30 * MIN, close=20 * MIN, forced=40 * MIN)
    for who, total in (("A", 500), ("B", 450)):
        await db_client.post(f"{RFQS}/{rfq_id}/bids", json=bid_payload(total), headers=setup[who])
    await set_schedule(db_app, rfq_id, start=-60 * MIN, close=-MIN, forced=20 * MIN)
    await worker(db_app).run_once()

    def closed_event(items: list[dict[str, Any]]) -> dict[str, Any]:
        return next(e for e in items if e["type"] == "AUCTION_CLOSED")["payload"]

    as_a = closed_event(
        (await db_client.get(f"{RFQS}/{rfq_id}/events", headers=setup["A"])).json()["items"]
    )
    as_b = closed_event(
        (await db_client.get(f"{RFQS}/{rfq_id}/events", headers=setup["B"])).json()["items"]
    )
    assert as_a["winning_supplier_company"] == "Bidder 2"
    assert as_a["winner_is_you"] is False
    assert as_b["winning_supplier_company"] == "You"
    assert as_b["winner_is_you"] is True
    assert "winning_supplier_id" not in as_a
