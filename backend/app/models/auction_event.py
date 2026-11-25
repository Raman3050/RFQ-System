import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventType(enum.StrEnum):
    # Phase 2
    RFQ_CREATED = "RFQ_CREATED"
    RFQ_UPDATED = "RFQ_UPDATED"
    RFQ_CANCELLED = "RFQ_CANCELLED"
    SUPPLIER_INVITED = "SUPPLIER_INVITED"
    SUPPLIER_JOINED = "SUPPLIER_JOINED"
    SUPPLIER_REMOVED = "SUPPLIER_REMOVED"
    # Phase 3+
    BID_SUBMITTED = "BID_SUBMITTED"
    RANK_CHANGED = "RANK_CHANGED"
    TIME_EXTENDED = "TIME_EXTENDED"
    AUCTION_STARTED = "AUCTION_STARTED"
    AUCTION_CLOSED = "AUCTION_CLOSED"
    AUCTION_FORCE_CLOSED = "AUCTION_FORCE_CLOSED"


class AuctionEvent(Base):
    """Append-only activity log per RFQ. The monotonically increasing `id` doubles as a
    sequence number for real-time clients to detect gaps (Phase 5)."""

    __tablename__ = "auction_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False
    )
    # String (not a PG enum) so new event types never need a migration.
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_auction_events_rfq_id_id", "rfq_id", "id"),)
