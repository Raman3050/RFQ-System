import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bidding import Quote
from app.models.bid import Bid
from app.models.user import User


@dataclass(frozen=True, slots=True)
class LatestBidRow:
    bid: Bid
    supplier_name: str
    supplier_company: str
    bid_count: int
    first_bid_at: datetime


class BidRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def db_now(self) -> datetime:
        """The authoritative clock (design decision D9). clock_timestamp() — not now() — so it is
        read *after* the row lock was acquired, not at transaction start."""
        result = await self.session.execute(text("SELECT clock_timestamp()"))
        now: datetime = result.scalar_one()
        return now

    def add(self, bid: Bid) -> None:
        self.session.add(bid)

    async def latest_quotes(self, rfq_id: uuid.UUID) -> list[Quote]:
        """Each supplier's latest bid (= their active, lowest quote)."""
        stmt = (
            select(Bid.supplier_id, Bid.id, Bid.total_amount, Bid.created_at)
            .where(Bid.rfq_id == rfq_id)
            .ext(distinct_on(Bid.supplier_id))
            .order_by(Bid.supplier_id, Bid.created_at.desc(), Bid.id.desc())
        )
        return [
            Quote(supplier_id=s, bid_id=b, total=t, created_at=c)
            for s, b, t, c in (await self.session.execute(stmt)).all()
        ]

    async def by_idempotency_key(
        self, rfq_id: uuid.UUID, supplier_id: uuid.UUID, key: str
    ) -> Bid | None:
        stmt = select(Bid).where(
            Bid.rfq_id == rfq_id, Bid.supplier_id == supplier_id, Bid.idempotency_key == key
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def supplier_has_bid(self, rfq_id: uuid.UUID, supplier_id: uuid.UUID) -> bool:
        stmt = select(
            select(Bid.id).where(Bid.rfq_id == rfq_id, Bid.supplier_id == supplier_id).exists()
        )
        return bool((await self.session.execute(stmt)).scalar())

    async def leaderboard_rows(self, rfq_id: uuid.UUID) -> list[LatestBidRow]:
        stats = (
            select(
                Bid.supplier_id.label("supplier_id"),
                func.count().label("bid_count"),
                func.min(Bid.created_at).label("first_bid_at"),
            )
            .where(Bid.rfq_id == rfq_id)
            .group_by(Bid.supplier_id)
            .subquery()
        )
        latest = (
            select(Bid.id)
            .where(Bid.rfq_id == rfq_id)
            .ext(distinct_on(Bid.supplier_id))
            .order_by(Bid.supplier_id, Bid.created_at.desc(), Bid.id.desc())
            .subquery()
        )
        stmt = (
            select(Bid, User.full_name, User.company_name, stats.c.bid_count, stats.c.first_bid_at)
            .join(latest, latest.c.id == Bid.id)
            .join(User, User.id == Bid.supplier_id)
            .join(stats, stats.c.supplier_id == Bid.supplier_id)
        )
        return [
            LatestBidRow(bid=b, supplier_name=n, supplier_company=c, bid_count=k, first_bid_at=f)
            for b, n, c, k, f in (await self.session.execute(stmt)).all()
        ]

    async def history(
        self, rfq_id: uuid.UUID, supplier_id: uuid.UUID | None, limit: int = 500
    ) -> list[tuple[Bid, str]]:
        stmt = (
            select(Bid, User.company_name)
            .join(User, User.id == Bid.supplier_id)
            .where(Bid.rfq_id == rfq_id)
            .order_by(Bid.created_at.desc(), Bid.id.desc())
            .limit(limit)
        )
        if supplier_id is not None:
            stmt = stmt.where(Bid.supplier_id == supplier_id)
        return [(b, c) for b, c in (await self.session.execute(stmt)).all()]

    async def supplier_aliases(self, rfq_id: uuid.UUID) -> dict[uuid.UUID, str]:
        """Stable anonymous labels: 'Bidder 1' is whoever bid first on this RFQ."""
        stmt = (
            select(Bid.supplier_id, func.min(Bid.created_at).label("first"))
            .where(Bid.rfq_id == rfq_id)
            .group_by(Bid.supplier_id)
            .order_by("first", Bid.supplier_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {sid: f"Bidder {i}" for i, (sid, _) in enumerate(rows, start=1)}
