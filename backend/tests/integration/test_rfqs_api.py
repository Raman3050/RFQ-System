import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.email.sender import OutgoingEmail
from app.models.auction_event import AuctionEvent
from app.models.rfq import Rfq
from app.models.user import UserRole
from tests.integration.helpers import RFQS, create_rfq, make_user, rfq_payload

pytestmark = pytest.mark.integration

Headers = dict[str, str]


@pytest.fixture
async def buyer(db_app: FastAPI) -> Headers:
    _, h = await make_user(
        db_app, "buyer@example.com", UserRole.BUYER, full_name="Priya Sharma", company="Acme"
    )
    return h


@pytest.fixture
async def supplier(db_app: FastAPI) -> Headers:
    _, h = await make_user(db_app, "carrier@example.com", UserRole.SUPPLIER, company="BlueDart")
    return h


async def shift_times(
    sm: async_sessionmaker[AsyncSession], rfq_id: str, *, start: timedelta, close: timedelta
) -> None:
    """Move an RFQ's schedule relative to now (to simulate time passing)."""
    now = datetime.now(UTC)
    async with sm() as s:
        await s.execute(
            update(Rfq)
            .where(Rfq.id == uuid.UUID(rfq_id))
            .values(
                bid_start_at=now + start,
                bid_close_at=now + close,
                current_close_at=now + close,
                forced_close_at=now + close + timedelta(hours=1),
            )
        )
        await s.commit()


# ---------------------------------------------------------------- create


async def test_create_british_auction(db_client: AsyncClient, buyer: Headers) -> None:
    rfq = await create_rfq(db_client, buyer)

    assert re.fullmatch(r"RFQ-\d{4}-\d{6}", rfq["reference_id"])
    assert rfq["status"] == "SCHEDULED"
    assert rfq["auction_config"] == {
        "trigger_window_minutes": 10,
        "extension_minutes": 5,
        "trigger_type": "BID_RECEIVED",
    }
    assert rfq["current_close_at"] == rfq["bid_close_at"]
    assert rfq["current_lowest_bid"] is None
    assert rfq["extension_count"] == 0
    assert rfq["version"] == 1
    assert rfq["buyer"] == {"full_name": "Priya Sharma", "company_name": "Acme"}
    assert rfq["permissions"] == {"can_edit": True, "can_cancel": True, "can_invite": True}
    assert rfq["invitations"] == []
    assert rfq["bid_start_at"].endswith("Z")


async def test_reference_ids_are_unique_and_sequential(
    db_client: AsyncClient, buyer: Headers
) -> None:
    a = (await create_rfq(db_client, buyer))["reference_id"]
    b = (await create_rfq(db_client, buyer))["reference_id"]
    assert int(b[-6:]) == int(a[-6:]) + 1


async def test_times_with_offsets_are_normalised_to_utc(
    db_client: AsyncClient, buyer: Headers
) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    close_utc = (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0)
    rfq = await create_rfq(db_client, buyer, bid_close_at=close_utc.astimezone(ist).isoformat())
    assert rfq["bid_close_at"] == close_utc.isoformat().replace("+00:00", "Z")


async def test_create_plain_rfq_without_auction(db_client: AsyncClient, buyer: Headers) -> None:
    rfq = await create_rfq(db_client, buyer, is_british_auction=False, auction_config=None)
    assert rfq["is_british_auction"] is False
    assert rfq["auction_config"] is None


@pytest.mark.parametrize(
    ("field", "delta", "code"),
    [
        ("forced_close_at", timedelta(hours=2), "forced_close_not_after_close"),  # == close
        ("forced_close_at", timedelta(minutes=90), "forced_close_not_after_close"),
        ("bid_close_at", timedelta(minutes=30), "close_before_start"),
        ("bid_start_at", timedelta(hours=-1), "start_in_past"),
    ],
)
async def test_schedule_rules(
    db_client: AsyncClient, buyer: Headers, field: str, delta: timedelta, code: str
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    resp = await db_client.post(
        RFQS, json=rfq_payload(**{field: (now + delta).isoformat()}), headers=buyer
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert {"loc": ["body", errors[0]["loc"][-1]], "type": code} == {
        "loc": errors[0]["loc"],
        "type": errors[0]["type"],
    }
    assert code in {e["type"] for e in errors}


@pytest.mark.parametrize(
    "overrides",
    [
        {"auction_config": None},  # British auction needs a config
        {"is_british_auction": False},  # plain RFQ must not have one
        {"bid_start_at": "2030-01-01T10:00:00"},  # naive datetime
        {
            "auction_config": {
                "trigger_window_minutes": 0,
                "extension_minutes": 5,
                "trigger_type": "BID_RECEIVED",
            }
        },
        {
            "auction_config": {
                "trigger_window_minutes": 10,
                "extension_minutes": 5,
                "trigger_type": "SOMETHING_ELSE",
            }
        },
        {"name": "ab"},
    ],
)
async def test_request_validation(
    db_client: AsyncClient, buyer: Headers, overrides: dict[str, object]
) -> None:
    resp = await db_client.post(RFQS, json=rfq_payload(**overrides), headers=buyer)
    assert resp.status_code == 422, resp.text


async def test_suppliers_cannot_create(db_client: AsyncClient, supplier: Headers) -> None:
    resp = await db_client.post(RFQS, json=rfq_payload(), headers=supplier)
    assert resp.status_code == 403


async def test_create_records_event(
    db_client: AsyncClient, buyer: Headers, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    rfq = await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    async with sessionmaker() as s:
        types = (
            (
                await s.execute(
                    select(AuctionEvent.event_type)
                    .where(AuctionEvent.rfq_id == uuid.UUID(rfq["id"]))
                    .order_by(AuctionEvent.id)
                )
            )
            .scalars()
            .all()
        )
    assert types == ["RFQ_CREATED", "SUPPLIER_INVITED"]


# ---------------------------------------------------------------- invitations


async def test_inviting_existing_and_new_suppliers(
    db_client: AsyncClient, buyer: Headers, supplier: Headers, outbox: list[OutgoingEmail]
) -> None:
    rfq = await create_rfq(
        db_client, buyer, supplier_emails=["Carrier@Example.com", "new@example.com"]
    )

    by_email = {i["email"]: i for i in rfq["invitations"]}
    assert by_email["carrier@example.com"]["status"] == "JOINED"
    assert by_email["carrier@example.com"]["supplier_company"] == "BlueDart"
    assert by_email["new@example.com"]["status"] == "PENDING_ACCOUNT"
    assert rfq["invited_count"] == 2

    mails = {m.to: m for m in outbox}
    assert f"http://app.test/auctions/{rfq['id']}" in mails["carrier@example.com"].text
    assert "http://app.test/accept-invite?token=" in mails["new@example.com"].text
    assert rfq["reference_id"] in mails["new@example.com"].subject


async def test_buyer_email_cannot_be_invited(
    db_client: AsyncClient, buyer: Headers, db_app: FastAPI, outbox: list[OutgoingEmail]
) -> None:
    await make_user(db_app, "otherbuyer@example.com", UserRole.BUYER)
    resp = await db_client.post(
        RFQS,
        json=rfq_payload(supplier_emails=["ok@example.com", "otherbuyer@example.com"]),
        headers=buyer,
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["loc"] == ["body", "supplier_emails", 1]
    # All-or-nothing: no RFQ, no emails.
    assert (await db_client.get(RFQS, headers=buyer)).json()["total"] == 0
    assert outbox == []


async def test_invite_endpoint_is_idempotent(
    db_client: AsyncClient, buyer: Headers, outbox: list[OutgoingEmail]
) -> None:
    rfq = await create_rfq(db_client, buyer)
    url = f"{RFQS}/{rfq['id']}/invitations"
    for _ in range(2):
        resp = await db_client.post(url, json={"emails": ["x@example.com"]}, headers=buyer)
        assert resp.status_code == 200
    assert resp.json()["invited_count"] == 1
    assert len(outbox) == 1


async def test_cannot_invite_after_auction_ends(
    db_client: AsyncClient, buyer: Headers, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    rfq = await create_rfq(db_client, buyer)
    await shift_times(sessionmaker, rfq["id"], start=-timedelta(hours=2), close=-timedelta(hours=1))
    resp = await db_client.post(
        f"{RFQS}/{rfq['id']}/invitations", json={"emails": ["x@example.com"]}, headers=buyer
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "RFQ_NOT_INVITABLE"


# ---------------------------------------------------------------- visibility & listing


async def test_listing_is_scoped_per_user(
    db_client: AsyncClient, db_app: FastAPI, buyer: Headers, supplier: Headers
) -> None:
    _, other_buyer = await make_user(db_app, "b2@example.com", UserRole.BUYER)
    _, outsider = await make_user(db_app, "s2@example.com", UserRole.SUPPLIER)
    invited = await create_rfq(db_client, buyer, supplier_emails=["carrier@example.com"])
    await create_rfq(db_client, buyer, name="Not shared")

    assert (await db_client.get(RFQS, headers=buyer)).json()["total"] == 2
    assert (await db_client.get(RFQS, headers=other_buyer)).json()["total"] == 0
    assert (await db_client.get(RFQS, headers=outsider)).json()["total"] == 0

    mine = (await db_client.get(RFQS, headers=supplier)).json()
    assert [r["id"] for r in mine["items"]] == [invited["id"]]
    assert mine["items"][0]["buyer_company"] == "Acme"
    assert mine["server_time"].endswith("Z")


async def test_details_visibility(
    db_client: AsyncClient, db_app: FastAPI, buyer: Headers, supplier: Headers
) -> None:
    _, outsider = await make_user(db_app, "s2@example.com", UserRole.SUPPLIER)
    _, other_buyer = await make_user(db_app, "b2@example.com", UserRole.BUYER)
    rfq = await create_rfq(db_client, buyer, supplier_emails=["carrier@example.com"])
    url = f"{RFQS}/{rfq['id']}"

    as_supplier = (await db_client.get(url, headers=supplier)).json()
    assert as_supplier["invitations"] is None  # suppliers don't see who else was invited
    assert as_supplier["permissions"] == {
        "can_edit": False,
        "can_cancel": False,
        "can_invite": False,
    }
    for h in (outsider, other_buyer):
        resp = await db_client.get(url, headers=h)
        assert resp.status_code == 404
        assert resp.json()["code"] == "RFQ_NOT_FOUND"


async def test_status_filter_search_and_pagination(
    db_client: AsyncClient, buyer: Headers, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    upcoming = await create_rfq(db_client, buyer, name="Chennai reefer")
    active = await create_rfq(db_client, buyer, name="Pune LTL")
    closed = await create_rfq(db_client, buyer, name="Delhi FTL")
    await shift_times(
        sessionmaker, active["id"], start=-timedelta(minutes=5), close=timedelta(hours=1)
    )
    await shift_times(
        sessionmaker, closed["id"], start=-timedelta(hours=3), close=-timedelta(hours=1)
    )

    async def ids(**params: object) -> list[str]:
        body = (await db_client.get(RFQS, params=params, headers=buyer)).json()
        return [r["id"] for r in body["items"]]

    assert await ids(status="ACTIVE") == [active["id"]]
    assert await ids(status="SCHEDULED") == [upcoming["id"]]
    assert await ids(status="CLOSED") == [closed["id"]]
    assert set(await ids(status=["ACTIVE", "CLOSED"])) == {active["id"], closed["id"]}
    assert await ids(q="reefer") == [upcoming["id"]]
    assert await ids(q=closed["reference_id"]) == [closed["id"]]

    page = (await db_client.get(RFQS, params={"size": 2, "page": 2}, headers=buyer)).json()
    assert page["total"] == 3
    assert len(page["items"]) == 1

    listed = {
        r["id"]: r["status"] for r in (await db_client.get(RFQS, headers=buyer)).json()["items"]
    }
    assert listed == {upcoming["id"]: "SCHEDULED", active["id"]: "ACTIVE", closed["id"]: "CLOSED"}


# ---------------------------------------------------------------- update & cancel


async def test_update_requires_version(db_client: AsyncClient, buyer: Headers) -> None:
    rfq = await create_rfq(db_client, buyer)
    resp = await db_client.patch(f"{RFQS}/{rfq['id']}", json={"name": "New"}, headers=buyer)
    assert resp.status_code == 428


async def test_update_with_stale_version(db_client: AsyncClient, buyer: Headers) -> None:
    rfq = await create_rfq(db_client, buyer)
    url = f"{RFQS}/{rfq['id']}"
    ok = await db_client.patch(url, json={"name": "First"}, headers={**buyer, "If-Match": "1"})
    assert ok.status_code == 200
    assert ok.json()["version"] == 2

    stale = await db_client.patch(url, json={"name": "Second"}, headers={**buyer, "If-Match": "1"})
    assert stale.status_code == 412
    assert stale.json()["current_version"] == 2


async def test_update_schedule_and_disable_auction(db_client: AsyncClient, buyer: Headers) -> None:
    rfq = await create_rfq(db_client, buyer)
    url = f"{RFQS}/{rfq['id']}"
    new_close = (datetime.now(UTC) + timedelta(hours=2, minutes=30)).replace(microsecond=0)

    resp = await db_client.patch(
        url,
        json={"bid_close_at": new_close.isoformat(), "is_british_auction": False},
        headers={**buyer, "If-Match": '"1"'},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_close_at"] == new_close.isoformat().replace("+00:00", "Z")
    assert body["auction_config"] is None

    # Close now later than forced close → rejected.
    bad = await db_client.patch(
        url,
        json={"bid_close_at": (new_close + timedelta(hours=5)).isoformat()},
        headers={**buyer, "If-Match": "2"},
    )
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["type"] == "forced_close_not_after_close"


async def test_cannot_edit_or_cancel_after_start(
    db_client: AsyncClient, buyer: Headers, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    rfq = await create_rfq(db_client, buyer)
    await shift_times(
        sessionmaker, rfq["id"], start=-timedelta(minutes=1), close=timedelta(hours=1)
    )
    url = f"{RFQS}/{rfq['id']}"
    detail = (await db_client.get(url, headers=buyer)).json()
    assert detail["status"] == "ACTIVE"
    assert detail["permissions"] == {"can_edit": False, "can_cancel": False, "can_invite": True}

    edit = await db_client.patch(
        url, json={"name": "Late"}, headers={**buyer, "If-Match": str(detail["version"])}
    )
    assert edit.status_code == 409
    assert edit.json()["code"] == "RFQ_NOT_EDITABLE"
    assert (await db_client.post(f"{url}/cancel", headers=buyer)).status_code == 409


async def test_cancel(db_client: AsyncClient, buyer: Headers) -> None:
    rfq = await create_rfq(db_client, buyer)
    resp = await db_client.post(f"{RFQS}/{rfq['id']}/cancel", headers=buyer)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    assert resp.json()["permissions"]["can_invite"] is False
    again = await db_client.post(f"{RFQS}/{rfq['id']}/cancel", headers=buyer)
    assert again.json()["code"] == "RFQ_NOT_CANCELLABLE"


async def test_other_buyer_cannot_modify(
    db_client: AsyncClient, db_app: FastAPI, buyer: Headers
) -> None:
    _, other = await make_user(db_app, "b2@example.com", UserRole.BUYER)
    rfq = await create_rfq(db_client, buyer)
    url = f"{RFQS}/{rfq['id']}"
    assert (
        await db_client.patch(url, json={"name": "Hijacked"}, headers={**other, "If-Match": "1"})
    ).status_code == 404
    assert (await db_client.post(f"{url}/cancel", headers=other)).status_code == 404
    assert (
        await db_client.post(
            f"{url}/invitations", json={"emails": ["a@example.com"]}, headers=other
        )
    ).status_code == 404
