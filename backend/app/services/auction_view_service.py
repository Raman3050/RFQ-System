"""Read models for the auction details page: leaderboard, bid history, activity log.

Visibility rules (design decision D10):
- The buyer (and admins) see everything.
- A supplier sees every competitor's rank, price and transit time ("bids openly"), but
  competitors are shown as "Bidder N" and their charge breakdown is hidden. A supplier
  always sees full details of their own quotes.
- Suppliers only see auction-progress events (bids, extensions, open/close), never the
  buyer's invitation management.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.domain.bidding import Quote, rank
from app.domain.rfq_status import effective_status
from app.models.auction_event import EventType
from app.models.user import User, UserRole
from app.repositories.bid_repo import BidRepository
from app.repositories.event_repo import EventRepository
from app.repositories.rfq_repo import RfqRepository, RfqRow
from app.schemas.bid import (
    BidHistoryItem,
    BidOut,
    EventOut,
    EventPage,
    Leaderboard,
    LeaderboardEntry,
)

SUPPLIER_VISIBLE_EVENTS = [
    EventType.BID_SUBMITTED,
    EventType.TIME_EXTENDED,
    EventType.AUCTION_STARTED,
    EventType.AUCTION_CLOSED,
    EventType.AUCTION_FORCE_CLOSED,
    EventType.RFQ_CANCELLED,
]


class AuctionViewService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.rfqs = RfqRepository(session)
        self.bids = BidRepository(session)
        self.events = EventRepository(session)

    async def _access(self, user: User, rfq_id: uuid.UUID) -> tuple[RfqRow, bool]:
        row = await self.rfqs.get_visible(rfq_id, user)
        if row is None:
            raise NotFoundError("RFQ not found", code="RFQ_NOT_FOUND")
        full_access = user.role == UserRole.ADMIN or row.rfq.buyer_id == user.id
        return row, full_access

    async def leaderboard(self, user: User, rfq_id: uuid.UUID) -> Leaderboard:
        row, full = await self._access(user, rfq_id)
        rfq = row.rfq
        now = datetime.now(UTC)
        latest = await self.bids.leaderboard_rows(rfq.id)
        aliases = await self.bids.supplier_aliases(rfq.id)
        by_supplier = {r.bid.supplier_id: r for r in latest}
        ranked = rank(
            [
                Quote(r.bid.supplier_id, r.bid.id, r.bid.total_amount, r.bid.created_at)
                for r in latest
            ]
        )

        entries: list[LeaderboardEntry] = []
        my_rank = None
        my_total = None
        for i, q in enumerate(ranked, start=1):
            r = by_supplier[q.supplier_id]
            is_you = q.supplier_id == user.id
            show = full or is_you
            if is_you:
                my_rank, my_total = i, r.bid.total_amount
            entries.append(
                LeaderboardEntry(
                    rank=i,
                    label=f"L{i}",
                    supplier_label=r.supplier_company if show else aliases[q.supplier_id],
                    is_you=is_you,
                    total_amount=r.bid.total_amount,
                    transit_time_days=r.bid.transit_time_days,
                    bid_count=r.bid_count,
                    last_bid_at=r.bid.created_at,
                    supplier_name=r.supplier_name if show else None,
                    carrier_name=r.bid.carrier_name if show else None,
                    freight_charges=r.bid.freight_charges if show else None,
                    origin_charges=r.bid.origin_charges if show else None,
                    destination_charges=r.bid.destination_charges if show else None,
                    quote_validity_until=r.bid.quote_validity_until if show else None,
                )
            )

        return Leaderboard(
            status=effective_status(
                rfq.status,
                now=now,
                bid_start_at=rfq.bid_start_at,
                current_close_at=rfq.current_close_at,
                forced_close_at=rfq.forced_close_at,
            ),
            currency=rfq.currency,
            current_close_at=rfq.current_close_at,
            forced_close_at=rfq.forced_close_at,
            extension_count=rfq.extension_count,
            entries=entries,
            my_rank=my_rank,
            my_current_total=my_total,
            server_time=now,
        )

    async def bid_history(self, user: User, rfq_id: uuid.UUID) -> list[BidHistoryItem]:
        """Buyer: every bid on the RFQ. Supplier: their own bids only."""
        row, full = await self._access(user, rfq_id)
        rows = await self.bids.history(row.rfq.id, None if full else user.id)
        return [
            BidHistoryItem(**BidOut.model_validate(b).model_dump(), supplier_company=company)
            for b, company in rows
        ]

    async def activity(
        self, user: User, rfq_id: uuid.UUID, *, before_id: int | None, limit: int
    ) -> EventPage:
        row, full = await self._access(user, rfq_id)
        types = None if full else [t.value for t in SUPPLIER_VISIBLE_EVENTS]
        rows = await self.events.list_for_rfq(
            row.rfq.id, types=types, before_id=before_id, limit=limit
        )
        aliases = {} if full else await self.bids.supplier_aliases(row.rfq.id)

        items = []
        for event, company, role in rows:
            payload = dict(event.payload)
            actor = company
            if not full and role == UserRole.SUPPLIER.value:
                is_you = event.actor_id == user.id
                alias = "You" if is_you else aliases.get(event.actor_id, "A bidder")  # type: ignore[arg-type]
                actor = alias
                if event.event_type == EventType.BID_SUBMITTED:
                    payload["supplier_company"] = alias
                    payload["is_you"] = is_you
                    payload.pop("supplier_id", None)
            items.append(
                EventOut(
                    id=event.id,
                    type=event.event_type,
                    created_at=event.created_at,
                    actor=actor,
                    payload=payload,
                )
            )
        return EventPage(
            items=items,
            next_before_id=items[-1].id if len(items) == limit else None,
            server_time=datetime.now(UTC),
        )
