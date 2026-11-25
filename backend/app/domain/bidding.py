"""Ranking and British Auction extension rules (spec §6). Pure functions, no I/O.

Design decisions (see README):
- D1  price = freight + origin + destination charges
- D2  a supplier's latest bid is their active quote (and must be lower than the last)
- D3  ties go to the earlier bid
- D4  new close = min(current close + Y, forced close)
- D5  trigger window = [current close - X, current close): it slides with extensions
- D6  "any rank change" = a supplier who already had a rank moved
- D7  "L1 change" needs a previous L1 (the very first bid isn't a change)
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.rfq import TriggerType


@dataclass(frozen=True, slots=True)
class Quote:
    """A supplier's current (latest) bid."""

    supplier_id: uuid.UUID
    bid_id: uuid.UUID
    total: Decimal
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuctionRules:
    trigger_window: timedelta  # X
    extension: timedelta  # Y
    trigger_type: TriggerType


@dataclass(frozen=True, slots=True)
class ExtensionDecision:
    extend: bool
    reason: str
    new_close: datetime | None = None
    capped: bool = False


def rank(quotes: Sequence[Quote]) -> list[Quote]:
    """L1 first. Ties: earlier bid wins, then bid id for full determinism."""
    return sorted(quotes, key=lambda q: (q.total, q.created_at, q.bid_id))


def any_rank_changed(before: Sequence[uuid.UUID], after: Sequence[uuid.UUID]) -> bool:
    position = {s: i for i, s in enumerate(after)}
    return any(position.get(s) != i for i, s in enumerate(before))


def l1_changed(before: Sequence[uuid.UUID], after: Sequence[uuid.UUID]) -> bool:
    return bool(before) and bool(after) and before[0] != after[0]


def _minutes(td: timedelta) -> int:
    return int(td.total_seconds() // 60)


def decide_extension(
    rules: AuctionRules,
    *,
    now: datetime,
    current_close: datetime,
    forced_close: datetime,
    before: Sequence[uuid.UUID],
    after: Sequence[uuid.UUID],
) -> ExtensionDecision:
    """Should the bid that just changed the ranking from `before` to `after` (supplier
    ids in rank order) extend the auction?"""
    if current_close >= forced_close:
        return ExtensionDecision(False, "already at forced close")
    if not (current_close - rules.trigger_window <= now < current_close):
        return ExtensionDecision(False, "outside trigger window")

    x = _minutes(rules.trigger_window)
    match rules.trigger_type:
        case TriggerType.BID_RECEIVED:
            reason = f"Bid received in the last {x} minutes"
        case TriggerType.ANY_RANK_CHANGE:
            if not any_rank_changed(before, after):
                return ExtensionDecision(False, "no ranking change")
            reason = f"Supplier ranking changed in the last {x} minutes"
        case TriggerType.L1_RANK_CHANGE:
            if not l1_changed(before, after):
                return ExtensionDecision(False, "L1 unchanged")
            reason = f"New lowest bidder (L1) in the last {x} minutes"

    new_close = min(current_close + rules.extension, forced_close)
    return ExtensionDecision(True, reason, new_close=new_close, capped=new_close == forced_close)
