"""Test fixtures.

Unit tests use `client` (no database). Integration tests (marked `integration`) use
`db_client`, which runs against a dedicated `<db>_test` database that is recreated and
migrated with Alembic once per test session, and truncated after every test.

If Postgres is unreachable, integration tests are skipped locally. Set
REQUIRE_INTEGRATION=1 (CI does) to make that a hard failure instead.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cache.redis import create_redis
from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.email.sender import MemoryEmailSender, OutgoingEmail
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- unit-test fixtures


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", log_json=False, log_level="WARNING")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """No lifespan, no DB. Tests override any dependency that would touch I/O."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------- integration fixtures


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(str(get_settings().database_url))
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


async def _recreate_database(url: str) -> None:
    u = make_url(url)
    conn = await asyncpg.connect(
        user=u.username, password=u.password, host=u.host, port=u.port, database="postgres"
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{u.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    """Sync fixture so Alembic's own asyncio.run() isn't nested in pytest's loop."""
    url = _test_database_url()
    try:
        asyncio.run(_recreate_database(url))
    except (OSError, asyncpg.PostgresError) as exc:
        if os.environ.get("REQUIRE_INTEGRATION") == "1":
            raise
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
def integration_settings(integration_db_url: str) -> Settings:
    return Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        database_url=integration_db_url,  # type: ignore[arg-type]
        email_backend="memory",
        frontend_base_url="http://app.test",
    )


@pytest.fixture
async def db_app(integration_settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(integration_settings)
    engine = create_engine(integration_settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = create_redis(integration_settings)
    try:
        yield app
    finally:
        async with engine.begin() as conn:
            # Every table references users, so this cascades through all of them.
            await conn.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
        await app.state.redis.aclose()
        await engine.dispose()


@pytest.fixture
def outbox(db_app: FastAPI) -> list[OutgoingEmail]:
    """Emails "sent" during the test (in-memory email backend)."""
    sender: MemoryEmailSender = db_app.state.email_sender
    return sender.outbox


@pytest.fixture
def sessionmaker(db_app: FastAPI) -> async_sessionmaker[AsyncSession]:
    sm: async_sessionmaker[AsyncSession] = db_app.state.sessionmaker
    return sm


@pytest.fixture
async def db_client(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=db_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
