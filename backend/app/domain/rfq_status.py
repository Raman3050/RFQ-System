"""Effective RFQ status: the stored status reconciled with the clock.

The lifecycle worker persists transitions, but readers must never depend on
it being on time, so every read derives the status from timestamps. Pure functions only.
"""

from datetime import datetime

from app.models.rfq import TERMINAL_STATUSES, RfqStatus


def effective_status(
    stored: RfqStatus,
    *,
    now: datetime,
    bid_start_at: datetime,
    current_close_at: datetime,
    forced_close_at: datetime,
) -> RfqStatus:
    if stored in TERMINAL_STATUSES:
        return stored
    if now < bid_start_at:
        return RfqStatus.SCHEDULED
    if now < current_close_at:
        return RfqStatus.ACTIVE
    # Ended. If extensions pushed the close all the way to the cap, it was force-closed.
    return RfqStatus.FORCE_CLOSED if current_close_at >= forced_close_at else RfqStatus.CLOSED


def is_editable(status: RfqStatus) -> bool:
    """Schedule and auction rules are frozen once bidding opens (design decision D11)."""
    return status == RfqStatus.SCHEDULED


def can_invite(status: RfqStatus) -> bool:
    return status in (RfqStatus.SCHEDULED, RfqStatus.ACTIVE)
