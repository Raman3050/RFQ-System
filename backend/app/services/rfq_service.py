"""RFQ use-cases: create, read, list, update (while scheduled), cancel."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.core.errors import PreconditionFailedError as VersionConflict
from app.core.logging import get_logger
from app.domain.rfq_rules import Schedule, validate_schedule
from app.domain.rfq_status import can_invite, effective_status, is_editable
from app.email.sender import OutgoingEmail
from app.models.auction_event import EventType
from app.models.rfq import AuctionConfig, Rfq, RfqStatus
from app.models.user import User, UserRole
from app.repositories.event_repo import EventRepository
from app.repositories.invitation_repo import InvitationRepository
from app.repositories.rfq_repo import RfqRepository, RfqRow, SortKey
from app.schemas.common import Page
from app.schemas.rfq import (
    AuctionConfigIn,
    AuctionConfigOut,
    BuyerOut,
    InvitationOut,
    RfqCreate,
    RfqDetail,
    RfqPermissions,
    RfqSummary,
    RfqUpdate,
)
from app.services.invitation_service import InvitationService

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WithEmails[T]:
    """A result plus the emails to send once the transaction has committed."""

    value: T
    emails: list[OutgoingEmail]


def _status_of(rfq: Rfq, now: datetime) -> RfqStatus:
    return effective_status(
        rfq.status,
        now=now,
        bid_start_at=rfq.bid_start_at,
        current_close_at=rfq.current_close_at,
        forced_close_at=rfq.forced_close_at,
    )


def _new_config(cfg: AuctionConfigIn) -> AuctionConfig:
    return AuctionConfig(
        trigger_window_minutes=cfg.trigger_window_minutes,
        extension_minutes=cfg.extension_minutes,
        trigger_type=cfg.trigger_type,
    )


class RfqService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.rfqs = RfqRepository(session)
        self.invitations = InvitationRepository(session)
        self.events = EventRepository(session)
        self.inviter = InvitationService(session, settings)

    # ---------------------------------------------------------------- commands

    async def create(self, buyer: User, data: RfqCreate) -> WithEmails[RfqDetail]:
        now = datetime.now(UTC)
        violations = validate_schedule(
            Schedule(data.bid_start_at, data.bid_close_at, data.forced_close_at, data.pickup_date),
            now=now,
        )
        if violations:
            raise DomainValidationError([v.as_error() for v in violations])

        seq = await self.rfqs.next_reference_number()
        rfq = Rfq(
            reference_id=f"RFQ-{data.bid_start_at.year}-{seq:06d}",
            name=data.name,
            buyer_id=buyer.id,
            is_british_auction=data.is_british_auction,
            bid_start_at=data.bid_start_at,
            bid_close_at=data.bid_close_at,
            current_close_at=data.bid_close_at,
            forced_close_at=data.forced_close_at,
            pickup_date=data.pickup_date,
            currency=data.currency,
            status=RfqStatus.SCHEDULED,
            config=_new_config(data.auction_config) if data.auction_config else None,
        )
        await self.rfqs.add(rfq)
        self.events.record(
            rfq.id,
            EventType.RFQ_CREATED,
            actor_id=buyer.id,
            payload={
                "reference_id": rfq.reference_id,
                "bid_close_at": rfq.bid_close_at.isoformat(),
                "forced_close_at": rfq.forced_close_at.isoformat(),
                "auction_config": data.auction_config.model_dump(mode="json")
                if data.auction_config
                else None,
            },
        )
        _, emails = await self.inviter.invite(rfq, buyer, data.supplier_emails)
        await self.session.commit()
        log.info("rfq_created", rfq_id=str(rfq.id), reference=rfq.reference_id)
        return WithEmails(await self.get(buyer, rfq.id), emails)

    async def update(
        self, buyer: User, rfq_id: uuid.UUID, data: RfqUpdate, expected_version: int
    ) -> RfqDetail:
        rfq = await self._owned_for_update(buyer, rfq_id)
        if rfq.version != expected_version:
            raise VersionConflict(
                "This RFQ was changed by someone else. Reload and try again.",
                extra={"current_version": rfq.version},
            )
        now = datetime.now(UTC)
        if not is_editable(_status_of(rfq, now)):
            raise ConflictError(
                "RFQs can only be edited before bidding starts", code="RFQ_NOT_EDITABLE"
            )

        changes = data.model_dump(exclude_unset=True)
        schedule = Schedule(
            data.bid_start_at or rfq.bid_start_at,
            data.bid_close_at or rfq.bid_close_at,
            data.forced_close_at or rfq.forced_close_at,
            data.pickup_date or rfq.pickup_date,
        )
        violations = validate_schedule(
            schedule, now=now, start_may_be_past="bid_start_at" not in changes
        )
        british = (
            data.is_british_auction
            if data.is_british_auction is not None
            else rfq.is_british_auction
        )
        if british and data.auction_config is None and rfq.config is None:
            violations_errors = [
                {
                    "loc": ["body", "auction_config"],
                    "msg": "Auction configuration is required for a British Auction",
                    "type": "missing",
                }
            ]
        elif not british and data.auction_config is not None:
            violations_errors = [
                {
                    "loc": ["body", "auction_config"],
                    "msg": "Remove the auction configuration or enable British Auction",
                    "type": "unexpected",
                }
            ]
        else:
            violations_errors = []
        errors = [v.as_error() for v in violations] + violations_errors
        if errors:
            raise DomainValidationError(errors)

        if data.name is not None:
            rfq.name = data.name
        if data.currency is not None:
            rfq.currency = data.currency
        rfq.bid_start_at = schedule.bid_start_at
        rfq.bid_close_at = schedule.bid_close_at
        rfq.current_close_at = schedule.bid_close_at  # no extensions before start
        rfq.forced_close_at = schedule.forced_close_at
        rfq.pickup_date = schedule.pickup_date
        rfq.is_british_auction = british
        if not british:
            rfq.config = None
        elif data.auction_config is not None:
            if rfq.config is None:
                rfq.config = _new_config(data.auction_config)
            else:
                rfq.config.trigger_window_minutes = data.auction_config.trigger_window_minutes
                rfq.config.extension_minutes = data.auction_config.extension_minutes
                rfq.config.trigger_type = data.auction_config.trigger_type

        self.events.record(
            rfq.id,
            EventType.RFQ_UPDATED,
            actor_id=buyer.id,
            payload={"changed": sorted(changes)},
        )
        await self.session.commit()
        return await self.get(buyer, rfq.id)

    async def cancel(
        self, buyer: User, rfq_id: uuid.UUID, expected_version: int | None
    ) -> RfqDetail:
        rfq = await self._owned_for_update(buyer, rfq_id)
        if expected_version is not None and rfq.version != expected_version:
            raise VersionConflict(
                "This RFQ was changed by someone else. Reload and try again.",
                extra={"current_version": rfq.version},
            )
        if _status_of(rfq, datetime.now(UTC)) != RfqStatus.SCHEDULED:
            raise ConflictError(
                "Only RFQs that have not started can be cancelled", code="RFQ_NOT_CANCELLABLE"
            )
        rfq.status = RfqStatus.CANCELLED
        rfq.cancelled_at = func.now()
        self.events.record(rfq.id, EventType.RFQ_CANCELLED, actor_id=buyer.id)
        await self.session.commit()
        return await self.get(buyer, rfq.id)

    async def invite(
        self, buyer: User, rfq_id: uuid.UUID, emails: list[str]
    ) -> WithEmails[RfqDetail]:
        rfq = await self._owned_for_update(buyer, rfq_id)
        if not can_invite(_status_of(rfq, datetime.now(UTC))):
            raise ConflictError(
                "Suppliers can only be invited before the auction ends",
                code="RFQ_NOT_INVITABLE",
            )
        _, messages = await self.inviter.invite(rfq, buyer, emails, field="emails")
        await self.session.commit()
        return WithEmails(await self.get(buyer, rfq.id), messages)

    async def resend_invitation(
        self, buyer: User, rfq_id: uuid.UUID, email: str
    ) -> WithEmails[None]:
        rfq = await self._owned_for_update(buyer, rfq_id)
        if not can_invite(_status_of(rfq, datetime.now(UTC))):
            raise ConflictError("This auction has ended", code="RFQ_NOT_INVITABLE")
        message = await self.inviter.resend(rfq, buyer, email)
        await self.session.commit()
        return WithEmails(None, [message])

    # ---------------------------------------------------------------- queries

    async def get(self, user: User, rfq_id: uuid.UUID) -> RfqDetail:
        row = await self.rfqs.get_visible(rfq_id, user)
        if row is None:
            raise NotFoundError("RFQ not found", code="RFQ_NOT_FOUND")
        now = datetime.now(UTC)
        is_owner = user.role == UserRole.ADMIN or row.rfq.buyer_id == user.id
        invitations = await self._invitations(row.rfq.id) if is_owner else None
        return self._detail(row, now, invitations, is_owner)

    async def list_rfqs(
        self,
        user: User,
        *,
        statuses: list[RfqStatus] | None,
        q: str | None,
        sort: SortKey,
        page: int,
        size: int,
    ) -> Page[RfqSummary]:
        rows, total = await self.rfqs.list_visible(
            user, statuses=statuses, q=q, sort=sort, page=page, size=size
        )
        now = datetime.now(UTC)
        return Page[RfqSummary](
            items=[RfqSummary(**self._summary_fields(r, now)) for r in rows],
            total=total,
            page=page,
            size=size,
            server_time=now,
        )

    # ---------------------------------------------------------------- helpers

    async def _owned_for_update(self, buyer: User, rfq_id: uuid.UUID) -> Rfq:
        rfq = await self.rfqs.get_for_update(rfq_id)
        # Not-owned looks exactly like not-found: don't reveal other buyers' RFQs.
        if rfq is None or (buyer.role != UserRole.ADMIN and rfq.buyer_id != buyer.id):
            raise NotFoundError("RFQ not found", code="RFQ_NOT_FOUND")
        return rfq

    async def _invitations(self, rfq_id: uuid.UUID) -> list[InvitationOut]:
        rows = await self.invitations.list_for_rfq(rfq_id)
        return [
            InvitationOut(
                email=r.invitation.invitee_email,
                status="JOINED" if r.invitation.supplier_id else "PENDING_ACCOUNT",
                supplier_name=r.supplier_name,
                supplier_company=r.supplier_company,
                invited_at=r.invitation.created_at,
                last_notified_at=r.invitation.last_notified_at,
            )
            for r in rows
        ]

    @staticmethod
    def _summary_fields(row: RfqRow, now: datetime) -> dict[str, Any]:
        rfq = row.rfq
        return {
            "id": rfq.id,
            "reference_id": rfq.reference_id,
            "name": rfq.name,
            "buyer_company": row.buyer_company,
            "status": _status_of(rfq, now),
            "is_british_auction": rfq.is_british_auction,
            "currency": rfq.currency,
            "current_lowest_bid": None,
            "bid_start_at": rfq.bid_start_at,
            "bid_close_at": rfq.bid_close_at,
            "current_close_at": rfq.current_close_at,
            "forced_close_at": rfq.forced_close_at,
            "extension_count": rfq.extension_count,
            "invited_count": row.invited_count,
        }

    def _detail(
        self,
        row: RfqRow,
        now: datetime,
        invitations: list[InvitationOut] | None,
        is_owner: bool,
    ) -> RfqDetail:
        rfq = row.rfq
        status = _status_of(rfq, now)
        return RfqDetail(
            **self._summary_fields(row, now),
            pickup_date=rfq.pickup_date,
            auction_config=AuctionConfigOut.model_validate(rfq.config) if rfq.config else None,
            buyer=BuyerOut(full_name=row.buyer_full_name, company_name=row.buyer_company),
            version=rfq.version,
            created_at=rfq.created_at,
            updated_at=rfq.updated_at,
            invitations=invitations,
            permissions=RfqPermissions(
                can_edit=is_owner and is_editable(status),
                can_cancel=is_owner and status == RfqStatus.SCHEDULED,
                can_invite=is_owner and can_invite(status),
            ),
            server_time=now,
        )
