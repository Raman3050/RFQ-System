import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid import Bid
from app.models.invitation import RfqInvitation, SupplierInvite
from app.models.user import User


@dataclass(frozen=True, slots=True)
class InvitationRow:
    invitation: RfqInvitation
    supplier_name: str | None
    supplier_company: str | None
    has_bid: bool


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------------------------------------------------------- rfq invitations

    async def get(self, rfq_id: uuid.UUID, email: str) -> RfqInvitation | None:
        return await self.session.get(RfqInvitation, (rfq_id, email))

    async def emails_for(self, rfq_id: uuid.UUID) -> set[str]:
        rows = await self.session.execute(
            select(RfqInvitation.invitee_email).where(RfqInvitation.rfq_id == rfq_id)
        )
        return {e.lower() for e in rows.scalars()}

    async def list_for_rfq(self, rfq_id: uuid.UUID) -> list[InvitationRow]:
        has_bid = (
            select(Bid.id)
            .where(Bid.rfq_id == RfqInvitation.rfq_id, Bid.supplier_id == RfqInvitation.supplier_id)
            .exists()
        )
        stmt = (
            select(RfqInvitation, User.full_name, User.company_name, has_bid)
            .outerjoin(User, User.id == RfqInvitation.supplier_id)
            .where(RfqInvitation.rfq_id == rfq_id)
            .order_by(RfqInvitation.created_at, RfqInvitation.invitee_email)
            .execution_options(populate_existing=True)
        )
        return [InvitationRow(*r) for r in (await self.session.execute(stmt)).all()]

    def add(self, invitation: RfqInvitation) -> None:
        self.session.add(invitation)

    async def delete(self, invitation: RfqInvitation) -> None:
        await self.session.delete(invitation)
        await self.session.flush()

    async def email_has_other_invitations(self, email: str) -> bool:
        stmt = select(
            select(RfqInvitation.rfq_id).where(RfqInvitation.invitee_email == email).exists()
        )
        return bool((await self.session.execute(stmt)).scalar())

    async def revoke_pending_invite(self, email: str) -> bool:
        """Delete an unused sign-up link so it stops working. Returns True if one existed."""
        pending = await self.pending_invite_for_update(email)
        if pending is None:
            return False
        await self.session.delete(pending)
        await self.session.flush()
        return True

    async def link_supplier(self, email: str, supplier_id: uuid.UUID) -> list[uuid.UUID]:
        """Attach a newly created supplier account to all RFQs they were invited to."""
        result = await self.session.execute(
            update(RfqInvitation)
            .where(RfqInvitation.invitee_email == email, RfqInvitation.supplier_id.is_(None))
            .values(supplier_id=supplier_id)
            .returning(RfqInvitation.rfq_id)
        )
        return list(result.scalars())

    # ---------------------------------------------------------------- account invites

    async def pending_invite_for_update(self, email: str) -> SupplierInvite | None:
        stmt = (
            select(SupplierInvite)
            .where(SupplierInvite.email == email, SupplierInvite.accepted_at.is_(None))
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def invite_by_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> SupplierInvite | None:
        stmt = select(SupplierInvite).where(SupplierInvite.token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_invite(self, invite: SupplierInvite) -> None:
        self.session.add(invite)
        await self.session.flush()

    async def mark_accepted(self, invite: SupplierInvite, user_id: uuid.UUID) -> None:
        invite.accepted_at = func.now()
        invite.accepted_user_id = user_id
        await self.session.flush()

    @staticmethod
    def is_expired(invite: SupplierInvite, now: datetime) -> bool:
        return invite.expires_at <= now
