import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# Feeds human-readable reference ids: RFQ-2026-000123.
rfq_reference_seq = Sequence("rfq_reference_seq", metadata=Base.metadata)


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class RfqStatus(enum.StrEnum):
    """Stored status. The *effective* status also depends on the clock — see
    app.domain.rfq_status.effective_status."""

    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    FORCE_CLOSED = "FORCE_CLOSED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset({RfqStatus.CLOSED, RfqStatus.FORCE_CLOSED, RfqStatus.CANCELLED})


class TriggerType(enum.StrEnum):
    BID_RECEIVED = "BID_RECEIVED"
    ANY_RANK_CHANGE = "ANY_RANK_CHANGE"
    L1_RANK_CHANGE = "L1_RANK_CHANGE"


class Rfq(TimestampMixin, Base):
    __tablename__ = "rfqs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    reference_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_british_auction: Mapped[bool] = mapped_column(Boolean, nullable=False)

    bid_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bid_close_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Originally scheduled close"
    )
    current_close_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Moves forward on each extension"
    )
    forced_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[RfqStatus] = mapped_column(
        _pg_enum(RfqStatus, "rfq_status"),
        nullable=False,
        server_default=RfqStatus.SCHEDULED.value,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    extension_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    config: Mapped["AuctionConfig | None"] = relationship(
        back_populates="rfq", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )

    # Optimistic concurrency: every UPDATE checks and bumps `version`.
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012

    __table_args__ = (
        CheckConstraint("bid_close_at > bid_start_at", name="close_after_start"),
        CheckConstraint("forced_close_at > bid_close_at", name="forced_after_close"),
        CheckConstraint("current_close_at >= bid_close_at", name="current_not_before_close"),
        CheckConstraint("current_close_at <= forced_close_at", name="current_within_forced"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("extension_count >= 0", name="extension_count_non_negative"),
        Index("ix_rfqs_buyer_created", "buyer_id", "created_at"),
        Index("ix_rfqs_status_close", "status", "current_close_at"),
        Index("ix_rfqs_status_start", "status", "bid_start_at"),
    )


class AuctionConfig(Base):
    """British Auction rules for an RFQ (absent when is_british_auction is false)."""

    __tablename__ = "auction_configs"

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), primary_key=True
    )
    trigger_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)  # X
    extension_minutes: Mapped[int] = mapped_column(Integer, nullable=False)  # Y
    trigger_type: Mapped[TriggerType] = mapped_column(
        _pg_enum(TriggerType, "auction_trigger_type"), nullable=False
    )

    rfq: Mapped[Rfq] = relationship(back_populates="config")

    __table_args__ = (
        CheckConstraint("trigger_window_minutes BETWEEN 1 AND 1440", name="trigger_window_range"),
        CheckConstraint("extension_minutes BETWEEN 1 AND 1440", name="extension_range"),
    )
