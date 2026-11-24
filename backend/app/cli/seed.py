"""Seed demo data (idempotent): one buyer, four suppliers and three demo RFQs
(one live, one upcoming, one closed) with suppliers already invited.

Run:  python -m app.cli.seed            (inside docker: make seed)

All demo accounts share the password in SEED_PASSWORD (default below). These are
local/demo credentials only; the command refuses to run in staging/production.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import create_engine, create_sessionmaker
from app.models.invitation import RfqInvitation
from app.models.rfq import AuctionConfig, Rfq, RfqStatus, TriggerType
from app.models.user import User, UserRole
from app.repositories.rfq_repo import RfqRepository
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


@dataclass(frozen=True)
class SeedRfq:
    name: str
    start: timedelta  # relative to now
    close: timedelta
    forced: timedelta
    trigger: TriggerType | None  # None = plain RFQ (no British Auction)
    invite: tuple[str, ...]


# Times are relative to "now", so a fresh seed always shows one auction in each state.
SEED_RFQS: tuple[SeedRfq, ...] = (
    SeedRfq(
        "Mumbai → Delhi FTL, 20T container",
        -timedelta(minutes=10),
        timedelta(minutes=50),
        timedelta(minutes=90),
        TriggerType.BID_RECEIVED,
        ("supplier1@example.com", "supplier2@example.com", "supplier3@example.com"),
    ),
    SeedRfq(
        "Chennai Port → Bengaluru reefer, 12T",
        timedelta(days=1),
        timedelta(days=1, hours=2),
        timedelta(days=1, hours=3),
        TriggerType.L1_RANK_CHANGE,
        ("supplier1@example.com", "supplier4@example.com"),
    ),
    SeedRfq(
        "Pune → Hyderabad LTL, 4 pallets",
        -timedelta(days=2),
        -timedelta(days=1, hours=22),
        -timedelta(days=1, hours=21),
        TriggerType.ANY_RANK_CHANGE,
        ("supplier2@example.com", "supplier3@example.com"),
    ),
)


async def seed_rfqs(session: AsyncSession) -> int:
    """Creates demo RFQs for the demo buyer if they have none. Inserted directly (not
    via the service) because some are deliberately in the past."""
    users = UserRepository(session)
    buyer = await users.get_by_email(SEED_USERS[0].email)
    if buyer is None:
        return 0
    if (await session.execute(select(Rfq.id).where(Rfq.buyer_id == buyer.id).limit(1))).first():
        return 0

    rfqs = RfqRepository(session)
    suppliers = await users.get_by_emails([u.email for u in SEED_USERS[1:]])
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    for sr in SEED_RFQS:
        start = now + sr.start
        rfq = Rfq(
            reference_id=f"RFQ-{start.year}-{await rfqs.next_reference_number():06d}",
            name=sr.name,
            buyer_id=buyer.id,
            is_british_auction=sr.trigger is not None,
            bid_start_at=start,
            bid_close_at=now + sr.close,
            current_close_at=now + sr.close,
            forced_close_at=now + sr.forced,
            pickup_date=(now + sr.forced + timedelta(days=2)).date(),
            status=RfqStatus.SCHEDULED,
            config=AuctionConfig(
                trigger_window_minutes=10, extension_minutes=5, trigger_type=sr.trigger
            )
            if sr.trigger
            else None,
        )
        await rfqs.add(rfq)
        for email in sr.invite:
            session.add(
                RfqInvitation(
                    rfq_id=rfq.id,
                    invitee_email=email,
                    supplier_id=suppliers[email].id,
                    invited_by=buyer.id,
                )
            )
    await session.commit()
    return len(SEED_RFQS)


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
            rfqs = await seed_rfqs(session)
        log.info("seed_complete", users_created=created, users_skipped=skipped, rfqs_created=rfqs)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
