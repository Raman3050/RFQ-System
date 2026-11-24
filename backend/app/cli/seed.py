"""Seed demo users (idempotent): one buyer and four suppliers.

Run:  python -m app.cli.seed            (inside docker: make seed)

All demo accounts share the password in SEED_PASSWORD (default below). These are
local/demo credentials only; the command refuses to run in staging/production.
"""

import asyncio
import os
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import create_engine, create_sessionmaker
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository

DEFAULT_SEED_PASSWORD = "Demo@12345"  # noqa: S105 - documented local demo credential

log = get_logger("app.cli.seed")


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    company_name: str
    role: UserRole


SEED_USERS: tuple[SeedUser, ...] = (
    SeedUser("buyer@example.com", "Priya Sharma", "Acme Manufacturing", UserRole.BUYER),
    SeedUser("supplier1@example.com", "Arjun Mehta", "BlueDart Freight", UserRole.SUPPLIER),
    SeedUser("supplier2@example.com", "Neha Gupta", "Swift Logistics", UserRole.SUPPLIER),
    SeedUser("supplier3@example.com", "Rahul Verma", "Oceanic Carriers", UserRole.SUPPLIER),
    SeedUser("supplier4@example.com", "Sara Khan", "TransGlobal Movers", UserRole.SUPPLIER),
)


async def seed_users(session: AsyncSession, password: str) -> tuple[int, int]:
    """Returns (created, skipped). Existing users are left untouched."""
    repo = UserRepository(session)
    password_hash = hash_password(password)
    created = skipped = 0
    for su in SEED_USERS:
        if await repo.get_by_email(su.email):
            skipped += 1
            continue
        await repo.add(
            User(
                email=su.email,
                password_hash=password_hash,
                full_name=su.full_name,
                company_name=su.company_name,
                role=su.role,
            )
        )
        created += 1
    await session.commit()
    return created, skipped


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    if settings.is_deployed:
        raise SystemExit("Refusing to seed demo users outside local/test environments")

    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            created, skipped = await seed_users(
                session, os.environ.get("SEED_PASSWORD", DEFAULT_SEED_PASSWORD)
            )
        log.info("seed_complete", created=created, skipped=skipped)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
