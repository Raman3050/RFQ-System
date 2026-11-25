"""Bidding endpoints: submit a bid, leaderboard, bid history, activity log."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status

from app.api.deps import CurrentUser, DbSession, SettingsDep, SupplierUser
from app.core import rate_limit as rl
from app.schemas.bid import BidCreate, BidHistoryItem, BidResult, EventPage, Leaderboard
from app.services.auction_view_service import AuctionViewService
from app.services.bidding_service import BiddingService

router = APIRouter(prefix="/rfqs/{rfq_id}", tags=["bidding"])


@router.post(
    "/bids",
    response_model=BidResult,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a bid (invited suppliers, while the auction is active)",
    description=(
        "Each new bid must be lower than the supplier's current bid. A bid inside the "
        "trigger window may extend the auction per its rules, never past the forced close. "
        "Send a unique Idempotency-Key header so retries can't create duplicate bids."
    ),
)
async def submit_bid(
    rfq_id: uuid.UUID,
    body: BidCreate,
    supplier: SupplierUser,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> BidResult:
    await rl.enforce(request, rl.BIDS_PER_SUPPLIER_RFQ, f"{supplier.id}:{rfq_id}")
    return await BiddingService(session, settings, request.app.state.publisher).submit(
        supplier, rfq_id, body, idempotency_key=idempotency_key
    )


@router.get(
    "/leaderboard",
    response_model=Leaderboard,
    summary="Current quotes ranked L1, L2, … (competitors anonymised for suppliers)",
)
async def leaderboard(
    rfq_id: uuid.UUID, user: CurrentUser, session: DbSession, settings: SettingsDep
) -> Leaderboard:
    return await AuctionViewService(session, settings).leaderboard(user, rfq_id)


@router.get(
    "/bids",
    response_model=list[BidHistoryItem],
    summary="Bid history (buyer: all bids; supplier: own bids)",
)
async def bid_history(
    rfq_id: uuid.UUID, user: CurrentUser, session: DbSession, settings: SettingsDep
) -> list[BidHistoryItem]:
    return await AuctionViewService(session, settings).bid_history(user, rfq_id)


@router.get("/events", response_model=EventPage, summary="Activity log, newest first")
async def activity_log(
    rfq_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EventPage:
    return await AuctionViewService(session, settings).activity(
        user, rfq_id, before_id=before_id, limit=limit
    )
