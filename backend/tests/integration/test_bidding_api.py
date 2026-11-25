"""Bidding engine against a real Postgres: ranking, all three extension triggers,
forced-close cap, validation, visibility, idempotency and concurrency."""

import asyncio
import itertools
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from app.models.user import UserRole
from tests.integration.helpers import (
    RFQS,
    bid_payload,
    create_rfq,
    make_user,
    set_schedule,
)

pytestmark = pytest.mark.integration

Headers = dict[str, str]
MIN = timedelta(minutes=1)


class Auction:
    """A British Auction with a buyer and three invited suppliers (A, B, C)."""

    def __init__(self, app: FastAPI, client: AsyncClient) -> None:
        self.app = app
        self.client = client
        self.rfq: dict[str, Any] = {}
        self.buyer: Headers = {}
        self.sup: dict[str, Headers] = {}

    async def setup(self, trigger: str = "BID_RECEIVED", x: int = 10, y: int = 5) -> "Auction":
        _, self.buyer = await make_user(self.app, "buyer@example.com", UserRole.BUYER)
        for name in "ABC":
            _, self.sup[name] = await make_user(
                self.app,
                f"{name.lower()}@carrier.com",
                UserRole.SUPPLIER,
                company=f"Carrier {name}",
            )
        self.rfq = await create_rfq(
            self.client,
            self.buyer,
            auction_config={
                "trigger_window_minutes": x,
                "extension_minutes": y,
                "trigger_type": trigger,
            },
            supplier_emails=["a@carrier.com", "b@carrier.com", "c@carrier.com"],
        )
        return self

    @property
    def id(self) -> str:
        return str(self.rfq["id"])

    async def open(self, *, closes_in: timedelta, forced_after_close: timedelta = 30 * MIN) -> None:
        await set_schedule(
            self.app,
            self.id,
            start=-10 * MIN,
            close=closes_in,
            forced=closes_in + forced_after_close,
        )

    async def bid(self, who: str, total: Any, **kw: Any) -> Response:
        headers = {**self.sup[who], **kw.pop("headers", {})}
        return await self.client.post(
            f"{RFQS}/{self.id}/bids", json=bid_payload(total, **kw), headers=headers
        )

    async def ok(self, who: str, total: Any) -> dict[str, Any]:
        resp = await self.bid(who, total)
        assert resp.status_code == 201, resp.text
        body: dict[str, Any] = resp.json()
        return body

    async def detail(self) -> dict[str, Any]:
        body: dict[str, Any] = (
            await self.client.get(f"{RFQS}/{self.id}", headers=self.buyer)
        ).json()
        return body

    async def board(self, as_: str | None = None) -> dict[str, Any]:
        headers = self.sup[as_] if as_ else self.buyer
        body: dict[str, Any] = (
            await self.client.get(f"{RFQS}/{self.id}/leaderboard", headers=headers)
        ).json()
        return body

    async def events(self, as_: str | None = None) -> list[dict[str, Any]]:
        headers = self.sup[as_] if as_ else self.buyer
        items: list[dict[str, Any]] = (
            await self.client.get(f"{RFQS}/{self.id}/events", headers=headers)
        ).json()["items"]
        return items


@pytest.fixture
async def auction(db_app: FastAPI, db_client: AsyncClient) -> Auction:
    return await Auction(db_app, db_client).setup()


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# ---------------------------------------------------------------- basic bidding


async def test_first_bid(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    resp = await auction.bid(
        "A",
        0,
        freight_charges="1000.50",
        origin_charges="200",
        destination_charges="99.50",
        carrier_name="BlueDart",
        transit_time_days=4,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["bid"]["total_amount"]) == Decimal("1300.00")
    assert body["rank"] == 1
    assert body["total_bidders"] == 1
    assert body["extension"] is None  # outside the 10-minute window
    assert body["replayed"] is False

    detail = await auction.detail()
    assert Decimal(detail["current_lowest_bid"]) == Decimal("1300.00")
    assert detail["status"] == "ACTIVE"


async def test_ranking_and_ties(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    await auction.ok("A", 500)
    await auction.ok("B", 400)
    await auction.ok("C", 400)  # same price as B, but later → ranks below B

    board = await auction.board()
    assert [(e["label"], e["supplier_label"]) for e in board["entries"]] == [
        ("L1", "Carrier B"),
        ("L2", "Carrier C"),
        ("L3", "Carrier A"),
    ]
    assert Decimal((await auction.detail())["current_lowest_bid"]) == Decimal("400")


async def test_new_bid_must_be_lower_than_own_current_bid(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    await auction.ok("A", 500)
    for total in (500, 600):
        resp = await auction.bid("A", total)
        assert resp.status_code == 409
        assert resp.json()["code"] == "BID_NOT_LOWER"
        assert resp.json()["your_current_total"] == "500.00"
    revised = await auction.ok("A", 450)
    assert revised["rank"] == 1

    board = await auction.board()
    assert board["entries"][0]["bid_count"] == 2
    assert Decimal(board["entries"][0]["total_amount"]) == Decimal("450")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"freight_charges": "-1"}, "freight_charges"),
        ({"freight_charges": "10.123"}, "freight_charges"),
        ({"transit_time_days": 0}, "transit_time_days"),
        ({"carrier_name": "  "}, "carrier_name"),
        ({"quote_validity_until": "2020-01-01"}, "quote_validity_until"),
    ],
)
async def test_quote_validation(auction: Auction, overrides: dict[str, Any], field: str) -> None:
    await auction.open(closes_in=60 * MIN)
    resp = await auction.bid("A", 100, **overrides)
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["loc"][-1] == field


async def test_total_must_be_positive(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    resp = await auction.bid("A", 0)
    assert resp.status_code == 422


async def test_bidding_window(auction: Auction) -> None:
    # Before start.
    resp = await auction.bid("A", 100)
    assert resp.status_code == 409
    assert resp.json()["code"] == "AUCTION_NOT_STARTED"

    # After close.
    await set_schedule(auction.app, auction.id, start=-60 * MIN, close=-MIN, forced=10 * MIN)
    resp = await auction.bid("A", 100)
    assert resp.status_code == 409
    assert resp.json()["code"] == "AUCTION_CLOSED"


async def test_who_can_bid(auction: Auction, db_app: FastAPI) -> None:
    await auction.open(closes_in=60 * MIN)
    _, outsider = await make_user(db_app, "x@carrier.com", UserRole.SUPPLIER)
    resp = await auction.client.post(
        f"{RFQS}/{auction.id}/bids", json=bid_payload(100), headers=outsider
    )
    assert resp.status_code == 404
    resp = await auction.client.post(
        f"{RFQS}/{auction.id}/bids", json=bid_payload(100), headers=auction.buyer
    )
    assert resp.status_code == 403


async def test_idempotency_key_replays_the_original_bid(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    key = {"Idempotency-Key": "client-generated-123"}
    first = await auction.bid("A", 300, headers=key)
    second = await auction.bid("A", 300, headers=key)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["replayed"] is True
    assert second.json()["bid"]["id"] == first.json()["bid"]["id"]
    assert (await auction.board())["entries"][0]["bid_count"] == 1


# ---------------------------------------------------------------- extensions (spec §6)


async def test_bid_in_window_extends_by_y(auction: Auction) -> None:
    await auction.open(closes_in=5 * MIN)  # inside X = 10
    before = parse((await auction.detail())["current_close_at"])

    body = await auction.ok("A", 100)

    ext = body["extension"]
    assert ext is not None
    assert parse(ext["new_close_at"]) == before + 5 * MIN
    assert ext["reason"] == "Bid received in the last 10 minutes"
    assert ext["capped"] is False
    detail = await auction.detail()
    assert parse(detail["current_close_at"]) == before + 5 * MIN
    assert detail["extension_count"] == 1
    # Original close time is preserved.
    assert parse(detail["bid_close_at"]) == before


async def test_bid_outside_window_does_not_extend(auction: Auction) -> None:
    await auction.open(closes_in=11 * MIN)
    assert (await auction.ok("A", 100))["extension"] is None
    assert (await auction.detail())["extension_count"] == 0


async def test_any_rank_change_trigger(db_app: FastAPI, db_client: AsyncClient) -> None:
    a = await Auction(db_app, db_client).setup(trigger="ANY_RANK_CHANGE")
    await a.open(closes_in=5 * MIN)

    assert (await a.ok("A", 100))["extension"] is None  # first bid: no ranks to change
    assert (await a.ok("B", 120))["extension"] is None  # new bidder at the bottom
    assert (await a.ok("B", 110))["extension"] is None  # improved but still L2
    assert (await a.ok("B", 90))["extension"] is not None  # B overtakes A


async def test_l1_change_trigger(db_app: FastAPI, db_client: AsyncClient) -> None:
    a = await Auction(db_app, db_client).setup(trigger="L1_RANK_CHANGE")
    await a.open(closes_in=5 * MIN)

    assert (await a.ok("A", 100))["extension"] is None
    assert (await a.ok("B", 120))["extension"] is None
    assert (await a.ok("C", 110))["extension"] is None  # rank change below L1 only
    ext = (await a.ok("C", 95))["extension"]  # C becomes the new L1
    assert ext is not None
    assert ext["reason"] == "New lowest bidder (L1) in the last 10 minutes"


async def test_extension_never_exceeds_forced_close(auction: Auction) -> None:
    await auction.open(closes_in=5 * MIN, forced_after_close=2 * MIN)
    forced = parse((await auction.detail())["forced_close_at"])

    first = await auction.ok("A", 100)
    assert first["extension"]["capped"] is True
    assert parse(first["extension"]["new_close_at"]) == forced

    second = await auction.ok("B", 90)  # still in the window, but already at the cap
    assert second["extension"] is None
    detail = await auction.detail()
    assert parse(detail["current_close_at"]) == forced
    assert detail["extension_count"] == 1


async def test_auction_that_ran_to_forced_close_is_force_closed(auction: Auction) -> None:
    await auction.open(closes_in=5 * MIN, forced_after_close=2 * MIN)
    await auction.ok("A", 100)  # extends to the forced close
    # Simulate time passing beyond the forced close (keep current_close == forced).
    from sqlalchemy import text

    async with auction.app.state.sessionmaker() as s:
        await s.execute(
            text(
                "UPDATE rfqs SET bid_start_at = now() - interval '2 hours', "
                "bid_close_at = now() - interval '20 minutes', "
                "current_close_at = now() - interval '10 minutes', "
                "forced_close_at = now() - interval '10 minutes' WHERE id = :id"
            ),
            {"id": auction.id},
        )
        await s.commit()
    assert (await auction.detail())["status"] == "FORCE_CLOSED"
    assert (await auction.bid("B", 50)).json()["code"] == "AUCTION_CLOSED"


async def test_plain_rfq_never_extends(db_app: FastAPI, db_client: AsyncClient) -> None:
    _, buyer = await make_user(db_app, "buyer@example.com", UserRole.BUYER)
    _, sup = await make_user(db_app, "a@carrier.com", UserRole.SUPPLIER)
    rfq = await create_rfq(
        db_client,
        buyer,
        is_british_auction=False,
        auction_config=None,
        supplier_emails=["a@carrier.com"],
    )
    await set_schedule(db_app, rfq["id"], start=-MIN, close=MIN, forced=30 * MIN)
    resp = await db_client.post(f"{RFQS}/{rfq['id']}/bids", json=bid_payload(100), headers=sup)
    assert resp.status_code == 201
    assert resp.json()["extension"] is None


# ---------------------------------------------------------------- visibility & activity log


async def test_supplier_sees_competitors_anonymised(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    await auction.ok("A", 500)
    await auction.ok("B", 400)

    board = await auction.board(as_="A")
    l1, l2 = board["entries"]
    assert l1["supplier_label"] == "Bidder 2"  # B bid second
    assert l1["is_you"] is False
    assert l1["carrier_name"] is None
    assert l1["freight_charges"] is None
    assert Decimal(l1["total_amount"]) == Decimal("400")  # prices are open
    assert l2["is_you"] is True
    assert l2["supplier_label"] == "Carrier A"
    assert l2["freight_charges"] is not None
    assert board["my_rank"] == 2
    assert Decimal(board["my_current_total"]) == Decimal("500")

    own = (await auction.client.get(f"{RFQS}/{auction.id}/bids", headers=auction.sup["A"])).json()
    assert len(own) == 1
    everything = (
        await auction.client.get(f"{RFQS}/{auction.id}/bids", headers=auction.buyer)
    ).json()
    assert len(everything) == 2


async def test_activity_log(auction: Auction) -> None:
    await auction.open(closes_in=5 * MIN)
    await auction.ok("A", 100)

    buyer_view = await auction.events()
    types = [e["type"] for e in buyer_view]
    assert types[:2] == ["TIME_EXTENDED", "BID_SUBMITTED"]  # newest first
    assert "SUPPLIER_INVITED" in types
    assert "RFQ_CREATED" in types
    ext = buyer_view[0]["payload"]
    assert ext["reason"] == "Bid received in the last 10 minutes"
    assert ext["extension_minutes"] == 5
    assert buyer_view[1]["payload"]["supplier_company"] == "Carrier A"

    b_view = await auction.events(as_="B")
    assert {e["type"] for e in b_view} == {"TIME_EXTENDED", "BID_SUBMITTED"}
    bid_event = next(e for e in b_view if e["type"] == "BID_SUBMITTED")
    assert bid_event["payload"]["supplier_company"] == "Bidder 1"
    assert bid_event["payload"]["is_you"] is False
    assert "supplier_id" not in bid_event["payload"]
    assert bid_event["actor"] == "Bidder 1"


# ---------------------------------------------------------------- removing invites


async def test_remove_invite_rules(auction: Auction) -> None:
    await auction.open(closes_in=60 * MIN)
    await auction.ok("A", 100)
    url = f"{RFQS}/{auction.id}/invitations"

    invites = {i["email"]: i for i in (await auction.detail())["invitations"]}
    assert invites["a@carrier.com"]["can_remove"] is False
    assert invites["b@carrier.com"]["can_remove"] is True

    blocked = await auction.client.delete(f"{url}/a@carrier.com", headers=auction.buyer)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "SUPPLIER_HAS_BID"

    removed = await auction.client.delete(f"{url}/b@carrier.com", headers=auction.buyer)
    assert removed.status_code == 200
    assert removed.json()["invited_count"] == 2
    # B loses access entirely.
    assert (
        await auction.client.get(f"{RFQS}/{auction.id}", headers=auction.sup["B"])
    ).status_code == 404
    assert (await auction.bid("B", 50)).status_code == 404


async def test_removing_a_pending_invite_kills_the_signup_link(
    db_app: FastAPI, db_client: AsyncClient, outbox: list[Any]
) -> None:
    from tests.integration.helpers import invite_token

    _, buyer = await make_user(db_app, "buyer@example.com", UserRole.BUYER)
    rfq = await create_rfq(db_client, buyer, supplier_emails=["new@carrier.com"])
    token = invite_token(outbox[0])

    resp = await db_client.delete(f"{RFQS}/{rfq['id']}/invitations/new@carrier.com", headers=buyer)
    assert resp.status_code == 200
    inspect = await db_client.post("/api/v1/auth/invitations/inspect", json={"token": token})
    assert inspect.json()["code"] == "INVITE_INVALID"


async def test_cannot_remove_after_auction_ends(auction: Auction) -> None:
    await set_schedule(auction.app, auction.id, start=-60 * MIN, close=-MIN, forced=10 * MIN)
    resp = await auction.client.delete(
        f"{RFQS}/{auction.id}/invitations/b@carrier.com", headers=auction.buyer
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "RFQ_NOT_INVITABLE"


# ---------------------------------------------------------------- concurrency


async def test_concurrent_bids_keep_the_auction_consistent(auction: Auction) -> None:
    """30 bids fired at once, in the trigger window, with a tight forced-close cap.
    The row lock must keep every invariant intact."""
    await auction.open(closes_in=5 * MIN, forced_after_close=12 * MIN)
    detail = await auction.detail()
    forced = parse(detail["forced_close_at"])

    async def fire(who: str, total: int) -> Response:
        return await auction.bid(who, total)

    jobs = [
        fire(who, 1000 - i * 10 - offset)
        for i in range(10)
        for who, offset in (("A", 0), ("B", 3), ("C", 7))
    ]
    results = await asyncio.gather(*jobs)

    codes = [r.status_code for r in results]
    assert set(codes) <= {201, 409}, codes  # never a 500
    accepted = [r.json() for r in results if r.status_code == 201]
    assert accepted, "at least some bids must succeed"

    detail = await auction.detail()
    board = await auction.board()
    events = await auction.events()
    current_close = parse(detail["current_close_at"])

    # 1. Never past the forced close.
    assert current_close <= forced
    # 2. Each extension is recorded exactly once.
    extensions = [e for e in events if e["type"] == "TIME_EXTENDED"]
    assert detail["extension_count"] == len(extensions)
    # 3. Every accepted bid is logged.
    assert len([e for e in events if e["type"] == "BID_SUBMITTED"]) == len(accepted)
    # 4. Stored L1 matches the true minimum of current quotes.
    totals = [Decimal(e["total_amount"]) for e in board["entries"]]
    assert totals == sorted(totals)
    assert Decimal(detail["current_lowest_bid"]) == totals[0]
    # 5. Each supplier's accepted bids strictly decrease over time.
    history = (await auction.client.get(f"{RFQS}/{auction.id}/bids", headers=auction.buyer)).json()
    for company in ("Carrier A", "Carrier B", "Carrier C"):
        mine = sorted(
            (b for b in history if b["supplier_company"] == company), key=lambda b: b["created_at"]
        )
        amounts = [Decimal(b["total_amount"]) for b in mine]
        assert amounts == sorted(amounts, reverse=True)
        assert len(set(amounts)) == len(amounts)
    # 6. Extension chain is contiguous: each starts where the previous ended.
    chain = sorted(extensions, key=lambda e: e["id"])
    for prev, nxt in itertools.pairwise(chain):
        assert nxt["payload"]["previous_close_at"] == prev["payload"]["new_close_at"]
