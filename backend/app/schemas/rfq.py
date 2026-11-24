import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.rfq import RfqStatus, TriggerType
from app.schemas.common import NormalizedEmail, UtcDatetime, UtcOut

RfqName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Currency = Literal["INR", "USD", "EUR", "GBP", "AED", "SGD"]
MAX_INVITES_PER_REQUEST = 50


class AuctionConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_window_minutes: int = Field(ge=1, le=1440, description="X: monitor the last X minutes")
    extension_minutes: int = Field(ge=1, le=1440, description="Y: extend the close by Y minutes")
    trigger_type: TriggerType


class AuctionConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trigger_window_minutes: int
    extension_minutes: int
    trigger_type: TriggerType


def _unique_emails(emails: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for e in emails:
        seen.setdefault(e, None)
    return list(seen)


class RfqCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RfqName
    bid_start_at: UtcDatetime
    bid_close_at: UtcDatetime
    forced_close_at: UtcDatetime
    pickup_date: date
    currency: Currency = "INR"
    is_british_auction: bool = True
    auction_config: AuctionConfigIn | None = None
    supplier_emails: list[NormalizedEmail] = Field(
        default_factory=list, max_length=MAX_INVITES_PER_REQUEST
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.is_british_auction and self.auction_config is None:
            raise ValueError("auction_config is required when is_british_auction is true")
        if not self.is_british_auction and self.auction_config is not None:
            raise ValueError("auction_config must be omitted when is_british_auction is false")
        self.supplier_emails = _unique_emails(self.supplier_emails)
        return self


class RfqUpdate(BaseModel):
    """Partial update; only allowed while the RFQ is SCHEDULED. Send If-Match: <version>."""

    model_config = ConfigDict(extra="forbid")

    name: RfqName | None = None
    bid_start_at: UtcDatetime | None = None
    bid_close_at: UtcDatetime | None = None
    forced_close_at: UtcDatetime | None = None
    pickup_date: date | None = None
    currency: Currency | None = None
    is_british_auction: bool | None = None
    auction_config: AuctionConfigIn | None = None


class InvitationsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emails: list[NormalizedEmail] = Field(min_length=1, max_length=MAX_INVITES_PER_REQUEST)

    @model_validator(mode="after")
    def _dedupe(self) -> Self:
        self.emails = _unique_emails(self.emails)
        return self


class InvitationOut(BaseModel):
    email: str
    status: Literal["JOINED", "PENDING_ACCOUNT"]
    supplier_name: str | None
    supplier_company: str | None
    invited_at: UtcOut
    last_notified_at: UtcOut | None


class BuyerOut(BaseModel):
    full_name: str
    company_name: str


class RfqSummary(BaseModel):
    """One row of the auction listing page (spec §8)."""

    id: uuid.UUID
    reference_id: str
    name: str
    buyer_company: str
    status: RfqStatus
    is_british_auction: bool
    currency: str
    current_lowest_bid: Decimal | None = Field(description="Populated from Phase 3")
    bid_start_at: UtcOut
    bid_close_at: UtcOut
    current_close_at: UtcOut
    forced_close_at: UtcOut
    extension_count: int
    invited_count: int


class RfqPermissions(BaseModel):
    can_edit: bool
    can_cancel: bool
    can_invite: bool


class RfqDetail(RfqSummary):
    pickup_date: date
    auction_config: AuctionConfigOut | None
    buyer: BuyerOut
    version: int
    created_at: UtcOut
    updated_at: UtcOut
    invitations: list[InvitationOut] | None = Field(description="Buyer only")
    permissions: RfqPermissions
    server_time: UtcOut


class RfqCreated(RfqDetail):
    pass
