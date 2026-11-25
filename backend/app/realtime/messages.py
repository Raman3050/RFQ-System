"""Real-time message shapes.

Messages are *notifications*, not data dumps: they carry only facts every viewer of the
auction may see (status, close time, extension count, current L1 price, extension reason).
Clients then refetch their own leaderboard / activity view over REST, so per-viewer
visibility rules (anonymised competitors) are enforced in exactly one place.
"""

from datetime import UTC, datetime
from typing import Any

from app.domain.rfq_status import effective_status
from app.models.rfq import Rfq


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def auction_state(rfq: Rfq, now: datetime) -> dict[str, Any]:
    return {
        "status": effective_status(
            rfq.status,
            now=now,
            bid_start_at=rfq.bid_start_at,
            current_close_at=rfq.current_close_at,
            forced_close_at=rfq.forced_close_at,
        ).value,
        "bid_start_at": iso(rfq.bid_start_at),
        "current_close_at": iso(rfq.current_close_at),
        "forced_close_at": iso(rfq.forced_close_at),
        "extension_count": rfq.extension_count,
        "current_lowest_bid": str(rfq.current_l1_amount)
        if rfq.current_l1_amount is not None
        else None,
    }


def auction_message(
    type_: str,
    rfq: Rfq,
    *,
    seq: int | None,
    now: datetime,
    extension: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`seq` is the id of the latest activity-log entry for the RFQ: clients that see a
    gap (or a lower number) refetch instead of trusting their cache."""
    return {
        "type": type_,
        "rfq_id": str(rfq.id),
        "seq": seq,
        "server_time": iso(now),
        "auction": auction_state(rfq, now),
        "extension": extension,
    }
