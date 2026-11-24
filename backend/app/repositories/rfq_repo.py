import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import ColumnElement, Row, Select, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.invitation import RfqInvitation
from app.models.rfq import Rfq, RfqStatus
from app.models.user import User, UserRole

SortKey = Literal["created_desc", "close_asc", "start_asc", "start_desc"]

_now = func.now()
_terminal = [RfqStatus.CLOSED, RfqStatus.FORCE_CLOSED, RfqStatus.CANCELLED]


def effective_status_clause(status: RfqStatus) -> ColumnElement[bool]:
    """SQL twin of app.domain.rfq_status.effective_status, for filtering lists."""
    live = Rfq.status.not_in(_terminal)
    match status:
        case RfqStatus.SCHEDULED:
            return and_(live, Rfq.bid_start_at > _now)
        case RfqStatus.ACTIVE:
            return and_(live, Rfq.bid_start_at <= _now, Rfq.current_close_at > _now)
        case RfqStatus.CLOSED:
            return or_(
                Rfq.status == RfqStatus.CLOSED,
                and_(
                    live,
                    Rfq.current_close_at <= _now,
                    Rfq.current_close_at < Rfq.forced_close_at,
                ),
            )
        case RfqStatus.FORCE_CLOSED:
            return or_(
                Rfq.status == RfqStatus.FORCE_CLOSED,
                and_(
                    live,
                    Rfq.current_close_at <= _now,
                    Rfq.current_close_at >= Rfq.forced_close_at,
                ),
            )
        case RfqStatus.CANCELLED:
            return Rfq.status == RfqStatus.CANCELLED


RowSelect = Select[tuple[Rfq, str, str, int]]


@dataclass(frozen=True, slots=True)
class RfqRow:
    rfq: Rfq
    buyer_full_name: str
    buyer_company: str
    invited_count: int


class RfqRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_reference_number(self) -> int:
        return int(
            (await self.session.execute(text("SELECT nextval('rfq_reference_seq')"))).scalar_one()
        )

    async def add(self, rfq: Rfq) -> Rfq:
        self.session.add(rfq)
        await self.session.flush()
        return rfq

    def _base(self) -> RowSelect:
        buyer = aliased(User)
        invited = (
            select(func.count())
            .where(RfqInvitation.rfq_id == Rfq.id)
            .correlate(Rfq)
            .scalar_subquery()
        )
        return select(Rfq, buyer.full_name, buyer.company_name, invited).join(
            buyer, buyer.id == Rfq.buyer_id
        )

    @staticmethod
    def _visible_to(stmt: RowSelect, user: User) -> RowSelect:
        match user.role:
            case UserRole.ADMIN:
                return stmt
            case UserRole.BUYER:
                return stmt.where(Rfq.buyer_id == user.id)
            case UserRole.SUPPLIER:
                return stmt.where(
                    select(RfqInvitation.rfq_id)
                    .where(RfqInvitation.rfq_id == Rfq.id, RfqInvitation.supplier_id == user.id)
                    .exists()
                )

    async def get_visible(self, rfq_id: uuid.UUID, user: User) -> RfqRow | None:
        stmt = self._visible_to(self._base().where(Rfq.id == rfq_id), user).execution_options(
            populate_existing=True  # always reflect the latest committed state
        )
        row = (await self.session.execute(stmt)).unique().first()
        return self._row(row) if row else None

    async def get_for_update(self, rfq_id: uuid.UUID) -> Rfq | None:
        stmt = select(Rfq).where(Rfq.id == rfq_id).with_for_update(of=Rfq)
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def list_visible(
        self,
        user: User,
        *,
        statuses: list[RfqStatus] | None,
        q: str | None,
        sort: SortKey,
        page: int,
        size: int,
    ) -> tuple[list[RfqRow], int]:
        stmt = self._visible_to(self._base(), user)
        if statuses:
            stmt = stmt.where(or_(*(effective_status_clause(s) for s in statuses)))
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(or_(Rfq.name.ilike(pattern), Rfq.reference_id.ilike(pattern)))

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order = {
            "created_desc": [Rfq.created_at.desc()],
            "close_asc": [Rfq.current_close_at.asc()],
            "start_asc": [Rfq.bid_start_at.asc()],
            "start_desc": [Rfq.bid_start_at.desc()],
        }[sort]
        stmt = stmt.order_by(*order, Rfq.id).offset((page - 1) * size).limit(size)
        rows = (await self.session.execute(stmt)).unique().all()
        return [self._row(r) for r in rows], int(total)

    @staticmethod
    def _row(r: Row[Any]) -> RfqRow:
        values: tuple[Any, ...] = tuple(r)
        return RfqRow(
            rfq=values[0],
            buyer_full_name=values[1],
            buyer_company=values[2],
            invited_count=int(values[3]),
        )
