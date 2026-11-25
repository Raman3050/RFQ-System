"""Bid submission: the critical path of the auction.

Everything happens in ONE transaction that holds the RFQ row lock:

    lock RFQ → read DB clock → validate → rank before → insert bid → rank after
    → decide extension → update RFQ (close time, L1) → write activity log → commit

- The row lock serialises bids per auction (different auctions run in parallel), so two
  near-simultaneous bids can never both see the "before" ranking, double-extend, or
  produce an inconsistent L1.
- "Now" is read from Postgres *after* the lock is acquired, so a bid that waited on the
  lock past the close time is rejected, and every server agrees on the time.
- Bid insert, extension and log entries commit together or not at all.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.core.logging import get_logger
from app.domain.bidding import AuctionRules, ExtensionDecision, decide_extension, rank
from app.domain.rfq_status import effective_status
from app.models.auction_event import EventType
from app.models.bid import Bid
from app.models.invitation import RfqInvitation
from app.models.rfq import Rfq, RfqStatus
from app.models.user import User
from app.realtime.messages import auction_message, iso
from app.realtime.publisher import EventPublisher, NullPublisher
from app.repositories.bid_repo import BidRepository
from app.repositories.event_repo import EventRepository
from app.repositories.rfq_repo import RfqRepository
from app.schemas.bid import BidCreate, BidOut, BidResult, ExtensionOut

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Applied:
    decision: ExtensionDecision
    previous_close: datetime


class BiddingService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        publisher: EventPublisher | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.publisher: EventPublisher = publisher or NullPublisher()
        self.rfqs = RfqRepository(session)
        self.bids = BidRepository(session)
        self.events = EventRepository(session)

    async def submit(
        self,
        supplier: User,
        rfq_id: uuid.UUID,
        data: BidCreate,
        *,
        idempotency_key: str | None,
    ) -> BidResult:
        rfq = await self.rfqs.get_for_update(rfq_id)  # serialises all bids on this RFQ
        if rfq is None or not await self._is_invited(rfq.id, supplier.id):
            raise NotFoundError("RFQ not found", code="RFQ_NOT_FOUND")

        now = await self.bids.db_now()

        # A retried request (network blip, double click) returns the original result.
        if idempotency_key:
            existing = await self.bids.by_idempotency_key(rfq.id, supplier.id, idempotency_key)
            if existing is not None:
                return await self._result(rfq, existing, supplier.id, None, now, replayed=True)

        self._ensure_open(rfq, now)
        self._validate_quote(data, rfq, now)

        previous = await self.bids.latest_for_supplier(rfq.id, supplier.id)
        new_total = data.freight_charges + data.origin_charges + data.destination_charges
        if previous is not None and new_total >= previous.total_amount:
            raise ConflictError(
                "Your new bid must be lower than your current bid",
                code="BID_NOT_LOWER",
                extra={"your_current_total": str(previous.total_amount)},
            )

        before = [q.supplier_id for q in rank(await self.bids.latest_quotes(rfq.id))]

        bid = Bid(
            rfq_id=rfq.id,
            supplier_id=supplier.id,
            carrier_name=data.carrier_name,
            freight_charges=data.freight_charges,
            origin_charges=data.origin_charges,
            destination_charges=data.destination_charges,
            transit_time_days=data.transit_time_days,
            quote_validity_until=data.quote_validity_until,
            idempotency_key=idempotency_key,
            created_at=now,
        )
        self.bids.add(bid)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # same idempotency key raced in; the lock makes
            await self.session.rollback()  # this near-impossible, but never 500 on it
            raise ConflictError("Duplicate bid submission", code="DUPLICATE_BID") from exc
        await self.session.refresh(bid)  # load the DB-computed total_amount

        ranked = rank(await self.bids.latest_quotes(rfq.id))
        after = [q.supplier_id for q in ranked]
        my_rank = after.index(supplier.id) + 1

        applied = self._apply_extension(rfq, now, before, after)

        l1 = ranked[0]
        rfq.current_l1_amount = l1.total
        rfq.current_l1_bid_id = l1.bid_id

        last_event = self.events.record(
            rfq.id,
            EventType.BID_SUBMITTED,
            actor_id=supplier.id,
            payload={
                "bid_id": str(bid.id),
                "supplier_id": str(supplier.id),
                "supplier_company": supplier.company_name,
                "total_amount": str(bid.total_amount),
                "rank": my_rank,
                "is_revision": previous is not None,
                "became_l1": my_rank == 1 and (not before or before[0] != supplier.id),
            },
        )
        if applied is not None:
            last_event = self.events.record(
                rfq.id,
                EventType.TIME_EXTENDED,
                actor_id=supplier.id,
                payload={
                    "previous_close_at": applied.previous_close.isoformat(),
                    "new_close_at": rfq.current_close_at.isoformat(),
                    "reason": applied.decision.reason,
                    "trigger_type": rfq.config.trigger_type.value if rfq.config else None,
                    "extension_minutes": rfq.config.extension_minutes if rfq.config else None,
                    "capped_at_forced_close": applied.decision.capped,
                    "bid_id": str(bid.id),
                },
            )

        await self.session.commit()
        # After commit: tell every viewer something changed (they refetch their own view).
        await self.publisher.publish(
            auction_message(
                EventType.TIME_EXTENDED.value if applied else EventType.BID_SUBMITTED.value,
                rfq,
                seq=last_event.id,
                now=now,
                extension={
                    "previous_close_at": iso(applied.previous_close),
                    "new_close_at": iso(rfq.current_close_at),
                    "reason": applied.decision.reason,
                    "capped": applied.decision.capped,
                }
                if applied
                else None,
            )
        )
        log.info(
            "bid_submitted",
            rfq_id=str(rfq.id),
            bid_id=str(bid.id),
            rank=my_rank,
            extended=applied is not None,
        )
        return await self._result(rfq, bid, supplier.id, applied, now, replayed=False)

    # ---------------------------------------------------------------- helpers

    async def _is_invited(self, rfq_id: uuid.UUID, supplier_id: uuid.UUID) -> bool:
        stmt = select(
            select(RfqInvitation.rfq_id)
            .where(RfqInvitation.rfq_id == rfq_id, RfqInvitation.supplier_id == supplier_id)
            .exists()
        )
        return bool((await self.session.execute(stmt)).scalar())

    @staticmethod
    def _ensure_open(rfq: Rfq, now: datetime) -> None:
        status = effective_status(
            rfq.status,
            now=now,
            bid_start_at=rfq.bid_start_at,
            current_close_at=rfq.current_close_at,
            forced_close_at=rfq.forced_close_at,
        )
        if status == RfqStatus.ACTIVE:
            return
        if status == RfqStatus.SCHEDULED:
            raise ConflictError(
                "Bidding has not started yet",
                code="AUCTION_NOT_STARTED",
                extra={"bid_start_at": rfq.bid_start_at.isoformat()},
            )
        raise ConflictError(
            "Bidding is closed for this auction",
            code="AUCTION_CLOSED",
            extra={"status": status.value},
        )

    @staticmethod
    def _validate_quote(data: BidCreate, rfq: Rfq, now: datetime) -> None:
        """A quote must still be valid on the pickup/service date, otherwise the winning
        price could legally lapse before the goods move."""
        if data.quote_validity_until < now.astimezone(UTC).date():
            msg, kind = "Quote validity cannot be in the past", "validity_in_past"
        elif data.quote_validity_until < rfq.pickup_date:
            msg = (
                "Quote must be valid at least until the pickup date "
                f"({rfq.pickup_date.strftime('%d %b %Y')})"
            )
            kind = "validity_before_pickup"
        else:
            return
        raise DomainValidationError(
            [{"loc": ["body", "quote_validity_until"], "msg": msg, "type": kind}],
            extra={"pickup_date": rfq.pickup_date.isoformat()},
        )

    @staticmethod
    def _apply_extension(
        rfq: Rfq, now: datetime, before: list[uuid.UUID], after: list[uuid.UUID]
    ) -> _Applied | None:
        if not rfq.is_british_auction or rfq.config is None:
            return None
        decision = decide_extension(
            AuctionRules(
                trigger_window=timedelta(minutes=rfq.config.trigger_window_minutes),
                extension=timedelta(minutes=rfq.config.extension_minutes),
                trigger_type=rfq.config.trigger_type,
            ),
            now=now,
            current_close=rfq.current_close_at,
            forced_close=rfq.forced_close_at,
            before=before,
            after=after,
        )
        if not decision.extend or decision.new_close is None:
            return None
        previous = rfq.current_close_at
        rfq.current_close_at = decision.new_close
        rfq.extension_count += 1
        return _Applied(decision=decision, previous_close=previous)

    async def _result(
        self,
        rfq: Rfq,
        bid: Bid,
        supplier_id: uuid.UUID,
        applied: _Applied | None,
        now: datetime,
        *,
        replayed: bool,
    ) -> BidResult:
        ranked = [q.supplier_id for q in rank(await self.bids.latest_quotes(rfq.id))]
        return BidResult(
            bid=BidOut.model_validate(bid),
            rank=ranked.index(supplier_id) + 1,
            total_bidders=len(ranked),
            current_close_at=rfq.current_close_at,
            extension=ExtensionOut(
                previous_close_at=applied.previous_close,
                new_close_at=rfq.current_close_at,
                reason=applied.decision.reason,
                capped=applied.decision.capped,
            )
            if applied
            else None,
            replayed=replayed,
            server_time=now,
        )
