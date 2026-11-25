import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, status

from app.api.deps import BuyerUser, CurrentUser, DbSession, SettingsDep
from app.core.errors import AppError
from app.email.sender import EmailSender, OutgoingEmail, send_safely
from app.models.rfq import RfqStatus
from app.repositories.rfq_repo import SortKey
from app.schemas.common import NormalizedEmail, Page
from app.schemas.rfq import InvitationsCreate, RfqCreate, RfqDetail, RfqSummary, RfqUpdate
from app.services.rfq_service import RfqService

router = APIRouter(prefix="/rfqs", tags=["rfqs"])


class PreconditionRequiredError(AppError):
    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    code = "VERSION_REQUIRED"


def _parse_if_match(value: str | None, *, required: bool) -> int | None:
    if value is None:
        if required:
            raise PreconditionRequiredError("Send the RFQ version in the If-Match header")
        return None
    try:
        return int(value.strip().strip('"').removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise PreconditionRequiredError("If-Match must be the RFQ version number") from exc


def _queue(background: BackgroundTasks, request: Request, emails: list[OutgoingEmail]) -> None:
    sender: EmailSender = request.app.state.email_sender
    for message in emails:
        background.add_task(send_safely, sender, message)


@router.post(
    "",
    response_model=RfqDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create an RFQ (optionally a British Auction) and invite suppliers",
)
async def create_rfq(
    body: RfqCreate,
    buyer: BuyerUser,
    request: Request,
    background: BackgroundTasks,
    session: DbSession,
    settings: SettingsDep,
) -> RfqDetail:
    result = await RfqService(session, settings).create(buyer, body)
    _queue(background, request, result.emails)
    return result.value


@router.get("", response_model=Page[RfqSummary], summary="Auction listing (scoped to the user)")
async def list_rfqs(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    status_: Annotated[
        list[RfqStatus] | None,
        Query(alias="status", description="Filter by effective status; repeatable"),
    ] = None,
    q: Annotated[str | None, Query(max_length=100, description="Search name / reference")] = None,
    sort: SortKey = "created_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[RfqSummary]:
    return await RfqService(session, settings).list_rfqs(
        user, statuses=status_, q=q, sort=sort, page=page, size=size
    )


@router.get("/{rfq_id}", response_model=RfqDetail, summary="RFQ details")
async def get_rfq(
    rfq_id: uuid.UUID, user: CurrentUser, session: DbSession, settings: SettingsDep
) -> RfqDetail:
    return await RfqService(session, settings).get(user, rfq_id)


@router.patch(
    "/{rfq_id}",
    response_model=RfqDetail,
    summary="Edit an RFQ before bidding starts (If-Match: <version> required)",
)
async def update_rfq(
    rfq_id: uuid.UUID,
    body: RfqUpdate,
    buyer: BuyerUser,
    session: DbSession,
    settings: SettingsDep,
    if_match: Annotated[str | None, Header()] = None,
) -> RfqDetail:
    version = _parse_if_match(if_match, required=True)
    assert version is not None  # noqa: S101 - narrowed by required=True
    return await RfqService(session, settings).update(buyer, rfq_id, body, version)


@router.post("/{rfq_id}/cancel", response_model=RfqDetail, summary="Cancel before bidding starts")
async def cancel_rfq(
    rfq_id: uuid.UUID,
    buyer: BuyerUser,
    session: DbSession,
    settings: SettingsDep,
    if_match: Annotated[str | None, Header()] = None,
) -> RfqDetail:
    version = _parse_if_match(if_match, required=False)
    return await RfqService(session, settings).cancel(buyer, rfq_id, version)


@router.post(
    "/{rfq_id}/invitations",
    response_model=RfqDetail,
    summary="Invite more suppliers by email (idempotent per email)",
)
async def invite_suppliers(
    rfq_id: uuid.UUID,
    body: InvitationsCreate,
    buyer: BuyerUser,
    request: Request,
    background: BackgroundTasks,
    session: DbSession,
    settings: SettingsDep,
) -> RfqDetail:
    result = await RfqService(session, settings).invite(buyer, rfq_id, body.emails)
    _queue(background, request, result.emails)
    return result.value


@router.post(
    "/{rfq_id}/invitations/{email}/resend",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-send an invitation email (rotates any pending sign-up link)",
)
async def resend_invitation(
    rfq_id: uuid.UUID,
    email: NormalizedEmail,
    buyer: BuyerUser,
    request: Request,
    background: BackgroundTasks,
    session: DbSession,
    settings: SettingsDep,
) -> dict[str, str]:
    result = await RfqService(session, settings).resend_invitation(buyer, rfq_id, email)
    _queue(background, request, result.emails)
    return {"status": "queued"}


@router.delete(
    "/{rfq_id}/invitations/{email}",
    response_model=RfqDetail,
    summary="Remove an invite (until the auction ends, and only if the supplier hasn't bid)",
)
async def remove_invitation(
    rfq_id: uuid.UUID,
    email: NormalizedEmail,
    buyer: BuyerUser,
    session: DbSession,
    settings: SettingsDep,
) -> RfqDetail:
    return await RfqService(session, settings).remove_invitation(buyer, rfq_id, email)
