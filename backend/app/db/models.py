"""Import every ORM model here so Alembic autogenerate can see the full metadata."""

from app.db.base import Base
from app.models import (
    AuctionConfig,
    AuctionEvent,
    RefreshToken,
    Rfq,
    RfqInvitation,
    SupplierInvite,
    User,
)

__all__ = [
    "AuctionConfig",
    "AuctionEvent",
    "Base",
    "RefreshToken",
    "Rfq",
    "RfqInvitation",
    "SupplierInvite",
    "User",
]
