"""Auction lifecycle: persist SCHEDULED → ACTIVE → CLOSED / FORCE_CLOSED on time.

Readers never depend on this (status is always derived from the clock, and the bid path
re-checks time under the row lock), so worker lag can't let a late bid in. The worker
makes the stored state and the activity log match reality, and fixes the winning bid.

Safety:
- `FOR UPDATE SKIP LOCKED` lets any number of worker replicas run: each RFQ row is
  processed by exactly one of them, and a row currently locked by a bid in flight is
  skipped and picked up on the next tick (after the bid's possible extension).
- The due-condition is evaluated against the DB clock *while holding the lock*, so a bid
  that extended the close just before can't be closed early.
- Each batch is its own short transaction; a crash mid-batch rolls back cleanly.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.auction_event import EventType
from app.models.bid import Bid
from app.models.rfq import Rfq, RfqStatus
from app.models.user import User
from app.repositories.event_repo import EventRepository

log = get_logger("app.lifecycle")

BATCH_SIZE = 100


@dataclass
class TickStats:
    started: int = 0
    closed: int = 0
    force_closed: int = 0
    closed_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.started + self.closed + self.force_closed


async def _db_now(session: AsyncSession) -> datetime:
    now: datetime = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
    return now


class LifecycleService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def run_once(self) -> TickStats:
        """Process everything that is due, in batches. Safe to call concurrently."""
        stats = TickStats()
        while await self._start_batch(stats) == BATCH_SIZE:
            pass
        while await self._close_batch(stats) == BATCH_SIZE:
            pass
        if stats.changed:
            log.info(
                "lifecycle_tick",
                started=stats.started,
                closed=stats.closed,
                force_closed=stats.force_closed,
            )
        return stats

    # ---------------------------------------------------------------- start

    async def _start_batch(self, stats: TickStats) -> int:
        async with self.sessionmaker() as session, session.begin():
            now = await _db_now(session)
            rows = (
                (
                    await session.execute(
                        select(Rfq)
                        .where(
                            Rfq.status == RfqStatus.SCHEDULED,
                            Rfq.bid_start_at <= now,
                            Rfq.current_close_at > now,  # already over → handled by close
                        )
                        .order_by(Rfq.bid_start_at)
                        .limit(BATCH_SIZE)
                        .with_for_update(skip_locked=True, of=Rfq)
                    )
                )
                .unique()
                .scalars()
                .all()
            )
            events = EventRepository(session)
            for rfq in rows:
                rfq.status = RfqStatus.ACTIVE
                events.record(
                    rfq.id,
                    EventType.AUCTION_STARTED,
                    actor_id=None,
                    payload={"bid_start_at": rfq.bid_start_at.isoformat()},
                )
            stats.started += len(rows)
            return len(rows)

    # ---------------------------------------------------------------- close

    async def _close_batch(self, stats: TickStats) -> int:
        async with self.sessionmaker() as session, session.begin():
            now = await _db_now(session)
            rows = (
                (
                    await session.execute(
                        select(Rfq)
                        .where(
                            Rfq.status.in_([RfqStatus.SCHEDULED, RfqStatus.ACTIVE]),
                            Rfq.current_close_at <= now,
                        )
                        .order_by(Rfq.current_close_at)
                        .limit(BATCH_SIZE)
                        .with_for_update(skip_locked=True, of=Rfq)
                    )
                )
                .unique()
                .scalars()
                .all()
            )
            events = EventRepository(session)
            for rfq in rows:
                if rfq.status == RfqStatus.SCHEDULED:
                    # The worker was down for the whole auction: record the start too.
                    events.record(
                        rfq.id,
                        EventType.AUCTION_STARTED,
                        actor_id=None,
                        payload={"bid_start_at": rfq.bid_start_at.isoformat(), "late": True},
                    )
                    stats.started += 1
                forced = rfq.current_close_at >= rfq.forced_close_at
                rfq.status = RfqStatus.FORCE_CLOSED if forced else RfqStatus.CLOSED
                rfq.closed_at = now
                events.record(
                    rfq.id,
                    EventType.AUCTION_FORCE_CLOSED if forced else EventType.AUCTION_CLOSED,
                    actor_id=None,
                    payload=await self._result_payload(session, rfq, forced),
                )
                if forced:
                    stats.force_closed += 1
                else:
                    stats.closed += 1
                stats.closed_ids.append(rfq.id)
            return len(rows)

    @staticmethod
    async def _result_payload(session: AsyncSession, rfq: Rfq, forced: bool) -> dict[str, Any]:
        counts = (
            await session.execute(
                select(func.count(), func.count(func.distinct(Bid.supplier_id))).where(
                    Bid.rfq_id == rfq.id
                )
            )
        ).one()
        payload: dict[str, Any] = {
            "closed_at_scheduled": rfq.current_close_at.isoformat(),
            "original_close_at": rfq.bid_close_at.isoformat(),
            "forced_close_at": rfq.forced_close_at.isoformat(),
            "reason": "Reached the forced close time" if forced else "Bid close time reached",
            "extension_count": rfq.extension_count,
            "total_bids": int(counts[0]),
            "bidders": int(counts[1]),
            "winning_bid_id": None,
            "winning_supplier_id": None,
            "winning_supplier_company": None,
            "winning_total": None,
        }
        if rfq.current_l1_bid_id is not None:
            winner = (
                await session.execute(
                    select(Bid.id, Bid.supplier_id, Bid.total_amount, User.company_name)
                    .join(User, User.id == Bid.supplier_id)
                    .where(Bid.id == rfq.current_l1_bid_id)
                )
            ).one_or_none()
            if winner is not None:
                payload.update(
                    winning_bid_id=str(winner[0]),
                    winning_supplier_id=str(winner[1]),
                    winning_total=str(winner[2]),
                    winning_supplier_company=winner[3],
                )
        return payload
