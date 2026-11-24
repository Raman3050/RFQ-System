import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.email.sender import OutgoingEmail
from app.models.user import User, UserRole

PASSWORD = "Secret123"
RFQS = "/api/v1/rfqs"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    app: FastAPI,
    email: str,
    role: UserRole,
    *,
    full_name: str = "Test User",
    company: str = "Test Co",
) -> tuple[User, dict[str, str]]:
    """Creates a user directly and returns (user, auth headers)."""
    async with app.state.sessionmaker() as s:
        user = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            full_name=full_name,
            company_name=company,
            role=role,
        )
        s.add(user)
        await s.commit()
    token, _ = create_access_token(app.state.settings, user_id=user.id, role=role.value)
    return user, bearer(token)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def rfq_payload(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    body: dict[str, Any] = {
        "name": "Mumbai to Delhi FTL 20T",
        "bid_start_at": iso(now + timedelta(hours=1)),
        "bid_close_at": iso(now + timedelta(hours=2)),
        "forced_close_at": iso(now + timedelta(hours=3)),
        "pickup_date": (now + timedelta(days=3)).date().isoformat(),
        "is_british_auction": True,
        "auction_config": {
            "trigger_window_minutes": 10,
            "extension_minutes": 5,
            "trigger_type": "BID_RECEIVED",
        },
    }
    body.update(overrides)
    return body


async def create_rfq(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> Any:
    resp = await client.post(RFQS, json=rfq_payload(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def invite_token(message: OutgoingEmail) -> str:
    match = re.search(r"accept-invite\?token=([\w-]+)", message.text)
    assert match, message.text
    return match.group(1)
