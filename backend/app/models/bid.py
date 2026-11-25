import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

Money = Numeric(14, 2)


class Bid(Base):
    """One quote submission. Append-only: a supplier lowers their price by submitting a
    new bid; their latest bid is their active quote (and, by rule, their lowest)."""

    __tablename__ = "bids"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    carrier_name: Mapped[str] = mapped_column(String(120), nullable=False)
    freight_charges: Mapped[Decimal] = mapped_column(Money, nullable=False)
    origin_charges: Mapped[Decimal] = mapped_column(Money, nullable=False)
    destination_charges: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # Ranking price (design decision D1). Computed by Postgres so it can never drift.
    total_amount: Mapped[Decimal] = mapped_column(
        Money,
        Computed("freight_charges + origin_charges + destination_charges", persisted=True),
    )
    transit_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_validity_until: Mapped[date] = mapped_column(Date, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    # Set explicitly to the DB clock read under the auction lock (design decision D9).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Fetch total_amount via INSERT … RETURNING instead of a follow-up SELECT.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    __table_args__ = (
        CheckConstraint(
            "freight_charges >= 0 AND origin_charges >= 0 AND destination_charges >= 0",
            name="charges_non_negative",
        ),
        CheckConstraint(
            "freight_charges + origin_charges + destination_charges > 0", name="total_positive"
        ),
        CheckConstraint("transit_time_days BETWEEN 1 AND 365", name="transit_range"),
        # Latest bid per supplier (ranking) and a supplier's own history.
        Index("ix_bids_rfq_supplier_created", "rfq_id", "supplier_id", "created_at"),
        Index("ix_bids_rfq_total", "rfq_id", "total_amount", "created_at"),
        Index(
            "uq_bids_supplier_idempotency_key",
            "rfq_id",
            "supplier_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
