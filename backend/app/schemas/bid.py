import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.rfq import RfqStatus
from app.schemas.common import UtcOut

Amount = Annotated[
    Decimal,
    Field(ge=0, le=Decimal("999999999999.99"), max_digits=14, decimal_places=2),
]
CarrierName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class BidCreate(BaseModel):
    """Quote submission form (spec §5)."""

    model_config = ConfigDict(extra="forbid")

    carrier_name: CarrierName
    freight_charges: Amount
    origin_charges: Amount
    destination_charges: Amount
    transit_time_days: int = Field(ge=1, le=365)
    quote_validity_until: date

    @model_validator(mode="after")
    def _positive_total(self) -> Self:
        if self.freight_charges + self.origin_charges + self.destination_charges <= 0:
            raise ValueError("The total of all charges must be greater than zero")
        return self


class BidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    carrier_name: str
    freight_charges: Decimal
    origin_charges: Decimal
    destination_charges: Decimal
    total_amount: Decimal
    transit_time_days: int
    quote_validity_until: date
    created_at: UtcOut


class BidHistoryItem(BidOut):
    supplier_company: str


class ExtensionOut(BaseModel):
    previous_close_at: UtcOut
    new_close_at: UtcOut
    reason: str
    capped: bool = Field(description="True if the forced close time limited this extension")


class BidResult(BaseModel):
    bid: BidOut
    rank: int
    total_bidders: int
    current_close_at: UtcOut
    extension: ExtensionOut | None
    replayed: bool = Field(description="True when an Idempotency-Key matched an earlier bid")
    server_time: UtcOut


class LeaderboardEntry(BaseModel):
    """One supplier's current quote. Competitors are anonymised for suppliers: their
    identity and charge breakdown are hidden, the price and rank are not."""

    rank: int
    label: str = Field(description="L1, L2, …")
    supplier_label: str = Field(description="Company name, or 'Bidder N' when anonymised")
    is_you: bool
    total_amount: Decimal
    transit_time_days: int
    bid_count: int
    last_bid_at: UtcOut
    # Visible to the buyer, and to a supplier for their own row only.
    supplier_name: str | None = None
    carrier_name: str | None = None
    freight_charges: Decimal | None = None
    origin_charges: Decimal | None = None
    destination_charges: Decimal | None = None
    quote_validity_until: date | None = None


class Leaderboard(BaseModel):
    status: RfqStatus
    currency: str
    current_close_at: UtcOut
    forced_close_at: UtcOut
    extension_count: int
    entries: list[LeaderboardEntry]
    my_rank: int | None = Field(description="Your rank, for suppliers who have bid")
    my_current_total: Decimal | None = None
    server_time: UtcOut


class EventOut(BaseModel):
    id: int
    type: str
    created_at: UtcOut
    actor: str | None
    payload: dict[str, Any]


class EventPage(BaseModel):
    items: list[EventOut]
    next_before_id: int | None = Field(description="Pass as before_id for older events")
    server_time: UtcOut
