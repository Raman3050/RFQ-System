"""Invite-only supplier onboarding: invite → email link → account → attached to RFQs."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.email.sender import OutgoingEmail
from app.models.auction_event import AuctionEvent
from app.models.invitation import SupplierInvite
from app.models.user import UserRole
from tests.integration.helpers import RFQS, bearer, create_rfq, invite_token, make_user

pytestmark = pytest.mark.integration

AUTH = "/api/v1/auth"


def accept_body(token: str, **overrides: Any) -> dict[str, Any]:
    return {
        "token": token,
        "password": "Carrier123",
        "full_name": "Arjun Mehta",
        "company_name": "BlueDart Freight",
        **overrides,
    }


@pytest.fixture
async def buyer(db_app: FastAPI) -> dict[str, str]:
    _, h = await make_user(db_app, "buyer@example.com", UserRole.BUYER, company="Acme")
    return h


async def test_full_onboarding_flow(
    db_client: AsyncClient,
    buyer: dict[str, str],
    outbox: list[OutgoingEmail],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    rfq = await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    token = invite_token(outbox[0])

    info = await db_client.post(f"{AUTH}/invitations/inspect", json={"token": token})
    assert info.status_code == 200
    assert info.json()["email"] == "new@example.com"
    assert info.json()["invited_by_company"] == "Acme"

    resp = await db_client.post(f"{AUTH}/invitations/accept", json=accept_body(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "SUPPLIER"
    assert body["user"]["email"] == "new@example.com"
    assert "rfq_refresh=" in resp.headers["set-cookie"]

    # The new supplier now sees the RFQ, and the buyer sees them as joined.
    supplier = bearer(body["access_token"])
    listing = (await db_client.get(RFQS, headers=supplier)).json()
    assert [r["id"] for r in listing["items"]] == [rfq["id"]]
    detail = (await db_client.get(f"{RFQS}/{rfq['id']}", headers=buyer)).json()
    assert detail["invitations"][0]["status"] == "JOINED"
    assert detail["invitations"][0]["supplier_company"] == "BlueDart Freight"

    async with sessionmaker() as s:
        events = (await s.execute(select(AuctionEvent.event_type))).scalars().all()
    assert "SUPPLIER_JOINED" in events

    # Supplier can log in normally afterwards.
    login = await db_client.post(
        f"{AUTH}/login", json={"email": "new@example.com", "password": "Carrier123"}
    )
    assert login.status_code == 200


async def test_invite_link_is_single_use(
    db_client: AsyncClient, buyer: dict[str, str], outbox: list[OutgoingEmail]
) -> None:
    await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    token = invite_token(outbox[0])
    assert (
        await db_client.post(f"{AUTH}/invitations/accept", json=accept_body(token))
    ).status_code == 201

    again = await db_client.post(f"{AUTH}/invitations/accept", json=accept_body(token))
    assert again.status_code == 410
    assert again.json()["code"] == "INVITE_USED"


async def test_expired_invite(
    db_client: AsyncClient,
    buyer: dict[str, str],
    outbox: list[OutgoingEmail],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    async with sessionmaker() as s:
        await s.execute(
            update(SupplierInvite).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    resp = await db_client.post(
        f"{AUTH}/invitations/inspect", json={"token": invite_token(outbox[0])}
    )
    assert resp.status_code == 410
    assert resp.json()["code"] == "INVITE_EXPIRED"


async def test_unknown_token(db_client: AsyncClient) -> None:
    resp = await db_client.post(f"{AUTH}/invitations/inspect", json={"token": "x" * 40})
    assert resp.status_code == 404
    assert resp.json()["code"] == "INVITE_INVALID"


async def test_resend_rotates_the_link(
    db_client: AsyncClient, buyer: dict[str, str], outbox: list[OutgoingEmail]
) -> None:
    rfq = await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    old = invite_token(outbox[0])

    resp = await db_client.post(
        f"{RFQS}/{rfq['id']}/invitations/new@example.com/resend", headers=buyer
    )
    assert resp.status_code == 202
    new = invite_token(outbox[1])
    assert new != old

    stale = await db_client.post(f"{AUTH}/invitations/inspect", json={"token": old})
    assert stale.json()["code"] == "INVITE_INVALID"
    fresh = await db_client.post(f"{AUTH}/invitations/inspect", json={"token": new})
    assert fresh.status_code == 200


async def test_one_account_joins_every_rfq_it_was_invited_to(
    db_client: AsyncClient,
    db_app: FastAPI,
    buyer: dict[str, str],
    outbox: list[OutgoingEmail],
) -> None:
    _, buyer2 = await make_user(db_app, "b2@example.com", UserRole.BUYER, company="Globex")
    a = await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    b = await create_rfq(db_client, buyer2, supplier_emails=["new@example.com"])

    # The second invite rotated the token: only the latest email's link works.
    resp = await db_client.post(
        f"{AUTH}/invitations/accept", json=accept_body(invite_token(outbox[-1]))
    )
    assert resp.status_code == 201
    supplier = bearer(resp.json()["access_token"])
    listing = (await db_client.get(RFQS, headers=supplier)).json()
    assert {r["id"] for r in listing["items"]} == {a["id"], b["id"]}


async def test_accept_validates_password(
    db_client: AsyncClient, buyer: dict[str, str], outbox: list[OutgoingEmail]
) -> None:
    await create_rfq(db_client, buyer, supplier_emails=["new@example.com"])
    resp = await db_client.post(
        f"{AUTH}/invitations/accept",
        json=accept_body(invite_token(outbox[0]), password="weak"),
    )
    assert resp.status_code == 422
