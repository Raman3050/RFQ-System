"""Import every ORM model here so Alembic autogenerate can see the full metadata."""

from app.db.base import Base
from app.models import (
    AuctionConfig,
    AuctionEvent,
    Bid,
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
    "Bid",
    "RefreshToken",
    "Rfq",
    "RfqInvitation",
    "SupplierInvite",
    "User",
]
