import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import BuyerUser
from app.cli.seed import SEED_USERS, seed_users
from app.core.security import create_access_token
from app.models.refresh_token import RefreshToken
from app.models.user import User

pytestmark = pytest.mark.integration

AUTH = "/api/v1/auth"
COOKIE = "rfq_refresh"
PASSWORD = "Secret123"


def register_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "email": "buyer@example.com",
        "password": PASSWORD,
        "full_name": "Priya Sharma",
        "company_name": "Acme",
        "role": "BUYER",
        **overrides,
    }


async def register(client: AsyncClient, **overrides: Any) -> Response:
    return await client.post(f"{AUTH}/register", json=register_payload(**overrides))


async def refresh_with(client: AsyncClient, token: str) -> Response:
    """Send a specific refresh token, bypassing the client's cookie jar."""
    client.cookies.clear()
    return await client.post(f"{AUTH}/refresh", headers={"Cookie": f"{COOKIE}={token}"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- register


async def test_register_creates_user_and_starts_session(db_client: AsyncClient) -> None:
    resp = await register(db_client)

    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["user"]["email"] == "buyer@example.com"
    assert body["user"]["role"] == "BUYER"
    assert "password" not in str(body)

    set_cookie = resp.headers["set-cookie"]
    assert f"{COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert resp.headers["cache-control"] == "no-store"


async def test_register_duplicate_email_is_case_insensitive(db_client: AsyncClient) -> None:
    await register(db_client)
    resp = await register(db_client, email="BUYER@Example.com")
    assert resp.status_code == 409
    assert resp.json()["code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"role": "ADMIN"}, "role"),
        ({"password": "short1"}, "password"),
        ({"password": "lettersonly"}, "password"),
        ({"password": "1234567890"}, "password"),
        ({"email": "not-an-email"}, "email"),
        ({"full_name": "   "}, "full_name"),
    ],
)
async def test_register_validation(
    db_client: AsyncClient, override: dict[str, str], field: str
) -> None:
    resp = await register(db_client, **override)
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["loc"][-1] == field


# ---------------------------------------------------------------- login


async def test_login_success_and_me(db_client: AsyncClient) -> None:
    await register(db_client)
    resp = await db_client.post(
        f"{AUTH}/login", json={"email": "Buyer@Example.com", "password": PASSWORD}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = await db_client.get(f"{AUTH}/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == "buyer@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [("buyer@example.com", "WrongPass1"), ("nobody@example.com", PASSWORD)],
)
async def test_login_failures_are_indistinguishable(
    db_client: AsyncClient, email: str, password: str
) -> None:
    await register(db_client)
    resp = await db_client.post(f"{AUTH}/login", json={"email": email, "password": password})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"
    assert resp.json()["detail"] == "Invalid email or password"
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_disabled_account_cannot_log_in(
    db_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await register(db_client)
    async with sessionmaker() as s:
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    resp = await db_client.post(
        f"{AUTH}/login", json={"email": "buyer@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "ACCOUNT_DISABLED"


# ---------------------------------------------------------------- access token guard


async def test_me_requires_token(db_client: AsyncClient) -> None:
    resp = await db_client.get(f"{AUTH}/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "NOT_AUTHENTICATED"
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_me_rejects_garbage_token(db_client: AsyncClient) -> None:
    resp = await db_client.get(f"{AUTH}/me", headers=bearer("abc.def.ghi"))
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_INVALID"


async def test_me_reports_expired_token(db_app: FastAPI, db_client: AsyncClient) -> None:
    user_id = uuid.UUID((await register(db_client)).json()["user"]["id"])
    expired, _ = create_access_token(
        db_app.state.settings,
        user_id=user_id,
        role="BUYER",
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    resp = await db_client.get(f"{AUTH}/me", headers=bearer(expired))
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_EXPIRED"


async def test_role_guard(db_app: FastAPI, db_client: AsyncClient) -> None:
    @db_app.get("/_test/buyer-only")
    async def buyer_only(user: BuyerUser) -> dict[str, str]:
        return {"ok": user.email}

    buyer = (await register(db_client)).json()["access_token"]
    supplier = (await register(db_client, email="s@example.com", role="SUPPLIER")).json()[
        "access_token"
    ]

    assert (await db_client.get("/_test/buyer-only", headers=bearer(buyer))).status_code == 200
    denied = await db_client.get("/_test/buyer-only", headers=bearer(supplier))
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN_ROLE"
    assert denied.json()["required_roles"] == ["ADMIN", "BUYER"]


# ---------------------------------------------------------------- refresh rotation


async def test_refresh_rotates_cookie_and_issues_new_access_token(
    db_client: AsyncClient,
) -> None:
    first = (await register(db_client)).cookies[COOKIE]

    resp = await refresh_with(db_client, first)
    assert resp.status_code == 200
    second = resp.cookies[COOKIE]
    assert second != first
    me = await db_client.get(f"{AUTH}/me", headers=bearer(resp.json()["access_token"]))
    assert me.status_code == 200


async def test_reusing_a_rotated_token_revokes_the_whole_family(
    db_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = (await register(db_client)).cookies[COOKIE]
    second = (await refresh_with(db_client, first)).cookies[COOKIE]

    replay = await refresh_with(db_client, first)
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_TOKEN_REUSED"

    # The legitimate latest token is now dead too.
    after = await refresh_with(db_client, second)
    assert after.status_code == 401
    async with sessionmaker() as s:
        active = (
            await s.execute(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
        ).all()
    assert active == []


async def test_separate_logins_are_independent_sessions(db_client: AsyncClient) -> None:
    laptop = (await register(db_client)).cookies[COOKIE]
    phone = (
        await db_client.post(
            f"{AUTH}/login", json={"email": "buyer@example.com", "password": PASSWORD}
        )
    ).cookies[COOKIE]

    await refresh_with(db_client, laptop)
    await refresh_with(db_client, laptop)  # replay kills only the laptop family

    assert (await refresh_with(db_client, phone)).status_code == 200


async def test_refresh_without_cookie(db_client: AsyncClient) -> None:
    resp = await db_client.post(f"{AUTH}/refresh")
    assert resp.status_code == 401
    assert resp.json()["code"] == "REFRESH_TOKEN_MISSING"


async def test_refresh_with_unknown_token(db_client: AsyncClient) -> None:
    resp = await refresh_with(db_client, "made-up-token")
    assert resp.status_code == 401
    assert resp.json()["code"] == "REFRESH_TOKEN_INVALID"


async def test_expired_refresh_token(
    db_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    token = (await register(db_client)).cookies[COOKIE]
    async with sessionmaker() as s:
        await s.execute(
            update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    resp = await refresh_with(db_client, token)
    assert resp.status_code == 401
    assert resp.json()["code"] == "REFRESH_TOKEN_EXPIRED"


# ---------------------------------------------------------------- logout


async def test_logout_revokes_session_and_clears_cookie(db_client: AsyncClient) -> None:
    token = (await register(db_client)).cookies[COOKIE]
    client_cookie = {"Cookie": f"{COOKIE}={token}"}

    resp = await db_client.post(f"{AUTH}/logout", headers=client_cookie)
    assert resp.status_code == 204
    assert (
        'rfq_refresh=""' in resp.headers["set-cookie"] or "Max-Age=0" in resp.headers["set-cookie"]
    )
    after = await refresh_with(db_client, token)
    assert after.status_code == 401
    # A logged-out token is not a theft signal.
    assert after.json()["code"] == "REFRESH_TOKEN_INVALID"


async def test_logout_without_session_is_noop(db_client: AsyncClient) -> None:
    assert (await db_client.post(f"{AUTH}/logout")).status_code == 204


# ---------------------------------------------------------------- seed


async def test_seed_is_idempotent_and_users_can_log_in(
    db_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as s:
        assert await seed_users(s, "Seed@12345") == (len(SEED_USERS), 0)
    async with sessionmaker() as s:
        assert await seed_users(s, "Seed@12345") == (0, len(SEED_USERS))

    for su in SEED_USERS:
        resp = await db_client.post(
            f"{AUTH}/login", json={"email": su.email, "password": "Seed@12345"}
        )
        assert resp.status_code == 200, su.email
        assert resp.json()["user"]["role"] == su.role.value
