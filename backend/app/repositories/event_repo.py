import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_event import AuctionEvent, EventType


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
