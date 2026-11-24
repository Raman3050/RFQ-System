"""Inviting suppliers to RFQs. Suppliers are invite-only (no public sign-up).

- Email belongs to an existing supplier  → attach them to the RFQ and notify them.
- Email has no account                   → attach the email to the RFQ and send a
                                            one-time sign-up link (account invite).
- Email belongs to a buyer/admin         → rejected.

Returns the emails to send; the caller sends them *after* committing.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.core.security import generate_refresh_token as generate_opaque_token
from app.core.security import hash_refresh_token as hash_token
from app.email import templates
from app.email.sender import OutgoingEmail
from app.models.auction_event import EventType
from app.models.invitation import RfqInvitation, SupplierInvite
from app.models.rfq import Rfq
from app.models.user import User, UserRole
from app.repositories.event_repo import EventRepository
from app.repositories.invitation_repo import InvitationRepository
from app.repositories.user_repo import UserRepository


class InvitationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.invitations = InvitationRepository(session)
        self.events = EventRepository(session)

    async def invite(
        self, rfq: Rfq, buyer: User, emails: list[str], *, field: str = "supplier_emails"
    ) -> tuple[list[str], list[OutgoingEmail]]:
        """Returns (newly invited emails, messages to send). Already-invited emails are
        skipped silently, so the call is idempotent."""
        if not emails:
            return [], []

        accounts = await self.users.get_by_emails(emails)
        errors = [
            {
                "loc": ["body", field, i],
                "msg": f"{email} belongs to a buyer account and cannot be invited as a supplier",
                "type": "invitee_not_supplier",
            }
            for i, email in enumerate(emails)
            if (u := accounts.get(email)) is not None and u.role != UserRole.SUPPLIER
        ]
        if errors:
            raise DomainValidationError(errors, "Some emails cannot be invited")

        already = await self.invitations.emails_for(rfq.id)
        new_emails = [e for e in emails if e not in already]
        messages: list[OutgoingEmail] = []

        for email in new_emails:
            supplier = accounts.get(email)
            self.invitations.add(
                RfqInvitation(
                    rfq_id=rfq.id,
                    invitee_email=email,
                    supplier_id=supplier.id if supplier else None,
                    invited_by=buyer.id,
                    last_notified_at=func.now(),
                )
            )
            messages.append(await self._message_for(rfq, buyer, email, supplier))
            self.events.record(
                rfq.id,
                EventType.SUPPLIER_INVITED,
                actor_id=buyer.id,
                payload={"email": email, "has_account": supplier is not None},
            )

        await self._flush_or_conflict()
        return new_emails, messages

    async def resend(self, rfq: Rfq, buyer: User, email: str) -> OutgoingEmail:
        invitation = await self.invitations.get(rfq.id, email)
        if invitation is None:
            raise NotFoundError("This email has not been invited", code="INVITATION_NOT_FOUND")
        supplier = await self.users.get(invitation.supplier_id) if invitation.supplier_id else None
        message = await self._message_for(rfq, buyer, email, supplier)
        invitation.last_notified_at = func.now()
        await self._flush_or_conflict()
        return message

    async def _message_for(
        self, rfq: Rfq, buyer: User, email: str, supplier: User | None
    ) -> OutgoingEmail:
        base = self.settings.frontend_base_url.rstrip("/")
        if supplier is not None:
            return templates.rfq_invitation(
                to=email,
                buyer_company=buyer.company_name,
                rfq_reference=rfq.reference_id,
                rfq_name=rfq.name,
                bid_start_at=rfq.bid_start_at,
                link=f"{base}/auctions/{rfq.id}",
            )
        token, expires_at = await self._issue_account_invite(email, buyer)
        return templates.supplier_account_invite(
            to=email,
            buyer_name=buyer.full_name,
            buyer_company=buyer.company_name,
            rfq_reference=rfq.reference_id,
            rfq_name=rfq.name,
            bid_start_at=rfq.bid_start_at,
            link=f"{base}/accept-invite?token={token}",
            expires_at=expires_at,
        )

    async def _issue_account_invite(self, email: str, buyer: User) -> tuple[str, datetime]:
        """Creates the pending sign-up invite for `email`, or rotates its token (which
        invalidates any link sent earlier) and extends its expiry."""
        token = generate_opaque_token()
        expires_at = datetime.now(UTC) + timedelta(days=self.settings.supplier_invite_ttl_days)
        pending = await self.invitations.pending_invite_for_update(email)
        if pending is None:
            await self.invitations.add_invite(
                SupplierInvite(
                    email=email,
                    token_hash=hash_token(token),
                    invited_by=buyer.id,
                    expires_at=expires_at,
                )
            )
        else:
            pending.token_hash = hash_token(token)
            pending.expires_at = expires_at
            pending.invited_by = buyer.id
        return token, expires_at

    async def _flush_or_conflict(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:  # concurrent invite of the same email
            await self.session.rollback()
            raise ConflictError(
                "Another invitation for this email was just created. Please retry.",
                code="INVITATION_CONFLICT",
            ) from exc
