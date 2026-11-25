import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_event import AuctionEvent, EventType
from app.models.user import User


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        rfq_id: uuid.UUID,
        event_type: EventType,
        *,
        actor_id: uuid.UUID | None,
        payload: dict[str, Any] | None = None,
    ) -> AuctionEvent:
        event = AuctionEvent(
            rfq_id=rfq_id, event_type=event_type.value, actor_id=actor_id, payload=payload or {}
        )
        self.session.add(event)
        return event

    async def list_for_rfq(
        self,
        rfq_id: uuid.UUID,
        *,
        types: list[str] | None,
        before_id: int | None,
        limit: int,
    ) -> list[tuple[AuctionEvent, str | None, str | None]]:
        """Newest first, with the actor's (company, role)."""
        stmt = (
            select(AuctionEvent, User.company_name, User.role)
            .outerjoin(User, User.id == AuctionEvent.actor_id)
            .where(AuctionEvent.rfq_id == rfq_id)
            .order_by(AuctionEvent.id.desc())
            .limit(limit)
        )
        if types is not None:
            stmt = stmt.where(AuctionEvent.event_type.in_(types))
        if before_id is not None:
            stmt = stmt.where(AuctionEvent.id < before_id)
        return [
            (e, c, r.value if r is not None else None)
            for e, c, r in (await self.session.execute(stmt)).all()
        ]

    async def latest_id(self, rfq_id: uuid.UUID) -> int | None:
        result = await self.session.execute(
            select(func.max(AuctionEvent.id)).where(AuctionEvent.rfq_id == rfq_id)
        )
        latest: int | None = result.scalar()
        return latest
