import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RfqInvitation(Base):
    """A supplier (by email) invited to bid on an RFQ.

    Keyed by email so buyers can invite people who have no account yet.
    `supplier_id` is filled in immediately for existing suppliers, or when the invitee
    accepts their account invite.
    """

    __tablename__ = "rfq_invitations"

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), primary_key=True
    )
    invitee_email: Mapped[str] = mapped_column(CITEXT(), primary_key=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_rfq_invitations_supplier_id", "supplier_id"),
        Index("ix_rfq_invitations_invitee_email", "invitee_email"),
    )


class SupplierInvite(Base):
    """One-time sign-up link for a supplier who has no account yet.

    At most one *pending* invite per email (partial unique index); re-inviting rotates
    the token and extends the expiry. Only the token's SHA-256 hash is stored.
    """

    __tablename__ = "supplier_invites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_supplier_invites_pending_email",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL"),
        ),
    )
